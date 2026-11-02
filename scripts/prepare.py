#!/usr/bin/env python3
"""Prepare Phase 1 without Docker or changing upstream application files."""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("certify.conformance.test", "verify.conformance.test", "oidf.conformance.test")


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def check_sources(root: Path = ROOT, fetch: bool = False) -> dict:
    lock = json.loads((root / "sources.lock.json").read_text(encoding="utf-8"))
    for name, source in lock.items():
        path = root / "upstream" / name
        if not path.exists() and fetch:
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--no-checkout", "--filter=blob:none",
                            "--single-branch", "--branch", source["branch"],
                            source["url"], str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "checkout", "--detach", source["commit"]], check=True)
        if not (path / ".git").exists():
            raise RuntimeError(f"Missing {name}; run prepare.py --fetch-sources")
        actual = git(path, "rev-parse", "HEAD")
        if actual != source["commit"]:
            raise RuntimeError(f"{name}: expected {source['commit']}, found {actual}; no automatic reset performed")
        if git(path, "status", "--porcelain"):
            raise RuntimeError(f"{name}: checkout has changes; refusing to build unrecorded source")
    return lock


def prepare_tls(directory: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f for f in ("ca.crt", "ca.key", "server.crt", "server.key")]
    if any(p.exists() for p in paths):
        if not all(p.exists() for p in paths):
            raise RuntimeError("Incomplete local TLS material; restore the missing files or use a new runtime directory")
        ca = x509.load_pem_x509_certificate(paths[0].read_bytes())
        cert = x509.load_pem_x509_certificate(paths[2].read_bytes())
        ca_key = serialization.load_pem_private_key(paths[1].read_bytes(), password=None)
        server_key = serialization.load_pem_private_key(paths[3].read_bytes(), password=None)
        if ca.public_key().public_numbers() != ca_key.public_key().public_numbers():
            raise RuntimeError("Local CA key/certificate mismatch")
        if cert.public_key().public_numbers() != server_key.public_key().public_numbers():
            raise RuntimeError("Local server key/certificate mismatch")
        cert.verify_directly_issued_by(ca)
        dns = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if not set(HOSTS).issubset(dns.get_values_for_type(x509.DNSName)):
            raise RuntimeError("Local certificate SANs do not cover the canonical service names")
        if min(ca.not_valid_after_utc, cert.not_valid_after_utc) < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1):
            raise RuntimeError("Local TLS certificates are expired or expiring; renew explicitly and rebuild images")
        return
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Inji local conformance CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOSTS[0])])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name)
            .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in HOSTS]
                           + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .sign(ca_key, hashes.SHA256()))
    for path, key in ((paths[1], ca_key), (paths[3], server_key)):
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        os.chmod(path, 0o600)
    paths[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths[2].write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def prepare(root: Path = ROOT, fetch: bool = False) -> dict:
    lock = check_sources(root, fetch)
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    prepare_tls(runtime / "tls")
    upstream = root / "upstream/inji-certify/docker-compose/docker-compose-injistack"
    default = (upstream / "config/certify-default.properties").read_text(encoding="utf-8")
    override = (root / "config/certify.properties").read_text(encoding="utf-8")
    (runtime / "certify.properties").write_text(default + "\n\n" + override, encoding="utf-8", newline="\n")
    shutil.copyfile(upstream / "config/vp_request_config.json", runtime / "vp_request_config.json")
    (runtime / "provenance.json").write_text(json.dumps({"sources": lock, "phase": 1,
        "runtime_verified": False}, indent=2) + "\n", encoding="utf-8")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-sources", action="store_true")
    args = parser.parse_args()
    try:
        prepare(fetch=args.fetch_sources)
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"INFRASTRUCTURE ERROR: {exc}")
        return 2
    print("Phase-1 files prepared. Runtime health remains unverified until run-phase1.sh succeeds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
