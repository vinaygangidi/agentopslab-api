"""
NDA Review Crew
================
A CrewAI multi-agent system that reviews NDA contracts against
NovaTech Solutions' legal playbook and produces a legal memo.

Agents:
  1. Document Parser      — extracts text from PDF
  2. Clause Extractor     — identifies all NDA clauses
  3. Playbook Reviewer    — compares clauses to playbook
  4. Risk Scorer          — calculates overall risk score
  5. Compliance Officer   — final compliance gate
  6. Report Writer        — produces JSON + PDF memo

Usage:
  python crew.py --contract path/to/contract.pdf
  python crew.py --all   (reviews all NDAs in test-data/legal/ndas/)
"""

import os
import sys
import json
import argparse
from pathlib import Path
from crewai import Agent, Task, Crew, Process

# Add parent dirs to path so tools can import cleanly
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from tools.legal_tools import (
    pdf_parser_tool,
    clause_extractor_tool,
    playbook_checker_tool,
    risk_scorer_tool,
    compliance_checker_tool,
)
from report_writer import write_report

# Load env and configure Claude
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent.parent / ".env")
CLAUDE = "anthropic/claude-sonnet-4-20250514"

# ── Resolve paths ─────────────────────────────────────────────
CREW_DIR     = Path(__file__).parent
OUTPUT_DIR   = CREW_DIR / "output"
NDA_DIR      = CREW_DIR.parent.parent.parent / "test-data" / "legal" / "ndas"

OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────
# AGENTS
# ─────────────────────────────────────────────────────────────

def build_agents():
    """Instantiate all six crew agents."""

    document_parser = Agent(
        role="Legal Document Parser",
        goal=(
            "Extract the complete text from an NDA PDF contract, "
            "preserving page numbers so clauses can be precisely located later."
        ),
        backstory=(
            "You are a document intelligence specialist with deep experience "
            "processing legal contracts. You ensure that no text is lost during "
            "extraction and that page references are maintained for audit purposes."
        ),
        tools=[pdf_parser_tool],
        verbose=True,
        allow_delegation=False,
        llm=CLAUDE,
    )

    clause_extractor = Agent(
        role="NDA Clause Extraction Specialist",
        goal=(
            "Identify and extract all ten key NDA clause types from the contract text. "
            "Note the page where each clause appears. Flag any clauses that cannot be found."
        ),
        backstory=(
            "You are a paralegal specialist who has reviewed thousands of NDAs. "
            "You have an expert eye for identifying clause types even when they are "
            "buried deep in a document or use non-standard headings. You never miss "
            "a clause and always note exactly where in the document it appears."
        ),
        tools=[clause_extractor_tool],
        verbose=True,
        allow_delegation=False,
        llm=CLAUDE,
    )

    playbook_reviewer = Agent(
        role="Legal Playbook Reviewer",
        goal=(
            "Compare every extracted NDA clause against NovaTech's legal playbook. "
            "Identify acceptable positions, deviations, and risky language. "
            "Assign a risk score to each clause based on the playbook thresholds."
        ),
        backstory=(
            "You are NovaTech's in-house counsel responsible for ensuring all "
            "incoming contracts meet company standards. You know the playbook "
            "inside out and can immediately spot when a counterparty is trying "
            "to sneak in unfavorable terms. You are thorough and never approve "
            "a contract without checking every clause."
        ),
        tools=[playbook_checker_tool],
        verbose=True,
        allow_delegation=False,
        llm=CLAUDE,
    )

    risk_scorer = Agent(
        role="Contract Risk Scoring Analyst",
        goal=(
            "Calculate the total risk score for the contract and determine the "
            "overall risk level (LOW, MEDIUM, HIGH, or CRITICAL). "
            "Identify the highest-risk clauses and determine what action is required."
        ),
        backstory=(
            "You are a risk analyst specializing in contract risk quantification. "
            "You translate legal findings into clear numerical risk scores that "
            "executives and legal teams can act on. Your risk assessments are "
            "trusted by the General Counsel to prioritize legal review resources."
        ),
        tools=[risk_scorer_tool],
        verbose=True,
        allow_delegation=False,
        llm=CLAUDE,
    )

    compliance_officer = Agent(
        role="Legal Compliance Officer",
        goal=(
            "Perform a final compliance gate check. Verify that all required clauses "
            "are present, determine sign-off authority needed, and issue a final "
            "compliance verdict of PASS, CONDITIONAL, or FAIL."
        ),
        backstory=(
            "You are the final gatekeeper before any contract is approved. You have "
            "stopped many contracts that slipped past initial review. Your compliance "
            "verdicts are definitive — no contract gets executed without your sign-off. "
            "You are firm, precise, and never let commercial pressure override legal risk."
        ),
        tools=[compliance_checker_tool],
        verbose=True,
        allow_delegation=False,
        llm=CLAUDE,
    )

    return {
        "parser":     document_parser,
        "extractor":  clause_extractor,
        "reviewer":   playbook_reviewer,
        "scorer":     risk_scorer,
        "compliance": compliance_officer,
    }


