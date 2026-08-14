"""Structured rune slot metadata for equipment items.

Runes carry their slot rules only as prose: `statistics.usage.text` says what
an item must be for the rune to go on it, and `variants[].text` says what each
grade does. This module decorates rune items with the structured equivalents:

  stat_block.rune     — form/slot/host and the parsed usage requirements
  stat_block.effects  — what the rune does, as a closed vocabulary of subjects

Deliberately NOT stored anywhere: property rune capacity (a function of the
potency rune's grade), whether a specific magic item can take property runes
(item_subcategory already says so), item level and the invested trait (derived
by the consumer). Storing derived state on 1,800 base items only lets it drift.

Prose stays authoritative — `usage_text` keeps the original string, and a rune
whose usage this module can't fully parse gets needs_review rather than a
partial requirement list that would silently exclude legal items.
"""

import copy
import re

RUNE_CATEGORY = "Runes"

# item_subcategory -> (host, form). Host is what the rune goes ON; form decides
# whether it occupies a named fundamental slot or consumes property capacity.
_SUBCATEGORY_SPEC = {
    "Fundamental Weapon Runes": ("weapon", "fundamental"),
    "Fundamental Armor Runes": ("armor", "fundamental"),
    "Shield Runes": ("shield", "fundamental"),
    "Weapon Property Runes": ("weapon", "property"),
    "Armor Property Runes": ("armor", "property"),
    "Accessory Runes": ("accessory", "property"),
    "Clan Dagger Filigrees": ("weapon", "property"),
}

# Fundamental runes occupy one named slot each and upgrade in place; a weapon
# can hold both a weapon_potency and a striking rune, but never two of either.
# Matched against the lowercased rune name, longest-first.
_FUNDAMENTAL_SLOTS = (
    ("weapon potency", "weapon_potency"),
    ("striking", "striking"),
    ("armor potency", "armor_potency"),
    # AoN spells the mythic one "Mythic Resilent" — prefix match covers both.
    ("resil", "resilient"),
    ("reinforcing", "reinforcing"),
)

# Accessory runes go on umbrellas, baskets and wind-powered vehicles; there is
# no structured item field to match those against and never will be, so their
# eligibility stays prose by design rather than being flagged for review.
_PROSE_ONLY_HOSTS = frozenset({"accessory"})

# Clan dagger filigrees carry no usage line at all — the subcategory is the rule.
_SUBCATEGORY_REQUIRES = {
    "Clan Dagger Filigrees": [
        {"path": "$.name", "op": "in", "values": ["Clan Dagger"]},
    ],
}

_LEAD_IN = re.compile(r"^\s*etched\s+(?:onto|on|into|in)\s+|^\s*applied\s+to\s+", re.I)

# "without a *disrupting* rune", "that isn't unholy"
_CONFLICT_RUNE = re.compile(r"\bwithout\s+an?\s+\*?([\w-]+)\*?\s+rune\b", re.I)
_CONFLICT_TRAIT = re.compile(r"\bthat\s+isn'?t\s+\*?([\w-]+)\*?\b", re.I)

_ARMOR_CATEGORIES = ("light", "medium", "heavy")
_DAMAGE_TYPES = ("bludgeoning", "piercing", "slashing")
# Armor material (metal / nonmetallic) is not modelled on armor items, so a
# usage naming it cannot be turned into a checkable clause.
_MATERIALS = ("nonmetallic", "metal")

# Words that carry no requirement once the real clauses are consumed.
_FILLER = frozenset(
    {
        "a",
        "an",
        "the",
        "or",
        "and",
        "of",
        "onto",
        "on",
        "to",
        "into",
        "in",
        "that",
        "with",
        "weapon",
        "armor",
        "shield",
        "dagger",
        "clan",
        "melee",
        "thrown",
        "monk",
        "trait",
        "rune",
        "without",
        "isn't",
        "is",
        "not",
        "each",
        "item",
        "etched",
        "applied",
    }
)


def _slot_for(name, form):
    if form != "fundamental":
        return "property"
    lowered = name.lower()
    for needle, slot in _FUNDAMENTAL_SLOTS:
        if needle in lowered:
            return slot
    raise AssertionError(f"Unrecognized fundamental rune, no slot for: {name!r}")


def _clause(path, values):
    return {"path": path, "op": "in", "values": values}


