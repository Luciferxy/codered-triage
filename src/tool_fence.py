"""Hard Voice Engineering: Deterministic Tool-Fencing and Auditory State Reconciliation."""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

@dataclass
class FencedToolEvent:
    tool_name: str
    turn_id: int
    arguments: Dict[str, Any]
    status: str  # "COMMITTED", "DISCARDED_STALE", "CANCELLED_IN_FLIGHT"
    started_at: float
    ended_at: float
    duration_ms: float
    discarded_payload: Optional[Any] = None

@dataclass
class InterruptionRecord:
    turn_id: int
    interrupted_at: float
    cutoff_latency_ms: float
    reason: str
    cancelled_tasks_count: int
    spoken_text_retained: str
    discarded_text_fenced: str

class AuditoryStateTracker:
    """Tracks what the clinician actually heard through the speaker vs. what was queued."""
    def __init__(self):
        self.queued_tokens: List[str] = []
        self.spoken_tokens: List[str] = []
        self.is_speaking: bool = False
        self.last_audio_start_time: float = 0.0

    def start_speaking(self, text: str):
        self.queued_tokens = text.split()
        self.spoken_tokens = []
        self.is_speaking = True
        self.last_audio_start_time = time.perf_counter()

    def record_playback_progress(self, words_played_count: int):
        if words_played_count <= len(self.queued_tokens):
            self.spoken_tokens = self.queued_tokens[:words_played_count]

    def truncate_on_interruption(self, playback_duration_sec: float, estimated_wps: float = 3.0) -> tuple[str, str]:
        """Estimate words spoken based on playback duration before cutoff."""
        self.is_speaking = False
        words_delivered_count = int(playback_duration_sec * estimated_wps)
        words_delivered_count = min(words_delivered_count, len(self.queued_tokens))
        
        spoken = " ".join(self.queued_tokens[:words_delivered_count])
        fenced = " ".join(self.queued_tokens[words_delivered_count:])
        self.spoken_tokens = self.queued_tokens[:words_delivered_count]
        self.queued_tokens = []
        return spoken, fenced

class TurnFenceManager:
    """Orchestrates turn tokens, tool cancellation, and state consistency."""
    def __init__(self):
        self.current_turn_id: int = 0
        self._active_tasks: Dict[int, List[asyncio.Task]] = {}
        self.auditory_tracker = AuditoryStateTracker()
        self.fenced_events: List[FencedToolEvent] = []
        self.interruption_history: List[InterruptionRecord] = []
        self._lock = asyncio.Lock()

    async def start_turn(self) -> int:
        """Starts a new conversational turn and increments monotonic turn ID."""
        async with self._lock:
            self.current_turn_id += 1
            turn_id = self.current_turn_id
            self._active_tasks[turn_id] = []
            return turn_id

    def is_turn_valid(self, turn_id: int) -> bool:
        """Returns True if the given turn_id is still current and not superseded or cancelled."""
        return turn_id == self.current_turn_id

    async def interrupt_current_turn(
        self,
        reason: str = "user_speech_barge_in",
        playback_duration_sec: float = 0.0
    ) -> InterruptionRecord:
        """Immediately interrupts active turn, cancels all in-flight tools, and purges audio queues."""
        t_start = time.perf_counter()
        
        async with self._lock:
            interrupted_turn = self.current_turn_id
            tasks = self._active_tasks.get(interrupted_turn, [])
            cancelled_count = 0
            
            for task in tasks:
                if not task.done():
                    task.cancel()
                    cancelled_count += 1
            
            # Invalidate current turn by bumping ID
            self.current_turn_id += 1
            
            # Compute auditory reconciliation
            spoken, fenced = self.auditory_tracker.truncate_on_interruption(playback_duration_sec)
            
            t_end = time.perf_counter()
            cutoff_ms = (t_end - t_start) * 1000.0

            record = InterruptionRecord(
                turn_id=interrupted_turn,
                interrupted_at=time.time(),
                cutoff_latency_ms=round(cutoff_ms, 3),
                reason=reason,
                cancelled_tasks_count=cancelled_count,
                spoken_text_retained=spoken,
                discarded_text_fenced=fenced
            )
            self.interruption_history.append(record)
            return record

    async def execute_fenced_tool(
        self,
        coro: Coroutine[Any, Any, Any],
        tool_name: str,
        arguments: Dict[str, Any],
        turn_id: int
    ) -> Optional[Any]:
        """Executes a tool within a fenced boundary. If the turn was invalidated during execution,
        discards the result and prevents it from entering speech or chat history."""
        t_start = time.perf_counter()
        tool_task = asyncio.create_task(coro)
        self._active_tasks.setdefault(turn_id, []).append(tool_task)

        try:
            result = await tool_task
            t_end = time.perf_counter()
            duration_ms = (t_end - t_start) * 1000.0
            
            # Check fence validity
            if not self.is_turn_valid(turn_id):
                # Stale tool completed after turn was cancelled/superseded
                event = FencedToolEvent(
                    tool_name=tool_name,
                    turn_id=turn_id,
                    arguments=arguments,
                    status="DISCARDED_STALE",
                    started_at=t_start,
                    ended_at=t_end,
                    duration_ms=round(duration_ms, 2),
                    discarded_payload=result
                )
                self.fenced_events.append(event)
                return None
            
            # Tool committed cleanly within valid turn
            event = FencedToolEvent(
                tool_name=tool_name,
                turn_id=turn_id,
                arguments=arguments,
                status="COMMITTED",
                started_at=t_start,
                ended_at=t_end,
                duration_ms=round(duration_ms, 2),
                discarded_payload=None
            )
            self.fenced_events.append(event)
            return result

        except asyncio.CancelledError:
            t_end = time.perf_counter()
            duration_ms = (t_end - t_start) * 1000.0
            event = FencedToolEvent(
                tool_name=tool_name,
                turn_id=turn_id,
                arguments=arguments,
                status="CANCELLED_IN_FLIGHT",
                started_at=t_start,
                ended_at=t_end,
                duration_ms=round(duration_ms, 2),
                discarded_payload=None
            )
            self.fenced_events.append(event)
            return None
