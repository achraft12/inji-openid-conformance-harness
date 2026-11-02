# Submission demo

## 1. Show the architecture and scope

Open `SUBMISSION.md`. Explain that the harness orchestrates official OIDF tests;
it does not implement its own OpenID4VCI/OpenID4VP protocol test logic. Point out
the implemented issuer path and the explicitly incomplete verifier/reporting
integrations.

## 2. Show recorded live evidence without Docker

```bash
python scripts/show_submission.py
```

This displays recorded build/runtime checks, not a new live execution and not
OIDF test results. Show `submission/evidence/verify-runtime-health.json`, the
database results, nginx validation and the final build interruption. Do not
describe Verify's health check as a conformance pass.

## 3. Run the local automation tests

After fetching the pinned upstream sources and installing dependencies:

```bash
python -m unittest discover -s tests -v
```

Explain the distinction: these check orchestration, official-client HTTP
contracts and error handling using fixtures. They establish harness behavior,
not application protocol compliance.

## 4. Attempt the live issuer run when the environment is available

```bash
python scripts/run_conformance.py --component certify
```

Show the timestamped directory under `results/certify/`. A successful run should
contain the actual OIDF module ID, original lifecycle/result, logs, normalized
row and official export. The submission snapshot does not contain such a run.
An infrastructure failure must return 2; it must not print a conformance pass.

## Suggested closing statement

“We have implemented and locally tested the issuer automation layer and
validated several real environment components. Full-stack readiness and real
conformance execution remain the next acceptance tests. Our failure-transparent
design preserves those gaps instead of manufacturing a green demo.”
