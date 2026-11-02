"""Transport-level tests of the real official client; fixtures are not live results."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock
import zipfile

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import certify_runner as runner
import prepare
import run_conformance

METADATA = "oid4vci-1_0-issuer-metadata-test"
ISSUANCE = "oid4vci-1_0-issuer-happy-flow"
POLICY = {"max_unexpected_failures": 0, "warning_is_failure": False,
          "review_is_failure": True, "skip_is_failure": True}


def temporary_directory():
    parent = prepare.ROOT / ".runtime/test-phase2"
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=parent)


class SuiteFixture:
    """Minimal API contract fixture, solely for runner tests."""
    def __init__(self, *, result="PASSED", interrupted=False, issuance=False,
                 stall=False, bad_plan=False, export_failure=False, missing_module=False,
                 unsafe_handoff=False, callback_failure=False):
        self.result = result
        self.lifecycle = "INTERRUPTED" if interrupted else "FINISHED"
        self.issuance = issuance
        self.stall = stall
        self.bad_plan = bad_plan
        self.export_failure = export_failure
        self.missing_module = missing_module
        self.unsafe_handoff = unsafe_handoff
        self.callback_failure = callback_failure
        self.stage = "offer" if issuance else "done"
        self.module = ISSUANCE if issuance else METADATA
        self.requests = []
        self.issuer_requests = []
        self.code = None
        self.cancelled = False

    async def suite(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/api/runner/available":
            return httpx.Response(200, json=[{"testName": self.module}])
        if path == "/api/plan":
            if self.bad_plan:
                return httpx.Response(502, json={"error": "fixture unavailable"})
            return httpx.Response(201, json={"id": "p1", "modules": [] if self.missing_module else [
                {"testModule": self.module, "variant": {}}]})
        if path == "/api/runner" and request.method == "POST":
            return httpx.Response(201, json={"id": "t1", "url": runner.OIDF + "/test/t1"})
        if path.endswith("/wait-state"):
            if self.stall:
                await asyncio.sleep(5)
            return httpx.Response(200, json={"state": self.lifecycle if self.stage == "done" else "WAITING"})
        if path == "/api/info/t1":
            return httpx.Response(200, json={"id": "t1", "status": self.lifecycle if self.stage == "done" else "WAITING",
                                             "result": self.result if self.stage == "done" else "UNKNOWN",
                                             "variant": {"grant_management": "disabled"}})
        if path == "/api/runner/t1" and request.method == "DELETE":
            self.cancelled = True
            return httpx.Response(200, json={})
        if path == "/api/runner/t1":
            exposed = {}
            if self.stage == "offer":
                exposed["credential_offer_endpoint"] = ("https://attacker.invalid/test/t1/credential_offer"
                    if self.unsafe_handoff else runner.OIDF + "/test/t1/credential_offer")
            elif self.stage == "tx":
                exposed["tx_code_endpoint"] = runner.OIDF + "/test/t1/tx_code?code=your_tx_code"
            return httpx.Response(200, json={"browser": {}, "exposed": exposed})
        if path == "/test/t1/credential_offer":
            assert request.method == "GET"
            assert request.url.params["credential_offer_uri"] == runner.CERTIFY + "/v1/certify/credential-offer-data/generated"
            self.stage = "done" if self.callback_failure else "tx"
            if self.callback_failure:
                self.result, self.lifecycle = "FAILED", "INTERRUPTED"
            return httpx.Response(500 if self.callback_failure else 200, text="fixture response")
        if path == "/test/t1/tx_code":
            assert request.url.params["code"] == self.code
            self.stage = "done"
            return httpx.Response(200, text="fixture response")
        if path == "/api/log/t1":
            return httpx.Response(200, json=[{"msg": "unit-test fixture log"}])
        if path == "/api/plan/export/p1":
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("fixture.json", '{"unit_test_fixture":true}')
            return httpx.Response(200, content=archive.getvalue(), headers={
                "content-disposition": 'attachment; filename="fixture-export.zip"',
                "content-type": "application/zip"})
        raise AssertionError(f"Unexpected suite request: {request.method} {path}")

    async def issuer(self, request):
        self.issuer_requests.append(request)
        assert "authorization" not in request.headers
        assert request.method == "POST"
        assert request.url.path == "/v1/certify/pre-authorized-data"
        body = json.loads(request.content)
        self.code = body["tx_code"]
        assert len(self.code) == 8
        assert body["credential_configuration_id"] == "ConformanceSDJWT"
        return httpx.Response(200, json={"credentialOfferUri": "openid-credential-offer://?credential_offer_uri="
            + runner.urlencode({"uri": runner.CERTIFY + "/v1/certify/credential-offer-data/generated"})[4:]})


class RunnerTransportTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = temporary_directory()
        cls.directory = Path(cls.temp.name)
        prepare.prepare_tls(cls.directory / "tls")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def exercise(self, fixture, *, timeout=1):
        with temporary_directory() as temp:
            output = Path(temp) / "execution"
            with patch.dict("os.environ", {"OIDF_API_TOKEN": "fixture-token"}):
                api = await runner.create_api(self.directory / "tls/ca.crt", httpx.MockTransport(fixture.suite))
            async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.issuer)) as issuer:
                if fixture.export_failure:
                    async def fail_export(*args):
                        raise RuntimeError("fixture export failed")
                    api.exportjson = fail_export
                with contextlib.redirect_stdout(io.StringIO()):
                    code = await runner.run(api, issuer, "preauthorized" if fixture.issuance else "metadata",
                                            output, timeout=timeout, poll_interval=0)
            await api.httpclient.aclose()
            summary = json.loads((output / "summary.json").read_text())
            rows = json.loads((output / "results.json").read_text())
            return code, summary, rows, {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}

    async def test_real_official_helpers_use_verified_endpoints_and_preserve_each_result(self):
        fixture = SuiteFixture()
        code, summary, rows, files = await self.exercise(fixture)
        self.assertEqual(0, code)
        self.assertTrue(summary["conformance_executed"])
        self.assertEqual("PASS", rows[0]["normalized"])
        self.assertEqual("PASSED", rows[0]["oidf_result"])
        self.assertEqual("disabled", rows[0]["variants"]["grant_management"])
        self.assertIn("modules/000-" + METADATA + "/logs.json", files)
        self.assertIn("fixture-export.zip", files)
        plan = next(req for req in fixture.requests if req.method == "POST" and req.url.path == "/api/plan")
        self.assertEqual("oid4vci-1_0-issuer-test-plan", plan.url.params["planName"])
        self.assertEqual("vci", json.loads(plan.url.params["variant"])["fapi_profile"])
        self.assertEqual(runner.CERTIFY, json.loads(plan.content)["vci"]["credential_issuer_url"])

    async def test_interrupted_authoritative_failure_exits_one(self):
        code, summary, rows, _ = await self.exercise(SuiteFixture(result="FAILED", interrupted=True))
        self.assertEqual(1, code)
        self.assertEqual("FAIL", rows[0]["normalized"])
        self.assertEqual("INTERRUPTED", rows[0]["lifecycle"])
        self.assertEqual("FAIL", summary["status"])

    async def test_unknown_result_is_infrastructure_not_pass(self):
        code, _, rows, _ = await self.exercise(SuiteFixture(result="UNKNOWN"))
        self.assertEqual(2, code)
        self.assertEqual("UNKNOWN", rows[0]["oidf_result"])
        self.assertIn("infrastructure_error", rows[0])

    async def test_no_replay_of_failed_plan_creation(self):
        fixture = SuiteFixture(bad_plan=True)
        code, summary, rows, _ = await self.exercise(fixture)
        self.assertEqual(2, code)
        self.assertFalse(summary["conformance_executed"])
        self.assertEqual([], rows)
        self.assertEqual(1, sum(req.url.path == "/api/plan" for req in fixture.requests))

    async def test_missing_selected_module_fails_infrastructure(self):
        code, _, rows, _ = await self.exercise(SuiteFixture(missing_module=True))
        self.assertEqual(2, code)
        self.assertEqual([], rows)

    async def test_timeout_retains_snapshot_and_cancels_only_created_module(self):
        fixture = SuiteFixture(issuance=True, stall=True)
        code, _, rows, files = await self.exercise(fixture, timeout=0.02)
        self.assertEqual(2, code)
        self.assertTrue(fixture.cancelled)
        self.assertEqual("WAITING", rows[0]["lifecycle"])
        self.assertTrue(any(path.endswith("info.json") for path in files))

    async def test_offer_and_transaction_code_handoff_without_token_leak(self):
        fixture = SuiteFixture(issuance=True)
        code, _, rows, _ = await self.exercise(fixture)
        self.assertEqual(0, code)
        self.assertEqual(1, len(fixture.issuer_requests))
        self.assertEqual(1, sum(req.url.path.endswith("/credential_offer") for req in fixture.requests))
        self.assertEqual(1, sum(req.url.path.endswith("/tx_code") for req in fixture.requests))
        self.assertEqual(ISSUANCE, rows[0]["test_name"])

    async def test_suite_callback_http_error_preserves_authoritative_protocol_failure(self):
        code, _, rows, _ = await self.exercise(SuiteFixture(issuance=True, callback_failure=True))
        self.assertEqual(1, code)
        self.assertEqual("FAILED", rows[0]["oidf_result"])
        self.assertNotIn("infrastructure_error", rows[0])

    async def test_untrusted_exposed_url_is_not_contacted(self):
        fixture = SuiteFixture(issuance=True, unsafe_handoff=True)
        code, _, rows, _ = await self.exercise(fixture)
        self.assertEqual(2, code)
        self.assertEqual([], fixture.issuer_requests)
        self.assertIn("outside", rows[0]["infrastructure_error"])

    async def test_export_failure_is_infrastructure_even_after_pass(self):
        code, summary, rows, _ = await self.exercise(SuiteFixture(export_failure=True))
        self.assertEqual(2, code)
        self.assertEqual("PASSED", rows[0]["oidf_result"])
        self.assertIn("export_error", summary)

    async def test_direct_runner_readiness_failure_cannot_create_plan(self):
        import argparse
        with temporary_directory() as temp:
            args = argparse.Namespace(output=Path(temp), ca=self.directory / "tls/ca.crt",
                                      scenario="metadata", module_timeout=1)
            with patch.object(runner, "readiness", return_value={"status": "ERROR", "checks": []}), \
                 patch.object(runner, "create_api", new_callable=AsyncMock) as create_api:
                with self.assertRaisesRegex(runner.InfrastructureError, "readiness failed"):
                    await runner.async_main(args)
                create_api.assert_not_called()

    async def test_repeated_waiting_does_not_replay_a_credential_offer(self):
        fixture = SuiteFixture(issuance=True)
        with temporary_directory() as temp:
            api = await runner.create_api(self.directory / "tls/ca.crt", httpx.MockTransport(fixture.suite))
            try:
                async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.issuer)) as issuer:
                    live = {"exposed": {"credential_offer_endpoint": runner.OIDF + "/test/t1/credential_offer"}}
                    sent = {}
                    _, _, preauth, _ = runner.load_configuration("preauthorized")
                    await runner.handoff(api, issuer, preauth, live, runner.OIDF + "/test/t1", Path(temp), sent)
                    self.assertIs(False, await runner.handoff(api, issuer, preauth, live,
                                  runner.OIDF + "/test/t1", Path(temp), sent))
                    self.assertEqual(1, len(fixture.issuer_requests))
            finally:
                await api.httpclient.aclose()


class PolicyAndEntrypointTest(unittest.TestCase):
    def test_warning_review_and_skip_policy_retains_distinct_semantics(self):
        for result, expected in (("PASSED", 0), ("FAILED", 1), ("WARNING", 0), ("REVIEW", 1), ("SKIPPED", 1)):
            with self.subTest(result=result):
                self.assertEqual(expected, runner.benchmark([{"oidf_result": result}], POLICY)["exit_code"])
        self.assertEqual(2, runner.benchmark([], POLICY)["exit_code"])
        tolerant = {**POLICY, "skip_is_failure": False}
        self.assertEqual(1, runner.benchmark([{"oidf_result": "SKIPPED"}], tolerant)["exit_code"])

    def test_failed_readiness_prevents_runner_container_launch(self):
        with temporary_directory() as temp, patch.object(run_conformance, "ROOT", Path(temp)), \
             patch.object(sys, "argv", ["run_conformance.py"]), \
             patch.object(run_conformance, "execute", side_effect=RuntimeError("Phase 1 failed")) as execute, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, run_conformance.main())
            self.assertEqual(1, execute.call_count)
            self.assertIn("phase1.py", " ".join(execute.call_args.args[0]))

    def test_callback_cannot_escape_active_module(self):
        with self.assertRaises(runner.InfrastructureError):
            runner.interaction_url(runner.OIDF + "/test/other/credential_offer",
                                   runner.OIDF + "/test/t1", "credential_offer")

    def test_reusing_output_directory_preserves_existing_evidence(self):
        with temporary_directory() as temp:
            path = Path(temp) / "error.log"
            path.write_text("existing evidence")
            with patch.object(sys, "argv", ["certify_runner.py", "--output", temp]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, runner.main())
            self.assertEqual("existing evidence", path.read_text())
            self.assertFalse((Path(temp) / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
