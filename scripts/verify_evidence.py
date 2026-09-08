"""Automated evidence runner: Produces verified, reproducible metrics for RIME_EVIDENCE.md.

Measurements are labeled with their methodology:
- Barge-in cutoff: In-process timing of fence manager's cancel logic via time.perf_counter()
- Rime TTFA: Real network latency if API key is present, simulated if offline
- Stale leakage: Deterministic inspection of conversation history
"""

import asyncio
import os
import platform
import sys
import time
from src.agent import CodeRedAgent


async def run_evidence_suite():
    print("================================================================")
    print("      CODERED TRIAGE: RIME_EVIDENCE REPEATABLE RUNNER           ")
    print("================================================================")

    # Environment context
    rime_mode = "Online (Live API)" if os.getenv("RIME_API_KEY") else "Offline Simulation"
    print(f"\n  Environment:")
    print(f"    Python:       {sys.version.split()[0]}")
    print(f"    Platform:     {platform.system()} {platform.machine()}")
    print(f"    Rime Mode:    {rime_mode}")
    print(f"    LLM Model:    {os.getenv('OPENROUTER_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b:free')}")

    agent = CodeRedAgent()
    all_passed = True

    # 1. Baseline Normal Turn (Uncached)
    t0 = time.perf_counter()
    normal_res = await agent.handle_user_speech("Calculate pediatric epinephrine for 15kg child")
    t_normal_e2e_ms = (time.perf_counter() - t0) * 1000.0

    print("\n[TEST 1] NORMAL END-TO-END CLINICAL TURN")
    print(f"  Input Prompt:         'Calculate pediatric epinephrine for 15kg child'")
    print(f"  Rime Model:           {normal_res['provider_metadata']['model_id']} ({normal_res['provider_metadata']['speaker']})")
    ttfa = normal_res['ttfa_ms']
    ttfa_method = "Network (live Rime API)" if os.getenv("RIME_API_KEY") else "Simulated (offline benchmark)"
    print(f"  Time-To-First-Audio:  {ttfa:.2f} ms  [{ttfa_method}]")
    print(f"  Total Roundtrip:      {t_normal_e2e_ms:.2f} ms  [In-process, includes tool + TTS]")
    print(f"  Spoken Output:        \"{normal_res['spoken_response'][:70]}...\"")

    # 2. Hard Voice Stress Test: Interruption & Asynchronous Tool-Fence
    print("\n[TEST 2] DELIBERATE FULL-DUPLEX STRESS TEST (TOOL-FENCE & BARGE-IN)")
    print("  Triggering Turn 1: 2.0s asynchronous dopamine calculation...")
    task1 = asyncio.create_task(
        agent.handle_user_speech("Calculate dopamine inotrope drip for 15kg patient")
    )
    
    # Wait 400ms into the 2.0s calculation
    await asyncio.sleep(0.4)
    print("  -> Interruption Injected at t = 400ms: 'Stop! Patient flatlined, start asystole protocol!'")

    t_barge_start = time.perf_counter()
    turn2_res = await agent.handle_user_speech(
        user_text="Stop! Patient flatlined, start asystole protocol!",
        was_speaking=True,
        playback_duration_sec=0.4
    )
    turn1_res = await task1
    t_barge_recovered_ms = (time.perf_counter() - t_barge_start) * 1000.0

    interruption = turn2_res["interruption_event"]
    fenced_events = agent.fence_manager.fenced_events
    stale_dopamine_events = [e for e in fenced_events if e.tool_name == "calculate_pediatric_dopamine_infusion"]

    print(f"\n[MEASUREMENTS & VERIFICATION]")
    print(f"  Methodology: All latencies measured via time.perf_counter() (in-process, monotonic clock)")
    print()

    # Metric 1: Cutoff latency
    cutoff_ms = interruption.cutoff_latency_ms
    cutoff_pass = cutoff_ms < 60.0
    if not cutoff_pass:
        all_passed = False
    print(f"  1. Barge-in Cutoff Latency:          {cutoff_ms:.2f} ms (Target: < 60 ms) -> {'PASS' if cutoff_pass else 'FAIL'}")
    print(f"     [Measures: time to cancel in-flight asyncio tasks + bump turn ID]")

    # Metric 2: Cancelled tasks
    print(f"  2. In-Flight Tasks Cancelled:        {interruption.cancelled_tasks_count}")

    # Metric 3: Tool fencing
    if stale_dopamine_events:
        status = stale_dopamine_events[0].status
        fenced = status in ("DISCARDED_STALE", "CANCELLED_IN_FLIGHT")
        print(f"  3. Stale Tool Quarantined & Fenced:  {fenced} (Status: {status})")
        if not fenced:
            all_passed = False
    else:
        print(f"  3. Stale Tool Quarantined & Fenced:  NO DOPAMINE EVENT FOUND -> FAIL")
        all_passed = False

    print(f"  4. Auditory State Retained Text:     \"{interruption.spoken_text_retained}\"")
    print(f"  5. Auditory State Fenced/Discarded:  \"{interruption.discarded_text_fenced}\"")
    print(f"  6. New Resuscitation Advice Spoken:  \"{turn2_res['spoken_response'][:70]}...\"")
    print(f"  7. Total Recovery to New Speech:     {t_barge_recovered_ms:.2f} ms")
    print(f"     [Measures: interrupt + new turn + tool execution + TTS pre-roll]")

    # Metric 8: Stale leakage
    all_assistant_text = " ".join([m["content"] for m in agent.conversation_history if m["role"] == "assistant"])
    stale_leak = "milliliters per hour" in all_assistant_text or "dopamine" in all_assistant_text
    leak_pass = not stale_leak
    if not leak_pass:
        all_passed = False
    print(f"  8. Stale Dosage Leakage Detected:    {stale_leak} -> {'ZERO LEAKAGE (PASS)' if leak_pass else 'LEAKAGE DETECTED (FAIL)'}")

    print("\n================================================================")
    if all_passed:
        print("  VERIFICATION RESULT: ALL ACCEPTANCE CRITERIA MET             ")
    else:
        print("  VERIFICATION RESULT: SOME CRITERIA FAILED                    ")
    print("================================================================")

if __name__ == "__main__":
    asyncio.run(run_evidence_suite())
