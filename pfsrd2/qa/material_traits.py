"""Material verification, using AoN's own published pages as the oracle.

The 68 precious-material use pages (Adamantine Armor, Silver Shield, ...) are
AoN's computed answer for every material x item-kind combination. So the trait
propagation rule doesn't have to be asserted — it can be checked: the traits
this parser says a material grants must be exactly the traits AoN prints on
that material's use pages.

    bin/pf2_verify_materials      # exit 1 on contradictions

What this canNOT check: rarity composition with a base item. The use pages are
generic ("Adamantine Weapon", no base weapon), so max(base, material) has no
published answer to compare against and is covered by unit tests instead.
"""

import glob
import json
import os

from pfsrd2.material import RARITIES

DATA = "/home/devon/MasterworkTools/pfsrd2/pfsrd2-data"


def load_equipment():
    for path in glob.glob(os.path.join(DATA, "equipment", "**", "*.json"), recursive=True):
        with open(path) as handle:
            yield json.load(handle)


def main():
    materials = {}
    uses = []
    for doc in load_equipment():
        stat_block = doc.get("stat_block", {})
        if stat_block.get("material"):
            materials[(doc["name"], doc["edition"])] = doc
        if stat_block.get("material_use"):
            uses.append(doc)

    if not materials:
        print("no material data found — run bin/pf2_run_equipment.sh equipment first")
        return 1

    problems = []

    # 1. Propagation, checked against the published use pages.
    checked = 0
    for doc in uses:
        stat_block = doc["stat_block"]
        base = (stat_block.get("base_material") or {}).get("name")
        if not base:
            continue
        material = materials.get((base, doc["edition"]))
        if not material:
            problems.append(f"{doc['name']}: base_material {base!r} has no material page")
            continue
        expected = set(material["stat_block"]["material"].get("grants_traits", []))
        actual = {t["name"] for t in stat_block.get("traits", [])}
        checked += 1
        if expected != actual:
            problems.append(
                f"{doc['name']}: traits {sorted(actual)} != {base} grants {sorted(expected)}"
            )

    # 2. Grades exist for precious materials and only for them.
    for (name, edition), doc in sorted(materials.items()):
        block = doc["stat_block"]["material"]
        grades = block.get("grades")
        if block["precious"] and not grades:
            problems.append(f"{name} ({edition}): precious but no grades")
        if not block["precious"] and grades:
            problems.append(f"{name} ({edition}): not precious but has grades {grades}")

    # 3. Every use-page variant resolved a grade.
    for doc in uses:
        for variant in doc["stat_block"].get("variants", []):
            if not (variant.get("material_use") or {}).get("grade"):
                problems.append(f"{doc['name']}: variant {variant.get('name')!r} has no grade")

    # 4. Rarity sanity — a material grants at most one rarity.
    for (name, edition), doc in sorted(materials.items()):
        granted = doc["stat_block"]["material"].get("grants_traits", [])
        rarities = [t for t in granted if t.lower() in RARITIES]
        if len(rarities) > 1:
            problems.append(f"{name} ({edition}): grants multiple rarities {rarities}")

    no_stats = [
        f"{name} ({edition})"
        for (name, edition), doc in sorted(materials.items())
        if not doc["stat_block"]["material"].get("statistics")
    ]

    print(f"materials: {len(materials)}   use pages: {len(uses)}")
    print(f"propagation checks against published pages: {checked}")
    if no_stats:
        print(f"materials with no stat table extracted: {len(no_stats)}")
        for entry in no_stats:
            print(f"  - {entry}")
    if problems:
        print(f"\nPROBLEMS: {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\ntrait propagation matches every published use page")
    return 0
