#!/usr/bin/env python3
"""Reproduce hardened Git manifests from the exact official Doppler chart, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import yaml

VERSION = "1.7.1"
SHA256 = "5230eb0232d5a9d31d5a4e7303c8a002f3232717afe2a03a8cabfd3030b3e407"
IMAGE = "docker.io/dopplerhq/kubernetes-operator:1.7.1@sha256:a29846259fb3e9a1b183adcde687e5216f768ea3693606df8266a945030d02ca"
PATH = "gitops/platform/doppler/install"


def require(condition):
    if not condition:
        raise ValueError("Doppler artifact or generated manifest mismatch.")


def render(chart):
    require(hashlib.sha256(chart.read_bytes()).hexdigest() == SHA256)
    objects = []
    with tarfile.open(chart, "r:gz") as archive:
        for filename in ["crds/all.yaml", "templates/all.yaml"]:
            member = archive.extractfile("doppler-kubernetes-operator/" + filename)
            objects += [obj for obj in yaml.safe_load_all(member.read()) if obj]
    require(len(objects) == 9)
    files = {}
    for obj in objects:
        kind, metadata = obj["kind"], obj["metadata"]
        annotations = metadata.setdefault("annotations", {})
        annotations["infra.oci-a1.example/upstream"] = "DopplerHQ/kubernetes-operator v1.7.1; Apache-2.0"
        annotations["infra.oci-a1.example/modified"] = "JSON conversion, sync waves, ARM64/image/security and restricted RBAC; see ../README.md"
        annotations["argocd.argoproj.io/sync-wave"] = "10" if kind == "Deployment" else "0"
        if kind in {"Namespace", "CustomResourceDefinition"}:
            annotations["argocd.argoproj.io/sync-options"] = "Prune=false,Delete=false"
        if kind == "Namespace":
            annotations["argocd.argoproj.io/sync-wave"] = "-20"
            metadata.setdefault("labels", {})["istio-injection"] = "disabled"
        if kind == "ClusterRole":
            rules = []
            for rule in obj["rules"]:
                if "serviceaccounts/token" in rule["resources"]:
                    continue
                if any(r in rule["resources"] for r in ["secrets", "deployments", "dopplersecrets"]):
                    rule["verbs"] = ["get", "list", "watch"]
                rules.append(rule)
            obj["rules"] = rules
        if kind == "Deployment":
            pod = obj["spec"]["template"]["spec"]
            pod["nodeSelector"] = {"kubernetes.io/arch": "arm64", "kubernetes.io/os": "linux"}
            pod["securityContext"]["seccompProfile"] = {"type": "RuntimeDefault"}
            require(len(pod["containers"]) == 1)
            container = pod["containers"][0]
            container["image"] = IMAGE
            container["securityContext"]["capabilities"] = {"drop": ["ALL"]}
        files[PATH + "/" + kind.lower() + "-" + metadata["name"] + ".yaml"] = obj
    files[PATH + "/kustomization.yaml"] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
        "resources": sorted(Path(path).name for path in files)}
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--chart", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        files, root = render(args.chart), args.repo_root.resolve()
        for path in files:
            target = root / path
            require(target.resolve().is_relative_to(root) and not target.is_symlink())
            require(not any(p.is_symlink() for p in target.parents if p.is_relative_to(root)))
        for path, obj in files.items():
            target = root / path
            data = yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(data, encoding="utf-8")
            else:
                require(target.is_file() and yaml.safe_load(target.read_text()) == obj)
        print("Doppler pinned manifests generated." if args.write else "Doppler pinned manifests match.")
        return 0
    except (ValueError, OSError, tarfile.TarError, yaml.YAMLError):
        print("Doppler artifact validation failed; no cluster was contacted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
