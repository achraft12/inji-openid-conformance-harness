#!/usr/bin/env python3
"""Test and package the honest hackathon prototype; exclude caches and private keys."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

from prepare import ROOT, check_sources

RUN = ROOT / "results/phase1/20261101T204822.229878Z"
EVIDENCE = ROOT / "submission/evidence"


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def collect_evidence():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    required = ("database-preflight.json", "certify-sql-result.txt", "verify-sql-result.txt",
                "verify-runtime-health.json", "nginx-preflight.log")
    # The archive also supports rebuilding on another machine after extraction,
    # where captured evidence is already included and the original logs are not.
    for name in required:
        source = RUN / name
        if source.exists():
            shutil.copyfile(source, EVIDENCE / name)
        elif not (EVIDENCE / name).exists():
            raise RuntimeError(f"Missing recorded evidence: {name}")
    log = RUN / "compose-up.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        milestones = [line for line in lines if re.search(
            r"BUILD SUCCESS|BUILD FAILURE|Compiling \d+ source|naming to docker.io/library/inji-conformance-|failed to receive status|error reading from server", line)]
        (EVIDENCE / "build-milestones.txt").write_text("\n".join(milestones) + "\n", encoding="utf-8")
    milestones = (EVIDENCE / "build-milestones.txt").read_text(encoding="utf-8")
    health = json.loads((EVIDENCE / "verify-runtime-health.json").read_text(encoding="utf-8-sig"))
    databases = json.loads((EVIDENCE / "database-preflight.json").read_text(encoding="utf-8"))
    nginx = (EVIDENCE / "nginx-preflight.log").read_text(encoding="utf-8-sig")
    checks = [{"name": f"{name} source image", "status": "BUILT" if
               f"naming to docker.io/library/inji-conformance-{name}:local" in milestones else "INCOMPLETE"}
              for name in ("verify", "oidf", "certify")]
    checks += [{"name": "Verify isolated runtime", "status": "UP_RECORDED" if health.get("status") == "UP" else "ERROR"}]
    checks += [{"name": row["component"] + " database initialization", "status": row["status"]}
               for row in databases]
    checks += [{"name": "TLS proxy configuration", "status": "PASS" if "test is successful" in nginx else "ERROR"}]
    save_json(EVIDENCE / "status.json", {"kind": "recorded-environment-evidence", "recorded_run": RUN.name,
        "snapshot_date": "2026-11-02", "genuine_oidf_results": 0,
        "full_stack_readiness_verified": False, "mandatory_pipeline_complete": False,
        "checks": checks, "limitation": "Docker connection closed during Certify service build"})


def run_tests():
    start = time.monotonic()
    process = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                             cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    (EVIDENCE / "harness-tests.txt").write_text(process.stdout, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in", process.stdout)
    count = int(match.group(1)) if match else 0
    report = {"kind": "local-harness-tests-not-conformance", "tests_run": count,
              "exit_code": process.returncode, "duration_seconds": round(time.monotonic() - start, 2),
              "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    save_json(EVIDENCE / "harness-tests.json", report)
    if process.returncode or count < 29:
        raise RuntimeError("Submission test check failed; see submission/evidence/harness-tests.txt")
    print(f"Local harness tests: {count} passed (not OIDF conformance results)", flush=True)


def package():
    roots = ("README.md", "SUBMISSION.md", "DEMO.md", "THIRD_PARTY_NOTICES.md", "sources.lock.json",
             "compose.yaml", "requirements-phase1.txt", "requirements-conformance.txt",
             "run-phase1.sh", "run-conformance.sh", ".gitignore", ".gitattributes", ".dockerignore")
    files = [ROOT / name for name in roots]
    for directory in ("config", "docker", "docs", "scripts", "tests", "submission/evidence"):
        files += [path for path in (ROOT / directory).rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    payload = {}
    for path in sorted(files):
        if path.is_symlink():
            raise RuntimeError(f"Refusing symlink in submission: {path}")
        name = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in (".key", ".p12", ".exe", ".jar"):
            raise RuntimeError(f"Refusing private key or binary in source submission: {name}")
        data = path.read_bytes()
        if re.search(rb"-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----", data):
            raise RuntimeError(f"Private key material detected in {name}")
        payload[name] = data
    manifest = "\n".join(f"{hashlib.sha256(data).hexdigest()}  {name}" for name, data in sorted(payload.items())) + "\n"
    payload["MANIFEST.sha256"] = manifest.encode()
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive_path = destination / "inji-conformance-hackathon-submission.zip"
    prefix = "inji-conformance-harness/"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(prefix + name, date_time=(2026, 11, 2, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if name.endswith((".sh", ".py")) else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity verification failed")
        for name, data in payload.items():
            if archive.read(prefix + name) != data:
                raise RuntimeError(f"Archive content verification failed: {name}")
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    save_json(destination / "package-info.json", {"archive": archive_path.name,
              "sha256": checksum, "files": len(payload), "bytes": archive_path.stat().st_size,
              "upstream_sources_bundled": False, "private_keys_bundled": False})
    print(f"Verified archive: {archive_path} ({len(payload)} files)")


def main():
    try:
        check_sources()
        collect_evidence()
        run_tests()
        package()
        return 0
    except Exception as exc:
        print(f"Submission packaging failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