def parse_usage(text):
    """Parse a rune's Usage line into requirement clauses on the host item.

    Returns (requires, conflicts_with, fully_parsed). `fully_parsed` is False
    when the string names something with no structured counterpart on items.
    Clauses parsed before that point are still returned; `rune_pass` is what
    discards them, so a partially-understood usage never ships a requirement
    list that looks authoritative.
    """
    requires = []
    conflicts = []
    if not text:
        return requires, conflicts, False

    working = text.strip()
    working = _LEAD_IN.sub("", working, count=1)

    for match in _CONFLICT_RUNE.finditer(working):
        conflicts.append(match.group(1).lower())
    working = _CONFLICT_RUNE.sub(" ", working)
    for match in _CONFLICT_TRAIT.finditer(working):
        captured = match.group(1).lower()
        # "that isn't holy" names a trait; "that isn't a ..." would capture the
        # article, which is never a real conflict.
        if captured not in _FILLER:
            conflicts.append(captured)
    working = _CONFLICT_TRAIT.sub(" ", working)

    lowered = working.lower()

    if "armor" in lowered:
        categories = [c.title() for c in _ARMOR_CATEGORIES if re.search(rf"\b{c}\b", lowered)]
        if categories:
            requires.append(_clause("$.stat_block.statistics.category", categories))
    else:
        damage = [d for d in _DAMAGE_TYPES if re.search(rf"\b{d}\b", lowered)]
        if damage:
            requires.append(
                _clause(
                    "$.stat_block.offense.weapon_modes[*].damage[*].damage_type",
                    damage,
                )
            )
        if re.search(r"\bmelee\b", lowered):
            requires.append(_clause("$.stat_block.offense.weapon_modes[*].weapon_type", ["Melee"]))
        traits = []
        if re.search(r"\bthrown\b", lowered):
            traits.append("Thrown")
        if re.search(r"\bmonk\b", lowered):
            traits.append("Monk")
        if traits:
            requires.append(_clause("$.stat_block.traits[*].name", traits))
        if re.search(r"\bclan dagger\b", lowered):
            requires.append(_clause("$.name", ["Clan Dagger"]))

    for material in _MATERIALS:
        if re.search(rf"\b{material}\b", lowered):
            # Armor items carry no material field — a clause here would match
            # zero armors and hide every legal one from a filtering consumer.
            return [], conflicts, False

    residue = [w for w in re.findall(r"[\w'-]+", lowered) if w not in _FILLER]
    residue = [
        w
        for w in residue
        if w not in _ARMOR_CATEGORIES and w not in _DAMAGE_TYPES and w != "weapons"
    ]
    return requires, conflicts, not residue


# --- Fundamental rune effects -------------------------------------------
#
# Hand-authored rather than extracted: there are only a couple of dozen of
# them, every consumer depends on them, and the prose states each grade
# absolutely ("The weapon deals three weapon damage dice") rather than as a
# delta, so a variant's effects replace the base rune's outright.
#
# Keyed by (lowercased rune name, lowercased variant name); a rune with no
# variants keys on None.
#
# ponytail: a static table can't notice errata that changes a number inside an
# existing rune — only a new or renamed grade, via the coverage assert in
# rune_pass. Upgrade path is the change_records enrichment sidecar
# (source_type 'equipment_rune'), whose text hashing gives staleness
# detection; property runes need that machinery anyway, so build it once there.


def _set(subject, value):
    return {
        "type": "stat_block_section",
        "subtype": "rune_effect",
        "operation": "set",
        "subject": subject,
        "value": value,
    }


def _bonus(subject, value, maximum=None):
    """An item bonus to `subject`.

    Every fundamental rune bonus is an item bonus per the rules text, armor
    potency included — so a consumer combines it with the base armor's own
    (bonus_type "armor") AC bonus rather than taking the higher of the two.
    """
    effect = {
        "type": "stat_block_section",
        "subtype": "rune_effect",
        "operation": "add_modifier",
        "subject": subject,
        "modifier": {
            "type": "bonus",
            "subtype": subject,
            "bonus_type": "item",
            "bonus_value": value,
        },
    }
    if maximum is not None:
        effect["maximum"] = maximum
    return effect


def _reinforcing(hardness, hardness_max, hit_points, hit_points_max, bt, bt_max):
    return [
        _bonus("hardness", hardness, hardness_max),
        _bonus("hit_points", hit_points, hit_points_max),
        _bonus("break_threshold", bt, bt_max),
    ]


