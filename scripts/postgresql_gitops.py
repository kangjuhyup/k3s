"""Shared single-instance PostgreSQL; explicit gate after credential delivery."""

SETTINGS = "gitops/clusters/oci-a1/postgresql.json"
PATH = "gitops/clusters/oci-a1/postgresql"
ROOT = "gitops/clusters/oci-a1/root"
IMAGE = "ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie@sha256:42708a75345b7a48fdd9257b071830783a97fd228529196b6313187a7198e185"


def require(condition):
    if not condition:
        raise ValueError("Invalid PostgreSQL configuration; values are not displayed.")


def resource(kind, name, spec, wave):
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": kind,
            "metadata": {"name": name, "namespace": "argocd", "annotations": {"argocd.argoproj.io/sync-wave": wave}},
            "spec": spec}


def sync_policy():
    return {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
            "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"]}


def render(bootstrap, config):
    require(set(config) == {"database_enabled", "credentials_ready_reviewed", "preserve_existing_bootstrap", "storage_size"})
    require(all(type(config[k]) is bool for k in ["database_enabled", "credentials_ready_reviewed", "preserve_existing_bootstrap"]))
    require(config["storage_size"] == "10Gi")
    require(not config["database_enabled"] or config["credentials_ready_reviewed"])
    destination = {"server": "https://kubernetes.default.svc", "namespace": "databases"}
    project = resource("AppProject", "platform-postgresql", {
        "sourceRepos": [bootstrap["repo_url"]], "destinations": [destination],
        "clusterResourceWhitelist": [{"group": "", "kind": "Namespace"}],
        "namespaceResourceWhitelist": [{"group": "postgresql.cnpg.io", "kind": "Cluster"}]}, "-10")
    app = resource("Application", "postgresql", {
        "project": "platform-postgresql", "destination": destination,
        "source": {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "path": PATH},
        "syncPolicy": sync_policy()}, "40")
    if config["preserve_existing_bootstrap"]:
        # Existing CNPG bootstrap remains live-owned; never replace its application identity.
        # RespectIgnoreDifferences has no effect on first creation: the generic private SQL path is used then.
        app["spec"]["syncPolicy"]["syncOptions"].append("RespectIgnoreDifferences=true")
        app["spec"]["ignoreDifferences"] = [{"group": "postgresql.cnpg.io", "kind": "Cluster",
            "name": "shared-postgres", "namespace": "databases", "jsonPointers": ["/spec/bootstrap"]}]
    files = {ROOT + "/postgresql-project.json": project, ROOT + "/postgresql.json": app,
             PATH + "/namespace.json": {"apiVersion": "v1", "kind": "Namespace", "metadata": {
                 "name": "databases", "labels": {"istio-injection": "disabled"}, "annotations": {
                     "argocd.argoproj.io/sync-wave": "-20", "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}}}}
    resources = ["namespace.json"]
    if config["database_enabled"]:
        files[PATH + "/cluster.json"] = {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster",
            "metadata": {"name": "shared-postgres", "namespace": "databases", "annotations": {
                "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}},
            "spec": {"instances": 1, "imageName": IMAGE, "enableSuperuserAccess": False,
                "storage": {"size": config["storage_size"], "storageClass": "local-path", "resizeInUseVolumes": False},
                "resources": {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"memory": "2Gi"}},
                "bootstrap": {"initdb": {"database": "postgres", "owner": "postgres", "dataChecksums": True,
                    "postInitSQLRefs": {"secretRefs": [{"name": "auth-db-private", "key": key}
                        for key in ["01-role.sql", "02-database.sql", "03-acl.sql"]]}}},
                "projectedVolumeTemplate": {"sources": [{"secret": {"name": "auth-db-private",
                    "items": [{"key": "database", "path": "identity/database"}, {"key": "username", "path": "identity/username"}]}}]},
                "postgresql": {"parameters": {"max_connections": "100", "shared_buffers": "256MB"},
                    "pg_hba": ["hostssl @/projected/identity/database @/projected/identity/username all scram-sha-256", "host all all all reject"]}}}
        resources.append("cluster.json")
    files[PATH + "/kustomization.yaml"] = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources}
    return files
