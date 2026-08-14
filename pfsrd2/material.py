"""Structured material slot metadata for equipment items.

Materials carry their rules as prose plus a markdown table: the material page
holds a Hardness/HP/BT grid keyed by item form and purity grade, and the
"precious material" use pages (Adamantine Armor, Adamantine Shield, ...) hold
per-grade prices and, for shields, their own Hardness/HP/BT.

This module decorates both tiers:

  stat_block.material      — on a Materials item: precious flag, available
                             grades with their level caps, the traits an item
                             made of it gains, and the stat grid
  stat_block.material_use  — on a precious-material use page and each of its
                             variants: the host kind, the grade, the item form
                             (shields split into shield / buckler / tower
                             shield), and any stated stat override

An item takes at most ONE precious material, so this is a single slot with a
value, not a capacity like property runes.

Grade exists only for PRECIOUS materials — "using purer forms of common
materials is so relatively inexpensive that the Price is included in any magic
item" (GM Core 253). The `precious` trait is therefore the gate, never the
variant naming: Stone is a common material whose only variant is published as
"Stone Object (Low-Grade)", and reading a grade off that name would wrongly
cap its rune levels.

Composing a material with a base item is the CONSUMER's job, not this
parser's — nothing here builds a combined item, so no code applies the rules
below. They are stated here because `grants_traits` is only meaningful with
them:

  - non-rarity traits union onto the item
  - rarity does NOT union; an item has exactly one, so it is the more
    restrictive of the item's own and the material's, over
    common < uncommon < rare < unique
"""

import re

MATERIAL_CATEGORY = "Materials"
USE_SUBCATEGORY_PREFIX = "Precious Material "

# Grade purity gates how powerful an item made from the material can be, and
# what runes it can hold (GM Core 253). High grade is unbounded, which is
# expressed by omitting the caps rather than by a null.
_GRADE_CAPS = {
    "low": 8,
    "standard": 15,
    "high": None,
}

_GRADE_ORDER = ("low", "standard", "high")

# `precious` classifies the material itself — it appears on all 28 precious
# materials and on none of their 68 published use pages, so it is the one
# trait that does not travel to the item.
_NON_PROPAGATING_TRAITS = frozenset({"precious"})

RARITIES = ("common", "uncommon", "rare", "unique")

# Item forms a precious-material use page can describe. `material_use.item_form`
# is deliberately a different vocabulary from `material_statistics.form`
# (thin / item / structure), which is why the two carry different key names.
ITEM_FORMS = frozenset({"armor", "weapon", "shield", "buckler", "tower shield"})

# Table row labels vary by page: Dragonhide says "Standard Items" for what
# every other material calls "Items", and structures appear both singular and
# plural.
_FORMS = {
    "thin items": "thin",
    "items": "item",
    "standard items": "item",
    "structure": "structure",
    "structures": "structure",
}

_GRADE_ROW = re.compile(r"^(low|standard|high)[- ]grade$", re.I)
_GRADE_SUFFIX = re.compile(r"\s*\((low|standard|high)-grade\)\s*$", re.I)
_STAT_TEXT = re.compile(
    r"Hardness\s+(\d+),?\s*(?:it gains an additional\s+)?HP\s+(\d+),?\s*(?:and\s+)?BT\s+(\d+)",
    re.I,
)


def _cell_values(row):
    return [c.strip().replace("**", "").strip() for c in row.strip().strip("|").split("|")]


def _ints(cells):
    """The three stat numbers from a row, or None if they aren't all numeric."""
    values = [c for c in cells if c]
    if len(values) != 3:
        return None
    if not all(v.isdigit() for v in values):
        return None
    return [int(v) for v in values]


def parse_stat_table(text):
    """Parse a material's Hardness/HP/BT markdown table into structured rows.

    Handles the layouts AoN publishes: bold or plain form headers with grade
    rows beneath, form headers that also carry the column labels, and
    grade-less rows for common materials. Returns [] for a table that names
    no recognizable form — legacy Dragonhide's table is Dragon Type to
    Resistance, not stats, and must not be read as one.
    """
    rows = []
    form = None
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = _cell_values(line)
        if not cells:
            continue
        label = cells[0].lower().rstrip(":")
        stats = _ints(cells[1:])

        if label in _FORMS:
            form = _FORMS[label]
            # "Thin Items | 4 | 16 | 8" — a common material states its stats
            # on the form row itself, with no grades at all.
            if stats:
                rows.append(_stat_row(form, None, stats))
            continue

        grade_match = _GRADE_ROW.match(label)
        if grade_match and form and stats:
            rows.append(_stat_row(form, grade_match.group(1).lower(), stats))
    return rows


def _stat_row(form, grade, stats):
    row = {
        "type": "stat_block_section",
        "subtype": "material_statistics",
        "form": form,
        "hardness": stats[0],
        "hit_points": stats[1],
        "break_threshold": stats[2],
    }
    if grade:
        row["grade"] = grade
    return row


def _grades_from_variants(variants):
    """Available grades, read off the 'Object (X-Grade)' variant names."""
    found = set()
    for variant in variants:
        match = _GRADE_SUFFIX.search(variant.get("name", ""))
        if match:
            found.add(match.group(1).lower())
    return [g for g in _GRADE_ORDER if g in found]


