"""Structured spell slot metadata for equipment items.

Scrolls, wands and staves hold spells, and the rules for what may go in them
live in prose. This module decorates the holders with the structured
equivalent:

  stat_block.spell_slots  — what the item can hold, and (for staves) what it
                            already holds, as rank -> spells
  variant.spell_slots     — a staff grade's own additions, which are
                            cumulative on top of the lower grades
  variant.spell_rank      — the rank a scroll/wand variant is priced for

The inversion versus runes and materials is deliberate. A rune decorates an
item that exists independently; a scroll or wand is a TEMPLATE until a spell
fills it, and its level, Price, rarity and traits all derive from the spell it
ends up holding (GM Core 262, 282). So the interesting constraint here is on
the SPELL, not on the host item.

Charge economy is NOT stored per item: a staff gains charges equal to the
preparer's highest spell rank, casting costs charges equal to the spell's
rank, and cantrips cost nothing (GM Core 278). Those are universal constants,
identical for every staff, so they are documented here rather than copied onto
90 items.
"""

import re

STAVES_CATEGORY = "Staves"
WANDS_CATEGORY = "Wands"
SCROLLS_SUBCATEGORY = "Scrolls"

# GM Core 262: scrolls go up to 10th rank.
SCROLL_MAX_RANK = 10

# GM Core 282: "Cantrips, focus spells, and rituals can't be placed in wands",
# and the published table stops at 9th rank.
WAND_MAX_RANK = 9
WAND_EXCLUDED_SPELL_TYPES = ("cantrip", "focus", "ritual")

# A bullet line naming a rank and the spells at it:
#   "* **Cantrip** *light*"      "* 1st fear, phantom pain"
_BULLET = re.compile(
    r"^\*\s*(?:\*\*)?(Cantrip|\d+)(?:st|nd|rd|th)?(?:\*\*)?\s+(.+?)\s*$",
    re.I | re.M,
)

# The rank a scroll/wand variant is priced for, from its name:
#   "Magic Wand (3rd-rank Spell)"   "3rd-rank Scroll"   "(2nd-Level Spell)"
_VARIANT_RANK = re.compile(r"(\d+)(?:st|nd|rd|th)[- ](?:rank|level)\b", re.I)

# Craft requirements naming one specific spell the wand always holds:
#   "Supply a casting of *force barrage* of the appropriate rank."
_FIXED_SPELL = re.compile(r"supply\s+(?:a|one)\s+casting\s+of\s+\*([^*]+)\*", re.I)

# Craft requirements leaving the spell open:
#   "Supply a casting of the spell at the listed rank."
_OPEN_SLOT = re.compile(r"casting\s+of\s+the\s+spell\b", re.I)

_EMPHASIS = re.compile(r"[*_]+")

# A trailing qualifier on a listed spell: "summon dragon (6th)",
# "illusory creature (dragons only)". It restricts or heightens the entry and
# is not part of the spell's name, so it is split off rather than dropped.
_QUALIFIER = re.compile(r"\s*\(([^()]*)\)\s*$")


def _clean(name):
    return _EMPHASIS.sub("", name).strip().strip(",").strip()


def _split_spells(text):
    """Split a rank's spell list on commas that aren't inside parentheses.

    "summon plant or fungus (fungus only, not a tree), wall of thorns" is two
    spells, not three — a naive split turns the qualifier's comma into a
    phantom spell named "not a tree)".
    """
    parts, depth, current = [], 0, []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [p for p in parts if p.strip()]


def _spell_index(links):
    """Map lowercased spell name -> aonid, from a links list."""
    index = {}
    for link in links or []:
        if link.get("game-obj") == "Spells" and link.get("name"):
            index.setdefault(link["name"].lower(), link.get("aonid"))
    return index


def parse_spell_entries(text, links=None):
    """Parse a staff's rank bullets into [{rank, spells: [{name, aonid?}]}].

    Every published staff list is a markdown bullet per rank, sometimes after
    a prose preamble. Returns [] when the text carries no such bullets.
    """
    index = _spell_index(links)
    entries = []
    for rank_token, spell_text in _BULLET.findall(text or ""):
        rank = "cantrip" if rank_token.lower() == "cantrip" else int(rank_token)
        spells = []
        for raw in _split_spells(spell_text):
            name = _clean(raw)
            if not name:
                continue
            note = None
            qualifier = _QUALIFIER.search(name)
            if qualifier:
                note = _clean(qualifier.group(1))
                name = _clean(name[: qualifier.start()])
            spell = {"type": "stat_block_section", "subtype": "spell_slot_spell", "name": name}
            if note:
                spell["note"] = note
            aonid = index.get(name.lower())
            if aonid is not None:
                spell["aonid"] = aonid
            spells.append(spell)
        if spells:
            entries.append(
                {
                    "type": "stat_block_section",
                    "subtype": "spell_slot_entry",
                    "rank": rank,
                    "spells": spells,
                }
            )
    return entries


