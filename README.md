# Inji OpenID conformance harness

**Submission:** start with [SUBMISSION.md](SUBMISSION.md), the candid
[feature matrix](docs/feature-status.md), and [demo guide](DEMO.md). A packaged
snapshot with recorded evidence can be generated using
`python scripts/build_submission.py`.

Repository analysis, environment preparation and Certify automation for Inji Certify
and Verify `release-1.0.x`, the MOSIP API rig, and the OpenID Foundation suite.

**Status:** environment preparation and the Certify Phase-2 runner are implemented
and locally tested. The Verify and OIDF source images built successfully;
Verify returned UP in an isolated runtime check, both database initialization
checks passed, and nginx configuration validation passed. The full-stack run
was interrupted by Docker connection EOF during Certify's service build.
No genuine conformance tests have run. Live execution remains gated on fresh
Phase-1 readiness. This is a prototype with incomplete mandatory integrations.

Read the [source-backed A–H engineering analysis](docs/repository-analysis.md)
and [Phase-1 commands and troubleshooting](docs/phase1.md).
The [validation record](docs/validation.md) separates completed checks from
pending runtime verification.
See [Certify automation](docs/certify-automation.md) for Phase-2 API mechanics,
known capability gaps, normalized results, benchmark policy and exit codes.

After Docker is installed, run the issuer metadata module unattended:

```powershell
python scripts/run_conformance.py --component certify
```

Or from Bash: `bash ./run-conformance.sh --component certify`. The command checks
the environment before creating a plan. The optional `--scenario preauthorized`
assesses issuance; it is not a known passing profile.

Prerequisites: Python 3.11+, Git, Docker with a Linux engine, Docker Compose v2
supporting `up --wait`, network access to the upstream Maven/image registries.
Allow sufficient Docker memory for three JVMs, Mongo and two PostgreSQL
instances; 8 GB is a starting allocation to validate, not a measured minimum.
Builds use Maven inside containers; host Java/Maven are unnecessary.

```bash
python -m pip install -r requirements-phase1.txt
python scripts/prepare.py --fetch-sources
python -m unittest discover -s tests -p test_phase1.py -v
python scripts/phase1.py
```

From Bash, the last command can also be `bash ./run-phase1.sh`. Python commands
work directly from PowerShell. For independent environments:

```bash
python scripts/phase1.py --component certify
python scripts/phase1.py --component verify
```

Without Docker, use `python scripts/phase1.py --prepare-only`. This reports
`PREPARED`, never runtime `PASS`. A normal start with missing Docker returns `2`
and saves the reason under `results/phase1/<UTC timestamp>/`.

The environment has source-locked apps, two PostgreSQL databases, MongoDB, the
source-locked OIDF Java server, and one TLS nginx ingress. A temporary probe
container checks the canonical HTTPS origins. Databases have no host ports.
Mimoto, Inji Web, remote eSignet, browser automation, and application business
logic changes are unnecessary for this initial setup.

This is not the completed conformance pipeline. Verify automation, `--combined`,
TestNG adapters, GitHub Actions, expected failures and diffs remain later phases.
The pinned plain final-spec OIDF plans are alpha/non-certifiable; formal
self-certification needs the appropriate certifiable profile and OIDF process.
