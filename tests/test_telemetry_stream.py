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

    async def test_pathway_stream_callback(self):
        """Verify that Pathway engine processes and dispatches vitals via subscribe."""
        engine = StreamingVitalsEngine()
        received_samples = []

        async def sample_handler(sample: PatientVitalSample):
            received_samples.append(sample)

        engine.subscribe(sample_handler)
        # Stream with fast interval through genuine Pathway pipeline
        stream_task = asyncio.create_task(engine.run_stream(interval_sec=0.05, loop_forever=False))
        await asyncio.sleep(5.0)
        engine.stop()
        await stream_task

        self.assertGreater(len(received_samples), 0, "Pathway engine should dispatch at least one sample")

        # Verify cardiac arrest detection was computed by Pathway
        arrest_samples = [s for s in received_samples if s.is_cardiac_arrest]
        non_arrest = [s for s in received_samples if not s.is_cardiac_arrest]
        self.assertGreater(len(arrest_samples), 0, "Pathway should detect cardiac arrest samples")
        self.assertGreater(len(non_arrest), 0, "Pathway should have non-arrest samples too")


if __name__ == "__main__":
    unittest.main()
