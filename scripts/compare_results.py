#!/usr/bin/env python3
"""Compare two persisted runs by module and variants, ignoring generated IDs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from result_model import EvidenceError, identity, load_run, outcome, write_new

# This comparison policy is distinct from the runner's configurable release gate.
SEVERITY = {"PASSED": 0, "WARNING": 1, "REVIEW": 2, "SKIPPED": 3, "FAILED": 4}


def compare(baseline, candidate):
    for field in ("component", "scenario", "policy"):
        if baseline.summary.get(field) != candidate.summary.get(field):
            raise EvidenceError(f"Cannot compare runs with different {field}")
    old = {identity(row): row for row in baseline.rows}
    new = {identity(row): row for row in candidate.rows}
    changes = []
    regressions = 0
    missing = 0
    for key in sorted(old.keys() | new.keys()):
        before = outcome(old[key]) if key in old else None
        after = outcome(new[key]) if key in new else None
        if before == after:
            continue
        if after is None:
            kind = "removed"
            missing += 1
        elif before is None:
            kind = "added"
            regressions += after in ("FAILED", "REVIEW", "SKIPPED")
        elif "ERROR" in (before, after):
            kind = "infrastructure-change"
        elif SEVERITY[after] > SEVERITY[before]:
            kind = "regression"
            regressions += 1
        else:
            kind = "improvement"
        changes.append({"component": key[0], "plan": key[1], "test_name": key[2],
                        "variants": json.loads(key[3]), "before": before, "after": after, "kind": kind})
    incomplete = missing or not old or not new or baseline.exit_code == 2 or candidate.exit_code == 2
    exit_code = 2 if incomplete else 1 if regressions else 0
    return {"kind": "persisted-result-comparison", "status": {0: "NO_REGRESSION", 1: "REGRESSION", 2: "INCOMPLETE"}[exit_code],
            "exit_code": exit_code, "regressions": regressions, "removed_modules": missing,
            "baseline_gate_exit": baseline.exit_code, "candidate_gate_exit": candidate.exit_code,
            "baseline_modules": len(old), "candidate_modules": len(new), "changes": changes,
            "notice": "No regression does not mean a passing release gate or independent evidence verification."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(load_run(args.baseline), load_run(args.candidate))
        write_new(args.output, json.dumps(result, indent=2) + "\n")
        print(f'{result["status"]}: {result["regressions"]} regression(s); {args.output}')
        return result["exit_code"]
    except (OSError, ValueError) as exc:
        print(f"COMPARISON ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
