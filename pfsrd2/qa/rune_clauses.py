"""Rune clause verification: every structured rune requirement must be
satisfiable by at least one real item, and every conflicts_with must name a
real rune.

A clause that matches nothing is worse than no clause — a consumer filtering
by it shows an empty list of legal items and no error. This is the equipment
counterpart of the template clause verification that caught the dead
$.traits target on creatures.

    bin/pf2_verify_runes        # exit 1 on dead clauses

Run after any change to rune usage parsing.
"""

import glob
import json
import os
import re

DATA = "/home/devon/MasterworkTools/pfsrd2/pfsrd2-data"

# Which data directories can host each kind of rune.
HOST_DIRS = {
    "weapon": ("weapons",),
    "armor": ("armor",),
    "shield": ("shields",),
}


def resolve(doc, path):
    """Resolve the '$.a.b[*].c' subset of JSONPath the rune clauses use.

    Returns the list of scalar values found. Missing keys yield nothing
    rather than raising — an item simply doesn't match the clause.
    """
    values = [doc]
    for token in path.lstrip("$").strip(".").split("."):
        key, wildcard = token, False
        if key.endswith("[*]"):
            key, wildcard = key[:-3], True
        found = []
        for value in values:
            if not isinstance(value, dict):
                continue
            item = value.get(key)
            if item is None:
                continue
            if wildcard:
                found.extend(item if isinstance(item, list) else [item])
            else:
                found.append(item)
        values = found
    return values


def load(kinds):
    docs = []
    for kind in kinds:
        for path in glob.glob(os.path.join(DATA, kind, "**", "*.json"), recursive=True):
            with open(path) as handle:
                docs.append(json.load(handle))
    return docs


def load_runes():
    runes = []
    for path in glob.glob(os.path.join(DATA, "equipment", "**", "*.json"), recursive=True):
        with open(path) as handle:
            doc = json.load(handle)
        if doc.get("stat_block", {}).get("item_category") == "Runes":
            runes.append(doc)
    return runes


def clause_matches(doc, clause):
    values = [str(v).lower() for v in resolve(doc, clause["path"])]
    return any(str(w).lower() in values for w in clause["values"])


def main():
    runes = load_runes()
    if not runes:
        print("no rune data found — run bin/pf2_run_equipment.sh equipment first")
        return 1

    hosts = {host: load(dirs) for host, dirs in HOST_DIRS.items()}
    rune_names = {re.sub(r"\s+rune$", "", r["name"].lower()) for r in runes}

    dead = []
    for rune_doc in runes:
        block = rune_doc["stat_block"].get("rune")
        if not block:
            dead.append((rune_doc["name"], "no rune block"))
            continue
        items = hosts.get(block["host"], [])
        for clause in block.get("requires", []):
            if not any(clause_matches(item, clause) for item in items):
                dead.append(
                    (rune_doc["name"], f"clause matches no {block['host']}: {clause}")
                )
        for conflict in block.get("conflicts_with", []):
            if conflict not in rune_names:
                dead.append((rune_doc["name"], f"conflicts_with unknown rune: {conflict!r}"))

    review = [r["name"] for r in runes if r["stat_block"].get("rune", {}).get("needs_review")]

    print(f"runes checked: {len(runes)}")
    print(f"needs_review (usage not fully parsed): {len(review)}")
    for name in review:
        print(f"  - {name}")
    if dead:
        print(f"\nDEAD CLAUSES: {len(dead)}")
        for name, reason in dead:
            print(f"  - {name}: {reason}")
        return 1
    print("\nall rune clauses resolve against real items")
    return 0