# ─────────────────────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────────────────────

def build_tasks(agents, pdf_path: str):
    """Build the sequential task chain for a single contract review."""

    task_parse = Task(
        description=(
            f"Parse the NDA contract PDF at this path: {pdf_path}\n"
            "Extract all text preserving page numbers. "
            "Return the full extracted text with page markers."
        ),
        expected_output=(
            "Complete contract text with [PAGE X of Y] markers before each page's content. "
            "Include a summary line showing total pages and word count."
        ),
        agent=agents["parser"],
    )

    task_extract = Task(
        description=(
            "Using the extracted contract text from the previous task, "
            "identify and extract all ten NDA clause types:\n"
            "CL-001 Definition of Confidential Information\n"
            "CL-002 Obligations of Receiving Party\n"
            "CL-003 Term and Duration\n"
            "CL-004 Permitted Disclosures\n"
            "CL-005 Return or Destruction of Information\n"
            "CL-006 Remedies and Injunctive Relief\n"
            "CL-007 Governing Law and Jurisdiction\n"
            "CL-008 Mutual vs One-Way Obligations\n"
            "CL-009 Exclusions from Confidentiality\n"
            "CL-010 No License Grant\n\n"
            "For each clause, note the page number where it was found. "
            "If a clause is not found, mark it as missing."
        ),
        expected_output=(
            "A JSON object with clauses_found array, total_found count, "
            "total_missing count, and a brief document_summary."
        ),
        agent=agents["extractor"],
        context=[task_parse],
    )

    task_review = Task(
        description=(
            "Using the extracted clauses from the previous task, "
            "compare each clause against NovaTech's NDA playbook. "
            "For each clause determine: "
            "(1) Is the position acceptable per the playbook? "
            "(2) Are there any risky positions or missing protections? "
            "(3) What is the risk score (0-10) for this clause? "
            "Pay special attention to: perpetual obligations, foreign jurisdiction, "
            "asymmetric remedies, retroactive confidentiality, and auto-renewal clauses."
        ),
        expected_output=(
            "A JSON object with playbook_results array containing status, risk_score, "
            "deviation_found, and recommendation for each of the 10 clauses. "
            "Also include total_risk_score, critical_flags list, and missing_clauses list."
        ),
        agent=agents["reviewer"],
        context=[task_extract],
    )

    task_score = Task(
        description=(
            "Using the playbook review results from the previous task, "
            "calculate the final risk assessment. "
            "Apply the risk thresholds: LOW (0-15), MEDIUM (16-35), HIGH (36-60), CRITICAL (61+). "
            "Identify the top high-risk clauses and determine what action is required: "
            "APPROVE, REVISE, REDLINE, or ESCALATE."
        ),
        expected_output=(
            "A JSON object with overall_risk_level, total_risk_score, recommendation, "
            "action_required, clause_summary counts, and high_risk_clauses list."
        ),
        agent=agents["scorer"],
        context=[task_review],
    )

    task_comply = Task(
        description=(
            "Using the risk assessment from the previous task, "
            "perform a final compliance gate check. "
            "Verify presence of the five mandatory clauses. "
            "Determine the compliance status (PASS / CONDITIONAL / FAIL), "
            "required sign-off authority, and estimated revision rounds needed."
        ),
        expected_output=(
            "A JSON object with compliance_status, missing_required_clauses, "
            "all_missing_clauses, critical_issues, sign_off_required, "
            "and estimated_revision_rounds."
        ),
        agent=agents["compliance"],
        context=[task_score],
    )

    return [task_parse, task_extract, task_review, task_score, task_comply]


