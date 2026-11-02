# Phase 1: preparation, verification and handoff

## What is prepared

`sources.lock.json` fixes the four analyzed Git commits. `prepare.py` refuses
different HEADs or dirty checkouts instead of resetting user work. New clones
are opt-in with `--fetch-sources`; existing clean checkouts remain on their
current branch at the locked commit. No upstream application files are edited.

Certify and Verify are built from source in Maven/Java 21 containers. Certify's
embedded Verify core is built from the same locked Verify checkout. The OIDF
server is built from its locked mirror commit. Maven caches are reused; initial
image builds skip upstream tests and **are not a substitute for those tests**.
The Python tests exercise the harness's preparation/error/readiness behavior.

Certify loads the pinned stock default properties plus the small overrides in
`config/certify.properties`. It uses its own preauthorized AS, native
`PreAuthDataProviderPlugin`, native `LoggerAuditService` and a local writable
PKCS12 volume. The source-locked upstream SQL initializes the schema; a second
SQL script removes the demo Farmer row and registers `ConformanceSDJWT` as
`dc+sd-jwt`, with explicit JWK binding, JWT proofs and ES256 signing metadata.
This prepares a valid format selection; successful issuance remains unproven.

Verify retains its default signing keystore. The initial planned protocol
variant is unsigned `redirect_uri` with `direct_post`; do not use this signing
keystore's `test.example.com` identity for an unrelated X.509 client ID.

One private CA and one SAN certificate cover these canonical origins:

| Service | Origin |
| --- | --- |
| Certify | `https://certify.conformance.test:8443` |
| Verify | `https://verify.conformance.test:8443` |
| OIDF | `https://oidf.conformance.test:8443` |

The proxy has network aliases for each name. Java trust stores import the CA
at image build time. The probe and cross-container curl commands verify the CA
and hostname explicitly. They do not set insecure TLS flags. OIDF retains its
own upstream HTTP-client/TLS-test behavior; installing a CA does not rewrite
that behavior or assert public Web PKI trust.

`.runtime/tls/ca.key` stays on the host and is excluded from Docker build
contexts; only the public CA is copied into JVM images. The server private key
is mounted read-only into nginx. Keys are local generated material and ignored
by Git. Preparation preserves existing certificates and rejects incomplete,
mismatched, or expiring material. Renew explicitly before expiration, then
rebuild the images to update Java trust. Do not upload `.runtime/` as an artifact.

Only 127.0.0.1:8443 is published. OIDF's explicit `fintechlabs.devmode=true`
allows unattended local API access with a dummy administrator. The Spring `dev`
profile is not enabled. Keep this deployment local.

## Commands

Run from the harness root:

```bash
python -m pip install -r requirements-phase1.txt
python scripts/prepare.py --fetch-sources
python -m py_compile scripts/prepare.py scripts/probe.py scripts/phase1.py
python -m unittest discover -s tests -p test_phase1.py -v

# Validate the actual Compose model when Docker Compose is installed.
docker compose --profile certify --profile verify config --quiet

# First real build/start/readiness run; startup uses health checks, not sleeps.
python scripts/phase1.py

# Repeat read-only checks against the existing stack.
python scripts/phase1.py --check
docker compose --profile certify --profile verify ps
```

`bash ./run-phase1.sh` calls the same Python orchestrator. Set `PYTHON=python`
if a Bash environment exposes Python by that name instead of `python3`.

`--component certify` starts the Certify profile plus shared OIDF/TLS services.
`--component verify` starts Verify plus shared services. `both` is the default.
Use `--wait-timeout 600` for a slower machine; this is a readiness deadline, not
a fixed startup delay. Image builds have a separate one-hour process deadline.

`--prepare-only` creates local configuration/certificates and provenance without
Docker. A preparation success must not be interpreted as live health. Avoid
changing CA/config between `up` and `--check`; rebuilding is needed for CA changes.

Stop the environment while retaining database/key volumes:

```bash
docker compose --profile certify --profile verify down
```

Upstream initialization SQL runs only for a fresh database volume. If the seed
changes after first startup, plan an explicit disposable-volume reset or
migration; an ordinary restart does not reinitialize it. Do not remove volumes
when preserving evidence or keys matters. The harness never deletes them.

For optional UI inspection, add a host mapping for all three canonical names
to 127.0.0.1 and trust the generated CA in a dedicated test browser profile.
That host-level change is not required by the container-based runner and is not
performed automatically. Access the suite at its canonical HTTPS origin.

