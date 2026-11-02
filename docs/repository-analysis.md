# Repository and integration analysis

Inspected 2026-10-30. This is the Phase-1 design, written before implementation.
No conformance module or container has run on this host: Docker is absent. The
user selected preparation here and live verification after Docker installation.

## A. Repository map and exact source versions

| Checkout under `upstream/` | Branch | Inspected commit |
| --- | --- | --- |
| `inji-certify` | `release-1.0.x` | `95fcf236917d05b0a9f246f3332d150618c72864` |
| `inji-verify` | `release-1.0.x` | `5b7bead2ebf4dc72ac3cb93a1ab98e2e620b011f` |
| `mosip-functional-tests` | default `master` | `085cfa94301738d901c5b70547dbf005cb762c2b` |
| `conformance-suite` | public GitHub mirror `master` | `cab8f98ace4a0daced29a8203d61938cfb754d99` |

Relevant source paths:

* Certify: `certify-service/src/main/java/io/mosip/certify/{controller,services,credential,validators,vcformatters}`;
  `certify-core/src/main/java/io/mosip/certify/core/dto`; `certify-integration-api`;
  `docker-compose/docker-compose-injistack/{docker-compose.yaml,certify_init.sql,certify-nginx.conf,config}`;
  `docs/technical_docs/SD_JWT_Support.md`; `api-test/{pom.xml,entrypoint.sh,testNgXmlFiles,src/main/java}`.
* Verify: `verify-service/src/main/java/io/inji/verify/controller`;
  `verify-core/src/main/java/io/inji/verify/{dto,services/impl,shared}`;
  `verify-service/src/main/resources/application.properties`;
  `docker-compose/{docker-compose-ci.yaml,docker-compose.yml,db-init/init.sql}`;
  `api-test/{pom.xml,entrypoint.sh,testNgXmlFiles,src/main/java}`.
* MOSIP: `apitest-commons/src/main/java/io/mosip/testrig/apirig/testrunner/BaseTestCase.java`;
  `report/EmailableReport.java`; `utils/{S3Adapter,ConfigManager}.java`;
  `src/main/resources/config/Kernel.properties`.
* OIDF: `scripts/{run-test-plan.py,conformance.py,test_plan_parser.py,requirements.txt}`;
  `src/main/java/net/openid/conformance/{vci10issuer,vp1finalverifier,variant,runner,info,frontchannel}`;
  `src/main/resources/static/js/log-detail.js`; `docker-compose.yml`, `nginx/{Dockerfile,nginx.conf}`.

All findings below refer to these commits, not to an assumed fixed meaning of
"1.0". Both Inji POM versions currently identify `1.0.0-rc.1-SNAPSHOT`.

