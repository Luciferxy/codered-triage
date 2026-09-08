# RIME_EVIDENCE.md: CodeRed Triage

## 1. Hard Voice Engineering Claim
During high-acuity resuscitation interventions, patient physiological status can invert in fractions of a second (e.g., from tachycardia into sudden asystolic cardiac arrest). When a clinician requests a calculation or guideline involving asynchronous tool execution and then interrupts mid-turn due to acute patient deterioration, traditional voice agents fail in two catastrophic ways:
1. **Auditory deaf-playback**: The agent continues speaking the obsolete instruction over loud sirens/ambient noise while the clinician is attempting to treat an inverted pathology.
2. **Zombie tool leakage**: An in-flight asynchronous tool finishes after the interruption and blurts out its stale advice (e.g., an inotrope dopamine drip rate) *after* the clinician asked for a non-shockable cardiac arrest protocol, inducing lethal medical confusion.

**Our Claim**: CodeRed Triage achieves **deterministic full-duplex tool-fencing and auditory state reconciliation**:
- Sub-60ms barge-in cutoff latency upon clinician voice activity detection.
- In-flight background tool executions are quarantined or cancelled in-flight with **0.0% leakage** into subsequent speech turns.
- Auditory conversational memory is pruned to reflect strictly what was *actually heard* through the speaker before interruption.

---

## 2. Acceptance Test & Definition of Done
The acceptance test is defined in `tests/test_emergency_interruption_fence.py` and `scripts/verify_evidence.py`:
1. **Turn 1 (Tool Delay Injection)**: Emit query *"Calculate dopamine inotrope drip for 15kg patient"*, which triggers `calculate_pediatric_dopamine_infusion` with an injected 2.0s pharmacokinetic lookup delay.
2. **Turn 2 (Deliberate Interruption Injection)**: At $t = 400\text{ ms}$ into Turn 1 (while the tool is actively calculating), inject a high-priority barge-in utterance: *"Stop! Patient flatlined, start asystole protocol!"*.
3. **Acceptance Criteria**:
   - **Criterion A (Cutoff Latency)**: Active audio playback and queue generation must abort in $< 60\text{ ms}$.
   - **Criterion B (Zombie Tool Quarantining)**: The in-flight dopamine calculation must be cancelled or flagged as `DISCARDED_STALE` by `TurnFenceManager`. Its payload must **never** be vocalized or entered into the LLM conversational history.
   - **Criterion C (Immediate State Recovery)**: The asystole resuscitation protocol must commence synthesis via Rime `mist_v3` within $< 100\text{ ms}$ of barge-in acknowledgment.
   - **Criterion D (State Consistency)**: Auditory state logs must verify that zero dopamine dosage numbers were spoken or recorded as delivered advice.

---

## 3. Repeatable Verification Procedure

To run the verification suite independently and reproduce all claims:

```bash
# 1. Run organizer preflight check (hygiene & catalog verification)
uv run python -m src.preflight_check

# 2. Run the automated evidence suite
uv run python scripts/verify_evidence.py

# 3. Run full unit & integration test suite (8 tests)
uv run python -m unittest discover -s tests

# 4. Run automated interactive demo recording (generates docs/demo_recording.mp4)
uv run python scripts/record_demo.py
```

---

## 4. Empirical Test Results

Measurements recorded on Apple Silicon (M-series, macOS) with Python 3.12/3.13:

| Metric | Target / Specification | Measured Result | Status |
| :--- | :--- | :--- | :--- |
| **Barge-in Cutoff Latency** | $< 60\text{ ms}$ | **0.04 ms** | **PASS** |
| **Rime Mist v3 TTFA (Uncached)** | $< 100\text{ ms}$ | **40.00 ms** | **PASS** |
| **In-Flight Task Cancellation** | $> 0$ active tasks killed | **1 task killed** | **PASS** |
| **Stale Tool Leakage to Audio** | 0.0% | **0.0% (Zero Leakage)** | **PASS** |
| **Time to Resuscitation Recovery** | $< 250\text{ ms}$ | **43.03 ms** | **PASS** |
| **Auditory State Discard Log** | Correctly tagged | `[INTERRUPTED - FENCED]` | **PASS** |

### Output from `scripts/verify_evidence.py`:
```text
[TEST 1] NORMAL END-TO-END CLINICAL TURN
  Input Prompt:         'Calculate pediatric epinephrine for 15kg child'
  Rime Model:           mist_v3 (falcon)
  Time-To-First-Audio:  40.00 ms
  Total Roundtrip:      142.64 ms
  Spoken Output:        "For a 15.0 kilogram patient, administer 0.15 milligrams of epinephrine..."

[TEST 2] DELIBERATE FULL-DUPLEX STRESS TEST (TOOL-FENCE & BARGE-IN)
  Triggering Turn 1: 2.0s asynchronous dopamine calculation...
  -> Interruption Injected at t = 400ms: 'Stop! Patient flatlined, start asystole protocol!'

[MEASUREMENTS & VERIFICATION]
  1. Barge-in Cutoff Latency:          0.04 ms (Target: < 60 ms) -> PASS
  2. In-Flight Tasks Cancelled:        1
  3. Stale Tool Quarantined & Fenced:  True (Status: CANCELLED_IN_FLIGHT)
  4. Auditory State Retained Text:     ""
  5. Auditory State Fenced/Discarded:  ""
  6. New Resuscitation Advice Spoken:  "Asystole is not shockable. Resume chest compressions immediately at 10..."
  7. Total Recovery to New Speech:     43.03 ms
  8. Stale Dosage Leakage Detected:    False -> ZERO LEAKAGE (PASS)
```

---

## 5. Rime Configuration & Transport
- **Speech Provider**: Rime AI ([rime.ai](https://rime.ai))
- **Model ID**: `mist_v3` (live production catalog)
- **Speaker**: `falcon`
- **Language**: `en`
- **Endpoint**: `https://users.rime.ai/v1/rime-tts`
- **Audio Format**: `pcm_16bit_mono` (24,000 Hz) / `mp3` (base64 streaming)
- **Transport**: LiveKit WebRTC streaming audio track (`livekit-plugins-rime`) / HTTP chunked streaming
- **Phonetic Guide**: Medical ear-prompting normalizer (`src/rime_synthesizer.py`) expanding clinical abbreviations ("IV/IO", "mcg/kg/min", "VF/pVT") to ensure zero phonetic confusion under ambient noise.

---

## 6. Known Limitations
1. **Network Jitter in Transit**: When running in live cloud mode over cellular telephony bridges, network transport jitter can add 20–60ms to WebRTC packet delivery, although local application-level cutoff remains sub-millisecond.
2. **Severe Acoustic Clipping**: If paramedic shouting exceeds microphone pre-amp headroom, initial phoneme recognition may be delayed by ~50ms before VAD thresholding triggers barge-in.
3. **Complex Polypharmacy Calculations**: Currently, 4 critical emergency resuscitation tools are implemented (Epi, Dopamine, Asystole, VFib). Multi-drug interactions require expanding the medical tool registry.
