"""
AgentOpsLab — NDA Review API
FastAPI backend that wraps the CrewAI pipeline and streams
agent progress to the frontend via Server-Sent Events (SSE).

Deploy on Railway. Set env vars:
  ANTHROPIC_API_KEY
  MISTRAL_API_KEY
  ALLOWED_ORIGIN (your Vercel URL)
"""

import os
import sys
import json
import uuid
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
import uvicorn

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="AgentOpsLab NDA Review API", version="1.0.0")

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://agentopslab-landing.vercel.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ────────────────────────────────────────────────────
# { job_id: { status, events: [], result: {} } }
jobs: dict = {}

UPLOAD_DIR = Path("/tmp/nda_uploads")
OUTPUT_DIR = Path("/tmp/nda_outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT PROGRESS TRACKING
# ─────────────────────────────────────────────────────────────────────────────

AGENT_STEPS = [
    {
        "step": 1,
        "agent": "Legal Document Parser",
        "model": "Haiku",
        "description": "Extracting text from PDF via Mistral OCR",
        "icon": "📄",
    },
    {
        "step": 2,
        "agent": "Clause Extraction Specialist",
        "model": "Haiku",
        "description": "Identifying all 10 NDA clause types",
        "icon": "🔍",
    },
    {
        "step": 3,
        "agent": "Legal Playbook Reviewer",
        "model": "Sonnet",
        "description": "Comparing clauses against NovaTech legal playbook",
        "icon": "📋",
    },
    {
        "step": 4,
        "agent": "Risk Scoring Analyst",
        "model": "Sonnet",
        "description": "Calculating risk scores and thresholds",
        "icon": "⚖️",
    },
    {
        "step": 5,
        "agent": "Legal Compliance Officer",
        "model": "Haiku",
        "description": "Running final compliance gate check",
        "icon": "✅",
    },
]


def push_event(job_id: str, event_type: str, data: dict):
    """Push an event to the job's event queue."""
    if job_id in jobs:
        jobs[job_id]["events"].append({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })


def run_pipeline(job_id: str, pdf_path: str, original_filename: str):
    """
    Runs the full CrewAI pipeline in a background thread.
    Patches CrewAI callbacks to emit SSE events per agent.
    """
    try:
        jobs[job_id]["status"] = "running"
        push_event(job_id, "start", {"message": "Pipeline started", "filename": original_filename})

        # Add the nda-review directory to sys.path
        nda_dir = Path(__file__).parent / "nda_review"
        sys.path.insert(0, str(nda_dir))
        sys.path.insert(0, str(nda_dir.parent))

        from crewai import Agent, Task, Crew, Process
        from crewai.agents.agent_builder.base_agent_executor_mixin import CrewAgentExecutorMixin

        # Monkey-patch to intercept agent completions
        original_execute = CrewAgentExecutorMixin._execute_core if hasattr(CrewAgentExecutorMixin, '_execute_core') else None

        # Import crew modules
        from nda_review.crew import build_agents, build_tasks
        from nda_review.report_writer import write_report

        # Track which agent is running
        step_tracker = {"current": 0}

        def on_agent_start(step_num: int, agent_name: str):
            step_tracker["current"] = step_num
            agent_info = AGENT_STEPS[step_num - 1]
            push_event(job_id, "agent_start", {
                "step": step_num,
                "agent": agent_name,
                "model": agent_info["model"],
                "description": agent_info["description"],
                "icon": agent_info["icon"],
                "total_steps": len(AGENT_STEPS),
            })

        def on_agent_complete(step_num: int, agent_name: str, output_preview: str = ""):
            push_event(job_id, "agent_complete", {
                "step": step_num,
                "agent": agent_name,
                "output_preview": output_preview[:200] if output_preview else "",
                "total_steps": len(AGENT_STEPS),
            })

        # Build agents and tasks
        agents = build_agents()
        tasks = build_tasks(agents, pdf_path)

        # Emit start events for each agent sequentially
        # We'll wrap each task's agent execution
        agent_list = list(agents.values())
        for i, (agent_key, agent_obj) in enumerate(agents.items()):
            step_num = i + 1
            agent_obj._original_execute = getattr(agent_obj, 'execute_task', None)

        # Run with progress tracking via thread monitoring
        import queue as q
        progress_queue = q.Queue()

        def progress_monitor():
            for i, step_info in enumerate(AGENT_STEPS):
                push_event(job_id, "agent_start", {
                    "step": step_info["step"],
                    "agent": step_info["agent"],
                    "model": step_info["model"],
                    "description": step_info["description"],
                    "icon": step_info["icon"],
                    "total_steps": len(AGENT_STEPS),
                })
                # Wait for signal that this agent completed
                progress_queue.get(timeout=600)  # 10 min timeout per agent
                push_event(job_id, "agent_complete", {
                    "step": step_info["step"],
                    "agent": step_info["agent"],
                    "total_steps": len(AGENT_STEPS),
                })

        # Patch task callbacks
        original_callbacks = []
        for i, task in enumerate(tasks):
            step_info = AGENT_STEPS[i]

            def make_callback(si, q_ref):
                def callback(output):
                    q_ref.put(si["step"])
                return callback

            task.callback = make_callback(step_info, progress_queue)

        # Start progress monitor thread
        monitor_thread = threading.Thread(target=progress_monitor, daemon=True)
        monitor_thread.start()

        # Run the crew
        from nda_review.crew import build_agents as ba, build_tasks as bt
        from dotenv import load_dotenv
        load_dotenv()

        crew = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=Process.sequential,
            verbose=False,
        )

        result = crew.kickoff()

        # Collect task outputs
        outputs = [
            t.output.raw if hasattr(t, 'output') and t.output else "{}"
            for t in tasks
        ]

        parse_out      = outputs[0] if len(outputs) > 0 else ""
        extract_out    = outputs[1] if len(outputs) > 1 else "{}"
        playbook_out   = outputs[2] if len(outputs) > 2 else "{}"
        risk_out       = outputs[3] if len(outputs) > 3 else "{}"
        compliance_out = outputs[4] if len(outputs) > 4 else "{}"

        # Generate reports
        report_paths = write_report(
            contract_filename=original_filename,
            contract_text_excerpt=parse_out[:500],
            clauses_json=extract_out,
            playbook_json=playbook_out,
            risk_json=risk_out,
            compliance_json=compliance_out,
            output_dir=str(OUTPUT_DIR),
        )

        # Parse final results for the frontend
        try:
            risk_data = json.loads(risk_out) if isinstance(risk_out, str) else risk_out
        except Exception:
            risk_data = {}

        try:
            compliance_data = json.loads(compliance_out) if isinstance(compliance_out, str) else compliance_out
        except Exception:
            compliance_data = {}

        try:
            clauses_data = json.loads(extract_out) if isinstance(extract_out, str) else extract_out
        except Exception:
            clauses_data = {}

        try:
            playbook_data = json.loads(playbook_out) if isinstance(playbook_out, str) else playbook_out
        except Exception:
            playbook_data = {}

        # Store result
        jobs[job_id]["result"] = {
            "risk_level": risk_data.get("overall_risk_level", "UNKNOWN"),
            "risk_score": risk_data.get("total_risk_score", 0),
            "action": risk_data.get("action_required", "UNKNOWN"),
            "recommendation": risk_data.get("recommendation", ""),
            "compliance_status": compliance_data.get("compliance_status", "UNKNOWN"),
            "sign_off_required": compliance_data.get("sign_off_required", ""),
            "revision_rounds": compliance_data.get("estimated_revision_rounds", 0),
            "critical_flags": risk_data.get("critical_flags", []),
            "high_risk_clauses": risk_data.get("high_risk_clauses", []),
            "clauses_found": clauses_data.get("total_found", 0),
            "clauses_missing": clauses_data.get("total_missing", 0),
            "playbook_results": playbook_data.get("playbook_results", []),
            "pdf_path": report_paths.get("pdf_memo", ""),
            "json_path": report_paths.get("json_report", ""),
            "contract_filename": original_filename,
            "completed_at": datetime.now().isoformat(),
        }

        jobs[job_id]["status"] = "complete"
        push_event(job_id, "complete", jobs[job_id]["result"])

    except Exception as e:
        jobs[job_id]["status"] = "error"
        push_event(job_id, "error", {"message": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "AgentOpsLab NDA Review API", "version": "1.0.0"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Accept a PDF upload, start the pipeline in background, return job_id.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    if file.size and file.size > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum 10MB.")

    job_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{job_id}.pdf"

    # Save uploaded file
    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)

    # Init job
    jobs[job_id] = {
        "status": "queued",
        "events": [],
        "result": None,
        "filename": file.filename,
        "created_at": datetime.now().isoformat(),
    }

    # Start pipeline in background thread
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, str(pdf_path), file.filename),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "queued", "filename": file.filename}


@app.get("/status/{job_id}")
async def stream_status(job_id: str):
    """
    SSE endpoint — streams agent progress events to the frontend.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        sent_count = 0
        while True:
            job = jobs.get(job_id)
            if not job:
                break

            # Send any new events
            events = job["events"]
            while sent_count < len(events):
                event = events[sent_count]
                yield f"data: {json.dumps(event)}\n\n"
                sent_count += 1

            # Check if done
            if job["status"] in ("complete", "error"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/result/{job_id}")
def get_result(job_id: str):
    """Return the final result JSON for a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "complete":
        raise HTTPException(status_code=202, detail="Job not yet complete")
    return job["result"]


@app.get("/download/pdf/{job_id}")
def download_pdf(job_id: str):
    """Download the PDF memo for a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "complete" or not job.get("result"):
        raise HTTPException(status_code=202, detail="Job not yet complete")

    pdf_path = job["result"].get("pdf_path", "")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"NDA_Review_{job_id[:8]}.pdf",
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
