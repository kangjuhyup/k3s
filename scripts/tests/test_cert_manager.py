"""Offline cert-manager installation contracts; no certificate issuance."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture as bootstrap, load


def fixture():
    return {"enabled": True, "reviewed": True}


class CertManagerTests(unittest.TestCase):
    def setUp(self):
        self.module = load("cert_manager_gitops")

    def test_disabled_defaults_and_strict_inputs(self):
        config = json.loads((ROOT / self.module.SETTINGS).read_text())
        self.assertEqual(self.module.render(bootstrap(), config), {})
        for invalid in [{"enabled": True, "reviewed": False}, {"enabled": "yes", "reviewed": True},
                        {**fixture(), "token": "DO_NOT_DISPLAY"}]:
            with self.assertRaises(ValueError):
                self.module.render(bootstrap(), invalid)
        config = bootstrap()
        config["kube_version"] = "1.32.1"
        with self.assertRaises(ValueError):
            self.module.render(config, fixture())

    def test_gitops_ownership_and_pinned_chart(self):
        files = self.module.render(bootstrap(), fixture())
        application = files[self.module.ROOT + "/cert-manager.json"]["spec"]
        self.assertEqual(application["sources"][0]["targetRevision"], "v1.21.1")
        self.assertFalse(application["syncPolicy"]["automated"]["prune"])
        self.assertIn("RespectIgnoreDifferences=true", application["syncPolicy"]["syncOptions"])
        project = files[self.module.ROOT + "/cert-manager-project.json"]["spec"]
        self.assertNotIn("Secret", [r["kind"] for r in project["namespaceResourceWhitelist"]])
        self.assertEqual({d["namespace"] for d in project["destinations"]}, {"cert-manager"})
        self.assertFalse(any(o.get("kind") in {"Secret", "Certificate", "ClusterIssuer"} for o in files.values()))

    def test_root_connection_and_disabling_requires_retirement(self):
        gitops = load("argocd_gitops")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, obj in [(gitops.SETTINGS_PATH, bootstrap()), (self.module.SETTINGS, fixture())]:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(obj))
            files = gitops.render_repository(root)
            self.assertIn("cert-manager.json", files[gitops.ROOT_PATH + "/kustomization.yaml"]["resources"])
            target = root / gitops.ROOT_PATH / "cert-manager.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(files[gitops.ROOT_PATH + "/cert-manager.json"]))
            (root / self.module.SETTINGS).write_text(json.dumps({"enabled": False, "reviewed": False}))
            with self.assertRaises(ValueError):
                gitops.render_repository(root)

    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("CERT_MANAGER_TEST_CHART"), "local Helm/chart not supplied")
    def test_official_chart_security_images_crds_and_project_permissions(self):
        objects = load("cert_manager_validate").render(ROOT, Path(os.environ["HELM_TEST_BINARY"]),
                                                     Path(os.environ["CERT_MANAGER_TEST_CHART"]), "1.35.1")
        project = self.module.render(bootstrap(), fixture())[self.module.ROOT + "/cert-manager-project.json"]["spec"]
        for obj in objects:
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            scope = "namespace" if obj["metadata"].get("namespace") else "cluster"
            self.assertIn({"group": group, "kind": obj["kind"]}, project[scope + "ResourceWhitelist"])
        self.assertEqual(len([o for o in objects if o["kind"] == "CustomResourceDefinition"]), 6)
        self.assertEqual(len([o for o in objects if o["kind"] == "Deployment"]), 3)
