#!/usr/bin/env python3
"""Certify Phase-2 automation using the source-locked official OIDF client."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
import traceback
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from probe import CERTIFY, OIDF, run as readiness

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"FINISHED", "INTERRUPTED"}
RESULT_MAP = {"PASSED": "PASS", "FAILED": "FAIL", "SKIPPED": "SKIP",
              "WARNING": "SKIP", "REVIEW": "SKIP"}


class InfrastructureError(RuntimeError):
    pass


def official_module(name):
    path = ROOT / "upstream/conformance-suite/scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"inji_official_{name}", path)
    if spec is None or spec.loader is None:
        raise InfrastructureError(f"Cannot load official client: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value):
    # Replace a complete document so interrupted writes cannot leave partial JSON.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise InfrastructureError("Suite returned an invalid or missing identifier")
    return value


def interaction_url(value: str, module_url: str, endpoint: str) -> str:
    """Only submit to this module's own suite URL; never trust arbitrary exposed URLs."""
    candidate, base = urlsplit(value), urlsplit(module_url)
    if (candidate.scheme, candidate.netloc) != (urlsplit(OIDF).scheme, urlsplit(OIDF).netloc):
        raise InfrastructureError("Interaction URL is outside the configured suite origin")
    if (base.scheme, base.netloc) != (urlsplit(OIDF).scheme, urlsplit(OIDF).netloc) or not base.path.startswith("/test/"):
        raise InfrastructureError("Invalid active module URL")
    if candidate.username or candidate.password or candidate.fragment:
        raise InfrastructureError("Invalid interaction URL")
    if candidate.path != base.path.rstrip("/") + "/" + endpoint:
        raise InfrastructureError("Interaction URL does not belong to the active module")
    return value


def normalize(info, *, name, module_id, plan_id, variants):
    lifecycle, original = info.get("status"), info.get("result")
    if lifecycle not in TERMINAL or original not in RESULT_MAP:
        raise InfrastructureError(f"No authoritative terminal result: lifecycle={lifecycle!r}, result={original!r}")
    if lifecycle == "INTERRUPTED" and original != "FAILED":
        raise InfrastructureError(f"Interrupted module has no authoritative failure: {original!r}")
    persisted_variants = info.get("variant", {})
    if not isinstance(persisted_variants, dict):
        raise InfrastructureError("Suite returned malformed selected variants")
    return {"component": "certify", "plan": "oid4vci-1_0-issuer-test-plan", "plan_id": plan_id,
            "test_name": name, "module_id": module_id, "variants": {**variants, **persisted_variants},
            "lifecycle": lifecycle, "oidf_result": original, "normalized": RESULT_MAP[original],
            "expected_failure": False, "summary": f"OIDF {original} ({lifecycle})",
            "details_url": f"{OIDF}/log-detail.html?log={module_id}"}


def benchmark(rows, policy):
    if not rows or any(row.get("infrastructure_error") for row in rows):
        return {"status": "ERROR", "exit_code": 2, "reason": "Incomplete or infrastructure-failed execution"}
    counts = Counter(row["oidf_result"] for row in rows)
    failures = counts["FAILED"]
    for result, option in (("WARNING", "warning_is_failure"), ("REVIEW", "review_is_failure"),
                           ("SKIPPED", "skip_is_failure")):
        if policy[option]:
            failures += counts[result]
    # Tolerating skipped tests must never turn an entirely unexecuted run green.
    passed = counts["SKIPPED"] != len(rows) and failures <= policy["max_unexpected_failures"]
    return {"status": "PASS" if passed else "FAIL", "exit_code": 0 if passed else 1,
            "counts": dict(counts), "unexpected_failures": failures, "policy": policy}


