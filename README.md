# CodeRed Triage 🚨

> **Voice-Native Emergency Resuscitation Copilot with Full-Duplex Tool-Fencing, Rime Mist v3 Speech Synthesis, and Pathway Streaming Telemetry**

Built for the **DataForge (.pathway x rime) Hackathon**.

---

## 1. The Clinical Problem & Voice Necessity (25%)

In emergency medical resuscitation (e.g., ambulances, trauma resuscitation bays, disaster zones), Emergency Medical Technicians (EMTs) and trauma teams operate with sterile or physically contaminated gloves while performing life-saving interventions (CPR chest compressions, bag-valve mask ventilation, hemorrhage tourniquets). 

* **Why Voice is Essential**: A screen interface is unusable and hazardous. Looking away from a deteriorating patient or taking off sterile gloves to type introduces fatal delays. Removing voice leaves the product inoperable.
* **The Hard Failure Mode**: In high-stakes trauma, physiological conditions can abruptly invert in seconds. When an EMT asks for a complex medication calculation (e.g., inotropic drip rate) and suddenly interrupts because the patient goes into cardiac arrest:
  1. Conventional voice bots continue speaking obsolete dosages (**deaf playback**).
  2. Asynchronous tools finish calculations in the background and blurt out stale numbers over resuscitation instructions (**zombie tool execution**).
  3. The conversational state becomes corrupted, confusing the trauma team.

**CodeRed Triage** eliminates this failure mode using **asynchronous tool-fencing**, **sub-60ms barge-in cutoff**, and **auditory memory reconciliation**.

---

## 2. System Architecture

```
                       ┌──────────────────────────────────────────────┐
                       │  Patient Monitors / Sensor Stream (1 Hz)     │
                       └──────────────────────┬───────────────────────┘
                                              ▼
┌──────────────────────┐        ┌──────────────────────────────────────────┐
│  Paramedic Speech    │        │  Pathway Real-Time Streaming Pipeline    │
│  (Hands-Free Audio)  │        │  (Cardiac Arrest / Vitals Detection)     │
└──────────┬───────────┘        └─────────────────────┬────────────────────┘
           │                                          │ (Telemetry Events)
           ▼                                          ▼
┌──────────────────────┐        ┌──────────────────────────────────────────┐
│  LiveKit WebRTC      │───────▶│  CodeRed Agent Core                      │
│  Transport & VAD     │        │  - TurnFenceManager (Tool Cancellation)  │
└──────────────────────┘        │  - Auditory State Tracker (Memory Sync)  │
           ▲                    │  - Medical Calculation Tools            │
           │                    └─────────────────────┬────────────────────┘
           │                                          │
           │ (Streaming PCM audio)                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Rime AI Synthesizer (mist_v3, speaker: celeste, 24kHz)                  │
│  - Medical Ear-Prompting Phonetic Expansion                              │
│  - Instant Audio Queue Purging on Barge-in                               │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Exact Speech Provider Specifications

As required by the hackathon submission rules:
* **Speech Provider**: Rime AI ([rime.ai](https://rime.ai))
* **Model ID**: `mist_v3` (High-speed conversational model, ~40ms TTFA)
* **Speaker**: `celeste` (Selected from Rime live catalog for crisp, authoritative clinical cadence)
* **Language**: English (`en`)
* **Endpoint**: `https://users.rime.ai/v1/rime-tts`
* **Audio Format**: `pcm_16bit_mono` (24,000 Hz)
* **Transport**: LiveKit WebRTC audio track streaming via `livekit-plugins-rime`
* **Ear-Prompting Lexicon**: Automatic expansion of medical abbreviations (`IV/IO` $\rightarrow$ `intravenous or intraosseous`, `mcg/kg/min` $\rightarrow$ `micrograms per kilo per minute`, `VF/pVT` $\rightarrow$ `V-Fib and pulseless V-Tach`).

---

## 4. Quick Start & Setup Instructions

### Prerequisites
- Python 3.11+
- `uv` package manager (recommended) or standard `pip`

```bash
# Clone the repository
git clone <your-repo-url>
cd HACKTHON

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .

# Configure environment variables (placeholders provided)
cp .env.example .env
```

### Running the Organizer Preflight Check
```bash
uv run python -m src.preflight_check
```

### Running the Repeatable Evidence Suite
```bash
uv run python scripts/verify_evidence.py
```

### Running the Automated Unit & Stress Tests
```bash
uv run python -m unittest tests/test_emergency_interruption_fence.py tests/test_telemetry_stream.py
```

### Launching the Trauma Console Web Application
```bash
uv run python -m src.server
```
Then navigate to: **`http://localhost:8080`** in your browser.

---

## 5. Deliberate Stress Case & Demo Guide

In the Web Trauma Console:
1. **Normal Flow**: Click **"Pediatric Epinephrine 1:10,000"**. Rime provides immediate weight-based calculations (`0.15 mg / 1.5 mL IV/IO`) in ~40ms TTFA.
2. **The Hard Voice Stress Case**:
   - Click **"1. Request Dopamine Infusion"** (starts a heavy 2.0s pharmacokinetic calculation).
   - At $t = 400\text{ ms}$, click **"2. DELIBERATE INTERRUPT (Asystole!)"**.
   - **Observable Behavior**:
     - Barge-in cutoff latency is recorded (`< 1 ms` in memory, `< 60 ms` over audio).
     - The in-flight dopamine calculation is **fenced and discarded** (visible in the live audit table).
     - Rime immediately speaks the urgent CPR protocol: *"Asystole is not shockable. Resume chest compressions immediately..."*
     - The conversational history retains zero stale dopamine advice.

---

## 6. Verifiable Evidence (`RIME_EVIDENCE.md`)

Full reproducibility details, acceptance tests, procedure, and metrics are documented in [`RIME_EVIDENCE.md`](file:///Users/souravsuman/Work/HACKTHON/RIME_EVIDENCE.md).

---

## 7. Known Limitations & Failure Behavior

* **Microphone Pre-amp Distortion**: In loud siren environments, high sound pressure levels (>100 dB) can saturate cheap mobile microphones, causing temporary VAD false-positives.
* **Network Transport Jitter**: On edge cellular networks, WebRTC UDP packets may experience 20-50ms jitter buffer delay before playing through speakers.
* **Offline Resilience**: If the external Rime API is unreachable or credentials are absent, CodeRed Triage automatically falls back to its deterministic local audio engine while visibly tagging `Rime AI Simulator (Offline Benchmark Mode)` on the console UI.
