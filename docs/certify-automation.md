# Phase 2: Certify API automation

Implementation status: the runner and its local HTTP contract tests are in
place. **No genuine OIDF module has run yet.** Docker installation and Linux
container execution were verified on 2026-11-01. A live metadata completion and then live issuance completion
are still the acceptance criteria for Phase 2.

## Execute

From PowerShell, after installing and starting Docker with a Linux engine:

```powershell
python -m pip install -r requirements-phase1.txt
python scripts/run_conformance.py --component certify
```

From Bash:

```bash
bash ./run-conformance.sh --component certify
```

The command prepares/builds/starts the Certify environment, runs the Phase-1
readiness/network checks, builds a small Python runner container, and executes
the **issuer metadata module only**. The container supplies Docker DNS and local
CA trust, so no host file edits or conformance-suite UI interaction are needed.
The official Python client and parser come from the pinned OIDF checkout.
No host Java, Maven, httpx or pyparsing installation is needed for this command.

To reuse an environment, while still checking readiness:

```powershell
python scripts/run_conformance.py --component certify --existing-environment
```

Only after a real metadata run has been inspected, try the issuance scenario:

```powershell
python scripts/run_conformance.py --component certify --scenario preauthorized
```

Use `--module-timeout 360` to change the bounded per-module budget. Commands
support Certify only in this phase. Verify, combined execution, TestNG adapters,
CI, expected failures and result diffs remain later implementation work.

For development outside Docker, `requirements-conformance.txt` installs the
runner and test dependencies. Direct execution of `scripts/certify_runner.py`
requires the canonical service names to resolve and an explicit CA path; it
still performs fresh readiness checks and has no bypass flag. Choose a new
`--output` directory for every run. The normal host wrapper handles this.

## Configuration and variants

`config/certify-metadata.json` selects the exact plan
`oid4vci-1_0-issuer-test-plan` and module
`oid4vci-1_0-issuer-metadata-test`, using `fapi_profile=vci` and
`client_auth_type=private_key_jwt`. The latter is a suite selector required by
this module; it is not a claim that Certify implements private-key client auth.

`config/certify-preauthorized.json` selects
`oid4vci-1_0-issuer-happy-flow`, issuer initiated preauthorization,
`credential_format=sd_jwt_vc` (wire format `dc+sd-jwt`), JWT proof and plain
credential responses. Inherited applicable selectors are explicit. OpenID
Connect and FAPI response mode selectors are omitted because the suite excludes
them for `fapi_profile=vci`. The official parser reads the entire selector,
rejecting trailing or malformed syntax; the server remains authoritative for
variant applicability. Module entries returned by the created plan determine
execution, and omitted selected modules cause infrastructure exit 2.

**Issuance is a capability assessment, not a known passing profile.** This suite
inherits private-key/attestation/mTLS client authentication and DPoP/mTLS sender
constraints; it has no simple Bearer selector. The optional scenario selects
private-key JWT and DPoP. Certify's isolated preauthorization token code returns
Bearer tokens and does not issue DPoP-bound tokens. This may cause real OIDF
failures, including during module configuration. Preserve and inspect those
findings rather than switching to an unrelated draft or adding expected failures.
No client registration, sender constraint support, or application capability is
invented by the harness.

Two environment details were corrected while implementing issuance:

* `OAuthController` implements both authorization-code and preauthorized grants.
  The harness now advertises both, matching the existing stock configuration
  and controller. This does not add a browser authorization endpoint or claim
  that the interactive IAR flow satisfies every suite check.
* The seeded VCT is an HTTPS URL. The pinned suite tries to fetch type metadata
  there. `config/certify-sdjwt-type.json` is served by nginx at that exact URL
  with JSON content type, and readiness verifies its VCT. A missing harness
  static document must not be passed off as an application protocol gap.

No application business code, database schema, or upstream checkout is modified.
The existing SD-JWT seed, native cached-claims provider and signer are reused.

## API sequence and interactions

1. Verify readiness, metadata, local AS URLs, SD-JWT configuration, JWKS and type
   metadata. The host also checks cross-container reachability. Failure stops
   before any plan is created.
2. Use official `Conformance.get_all_test_modules()` and `create_test_plan()`.
   Each run generates a new alias, and IDs always come from API responses.
3. Filter the returned plan's module entries using the explicit selector.
   Create modules with `create_test_from_plan_with_variant()` sequentially.
4. These selected modules inherit `AbstractTestModule.autoStart() == true`.
   `TestRunner` configures/starts them in its background task. The harness does
   not race auto-start with a redundant manual POST. It calls the official
   `wait_for_state()` long poll, explicitly including INTERRUPTED.
5. Read `/api/info/{id}` for persisted lifecycle/result. While WAITING, read
   **live** `/api/runner/{id}` for `exposed` interaction URLs.