def load_configuration(scenario):
    template = json.loads((ROOT / f"config/certify-{scenario}.json").read_text(encoding="utf-8"))
    parser = official_module("test_plan_parser")
    # Official grammar, with strict whole-input parsing (parse_test is permissive).
    selection = parser.test_unit.parse_string(template["selector"], parse_all=True)[0]["test"]
    if selection["test_name"] != "oid4vci-1_0-issuer-test-plan" or not selection.get("modules"):
        raise InfrastructureError("An explicit issuer module selection is required")
    config = template["oidf"]
    config["alias"] = "inji-certify-" + secrets.token_hex(8)
    if config["vci"]["credential_issuer_url"] != CERTIFY:
        raise InfrastructureError("Issuer config differs from the checked Phase-1 environment")
    policy = json.loads((ROOT / "config/benchmark.json").read_text(encoding="utf-8"))["certify"]
    if type(policy.get("max_unexpected_failures")) is not int or policy["max_unexpected_failures"] < 0:
        raise InfrastructureError("Invalid benchmark failure threshold")
    for option in ("warning_is_failure", "review_is_failure", "skip_is_failure"):
        if type(policy.get(option)) is not bool:
            raise InfrastructureError(f"Invalid benchmark option {option}")
    return selection, config, template.get("preauthorization"), policy


async def create_api(ca, transport=None):
    official = official_module("conformance")
    context = ssl.create_default_context(cafile=str(ca))
    api = official.Conformance(OIDF, os.environ.get("OIDF_API_TOKEN"), context)
    # The official RetryTransport retries POSTs on failures. Replaying plan/module
    # creation can create duplicate live runs. Keep the official API helpers but
    # use single-attempt HTTP transport and bounded orchestration instead.
    headers = dict(api.httpclient.headers)
    await api.httpclient.aclose()
    api.httpclient = httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(verify=context),
                                     headers=headers, timeout=20, trust_env=False, follow_redirects=False)
    return api


async def handoff(api, issuer, preauth, live, module_url, directory, sent):
    exposed = live.get("exposed", {})
    if not isinstance(exposed, dict):
        raise InfrastructureError("Malformed suite exposed values")
    if exposed.get("tx_code_endpoint"):
        if "offer" not in sent:
            raise InfrastructureError("Suite requested a transaction code before an offer was submitted")
        if "tx" in sent:
            return False
        target = interaction_url(exposed["tx_code_endpoint"], module_url, "tx_code")
        parts = urlsplit(target)
        query = [(key, val) for key, val in parse_qsl(parts.query) if key != "code"]
        query.append(("code", sent["tx_code"]))
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        sent["tx"] = True  # Do not replay a possibly accepted request on transport error.
    elif exposed.get("credential_offer_endpoint"):
        if "offer" in sent:
            return False
        if not preauth:
            raise InfrastructureError("Unexpected credential offer interaction in metadata-only execution")
        target = interaction_url(exposed["credential_offer_endpoint"], module_url, "credential_offer")
        sent["tx_code"] = "".join(secrets.choice("0123456789") for _ in range(8))
        response = await issuer.post(CERTIFY + "/v1/certify/pre-authorized-data",
                                     json={**preauth, "tx_code": sent["tx_code"]})
        (directory / "preauthorization-response.txt").write_text(
            f"HTTP {response.status_code}\n{response.text}", encoding="utf-8")
        response.raise_for_status()
        body = response.json()
        write_json(directory / "credential-offer.json", body)
        offer = urlsplit(body.get("credentialOfferUri", ""))
        params = parse_qsl(offer.query, keep_blank_values=True)
        if offer.scheme != "openid-credential-offer" or len(params) != 1 or params[0][0] != "credential_offer_uri":
            raise InfrastructureError("Certify returned an invalid credential offer URI")
        fetch = urlsplit(params[0][1])
        if (fetch.scheme, fetch.netloc) != (urlsplit(CERTIFY).scheme, urlsplit(CERTIFY).netloc) or not fetch.path.startswith("/v1/certify/credential-offer-data/"):
            raise InfrastructureError("Credential offer points outside the checked Certify environment")
        separator = "&" if urlsplit(target).query else "?"
        target += separator + offer.query  # Preserve the issuer's encoded offer URI exactly.
        sent["offer"] = True
    else:
        return False
    response = await api.httpclient.get(target, timeout=60)
    (directory / ("tx-response.txt" if "tx" in sent else "offer-response.txt")).write_text(
        f"HTTP {response.status_code}\n{response.text}", encoding="utf-8")
    # A condition failure while handling the GET may yield a non-2xx response.
    # Let the caller inspect the persisted final result before classifying it.
    return response


