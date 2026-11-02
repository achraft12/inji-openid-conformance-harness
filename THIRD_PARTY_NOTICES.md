# Upstream source and licenses

This archive contains the harness's own source and documentation. Upstream
repositories, installed software, private CA keys, images, Maven caches and
third-party binaries are not bundled. `prepare.py --fetch-sources` retrieves
the exact commits listed in `sources.lock.json`.

* Inji Certify — https://github.com/inji/inji-certify — Apache License 2.0.
* Inji Verify — https://github.com/inji/inji-verify — Apache License 2.0.
* MOSIP functional tests — https://github.com/mosip/mosip-functional-tests —
  Mozilla Public License 2.0.
* OIDF conformance suite — https://github.com/openid-certification/conformance-suite —
  MIT License; refer to `LICENSE.txt` and component notices in the fetched source.

The harness loads the official OIDF Python client/parser from the fetched source
without modifying those files. Docker Desktop is a separately installed
prerequisite governed by its own terms; its installer is not included.
