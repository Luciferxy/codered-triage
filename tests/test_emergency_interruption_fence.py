"""Repeatable acceptance test for full-duplex tool-fencing under emergency conditions."""

import asyncio
import time
import unittest
from src.agent import CodeRedAgent

class TestEmergencyInterruptionFence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = CodeRedAgent()

    async def test_01_normal_clinical_turn(self):
        """Verify normal end-to-end execution without interruption."""
        res = await self.agent.handle_user_speech("Calculate pediatric epinephrine for 15kg child")
        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("0.15 milligrams", res["spoken_response"])
        self.assertIn("1.5 milliliters", res["spoken_response"])
        self.assertGreater(res["ttfa_ms"], 0.0)

    async def test_02_deliberate_tool_interruption_and_fencing(self):
        """
        The Core Hard Voice Engineering Acceptance Test:
        1. Start heavy calculation tool (dopamine drip, 2.0s delay).
        2. Mid-execution at t=0.4s, simulate paramedic interruption: 'Patient flatlined!'.
        3. Verify queued Rime audio stops promptly (cutoff latency < 60ms).
        4. Verify stale dopamine calculation is fenced and NOT spoken.
        5. Verify asystole protocol is delivered immediately without stale state corruption.
        """
        # Launch turn 1 (dopamine drip with 2s delay) in background
        task1 = asyncio.create_task(
            self.agent.handle_user_speech("Calculate dopamine inotrope drip for 15kg patient")
        )

        # Allow calculation to start running
        await asyncio.sleep(0.4)

        # Paramedic interrupts loudly due to cardiac arrest
        t_barge_in = time.perf_counter()
        turn2_result = await self.agent.handle_user_speech(
            user_text="Stop! Patient flatlined, start asystole protocol!",
            was_speaking=True,
            playback_duration_sec=0.4
        )
        t_recovered = time.perf_counter()

        # Let task 1 complete in the background
        await task1

        # 1. Verify Cutoff Latency < 60ms
        interruption_event = turn2_result["interruption_event"]
        self.assertIsNotNone(interruption_event)
        self.assertLess(interruption_event.cutoff_latency_ms, 60.0,
                        f"Cutoff latency too high: {interruption_event.cutoff_latency_ms}ms")

        # 2. Verify stale dopamine calculation was intercepted by tool fence
        fenced_events = self.agent.fence_manager.fenced_events
        dopamine_events = [e for e in fenced_events if e.tool_name == "calculate_pediatric_dopamine_infusion"]
        self.assertTrue(len(dopamine_events) > 0, "Dopamine tool event was not tracked in fence logs.")
        self.assertIn(dopamine_events[0].status, ["DISCARDED_STALE", "CANCELLED_IN_FLIGHT"],
                      "Stale tool result was not intercepted/cancelled by turn fence!")

        # 3. Verify turn 2 delivered immediate resuscitation advice
        self.assertEqual(turn2_result["status"], "COMPLETED")
        self.assertIn("Asystole is not shockable", turn2_result["spoken_response"])
        self.assertIn("Resume chest compressions", turn2_result["spoken_response"])

        # 4. Verify conversation state consistency (no stale dopamine drip advice)
        assistant_responses = [m["content"] for m in self.agent.conversation_history if m["role"] == "assistant"]
        for resp in assistant_responses:
            self.assertNotIn("milliliters per hour", resp, "CRITICAL ERROR: Stale dopamine advice leaked into conversation!")

    async def test_03_auditory_state_accounting(self):
        """Verify that conversation history reflects only what the clinician actually heard."""
        tracker = self.agent.fence_manager.auditory_tracker
        prompt = "Administer one milligram of epinephrine IV and resume two minutes of high quality chest compressions"
        tracker.start_speaking(prompt)
        
        # Clinician interrupts after 1.5 seconds (approx 4 words heard)
        spoken, fenced = tracker.truncate_on_interruption(playback_duration_sec=1.5, estimated_wps=3.0)
        self.assertIn("Administer one milligram", spoken)
        self.assertIn("chest compressions", fenced)
        self.assertFalse(tracker.is_speaking)

if __name__ == "__main__":
    unittest.main()
