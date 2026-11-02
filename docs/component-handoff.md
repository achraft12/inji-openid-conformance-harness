# Component handoff

## Certify

Start with `config/certify-metadata.json`, then the optional
`config/certify-preauthorized.json`. The issuer is the HTTPS origin; the service
adds `/v1/certify` to issuance and nonce endpoints. Its interactive endpoint on
the inspected branch is `/oauth/iae`.

The native `PreAuthDataProviderPlugin` consumes cached claims; external eSignet
and CSV/mock plugins are not needed for this initial preauthorization setup.
The conformance-only seed registers `ConformanceSDJWT` as `dc+sd-jwt` with ES256
and JWK binding. VCT type metadata is served by nginx at the seeded HTTPS URL.

Next acceptance check: finish the service source image, verify live metadata,
then obtain an authoritative terminal result from the actual OIDF module.
Investigate the inherited private-key client-auth/DPoP requirements honestly:
the built-in preauthorization token service returns Bearer tokens. Do not add
expected failures for bad networking, TLS, variants or runner bugs.

## Verify

The source image and isolated startup were verified. The protocol driver has
not been implemented. Relevant endpoints on the locked branch:

* POST `/v1/verify/v2/vp-request`.
* GET `/v1/verify/v2/vp-request/{requestId}` for signed request objects.
* POST `/v1/verify/v2/vp-submission/direct-post`.

Initial suite selection should use plain VP, SD-JWT, `redirect_uri`, `url_query`
and `direct_post`, rather than unsupported `direct_post.jwt` or an unrelated
older draft. The redirect client ID must exactly match the HTTPS response URI.
Derive DCQL/VCT from the suite's mock wallet credential, not the Certify seed.

Read live `browser.uriInputRequests` from GET `/api/runner/{id}`. The OIDF UI's
actual handoff takes the generated `openid4vp://` URI query and GETs it to the
input's `submitUrl`; do not invent a JSON POST endpoint. Allowlist the suite
origin/module path and deduplicate unchanged interactions. Read authoritative
final lifecycle/result from `/api/info/{id}` independently.

## MOSIP / TestNG

Preserve both existing `InjiTestRunner` implementations. Certify depends on
`apitest-commons:1.6.0`; Verify uses `1.5.0`. Add module-specific
`OpenIDConformanceTest.java` classes and opt-in suite XML files in their current
API rigs, using `System.getProperty("env.endpoint")` and existing initialization.

Provide one named invocation per OIDF module/variant and preserve raw OIDF data.
Verify actual TestNG, Extent and EmailableReport output for pass/fail/skip cases;
the reporter may assume existing data-provider parameter shapes. Merely
extending `BaseTestCase` does not prove reporting integration works.

The existing runners end with exit 0, so retain the harness's independent gate.
Use the existing configurable S3/MinIO account/path; do not introduce a parallel
per-module reporting framework or assume `automationtests` is a fixed bucket.

## Certification

The selected plain final-spec issuer/verifier plans are marked alpha and
non-certifiable in the locked suite. Local results cannot establish formal
certification. Once implementation capabilities and the appropriate certifiable
profile (for example HAIP where applicable) align, follow the current OIDF
certification program's configuration, evidence/export and submission process.
Do not submit fixture results or relabel this prototype as certified.
