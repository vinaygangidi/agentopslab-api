"""
Legal Memo Report Writer
=========================
Takes all agent outputs and generates:
  1. JSON report file (machine-readable)
  2. Professional PDF legal memo (human-readable)
"""

import os
import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY


RISK_COLORS = {
    "LOW":      colors.HexColor("#2E7D32"),
    "MEDIUM":   colors.HexColor("#E65100"),
    "HIGH":     colors.HexColor("#B71C1C"),
    "CRITICAL": colors.HexColor("#4A148C"),
    "UNKNOWN":  colors.grey,
}

ACTION_LABELS = {
    "APPROVE":  "Approved for signature",
    "REVISE":   "Revisions required before signing",
    "REDLINE":  "Significant redlines required — mandatory legal review",
    "ESCALATE": "DO NOT SIGN — escalate to General Counsel immediately",
}


def write_report(
    contract_filename: str,
    contract_text_excerpt: str,
    clauses_json: str,
    playbook_json: str,
    risk_json: str,
    compliance_json: str,
    output_dir: str
) -> dict:
    """
    Master report writer — generates JSON + PDF outputs.
    Returns dict with paths to both output files.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Parse all inputs
    try:
        clauses    = json.loads(clauses_json)    if isinstance(clauses_json, str)    else clauses_json
        playbook   = json.loads(playbook_json)   if isinstance(playbook_json, str)   else playbook_json
        risk       = json.loads(risk_json)       if isinstance(risk_json, str)       else risk_json
        compliance = json.loads(compliance_json) if isinstance(compliance_json, str) else compliance_json
    except Exception:
        clauses = playbook = risk = compliance = {}

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name   = os.path.splitext(contract_filename)[0]
    json_path   = os.path.join(output_dir, f"{base_name}_report_{timestamp}.json")
    pdf_path    = os.path.join(output_dir, f"{base_name}_legal_memo_{timestamp}.pdf")

    # ── Write JSON ────────────────────────────────────────────
    full_report = {
        "report_metadata": {
            "generated_at": datetime.now().isoformat(),
            "contract_file": contract_filename,
            "review_system": "NDA Review Crew v1.0 — NovaTech Solutions",
            "framework": "CrewAI + Claude Sonnet"
        },
        "clause_extraction": clauses,
        "playbook_review":   playbook,
        "risk_assessment":   risk,
        "compliance_check":  compliance,
    }

    with open(json_path, "w") as f:
        json.dump(full_report, f, indent=2)

    # ── Write PDF ─────────────────────────────────────────────
    _generate_pdf(
        pdf_path, contract_filename, clauses,
        playbook, risk, compliance, timestamp
    )

    return {"json_report": json_path, "pdf_memo": pdf_path}


def _generate_pdf(pdf_path, contract_filename, clauses, playbook, risk, compliance, timestamp):
    """Generates the formatted legal memo PDF."""

    doc = SimpleDocTemplate(
        pdf_path, pagesize=letter,
        rightMargin=1*inch, leftMargin=1*inch,
        topMargin=1*inch, bottomMargin=1*inch,
        title=f"Legal Review Memo — {contract_filename}"
    )

    base   = getSampleStyleSheet()
    risk_level = risk.get("overall_risk_level", "UNKNOWN")
    risk_color = RISK_COLORS.get(risk_level, colors.grey)

    # Styles
    S = {
        "title": ParagraphStyle("T", parent=base["Title"],
            fontSize=15, leading=20, alignment=TA_CENTER,
            fontName="Helvetica-Bold", spaceAfter=4),
        "sub":   ParagraphStyle("S", parent=base["Normal"],
            fontSize=10, alignment=TA_CENTER, fontName="Helvetica",
            textColor=colors.HexColor("#444444"), spaceAfter=2),
        "h1":    ParagraphStyle("H1", parent=base["Heading1"],
            fontSize=12, fontName="Helvetica-Bold",
            spaceBefore=14, spaceAfter=6),
        "h2":    ParagraphStyle("H2", parent=base["Heading2"],
            fontSize=11, fontName="Helvetica-Bold",
            spaceBefore=10, spaceAfter=4),
        "body":  ParagraphStyle("B", parent=base["Normal"],
            fontSize=10, leading=15, alignment=TA_JUSTIFY,
            fontName="Helvetica", spaceAfter=6),
        "mono":  ParagraphStyle("M", parent=base["Normal"],
            fontSize=9, leading=13, fontName="Courier",
            spaceAfter=4, leftIndent=12),
        "risk":  ParagraphStyle("R", parent=base["Normal"],
            fontSize=13, fontName="Helvetica-Bold",
            alignment=TA_CENTER, textColor=risk_color, spaceAfter=4),
        "foot":  ParagraphStyle("F", parent=base["Normal"],
            fontSize=8, alignment=TA_CENTER,
            textColor=colors.grey, fontName="Helvetica-Oblique"),
    }

    story = []

    # ── Cover ─────────────────────────────────────────────────
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("LEGAL REVIEW MEMORANDUM", S["title"]))
    story.append(Paragraph("NDA Contract Analysis — NovaTech Solutions Inc.", S["sub"]))
    story.append(Spacer(1, 0.1*inch))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black, spaceAfter=10))
    story.append(Spacer(1, 0.1*inch))

    meta_data = [
        ["Contract File:", contract_filename],
        ["Review Date:",   datetime.now().strftime("%B %d, %Y")],
        ["Review System:", "NDA Review Crew v1.0 (CrewAI + Claude Sonnet)"],
        ["Reviewed By:",   "Multi-Agent Legal Review System"],
    ]
    meta_table = Table(meta_data, colWidths=[1.6*inch, 4.8*inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME",    (1,0), (1,-1), "Helvetica"),
        ("FONTSIZE",    (0,0), (-1,-1), 10),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("TEXTCOLOR",   (0,0), (0,-1), colors.HexColor("#333333")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.2*inch))

    # Risk badge
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=8))
    story.append(Paragraph(f"OVERALL RISK: {risk_level}", S["risk"]))
    action_text = ACTION_LABELS.get(risk.get("action_required", ""), "See recommendations below")
    story.append(Paragraph(action_text, S["sub"]))
    story.append(Paragraph(
        f"Total Risk Score: {risk.get('total_risk_score', 'N/A')} / 100  |  "
        f"Sign-off Required: {compliance.get('sign_off_required', 'N/A')}",
        S["sub"]
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=8))
    story.append(Spacer(1, 0.1*inch))

    # ── Section 1: Executive Summary ──────────────────────────
    story.append(Paragraph("1. EXECUTIVE SUMMARY", S["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=6))

    total_found   = clauses.get("total_found",   "N/A")
    total_missing = clauses.get("total_missing", "N/A")
    doc_summary   = clauses.get("document_summary", "Contract reviewed by multi-agent system.")

    story.append(Paragraph(doc_summary, S["body"]))
    story.append(Paragraph(
        f"The automated review identified <b>{total_found}</b> of 10 required NDA clauses. "
        f"<b>{total_missing}</b> clauses were not found or are absent from the contract. "
        f"The contract received an overall risk score of <b>{risk.get('total_risk_score','N/A')}</b> "
        f"out of 100, placing it in the <b>{risk_level}</b> risk category.",
        S["body"]
    ))

    # Clause count table
    counts = risk.get("clause_summary", {})
    if counts:
        summary_rows = [["Status", "Count"]]
        status_colors = {
            "ACCEPTABLE":       "#2E7D32",
            "MINOR_DEVIATION":  "#F57F17",
            "MODERATE_DEVIATION":"#E65100",
            "RISKY":            "#B71C1C",
            "MISSING":          "#4A148C",
        }
        for status, count in counts.items():
            summary_rows.append([status.replace("_", " ").title(), str(count)])

        summary_table = Table(summary_rows, colWidths=[3*inch, 1*inch])
        ts = TableStyle([
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 10),
            ("BACKGROUND",   (0,0), (-1,0), colors.HexColor("#EEEEEE")),
            ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING",   (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ])
        for i, row in enumerate(summary_rows[1:], 1):
            status_key = row[0].upper().replace(" ", "_")
            hex_color  = status_colors.get(status_key, "#333333")
            ts.add("TEXTCOLOR", (0,i), (0,i), colors.HexColor(hex_color))
            ts.add("FONTNAME",  (0,i), (0,i), "Helvetica-Bold")
        summary_table.setStyle(ts)
        story.append(summary_table)
        story.append(Spacer(1, 0.1*inch))

    # ── Section 2: Critical Issues ────────────────────────────
    story.append(Paragraph("2. CRITICAL ISSUES AND FLAGS", S["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=6))

    high_risk = risk.get("high_risk_clauses", [])
    missing   = compliance.get("all_missing_clauses", [])

    if high_risk:
        story.append(Paragraph("High-Risk Clauses Identified:", S["h2"]))
        for item in high_risk:
            story.append(Paragraph(
                f"<b>{item.get('clause','Unknown')}</b> — Risk Score: {item.get('score','N/A')}/10",
                S["body"]
            ))
            story.append(Paragraph(
                f"Issue: {item.get('issue', 'See detailed review below')}",
                S["mono"]
            ))
    else:
        story.append(Paragraph("No high-risk clauses identified.", S["body"]))

    if missing:
        story.append(Spacer(1, 0.1*inch))
        story.append(Paragraph("Missing Required Clauses:", S["h2"]))
        for m in missing:
            story.append(Paragraph(f"• {m}", S["body"]))

    # ── Section 3: Clause-by-Clause Review ───────────────────
    story.append(PageBreak())
    story.append(Paragraph("3. CLAUSE-BY-CLAUSE REVIEW", S["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=6))

    pb_results = playbook.get("playbook_results", [])
    if pb_results:
        for clause in pb_results:
            status     = clause.get("status", "UNKNOWN")
            score      = clause.get("risk_score", 0)
            color_map  = {
                "ACCEPTABLE":        "#2E7D32",
                "MINOR_DEVIATION":   "#F57F17",
                "MODERATE_DEVIATION":"#E65100",
                "RISKY":             "#B71C1C",
                "MISSING":           "#4A148C",
            }
            c_color = colors.HexColor(color_map.get(status, "#333333"))

            clause_style = ParagraphStyle(
                "CS", parent=S["h2"],
                textColor=c_color
            )
            story.append(Paragraph(
                f"{clause.get('clause_id','')}: {clause.get('clause_name','')} "
                f"[{status}] — Score: {score}/10",
                clause_style
            ))

            if clause.get("deviation_found"):
                story.append(Paragraph(
                    f"Deviation: {clause['deviation_found']}", S["mono"]
                ))
            if clause.get("playbook_position_violated"):
                story.append(Paragraph(
                    f"Playbook position violated: {clause['playbook_position_violated']}", S["mono"]
                ))
            if clause.get("recommendation"):
                story.append(Paragraph(
                    f"Recommendation: {clause['recommendation']}", S["body"]
                ))
            story.append(HRFlowable(
                width="100%", thickness=0.3,
                color=colors.HexColor("#DDDDDD"), spaceAfter=4
            ))
    else:
        story.append(Paragraph("Detailed clause review not available.", S["body"]))

    # ── Section 4: Compliance Verdict ────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("4. COMPLIANCE VERDICT AND NEXT STEPS", S["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=6))

    comp_status = compliance.get("compliance_status", "UNKNOWN")
    comp_colors = {"PASS": "#2E7D32", "CONDITIONAL": "#E65100", "FAIL": "#B71C1C"}
    comp_color  = colors.HexColor(comp_colors.get(comp_status, "#333333"))

    verdict_style = ParagraphStyle("VS", parent=S["h1"], textColor=comp_color, fontSize=14)
    story.append(Paragraph(f"Compliance Status: {comp_status}", verdict_style))
    story.append(Spacer(1, 0.1*inch))

    next_steps = []
    if risk_level == "LOW":
        next_steps = [
            "Review minor notes flagged above with contract manager",
            "Obtain standard approval signature",
            "File executed contract in contract management system",
        ]
    elif risk_level == "MEDIUM":
        next_steps = [
            "Send redline comments to counterparty on flagged clauses",
            f"Estimated {compliance.get('estimated_revision_rounds',1)} revision round(s) required",
            "Obtain Legal Team sign-off before executing",
            "Re-run automated review after revisions",
        ]
    elif risk_level == "HIGH":
        next_steps = [
            "DO NOT EXECUTE — mandatory legal review required",
            f"Flagged clauses: {', '.join(risk.get('critical_flags', []))}",
            f"Missing clauses: {', '.join(compliance.get('all_missing_clauses', []))}",
            f"Estimated {compliance.get('estimated_revision_rounds',2)} revision round(s) required",
            "Obtain Legal Team sign-off after all revisions",
        ]
    else:
        next_steps = [
            "DO NOT SIGN UNDER ANY CIRCUMSTANCES",
            "Escalate immediately to General Counsel",
            "Request completely revised agreement from counterparty",
            "Consider whether to continue the business relationship",
        ]

    for i, step in enumerate(next_steps, 1):
        story.append(Paragraph(f"{i}. {step}", S["body"]))

    # ── Footer ────────────────────────────────────────────────
    story.append(Spacer(1, 0.4*inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=8))
    story.append(Paragraph(
        f"This memo was generated by NDA Review Crew v1.0 on {datetime.now().strftime('%B %d, %Y at %H:%M')}. "
        f"It is a synthesized demo output for portfolio purposes. "
        f"This is not legal advice. All contract names and parties are fictitious.",
        S["foot"]
    ))

    doc.build(story)
