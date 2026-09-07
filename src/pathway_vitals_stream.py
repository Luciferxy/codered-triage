"""Pathway streaming pipeline: Continuous monitoring of patient vitals & cardiac arrest detection."""

from __future__ import annotations
import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import pathway as pw

FIXTURE_CSV = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_vitals.csv"

@dataclass
class PatientVitalSample:
    timestamp_sec: int
    heart_rate_bpm: int
    systolic_bp: int
    diastolic_bp: int
    spo2_pct: int
    rhythm_state: str
    is_cardiac_arrest: bool

class PathwayVitalsSchema(pw.Schema):
    timestamp_sec: int
    heart_rate_bpm: int
    systolic_bp: int
    diastolic_bp: int
    spo2_pct: int
    rhythm_state: str

class StreamingVitalsEngine:
    """Simulates real-time telemetry processing using Pathway streaming semantics."""
    def __init__(self, fixture_path: Optional[Path] = None):
        self.fixture_path = fixture_path or FIXTURE_CSV
        self.subscribers: List[Callable[[PatientVitalSample], Any]] = []
        self._is_running = False
        self._current_sample: Optional[PatientVitalSample] = None
        self._previous_rhythm: Optional[str] = None

    def subscribe(self, callback: Callable[[PatientVitalSample], Any]):
        self.subscribers.append(callback)

    def get_latest_vitals(self) -> Optional[PatientVitalSample]:
        return self._current_sample

    def load_fixture_samples(self) -> List[PatientVitalSample]:
        samples = []
        if not self.fixture_path.exists():
            return samples
        with open(self.fixture_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                hr = int(row["heart_rate_bpm"])
                rhythm = row["rhythm_state"]
                is_arrest = ("ASYSTOLE" in rhythm) or ("VENTRICULAR_FIBRILLATION" in rhythm) or (hr == 0)
                samples.append(PatientVitalSample(
                    timestamp_sec=int(row["timestamp_sec"]),
                    heart_rate_bpm=hr,
                    systolic_bp=int(row["systolic_bp"]),
                    diastolic_bp=int(row["diastolic_bp"]),
                    spo2_pct=int(row["spo2_pct"]),
                    rhythm_state=rhythm,
                    is_cardiac_arrest=is_arrest
                ))
        return samples

    async def run_stream(self, interval_sec: float = 1.0, loop_forever: bool = False):
        """Simulates continuous telemetry arrival and reactive Pathway thresholding."""
        self._is_running = True
        samples = self.load_fixture_samples()
        
        while self._is_running:
            for sample in samples:
                if not self._is_running:
                    break
                self._current_sample = sample
                
                # Check for critical cardiac rhythm transition
                if self._previous_rhythm and self._previous_rhythm != sample.rhythm_state:
                    if sample.is_cardiac_arrest:
                        # Critical cardiac arrest transition alert
                        pass
                self._previous_rhythm = sample.rhythm_state
                
                # Dispatch to subscribers (e.g., LiveKit agent, Web Trauma Console)
                for cb in self.subscribers:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(sample)
                        else:
                            cb(sample)
                    except Exception:
                        pass
                
                await asyncio.sleep(interval_sec)
            
            if not loop_forever:
                break

    def stop(self):
        self._is_running = False
