#!/usr/bin/env python3
"""Prepare a public, checked Git-revision bootstrap bundle. No cluster access."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gitops = load("gitops_validate")
accounts = load("argocd_accounts")
runtime = load("argocd_bootstrap_runtime")


def run(args, cwd):
    environment = {"PATH": os.defpath}
    if "HOME" in os.environ:
        environment["HOME"] = os.environ["HOME"]
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, timeout=60, env=environment)
    gitops.require(result.returncode == 0)
    return result.stdout


def verify_checkout(root, revision):
    gitops.require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None)
    gitops.require(run(["git", "rev-parse", "HEAD"], root).strip() == revision)
    # Git-managed code, source settings and outputs must match the same checkout.
    gitops.require(not run(["git", "status", "--porcelain", "--untracked-files=all", "--", "ansible", "scripts", "gitops"], root).strip())
    gitops.require(run(["git", "ls-files", "--error-unmatch", gitops.SETTINGS_PATH], root).strip() == gitops.SETTINGS_PATH)


def render_chart(root, helm, chart, config):
    versions = gitops.read_json(root / "gitops/platform/argocd/versions.json")
    gitops.require(versions["version"] == gitops.CHART_VERSION and versions["repository"] == gitops.CHART_REPO)
    gitops.require(hashlib.sha256(chart.read_bytes()).hexdigest() == versions["sha256"])
    gitops.require(run([str(helm), "version", "--template", "{{.Version}}"], root).strip() == versions["helm_version"])
    raw = run([str(helm), "template", "argocd", str(chart), "--namespace", "argocd",
               "--kube-version", config["kube_version"],
               "--values", str(root / gitops.BASE_PATH), "--values", str(root / gitops.ENV_PATH),
               "--values", str(root / gitops.ACCOUNTS_PATH)], root)
    resources = [doc for doc in yaml.safe_load_all(raw) if doc]
    # kubectl create orders prerequisite objects ahead of their consumers.
    priority = {"CustomResourceDefinition": 0, "ServiceAccount": 1, "ClusterRole": 2,
                "ClusterRoleBinding": 3, "Role": 4, "RoleBinding": 5, "ConfigMap": 6,
                "Service": 7, "NetworkPolicy": 8, "StatefulSet": 9, "Deployment": 10}
    gitops.require(all(obj.get("kind") in priority for obj in resources))
    resources.sort(key=lambda obj: (priority[obj["kind"]], obj["metadata"]["name"]))
    values = gitops.read_json(root / gitops.BASE_PATH)
    expected_images = {values["global"]["image"]["repository"] + ":" + values["global"]["image"]["tag"],
                       values["redis"]["image"]["repository"] + ":" + values["redis"]["image"]["tag"]}
    gitops.require(all("@sha256:" in image for image in expected_images))
    seen_images = set()
    for obj in resources:
        if obj["kind"] == "Service":
            gitops.require(obj["spec"].get("type", "ClusterIP") == "ClusterIP")
        if obj["kind"] in ("StatefulSet", "Deployment"):
            pod = obj["spec"]["template"]["spec"]
            gitops.require(obj["spec"]["replicas"] == 1 and pod["nodeSelector"]["kubernetes.io/arch"] == "arm64")
            for container in pod.get("containers", []) + pod.get("initContainers", []):
                gitops.require(container["image"] in expected_images)
                seen_images.add(container["image"])
    gitops.require(seen_images == expected_images)
    cm = next(o for o in resources if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "argocd-cm")
    rbac = next(o for o in resources if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "argocd-rbac-cm")
    account_values = gitops.read_json(root / gitops.ACCOUNTS_PATH)["configs"]
    for section, rendered in [("cm", cm), ("rbac", rbac)]:
        for key, value in account_values[section].items():
            gitops.require(rendered["data"].get(key) == value)
    return resources


def prepare(root, helm, chart, revision):
    verify_checkout(root, revision)
    config = gitops.validate(gitops.read_json(root / gitops.SETTINGS_PATH))
    files = gitops.validate_repository(root)
    account_config = gitops.read_json(root / "gitops/platform/argocd/accounts.json")
    gitops.require(accounts.render_values(account_config) == gitops.read_json(root / gitops.ACCOUNTS_PATH))
    bundle = {"schema": 1, "config": config, "identity": gitops.identity(config), "expected_revision": revision,
              "resources": render_chart(root, helm, chart, config),
              "root": files[gitops.ROOT_PATH + "/root.yaml"], "self": files[gitops.ROOT_PATH + "/argocd.yaml"],
              "projects": [files[gitops.ROOT_PATH + "/" + name] for name in ["root-project.yaml", "platform-project.yaml"]],
              "initial_accounts": account_config["phase"] == "bootstrap" and not any(a["enabled"] for a in account_config["accounts"])}
    runtime.validate_bundle(bundle)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--helm", type=Path, required=True)
    parser.add_argument("--chart", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.repo_root.resolve(), args.helm.resolve(), args.chart.resolve(), args.expected_revision)
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration, yaml.YAMLError, subprocess.SubprocessError):
        print("Bundle rejected: verify clean committed declarations, pinned local tools/chart and explicit Git SHA.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
