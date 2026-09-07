"""Test Pathway patient telemetry ingestion and cardiac arrest detection."""

import asyncio
import unittest
from src.pathway_vitals_stream import PatientVitalSample, StreamingVitalsEngine

class TestTelemetryStream(unittest.IsolatedAsyncioTestCase):
    async def test_vitals_loading_and_streaming(self):
        engine = StreamingVitalsEngine()
        samples = engine.load_fixture_samples()
        
        self.assertGreater(len(samples), 5)
        # Check first sample
        first = samples[0]
        self.assertEqual(first.rhythm_state, "SINUS_TACHYCARDIA")
        self.assertFalse(first.is_cardiac_arrest)

        # Check cardiac arrest transition sample
        arrest_samples = [s for s in samples if s.is_cardiac_arrest]
        self.assertGreater(len(arrest_samples), 0)
        self.assertEqual(arrest_samples[0].rhythm_state, "ASYSTOLE_CARDIAC_ARREST")
        self.assertEqual(arrest_samples[0].heart_rate_bpm, 0)

    async def test_live_stream_callback(self):
        engine = StreamingVitalsEngine()
        received_samples = []

        async def sample_handler(sample: PatientVitalSample):
            received_samples.append(sample)

        engine.subscribe(sample_handler)
        # Stream 3 samples with rapid 0.05s interval
        stream_task = asyncio.create_task(engine.run_stream(interval_sec=0.05, loop_forever=False))
        await asyncio.sleep(0.2)
        engine.stop()
        await stream_task

        self.assertGreater(len(received_samples), 0)

if __name__ == "__main__":
    unittest.main()
