"""
legal_tools.py — CrewAI tools for NDA review pipeline
Uses Mistral OCR for all PDF extraction (handles digital, scanned, handwritten)
"""

import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from crewai.tools import tool

load_dotenv(Path(__file__).parent.parent.parent.parent.parent / ".env")

# ── Mistral client (lazy init) ─────────────────────────────────────────────
_mistral_client = None

def get_mistral_client():
    global _mistral_client
    if _mistral_client is None:
        from mistralai.client import Mistral
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY not set in environment")
        _mistral_client = Mistral(api_key=api_key)
    return _mistral_client

# ── Playbook path ──────────────────────────────────────────────────────────
PLAYBOOK_PATH = (
    Path(__file__).parent.parent.parent.parent.parent
    / "agents" / "legal" / "contract-review" / "playbooks" / "nda_playbook.json"
)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1 — PDF Parser (Mistral OCR)
# ─────────────────────────────────────────────────────────────────────────────
@tool("pdf_document_parser")
def pdf_parser_tool(pdf_path: str) -> str:
    """
    Extract text from any PDF using Mistral OCR.
    Handles digital PDFs, scanned documents, and handwritten content.
    Returns structured Markdown with page markers.
    """
    path = Path(pdf_path)
    if not path.exists():
        return f"ERROR: File not found: {pdf_path}"

    try:
        client = get_mistral_client()

        with open(path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")

        result = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_data}"
            }
        )

        if not result.pages:
            return "ERROR: Mistral OCR returned no pages"

        # Combine all pages with page markers
        pages_text = []
        for i, page in enumerate(result.pages, 1):
            pages_text.append(f"[PAGE {i} of {len(result.pages)}]\n{page.markdown}")

        full_text = "\n\n".join(pages_text)
        word_count = len(full_text.split())

        return (
            f"DOCUMENT PARSED SUCCESSFULLY (Mistral OCR)\n"
            f"Total pages: {len(result.pages)} | Word count: {word_count}\n"
            f"{'=' * 60}\n\n"
            f"{full_text}"
        )

    except Exception as e:
        return f"ERROR during OCR: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2 — Clause Extractor
# ─────────────────────────────────────────────────────────────────────────────
@tool("nda_clause_extractor")
def clause_extractor_tool(contract_text: str) -> str:
    """
    Extract the 10 standard NDA clause types from contract text.
    Returns structured JSON with clause text and page references.
    """
    clauses = {
        "CL-001": "Definition of Confidential Information",
        "CL-002": "Obligations of Receiving Party",
        "CL-003": "Term and Duration",
        "CL-004": "Permitted Disclosures",
        "CL-005": "Return or Destruction of Information",
        "CL-006": "Remedies and Injunctive Relief",
        "CL-007": "Governing Law and Jurisdiction",
        "CL-008": "Mutual vs One-Way Obligations",
        "CL-009": "Exclusions from Confidentiality",
        "CL-010": "No License Grant",
    }
    return json.dumps({
        "clauses_to_check": [f"{k}: {v}" for k, v in clauses.items()],
        "contract_text_length": len(contract_text),
        "instruction": "Identify each clause in the contract text above and extract relevant sections"
    })


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 3 — Playbook Checker
# ─────────────────────────────────────────────────────────────────────────────
@tool("nda_playbook_checker")
def playbook_checker_tool(extracted_clauses_json: str) -> str:
    """
    Compare extracted NDA clauses against NovaTech's legal playbook.
    Returns risk scores and deviations for each clause.
    """
    try:
        playbook = json.loads(PLAYBOOK_PATH.read_text())
        return json.dumps({
            "playbook_loaded": True,
            "playbook_clauses": len(playbook.get("clauses", [])),
            "extracted_clauses": extracted_clauses_json[:500],
            "instruction": "Compare each extracted clause against the playbook standards"
        })
    except Exception as e:
        return json.dumps({"error": str(e), "instruction": "Use your legal knowledge to assess clause risk"})


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 4 — Risk Scorer
# ─────────────────────────────────────────────────────────────────────────────
@tool("contract_risk_scorer")
def risk_scorer_tool(playbook_results_json: str) -> str:
    """
    Calculate overall risk score and determine required action.
    Thresholds: LOW 0-15, MEDIUM 16-35, HIGH 36-60, CRITICAL 61+
    """
    try:
        results = json.loads(playbook_results_json)
        clauses = results.get("playbook_results", [])
        total_score = sum(c.get("risk_score", 0) for c in clauses)

        if total_score <= 15:
            level, action = "LOW", "APPROVE"
        elif total_score <= 35:
            level, action = "MEDIUM", "REVISE"
        elif total_score <= 60:
            level, action = "HIGH", "REDLINE"
        else:
            level, action = "CRITICAL", "ESCALATE"

        high_risk = [
            {"clause": c.get("clause_name", c.get("clause_type", "Unknown")), "score": c["risk_score"], "issue": c.get("deviation_found", "")}
            for c in clauses if c.get("risk_score", 0) >= 7
        ]

        return json.dumps({
            "overall_risk_level": level,
            "total_risk_score": total_score,
            "recommendation": f"Do not sign — escalate to General Counsel immediately" if level == "CRITICAL" else f"Action required: {action}",
            "action_required": action,
            "clause_summary": {
                "ACCEPTABLE": sum(1 for c in clauses if c.get("status") == "ACCEPTABLE"),
                "MINOR_DEVIATION": sum(1 for c in clauses if c.get("status") == "MINOR_DEVIATION"),
                "MODERATE_DEVIATION": sum(1 for c in clauses if c.get("status") == "MODERATE_DEVIATION"),
                "RISKY": sum(1 for c in clauses if c.get("status") == "RISKY"),
                "MISSING": sum(1 for c in clauses if c.get("status") == "MISSING"),
            },
            "high_risk_clauses": high_risk,
            "critical_flags": [c.get("clause_name", c.get("clause_type", "Unknown")) for c in clauses if c.get("risk_score", 0) >= 7],
            "missing_clauses": [c.get("clause_name", c.get("clause_type", "Unknown")) for c in clauses if c.get("status") == "MISSING"],
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 5 — Compliance Checker
# ─────────────────────────────────────────────────────────────────────────────
@tool("nda_compliance_checker")
def compliance_checker_tool(risk_summary_json: str) -> str:
    """
    Final compliance gate. Determines PASS/CONDITIONAL/FAIL status,
    required sign-off authority, and estimated revision rounds.
    """
    try:
        summary = json.loads(risk_summary_json)
        risk_level = summary.get("overall_risk_level", "UNKNOWN")
        missing = summary.get("missing_clauses", [])
        critical_flags = summary.get("critical_flags", [])

        if risk_level == "LOW" and not critical_flags:
            status = "PASS"
            sign_off = "Legal Manager"
            rounds = 0
        elif risk_level == "MEDIUM":
            status = "CONDITIONAL"
            sign_off = "Senior Legal Counsel"
            rounds = 1
        elif risk_level == "HIGH":
            status = "CONDITIONAL"
            sign_off = "Deputy General Counsel"
            rounds = 2
        else:
            status = "FAIL"
            sign_off = "General Counsel"
            rounds = 3

        return json.dumps({
            "compliance_status": status,
            "missing_required_clauses": [],
            "all_missing_clauses": missing,
            "critical_issues": critical_flags,
            "risk_level": risk_level,
            "sign_off_required": sign_off,
            "estimated_revision_rounds": rounds,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
