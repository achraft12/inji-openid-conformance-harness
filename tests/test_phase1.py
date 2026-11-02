"""Focused checks for TLS, readiness validation and infrastructure exit semantics."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography import x509
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import phase1
import prepare
import probe


def workspace_tempdir():
    directory = prepare.ROOT / ".runtime/test-temp"
    directory.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=directory)


def metadata():
    return {
        "credential_issuer": probe.CERTIFY,
        "authorization_servers": [probe.CERTIFY],
        "credential_endpoint": probe.CERTIFY + "/v1/certify/issuance/credential",
        "nonce_endpoint": probe.CERTIFY + "/v1/certify/nonce",
        "credential_configurations_supported": {
            "ConformanceSDJWT": {
                "format": "dc+sd-jwt",
                "vct": probe.CERTIFY + "/credentials/conformance",
                "credential_signing_alg_values_supported": ["ES256"],
                "cryptographic_binding_methods_supported": ["jwk"],
                "proof_types_supported": {"jwt": {"proof_signing_alg_values_supported": ["ES256"]}},
            }
        },
    }


class TLSPreparationTest(unittest.TestCase):
    def test_certificate_chain_sans_and_repeat_preparation(self):
        with workspace_tempdir() as temp:
            directory = Path(temp)
            prepare.prepare_tls(directory)
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            cert = x509.load_pem_x509_certificate(before["server.crt"])
            ca = x509.load_pem_x509_certificate(before["ca.crt"])
            cert.verify_directly_issued_by(ca)
            self.assertFalse(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
            self.assertEqual(set(prepare.HOSTS), set(cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)))
            prepare.prepare_tls(directory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_incomplete_tls_is_rejected_without_rotation(self):
        with workspace_tempdir() as temp:
            directory = Path(temp)
            (directory / "ca.crt").write_text("existing material")
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                prepare.prepare_tls(directory)
            self.assertEqual((directory / "ca.crt").read_text(), "existing material")

    def test_mismatched_private_key_is_rejected(self):
        with workspace_tempdir() as temp:
            first, second = Path(temp) / "first", Path(temp) / "second"
            prepare.prepare_tls(first)
            prepare.prepare_tls(second)
            shutil.copyfile(second / "server.key", first / "server.key")
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                prepare.prepare_tls(first)


class ReadinessValidationTest(unittest.TestCase):
    def test_configured_native_sd_jwt_is_accepted(self):
        probe.validate_metadata(metadata())

    def test_stock_ldp_seed_is_rejected(self):
        body = metadata()
        body["credential_configurations_supported"]["FarmerCredential"] = {"format": "ldp_vc"}
        with self.assertRaisesRegex(ValueError, "LDP"):
            probe.validate_metadata(body)

    def test_remote_as_and_wrong_endpoint_are_rejected(self):
        for field, value in (("authorization_servers", ["https://remote.invalid"]),
                             ("credential_endpoint", probe.CERTIFY + "/v1/certify/v1/certify/issuance/credential")):
            with self.subTest(field=field):
                body = metadata()
                body[field] = value
                with self.assertRaises(ValueError):
                    probe.validate_metadata(body)

    def test_missing_signing_and_binding_metadata_are_rejected(self):
        for field in ("credential_signing_alg_values_supported", "proof_types_supported",
                      "cryptographic_binding_methods_supported"):
            with self.subTest(field=field):
                body = metadata()
                del body["credential_configurations_supported"]["ConformanceSDJWT"][field]
                with self.assertRaises(ValueError):
                    probe.validate_metadata(body)

    def test_missing_final_spec_module_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            probe.validate_modules([{"testName": "older-draft-module"}], "verify")

    def test_network_error_does_not_report_readiness_pass(self):
        class FailedOpener:
            def open(self, *args, **kwargs):
                raise ConnectionError("OIDF unreachable")
        with workspace_tempdir() as temp:
            directory = Path(temp)
            prepare.prepare_tls(directory)
            with patch.object(probe.urllib.request, "build_opener", return_value=FailedOpener()):
                report = probe.run("both", directory / "ca.crt")
            self.assertEqual("ERROR", report["status"])
            self.assertEqual(7, len(report["checks"]))
            self.assertTrue(all(c["status"] == "ERROR" for c in report["checks"]))


class OrchestrationTest(unittest.TestCase):
    def test_missing_docker_exits_two_and_retains_unverified_evidence(self):
        with workspace_tempdir() as temp:
            with patch.object(phase1, "ROOT", Path(temp)), patch.object(phase1, "prepare", return_value={}), \
                 patch.object(phase1.shutil, "which", return_value=None), \
                 patch.object(sys, "argv", ["phase1.py"]), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, phase1.main())
            summaries = list(Path(temp).rglob("summary.json"))
            self.assertEqual(1, len(summaries))
            report = json.loads(summaries[0].read_text())
            self.assertEqual("ERROR", report["status"])
            self.assertFalse(report["runtime_verified"])
            self.assertFalse(report["conformance_executed"])
            self.assertTrue(summaries[0].with_name("error.log").exists())

    def test_prepare_only_cannot_claim_live_success(self):
        with workspace_tempdir() as temp:
            with patch.object(phase1, "ROOT", Path(temp)), patch.object(phase1, "prepare", return_value={}), \
                 patch.object(sys, "argv", ["phase1.py", "--prepare-only"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, phase1.main())
            report = json.loads(next(Path(temp).rglob("summary.json")).read_text())
            self.assertEqual("PREPARED", report["status"])
            self.assertFalse(report["runtime_verified"])

    def test_component_profiles_are_independent(self):
        for name in ("certify", "verify"):
            command = phase1.compose_command(name)
            self.assertEqual(name, command[-1])
            self.assertEqual(1, command.count("--profile"))
        self.assertEqual(2, phase1.compose_command("both").count("--profile"))

    def test_compose_profiles_have_no_missing_dependencies_or_bind_sources(self):
        root = Path(__file__).resolve().parents[1]
        document = yaml.safe_load((root / "compose.yaml").read_text())
        services = document["services"]
        for component in ("certify", "verify", "both"):
            profiles = set(phase1.selected_components(component))
            active = {name for name, service in services.items()
                      if not service.get("profiles") or profiles.intersection(service["profiles"])}
            for name in active:
                service = services[name]
                self.assertIn("healthcheck", service, name)
                self.assertTrue(set(service.get("depends_on", {})).issubset(active), name)
                for mount in service.get("volumes", []):
                    source = mount.split(":", 1)[0]
                    if source.startswith("./"):
                        self.assertTrue((root / source).exists(), source)
                for port in service.get("ports", []):
                    self.assertTrue(port.startswith("127.0.0.1:"), port)


if __name__ == "__main__":
    unittest.main()
