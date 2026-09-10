#!/usr/bin/env python3
"""Read-only remote Git SHA check; executed only by an explicitly run bootstrap."""
import argparse
import base64
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

spec = importlib.util.spec_from_file_location("argocd_gitops", Path(__file__).with_name("argocd_gitops.py"))
gitops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gitops)


def verify(config, revision, source_env, execute=subprocess.run):
    gitops.validate(config)
    gitops.require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None)
    environment = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_TERMINAL_PROMPT": "0"}
    if config["auth"]["mode"] == "https-token":
        username = source_env.get(config["auth"]["username_env"], "")
        password = source_env.get(config["auth"]["password_env"], "")
        gitops.require(username and password and ":" not in username)
        credentials = base64.b64encode((username + ":" + password).encode()).decode()
        environment.update({"GIT_CONFIG_COUNT": "1",
                            "GIT_CONFIG_KEY_0": "http." + config["repo_url"] + ".extraHeader",
                            "GIT_CONFIG_VALUE_0": "Authorization: Basic " + credentials})
    reference = "refs/heads/" + config["revision"]
    result = execute(["git", "-c", "credential.helper=", "-c", "core.askPass=", "-c", "http.followRedirects=false",
                      "ls-remote", "--exit-code", config["repo_url"], reference],
                     text=True, capture_output=True, check=False, timeout=60, env=environment)
    gitops.require(result.returncode == 0)
    gitops.require(result.stdout.strip() == revision + "\t" + reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args()
    try:
        verify(gitops.read_json(args.repo_root / gitops.SETTINGS_PATH), args.expected_revision, os.environ)
        print("Remote Git branch matches the reviewed commit; no repository writes performed.")
        return 0
    except (ValueError, TypeError, OSError, subprocess.SubprocessError):
        print("Remote Git verification failed; check scoped authentication and branch SHA. Credentials are not displayed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
