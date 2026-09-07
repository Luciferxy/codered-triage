"""FastAPI web server: Trauma console API, real-time vitals SSE stream, and audio endpoints."""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent import CodeRedAgent
from src.pathway_vitals_stream import PatientVitalSample, StreamingVitalsEngine

app = FastAPI(title="CodeRed Triage Console")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# Shared agent and vitals engine instances
agent = CodeRedAgent()
vitals_engine = StreamingVitalsEngine()

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
        "provider_metadata": agent.synthesizer.get_provider_metadata(),
        "current_turn_id": agent.fence_manager.current_turn_id,
        "interruption_count": len(agent.fence_manager.interruption_history),
        "fenced_events_count": len(agent.fence_manager.fenced_events)
    }

def _serialize_dict(obj: Any) -> Any:
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialize_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_dict(i) for i in obj]
    return obj

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
    """Server-Sent Events (SSE) streaming real-time patient vitals."""
    async def event_generator():
        samples = vitals_engine.load_fixture_samples()
        while True:
            for s in samples:
                if await request.is_disconnected():
                    break
                data = {
                    "timestamp_sec": s.timestamp_sec,
                    "heart_rate_bpm": s.heart_rate_bpm,
                    "systolic_bp": s.systolic_bp,
                    "diastolic_bp": s.diastolic_bp,
                    "spo2_pct": s.spo2_pct,
                    "rhythm_state": s.rhythm_state,
                    "is_cardiac_arrest": s.is_cardiac_arrest
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(1.0)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
