#!/usr/bin/env python3
"""Render persisted execution evidence as HTML and JUnit; preserve its gate exit."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from result_model import EvidenceError, identity, load_run, outcome, write_new


def xml_text(value):
    return re.sub(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", str(value))


def junit_report(run):
    suite = ET.Element("testsuite", name="Inji persisted conformance evidence")
    ET.SubElement(suite, "properties")
    properties = suite.find("properties")
    for name, value in (("evidence_type", "persisted; not independently verified"),
                        ("harness_status", run.summary["status"]),
                        ("harness_exit_code", run.exit_code)):
        ET.SubElement(properties, "property", name=name, value=str(value))
    for row in run.rows:
        component, plan, name, variants = identity(row)
        case = ET.SubElement(suite, "testcase", classname=xml_text(component + "." + plan),
                             name=xml_text(name + " " + variants))
        status = outcome(row)
        if status == "ERROR":
            ET.SubElement(case, "error", type="InfrastructureError").text = xml_text(
                row.get("infrastructure_error") or row.get("cleanup_error"))
        elif status == "FAILED":
            ET.SubElement(case, "failure", type="OIDFFailure").text = xml_text(row.get("summary", status))
        elif status != "PASSED":
            ET.SubElement(case, "skipped", message=status)
        ET.SubElement(case, "system-out").text = xml_text(json.dumps({
            "oidf_result": row.get("oidf_result"), "lifecycle": row.get("lifecycle"),
            "module_id": row.get("module_id"), "variants": row["variants"]}, sort_keys=True))
    # Preserve export failures, preflight failures, and policy rejection even if
    # the module cases alone look green to a JUnit consumer.
    if run.exit_code:
        case = ET.SubElement(suite, "testcase", classname="harness", name="Persisted release gate")
        tag = "error" if run.exit_code == 2 else "failure"
        ET.SubElement(case, tag, type="HarnessGate").text = xml_text(json.dumps(run.summary, sort_keys=True))
    cases = suite.findall("testcase")
    suite.set("tests", str(len(cases)))
    for tag, attr in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
        suite.set(attr, str(sum(case.find(tag) is not None for case in cases)))
    ET.indent(suite)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"


def html_report(run):
    rows = []
    for row in run.rows:
        cells = (row["component"], row["test_name"], json.dumps(row["variants"], sort_keys=True),
                 row.get("module_id") or "None", outcome(row),
                 row.get("infrastructure_error") or row.get("summary") or "")
        rows.append("<tr>" + "".join("<td>" + escape(str(cell)) + "</td>" for cell in cells) + "</tr>")
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>Inji execution evidence</title>
<style>body{font:16px system-ui;margin:3rem auto;max-width:1100px;padding:0 1rem;color:#182c30}
table{border-collapse:collapse;width:100%}th,td{padding:.7rem;border-bottom:1px solid #ccc;text-align:left;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f4;padding:1rem}.table{overflow-x:auto}</style>
<h1>Inji execution evidence</h1>
<p>Rendered from persisted JSON. This report does not execute tests or independently verify OIDF evidence.
It does not establish OpenID certification. Do not publish raw evidence without reviewing it for secrets.</p>
''' + f'<p><strong>Harness status: {escape(run.summary["status"])} · exit {run.exit_code}</strong></p>' + (
        '<p>Suite execution recorded: ' + str(run.summary["conformance_executed"]) + '</p>'
        '<div class="table"><table><thead><tr><th>Component</th><th>Module</th><th>Variants</th>'
        '<th>Suite ID</th><th>Original outcome</th><th>Detail</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div><h2>Persisted gate summary</h2><pre>'
        + escape(json.dumps(run.summary, indent=2, sort_keys=True)) + '</pre></html>\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args(argv)
    if not args.html and not args.junit:
        parser.error("Specify --html and/or --junit output paths")
    try:
        run = load_run(args.execution)
        outputs = [(path, renderer(run)) for path, renderer in
                   ((args.html, html_report), (args.junit, junit_report)) if path]
        if len({path.resolve() for path, _ in outputs}) != len(outputs):
            raise EvidenceError("HTML and JUnit output paths must differ")
        if any(path.exists() for path, _ in outputs):
            raise EvidenceError("Output already exists; choose fresh report paths")
        for path, content in outputs:
            write_new(path, content)
            print(f"Created {path}")
        return run.exit_code
    except (OSError, ValueError) as exc:
        print(f"REPORT ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
