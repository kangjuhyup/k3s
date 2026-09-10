#!/usr/bin/env python3
"""Pinned CNPG operator only; database and credentials are configured separately."""
SETTINGS = "gitops/clusters/oci-a1/cnpg.json"
PATH = "gitops/clusters/oci-a1/cnpg"
ROOT = "gitops/clusters/oci-a1/root"
VALUES = "gitops/platform/cnpg/base.values.json"
REPOSITORY = "https://cloudnative-pg.github.io/charts"
VERSION = "0.29.0"
NAMESPACE = "cnpg-system"


def require(condition):
    if not condition:
        raise ValueError("Invalid cnpg configuration or unsafe ownership change; values are not displayed.")


def render(bootstrap, config):
    require(isinstance(config, dict) and set(config) == {"enabled", "reviewed"})
    require(all(type(config[k]) is bool for k in config))
    if not config["enabled"]:
        return {}
    require(config["reviewed"] and 34 <= int(bootstrap["kube_version"].split(".")[1]) <= 36)
    destination = {"server": "https://kubernetes.default.svc", "namespace": NAMESPACE}

    def resource(kind, name, spec, wave):
        return {"apiVersion": "argoproj.io/v1alpha1", "kind": kind,
                "metadata": {"name": name, "namespace": "argocd", "annotations": {"argocd.argoproj.io/sync-wave": wave}},
                "spec": spec}

    project = resource("AppProject", "platform-cnpg", {
        "description": "Administrator-only PostgreSQL operator and admission; no Git-owned Secret data",
        "sourceRepos": [bootstrap["repo_url"], REPOSITORY], "destinations": [destination],
        "clusterResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "Namespace"), ("apiextensions.k8s.io", "CustomResourceDefinition"),
            ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
            ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
            ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration")]],
        "namespaceResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("apps", "Deployment"),
            ("rbac.authorization.k8s.io", "Role"), ("rbac.authorization.k8s.io", "RoleBinding")]]}, "-10")
    app = resource("Application", "cnpg", {
        "project": "platform-cnpg", "destination": destination,
        "sources": [{"repoURL": REPOSITORY, "chart": "cloudnative-pg", "targetRevision": VERSION,
                     "helm": {"releaseName": "cnpg", "kubeVersion": bootstrap["kube_version"],
                              "valueFiles": ["$values/" + VALUES]}},
                    {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "ref": "values", "path": PATH}],
        "syncPolicy": {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
                       "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true", "RespectIgnoreDifferences=true"]},
        "ignoreDifferences": [{"group": "admissionregistration.k8s.io", "kind": k,
                               "jqPathExpressions": [".webhooks[]?.clientConfig.caBundle"]}
                              for k in ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"]]}, "35")
    return {ROOT + "/cnpg-project.json": project, ROOT + "/cnpg.json": app,
            PATH + "/namespace.json": {"apiVersion": "v1", "kind": "Namespace", "metadata": {
                "name": NAMESPACE, "labels": {"istio-injection": "disabled"},
                "annotations": {"argocd.argoproj.io/sync-wave": "-20", "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}}},
            PATH + "/kustomization.yaml": {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                                            "resources": ["namespace.json"]}}
