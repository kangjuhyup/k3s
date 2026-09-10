"""Git-owned declarations reject unsafe changes without rewriting the repository."""
import json
from pathlib import Path
import shutil
import tempfile
import yaml
import unittest

from test_argocd_gitops import ROOT, load


class DeclarationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.validator = load("gitops_validate")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / "gitops", self.root / "gitops")

    def change(self, path, mutate):
        target = self.root / "gitops/clusters/oci-a1" / path
        obj = yaml.safe_load(target.read_text())
        mutate(obj)
        target.write_text(yaml.safe_dump(obj, sort_keys=False))

    def test_current_manifests_validate_without_any_file_changes(self):
        before = {p: p.read_bytes() for p in (self.root / "gitops").rglob("*") if p.is_file()}
        files = self.validator.validate_repository(self.root)
        self.assertIn("gitops/clusters/oci-a1/auth/hpa.yaml", files)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_draft_workloads_still_require_immutable_images(self):
        self.change("auth/auth-service-patch.yaml", lambda o: o["spec"]["template"]["spec"]["containers"][0].update(image="example.invalid/auth:main"))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_secret_values_cannot_be_added_even_outside_active_paths(self):
        target = self.root / "gitops/forbidden.yaml"
        target.write_text(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "synthetic"}, "stringData": {"token": "DO_NOT_DISPLAY"}}))
        with self.assertRaises(ValueError) as error:
            self.validator.validate_repository(self.root)
        self.assertNotIn("DO_NOT_DISPLAY", str(error.exception))

    def test_hpa_replica_ownership_cannot_be_overridden_by_git(self):
        self.change("auth/auth-service-patch.yaml", lambda o: o["spec"].update(replicas=1))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_automatic_resource_deletion_requires_explicit_retirement(self):
        self.change("root/auth.yaml", lambda o: o["spec"]["syncPolicy"]["automated"].update(prune=True))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_live_certificate_must_be_covered_by_dns_issuer(self):
        self.change("monitoring/grafana-certificate.yaml", lambda o: o["spec"].update(dnsNames=["unconfigured.example.invalid"]))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_public_gateway_cannot_accept_wildcard_hosts(self):
        self.change("monitoring/grafana-gateway.yaml", lambda o: o["spec"]["servers"][1].update(hosts=["./*.rvkang.app"]))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_gateway_certificate_reference_must_resolve(self):
        self.change("monitoring/grafana-gateway.yaml", lambda o: o["spec"]["servers"][1]["tls"].update(credentialName="absent-tls"))
        with self.assertRaises((ValueError, StopIteration)):
            self.validator.validate_repository(self.root)

    def test_http_gateway_cannot_disable_https_redirect(self):
        self.change("monitoring/grafana-gateway.yaml", lambda o: o["spec"]["servers"][0]["tls"].update(httpsRedirect=False))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_application_cannot_be_silently_removed_from_root(self):
        self.change("root/kustomization.yaml", lambda o: o["resources"].remove("auth.yaml"))
        with self.assertRaises(ValueError):
            self.validator.validate_repository(self.root)

    def test_missing_kustomize_resource_is_not_silently_ignored(self):
        (self.root / "gitops/clusters/oci-a1/root/auth.yaml").unlink()
        with self.assertRaises(OSError):
            self.validator.validate_repository(self.root)

    def test_symlinked_git_inputs_are_rejected(self):
        source = self.root / "gitops/clusters/oci-a1/bootstrap.json"
        (self.root / "gitops/alias.yaml").symlink_to(source)
        with self.assertRaises(ValueError):
            self.validator.read_repository(self.root)

    def test_yaml_duplicate_keys_are_rejected_without_echoing_values(self):
        target = self.root / "gitops/duplicate.yaml"
        target.write_text("kind: ConfigMap\nkind: DO_NOT_DISPLAY\n")
        with self.assertRaises(ValueError) as error:
            self.validator.read_json(target)
        self.assertNotIn("DO_NOT_DISPLAY", str(error.exception))

    def test_json_runtime_configuration_remains_supported(self):
        config = self.validator.read_json(self.root / "gitops/clusters/oci-a1/bootstrap.json")
        self.assertEqual(config["revision"], "main")
        self.assertIs(self.validator.validate(config), config)
