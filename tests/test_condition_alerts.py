"""Unit tests for autonomous condition alerts and preemptive tool-fencing."""

import asyncio
import time
import unittest

from src.agent import CodeRedAgent
from src.condition_alerts import ConditionAlertDetector
from src.pathway_vitals_stream import PatientVitalSample


class TestConditionAlerts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = CodeRedAgent()
        self.detector = ConditionAlertDetector(cooldown_sec=10.0)

    def test_01_transition_detection(self):
        """Verify alerts trigger strictly on clinical state transitions."""
        # 1. Baseline Sinus Tachycardia -> No alert
        s1 = PatientVitalSample(0, 132, 94, 62, 94, "SINUS_TACHYCARDIA", False)
        a1 = self.detector.check_sample(s1)
        self.assertIsNone(a1)

        # 2. Continued Sinus Tachycardia -> No alert
        s2 = PatientVitalSample(1, 135, 92, 60, 93, "SINUS_TACHYCARDIA", False)
        a2 = self.detector.check_sample(s2)
        self.assertIsNone(a2)

        # 3. Transition to Ventricular Tachycardia -> URGENT alert
        s3 = PatientVitalSample(6, 160, 78, 50, 89, "VENTRICULAR_TACHYCARDIA", False)
        a3 = self.detector.check_sample(s3)
        self.assertIsNotNone(a3)
        self.assertEqual(a3.severity, "URGENT")
        self.assertEqual(a3.condition, "VENTRICULAR_TACHYCARDIA")
        self.assertIn("carotid pulse", a3.message)

        # 4. Same VT state next tick -> Suppressed (no repeat spam)
        s4 = PatientVitalSample(7, 165, 74, 48, 87, "VENTRICULAR_TACHYCARDIA", False)
        a4 = self.detector.check_sample(s4)
        self.assertIsNone(a4)

        # 5. Transition to Asystole / Cardiac Arrest -> CRITICAL alert
        s5 = PatientVitalSample(10, 0, 0, 0, 74, "ASYSTOLE_CARDIAC_ARREST", True)
        a5 = self.detector.check_sample(s5)
        self.assertIsNotNone(a5)
        self.assertEqual(a5.severity, "CRITICAL")
        self.assertEqual(a5.condition, "ASYSTOLE_CARDIAC_ARREST")
        self.assertTrue(a5.requires_immediate_cpr)
        self.assertIn("flatlined", a5.message)

        # 6. Continued asystole next tick -> Suppressed
        s6 = PatientVitalSample(11, 0, 0, 0, 70, "ASYSTOLE_CARDIAC_ARREST", True)
        a6 = self.detector.check_sample(s6)
        self.assertIsNone(a6)

    def test_02_hypoxia_cooldown(self):
        """Verify hypoxia alerts respect cooldowns and reset upon recovery."""
        detector = ConditionAlertDetector(cooldown_sec=5.0)

        # Normal SpO2
        s1 = PatientVitalSample(0, 80, 120, 80, 98, "NORMAL_SINUS", False)
        self.assertIsNone(detector.check_sample(s1))

        # Sudden hypoxia (SpO2 75%) -> Alert
        s2 = PatientVitalSample(1, 80, 120, 80, 75, "NORMAL_SINUS", False)
        a2 = detector.check_sample(s2)
        self.assertIsNotNone(a2)
        self.assertEqual(a2.condition, "SEVERE_HYPOXIA")

        # Hypoxia continues immediately -> Suppressed
        s3 = PatientVitalSample(2, 80, 120, 80, 74, "NORMAL_SINUS", False)
        self.assertIsNone(detector.check_sample(s3))

        # Recovery (SpO2 95%) -> Resets tracker
        s4 = PatientVitalSample(3, 80, 120, 80, 95, "NORMAL_SINUS", False)
        self.assertIsNone(detector.check_sample(s4))

        # Re-drop into hypoxia -> New alert fires
        s5 = PatientVitalSample(4, 80, 120, 80, 72, "NORMAL_SINUS", False)
        a5 = detector.check_sample(s5)
        self.assertIsNotNone(a5)
        self.assertEqual(a5.condition, "SEVERE_HYPOXIA")

    async def test_03_critical_alert_preempts_inflight_tool(self):
        """Verify that an autonomous telemetry alert preempts in-flight tools and fences stale output."""
        # 1. Start heavy calculation tool (dopamine drip with 2.0s delay) in background
        task1 = asyncio.create_task(
            self.agent.handle_user_speech("Calculate dopamine inotrope drip for 15kg patient")
        )

        # Allow calculation to spin up
        await asyncio.sleep(0.3)

        # 2. Pathway detects asystole transition -> Condition alert fires
        alert_msg = "Critical alert: Patient has flatlined in asystole. Resume chest compressions immediately."
        alert_result = await self.agent.handle_condition_alert(
            alert_text=alert_msg,
            severity="CRITICAL",
            playback_duration_sec=0.3
        )

        # Let task 1 complete in the background
        await task1

        # 3. Verify alert turn completed and preempted previous task
        self.assertEqual(alert_result["status"], "ALERT_DISPATCHED")
        self.assertEqual(alert_result["spoken_response"], alert_msg)
        interruption = alert_result["interruption_event"]
        self.assertIsNotNone(interruption, "Alert must trigger an interruption event on active tasks")
        self.assertLess(interruption.cutoff_latency_ms, 60.0, "Cutoff latency must be sub-60ms")

        # 4. Verify dopamine tool was intercepted by tool fence
        fenced = [e for e in self.agent.fence_manager.fenced_events if e.tool_name == "calculate_pediatric_dopamine_infusion"]
        self.assertTrue(len(fenced) > 0, "Dopamine tool must be logged in fence events")
        self.assertIn(fenced[0].status, ["DISCARDED_STALE", "CANCELLED_IN_FLIGHT"],
                      "In-flight tool must be marked DISCARDED_STALE or CANCELLED_IN_FLIGHT")

        # 5. Verify conversation history integrity
        for msg in self.agent.conversation_history:
            if msg["role"] == "assistant":
                self.assertNotIn("milliliters per hour", msg["content"],
                                 "Stale calculation must NOT enter conversation memory")


if __name__ == "__main__":
    unittest.main()
