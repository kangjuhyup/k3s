#!/usr/bin/env python3
"""Offline render of the pinned cert-manager chart; no cluster or issuer calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import yaml


def require(condition):
    if not condition:
        raise ValueError("cert-manager artifact or rendered configuration mismatch.")


def render(root, helm, chart, kube_version):
    require(kube_version.startswith("1.") and len(kube_version.split(".")) == 3)
    require(33 <= int(kube_version.split(".")[1]) <= 36)
    lock = json.loads((root / "gitops/platform/cert-manager/versions.json").read_text())
    require(lock["version"] == "v1.21.1" and lock["repository"] == "https://charts.jetstack.io")
    require(hashlib.sha256(chart.read_bytes()).hexdigest() == lock["sha256"])

    def run(args):
        result = subprocess.run([str(helm), *args], text=True, capture_output=True, timeout=45,
                                check=False, env={"PATH": os.defpath})
        require(result.returncode == 0)
        return result.stdout

    require(run(["version", "--template", "{{.Version}} "]).strip() == lock["helm_version"])
    values_path = root / "gitops/platform/cert-manager/base.values.json"
    values = json.loads(values_path.read_text())
    objects = [o for o in yaml.safe_load_all(run([
        "template", "cert-manager", str(chart), "--namespace", "cert-manager", "--kube-version", kube_version,
        "--values", str(values_path)])) if o]
    allowed = {"CustomResourceDefinition", "ServiceAccount", "ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding",
               "Service", "ConfigMap", "Deployment", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}
    require(all(o["kind"] in allowed for o in objects))
    images = {values["image"]["repository"] + ":" + values["image"]["tag"] + "@" + values["image"]["digest"]}
    for name in ["webhook", "cainjector"]:
        item = values[name]["image"]
        images.add(item["repository"] + ":" + item["tag"] + "@" + item["digest"])
    require(all("@sha256:" in value for value in images))
    seen, crds, deployments = set(), 0, 0
    for obj in objects:
        annotations = obj["metadata"].get("annotations", {})
        require("helm.sh/hook" not in annotations and "argocd.argoproj.io/hook" not in annotations)
        if "namespace" in obj["metadata"]:
            require(obj["metadata"]["namespace"] == "cert-manager")
        if obj["kind"] == "CustomResourceDefinition":
            crds += 1
            require(annotations.get("helm.sh/resource-policy") == "keep")
        if obj["kind"] == "Deployment":
            deployments += 1
            require(obj["spec"]["replicas"] == 1 and annotations.get("argocd.argoproj.io/sync-wave") == "10")
            pod = obj["spec"]["template"]["spec"]
            require(pod["nodeSelector"] == {"kubernetes.io/os": "linux", "kubernetes.io/arch": "arm64"})
            require(not pod.get("hostNetwork") and not pod.get("initContainers"))
            require(pod["securityContext"]["runAsNonRoot"] is True)
            require(pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault")
            for container in pod["containers"]:
                require(container["image"] in images)
                seen.add(container["image"])
                require(container["securityContext"]["allowPrivilegeEscalation"] is False)
                require(container["securityContext"]["capabilities"]["drop"] == ["ALL"])
                require(container["resources"].get("requests") and container["resources"].get("limits"))
        if obj["kind"] == "Service":
            require(obj["spec"].get("type", "ClusterIP") == "ClusterIP")
        if obj["kind"].endswith("WebhookConfiguration"):
            require(all(w["failurePolicy"] == "Fail" and not w["clientConfig"].get("caBundle") for w in obj["webhooks"]))
    require(crds == 6 and deployments == 3 and seen == images)
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--helm", type=Path, required=True)
    parser.add_argument("--chart", type=Path, required=True)
    parser.add_argument("--kube-version", required=True)
    args = parser.parse_args()
    try:
        objects = render(args.repo_root.resolve(), args.helm.resolve(), args.chart.resolve(), args.kube_version)
        print(f"cert-manager: {len(objects)} objects validated offline. No issuance or deployment occurred.")
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, yaml.YAMLError):
        print("cert-manager validation blocked: invalid artifacts or configuration; values are not displayed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
