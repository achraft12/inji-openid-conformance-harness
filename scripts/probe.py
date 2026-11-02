#!/usr/bin/env python3
"""Read-only Phase-1 checks, run inside the Compose network with CA validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import ssl
import urllib.request

CERTIFY = "https://certify.conformance.test:8443"
VERIFY = "https://verify.conformance.test:8443"
OIDF = "https://oidf.conformance.test:8443"


def validate_metadata(metadata: dict) -> None:
    if metadata.get("credential_issuer") != CERTIFY:
        raise ValueError("Certify issuer differs from canonical HTTPS origin")
    for field, path in (("credential_endpoint", "/issuance/credential"), ("nonce_endpoint", "/nonce")):
        if metadata.get(field) != CERTIFY + "/v1/certify" + path:
            raise ValueError(f"Unexpected {field}: {metadata.get(field)!r}")
    if metadata.get("authorization_servers") != [CERTIFY]:
        raise ValueError("Certify still advertises an external/incorrect authorization server")
    configs = metadata.get("credential_configurations_supported", {})
    config = configs.get("ConformanceSDJWT", {})
    if config.get("format") != "dc+sd-jwt":
        raise ValueError("ConformanceSDJWT is missing or has an incompatible credential format")
    if config.get("vct") != CERTIFY + "/credentials/conformance":
        raise ValueError("ConformanceSDJWT has an incorrect VCT")
    if "ES256" not in config.get("credential_signing_alg_values_supported", []):
        raise ValueError("ConformanceSDJWT must advertise the configured ES256 signer")
    if "jwk" not in config.get("cryptographic_binding_methods_supported", []):
        raise ValueError("ConformanceSDJWT must advertise JWK holder binding")
    if "ES256" not in config.get("proof_types_supported", {}).get("jwt", {}).get("proof_signing_alg_values_supported", []):
        raise ValueError("ConformanceSDJWT must advertise JWT/ES256 proof support")
    if any(c.get("format") == "ldp_vc" for c in configs.values()):
        raise ValueError("Stock LDP credential still present in the isolated conformance database")


def validate_modules(modules: list, component: str) -> None:
    if not isinstance(modules, list):
        raise ValueError("OIDF available-modules API did not return a JSON array")
    names = {m.get("testName") for m in modules if isinstance(m, dict)}
    expected = []
    if component in ("certify", "both"):
        expected.append("oid4vci-1_0-issuer-metadata-test")
    if component in ("verify", "both"):
        expected.append("oid4vp-1final-verifier-happy-flow")
    if missing := set(expected) - names:
        raise ValueError(f"Pinned suite modules unavailable: {sorted(missing)}")


def validate_type_metadata(body):
    if not isinstance(body, dict) or body.get("vct") != CERTIFY + "/credentials/conformance":
        raise ValueError("SD-JWT type metadata does not describe the configured VCT")


def run(component: str, ca: Path) -> dict:
    context = ssl.create_default_context(cafile=str(ca))
    # Docker aliases must resolve directly; host proxy variables must not redirect
    # private service names to a corporate proxy or the public internet.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=context))
    checks = []

    def check(name, url, validate):
        try:
            with opener.open(url, timeout=15) as response:
                payload = json.load(response)
            validate(payload)
            checks.append({"name": name, "url": url, "status": "PASS"})
        except Exception as exc:
            # Preserve each failed check; never convert connection failures into
            # conformance results. This command has no protocol PASS/FAIL logic.
            checks.append({"name": name, "url": url, "status": "ERROR",
                           "error": f"{type(exc).__name__}: {exc}"})

    def up(body):
        if body.get("status") != "UP":
            raise ValueError("Actuator status is not UP")

    def oauth(body):
        expected = {"issuer": CERTIFY,
                    "token_endpoint": CERTIFY + "/v1/certify/oauth/token",
                    "jwks_uri": CERTIFY + "/v1/certify/.well-known/jwks.json"}
        for field, value in expected.items():
            if body.get(field) != value:
                raise ValueError(f"Unexpected OAuth {field}: {body.get(field)!r}")

    def jwks(body):
        keys = body.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("JWKS is empty or malformed")
        if any(any(field in key for field in ("d", "p", "q", "k")) for key in keys):
            raise ValueError("JWKS exposes private or symmetric key material")

    check("oidf-modules", OIDF + "/api/runner/available", lambda body: validate_modules(body, component))
    if component in ("certify", "both"):
        check("certify-health", CERTIFY + "/v1/certify/actuator/health", up)
        check("certify-metadata", CERTIFY + "/.well-known/openid-credential-issuer", validate_metadata)
        check("certify-oauth", CERTIFY + "/.well-known/oauth-authorization-server", oauth)
        check("certify-jwks", CERTIFY + "/v1/certify/.well-known/jwks.json", jwks)
        check("certify-type-metadata", CERTIFY + "/credentials/conformance", validate_type_metadata)
    if component in ("verify", "both"):
        check("verify-health", VERIFY + "/v1/verify/actuator/health", up)
    return {"phase": 1, "kind": "infrastructure-readiness", "component": component,
            "tls_verification": "CA and hostname", "checks": checks,
            "status": "PASS" if checks and all(c["status"] == "PASS" for c in checks) else "ERROR"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("certify", "verify", "both"), default="both")
    parser.add_argument("--ca", type=Path, default=Path("/tls/ca.crt"))
    args = parser.parse_args()
    try:
        report = run(args.component, args.ca)
    except Exception as exc:
        report = {"phase": 1, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
