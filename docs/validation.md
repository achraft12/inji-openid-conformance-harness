# Submission verification snapshot: 2026-11-02

The latest recorded live build is `results/phase1/20261101T204822.229878Z/`.
It established the following additional facts after the earlier installation
checks below:

* Verify compiled and its source image was exported successfully.
* OIDF compiled 4,409 Java source files and its source image was exported.
* Certify's integration API and core compiled; the service build was interrupted
  when the Docker connection closed with `rpc error ... EOF`.
* Both real PostgreSQL initialization checks passed in disposable containers.
  The Certify query returned `ConformanceSDJWT | dc+sd-jwt | ES256`.
* A separate temporary Verify runtime returned `{"status":"UP"}`. Its project
  was removed after saving evidence.
* The built proxy passed `nginx -t` with the generated certificate/key mounted.

The interrupted full-stack attempt did not produce a passing readiness summary.
No real OIDF module or TestNG bridge was executed. Curated source evidence is
included under `submission/evidence/`; these environment checks are not protocol
results. The submission builder reruns the 29 local tests, verifies archive
integrity and includes a SHA-256 file manifest.

# Earlier installation verification: 2026-11-01

Docker Desktop was installed per user using the WSL 2 backend. Verified:

* Docker CLI and Linux engine: 29.9.2.
* Docker Compose: v5.6.1.
* `docker run --rm hello-world`: successful image pull and container execution.
* `docker compose --profile certify --profile verify config --quiet`: passed.
* Active context: `desktop-linux`; engine reports Linux, 16 CPUs and about
  7.4 GiB available memory.

At the time of these initial installation checks, application builds and live
readiness had not run. The newer snapshot above records subsequent progress.

# Preparation validation recorded on 2026-10-30

These checks ran on the Windows preparation host. They do not establish that
the Docker environment starts or that either application conforms to OpenID.

| Check | Command / evidence | Result |
| --- | --- | --- |
| Source provenance | `python scripts/prepare.py` compares Git HEADs with `sources.lock.json`, rejects dirty trees, and prepares config/TLS | PASS |
| Python syntax | `python -m py_compile scripts/prepare.py scripts/probe.py scripts/phase1.py tests/test_phase1.py` | PASS |
| Focused harness tests | `python -m unittest discover -s tests -v` after installing `requirements-conformance.txt` | 29 passed (13 Phase-1 + 16 Phase-2) |
| Compose schema | PyYAML parse + `jsonschema.validate` against the official Compose schema | PASS |
| Bash syntax | Git Bash `bash -n run-phase1.sh` | PASS |
| Phase-2 syntax | Python compilation of `certify_runner.py`, `run_conformance.py`, `probe.py`, `test_certify_runner.py`; Git Bash `bash -n run-conformance.sh` | PASS |
| SD-JWT type metadata | Validated `config/certify-sdjwt-type.json` against the pinned OIDF `json-schemas/sdjwtvc/type_metadata.json` | PASS |
| Preparation mode | `python scripts/phase1.py --prepare-only` | Exit 0; PREPARED; runtime unverified |
| Missing-Docker behavior | `python scripts/phase1.py` with process return code captured | Exit 2; infrastructure error and traceback retained |
| One-command Phase-2 gate | `python scripts/run_conformance.py --component certify` | Exit 2; Phase-1 diagnostics retained; protocol container not launched |
| Upstream changes | `git -C upstream/<repository> status --short` for all four checkouts | Clean |

Compose schema reference: [official schema](https://github.com/compose-spec/compose-spec/blob/main/schema/compose-spec.json),
Git blob SHA `44bbc2710502200b78a3e7793369a771d1ed7356`, copied to ignored
`.runtime/compose-spec.json` for this check. The validation command was:

```bash
python -c "import json,yaml,jsonschema; from pathlib import Path; jsonschema.validate(yaml.safe_load(Path('compose.yaml').read_text()),json.loads(Path('.runtime/compose-spec.json').read_text()))"
```

The focused tests cover CA signatures/SANs, repeat preparation without key
rotation, rejection of incomplete/mismatched TLS material, incompatible LDP
metadata, external authorization servers, malformed endpoint paths, missing
binding/signing/proof metadata, unavailable final-spec modules, network errors,
component-profile dependencies, missing bind sources, loopback-only published
ports, and evidence/exit-code behavior. They use synthetic metadata solely as
unit-test fixtures; no fixture is emitted as a conformance result.

Phase-2 tests use the real pinned official Python helpers through mocked HTTP
transport. They verify endpoint/query/body mechanics, authoritative results,
transaction-code/credential-offer handoffs, no repeated one-time submissions,
OIDF-token separation, URL restrictions, timeouts/cancellation, source-plan
selection, export ZIP parsing, log/export failures and both readiness gates.
The Windows sandbox prevented asyncio's local socket-pair initialization;
tests passed outside that sandbox without contacting external services.
Upstream httpx usage emits a deprecation warning for raw `data=` payloads; the
official source is unchanged and the request bodies are checked by the tests.

Not run: Docker Compose's own model validation, nginx execution, image builds,
upstream Java/Maven tests, database SQL execution, live Actuator/metadata/JWKS
checks, cross-container HTTPS, any OIDF module, TestNG/Extent reports, MinIO/S3
uploads, or CI. Docker is absent; the user selected running those checks after
installation. See `docs/phase1.md` for the exact live verification commands.
