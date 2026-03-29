"""Universal spell parser for creature stat blocks and monster families.

Parses spell blocks from HTML into structured spell objects with
spell_tradition, spell_type, saving_throw, spell_attack, and nested
spell_list → spell arrays.

Extracted from pfsrd2/creatures.py to be shared across parsers.
"""

import re
from pprint import pprint

from bs4 import BeautifulSoup

import pfsrd2.constants as constants
from universal.creatures import universal_handle_save_dc
from universal.universal import extract_link
from universal.utils import get_text, split_maintain_parens

# Class → tradition mapping for auto-inserting tradition from class name
_CLASS_TRADITIONS = {
    "Wizard": "Arcane",
    "Magus": "Arcane",
    "Bard": "Occult",
    "Witch": "Occult",
    "Champion": "Divine",
    "Cleric": "Divine",
    "Druid": "Primal",
}

_VALID_TRADITIONS = {"Occult", "Arcane", "Divine", "Primal", "Unique"}


def is_spell_name(name):
    """Check if a name indicates a spell section.

    Checks for 'Spells' in parts, or ends with 'Rituals'/'Formulas'/'Hexes'.
    Excludes known non-spell names like 'Soul Spells', 'Signature Spells'.
    """
    if name in constants.CREATURE_NOT_SPELLS:
        return False
    parts = name.split(" ")
    return bool(
        "Spells" in parts
        or name.endswith("Rituals")
        or name.endswith("Formulas")
        or name.endswith("Hexes")
    )


def parse_spell_block(name, text, action_type=None, traits=None):
    """Parse a spell block from name + HTML text.

    Args:
        name: spell block name (e.g., "Primal Prepared Spells")
        text: HTML text after the name (DC, attack, spell levels)
        action_type: pre-extracted action_type object (optional)
        traits: pre-extracted traits list (optional)

    Returns:
        dict with subtype="spells", containing spell_tradition, spell_type,
        saving_throw, spell_attack, focus_points, spell_list array.
    """
    section = {
        "type": "stat_block_section",
        "subtype": "spells",
        "name": name,
    }
    if action_type:
        section["action_type"] = action_type
    if traits:
        section["traits"] = traits

    # Strip trailing "DC" from name (some family HTML bakes it in)
    if name.endswith(" DC"):
        name = name[:-3]
        section["name"] = name

    # Parse tradition and spell type from name
    name_parts = name.split(" ")
    _handle_traditions(name_parts)
    if name_parts[-1] not in ["Formulas", "Rituals"] and "Monk" not in name_parts:
        if name_parts[0] in _VALID_TRADITIONS:
            section["spell_tradition"] = name_parts.pop(0)
        elif len(name_parts) > 1 and name_parts[1] in _VALID_TRADITIONS:
            section["spell_tradition"] = name_parts.pop(1)
    if name_parts[-1] == "Rituals" and len(name_parts) > 1:
        name_parts.pop(0)
    section["spell_type"] = " ".join(name_parts)
    _handle_bloodline(section)

    # Parse header metadata (DC, attack, focus points) from first semicolon part
    parts = split_maintain_parens(text, ";")
    tt_parts = split_maintain_parens(parts.pop(0), ",")
    remains = []
    for tt in tt_parts:
        tt = tt.strip()
        if tt == "":
            continue
        chunks = tt.split(" ")
        if tt.startswith("DC"):
            section["saving_throw"] = universal_handle_save_dc(tt)
        elif tt.startswith("attack") or tt.startswith("spell attack"):
            section["spell_attack"] = int(chunks.pop())
        elif tt.endswith("Focus Points"):
            section["focus_points"] = int(tt.replace(" Focus Points", "").strip())
        elif tt.endswith("Focus Point"):
            section["focus_points"] = int(tt.replace(" Focus Point", "").strip())
        else:
            remains.append(tt)

    if len(remains) > 0 and remains != tt_parts:

        def _fix_parens(r):
            if r.startswith("("):
                r = r[1:]
            if r.endswith(")") and r.find("(") == -1:
                r = r[:-1]
            return r

        remains = [_fix_parens(r) for r in remains]
        # Strip any HTML tags from notes
        clean_notes = []
        for note in remains:
            if "<" in note:
                note_bs = BeautifulSoup(note, "html.parser")
                note = get_text(note_bs).strip()
            clean_notes.append(note)
        section["notes"] = clean_notes
        addons = ["DC", "attack", "Focus"]
        for addon in addons:
            for note in section["notes"]:
                assert addon not in note, f"{addon} should not be in spell notes: {note}"
                assert addon.lower() not in note, f"{addon} should not be in spell notes: {note}"
        remains = []
    if len(remains) > 0:
        parts.insert(0, ", ".join(remains))

    # Parse each remaining part as a spell list.
    # Some parts start with "as young X, plus" referencing another subtype —
    # strip that prefix and store it as notes.
    spell_lists = []
    assert len(parts) > 0, section
    for p in parts:
        p_stripped, ref_note = _strip_reference_prefix(p)
        if ref_note:
            section.setdefault("notes", []).append(ref_note)
        if p_stripped.strip():
            spell_lists.append(_parse_spell_list(section, p_stripped))
    section["spell_list"] = spell_lists

    return section