## Evidence and pass criteria

Every invocation writes a separate UTC-timestamped directory below
`results/phase1/`. `summary.json` always distinguishes PREPARED, PASS and ERROR,
includes source commits, and records `runtime_verified` and
`conformance_executed`. The latter remains false throughout Phase 1.

A live success requires:

1. A Linux Docker engine and valid Compose configuration.
2. Both DB schemas initialized; selected Java services and OIDF healthy under
   Compose `up --wait`. nginx waits on OIDF; app services start independently
   after their own databases, and the overall wait includes all selected apps.
3. `nginx -t` succeeds.
4. The probe retrieves the expected OIDF final-spec module names, selected
   Actuator health bodies, and (for Certify) canonical issuer/nonce/credential/AS
   metadata, the SD-JWT configuration and a nonempty public JWKS.
5. Requests originating inside OIDF reach each selected app over HTTPS; requests
   inside each app container reach the suite over HTTPS. This proves DNS,
   routing and CA trust for curl. Actual application protocol callbacks and
   Java HTTP behavior remain Phase-2/3 verification work.

Retained files include Compose version/engine checks, build/start output,
Compose service state, nginx validation, readiness JSON, cross-container
responses, image IDs, and container logs. On failures, error/traceback and
available logs are retained. Do not treat these infrastructure checks as
individual OIDF conformance results.

Exit codes in this phase: 0 for the requested preparation or environment checks
completing successfully; 2 for infrastructure failures. Exit 1 for protocol
failures belongs to the separate Phase-2 conformance runner. Phase 1 never
applies a protocol gate. Unsupported command-line syntax uses argparse's normal exit 2.

## Troubleshooting

| Symptom | Inspect / action |
| --- | --- |
| Docker CLI missing | Install/start Docker with Linux containers; preparation remains available without it |
| Docker engine unavailable | Check the selected Docker context and Desktop/WSL engine; see `docker-engine.log` |
| Build fails | Read `compose-up.log`; verify access to Maven Central, Sonatype snapshots, JitPack and Danubetech repositories; no build has been validated on the preparation host |
| Git HEAD mismatch/dirty checkout | Preserve your changes; use a separate checkout matching `sources.lock.json`; the script will not reset it |
| DB unhealthy | Read container logs and `compose-ps.log`; an old volume may predate the conformance seed; verify schema and locale initialization |
| Certify startup fails | Inspect missing property/bean messages, source SNAPSHOT compatibility, `/keys` permissions and key-policy rows |
| TLS trust/SAN failure | Confirm generated SAN names, mounted CA/leaf, and rebuilt Java images; do not use `-k` |
| OIDF module unavailable | Confirm the suite source commit and build; do not substitute an older draft plan |
| Wrong issuer or credential URLs | `mosip.certify.domain.url` must be the HTTPS origin; the service appends `/v1/certify` |
| `ldp_vc` still advertised | Confirm the second SQL script ran on a fresh conformance DB and inspect `credential_config` |
| API reachable on host only | Container localhost is different; use the canonical proxy aliases on the Compose network |
| Probe fails before complete JSON | Read `probe.log`, `error.log` and the proxy/backend logs; a pull error is infrastructure failure |

## Boundary for the next implementation

Live protocol execution must wait until the real Phase-1 checks succeed.
The Phase-2 implementation is now prepared; its entrypoint enforces that gate.
See [Certify automation](certify-automation.md) for commands and API behavior.
Then run one genuine `oid4vci-1_0-issuer-metadata-test` using official
`scripts/conformance.py`, retaining `/api/info/{id}` and logs. Next validate a
preauthorized SD-JWT issuance module, including any real client-authentication
or sender-constraint gap. For Verify, query **live** `/api/runner/{id}` for
`browser.uriInputRequests`, generate the VP request with the correct DTO, and
GET its query string to the supplied suite `submitUrl`.

Only after those live modules complete should the per-module TestNG adapters,
sequential combined runner, benchmark configuration, CI, expected failures and
result diffs be added. Follow the detailed handoffs in the repository analysis.

Reproducibility currently locks application source but not every dependency:
base image tags and externally resolved Maven SNAPSHOT artifacts remain to be
pinned by digest/checksum after a successful build. Save the first working
image IDs and resolved dependencies before treating this as a release pipeline.
