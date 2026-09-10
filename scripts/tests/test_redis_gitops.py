"""Shared Redis isolation and constrained single-node replication contracts."""
import unittest
from test_argocd_gitops import fixture, load


class RedisTests(unittest.TestCase):
    def setUp(self):
        self.module = load("redis_gitops")
        self.objects = self.module.render(fixture(), {"enabled": True, "credentials_ready_reviewed": True,
                                                   "mtls_enabled": True, "tls_revision": 1})

    def test_two_persistent_instances_each_have_256_mib_limit(self):
        states = [o for o in self.objects.values() if o.get("kind") == "StatefulSet"]
        self.assertEqual(len(states), 2)
        for obj in states:
            spec = obj["spec"]
            self.assertEqual(spec["replicas"], 1)
            pod = spec["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(pod["containers"][0]["resources"]["limits"]["memory"], "256Mi")
            self.assertEqual(spec["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"], "1Gi")
            self.assertEqual(spec["persistentVolumeClaimRetentionPolicy"]["whenDeleted"], "Retain")
            self.assertEqual(spec["volumeClaimTemplates"][0]["apiVersion"], "v1")
            self.assertEqual(spec["volumeClaimTemplates"][0]["kind"], "PersistentVolumeClaim")

    def test_unreviewed_credentials_block_deployment(self):
        with self.assertRaises(ValueError):
            self.module.render(fixture(), {"enabled": True, "credentials_ready_reviewed": False})

    def test_service_accounts_use_private_acl_inputs_and_no_global_key_discovery(self):
        self.assertFalse(any(o.get("kind") in {"Secret", "Namespace", "Ingress"} for o in self.objects.values()))
        for o in self.objects.values():
            if o.get("kind") == "Service":
                self.assertIn(o["spec"].get("type"), [None, "ClusterIP"])
        for rule in ["user default off", "~%s*", "resetchannels", "-@dangerous", "-@scripting", "-keys -scan -randomkey -dbsize"]:
            self.assertIn(rule, self.module.START)
        self.assertIn("maxmemory 128mb", self.module.CONFIG)
        self.assertIn("replica-ignore-maxmemory yes", self.module.CONFIG)
        self.assertIn("appendonly yes", self.module.CONFIG)
        self.assertIn("maxmemory-policy noeviction", self.module.CONFIG)
        self.assertNotIn("--user", self.module.HEALTH)
        self.assertIn("AUTH %s %s", self.module.HEALTH)
        self.assertIn("INFO server", self.module.HEALTH)
        for directive in ["port 0", "tls-port 6379", "tls-auth-clients yes", "tls-replication yes"]:
            self.assertIn(directive, self.module.CONFIG)
        for obj in self.objects.values():
            if obj.get("kind") == "StatefulSet":
                pod = obj["spec"]["template"]["spec"]
                tls = next(v for v in pod["volumes"] if v["name"] == "tls")
                self.assertEqual(tls["secret"]["secretName"], obj["metadata"]["name"] + "-tls")
                self.assertNotIn("ca-key", str(pod))
