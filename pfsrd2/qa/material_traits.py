"""Material verification, using AoN's own published pages as the oracle.

The 68 precious-material use pages (Adamantine Armor, Silver Shield, ...) are
AoN's computed answer for every material x item-kind combination. So the trait
propagation rule doesn't have to be asserted — it can be checked: the traits
this parser says a material grants must be exactly the traits AoN prints on
that material's use pages.

    bin/pf2_verify_materials      # exit 1 on contradictions

What this canNOT check: rarity composition with a base item. The use pages are
generic ("Adamantine Weapon", no base weapon), so the more-restrictive-wins
rule documented in pfsrd2/material.py has no published answer to compare
against.

Each check below is a pure function over already-loaded docs so it can be
unit-tested without a data checkout; main() only loads and reports.
"""

from pfsrd2.material import RARITIES
from pfsrd2.qa import load_equipment


def load_materials_and_uses():
    """Split equipment data into {(name, edition): doc} materials and use pages."""
    materials = {}
    uses = []
    for doc in load_equipment():
        stat_block = doc.get("stat_block", {})
        if stat_block.get("material"):
            materials[(doc["name"], doc["edition"])] = doc
        if stat_block.get("material_use"):
            uses.append(doc)
    return materials, uses


def check_propagation(materials, uses):
    """Derived grants_traits must equal what AoN prints on each use page."""
    problems = []
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
    return problems, checked


def check_grades(materials):
    """Grades exist for precious materials and only for them."""
    problems = []
    for (name, edition), doc in sorted(materials.items()):
        block = doc["stat_block"]["material"]
        grades = block.get("grades")
        if block["precious"] and not grades:
            problems.append(f"{name} ({edition}): precious but no grades")
        if not block["precious"] and grades:
            problems.append(f"{name} ({edition}): not precious but has grades {grades}")
    return problems


def check_variant_grades(uses):
    """Every use-page variant resolved a grade and an item form."""
    problems = []
    for doc in uses:
        for variant in doc["stat_block"].get("variants", []):
            use = variant.get("material_use") or {}
            if not use.get("grade"):
                problems.append(f"{doc['name']}: variant {variant.get('name')!r} has no grade")
            if not use.get("item_form"):
                problems.append(f"{doc['name']}: variant {variant.get('name')!r} has no item_form")
    return problems


def check_statistics(materials):
    """Every material page publishes a Hardness/HP/BT grid, so every one parses.

    Reported as a failure rather than a note: a missing grid means a table
    layout this parser doesn't handle, which is exactly the silent data loss
    that let legacy Dragonhide ship with no statistics.
    """
    problems = []
    for (name, edition), doc in sorted(materials.items()):
        if not doc["stat_block"]["material"].get("statistics"):
            problems.append(f"{name} ({edition}): no statistics extracted")
    return problems


def check_rarity(materials):
    """A material grants at most one rarity."""
    problems = []
    for (name, edition), doc in sorted(materials.items()):
        granted = doc["stat_block"]["material"].get("grants_traits", [])
        rarities = [t for t in granted if t.lower() in RARITIES]
        if len(rarities) > 1:
            problems.append(f"{name} ({edition}): grants multiple rarities {rarities}")
    return problems


def main():
    materials, uses = load_materials_and_uses()
    if not materials or not uses:
        print("no material data found — run bin/pf2_run_equipment.sh equipment first")
        return 1

    propagation_problems, checked = check_propagation(materials, uses)
    if not checked:
        # A verifier that compared nothing must not report success. Every
        # published use page names a base_material, so zero comparisons means
        # the data or the parse is broken, not that everything agrees.
        print("no propagation comparisons ran — every use page lacked a base_material")
        return 1
    problems = (
        propagation_problems
        + check_grades(materials)
        + check_variant_grades(uses)
        + check_statistics(materials)
        + check_rarity(materials)
    )

    print(f"materials: {len(materials)}   use pages: {len(uses)}")
    print(f"propagation checks against published pages: {checked}")
    if problems:
        print(f"\nPROBLEMS: {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\ntrait propagation matches every published use page")
    return 0
