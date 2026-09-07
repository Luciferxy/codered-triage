"""CodeRed Triage: Full-duplex emergency paramedic voice agent with tool-fencing."""

from __future__ import annotations
import asyncio
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.medical_tools import (
    calculate_pediatric_dopamine_infusion,
    calculate_pediatric_epinephrine,
    get_asystole_pea_protocol,
    get_vf_pvt_protocol,
)
from src.pathway_vitals_stream import PatientVitalSample, StreamingVitalsEngine
from src.rime_synthesizer import RimeSynthesizer
from src.tool_fence import InterruptionRecord, TurnFenceManager

class CodeRedAgent:
    """Voice-native emergency resuscitation agent with sub-60ms barge-in and tool-fencing."""
    def __init__(self, rime_api_key: Optional[str] = None):
        self.fence_manager = TurnFenceManager()
        self.synthesizer = RimeSynthesizer(api_key=rime_api_key)
        self.vitals_engine = StreamingVitalsEngine()
        
        # Conversational memory: accurately tracks user prompts and only *heard* responses
        self.conversation_history: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are CodeRed Triage, an expert emergency resuscitation voice copilot for paramedics. "
                    "Keep spoken answers under 2 concise sentences. State direct, life-saving actions first. "
                    "Never explain theory during active resuscitation."
                )
            }
        ]
        self.active_streaming_task: Optional[asyncio.Task] = None
        self._is_speaking = False

    async def handle_user_speech(
        self,
        user_text: str,
        was_speaking: bool = False,
        playback_duration_sec: float = 0.0
    ) -> Dict[str, Any]:
        """Main turn entry point when user speaks (via LiveKit STT or console simulator)."""
        interruption_event: Optional[InterruptionRecord] = None
        
        # 1. Detect barge-in interruption
        if was_speaking or self._is_speaking or self.fence_manager.auditory_tracker.is_speaking:
            self.synthesizer.trigger_interruption()
            interruption_event = await self.fence_manager.interrupt_current_turn(
                reason="paramedic_speech_barge_in",
                playback_duration_sec=playback_duration_sec
            )
            # Reconcile memory: record only what the paramedic actually heard
            if self.conversation_history and self.conversation_history[-1]["role"] == "assistant":
                reconciled = (
                    f"{interruption_event.spoken_text_retained} "
                    f"[INTERRUPTED BY PARAMEDIC - REMAINDER FENCED & NOT HEARD]"
                )
                self.conversation_history[-1]["content"] = reconciled

        # 2. Begin new valid turn
        turn_id = await self.fence_manager.start_turn()
        self.conversation_history.append({"role": "user", "content": user_text})
        
        # 3. Intent classification & tool execution
        lower_text = user_text.lower()
        tool_task = None
        spoken_response = ""

        try:
            if "dopamine" in lower_text or "drip" in lower_text or "inotrope" in lower_text:
                # Heavy calculation with simulated 2.0s delay
                coro = calculate_pediatric_dopamine_infusion(weight_kg=15.0, dose_mcg_kg_min=5.0, simulated_delay_sec=2.0)
                res = await self.fence_manager.execute_fenced_tool(
                    coro=coro,
                    tool_name="calculate_pediatric_dopamine_infusion",
                    arguments={"weight_kg": 15.0, "dose_mcg_kg_min": 5.0},
                    turn_id=turn_id
                )
                if res and self.fence_manager.is_turn_valid(turn_id):
                    spoken_response = res["spoken_summary"]

            elif "flatline" in lower_text or "asystole" in lower_text or "cardiac arrest" in lower_text or "no pulse" in lower_text:
                # Immediate non-shockable emergency protocol
                coro = get_asystole_pea_protocol()
                res = await self.fence_manager.execute_fenced_tool(
                    coro=coro,
                    tool_name="get_asystole_pea_protocol",
                    arguments={},
                    turn_id=turn_id
                )
                if res and self.fence_manager.is_turn_valid(turn_id):
                    spoken_response = res["spoken_summary"]

            elif "v-fib" in lower_text or "shock" in lower_text or "ventricular fibrillation" in lower_text:
                # Shockable emergency protocol
                coro = get_vf_pvt_protocol(weight_kg=15.0)
                res = await self.fence_manager.execute_fenced_tool(
                    coro=coro,
                    tool_name="get_vf_pvt_protocol",
                    arguments={"weight_kg": 15.0},
                    turn_id=turn_id
                )
                if res and self.fence_manager.is_turn_valid(turn_id):
                    spoken_response = res["spoken_summary"]

            elif "epinephrine" in lower_text or "epi" in lower_text:
                # Pediatric epinephrine calculation
                coro = calculate_pediatric_epinephrine(weight_kg=15.0, simulated_delay_sec=0.1)
                res = await self.fence_manager.execute_fenced_tool(
                    coro=coro,
                    tool_name="calculate_pediatric_epinephrine",
                    arguments={"weight_kg": 15.0},
                    turn_id=turn_id
                )
                if res and self.fence_manager.is_turn_valid(turn_id):
                    spoken_response = res["spoken_summary"]

            else:
                spoken_response = f"Copy: {user_text}. Monitoring vitals. Awaiting clinical command."

        except asyncio.CancelledError:
            return {
                "turn_id": turn_id,
                "status": "CANCELLED_IN_FLIGHT",
                "interruption_event": interruption_event,
                "spoken_response": None,
                "fenced_events": self.fence_manager.fenced_events[-1:] if self.fence_manager.fenced_events else []
            }

        # If turn was cancelled during tool execution, spoken_response will be empty
        if not spoken_response or not self.fence_manager.is_turn_valid(turn_id):
            return {
                "turn_id": turn_id,
                "status": "INTERRUPTED_AND_FENCED",
                "interruption_event": interruption_event,
                "spoken_response": None,
                "fenced_events": self.fence_manager.fenced_events[-1:] if self.fence_manager.fenced_events else []
            }

        # 4. Stream response through Rime to measure TTFA and buffer
        self.fence_manager.auditory_tracker.start_speaking(spoken_response)
        self.conversation_history.append({"role": "assistant", "content": spoken_response})
        self._is_speaking = True

        # Pre-roll initial audio packet from Rime synthesizer to record TTFA
        async for _ in self.synthesizer.stream_speech(spoken_response):
            break

        return {
            "turn_id": turn_id,
            "status": "COMPLETED",
            "interruption_event": interruption_event,
            "spoken_response": spoken_response,
            "ttfa_ms": self.synthesizer.last_ttfa_ms,
            "provider_metadata": self.synthesizer.get_provider_metadata()
        }