def variant_rank(name):
    """The spell rank a scroll/wand variant is priced for, or None."""
    match = _VARIANT_RANK.search(name or "")
    return int(match.group(1)) if match else None


def _abilities(stat_block):
    return ((stat_block.get("statistics") or {}).get("abilities")) or []


def _staff_pass(stat_block):
    slots = {
        "type": "stat_block_section",
        "subtype": "spell_slots",
        "holder": "staff",
        # GM Core 278. Stated per staff because it is the one charge rule a
        # consumer needs at the point of use; the rest are universal.
        "cantrips_free": True,
    }

    # The list lives in one of three places depending on how AoN laid the page
    # out: on each grade variant, inside the Cast a Spell activation, or in the
    # item text. Variants win — a graded staff adds ranks per grade.
    entries = []
    for variant in stat_block.get("variants", []):
        found = parse_spell_entries(variant.get("text"), variant.get("links"))
        if found:
            variant["spell_slots"] = {
                "type": "stat_block_section",
                "subtype": "spell_slots",
                "holder": "staff",
                # A grade's spells are ADDITIONS to the lower grades, not a
                # replacement, which is how the source presents them.
                "cumulative": True,
                "entries": found,
            }
    if not any("spell_slots" in v for v in stat_block.get("variants", [])):
        for ability in _abilities(stat_block):
            entries = parse_spell_entries(ability.get("effect"), ability.get("links"))
            if entries:
                break
        if not entries:
            entries = parse_spell_entries(stat_block.get("text"), stat_block.get("links"))
    if entries:
        slots["entries"] = entries
    stat_block["spell_slots"] = slots


def _template_pass(struct, stat_block, holder):
    """A scroll or wand: one slot, parameterised by rank."""
    slots = {
        "type": "stat_block_section",
        "subtype": "spell_slots",
        "holder": holder,
        "capacity": 1,
        "max_rank": WAND_MAX_RANK if holder == "wand" else SCROLL_MAX_RANK,
    }
    if holder == "wand":
        slots["excluded_spell_types"] = list(WAND_EXCLUDED_SPELL_TYPES)

    craft = stat_block.get("craft_requirements") or ""
    fixed = _FIXED_SPELL.search(craft)
    if fixed:
        # The wand always holds this spell; only the rank varies.
        name = _clean(fixed.group(1))
        spell = {"type": "stat_block_section", "subtype": "spell_slot_spell", "name": name}
        aonid = _spell_index(stat_block.get("links")).get(name.lower())
        if aonid is not None:
            spell["aonid"] = aonid
        slots["spell"] = spell
    elif craft and not _OPEN_SLOT.search(craft):
        # A specialty wand constrains which spells qualify ("casting time of
        # one or two actions, no duration, an area of burst, cone or line").
        # Kept as prose: the predicate is over spell fields this parser does
        # not model, and a partial structuring would read as authoritative.
        slots["constraint_text"] = craft

    stat_block["spell_slots"] = slots

    for variant in stat_block.get("variants", []):
        rank = variant_rank(variant.get("name"))
        assert rank, (
            f"{holder} variant {variant.get('name')!r} on {struct.get('name')!r} names no "
            "spell rank — its level and Price are meaningless without one"
        )
        assert rank <= slots["max_rank"], (
            f"{holder} variant {variant.get('name')!r} on {struct.get('name')!r} is rank "
            f"{rank}, above the {slots['max_rank']} the rules allow"
        )
        variant["spell_rank"] = rank


def spell_slot_pass(struct):
    """Decorate a spell-holding item. No-op for anything else."""
    stat_block = struct.get("stat_block")
    if not stat_block:
        return
    category = stat_block.get("item_category")
    if category == STAVES_CATEGORY:
        _staff_pass(stat_block)
    elif category == WANDS_CATEGORY:
        _template_pass(struct, stat_block, "wand")
    elif stat_block.get("item_subcategory") == SCROLLS_SUBCATEGORY:
        _template_pass(struct, stat_block, "scroll")
