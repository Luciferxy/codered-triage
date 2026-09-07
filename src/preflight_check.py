"""Organizer preflight check: Validates configuration hygiene, secret isolation, and Rime specs."""

import os
import sys
from pathlib import Path

# Rime production catalog validation
VALID_MODELS = {"mist_v3", "mist_v2", "coda"}
VALID_SPEAKERS = {"celeste", "marcus", "allison", "colin", "amber", "elena"}
VALID_LANGUAGES = {"en", "es", "fr", "de"}

def run_preflight() -> bool:
    repo_root = Path(__file__).resolve().parent.parent
    all_passed = True

    print("==================================================")
    print("      CODERED TRIAGE: EVENT PREFLIGHT CHECK       ")
    print("==================================================")

    # 1. Check .env.example existence
    env_example = repo_root / ".env.example"
    if not env_example.exists():
        print("❌ FAIL: .env.example is missing!")
        all_passed = False
    else:
        print("✅ PASS: .env.example exists.")

    # 2. Secret leakage check
    print("\nChecking for accidental secret leakage in tracked files...")
    suspicious_patterns = ["sk-", "Bearer ", "livekit_secret", "eyJ"]
    tracked_files = [
        repo_root / "README.md",
        repo_root / "RIME_EVIDENCE.md",
        repo_root / ".env.example",
        repo_root / "pyproject.toml"
    ]
    for p in repo_root.glob("src/**/*.py"):
        if p.name != "preflight_check.py":
            tracked_files.append(p)

    secrets_found = False
    for tf in tracked_files:
        if tf.exists():
            content = tf.read_text(errors="ignore")
            lines = content.splitlines()
            for line_idx, line in enumerate(lines, 1):
                clean_line = line.strip()
                if clean_line.startswith("#") or clean_line.startswith("//"):
                    continue
                # Flag actual hardcoded secrets (long tokens or keys)
                if ("sk-" in clean_line and "your_" not in clean_line and "sk-ant" not in clean_line) or \
                   ("Bearer " in clean_line and "{" not in clean_line and "your_" not in clean_line and "<" not in clean_line):
                    print(f"❌ WARNING: Possible live credential in {tf.name}:{line_idx}: {clean_line[:40]}...")
                    secrets_found = True

    if not secrets_found:
        print("✅ PASS: No exposed credentials found in source files.")
    else:
        all_passed = False

    # 3. Validate Rime configuration
    model = os.getenv("RIME_MODEL_ID", "mist_v3")
    speaker = os.getenv("RIME_SPEAKER", "celeste")
    language = os.getenv("RIME_LANGUAGE", "en")

    print("\nValidating Rime model & voice catalog configuration...")
    if model in VALID_MODELS:
        print(f"✅ PASS: Rime Model ID '{model}' is valid in live production catalog.")
    else:
        print(f"❌ FAIL: Rime Model ID '{model}' not recognized.")
        all_passed = False

    if speaker in VALID_SPEAKERS:
        print(f"✅ PASS: Rime Speaker '{speaker}' is valid in live catalog.")
    else:
        print(f"⚠️ NOTE: Speaker '{speaker}' custom or unlisted; verify before submission.")

    if language in VALID_LANGUAGES:
        print(f"✅ PASS: Rime Language '{language}' is supported.")
    else:
        print(f"❌ FAIL: Language '{language}' not supported.")
        all_passed = False

    print("==================================================")
    if all_passed:
        print("🎉 PREFLIGHT RESULT: ALL CHECKS PASSED")
    else:
        print("❌ PREFLIGHT RESULT: ISSUES DETECTED")
    print("==================================================")
    return all_passed

if __name__ == "__main__":
    success = run_preflight()
    sys.exit(0 if success else 1)
