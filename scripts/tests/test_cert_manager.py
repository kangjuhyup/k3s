"""Offline cert-manager installation contracts; no certificate issuance."""
import os
from pathlib import Path
import unittest

from test_argocd_gitops import manifest_files, layout, ROOT, load


class CertManagerTests(unittest.TestCase):
    def setUp(self):
        self.module = layout("cert-manager")


    def test_gitops_ownership_and_pinned_chart(self):
        files = manifest_files("cert-manager")
        application = files[self.module.ROOT + "/cert-manager.yaml"]["spec"]
        self.assertEqual(application["sources"][0]["targetRevision"], "v1.21.1")
        self.assertFalse(application["syncPolicy"]["automated"]["prune"])
        self.assertIn("RespectIgnoreDifferences=true", application["syncPolicy"]["syncOptions"])
        project = files[self.module.ROOT + "/cert-manager-project.yaml"]["spec"]
        self.assertNotIn("Secret", [r["kind"] for r in project["namespaceResourceWhitelist"]])
        self.assertEqual({d["namespace"] for d in project["destinations"]}, {"cert-manager"})
        self.assertFalse(any(o.get("kind") in {"Secret", "Certificate", "ClusterIssuer"} for o in files.values()))


    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("CERT_MANAGER_TEST_CHART"), "local Helm/chart not supplied")
    def test_official_chart_security_images_crds_and_project_permissions(self):
        objects = load("cert_manager_validate").render(ROOT, Path(os.environ["HELM_TEST_BINARY"]),
                                                     Path(os.environ["CERT_MANAGER_TEST_CHART"]), "1.35.1")
        project = manifest_files()[self.module.ROOT + "/cert-manager-project.yaml"]["spec"]
        for obj in objects:
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            scope = "namespace" if obj["metadata"].get("namespace") else "cluster"
            self.assertIn({"group": group, "kind": obj["kind"]}, project[scope + "ResourceWhitelist"])
        self.assertEqual(len([o for o in objects if o["kind"] == "CustomResourceDefinition"]), 6)
        self.assertEqual(len([o for o in objects if o["kind"] == "Deployment"]), 3)
