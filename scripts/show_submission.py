#!/usr/bin/env python3
"""Show recorded submission evidence; never represents a new live conformance run."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "submission/evidence"
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    tests = json.loads((directory / "harness-tests.json").read_text(encoding="utf-8"))
    print("RECORDED SUBMISSION EVIDENCE - not a live conformance run\n")
    for check in status["checks"]:
        print(f"{check['status']:12} {check['name']}")
    print(f"\nLocal harness tests: {tests['tests_run']} run; exit {tests['exit_code']}")
    print("Genuine OIDF results: NONE RECORDED")
    print("Full mandatory pipeline: INCOMPLETE - see docs/feature-status.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