# ─────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────

def review_contract(pdf_path: str) -> dict:
    """
    Run the full NDA review crew on a single contract.
    Returns paths to the JSON and PDF output files.
    """
    pdf_path = str(Path(pdf_path).resolve())
    filename  = Path(pdf_path).name

    print(f"\n{'='*60}")
    print(f"NDA REVIEW CREW — Starting review")
    print(f"Contract: {filename}")
    print(f"{'='*60}\n")

    agents = build_agents()
    tasks  = build_tasks(agents, pdf_path)

    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )

    # Run the crew
    result = crew.kickoff()

    # Collect task outputs
    outputs = [t.output.raw if hasattr(t, 'output') and t.output else "" for t in tasks]

    parse_out      = outputs[0] if len(outputs) > 0 else ""
    extract_out    = outputs[1] if len(outputs) > 1 else "{}"
    playbook_out   = outputs[2] if len(outputs) > 2 else "{}"
    risk_out       = outputs[3] if len(outputs) > 3 else "{}"
    compliance_out = outputs[4] if len(outputs) > 4 else "{}"

    # Generate reports
    report_paths = write_report(
        contract_filename=filename,
        contract_text_excerpt=parse_out[:500],
        clauses_json=extract_out,
        playbook_json=playbook_out,
        risk_json=risk_out,
        compliance_json=compliance_out,
        output_dir=str(OUTPUT_DIR),
    )

    print(f"\n{'='*60}")
    print(f"REVIEW COMPLETE: {filename}")
    print(f"  JSON report: {report_paths['json_report']}")
    print(f"  PDF memo:    {report_paths['pdf_memo']}")
    print(f"{'='*60}\n")

    return report_paths


def review_all_ndas():
    """Review all three synthesized NDAs in test-data/legal/ndas/."""
    if not NDA_DIR.exists():
        print(f"ERROR: NDA directory not found at {NDA_DIR}")
        return

    pdfs = sorted(NDA_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found in {NDA_DIR}")
        return

    print(f"\nFound {len(pdfs)} NDA contracts to review:\n")
    for p in pdfs:
        print(f"  {p.name}")

    all_results = []
    for pdf in pdfs:
        result = review_contract(str(pdf))
        all_results.append(result)

    print(f"\n{'='*60}")
    print("ALL REVIEWS COMPLETE")
    print(f"{'='*60}")
    for r in all_results:
        print(f"  PDF:  {Path(r['pdf_memo']).name}")
        print(f"  JSON: {Path(r['json_report']).name}")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NDA Review Crew — Multi-Agent Legal Review System")
    parser.add_argument("--contract", type=str, help="Path to a single NDA PDF to review")
    parser.add_argument("--all",      action="store_true", help="Review all NDAs in test-data/legal/ndas/")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    if args.all:
        review_all_ndas()
    elif args.contract:
        review_contract(args.contract)
    else:
        print("Usage:")
        print("  python crew.py --contract path/to/nda.pdf")
        print("  python crew.py --all")
        print("\nExample:")
        print("  python crew.py --contract test-data/legal/ndas/NDA_Meridian_Capital_HIGH_RISK.pdf")