6. For preauthorization, call Certify POST `/v1/certify/pre-authorized-data`
   with the configured synthetic claims and a newly generated transaction code.
   Validate the returned `openid-credential-offer://` URI and issuer origin;
   GET its original query string to the suite's `credential_offer_endpoint`.
7. When exposed, GET the generated transaction code to `tx_code_endpoint` using
   its exact `code` query field. Only this module's own suite-origin endpoints
   are accepted. Each offer/code submission is attempted once; unchanged
   WAITING states do not replay it. Additional unexpected waits expire with
   infrastructure diagnostics instead of being treated as success.
8. Normalize the authoritative terminal result, retain per-module JSON/logs,
   and use official `exportjson()` to download the signed ZIP from
   **`/api/plan/export/{planId}`**. The helper name is `exportjson`; the actual
   HTTP path is `export`, not `exportjson`.

An HTTP error from a suite interaction may be the result of an OIDF condition
failing while it handles that request. The runner reads persisted state first:
an authoritative terminal FAILED stays a conformance failure; otherwise the
HTTP error remains infrastructure failure.

The official client's default transport retries POSTs on transient errors.
The wrapper retains its API helpers but supplies single-attempt HTTP transport
to avoid creating duplicate plans/modules or replaying one-time handoffs.
TLS validation remains enabled, environment HTTP proxies are not used for local
origins, and redirects are not followed. The OIDF API token is attached only to
the suite client and is never sent to Certify. For this local devmode deployment
no token is needed; `OIDF_API_TOKEN` can supply one via the container environment.

## Results, policy and exit codes

Each run has a new directory under `results/certify/<UTC timestamp>/`:

```text
phase1.log
runner-build.log
runner.log
execution/
  readiness.json
  configuration.json
  sources.lock.json
  plan.json
  results.json
  summary.json
  <official signed export>.zip
  modules/000-<module-name>/
    created.json
    info.json
    logs.json
    result.json
    live.json                         # when interaction was needed
    credential-offer.json              # issuance only
    preauthorization-response.txt      # issuance only
    offer-response.txt / tx-response.txt
    error.log                         # on infrastructure failure
```

The wrapper's `orchestration-error.json` and Phase-1 evidence are retained when
Docker/build/readiness prevents the protocol runner from starting. Output
directories cannot be reused or overwrite earlier evidence.

`results.json` has one row per selected plan module/variant and retains plan ID,
module ID, original lifecycle, original OIDF result, normalized visualization
status, details URL and any infrastructure error. Live/log/config data stays
available for diagnosis. These files can contain issued test credentials,
transaction codes and access tokens; use synthetic identities and restrict
artifact access. Never upload local CA private keys with reports.

| Authoritative OIDF outcome | Normalized visualization | Default gate |
| --- | --- | --- |
| PASSED with FINISHED | PASS | Accept |
| FAILED with FINISHED or INTERRUPTED | FAIL | Reject |
| SKIPPED with FINISHED | SKIP | Reject |
| WARNING with FINISHED | SKIP, raw WARNING retained | Accept |
| REVIEW with FINISHED | SKIP, raw REVIEW retained | Reject |
| Missing/UNKNOWN result, nonterminal or unclassified interruption | No synthetic result | Infrastructure error |

`config/benchmark.json` controls the failure threshold and warning/review/skip
policy. An empty run, entirely skipped run, incomplete export, missing logs,
invalid configuration, timeout or failed cancellation cannot become green.
There is no expected-failure mechanism in this phase.

Process exit codes: **0** gate passed, **1** OIDF findings rejected by policy,
**2** infrastructure/orchestration/evidence failure. Protocol results remain
preserved even if a later export fails and changes the overall exit to 2.
On timeout/error, cancel only the module created by this runner and retain its
latest persisted state and logs. Do not cancel unrelated tests or rerun a
completed module after losing its response.

## Verification and remaining live work

```powershell
python -m pip install -r requirements-conformance.txt
python -m py_compile scripts/certify_runner.py scripts/run_conformance.py
python -m unittest discover -s tests -v
```

Contract tests exercise the actual pinned `Conformance` helper methods using
`httpx.MockTransport`, including the official export ZIP download/integrity
handling with a fixture archive. The harness retains the official export
unchanged; it does not independently verify its RSA signature. HTTP fixtures
are confined to the test suite; they are not an execution mode or conformance
evidence. Tests cover 0/1/2 semantics, unknown results, timeout/cancellation,
offer and transaction-code handoffs, replay prevention, token separation,
URL validation, missing modules, export failure and readiness gating.

After Docker is installed, run the metadata command first, inspect its actual
`info.json`/`logs.json`, and only then attempt issuance. Resolve infrastructure
problems before interpreting protocol failures. The local contract tests do
not establish source-build success, live API compatibility or conformance.
Both selected plain final-spec plans remain alpha/non-certifiable upstream.
