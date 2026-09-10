"""Database creation requires delivered credentials and keeps application isolation."""
import unittest
from test_argocd_gitops import manifest_files, load


class PostgreSQLTests(unittest.TestCase):

    def test_database_is_private_single_instance_and_has_no_backup_credentials(self):
        config = {"database_enabled": True, "credentials_ready_reviewed": True,
                  "preserve_existing_bootstrap": True, "storage_size": "10Gi"}
        objects = manifest_files("postgresql")
        spec = next(v for v in objects.values() if v.get("kind") == "Cluster")["spec"]
        self.assertEqual(spec["instances"], 1)
        self.assertEqual(spec["storage"]["size"], "10Gi")
        self.assertFalse(spec["enableSuperuserAccess"])
        self.assertNotIn("backup", spec)
        self.assertEqual(spec["postgresql"]["pg_hba"][-1], "host all all all reject")
        self.assertFalse(any(v.get("kind") in {"Secret", "Service"} for v in objects.values()))
        self.assertEqual(spec["bootstrap"]["initdb"]["database"], "postgres")
        self.assertNotIn("secret", spec["bootstrap"]["initdb"])
        self.assertIn("@/projected/identity/database", spec["postgresql"]["pg_hba"][0])
        app = next(v for v in objects.values() if v.get("kind") == "Application")
        self.assertEqual(app["spec"]["ignoreDifferences"][0]["jsonPointers"], ["/spec/bootstrap"])

    def test_private_sql_quotes_password_and_rejects_identifier_injection(self):
        module = load("postgresql_private_bootstrap")
        sql = module.statements("example_db", "example_user", "abc'def\\ghi")
        self.assertIn("abc''def", sql["DB_INIT_ROLE_SQL"])
        self.assertEqual(len(sql), 3)
        with self.assertRaises(ValueError):
            module.statements('invalid"; SELECT 1', "example_user", "password")

    def test_basic_auth_requires_both_username_and_password(self):
        from test_doppler_gitops import fixture as mapping_fixture
        module = load("doppler_gitops")
        config = mapping_fixture()
        mapping = config["mappings"][0]
        mapping.update(target_namespace="databases", type="kubernetes.io/basic-auth",
                       keys={"DB_USER": "username", "DB_PASSWORD": "password"})
        module.validate(config)
        mapping["keys"].pop("DB_USER")
        with self.assertRaises(ValueError):
            module.validate(config)
