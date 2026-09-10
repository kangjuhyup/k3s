#!/usr/bin/env python3
"""Render an explicit, non-secret K3s settings file to a JSON/YAML inventory."""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import os


MODULE = Path(__file__).resolve().parents[1] / "ansible/filter_plugins/k3s_config.py"
spec = importlib.util.spec_from_file_location("k3s_config", MODULE)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Explicitly write; default is comparison only")
    parser.add_argument("--format", choices=['inventory', 'json'], default='inventory',
                        help="inventory validates K3s; json resolves Terraform input references")
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve() or args.output.is_symlink():
            raise ValueError("Unsafe output")
        config = json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        rendered = config_module.inventory(config) if args.format == 'inventory' else config_module.resolve_environment(config)
        content = json.dumps(rendered, indent=2, sort_keys=True) + "\n"
        if args.write:
            # Parent must already exist; no implicit broad directory creation.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                             delete=False) as temporary:
                temporary_name = temporary.name
                try:
                    temporary.write(content)
                    temporary.flush()
                    os.replace(temporary_name, args.output)
                finally:
                    if os.path.exists(temporary_name):
                        os.unlink(temporary_name)
            print("Validated inventory written; no host connection was made.")
        elif not args.output.exists() or args.output.read_text(encoding="utf-8") != content:
            print("Inventory missing or differs; review inputs before using --write.")
            return 1
        else:
            print("Inventory matches the validated configuration.")
    except (ValueError, TypeError, OSError, OverflowError):
        print("Inventory rejected; check the input schema and file paths. Values are not displayed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