_FUNDAMENTAL_EFFECTS = {
    ("weapon potency", "weapon potency (+1)"): [
        _bonus("attack", 1),
        _set("property_rune_slots", 1),
    ],
    ("weapon potency", "weapon potency (+2)"): [
        _bonus("attack", 2),
        _set("property_rune_slots", 2),
    ],
    ("weapon potency", "weapon potency (+3)"): [
        _bonus("attack", 3),
        _set("property_rune_slots", 3),
    ],
    ("mythic weapon potency", None): [_bonus("attack", 4), _set("property_rune_slots", 4)],
    ("armor potency", "armor potency (+1)"): [_bonus("ac", 1), _set("property_rune_slots", 1)],
    ("armor potency", "armor potency (+2)"): [_bonus("ac", 2), _set("property_rune_slots", 2)],
    ("armor potency", "armor potency (+3)"): [_bonus("ac", 3), _set("property_rune_slots", 3)],
    ("mythic armor potency", None): [_bonus("ac", 4), _set("property_rune_slots", 4)],
    ("striking", "striking"): [_set("weapon_damage_dice", 2)],
    ("striking", "striking (greater)"): [_set("weapon_damage_dice", 3)],
    ("striking", "striking (major)"): [_set("weapon_damage_dice", 4)],
    ("mythic striking", None): [_set("weapon_damage_dice", 5)],
    ("resilient", "resilient"): [_bonus("save", 1)],
    ("resilient", "resilient (greater)"): [_bonus("save", 2)],
    ("resilient", "resilient (major)"): [_bonus("save", 3)],
    ("mythic resilent", None): [_bonus("save", 4)],
    ("reinforcing rune", "reinforcing rune (minor)"): _reinforcing(3, 8, 44, 64, 22, 32),
    ("reinforcing rune", "reinforcing rune (lesser)"): _reinforcing(3, 10, 52, 80, 26, 40),
    ("reinforcing rune", "reinforcing rune (moderate)"): _reinforcing(3, 13, 64, 104, 32, 52),
    ("reinforcing rune", "reinforcing rune (greater)"): _reinforcing(5, 15, 80, 120, 40, 60),
    ("reinforcing rune", "reinforcing rune (major)"): _reinforcing(5, 17, 84, 136, 42, 68),
    ("reinforcing rune", "reinforcing rune (supreme)"): _reinforcing(7, 20, 108, 160, 54, 80),
}


def _effects_for(name, variant_name):
    key = (name.lower(), variant_name.lower() if variant_name else None)
    effects = _FUNDAMENTAL_EFFECTS.get(key)
    return copy.deepcopy(effects) if effects else None


def _usage_text(stat_block):
    statistics = stat_block.get("statistics") or {}
    usage = statistics.get("usage") or {}
    return usage.get("text")


def is_rune(stat_block):
    return stat_block.get("item_category") == RUNE_CATEGORY


def rune_pass(struct):
    """Decorate a rune item (and each of its variants) with slot metadata.

    No-op for anything that isn't a rune. Variants inherit the parent's rune
    block: a grade changes what the rune does, never where it can go.
    """
    stat_block = struct.get("stat_block")
    if not stat_block or not is_rune(stat_block):
        return

    subcategory = stat_block.get("item_subcategory")
    spec = _SUBCATEGORY_SPEC.get(subcategory)
    assert spec, f"Unrecognized rune subcategory: {subcategory!r} on {struct.get('name')!r}"
    host, form = spec

    name = struct.get("name", "")
    rune = {
        "type": "stat_block_section",
        "subtype": "rune",
        "form": form,
        "slot": _slot_for(name, form),
        "host": host,
    }

    usage_text = _usage_text(stat_block)
    if usage_text:
        rune["usage_text"] = usage_text

    if host in _PROSE_ONLY_HOSTS:
        # Eligibility is prose by design; nothing to review.
        pass
    elif subcategory in _SUBCATEGORY_REQUIRES and not usage_text:
        rune["requires"] = copy.deepcopy(_SUBCATEGORY_REQUIRES[subcategory])
    else:
        requires, conflicts, fully_parsed = parse_usage(usage_text)
        if conflicts:
            rune["conflicts_with"] = sorted(set(conflicts))
        if fully_parsed:
            if requires:
                rune["requires"] = requires
        else:
            # Partial clauses are worse than none: a consumer filtering on
            # them would treat an incomplete requirement list as authoritative
            # and call ineligible items legal.
            rune["needs_review"] = True

    stat_block["rune"] = rune
    variants = stat_block.get("variants", [])
    for variant in variants:
        # deepcopy, not dict(): a shallow copy would alias the requires and
        # conflicts_with lists across the base block and every variant.
        variant["rune"] = copy.deepcopy(rune)

    base_effects = _effects_for(name, None)
    if base_effects:
        stat_block["effects"] = base_effects
    for variant in variants:
        variant_effects = _effects_for(name, variant.get("name"))
        if variant_effects:
            variant["effects"] = variant_effects

    if form == "fundamental":
        # Every fundamental rune grade is hand-authored, and every consumer
        # depends on them — a new or renamed one must fail the parse rather
        # than ship silently undecorated.
        undecorated = [v["name"] for v in variants if not v.get("effects")]
        if not variants and not base_effects:
            undecorated = [name]
        assert not undecorated, (
            f"Fundamental rune {name!r} has grades with no effects: {undecorated}. "
            "Add them to _FUNDAMENTAL_EFFECTS."
        )
