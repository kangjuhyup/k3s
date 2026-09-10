#!/usr/bin/env python3
"""Validate pinned local Istio charts offline; never install or contact Kubernetes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import yaml

spec = importlib.util.spec_from_file_location("argocd_gitops", Path(__file__).with_name("argocd_gitops.py"))
gitops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gitops)


def render(root, helm, chart_dir, kube_version, ingress=None):
    require = gitops.require
    require(gitops.match(kube_version, r"1\.[0-9]+\.[0-9]+"))
    require(32 <= int(kube_version.split(".")[1]) <= 36)
    external = ingress is not None and gitops.ingress_enabled(ingress)
    ingress_files = {}
    if external:
        # Reuse the production renderer to derive exactly the generated values.
        additions, ingress_files = gitops.render_istio({
            "repo_url": "https://git.example.invalid/test/infra.git", "revision": "main", "kube_version": kube_version},
            {"enabled": True, "reviewed": True, "mode": "sidecar", "namespace": "istio-system", "gateway_service_type": "ClusterIP"})
        ingress_files.update({gitops.ROOT_PATH + "/" + name: obj for name, obj in additions.items()})
        gitops.add_ingress(ingress_files, ingress)
    base = root / "gitops/platform/istio"
    versions = gitops.read_json(base / "versions.json")
    require(versions["version"] == gitops.ISTIO_VERSION and versions["repository"] == gitops.ISTIO_REPO)

    def run(args):
        result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=60)
        require(result.returncode == 0)
        return result.stdout

    require(run([str(helm), "version", "--template", "{{.Version}}"]).strip() == versions["helm_version"])
    objects = []
    seen = set()
    for chart, release in [("base", "istio-base"), ("istiod", "istiod"), ("gateway", "istio-ingress")]:
        archive = chart_dir / (chart + "-" + versions["version"] + ".tgz")
        require(hashlib.sha256(archive.read_bytes()).hexdigest() == versions["charts"][chart])
        args = [str(helm), "template", release, str(archive), "--namespace", "istio-system",
                "--kube-version", kube_version, "--values", str(base / (chart + ".values.json"))]
        if external and chart == "gateway":
            args += ["--set-json", "service=" + json.dumps(ingress_files[gitops.INGRESS_VALUES_PATH]["service"])]
        rendered = run(args)
        for obj in yaml.safe_load_all(rendered):
            if not obj:
                continue
            identity = (obj["apiVersion"], obj["kind"], obj["metadata"].get("namespace", ""), obj["metadata"]["name"])
            require(identity not in seen)
            seen.add(identity)
            require("helm.sh/hook" not in obj["metadata"].get("annotations", {}))
            require(obj["kind"] not in ("Secret", "Job", "DaemonSet", "HorizontalPodAutoscaler", "PodDisruptionBudget"))
            if obj["kind"] == "Service":
                if external and chart == "gateway":
                    require(obj["spec"]["type"] == "LoadBalancer")
                    require(obj["spec"]["allocateLoadBalancerNodePorts"] is False)
                    require(obj["spec"]["externalTrafficPolicy"] == "Cluster")
                    require([p["port"] for p in obj["spec"]["ports"]] == [80, 443])
                    require(all("nodePort" not in p for p in obj["spec"]["ports"]))
                else:
                    require(obj["spec"].get("type", "ClusterIP") == "ClusterIP")
                require(not obj["spec"].get("externalIPs"))
            if obj["kind"] == "Deployment":
                pod = obj["spec"]["template"]["spec"]
                require(obj["spec"]["replicas"] == 1)
                require(pod["nodeSelector"] == {"kubernetes.io/os": "linux", "kubernetes.io/arch": "arm64"})
                require(not pod.get("hostNetwork", False) and not pod.get("initContainers"))
                require(len(pod["containers"]) == 1)
                wave = obj["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave")
                if chart == "istiod":
                    require(wave == "10" and pod["containers"][0]["image"] == versions["images"]["pilot"])
                else:
                    require(chart == "gateway" and wave == "20")
                    # Istiod's gateway injection template supplies the actual proxy image.
                    require(pod["containers"][0]["image"] == "auto")
                    require(obj["spec"]["template"]["metadata"]["annotations"]["inject.istio.io/templates"] == "gateway")
            if obj["kind"] == "ValidatingWebhookConfiguration":
                require(all(w["failurePolicy"] == "Fail" for w in obj["webhooks"]))
            objects.append(obj)
    require(sum(o["kind"] == "Deployment" for o in objects) == 2)
    require(any(o["kind"] == "CustomResourceDefinition" for o in objects))
    injector = next(o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "istio-sidecar-injector")
    injected_values = json.loads(injector["data"]["values"])
    for key in ["proxy", "proxy_init"]:
        require(injected_values["global"][key]["image"] == versions["images"]["proxyv2"])
    require("gateway:" in injector["data"]["config"])
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--helm", type=Path, required=True)
    parser.add_argument("--chart-dir", type=Path, required=True)
    parser.add_argument("--kube-version", required=True)
    parser.add_argument("--with-ingress", action="store_true", help="Validate reviewed ingress plus Git-owned K3s ServiceLB inputs")
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        ingress = None
        if args.with_ingress:
            gitops.render_repository(root)
            ingress = gitops.read_json(root / gitops.INGRESS_SETTINGS_PATH)
            gitops.require(gitops.ingress_enabled(ingress))
            gitops.require(gitops.read_json(root / gitops.SETTINGS_PATH)["kube_version"] == args.kube_version)
        objects = render(root, args.helm.resolve(), args.chart_dir.resolve(), args.kube_version, ingress)
        print(f"Istio offline render validated: {len(objects)} objects. No deployment occurred.")
        return 0
    except (ValueError, TypeError, KeyError, OSError, StopIteration, yaml.YAMLError, subprocess.SubprocessError):
        print("Istio validation blocked: verify pinned tools/charts, Kubernetes version and values.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