def _grade_entry(grade):
    entry = {"type": "stat_block_section", "subtype": "material_grade", "grade": grade}
    cap = _GRADE_CAPS[grade]
    if cap is not None:
        # Purity gates both the level of magic item it can become and the
        # level of rune it can hold; the rules give one number for both.
        entry["max_item_level"] = cap
        entry["max_rune_level"] = cap
    return entry


def granted_traits(traits):
    """The traits an item gains from being made of this material."""
    return [t for t in traits if t.lower() not in _NON_PROPAGATING_TRAITS]


def _stat_tables(sections):
    """Every markdown table on the page, in document order."""
    tables = []
    for section in sections or []:
        text = section.get("text") or ""
        if "| ---" in text:
            tables.append(text)
        tables.extend(_stat_tables(section.get("sections")))
    return tables


def _find_stat_rows(sections):
    """Stat rows from the first table on the page that parses as one.

    A material page can carry more than one table: legacy Dragonhide leads
    with Dragon Type to Resistance and puts the real Hardness/HP/BT grid in
    the section below it. Taking the first table outright dropped that page's
    statistics silently, so every table is tried and the first that yields
    rows wins.
    """
    for table in _stat_tables(sections):
        rows = parse_stat_table(table)
        if rows:
            return rows
    return []


def _trait_names(stat_block):
    return [t["name"] for t in stat_block.get("traits", []) if t.get("name")]


def _material_pass(struct, stat_block):
    traits = _trait_names(stat_block)
    precious = any(t.lower() == "precious" for t in traits)
    variants = stat_block.get("variants", [])

    material = {
        "type": "stat_block_section",
        "subtype": "material",
        "precious": precious,
    }
    granted = granted_traits(traits)
    if granted:
        material["grants_traits"] = granted

    if precious:
        grades = _grades_from_variants(variants)
        assert grades, (
            f"Precious material {struct.get('name')!r} has no "
            "'Object (X-Grade)' variant to read its grades from"
        )
        material["grades"] = [_grade_entry(g) for g in grades]

    rows = _find_stat_rows(stat_block.get("sections"))
    assert rows, (
        f"Material {struct.get('name')!r} has no parsable Hardness/HP/BT table. "
        "Every published material page carries one — a new table layout needs "
        "handling in parse_stat_table rather than shipping a material with no "
        "statistics."
    )
    material["statistics"] = rows

    stat_block["material"] = material


def _use_item_form(item_name, variant_name, host):
    """The item form a use-page variant describes.

    Shields publish separate buckler / shield / tower shield rows because the
    stats differ; armor and weapons have a single generic form. Falls back to
    the host kind when the variant name adds nothing beyond the material name
    (Elven Chain is a specific armor, so its leftover is a name, not a form).

    The result is checked against a closed set: an unrecognized leftover means
    AoN published a form this parser doesn't model, and silently shipping it
    as a free string would let a consumer's form lookup miss.
    """
    head = _GRADE_SUFFIX.sub("", variant_name or "").strip()
    # Strip the material name off the front: "Adamantine Buckler" -> "Buckler".
    material_name = re.sub(r"\s+(Armor|Shield|Weapon)$", "", item_name or "").strip()
    if material_name and head.lower().startswith(material_name.lower()):
        head = head[len(material_name) :].strip()
    form = head.lower() or host
    assert form in ITEM_FORMS, (
        f"Unrecognized precious-material item form {form!r} from variant "
        f"{variant_name!r} on {item_name!r} — add it to ITEM_FORMS and the "
        "material_use.item_form schema enum."
    )
    return form


def _use_pass(struct, stat_block, host):
    stat_block["material_use"] = {
        "type": "stat_block_section",
        "subtype": "material_use",
        "host": host,
    }
    for variant in stat_block.get("variants", []):
        name = variant.get("name", "")
        # Grade first: a malformed title fails both checks, and "no grade
        # suffix" is the diagnosis that points at the actual defect.
        grade_match = _GRADE_SUFFIX.search(name)
        assert grade_match, (
            f"Precious material variant {name!r} on {struct.get('name')!r} has no "
            "grade suffix — the page or the parse is malformed"
        )
        use = {
            "type": "stat_block_section",
            "subtype": "material_use",
            "host": host,
            "item_form": _use_item_form(struct.get("name"), name, host),
            "grade": grade_match.group(1).lower(),
        }

        stats = _STAT_TEXT.search(variant.get("text") or "")
        if stats:
            # A stated stat block overrides the material page's grid — this is
            # how a buckler differs from a shield of the same material.
            use["hardness"] = int(stats.group(1))
            use["hit_points"] = int(stats.group(2))
            use["break_threshold"] = int(stats.group(3))
        variant["material_use"] = use


_USE_HOSTS = {"Armor": "armor", "Shields": "shield", "Weapons": "weapon"}


def material_pass(struct):
    """Decorate a material or a precious-material use page. No-op otherwise."""
    stat_block = struct.get("stat_block")
    if not stat_block:
        return
    if stat_block.get("item_category") == MATERIAL_CATEGORY:
        _material_pass(struct, stat_block)
        return
    subcategory = stat_block.get("item_subcategory") or ""
    if subcategory.startswith(USE_SUBCATEGORY_PREFIX):
        kind = subcategory[len(USE_SUBCATEGORY_PREFIX) :]
        host = _USE_HOSTS.get(kind)
        assert host, f"Unrecognized precious material use subcategory: {subcategory!r}"
        _use_pass(struct, stat_block, host)
