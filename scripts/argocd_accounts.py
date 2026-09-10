#!/usr/bin/env python3
"""Validate non-secret local accounts and render argo-cd Helm values offline.

Default mode only checks a committed generated file. --write explicitly updates
that file. This tool never contacts Argo CD, Kubernetes, OCI or Doppler.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import yaml


class ConfigError(ValueError):
    """Safe diagnostics must never include untrusted input values."""


def require(condition, message):
    if not condition:
        raise ConfigError(message)


def fields(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected),
            label + " has missing or unsupported fields")


def identifier(value, maximum):
    return (isinstance(value, str) and len(value) <= maximum and
            re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) is not None)


def render_values(config):
    """Return a deterministic, non-secret values object or raise ConfigError."""
    fields(config, {"phase", "accounts", "cutover"}, "configuration")
    require(config["phase"] in ("bootstrap", "managed"), "invalid phase")
    require(isinstance(config["accounts"], list), "accounts must be a list")
    cutover = config["cutover"]
    fields(cutover, {"verified_admin", "recovery_verified"}, "cutover")
    require(type(cutover["recovery_verified"]) is bool, "recovery_verified must be a boolean")
    require(cutover["verified_admin"] is None or identifier(cutover["verified_admin"], 32),
            "verified_admin must be null or a valid account name")

    names = set()
    active_admins = set()
    for account in config["accounts"]:
        fields(account, {"name", "role", "enabled", "projects"}, "account")
        name = account["name"]
        require(identifier(name, 32) and name != "admin", "invalid or reserved account name")
        require(name not in names, "duplicate account name")
        names.add(name)
        require(type(account["enabled"]) is bool, "account enabled must be a boolean")
        require(account["role"] in ("developer", "platform-admin"), "unsupported account role")
        projects = account["projects"]
        require(isinstance(projects, list) and all(identifier(project, 63) for project in projects),
                "projects must contain explicit valid project names")
        require(len(set(projects)) == len(projects), "duplicate project name")
        if account["role"] == "platform-admin":
            require(not projects, "platform-admin cannot imply project-scoped administration")
            if account["enabled"]:
                active_admins.add(name)
        else:
            require(bool(projects), "developer requires at least one explicit project")

    if config["phase"] == "managed":
        require(cutover["verified_admin"] in active_admins and cutover["recovery_verified"],
                "managed phase requires a verified active personal admin and recovery path")

    cm = {
        "admin.enabled": "true" if config["phase"] == "bootstrap" else "false",
        "users.anonymous.enabled": "false",
    }
    policy = []
    for account in sorted(config["accounts"], key=lambda item: item["name"]):
        name = account["name"]
        cm["accounts." + name] = "login"
        cm["accounts." + name + ".enabled"] = "true" if account["enabled"] else "false"
        if not account["enabled"]:
            continue
        if account["role"] == "platform-admin":
            policy.append("g, " + name + ", role:admin")
        else:
            # Direct local-user grants avoid SSO group/role-name ambiguity.
            # No sync, override, action, exec, logs or write grants are emitted.
            for project in sorted(account["projects"]):
                policy.append("p, " + name + ", applications, get, " + project + "/*, allow")
                policy.append("p, " + name + ", projects, get, " + project + ", allow")
    return {"configs": {
        "cm": cm,
        "rbac": {
            "policy.default": "role:authenticated",
            "policy.csv": "\n".join(policy) + ("\n" if policy else ""),
            "policy.matchMode": "glob",
            "scopes": "[]",
        },
    }}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_value):
    raise ConfigError("non-standard JSON constant")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="non-secret accounts JSON")
    parser.add_argument("--output", required=True, type=Path, help="generated Helm values YAML")
    parser.add_argument("--write", action="store_true", help="write generated values; default only checks")
    args = parser.parse_args(argv)
    temporary = None
    try:
        require(not args.output.is_symlink(), "output must not be a symbolic link")
        require(args.input.resolve() != args.output.resolve(), "input and output must differ")
        try:
            config = json.loads(args.input.read_text(encoding="utf-8"),
                                object_pairs_hook=unique_object, parse_constant=reject_constant)
        except (json.JSONDecodeError, UnicodeError):
            raise ConfigError("input must be valid UTF-8 JSON") from None
        rendered = yaml.safe_dump(render_values(config), sort_keys=False, allow_unicode=True)
        if args.write:
            # Atomic replacement avoids a partially written desired-state file.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                             prefix=".argocd-accounts-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(rendered)
            os.replace(temporary, args.output)
            temporary = None
            print("Account values generated; no external changes performed.")
        else:
            require(args.output.is_file(), "generated values are missing; use --write to create them")
            require(yaml.safe_load(args.output.read_text(encoding="utf-8")) == render_values(config),
                    "generated values differ; review input and regenerate with --write")
            print("Account values match the validated configuration.")
        return 0
    except ConfigError as error:
        print("Account configuration rejected: " + str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, yaml.YAMLError):
        print("Unable to read/write account files; check paths and permissions.", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
