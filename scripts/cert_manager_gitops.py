#!/usr/bin/env python3
"""Pinned cert-manager foundation. Issuance is configured separately from installation."""
SETTINGS = "gitops/clusters/oci-a1/cert-manager.json"
PATH = "gitops/clusters/oci-a1/cert-manager"
ROOT = "gitops/clusters/oci-a1/root"
VALUES = "gitops/platform/cert-manager/base.values.json"
REPOSITORY = "https://charts.jetstack.io"
VERSION = "v1.21.1"
NAMESPACE = "cert-manager"


def require(condition):
    if not condition:
        raise ValueError("Invalid cert-manager configuration or unsafe ownership change; values are not displayed.")


def render(bootstrap, config):
    require(isinstance(config, dict) and set(config) == {"enabled", "reviewed"})
    require(all(type(config[k]) is bool for k in config))
    if not config["enabled"]:
        return {}
    require(config["reviewed"] and 33 <= int(bootstrap["kube_version"].split(".")[1]) <= 36)
    destination = {"server": "https://kubernetes.default.svc", "namespace": NAMESPACE}

    def resource(kind, name, spec, wave):
        return {"apiVersion": "argoproj.io/v1alpha1", "kind": kind,
                "metadata": {"name": name, "namespace": "argocd", "annotations": {"argocd.argoproj.io/sync-wave": wave}},
                "spec": spec}

    project = resource("AppProject", "platform-cert-manager", {
        "description": "Administrator-only certificate controller and admission; no Git-owned Secret data",
        "sourceRepos": [bootstrap["repo_url"], REPOSITORY], "destinations": [destination],
        "clusterResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "Namespace"), ("apiextensions.k8s.io", "CustomResourceDefinition"),
            ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
            ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
            ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration")]],
        "namespaceResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("apps", "Deployment"),
            ("rbac.authorization.k8s.io", "Role"), ("rbac.authorization.k8s.io", "RoleBinding")]]}, "-10")
    app = resource("Application", "cert-manager", {
        "project": "platform-cert-manager", "destination": destination,
        "sources": [{"repoURL": REPOSITORY, "chart": "cert-manager", "targetRevision": VERSION,
                     "helm": {"releaseName": "cert-manager", "kubeVersion": bootstrap["kube_version"],
                              "valueFiles": ["$values/" + VALUES]}},
                    {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "ref": "values", "path": PATH}],
        "syncPolicy": {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
                       "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true", "RespectIgnoreDifferences=true"]},
        "ignoreDifferences": [{"group": "admissionregistration.k8s.io", "kind": k,
                               "name": "cert-manager-webhook", "jqPathExpressions": [".webhooks[]?.clientConfig.caBundle"]}
                              for k in ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"]]}, "25")
    return {ROOT + "/cert-manager-project.json": project, ROOT + "/cert-manager.json": app,
            PATH + "/namespace.json": {"apiVersion": "v1", "kind": "Namespace", "metadata": {
                "name": NAMESPACE, "labels": {"istio-injection": "disabled"},
                "annotations": {"argocd.argoproj.io/sync-wave": "-20", "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}}},
            PATH + "/kustomization.yaml": {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                                            "resources": ["namespace.json"]}}
