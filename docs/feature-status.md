# Requirement status for the submission snapshot

Snapshot: 2026-11-02. “Implemented” describes code presence; the verification
column states what was actually tested. There are no genuine OIDF results yet.

| Requirement | Implementation | Verification / limitation |
| --- | --- | --- |
| Branch-specific repository analysis | Complete | Four exact Git commits inspected and locked |
| Minimal combined Compose | Implemented | Docker Compose model validation passed |
| Certify and Verify PostgreSQL | Implemented | Both initialization scripts ran successfully in isolated containers |
| Local CA and TLS ingress | Implemented | CA/SAN tests and real nginx config validation passed; full-stack HTTPS pending |
| Verify service | Source-built | Isolated real runtime returned UP |
| OIDF server/Mongo/proxy | Prepared; server source-built | OIDF runtime health pending |
| Certify service | Prepared; API/core compiled | Service build interrupted by Docker EOF; no complete runtime check |
| Programmatic issuer plan creation | Implemented via official client | HTTP contract tests passed; live module pending |
| Preauthorized offer/code interaction | Implemented for initial issuer happy flow | Contract tested; target capability gaps remain |
| Per-module normalized results/log/export | Implemented for Certify | Contract tested, including export ZIP handling; no real OIDF artifact |
| Benchmark and 0/1/2 exits | Implemented for Certify | Local tests passed; no combined gate yet |
| Certify-only one-command execution | Implemented | Readiness stops unready execution; complete live run pending |
| Verify conformance automation | Not implemented | Exact API/DTO/URI handoff analyzed |
| TestNG bridges in both API rigs | Not implemented | Existing listeners, dependency versions and safe extension points analyzed |
| Combined protocol execution/report | Not implemented | Environment supports both; protocol CLI currently supports Certify only |
| GitHub Actions | Not implemented | Must follow validated local workflow |
| Expected failures | Not implemented | No infrastructure/protocol failures are suppressed |
| Result diff | Not implemented | Follow stable real execution |
| Parallel execution | Not implemented | Deliberately deferred until sequential combined execution is reliable |
| Architecture/API/troubleshooting docs | Included | Source-backed; limitations explicitly recorded |
| Formal OpenID certification | Not claimed | Selected plain plans are alpha/non-certifiable |

This prototype does **not** satisfy every mandatory hackathon requirement yet.
It is suitable for submission only with the above scope and limitations made
visible to reviewers.
