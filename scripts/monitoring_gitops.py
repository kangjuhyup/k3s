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
                           "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true", "RespectIgnoreDifferences=true", "SkipDryRunOnMissingResource=true"]}}
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
        for role in ["master", "replica"]:
            name = "redis-metrics-" + role
            labels = {"app.kubernetes.io/name": "redis-metrics", "redis-role": role}
            def secret_env(name, key):
                return {"name": name, "valueFrom": {"secretKeyRef": {"name": "redis-metrics", "key": key}}}
            container = {"name": "exporter", "image": "docker.io/oliver006/redis_exporter:v1.91.1@sha256:c67a432dba6b4ae30f471e3c77cf14a289133bbeeb89abb0bb03e6092efb2836",
                         "args": ["--config-command=-", "--log-level=fatal"],
                         "env": [secret_env("REDIS_HOST", role + "-host"), secret_env("REDIS_PORT", "port"),
                                 secret_env("REDIS_USER", "username"), secret_env("REDIS_PASSWORD", "password"),
                                 {"name": "REDIS_ADDR", "value": "rediss://$(REDIS_HOST):$(REDIS_PORT)"},
                                 {"name": "REDIS_EXPORTER_TLS_CA_CERT_FILE", "value": "/tls/ca.crt"},
                                 {"name": "REDIS_EXPORTER_TLS_CLIENT_CERT_FILE", "value": "/tls/tls.crt"},
                                 {"name": "REDIS_EXPORTER_TLS_CLIENT_KEY_FILE", "value": "/tls/tls.key"}],
                         "ports": [{"name": "metrics", "containerPort": 9121}],
                         "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"memory": "64Mi"}},
                         "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                         "volumeMounts": [{"name": "tls", "mountPath": "/tls", "readOnly": True}],
                         "readinessProbe": {"httpGet": {"path": "/health", "port": "metrics"}},
                         "livenessProbe": {"httpGet": {"path": "/health", "port": "metrics"}}}
            files[PATH + "/" + name + ".json"] = {"apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": name, "namespace": "monitoring"}, "spec": {"replicas": 1,
                "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": {
                    "automountServiceAccountToken": False, "securityContext": {"runAsNonRoot": True, "runAsUser": 65534,
                        "runAsGroup": 65534, "fsGroup": 65534, "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [container], "volumes": [{"name": "tls", "secret": {"secretName": "redis-metrics",
                        "defaultMode": 288, "items": [{"key": k, "path": k} for k in ["ca.crt", "tls.crt", "tls.key"]]}}]}}}}
            resources.append(name + ".json")
        files[PATH + "/redis-podmonitor.json"] = {"apiVersion": "monitoring.coreos.com/v1", "kind": "PodMonitor",
            "metadata": {"name": "redis", "namespace": "monitoring", "labels": {"release": "monitoring"}},
            "spec": {"selector": {"matchLabels": {"app.kubernetes.io/name": "redis-metrics"}},
                     "podTargetLabels": ["redis-role"], "podMetricsEndpoints": [{"port": "metrics", "interval": "30s"}]}}
        resources.append("redis-podmonitor.json")
        files[PATH + "/database-rules.json"] = {"apiVersion": "monitoring.coreos.com/v1", "kind": "PrometheusRule",
            "metadata": {"name": "database-health", "namespace": "monitoring", "labels": {"release": "monitoring"}},
            "spec": {"groups": [{"name": "database-health", "rules": [
                {"alert": "RedisUnavailable", "expr": "redis_up == 0", "for": "2m", "labels": {"severity": "critical"},
                 "annotations": {"summary": "Redis authentication or availability check failed"}},
                {"alert": "RedisReplicationDisconnected", "expr": "redis_master_link_up == 0", "for": "2m", "labels": {"severity": "critical"},
                 "annotations": {"summary": "Redis replica has lost its master connection"}},
                {"alert": "RedisMemoryNearLimit", "expr": "redis_memory_used_bytes / redis_memory_max_bytes > 0.85", "for": "5m", "labels": {"severity": "warning"},
                 "annotations": {"summary": "Redis memory is above 85 percent of its configured limit"}},
                {"alert": "PostgreSQLCollectorUnavailable", "expr": "cnpg_collector_up == 0", "for": "2m", "labels": {"severity": "critical"},
                 "annotations": {"summary": "PostgreSQL monitoring connection failed"}}
            ]}]}}
        resources.append("database-rules.json")
    files[PATH + "/kustomization.yaml"] = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources}
    return files
