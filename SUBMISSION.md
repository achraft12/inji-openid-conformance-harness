# Automated OpenID Conformance Harness for Inji

**Hackathon prototype · submission snapshot: 2026-11-02**

This submission automates environment preparation and an issuer-side path from
Inji Certify to the official OpenID Foundation conformance-suite API. It keeps
protocol testing in the OIDF suite and separates protocol findings from harness
and infrastructure failures.

**Read this first:** this is a tested automation prototype, not the completed
full-stack deliverable. No genuine OIDF conformance result has been recorded.
Verify automation, TestNG bridges, combined execution and CI are still missing.
The included feature matrix makes these boundaries explicit.

## Problem and approach

Manual conformance testing requires separate environments and repeated suite UI
interaction. Our approach puts the services behind local HTTPS, checks readiness
before test creation, wraps the official Python client, automates issuer offer
handoffs, and preserves authoritative per-module results and detailed evidence.

```text
CLI -> live readiness gate -> official OIDF Python client
                                  |
                     plan + module creation / state polling
                                  |
                  Certify preauthorization offer + transaction code
                                  |
                     persisted result + logs + signed export
                                  |
                         configurable benchmark / exit code

Docker: TLS proxy -> Certify / Verify / OIDF
                        |        |       |
                    PostgreSQL PostgreSQL MongoDB
```

## What is implemented

* Exact upstream Git commit locks for both Inji `release-1.0.x` branches,
  MOSIP functional tests and the OIDF public mirror.
* Minimal Compose topology, source-build Dockerfiles, health checks, a private
  local CA, hostname validation, and canonical container DNS aliases.
* Native SD-JWT conformance seed and isolated Certify preauthorization setup,
  without remote eSignet, Mimoto or Inji Web.
* Official OIDF API-client integration for the issuer metadata module and an
  optional preauthorized issuance capability assessment.
* Bounded waits, generated aliases/IDs, fresh credential offers, transaction-code
  handoff, replay protection, per-module normalized JSON, logs and exports.
* Configurable warning/review/skip policy and explicit exit codes: 0 accepted,
  1 rejected OIDF findings, 2 infrastructure or incomplete evidence.
* A local automated test suite covering transport contracts, failure semantics,
  TLS preparation and orchestration. Fixtures are not conformance evidence.

## Evidence and current status

The archive includes `submission/evidence/`; run
`python scripts/show_submission.py` to read its **recorded** status offline.

| Area | Recorded outcome |
| --- | --- |
| Docker Linux execution | `hello-world` succeeded |
| Compose model | Validated by Docker Compose |
| TLS proxy | Image built; `nginx -t` succeeded with generated certificates |
| Certify database | Real initialization passed; `ConformanceSDJWT`, `dc+sd-jwt`, ES256 row verified |
| Verify database | Real initialization passed |
| Verify source/runtime | Source image built; isolated Actuator returned `UP` |
| OIDF source | Source image built; 4,409 Java source files compiled |
| Certify source | Integration API and core compiled; service build interrupted by Docker connection EOF |
| Genuine conformance | Not yet executed |
| Local harness tests | See freshly generated `submission/evidence/harness-tests.json` |

The recorded build interruption is an infrastructure failure. It is neither an
expected protocol failure nor a passing release gate. The original detailed
build log remains in the development workspace; the archive contains selected
build milestones and the terminal error.

## Reproduce

Python 3.11+, Git, a working Linux Docker engine and network access are required.
From the extracted project directory:

```bash
python -m pip install -r requirements-conformance.txt
python scripts/prepare.py --fetch-sources
python -m unittest discover -s tests -v
python scripts/run_conformance.py --component certify
```

The last command builds/checks the environment and then selects the issuer
metadata module. If readiness fails, it stops with exit 2 before creating a plan.
Cold image and Maven downloads can take substantial time. No UI configuration
is required by the implemented issuer flow.

After inspecting a real metadata run, assess issuance with:

```bash
python scripts/run_conformance.py --component certify --scenario preauthorized
```

This optional profile is **not known to pass**: the pinned suite inherits DPoP
and client-authentication expectations that may exceed Certify's isolated
Bearer-token preauthorization implementation. Those gaps are documented rather
than hidden. The selected plain final-spec plans are alpha/non-certifiable;
this project does not claim OpenID certification.

## Required work that remains

1. Complete Certify's source build and obtain full-stack HTTPS readiness.
2. Record real issuer metadata and issuance outcomes; resolve environment issues
   before interpreting protocol gaps.
3. Implement Verify's VP-request/URI-input handoff and real verifier modules.
4. Add and verify per-module TestNG/Extent/EmailableReport bridges in both rigs.
5. Add sequential combined execution and a consolidated cross-component gate.
6. Add GitHub Actions and complete the end-to-end demo/handoff validation.

Expected-failure tracking, result diffs and parallel execution follow those
mandatory steps. They are not presented as implemented features.

## Review guide

* `DEMO.md`: short recorded-evidence and live-run walkthrough.
* `docs/repository-analysis.md`: branch-specific A–H engineering analysis.
* `docs/certify-automation.md`: exact API mechanics and failure semantics.
* `docs/phase1.md`: environment setup and troubleshooting.
* `docs/feature-status.md`: requirement-by-requirement implementation matrix.
* `docs/component-handoff.md`: Certify, Verify and MOSIP integration handoffs.
* `sources.lock.json`: exact source provenance.
* `MANIFEST.sha256` inside the ZIP: checksums for every packaged file.
