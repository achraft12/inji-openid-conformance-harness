#!/usr/bin/env python3
"""Build/start/check the environment; deliberately does not run conformance tests."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from prepare import ROOT, prepare


def selected_components(component: str) -> list[str]:
    return ["certify", "verify"] if component == "both" else [component]


def compose_command(component: str) -> list[str]:
    command = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    for name in selected_components(component):
        command.extend(["--profile", name])
    return command


def execute(command: list[str], destination: Path, *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    with destination.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed (exit {result.returncode}); see {destination}")
    return result


def cross_container_checks(command: list[str], component: str, output: Path) -> list[dict]:
    targets = [("oidf", name, f"https://{name}.conformance.test:8443/v1/{name}/actuator/health")
               for name in selected_components(component)]
    targets.extend((name, "oidf", "https://oidf.conformance.test:8443/api/runner/available")
                   for name in selected_components(component))
    checks = []
    for source, target, url in targets:
        path = output / f"network-{source}-to-{target}.json"
        execute(command + ["exec", "-T", source, "curl", "--fail", "--silent", "--show-error",
                           "--max-time", "15", "--noproxy", "*", "--cacert", "/tls/ca.crt", url], path)
        body = json.loads(path.read_text(encoding="utf-8"))
        if target != "oidf" and body.get("status") != "UP":
            raise RuntimeError(f"{source} -> {target} actuator did not return UP; see {path}")
        if target == "oidf" and (not isinstance(body, list) or not body):
            raise RuntimeError(f"{source} -> oidf module list is empty or invalid; see {path}")
        checks.append({"source": source, "target": target, "url": url, "status": "PASS"})
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("certify", "verify", "both"), default="both")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--fetch-sources", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check an already started environment")
    parser.add_argument("--wait-timeout", type=int, default=360)
    args = parser.parse_args()
    if args.wait_timeout <= 0:
        parser.error("--wait-timeout must be positive")
    if args.check and args.prepare_only:
        parser.error("--check and --prepare-only cannot be combined")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "results/phase1" / stamp
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f"INFRASTRUCTURE ERROR: Cannot create evidence directory {output}: {exc}", file=sys.stderr)
        return 2
    summary = {"phase": 1, "component": args.component, "status": "ERROR",
               "runtime_verified": False, "conformance_executed": False, "started_at": stamp}
    command = compose_command(args.component)
    docker_ready = False
    try:
        summary["sources"] = prepare(fetch=args.fetch_sources)
        if args.prepare_only:
            summary["status"] = "PREPARED"
            print("Phase 1 prepared. Containers have not been started or verified.")
            return 0
        if not shutil.which("docker"):
            raise RuntimeError("Docker CLI is unavailable. Install/start Docker with Linux containers, then rerun this command.")
        execute(["docker", "compose", "version"], output / "compose-version.log", timeout=20)
        execute(["docker", "info", "--format", "{{.OSType}}"], output / "docker-engine.log", timeout=20)
        if (output / "docker-engine.log").read_text(encoding="utf-8").strip() != "linux":
            raise RuntimeError("A Linux Docker engine is required")
        docker_ready = True
        execute(command + ["config", "--quiet"], output / "compose-validation.log")
        if not args.check:
            print(f"Building and starting {args.component}; logs: {output / 'compose-up.log'}", flush=True)
            execute(command + ["up", "--build", "--detach", "--wait", "--wait-timeout", str(args.wait_timeout)],
                    output / "compose-up.log", timeout=3600)
        execute(command + ["ps", "--all", "--format", "json"], output / "compose-ps.json")
        execute(command + ["exec", "-T", "tls-proxy", "nginx", "-t"], output / "nginx-validation.log")
        execute(command + ["run", "--rm", "--no-deps", "-T", "probe", "--component", args.component],
                output / "probe.log", timeout=180)
        # Compose output can include image-pull messages; JSON itself is emitted
        # by the probe on stdout. Keep it separate from Compose's stderr.
        # Re-run is unnecessary: extract the JSON from the retained log.
        probe_text = (output / "probe.log").read_text(encoding="utf-8")
        start = probe_text.find('{\n  "phase"')
        if start < 0:
            raise RuntimeError("Readiness probe produced no structured report")
        report, _ = json.JSONDecoder().raw_decode(probe_text[start:])
        if report.get("status") != "PASS":
            raise RuntimeError("Readiness probe did not pass; see probe.log")
        (output / "readiness.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        summary["network_checks"] = cross_container_checks(command, args.component, output)
        execute(command + ["images", "--format", "json"], output / "images.json")
        summary.update(status="PASS", runtime_verified=True)
        for component in selected_components(args.component):
            print(f"Inji {component.capitalize()}: UP (HTTPS checked)")
        print("OpenID suite: UP; cross-container HTTPS checks passed.")
        print("Phase 1 verified. No conformance tests have been executed.")
        return 0
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"INFRASTRUCTURE ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        # Diagnostics must never replace the original exit code or exception.
        if docker_ready:
            for suffix, options in (("compose-ps.log", ["ps", "--all"]),
                                    ("containers.log", ["logs", "--no-color", "--tail", "500"])):
                try:
                    execute(command + options, output / suffix, timeout=30, check=False)
                except (OSError, subprocess.SubprocessError) as exc:
                    summary.setdefault("diagnostic_errors", []).append(str(exc))
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {output}")


if __name__ == "__main__":
    raise SystemExit(main())