async def run_module(api, issuer, entry, selection, plan_id, preauth, output, timeout, poll_interval):
    name = entry["testModule"]
    directory = output / "modules" / f"{len(list((output / 'modules').iterdir())):03d}-{identifier(name)}"
    directory.mkdir()
    module_id = None
    info = {}
    result = {"component": "certify", "test_name": name, "module_id": None,
              "plan": selection["test_name"], "plan_id": plan_id,
              "variants": {**(entry.get("variant") or {}), **selection.get("variants", {})},
              "oidf_result": None, "lifecycle": None, "normalized": None, "expected_failure": False}
    try:
        async with asyncio.timeout(timeout):
            created = await api.create_test_from_plan_with_variant(plan_id, name, entry.get("variant"))
            write_json(directory / "created.json", created)
            module_id = identifier(created.get("id"))
            result["module_id"] = module_id
            result["details_url"] = f"{OIDF}/log-detail.html?log={module_id}"
            module_url = created.get("url", "")
            sent = {}
            while True:
                # All currently selected issuer modules auto-start, as confirmed
                # by AbstractTestModule.autoStart and TestRunner.configure/start.
                await api.wait_for_state(module_id, ["WAITING", "FINISHED", "INTERRUPTED"], timeout=timeout)
                info = await api.get_module_info(module_id)
                write_json(directory / "info.json", info)
                if info.get("status") in TERMINAL:
                    variants = {**(entry.get("variant") or {}), **selection.get("variants", {})}
                    result = normalize(info, name=name, module_id=module_id, plan_id=plan_id, variants=variants)
                    break
                live_response = await api.httpclient.get(f"{OIDF}/api/runner/{module_id}")
                live_response.raise_for_status()
                live = live_response.json()
                write_json(directory / "live.json", live)
                response = await handoff(api, issuer, preauth, live, module_url, directory, sent)
                if response is not False and not response.is_success:
                    info = await api.get_module_info(module_id)
                    write_json(directory / "info.json", info)
                    if info.get("status") in TERMINAL and info.get("result") == "FAILED":
                        continue
                    response.raise_for_status()
                # WAITING can remain unchanged after submission or until exposed
                # values appear. Bounded polling avoids a busy loop or replay.
                await asyncio.sleep(poll_interval)
    except Exception as exc:
        result.update(lifecycle=info.get("status"), oidf_result=info.get("result"),
                      infrastructure_error=f"{type(exc).__name__}: {exc}")
        (directory / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if module_id:
            if result.get("infrastructure_error"):
                try:
                    async with asyncio.timeout(10):
                        info = await api.get_module_info(module_id)
                        write_json(directory / "info.json", info)
                        result.update(lifecycle=info.get("status"), oidf_result=info.get("result"))
                except Exception as exc:
                    result["snapshot_error"] = f"{type(exc).__name__}: {exc}"
            if info.get("status") not in TERMINAL:
                try:
                    response = await api.httpclient.delete(f"{OIDF}/api/runner/{module_id}", timeout=10)
                    if response.status_code not in (200, 404):
                        response.raise_for_status()
                except Exception as exc:
                    result["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            try:
                async with asyncio.timeout(20):
                    write_json(directory / "logs.json", await api.get_test_log(module_id))
            except Exception as exc:
                result["infrastructure_error"] = result.get("infrastructure_error", "") + f" Log retrieval failed: {exc}"
            if result.get("cleanup_error"):
                result["infrastructure_error"] = result.get("infrastructure_error", "") + " Module cancellation failed"
        write_json(directory / "result.json", result)
    return result


async def run(api, issuer, scenario, output, timeout=240, poll_interval=1):
    selection, config, preauth, policy = load_configuration(scenario)
    summary = {"component": "certify", "scenario": scenario, "status": "ERROR", "exit_code": 2,
               "conformance_executed": False, "plan_id": None}
    rows = []
    output.mkdir(parents=True, exist_ok=True)
    (output / "modules").mkdir(exist_ok=True)
    if (output / "summary.json").exists() or list((output / "modules").iterdir()):
        raise InfrastructureError("Output directory already contains a run; choose a fresh directory")
    write_json(output / "configuration.json", {"selector": selection, "oidf": config})
    write_json(output / "sources.lock.json", json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8")))
    try:
        available = await asyncio.wait_for(api.get_all_test_modules(), 30)
        names = {item["testName"] for item in available}
        if missing := set(selection["modules"]) - names:
            raise InfrastructureError(f"Selected modules unavailable: {sorted(missing)}")
        plan = await asyncio.wait_for(api.create_test_plan(selection["test_name"], json.dumps(config), selection.get("variants")), 30)
        write_json(output / "plan.json", plan)
        plan_id = identifier(plan.get("id"))
        summary["plan_id"] = plan_id
        entries = [entry for entry in plan.get("modules", []) if entry.get("testModule") in selection["modules"]]
        if {entry["testModule"] for entry in entries} != set(selection["modules"]):
            raise InfrastructureError("Created plan omitted selected modules; check variants")
        summary["planned_modules"] = entries
        for entry in entries:
            row = await run_module(api, issuer, entry, selection, plan_id, preauth, output, timeout, poll_interval)
            rows.append(row)
            summary["conformance_executed"] = any(row.get("module_id") for row in rows)
            write_json(output / "results.json", rows)
            print(f"{row.get('oidf_result') or 'ERROR'}  {row['test_name']}", flush=True)
        summary.update(benchmark(rows, policy))
    except Exception as exc:
        summary.update(status="ERROR", exit_code=2, error=f"{type(exc).__name__}: {exc}")
        (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if summary["plan_id"]:
            try:
                async with asyncio.timeout(45):
                    summary["export"] = Path(await api.exportjson(summary["plan_id"], str(output))).name
            except Exception as exc:
                summary.update(status="ERROR", exit_code=2, export_error=f"{type(exc).__name__}: {exc}")
        write_json(output / "results.json", rows)
        write_json(output / "summary.json", summary)
    return summary["exit_code"]


async def async_main(args):
    output = args.output
    # Fresh network/config checks, not a stale Phase-1 marker or a bypass flag.
    report = await asyncio.to_thread(readiness, "certify", args.ca)
    write_json(output / "readiness.json", report)
    if report["status"] != "PASS":
        raise InfrastructureError("Phase-1 readiness failed; see readiness.json; no plan was created")
    api = await create_api(args.ca)
    try:
        # No OIDF Authorization header is ever forwarded to Certify.
        context = ssl.create_default_context(cafile=str(args.ca))
        async with httpx.AsyncClient(verify=context, trust_env=False, timeout=20, follow_redirects=False) as issuer:
            return await run(api, issuer, args.scenario, output, args.module_timeout)
    finally:
        await api.httpclient.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("metadata", "preauthorized"), default="metadata")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ca", type=Path, default=Path("/tls/ca.crt"))
    parser.add_argument("--module-timeout", type=float, default=240)
    args = parser.parse_args()
    if args.module_timeout <= 0:
        parser.error("--module-timeout must be positive")
    owned_output = False
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        owned_output = True
        return asyncio.run(async_main(args))
    except Exception as exc:
        print(f"INFRASTRUCTURE ERROR: {exc}", file=sys.stderr)
        # Never overwrite an earlier completed run on accidental path reuse.
        if owned_output and not (args.output / "summary.json").exists():
            write_json(args.output / "summary.json", {"status": "ERROR", "exit_code": 2,
                "conformance_executed": False, "error": f"{type(exc).__name__}: {exc}"})
            (args.output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
