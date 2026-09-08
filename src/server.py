"""FastAPI web server: Trauma console API, real-time vitals SSE stream, and audio endpoints."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Any, Dict, Set
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

from src.agent import CodeRedAgent
from src.condition_alerts import ConditionAlertDetector
from src.pathway_vitals_stream import PatientVitalSample, StreamingVitalsEngine

# Shared agent, detector, and vitals engine instances
agent = CodeRedAgent()
vitals_engine = StreamingVitalsEngine()
alert_detector = ConditionAlertDetector(cooldown_sec=15.0)

# Active SSE client queues for broadcasting real-time vitals & alerts
active_sse_queues: Set[asyncio.Queue] = set()
vitals_task: asyncio.Task | None = None


def _serialize_dict(obj: Any) -> Any:
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialize_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_dict(i) for i in obj]
    return obj


async def on_vitals_sample(sample: PatientVitalSample):
    """Callback invoked by Pathway streaming engine for each processed telemetry row."""
    alert_payload = None

    # Check for clinical state transitions
    alert = alert_detector.check_sample(sample)
    if alert:
        alert_turn = await agent.handle_condition_alert(
            alert_text=alert.message,
            severity=alert.severity
        )
        alert_payload = {
            "severity": alert.severity,
            "condition": alert.condition,
            "text": alert.message,
            "audio_base64": alert_turn.get("audio_base64"),
            "turn_id": alert_turn.get("turn_id"),
            "ttfa_ms": alert_turn.get("ttfa_ms"),
            "interruption_event": _serialize_dict(alert_turn.get("interruption_event")),
        }

    data = {
        "timestamp_sec": sample.timestamp_sec,
        "heart_rate_bpm": sample.heart_rate_bpm,
        "systolic_bp": sample.systolic_bp,
        "diastolic_bp": sample.diastolic_bp,
        "spo2_pct": sample.spo2_pct,
        "rhythm_state": sample.rhythm_state,
        "is_cardiac_arrest": sample.is_cardiac_arrest,
        "alert": alert_payload,
    }

    # Broadcast to all connected browser SSE listeners
    for q in list(active_sse_queues):
        try:
            q.put_nowait(data)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts the genuine Pathway streaming engine on server startup."""
    global vitals_task
    # Subscribe alert handler to Pathway pipeline
    vitals_engine.subscribe(on_vitals_sample)
    # Launch Pathway background stream loop
    vitals_task = asyncio.create_task(vitals_engine.run_stream(interval_sec=1.0, loop_forever=True))
    yield
    # Cleanup on server shutdown
    vitals_engine.stop()
    if vitals_task and not vitals_task.done():
        vitals_task.cancel()


app = FastAPI(title="CodeRed Triage Console", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class UtteranceRequest(BaseModel):
    text: str
    was_speaking: bool = False
    playback_duration_sec: float = 0.0


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = WEB_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "pathway_running": vitals_engine._is_running,
        "provider_metadata": agent.synthesizer.get_provider_metadata(),
        "current_turn_id": agent.fence_manager.current_turn_id,
        "interruption_count": len(agent.fence_manager.interruption_history),
        "fenced_events_count": len(agent.fence_manager.fenced_events),
    }


@app.post("/api/speak")
async def handle_speech(req: UtteranceRequest):
    result = await agent.handle_user_speech(
        user_text=req.text,
        was_speaking=req.was_speaking,
        playback_duration_sec=req.playback_duration_sec
    )
    return JSONResponse(content=_serialize_dict(result))


@app.get("/api/vitals/stream")
async def stream_vitals(request: Request):
    """Server-Sent Events (SSE) streaming real-time patient vitals powered by Pathway."""
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=50)
    
    # Pre-populate with latest sample if available
    latest = vitals_engine.get_latest_vitals()
    if latest:
        q.put_nowait({
            "timestamp_sec": latest.timestamp_sec,
            "heart_rate_bpm": latest.heart_rate_bpm,
            "systolic_bp": latest.systolic_bp,
            "diastolic_bp": latest.diastolic_bp,
            "spo2_pct": latest.spo2_pct,
            "rhythm_state": latest.rhythm_state,
            "is_cardiac_arrest": latest.is_cardiac_arrest,
            "alert": None
        })

    active_sse_queues.add(q)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat ping
                    yield ": keep-alive\n\n"
        finally:
            active_sse_queues.discard(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/vitals/reset")
async def reset_vitals():
    """Resets the condition detector for demonstration replay."""
    alert_detector.reset()
    return {"status": "reset", "message": "Alert detector reset to baseline"}


@app.get("/api/fenced_events")
async def get_fenced_events():
    events = [
        {
            "tool_name": e.tool_name,
            "turn_id": e.turn_id,
            "arguments": e.arguments,
            "status": e.status,
            "duration_ms": e.duration_ms,
            "discarded": e.status in ("DISCARDED_STALE", "CANCELLED_IN_FLIGHT")
        }
        for e in agent.fence_manager.fenced_events
    ]
    interruptions = [
        {
            "turn_id": i.turn_id,
            "cutoff_latency_ms": i.cutoff_latency_ms,
            "reason": i.reason,
            "cancelled_tasks": i.cancelled_tasks_count,
            "spoken_retained": i.spoken_text_retained,
            "fenced_discarded": i.discarded_text_fenced
        }
        for i in agent.fence_manager.interruption_history
    ]
    return {
        "fenced_events": events,
        "interruption_history": interruptions,
        "conversation_history": agent.conversation_history
    }


def main():
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
