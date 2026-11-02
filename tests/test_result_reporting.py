"""Synthetic fixtures exercise report safety and regression gates, not OpenID."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_results
import report_results
from result_model import EvidenceError, RESULTS, load_run


def temporary_directory():
    directory = Path(__file__).resolve().parents[1] / ".runtime/report-tests"
    directory.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=directory)


def row(result="PASSED", **changes):
    return {"component": "certify", "plan": "fixture-plan", "test_name": "fixture-module",
            "variants": {"credential_format": "sd_jwt_vc"}, "module_id": "fixture-id",
            "oidf_result": result, "normalized": RESULTS[result], "lifecycle": "FINISHED",
            "expected_failure": False, **changes}


def save_run(directory, rows=None, **changes):
    directory.mkdir(parents=True, exist_ok=True)
    summary = {"component": "certify", "scenario": "metadata", "status": "PASS", "exit_code": 0,
               "conformance_executed": True, "policy": {"max_unexpected_failures": 0}, **changes}
    (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (directory / "results.json").write_text(json.dumps([row()] if rows is None else rows), encoding="utf-8")
    return load_run(directory)


class ReportingTest(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_html_escapes_suite_text_and_does_not_link_untrusted_urls(self):
        run = save_run(self.root / "run", [row(test_name='<script>alert("x")</script>',
                       summary='<img src=x onerror="boom">', details_url="javascript:boom")])
        html = report_results.html_report(run)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:boom", html)

    def test_junit_preserves_each_original_outcome_and_policy_rejection(self):
        rows = [row(value, test_name=value) for value in RESULTS]
        run = save_run(self.root / "run", rows, status="FAIL", exit_code=1)
        xml = ET.fromstring(report_results.junit_report(run))
        self.assertEqual("6", xml.get("tests"))
        self.assertEqual("2", xml.get("failures"))
        self.assertEqual("3", xml.get("skipped"))
        self.assertIn('"oidf_result": "WARNING"', xml.find("testcase[@name='WARNING {\"credential_format\":\"sd_jwt_vc\"}']/system-out").text)

    def test_export_failure_adds_junit_error_even_with_passed_module(self):
        run = save_run(self.root / "run", status="ERROR", exit_code=2, export_error="fixture export error")
        xml = ET.fromstring(report_results.junit_report(run))
        self.assertEqual("1", xml.get("errors"))
        self.assertEqual("2", xml.get("tests"))

    def test_preflight_failure_without_results_is_reportable(self):
        run = save_run(self.root / "run", [], status="ERROR", exit_code=2, conformance_executed=False)
        (run.directory / "results.json").unlink()
        xml = ET.fromstring(report_results.junit_report(load_run(run.directory)))
        self.assertEqual("1", xml.get("errors"))

    def test_nonterminal_infrastructure_failure_remains_error(self):
        run = save_run(self.root / "run", [row(lifecycle="WAITING", oidf_result=None, normalized=None,
                       infrastructure_error="timeout")], status="ERROR", exit_code=2)
        self.assertEqual({"ERROR": 1}, run.counts)
        self.assertEqual("2", ET.fromstring(report_results.junit_report(run)).get("errors"))

    def test_invalid_evidence_cannot_generate_a_green_report(self):
        cases = [([], {}), ([row(lifecycle="WAITING")], {}), ([row(oidf_result="UNKNOWN")], {}),
                 ([row(oidf_result=[])], {}), ([row(normalized="FAIL")], {}),
                 ([row(module_id=None)], {}), ([row(expected_failure=True)], {}),
                 ([row(), row(module_id="another")], {}), ([row("SKIPPED")], {}),
                 ([row(infrastructure_error="broken")], {}), ([row()], {"exit_code": 1}),
                 ([row()], {"status": []}), ([row()], {"conformance_executed": False}),
                 ([row()], {"export_error": "failed"})]
        for index, (rows, summary) in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(EvidenceError):
                save_run(self.root / str(index), rows, **summary)

    def test_duplicate_json_keys_and_nonfinite_constants_are_rejected(self):
        run = save_run(self.root / "run")
        for data in ('{"status":"ERROR","status":"PASS"}', '{"value":NaN}'):
            (run.directory / "summary.json").write_text(data)
            with self.assertRaises(EvidenceError):
                load_run(run.directory)

    def test_invalid_xml_characters_are_removed(self):
        run = save_run(self.root / "run", [row(summary="bad\x00text")])
        ET.fromstring(report_results.junit_report(run))

    def test_cli_returns_persisted_exit_and_never_overwrites_output(self):
        run = save_run(self.root / "run", [row("FAILED")], status="FAIL", exit_code=1)
        output = self.root / "report.xml"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, report_results.main([str(run.directory), "--junit", str(output)]))
            original = output.read_bytes()
            self.assertEqual(2, report_results.main([str(run.directory), "--junit", str(output)]))
        self.assertEqual(original, output.read_bytes())

    def test_cli_refuses_colliding_output_paths(self):
        run = save_run(self.root / "run")
        path = str(self.root / "collision")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, report_results.main([str(run.directory), "--html", path, "--junit", path]))
        self.assertFalse(Path(path).exists())


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def compare(self, before, after, **summary):
        baseline = save_run(self.root / "baseline", before, **summary)
        candidate = save_run(self.root / "candidate", after, **summary)
        return compare_results.compare(baseline, candidate)

    def test_generated_ids_and_variant_key_order_do_not_change_identity(self):
        result = self.compare([row(variants={"a": "1", "b": "2"})],
                              [row(module_id="new-id", variants={"b": "2", "a": "1"})])
        self.assertEqual(0, result["exit_code"])
        self.assertEqual([], result["changes"])

    def test_pass_to_failure_is_regression(self):
        result = self.compare([row()], [row("FAILED")], status="FAIL", exit_code=1)
        self.assertEqual(1, result["exit_code"])
        self.assertEqual("regression", result["changes"][0]["kind"])

    def test_unchanged_failure_is_not_a_passing_release_gate(self):
        result = self.compare([row("FAILED")], [row("FAILED")], status="FAIL", exit_code=1)
        self.assertEqual(0, result["exit_code"])
        self.assertEqual(1, result["candidate_gate_exit"])

    def test_removed_or_variant_changed_module_is_incomplete(self):
        result = self.compare([row()], [row(variants={"credential_format": "other"})])
        self.assertEqual(2, result["exit_code"])
        self.assertEqual(1, result["removed_modules"])

    def test_infrastructure_failure_never_becomes_no_regression(self):
        baseline = save_run(self.root / "baseline")
        candidate = save_run(self.root / "candidate", status="ERROR", exit_code=2, export_error="failed")
        self.assertEqual(2, compare_results.compare(baseline, candidate)["exit_code"])

    def test_different_scenarios_and_gate_policies_are_not_comparable(self):
        baseline = save_run(self.root / "baseline")
        for change in ({"scenario": "preauthorized"}, {"policy": {"max_unexpected_failures": 1}}):
            candidate = save_run(self.root / "candidate", **change)
            with self.assertRaises(EvidenceError):
                compare_results.compare(baseline, candidate)

    def test_new_failure_is_counted_as_regression(self):
        result = self.compare([row()], [row(), row("FAILED", test_name="new-module")], status="FAIL", exit_code=1)
        self.assertEqual(1, result["regressions"])

    def test_improvement_and_warning_regression(self):
        improved = self.compare([row("FAILED")], [row()], status="FAIL", exit_code=1)
        self.assertEqual("improvement", improved["changes"][0]["kind"])
        worsened = self.compare([row()], [row("WARNING")])
        self.assertEqual(1, worsened["exit_code"])

    def test_comparison_cli_writes_machine_readable_result(self):
        baseline = save_run(self.root / "baseline")
        candidate = save_run(self.root / "candidate")
        output = self.root / "diff.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, compare_results.main([str(baseline.directory), str(candidate.directory), "--output", str(output)]))
        self.assertEqual("NO_REGRESSION", json.loads(output.read_text())["status"])


if __name__ == "__main__":
    unittest.main()
