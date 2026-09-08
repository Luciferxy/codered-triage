"""LiveKit voice agent worker: Real voice-native pipeline with Rime TTS, OpenRouter LLM, and barge-in.

Connects to a LiveKit Cloud room, receives audio from the paramedic's microphone,
transcribes via STT, reasons via OpenRouter LLM, and speaks back via Rime mist_v3.

Usage:
    uv run python -m src.livekit_worker dev

Requires in .env:
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    RIME_API_KEY
    OPENROUTER_API_KEY
"""

from __future__ import annotations
import os
import sys

from dotenv import load_dotenv
load_dotenv()


def _check_credentials() -> list[str]:
    """Returns a list of missing credential names."""
    missing = []
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        val = os.getenv(key, "").strip()
        if not val or val.startswith("your_"):
            missing.append(key)
    if not os.getenv("RIME_API_KEY", "").strip():
        missing.append("RIME_API_KEY")
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        missing.append("OPENROUTER_API_KEY")
    return missing


def main():
    missing = _check_credentials()
    if missing:
        print("=" * 60)
        print("  CODERED TRIAGE: LIVEKIT WORKER — CREDENTIAL CHECK FAILED")
        print("=" * 60)
        for m in missing:
            print(f"  ❌ Missing: {m}")
        print()
        print("  Copy your credentials into .env and try again.")
        print("  LiveKit secrets: https://cloud.livekit.io")
        print("=" * 60)
        sys.exit(1)

    from livekit.agents import AgentSession, JobContext, WorkerOptions, cli
    from livekit.agents.voice import Agent
    from livekit.agents.inference import LLM, STT, TTS

    from src.medical_tools import (
        calculate_pediatric_epinephrine,
        calculate_pediatric_dopamine_infusion,
        get_asystole_pea_protocol,
        get_vf_pvt_protocol,
    )
    from src.rime_synthesizer import normalize_medical_speech

    SYSTEM_INSTRUCTIONS = (
        "You are CodeRed Triage, an expert emergency resuscitation voice copilot for paramedics. "
        "Keep spoken answers under 2 concise sentences. State direct, life-saving actions first. "
        "Never explain theory during active resuscitation. "
        "Expand medical abbreviations for speech: say 'intravenous' not 'IV', "
        "'milligrams per kilo' not 'mg/kg', 'C-P-R' not 'CPR'."
    )

    async def entrypoint(ctx: JobContext):
        await ctx.connect()

        # Configure Rime TTS via LiveKit plugin
        rime_tts = TTS(
            model="rime/mist",
            api_key=os.getenv("RIME_API_KEY"),
        )

        # Configure OpenRouter LLM via the unified inference API
        openrouter_llm = LLM(
            model=os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        # Build voice agent with interruption enabled
        agent = Agent(
            instructions=SYSTEM_INSTRUCTIONS,
            llm=openrouter_llm,
            tts=rime_tts,
            allow_interruptions=True,
            min_endpointing_delay=0.5,
        )

        session = AgentSession()
        await session.start(
            agent=agent,
            room=ctx.room,
        )

        print("[CodeRed LiveKit] Agent session started — listening for paramedic speech")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=os.getenv("LIVEKIT_URL"),
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            agent_name="codered-triage",
        )
    )


if __name__ == "__main__":
    main()
