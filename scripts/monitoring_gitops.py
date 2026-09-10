#!/usr/bin/env python3
"""Monitoring namespace first, then pinned stack after Doppler delivery is verified."""
SETTINGS = "gitops/clusters/oci-a1/monitoring.json"
PATH = "gitops/clusters/oci-a1/monitoring"
ROOT = "gitops/clusters/oci-a1/root"
VALUES = "gitops/platform/monitoring/base.values.json"
REPOSITORY = "https://prometheus-community.github.io/helm-charts"
VERSION = "90.0.0"


def render(bootstrap, config):
    if (not isinstance(config, dict) or set(config) != {"enabled", "credentials_ready_reviewed"}
            or any(type(v) is not bool for v in config.values())
            or (config["enabled"] and not config["credentials_ready_reviewed"])):
        raise ValueError("Monitoring requires reviewed secret delivery; values suppressed")
    destination = {"server": "https://kubernetes.default.svc", "namespace": "monitoring"}
    git = {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "path": PATH}
    spec = {"project": "platform-monitoring", "destination": destination,
            "syncPolicy": {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
                           "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true", "RespectIgnoreDifferences=true"]}}
    if config["enabled"]:
        spec["sources"] = [{"repoURL": REPOSITORY, "chart": "kube-prometheus-stack", "targetRevision": VERSION,
                            "helm": {"releaseName": "monitoring", "kubeVersion": bootstrap["kube_version"],
                                     "valueFiles": ["$values/" + VALUES], "skipTests": True}}, dict(git, ref="values")]
        spec["ignoreDifferences"] = [{"group": "admissionregistration.k8s.io", "kind": k,
                                       "jqPathExpressions": [".webhooks[]?.clientConfig.caBundle"]}
                                      for k in ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"]]
    else:
        spec["source"] = git
    def argo(kind, name, body, wave):
        return {"apiVersion": "argoproj.io/v1alpha1", "kind": kind,
                "metadata": {"name": name, "namespace": "argocd", "annotations": {"argocd.argoproj.io/sync-wave": wave}},
                "spec": body}
    project = {"sourceRepos": [bootstrap["repo_url"], REPOSITORY],
               "destinations": [destination, dict(destination, namespace="kube-system")],
               "clusterResourceWhitelist": [{"group": g, "kind": k} for g, k in [
                   ("", "Namespace"), ("apiextensions.k8s.io", "CustomResourceDefinition"),
                   ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
                   ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
                   ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration")]],
               "namespaceResourceWhitelist": [{"group": g, "kind": k} for g, k in [
                   ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("", "Secret"),
                   ("", "PersistentVolumeClaim"), ("apps", "Deployment"), ("apps", "DaemonSet"),
                   ("batch", "Job"), ("rbac.authorization.k8s.io", "Role"), ("rbac.authorization.k8s.io", "RoleBinding"),
                   ("monitoring.coreos.com", "Prometheus"), ("monitoring.coreos.com", "Alertmanager"),
                   ("monitoring.coreos.com", "ServiceMonitor"), ("monitoring.coreos.com", "PodMonitor"),
                   ("monitoring.coreos.com", "PrometheusRule")]]}
    files = {ROOT + "/monitoring-project.json": argo("AppProject", "platform-monitoring", project, "-10"),
             ROOT + "/monitoring.json": argo("Application", "monitoring", spec, "60" if config["enabled"] else "25"),
             PATH + "/namespace.json": {"apiVersion": "v1", "kind": "Namespace", "metadata": {
                 "name": "monitoring", "labels": {"istio-injection": "disabled"},
                 "annotations": {"argocd.argoproj.io/sync-wave": "-20", "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}}}}
    resources = ["namespace.json"]
    if config["enabled"]:
        files[PATH + "/postgresql-podmonitor.json"] = {
            "apiVersion": "monitoring.coreos.com/v1", "kind": "PodMonitor", "metadata": {
                "name": "postgresql", "namespace": "monitoring", "labels": {"release": "monitoring"}},
            "spec": {"namespaceSelector": {"matchNames": ["databases"]},
                     "selector": {"matchLabels": {"cnpg.io/cluster": "shared-postgres"}},
                     "podMetricsEndpoints": [{"port": "metrics", "interval": "30s"}]}}
        resources.append("postgresql-podmonitor.json")
    files[PATH + "/kustomization.yaml"] = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources}
    return files
