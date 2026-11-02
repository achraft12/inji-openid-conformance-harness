#!/usr/bin/env python3
"""One-command Certify conformance run, gated on live Phase-1 verification."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from phase1 import compose_command, execute
from prepare import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("certify",), default="certify")
    parser.add_argument("--scenario", choices=("metadata", "preauthorized"), default="metadata")
    parser.add_argument("--existing-environment", action="store_true", help="Check the existing stack instead of starting it")
    parser.add_argument("--module-timeout", type=float, default=240)
    args = parser.parse_args()
    if args.module_timeout <= 0:
        parser.error("--module-timeout must be positive")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "results/certify" / stamp
    try:
        output.mkdir(parents=True)
        phase1 = [sys.executable, str(ROOT / "scripts/phase1.py"), "--component", "certify"]
        if args.existing_environment:
            phase1.append("--check")
        # No flag bypasses readiness. Missing Docker never creates an OIDF plan.
        execute(phase1, output / "phase1.log", timeout=4200)
        compose = compose_command("certify")
        execute(compose + ["build", "certify-runner"], output / "runner-build.log", timeout=900)
        command = compose + ["run", "--rm", "--no-deps", "-T", "certify-runner",
            "--scenario", args.scenario, "--module-timeout", str(args.module_timeout),
            "--output", f"/results/certify/{stamp}/execution"]
        print(f"Running Certify {args.scenario}; evidence: {output}", flush=True)
        # This initial phase selects one module. Leave budget for HTTP readiness,
        # plan creation, cancellation, log retrieval and the signed result export.
        process = execute(command, output / "runner.log", timeout=int(args.module_timeout) + 360, check=False)
        path = output / "execution/summary.json"
        if not path.exists():
            raise RuntimeError("Runner produced no summary; see runner.log")
        summary = json.loads(path.read_text(encoding="utf-8"))
        if process.returncode not in (0, 1, 2) or process.returncode != summary.get("exit_code"):
            raise RuntimeError("Runner exit code and persisted summary disagree")
        print(f"Certify {args.scenario}: {summary['status']} (exit {process.returncode})")
        return process.returncode
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"INFRASTRUCTURE ERROR: {exc}", file=sys.stderr)
        if output.is_dir():
            (output / "orchestration-error.json").write_text(json.dumps({"status": "ERROR", "exit_code": 2,
                "error": f"{type(exc).__name__}: {exc}"}, indent=2) + "\n", encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
