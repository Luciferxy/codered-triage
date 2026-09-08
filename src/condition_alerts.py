"""Clinical Condition Alerts: Transition detection & emergency voice alert rules.

Monitors real-time telemetry from Pathway and identifies critical clinical
transitions (e.g., Sinus Tach -> V-Tach -> Asystole/Cardiac Arrest, Severe Hypoxia).
Generates prioritized resuscitation alerts for immediate voice delivery.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Optional

from src.pathway_vitals_stream import PatientVitalSample


@dataclass
class ClinicalAlert:
    severity: str  # "CRITICAL", "URGENT", "ADVISORY"
    condition: str
    message: str
    timestamp_sec: int
    requires_immediate_cpr: bool = False
    requires_defibrillation: bool = False


class ConditionAlertDetector:
    """Evaluates vitals samples and fires prioritized clinical alerts on state transitions."""

    def __init__(self, cooldown_sec: float = 15.0):
        self.cooldown_sec = cooldown_sec
        self._previous_rhythm: Optional[str] = None
        self._previous_is_arrest: bool = False
        self._last_alert_time: Dict[str, float] = {}
        self._hypoxia_alerted = False

    def reset(self):
        """Reset state tracking (e.g. for new stream replay)."""
        self._previous_rhythm = None
        self._previous_is_arrest = False
        self._last_alert_time.clear()
        self._hypoxia_alerted = False

    def check_sample(self, sample: PatientVitalSample) -> Optional[ClinicalAlert]:
        """Examines a vitals sample from Pathway and returns a ClinicalAlert if a transition occurred."""
        now = time.time()
        rhythm = sample.rhythm_state.upper()
        alert: Optional[ClinicalAlert] = None

        # Rule 1: Asystole / Cardiac Arrest (Highest Priority)
        is_arrest = sample.is_cardiac_arrest or sample.heart_rate_bpm == 0 or ("ASYSTOLE" in rhythm)
        if is_arrest:
            if not self._previous_is_arrest or self._previous_rhythm != rhythm:
                alert = ClinicalAlert(
                    severity="CRITICAL",
                    condition="ASYSTOLE_CARDIAC_ARREST",
                    message="Critical alert: Patient has flatlined in asystole. Start chest compressions immediately and prepare epinephrine.",
                    timestamp_sec=sample.timestamp_sec,
                    requires_immediate_cpr=True,
                )
                self._last_alert_time["ASYSTOLE"] = now

        # Rule 2: Ventricular Fibrillation (Shockable Arrest)
        elif "VENTRICULAR_FIBRILLATION" in rhythm:
            if self._previous_rhythm != rhythm:
                alert = ClinicalAlert(
                    severity="CRITICAL",
                    condition="VENTRICULAR_FIBRILLATION",
                    message="Critical alert: Ventricular fibrillation detected. Charge defibrillator to 200 joules and prepare to shock immediately.",
                    timestamp_sec=sample.timestamp_sec,
                    requires_defibrillation=True,
                )
                self._last_alert_time["VF"] = now

        # Rule 3: Ventricular Tachycardia (Unstable Tachyarrhythmia)
        elif "VENTRICULAR_TACHYCARDIA" in rhythm:
            if self._previous_rhythm != rhythm:
                alert = ClinicalAlert(
                    severity="URGENT",
                    condition="VENTRICULAR_TACHYCARDIA",
                    message="Urgent alert: Ventricular tachycardia detected with falling blood pressure. Check carotid pulse immediately.",
                    timestamp_sec=sample.timestamp_sec,
                )
                self._last_alert_time["VT"] = now

        # Rule 4: Severe Hypoxia (SpO2 < 80%) when not in cardiac arrest
        elif sample.spo2_pct < 80 and sample.spo2_pct > 0 and not is_arrest:
            last_hypoxia = self._last_alert_time.get("HYPOXIA", 0.0)
            if not self._hypoxia_alerted or (now - last_hypoxia >= self.cooldown_sec):
                alert = ClinicalAlert(
                    severity="URGENT",
                    condition="SEVERE_HYPOXIA",
                    message=f"Alert: Severe hypoxia detected. Oxygen saturation dropped to {sample.spo2_pct} percent. Verify airway and high-flow oxygen.",
                    timestamp_sec=sample.timestamp_sec,
                )
                self._last_alert_time["HYPOXIA"] = now
                self._hypoxia_alerted = True
        elif sample.spo2_pct >= 85:
            self._hypoxia_alerted = False

        # Update state trackers
        self._previous_rhythm = rhythm
        self._previous_is_arrest = is_arrest

        return alert
