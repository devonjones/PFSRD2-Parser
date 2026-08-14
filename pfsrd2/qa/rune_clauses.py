"""Rune clause verification: every structured rune requirement must be
satisfiable by at least one real item, and every conflicts_with must name a
real rune.

A clause that matches nothing is worse than no clause — a consumer filtering
by it shows an empty list of legal items and no error. This is the equipment
counterpart of the template clause verification that caught the dead
$.traits target on creatures.

    bin/pf2_verify_runes        # exit 1 on dead clauses

Run after any change to rune usage parsing.

resolve() and clause_matches() are the oracle this verifier trusts, so they
are pure functions over already-loaded docs and unit-tested directly — an
over-matching resolver would silently pass dead clauses.
"""

import re

from pfsrd2.qa import load_equipment, load_json_dir

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


def clause_matches(doc, clause):
    values = [str(v).lower() for v in resolve(doc, clause["path"])]
    return any(str(w).lower() in values for w in clause["values"])


def load_runes():
    return load_equipment(lambda doc: doc.get("stat_block", {}).get("item_category") == "Runes")


def check_clauses(runes, hosts):
    """Every requires clause matches a real item; every conflict names a rune."""
    problems = []
    rune_names = {re.sub(r"\s+rune$", "", r["name"].lower()) for r in runes}
    for rune_doc in runes:
        block = rune_doc["stat_block"].get("rune")
        if not block:
            problems.append((rune_doc["name"], "no rune block"))
            continue
        items = hosts.get(block["host"], [])
        for clause in block.get("requires", []):
            if not any(clause_matches(item, clause) for item in items):
                problems.append((rune_doc["name"], f"clause matches no {block['host']}: {clause}"))
        for conflict in block.get("conflicts_with", []):
            if conflict not in rune_names:
                problems.append((rune_doc["name"], f"conflicts_with unknown rune: {conflict!r}"))
    return problems


def check_review_exclusivity(runes):
    """needs_review and requires are mutually exclusive.

    A rune whose usage only partly parsed must ship no clauses at all — a
    partial list reads as authoritative and would call ineligible items legal.
    """
    problems = []
    for rune_doc in runes:
        block = rune_doc["stat_block"].get("rune") or {}
        if block.get("needs_review") and block.get("requires"):
            problems.append((rune_doc["name"], "has both needs_review and requires clauses"))
    return problems


def main():
    runes = load_runes()
    if not runes:
        print("no rune data found — run bin/pf2_run_equipment.sh equipment first")
        return 1

    hosts = {host: load_json_dir(*dirs) for host, dirs in HOST_DIRS.items()}
    empty = sorted(host for host, docs in hosts.items() if not docs)
    if empty:
        # Same trap as the material verifier: an empty host list makes every
        # clause for that host vacuously unverifiable. Shield-host runes all
        # have empty requires today, so a missing shields/ directory would
        # otherwise pass silently.
        print(f"no items loaded for host(s): {', '.join(empty)} — check the data directories")
        return 1
    problems = check_clauses(runes, hosts) + check_review_exclusivity(runes)
    review = [r["name"] for r in runes if r["stat_block"].get("rune", {}).get("needs_review")]

    print(f"runes checked: {len(runes)}")
    print(f"needs_review (usage not fully parsed): {len(review)}")
    for name in review:
        print(f"  - {name}")
    if problems:
        print(f"\nDEAD CLAUSES: {len(problems)}")
        for name, reason in problems:
            print(f"  - {name}: {reason}")
        return 1
    print("\nall rune clauses resolve against real items")
    return 0