def _strip_reference_prefix(part):
    """Strip 'as young/adult/ancient X, plus' prefix from a spell list part.

    Monster families reference earlier subtypes with phrases like
    'as young brine dragon, plus <b>5th</b> cone of cold'.
    Returns (stripped_part, reference_note_or_None).
    """
    # Match "as <words>, plus <rest>" or "as <words>; plus <rest>"
    m = re.match(r"^(as\s+.+?),?\s+plus\s+", part, re.IGNORECASE)
    if m:
        return part[m.end() :], m.group(1).strip()
    # Match "as <words>" with no "plus" (entire part is a reference)
    m2 = re.match(r"^as\s+.+$", part.strip(), re.IGNORECASE)
    if m2 and "<b>" not in part:
        return "", part.strip()
    return part, None


def _handle_traditions(name_parts):
    """Auto-insert tradition name when class name is present."""
    for caster, tradition in _CLASS_TRADITIONS.items():
        if caster in name_parts:
            if tradition not in name_parts:
                name_parts.insert(0, tradition)
            return


def _handle_bloodline(section):
    """Extract bloodline name from spell_type if present."""
    if "Bloodline" in section["spell_type"]:
        parts = section["spell_type"].split(" ")
        if len(parts) == 4:
            # Old format: [class, bloodline_name, "Bloodline", "Spells"]
            section["bloodline"] = parts[1]
            del parts[1]
            section["spell_type"] = " ".join(parts)


def _parse_spell_list(section, part):
    """Parse a single spell level (e.g., '3rd <spell>, <spell>')."""
    try:
        spell_list = {"type": "stat_block_section", "subtype": "spell_list"}
        bs = BeautifulSoup(part, "html.parser")
        if not bs.b and section["name"] == "Alchemical Formulas":
            pass
        else:
            level_text = get_text(bs.b.extract())
            if level_text == "Constant":
                spell_list["constant"] = True
                level_text = get_text(bs.b.extract()) if bs.b else ""
            if level_text == "Cantrips":
                spell_list["cantrips"] = True
                level_text = get_text(bs.b.extract()) if bs.b else ""
            elif level_text.startswith("Cantrips"):
                # Combined format: "Cantrips (3rd)" as single <b> tag
                spell_list["cantrips"] = True
                level_text = level_text.replace("Cantrips", "").strip()
            m = re.match(r"^\(?(\d*)[snrt][tdh]\)?$", level_text)
            assert m, f"Failed to parse spells: {part}"
            spell_list["level"] = int(m.groups()[0])
            spell_list["level_text"] = level_text
        spells_html = split_maintain_parens(str(bs), ",")
        spells = []
        for html in spells_html:
            spells.append(_parse_spell(html))
        spell_list["spells"] = spells
        return spell_list
    except AttributeError as e:
        print(section)
        pprint(part)
        raise e


def _parse_spell(html):
    """Parse a single spell entry from HTML."""
    spell = {"type": "stat_block_section", "subtype": "spell"}
    bsh = BeautifulSoup(html, "html.parser")
    hrefs = bsh.find_all("a")
    links = []
    for a in hrefs:
        _, link = extract_link(a)
        links.append(link)
    spell["links"] = links
    text = get_text(bsh)
    if text.find("(") > -1:
        parts = [t.strip() for t in text.split("(")]
        assert len(parts) == 2, f"Failed to parse spell: {html}"
        spell["name"] = parts.pop(0)
        count_text = parts.pop().replace(")", "")
        spell["count_text"] = count_text
        count = None
        for split in [";", ","]:
            remainder = []
            for part in count_text.split(split):
                m = re.match(r"^x\d*$", part.strip())
                if m:
                    assert count is None, f"Failed to parse spell: {html}"
                    count = int(part.strip()[1:])
                else:
                    remainder.append(part)
                count_text = split.join(remainder)
        if count:
            spell["count"] = count
    else:
        spell["name"] = text
        spell["count"] = 1
    return spell
