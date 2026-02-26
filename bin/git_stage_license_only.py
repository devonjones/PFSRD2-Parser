#!/usr/bin/env python
"""Stage only license-related changes from modified JSON files.

Usage: python git_stage_license_only.py [path]
  path: directory to check (default: current directory)

For each modified JSON file, builds an intermediate version: old data values
re-serialized with the new file's key ordering, plus the new license block.
This stages key-reorder noise and license changes, leaving only real data
changes unstaged.
"""

import json
import subprocess
import sys
import tempfile
import os


def get_modified_json_files(path):
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--", path],
        capture_output=True,
        text=True,
    )
    return [f for f in result.stdout.split("\0") if f.endswith(".json")]


def get_old_json(filepath):
    result = subprocess.run(
        ["git", "show", f"HEAD:{filepath}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def reorder_keys(old, new):
    """Recursively reorder old's keys to match new's ordering.

    Returns a new OrderedDict-like structure with old's values but new's
    key order. Keys only in old are appended at end; keys only in new
    are skipped (they represent real additions).
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return old

    result = {}
    # First, keys from new in new's order (using old's values)
    for k in new:
        if k in old:
            result[k] = reorder_keys(old[k], new[k])
    # Then, keys only in old (appended at end)
    for k in old:
        if k not in new:
            result[k] = old[k]
    return result


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    files = get_modified_json_files(path)
    if not files or files == [""]:
        print("No modified JSON files found.")
        return

    staged = 0
    skipped = 0

    for filepath in files:
        old = get_old_json(filepath)
        if old is None:
            print(f"  NEW: {filepath}")
            skipped += 1
            continue
        try:
            with open(filepath) as f:
                new = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"  ERR: {filepath}")
            skipped += 1
            continue

        # Detect trailing newline style of each version
        with open(filepath, "rb") as f:
            new_raw = f.read()
        new_has_newline = new_raw.endswith(b"\n")

        old_raw_result = subprocess.run(
            ["git", "show", f"HEAD:{filepath}"],
            capture_output=True,
        )
        old_has_newline = old_raw_result.stdout.endswith(b"\n")

        # Build intermediate: old data with new key ordering + new license
        intermediate = reorder_keys(old, new)
        intermediate["license"] = new.get("license", intermediate.get("license"))

        # Use new file's trailing newline style for the intermediate
        new_trailing = "\n" if new_has_newline else ""
        old_trailing = "\n" if old_has_newline else ""

        # Check if intermediate is same as old serialization
        old_text = json.dumps(old, indent=4) + old_trailing
        int_text = json.dumps(intermediate, indent=4) + new_trailing
        if old_text == int_text:
            skipped += 1
            continue

        # Check if intermediate is same as new (nothing to leave unstaged)
        new_text = json.dumps(new, indent=4) + new_trailing
        if int_text == new_text:
            # Whole file is just reorder + license; stage it directly
            subprocess.run(["git", "add", filepath], check=True)
            print(f"  staged whole file (reorder+license only): {filepath}")
            staged += 1
            continue

        # Write intermediate to temp, hash into git, update index
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(int_text)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["git", "hash-object", "-w", tmp_path],
                capture_output=True,
                text=True,
                check=True,
            )
            blob_hash = result.stdout.strip()

            ls_result = subprocess.run(
                ["git", "ls-files", "-s", filepath],
                capture_output=True,
                text=True,
            )
            mode = ls_result.stdout.split()[0] if ls_result.stdout else "100644"

            subprocess.run(
                ["git", "update-index", "--cacheinfo", f"{mode},{blob_hash},{filepath}"],
                check=True,
            )
            print(f"  staged reorder+license, kept real changes: {filepath}")
            staged += 1
        finally:
            os.unlink(tmp_path)

    print(f"\nStaged {staged} files, {skipped} unchanged.")


if __name__ == "__main__":
    main()