Primary source references:
[Certify controllers](https://github.com/inji/inji-certify/tree/95fcf236917d05b0a9f246f3332d150618c72864/certify-service/src/main/java/io/mosip/certify/controller),
[Certify built-in preauth provider](https://github.com/inji/inji-certify/blob/95fcf236917d05b0a9f246f3332d150618c72864/certify-service/src/main/java/io/mosip/certify/services/PreAuthIssuanceServiceImpl.java),
[Verify request implementation](https://github.com/inji/inji-verify/blob/5b7bead2ebf4dc72ac3cb93a1ab98e2e620b011f/verify-core/src/main/java/io/inji/verify/services/impl/VerifiablePresentationRequestServiceImpl.java),
[Verify constants](https://github.com/inji/inji-verify/blob/5b7bead2ebf4dc72ac3cb93a1ab98e2e620b011f/verify-core/src/main/java/io/inji/verify/shared/Constants.java),
[MOSIP reporter](https://github.com/mosip/mosip-functional-tests/blob/085cfa94301738d901c5b70547dbf005cb762c2b/apitest-commons/src/main/java/io/mosip/testrig/apirig/report/EmailableReport.java),
[official OIDF API client](https://github.com/openid-certification/conformance-suite/blob/cab8f98ace4a0daced29a8203d61938cfb754d99/scripts/conformance.py),
[OIDF URI handoff UI](https://github.com/openid-certification/conformance-suite/blob/cab8f98ace4a0daced29a8203d61938cfb754d99/src/main/resources/static/js/log-detail.js).

## B. Certify integration points

| Item | Verified source behavior |
| --- | --- |
| Internal address | Port 8090, Spring MVC servlet path `/v1/certify` |
| Health | `/v1/certify/actuator/health`, also the Helm readiness/liveness path |
| Issuer metadata | Controller: `/v1/certify/.well-known/openid-credential-issuer`; stock nginx exposes `/.well-known/openid-credential-issuer` |
| OAuth metadata | Controller: `/v1/certify/.well-known/oauth-authorization-server`; stock nginx exposes `/.well-known/oauth-authorization-server` |
| JWKS | `/v1/certify/.well-known/jwks.json`, root alias in stock nginx |
| Credential | POST `/v1/certify/issuance/credential` |
| Nonce | POST `/v1/certify/nonce`; separate from token response |
| Token | POST `/v1/certify/oauth/token`, form encoded |
| Interactive auth | POST `/v1/certify/oauth/iae`, form encoded; presentation during issuance, not a generic browser login endpoint |
| Preauthorization | POST `/v1/certify/pre-authorized-data`; GET `/v1/certify/credential-offer-data/{offer_id}` |
| Config API | POST `/v1/certify/credential-configurations` with a bare `CredentialConfigurationDTO` |

`CredentialConfigurationServiceImpl` uses `mosip.certify.domain.url` **as the
credential issuer**, then appends the servlet path for issuance/nonce. Keep
the domain URL at the HTTPS origin; adding `/v1/certify` duplicates the path.
OIDF constructs discovery by inserting `/.well-known/openid-credential-issuer`
before any issuer path. Using an origin issuer avoids a path ambiguity.

The default Compose configuration points at remote eSignet. The same properties
explicitly document using Certify's own issuer/JWKS/token endpoints instead.
There is a better isolated path than loading an external mock plugin:
`services/PreAuthIssuanceServiceImpl` is a built-in `DataProviderPlugin`, enabled
by `mosip.certify.integration.data-provider-plugin=PreAuthDataProviderPlugin`.
It reads claims cached by the preauthorized flow. Built-in `LoggerAuditService`
supplies auditing. These support a local preauthorized issuance experiment
without eSignet, Mimoto, Inji Web, or a separate mock identity service.

`PreAuthorizedRequest` contains `credential_configuration_id`, `claims`, optional
`expires_in` and `tx_code` (4–8 alphanumeric characters). The response is a
`credentialOfferUri` containing an `openid-credential-offer://` URI. Each offer
is generated dynamically; do not reuse consumed codes.

The stock DB seeds `FarmerCredential` as `ldp_vc` and includes a temporary ngrok
DID. Native `credential/SDJWT.java` handles `dc+sd-jwt`. The safe change is a
conformance-only DB seed, retaining the upstream schema/key policies, with an
SD-JWT VCT, native signing alias, metadata, and template. `mso_mdoc` support and
the `mock-mdl` profile exist, but the default choice should be native SD-JWT.
Metadata on the current branch requires explicit binding/proof/signing fields;
`signatureCryptoSuite` must be absent for SD-JWT (see the current SD-JWT guide).

Minimal runtime dependencies: PostgreSQL, writable PKCS12 storage, and HTTPS
ingress. In-process Verify core is a Maven dependency, not an extra remote
authorization server. Certify uses Java 21 / Spring Boot 3.2.3.

The API rig uses package `io.inji.testrig.apirig.injicertify`, the existing
`testrunner.InjiTestRunner`, `injicertifyMasterTestSuite.xml`, prerequisite and
main child suites, and `apitest-commons:1.6.0`.

## C. Verify integration points

| Item | Verified source behavior |
| --- | --- |
| Internal address | Port 8080, servlet context `/v1/verify` |
| Health | GET `/v1/verify/actuator/health` (existing CI Compose check) |
| VP creation | POST `/v1/verify/v2/vp-request` |
| Session creation | POST `/v1/verify/v2/vp-session-request` |
| Signed request URI | GET `/v1/verify/v2/vp-request/{requestId}`, `application/oauth-authz-req+jwt` |
| HTTP wallet response | POST `/v1/verify/v2/vp-submission/direct-post`, form encoded |
| DC API response | POST `/v1/verify/vp-submission/dc-api`, JSON |
| Request status | GET `/v1/verify/vp-request/{requestId}/status` |

**The current direct-post endpoint includes `/v2`.** The unversioned path in
the initial problem description must not be copied into the harness.

`VPRequestCreateDto` accepts `clientId`, optional `transactionId` and `nonce`,
`dcqlQuery`, `responseCodeValidationRequired`, and `responseMode`. When omitted,
the service generates a nonce. A supplied nonce must be URL safe and at least
16 characters. Example structure derived from the DTOs:

```json
{
  "clientId": "redirect_uri:https://verify.conformance.test:8443/v1/verify/v2/vp-submission/direct-post",
  "dcqlQuery": {
    "credentials": [{
      "id": "credential",
      "format": "dc+sd-jwt",
      "meta": {"vct_values": ["<VCT issued by the OIDF mock wallet>"]}
    }]
  },
  "responseMode": "direct_post",
  "responseCodeValidationRequired": false
}
```

The VCT is intentionally unresolved here: derive it from the selected OIDF
wallet credential, not from the unrelated Certify credential configuration.

Service request modes are `direct_post` and `dc_api`; it rejects
`direct_post.jwt`. Schemes `decentralized_identifier:` and `x509_san_dns:` trigger
a signed request URI; `redirect_uri:` returns by-value `authorizationDetails`.
`redirect_uri:` requires an absolute HTTPS URI exactly equal to the deployment's
submission URL. `x509_san_dns:` has DNS/HTTPS validation; the bundled signing
keystore identifies `test.example.com`. Transport TLS and request-object signing
trust are separate concerns. Do not pretend a TLS certificate fixes signing.

Start with `redirect_uri` + `url_query` + `direct_post`, `vp_profile=plain_vp`,
`credential_format=sd_jwt_vc`. Translate response DTO camelCase fields into
OpenID snake_case query parameters and JSON encode `dcql_query` and
`client_metadata` as appropriate. A later signed request variant requires proper
signing identity/trust setup. The suite's final verifier plan does not offer a
`decentralized_identifier` variant at this commit.

Minimal dependencies: PostgreSQL (`inji_verify`, schema `verify`), HTTPS ingress.
Reuse `docker-compose-ci.yaml`'s healthy Postgres dependency. Source targets
Java 21 / Spring Boot 3.4.10 even though the upstream service Dockerfile uses a
Java 25 JRE. Source builds can consistently use Java 21.

The API rig uses `io.inji.testrig.apirig.injiverify`, existing `InjiTestRunner`,
`injiverifyMasterTestSuite.xml` → `injiverifySuite.xml`, and
`apitest-commons:1.5.0`. Preserve that dependency version.

## D. MOSIP test framework and safe extension

`BaseTestCase.initialize()` reads `env.endpoint`, `env.user`, and `env.testLevel`.
Existing shell entrypoints translate `ENV_ENDPOINT` into `-Denv.endpoint`.
`BaseTestCase` supplies Extent fields, report names, teardown/copy behavior, and
module context. The master suites register
`io.mosip.testrig.apirig.report.EmailableReport` (`IReporter`).

`EmailableReport` walks TestNG suites/results, generates full/error HTML reports,
and either copies them to the configured report mount or uses `S3Adapter` when
`push-reports-to-s3=yes`. `S3Adapter` uses a configurable endpoint and path style
AWS S3 client suitable for MinIO. **Do not assume `automationtests` is a literal
bucket name**: current shared defaults have `s3-account=automation`, uploads
use the configured account and `modules`, while `automationtests` also appears
in Maven metadata. Deployment configuration determines the actual bucket/path.

Add `OpenIDConformanceTest.java` within each rig's existing `testscripts`
package, plus an opt-in `openidConformanceSuite.xml` included from its existing
master suite. Use one named invocation per module/variant (DataProvider plus
`ITest` names, or XML test per module). Preserve authoritative result JSON;
PASS maps to assertion success, FAIL to assertion failure, SKIP/XFAIL to
`SkipException`. WARNING/REVIEW mapping must be explicit and retain raw data.
Missing or empty results and uncompleted execution are infrastructure errors.
Use existing report lifecycle/Extent logging, not merely an `extends` declaration.

Inspect both dependency versions' report assumptions before choosing parameter
types: report code was built around existing data-driven API tests. A new test
must be verified in generated HTML/XML and Extent, including failed/skipped
rows, before integration is called complete.

Both module runners end in `System.exit(0)` even after test execution; the
harness must enforce its own 0/1/2 gate instead of trusting the rig JVM exit code.
Keep `InjiTestRunner`; add the small bridge after live modules are proven.

## E. OpenID Foundation suite

Exact plans: `oid4vci-1_0-issuer-test-plan` and
`oid4vp-1final-verifier-test-plan`. Both are marked `alpha=true`,
`certifiable=false`: useful test coverage, not a certification claim. HAIP plans
are separate and require capabilities beyond the initial isolated setup.

Issuer module `oid4vci-1_0-issuer-metadata-test` is the first target. It needs
`vci.credential_issuer_url` plus applicable variants `fapi_profile=vci` and
`client_auth_type=private_key_jwt` (the metadata module excludes `none` and
client-secret variants). This variant does not establish that Certify supports
private-key client authentication. Happy-flow selection additionally involves
`vci_grant_type=pre_authorization_code`,
`vci_authorization_code_flow_variant=issuer_initiated`,
`credential_format=sd_jwt_vc` (wire format `dc+sd-jwt`) or `mdoc`,
`vci_credential_encryption=plain`, and inherited FAPI parameters.
Configuration includes `vci.credential_configuration_id`, optional
`vci.authorization_server`, proof hints, client configuration and optional
`vci.static_tx_code`. Full issuance variant compatibility remains a Phase-2
experiment: Certify's built-in token service returns Bearer tokens and does
not issue DPoP-bound tokens. Do not select DPoP and declare that gap solved.

Verifier variants: `vp_profile=plain_vp` (default HAIP would be wrong),
`credential_format=sd_jwt_vc` or `iso_mdl`,
`client_id_prefix=redirect_uri` / `x509_san_dns` / `x509_hash`,
`response_mode=direct_post` / `direct_post.jwt`,
`request_method=url_query` / `request_uri_signed`. Signed requests are excluded
for `redirect_uri`; query requests are excluded for the X.509 schemes.
For X.509 use `client.client_id` and the relevant optional RICAL/trust-anchor
configuration. Plain redirect mode resolves identity dynamically. Include a
unique `alias`, description, and bounded `waitTimeoutSeconds`.

Verified REST calls, taken directly from `scripts/conformance.py` and Java:

| Operation | Request |
| --- | --- |
| Available modules | GET `/api/runner/available` |
| Create plan | POST `/api/plan?planName=...&variant=<JSON>`, configuration JSON body; HTTP 201 |
| Create module from plan | POST `/api/runner?test=...&plan=...&variant=<JSON>`; HTTP 201 |
| Explicit start when required | POST `/api/runner/{id}` |
| Persisted state and result | GET `/api/info/{id}` |
| Live interactions/exposed values | GET `/api/runner/{id}` |
| Wait for lifecycle state | GET `/api/runner/{id}/wait-state` (official client implements parameters/timeouts) |
| Logs | GET `/api/log/{id}` |
| Export | GET `/api/plan/export/{planId}` and `/api/plan/exporthtml/{planId}` via official helper (`exportjson()` calls `export`) |

`/api/info/{id}` is persisted state. **Read live `browser.uriInputRequests` from
`/api/runner/{id}`**; it is not supplied by the persisted info endpoint at this
commit. `TestRunner.createTestStatusMap()` confirms this distinction. Module
configuration/start happens asynchronously, so a successful create call is
insufficient. Follow official auto-start handling and start only when needed.

`AbstractVP1FinalVerifierTest.start()` adds a URI input request with its mock
authorization endpoint and enters WAITING. Each request contains `submitUrl`
and `description`. `log-detail.js:handleSubmitUri()` takes the substring starting
at the first `?` and performs GET `submitUrl + query`. The runner should perform
that same HTTP operation, allowlist the suite origin, and deduplicate by
module/input endpoint. **Do not POST an invented JSON `uri` body.** The mock
wallet then sends its response to Verify's HTTPS submission URI.

Issuer initiated preauthorization exposes `credential_offer_endpoint` and can
wait separately for `tx_code_endpoint`; obtain fresh offers/codes for each
interaction. This needs a small custom interaction loop around official
`Conformance`, since `run-test-plan.py` does not implement the Inji handoffs.
Reuse official create/wait/log/export helpers and `test_plan_parser` selector
syntax (`plan[variant=value]:module1,module2`). Dependencies are `httpx` and
`pyparsing`. Do not fork protocol condition classes.

Read final `status` and `result` from `/api/info/{id}` independently. FINISHED
is not PASSED; INTERRUPTED can accompany a protocol failure. Preserve both,
the API's error, logs, configuration, module ID, variants, and details URL.
Classify transport, startup, timeout, unknown result and malformed config
separately from actual OIDF findings. Never infer PASS from missing FAIL logs.

Upstream local Compose uses MongoDB 6.0.13, Java server and nginx TLS. Current
server POM is Spring Boot 4.0.9 / Java 21. Local `fintechlabs.devmode=true`
injects a dummy admin; restrict all published ports to loopback. Do not enable
the Spring `dev` profile merely to obtain API access. No Selenium is needed
for the first metadata and direct-post handoffs.

## F. Risks and remaining experiments

1. Stock LDP seed is invalid for final-spec issuer variants. Replace only the
   conformance DB seed with native SD-JWT; inspect resulting metadata before runs.
2. Isolated preauthorization avoids remote eSignet, but does not prove the full
   issuer plan's client-authentication/sender-constraint requirements. Record a
   real implementation gap if one remains; never xfail environment mistakes.
3. Verify uses HTTPS even for redirect_uri. Trust a private local CA explicitly;
   never disable validation. Signed request JWT trust is a separate later step.
4. URI submission uses live runner state and GET query handoff. Using the info
   endpoint alone would wait forever. Some negative tests may require additional
   interactions or time to observe rejection; handle each boundedly.
5. Canonical HTTPS names must resolve inside Docker. `localhost` in the suite
   JVM points to itself; expose origins on Docker network aliases instead.
6. Branch/tag and Maven SNAPSHOT drift are real. Lock Git commits; build sources
   rather than relying on moving QA `1.0.x` images. Certify embeds Verify core;
   build that dependency from the pinned Verify checkout. Record resolved Maven
   artifacts. Container base-image digests and remaining external SNAPSHOT
   artifacts still need locking after the first successful dependency build.
7. BaseTestCase/report parameter assumptions and both runners' forced exit zero
   must be checked. Master suites also execute unrelated prerequisite/API tests;
   conformance selection must remain opt-in and independent.
8. MongoDB 6 is the upstream local reference, not a production deployment
   recommendation. This harness is isolated and binds no databases to the host.
9. Certify config has all-actuator exposure and temporary remote URLs. Narrow
   management exposure and override remote AS/DID/config addresses locally.
10. This Windows host has no Docker executable/Desktop at standard paths. No
    live health, image build, Java build, or conformance result is verified yet.

## G. Recommended Phase-1 architecture

```text
                    local TLS nginx (:8443)
              one private CA; three DNS aliases
                   /          |          \
            Certify        Verify       OIDF server
             :8090          :8080          :8080
               |              |              |
          PostgreSQL     PostgreSQL       MongoDB
           certify        verify          test_suite

OIDF server -> TLS nginx -> Certify and Verify
Verify -> TLS nginx -> OIDF issuer/JWKS/status callbacks
probe container -> each HTTPS origin (CA and hostname verified)
```

One TLS ingress serves `certify.conformance.test`, `verify.conformance.test`,
and `oidf.conformance.test`, all at port 8443. This replaces two separate app
proxies while retaining the OIDF forwarding headers. Only host port 8443 is
published, bound to 127.0.0.1. Docker DNS aliases resolve the same origins for
all containers. Optional host mappings are needed only for viewing the UI.

Each database has a readiness check. Java images explicitly install curl for
HTTP health checks. nginx starts after backend health, and a probe validates
HTTPS, UP bodies, metadata URLs, the SD-JWT configuration, OAuth/JWKS, OIDF API
access and cross-container reachability. No fixed startup sleeps.

## H. Exact first implementation steps and verification

These are harness-owned additions; upstream application code remains unchanged.

| File | Purpose/content | Verification |
| --- | --- | --- |
| `sources.lock.json` | Repository URLs, branch provenance and exact commits | Git HEAD/clean-tree check before generation/build |
| `scripts/prepare.py` | Validate sources; derive local config/schema; create private CA and SAN certificates; generate readiness manifest | Python compilation and focused preparation/TLS tests |
| `config/certify.properties` | Small override over the pinned upstream default; local AS, built-in preauth provider, local keys and URLs | Assert generated effective URLs/properties; later real metadata probes |
| `config/certify-conformance.sql` | Conformance-only SD-JWT seed applied after schema, replacing LDP row | Static checks; later PostgreSQL initialization and issuer metadata |
| `compose.yaml` | Seven long-running services: two databases, two apps, Mongo, OIDF, TLS ingress | `docker compose config --quiet`; `up --build --wait`; `ps` |
| `docker/{certify,verify,oidf}.Dockerfile` | Build pinned sources with Maven cache; add health tooling and explicit local CA trust | Actual builds after Docker is installed; retain build logs |
| `docker/proxy/{Dockerfile,nginx.conf}` | SAN-correct TLS routing and OIDF forwarding headers | nginx config check and verified HTTPS probes |
| `scripts/{phase1.py,probe.py}` | Preflight; bounded Compose readiness; source/container network checks; JSON evidence and diagnostics; infrastructure exit 2 | Focused failure/readiness tests, then a real Phase-1 run |
| `run-phase1.sh`, `README.md`, `docs/phase1.md` | Reproducible preparation/start/check commands, limitations and troubleshooting | Shell syntax when Bash is available; document actual command results |

Stop at this environment boundary until Certify UP, Verify UP, OIDF UP and the
cross-container HTTPS checks succeed. Phase 2 then adds a minimal issuer
metadata run using the official client, followed by real issuance. TestNG,
combined protocol runs, release gates, Actions, expected failures, diffs and
parallel execution remain later phases; none is claimed complete by Phase 1.
