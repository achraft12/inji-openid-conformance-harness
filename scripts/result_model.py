"""Validate persisted harness results without importing protocol or HTTP clients."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

RESULTS = {"PASSED": "PASS", "FAILED": "FAIL", "WARNING": "SKIP",
           "REVIEW": "SKIP", "SKIPPED": "SKIP"}
EXITS = {"PASS": 0, "FAIL": 1, "ERROR": 2}
MAX_JSON_BYTES = 16 * 1024 * 1024


class EvidenceError(ValueError):
    """Malformed or ambiguous persisted evidence."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise EvidenceError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
    def invalid_constant(value):
        raise EvidenceError(f"Non-finite JSON number: {value}")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                      parse_constant=invalid_constant)


def identity(row):
    """Ignore generated run IDs; retain component, plan, module, and variants."""
    fields = []
    for key in ("component", "plan", "test_name"):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EvidenceError(f"Missing nonempty row field: {key}")
        fields.append(value)
    variants = row.get("variants")
    if not isinstance(variants, dict) or any(not isinstance(v, str) for v in variants.values()):
        raise EvidenceError("Variants must be an object of string values")
    return (*fields, json.dumps(variants, sort_keys=True, separators=(",", ":")))


def outcome(row):
    if row.get("infrastructure_error") or row.get("cleanup_error"):
        return "ERROR"
    return row.get("oidf_result")


@dataclass(frozen=True)
class Run:
    directory: Path
    summary: dict
    rows: tuple

    @property
    def exit_code(self):
        return self.summary["exit_code"]

    @property
    def counts(self):
        return dict(Counter(outcome(row) for row in self.rows))


def load_run(directory):
    directory = Path(directory)
    summary = read_json(directory / "summary.json")
    if not isinstance(summary, dict) or not isinstance(summary.get("status"), str) or summary["status"] not in EXITS:
        raise EvidenceError("Unknown or missing summary status")
    if type(summary.get("exit_code")) is not int or summary["exit_code"] != EXITS[summary["status"]]:
        raise EvidenceError("Summary status and exit code disagree")
    if type(summary.get("conformance_executed")) is not bool:
        raise EvidenceError("Summary must explicitly state conformance_executed")
    for key in ("error", "export_error"):
        if summary.get(key) and summary["status"] != "ERROR":
            raise EvidenceError(f"Summary hides an infrastructure failure: {key}")
    results_path = directory / "results.json"
    rows = read_json(results_path) if results_path.exists() else []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EvidenceError("Results must be an array of objects")
    seen = set()
    for row in rows:
        key = identity(row)
        if key in seen:
            raise EvidenceError(f"Duplicate module/variant identity: {key}")
        seen.add(key)
        if row.get("expected_failure") not in (False, None):
            raise EvidenceError("Expected-failure suppression is not supported")
        if outcome(row) == "ERROR":
            if summary["status"] != "ERROR":
                raise EvidenceError("Summary hides a module infrastructure failure")
            continue
        original = row.get("oidf_result")
        if not isinstance(original, str) or original not in RESULTS or row.get("normalized") != RESULTS[original]:
            raise EvidenceError("Unknown OIDF result or inconsistent normalization")
        lifecycle = row.get("lifecycle")
        if lifecycle != "FINISHED" and not (lifecycle == "INTERRUPTED" and original == "FAILED"):
            raise EvidenceError("Module lacks an authoritative terminal result")
        if not isinstance(row.get("module_id"), str) or not row["module_id"]:
            raise EvidenceError("Terminal module is missing its suite ID")
    if summary["status"] != "ERROR":
        if not rows or summary["conformance_executed"] is not True:
            raise EvidenceError("Non-error summary has no executed modules")
        if all(row.get("oidf_result") == "SKIPPED" for row in rows):
            if summary["status"] == "PASS":
                raise EvidenceError("An entirely skipped run cannot pass")
    return Run(directory, summary, tuple(rows))


def write_new(path, content):
    """Never replace evidence or a report the caller already has."""
    path = Path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
