"""Medical emergency calculation tools for ACLS/PALS resuscitation."""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any, Dict

# Load protocol definitions
FIXTURES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "acls_protocols.json"

def _get_protocols() -> Dict[str, Any]:
    if FIXTURES_PATH.exists():
        with open(FIXTURES_PATH, "r") as f:
            return json.load(f)
    return {}

async def calculate_pediatric_epinephrine(weight_kg: float, simulated_delay_sec: float = 0.0) -> Dict[str, Any]:
    """Calculate pediatric epinephrine dose for cardiac arrest (0.01 mg/kg, 1:10,000 conc)."""
    if simulated_delay_sec > 0:
        await asyncio.sleep(simulated_delay_sec)
    
    dose_mg = round(min(weight_kg * 0.01, 1.0), 3)
    volume_ml = round(weight_kg * 0.1, 2)
    return {
        "indication": "Pediatric Cardiac Arrest",
        "weight_kg": weight_kg,
        "medication": "Epinephrine (1:10,000)",
        "dose_mg": dose_mg,
        "volume_ml": volume_ml,
        "route": "IV or IO",
        "repeat_interval": "Every 3 to 5 minutes as needed",
        "spoken_summary": f"For a {weight_kg} kilogram patient, administer {dose_mg} milligrams of epinephrine 1 to 10,000, which is {volume_ml} milliliters IV or IO."
    }

async def calculate_pediatric_dopamine_infusion(
    weight_kg: float,
    dose_mcg_kg_min: float = 5.0,
    simulated_delay_sec: float = 2.0
) -> Dict[str, Any]:
    """Calculate continuous dopamine inotrope drip rate. Default simulated delay = 2.0s to simulate complex pharmacokinetic lookup."""
    if simulated_delay_sec > 0:
        await asyncio.sleep(simulated_delay_sec)
    
    total_mcg_min = weight_kg * dose_mcg_kg_min
    # Standard 400 mg in 250 mL D5W = 1600 mcg/mL
    drip_rate_ml_hr = round((total_mcg_min * 60) / 1600.0, 1)
    return {
        "indication": "Cardiogenic Shock Inotropic Support",
        "weight_kg": weight_kg,
        "dose_mcg_kg_min": dose_mcg_kg_min,
        "drip_rate_ml_hr": drip_rate_ml_hr,
        "concentration": "1600 mcg/mL (400 mg in 250 mL D5W)",
        "spoken_summary": f"At {dose_mcg_kg_min} micrograms per kilo per minute for a {weight_kg} kilogram patient, set infusion pump to {drip_rate_ml_hr} milliliters per hour."
    }

async def get_asystole_pea_protocol() -> Dict[str, Any]:
    """ACLS Cardiac Arrest Protocol for non-shockable rhythm (Asystole / PEA)."""
    protocols = _get_protocols()
    cardiac = protocols.get("cardiac_arrest", {}).get("asystole_pea", {})
    return {
        "rhythm": "Asystole / PEA",
        "shockable": False,
        "immediate_action": "Start CPR immediately. Do NOT shock.",
        "medication": "Epinephrine 1 milligram IV or IO every 3 to 5 minutes.",
        "spoken_summary": "Asystole is not shockable. Resume chest compressions immediately at 100 to 120 per minute. Give 1 milligram of epinephrine IV or IO now."
    }

async def get_vf_pvt_protocol(weight_kg: float | None = None) -> Dict[str, Any]:
    """ACLS/PALS Protocol for shockable rhythm (VF / Pulseless VT)."""
    if weight_kg and weight_kg < 35:
        # Pediatric shock dose
        first_shock_j = round(weight_kg * 2.0)
        return {
            "rhythm": "Pediatric VF / Pulseless VT",
            "shockable": True,
            "joules": first_shock_j,
            "spoken_summary": f"Shockable rhythm. Clear patient and deliver {first_shock_j} Joules. Immediately resume CPR after shock."
        }
    return {
        "rhythm": "Adult VF / Pulseless VT",
        "shockable": True,
        "joules": 200,
        "spoken_summary": "Ventricular fibrillation detected. Charge defibrillator to 200 Joules biphasic. Clear patient and deliver shock. Resume CPR immediately."
    }
