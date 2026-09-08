"""Pathway streaming pipeline: Continuous monitoring of patient vitals & cardiac arrest detection.

Uses Pathway's genuine ConnectorSubject → Table → subscribe pipeline to process
telemetry data through Pathway's streaming engine, with computed cardiac arrest
detection as a real Pathway transformation.
"""

from __future__ import annotations
import asyncio
import csv
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

import pathway as pw
from pathway.io.python import ConnectorSubject

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


class VitalsSubject(ConnectorSubject):
    """Replays CSV fixture rows into Pathway's engine at 1 Hz intervals."""

    def __init__(self, fixture_path: Path, interval_sec: float = 1.0, loop_forever: bool = False):
        super().__init__()
        self.fixture_path = fixture_path
        self.interval_sec = interval_sec
        self.loop_forever = loop_forever
        self._stop_event = threading.Event()

    def run(self):
        rows = self._load_rows()
        while not self._stop_event.is_set():
            for row in rows:
                if self._stop_event.is_set():
                    break
                self.next(
                    timestamp_sec=int(row["timestamp_sec"]),
                    heart_rate_bpm=int(row["heart_rate_bpm"]),
                    systolic_bp=int(row["systolic_bp"]),
                    diastolic_bp=int(row["diastolic_bp"]),
                    spo2_pct=int(row["spo2_pct"]),
                    rhythm_state=row["rhythm_state"],
                )
                self.commit()
                time.sleep(self.interval_sec)
            if not self.loop_forever:
                break
        self.close()

    def stop(self):
        self._stop_event.set()

    def _load_rows(self) -> list[dict]:
        rows = []
        if not self.fixture_path.exists():
            return rows
        with open(self.fixture_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows


class StreamingVitalsEngine:
    """Real-time telemetry processing using Pathway's streaming engine.

    Pathway ingests CSV vitals via ConnectorSubject, computes cardiac arrest
    detection as a table transformation, and emits processed rows via subscribe().
    """

    def __init__(self, fixture_path: Optional[Path] = None):
        self.fixture_path = fixture_path or FIXTURE_CSV
        self.subscribers: List[Callable[[PatientVitalSample], Any]] = []
        self._is_running = False
        self._current_sample: Optional[PatientVitalSample] = None
        self._previous_rhythm: Optional[str] = None
        self._queue: asyncio.Queue[PatientVitalSample] = asyncio.Queue()
        self._pw_thread: Optional[threading.Thread] = None
        self._subject: Optional[VitalsSubject] = None

    def subscribe(self, callback: Callable[[PatientVitalSample], Any]):
        self.subscribers.append(callback)

    def get_latest_vitals(self) -> Optional[PatientVitalSample]:
        return self._current_sample

    def load_fixture_samples(self) -> List[PatientVitalSample]:
        """Load samples directly from CSV (used by tests and SSE endpoint)."""
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

    def _run_pathway(self, interval_sec: float, loop_forever: bool):
        """Runs Pathway's engine in a dedicated thread."""
        self._subject = VitalsSubject(
            fixture_path=self.fixture_path,
            interval_sec=interval_sec,
            loop_forever=loop_forever,
        )

        # Build Pathway dataflow graph
        vitals_table = pw.io.python.read(self._subject, schema=PathwayVitalsSchema)

        # Genuine Pathway transformation: compute cardiac arrest flag
        processed = vitals_table.select(
            *pw.this,
            is_cardiac_arrest=pw.if_else(
                (vitals_table.rhythm_state.str.find("ASYSTOLE") >= 0)
                | (vitals_table.rhythm_state.str.find("VENTRICULAR_FIBRILLATION") >= 0)
                | (vitals_table.heart_rate_bpm == 0),
                True,
                False,
            ),
        )

        # Subscribe: push each processed row into the asyncio queue
        loop = self._loop

        def on_change(key: pw.Pointer, row: dict, time: int, is_addition: bool):
            if not is_addition:
                return
            sample = PatientVitalSample(
                timestamp_sec=row["timestamp_sec"],
                heart_rate_bpm=row["heart_rate_bpm"],
                systolic_bp=row["systolic_bp"],
                diastolic_bp=row["diastolic_bp"],
                spo2_pct=row["spo2_pct"],
                rhythm_state=row["rhythm_state"],
                is_cardiac_arrest=row["is_cardiac_arrest"],
            )
            loop.call_soon_threadsafe(self._queue.put_nowait, sample)

        pw.io.subscribe(processed, on_change=on_change)
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)

    async def run_stream(self, interval_sec: float = 1.0, loop_forever: bool = False):
        """Starts Pathway engine in a background thread and dispatches processed rows to subscribers."""
        self._is_running = True
        self._loop = asyncio.get_running_loop()

        # Start Pathway in a background thread
        self._pw_thread = threading.Thread(
            target=self._run_pathway,
            args=(interval_sec, loop_forever),
            daemon=True,
        )
        self._pw_thread.start()

        # Consume processed samples from the queue
        try:
            while self._is_running:
                try:
                    sample = await asyncio.wait_for(self._queue.get(), timeout=interval_sec + 2.0)
                except asyncio.TimeoutError:
                    # Check if Pathway thread has finished
                    if self._pw_thread and not self._pw_thread.is_alive():
                        break
                    continue

                self._current_sample = sample

                # Dispatch to subscribers
                for cb in self.subscribers:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(sample)
                        else:
                            cb(sample)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass

        self._is_running = False

    def stop(self):
        self._is_running = False
        if self._subject:
            self._subject.stop()
