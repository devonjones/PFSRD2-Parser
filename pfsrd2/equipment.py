import importlib
import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString, Tag

import pfsrd2.constants as constants
from pfsrd2.action import extract_action_type
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.traits import (
    fetch_trait_by_name,
)
from pfsrd2.sql.traits import (
    trait_db_pass as universal_trait_db_pass,
)
from universal.creatures import (
    universal_handle_alignment,
    universal_handle_range,
    universal_handle_save_dc,
    write_creature,
)
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass
from universal.universal import (
    aon_pass,
    build_object,
    build_objects,
    edition_from_alternate_link,
    edition_pass,
    entity_pass,
    extract_link,
    extract_links,
    extract_source,
    game_id_pass,
    get_links,
    handle_alternate_link,
    link_modifiers,
    modifiers_from_string_list,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_edition_override_pass,
    test_key_is_value,
    walk,
)
from universal.utils import (
    clear_garbage,
    clear_tags,
    extract_pfs_note,
    get_text,
    parse_section_modifiers,
    rebuilt_split_modifiers,
    recursive_filter_entities,
    split_comma_and_semicolon,
    split_maintain_parens,
    split_on_tag,
    split_stat_block_line,
)


# Equipment Type Configuration Registry
# To add a new equipment type, just add a configuration dictionary here
# Note: 'normalize_fields' will be populated after the normalizer functions are defined
def _normalize_whitespace(text):
    """Normalize whitespace in text by collapsing multiple whitespace characters to single space.

    After unwrapping links with BeautifulSoup, there may be extra newlines or spaces
    that were part of the HTML formatting. This function normalizes them.
    """
    # Replace any sequence of whitespace characters (spaces, tabs, newlines) with a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _trait_class_matcher(c):
    """Match BeautifulSoup class attributes that start with 'trait'.

    BeautifulSoup passes class as string if single class, list if multiple, or None if no class.
    This matcher function works with all formats.
    """
    if not c:
        return False
    if isinstance(c, str):
        return c.startswith("trait")
    else:  # list of classes
        return any(cls.startswith("trait") for cls in c)


# Default field destinations shared across armor, shield, and equipment types.
# The routing code only processes fields actually present in extracted stats,
# so unused entries are harmless (e.g. 'access' for shields).
DEFAULT_FIELD_DESTINATIONS = {
    "price": None,  # top-level stat_block
    "bulk": None,  # top-level stat_block
    "access": "statistics",
}

EQUIPMENT_TYPES = {
    "armor": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Access": "access",
            "Price": "price",
            "AC Bonus": "ac_bonus",
            "Dex Cap": "dex_cap",
            "Check Penalty": "check_penalty",
            "Speed Penalty": "speed_penalty",
            "Strength": "strength",
            "Bulk": "bulk",
            "Category": "category",
            "Group": "armor_group",
        },
        "field_destinations": {
            **DEFAULT_FIELD_DESTINATIONS,
            "category": "statistics",
            "strength": "statistics",  # becomes strength_requirement
            "ac_bonus": "defense",
            "dex_cap": "defense",
            "check_penalty": "defense",
            "speed_penalty": "defense",
            "armor_group": "defense",
        },
        "group_table": "armor_groups",
        "group_sql_module": "pfsrd2.sql.armor_groups",
        "group_subtype": "armor_group",
        "schema_file": "equipment.schema.json",
        "output_subdir": "armor",
        "normalize_fields": None,  # Set after function definition
    },
    "weapon": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Access": "access",
            "Price": "price",
            "Damage": "damage",
            "Bulk": "bulk",
            "Hands": "hands",
            "Range": "range",
            "Reload": "reload",
            "Type": "weapon_type",  # Renamed to avoid collision with structural 'type' field
            "Category": "category",
            "Group": "weapon_group",
            "Ammunition": "ammunition",
            "Favored Weapon": "favored_weapon",  # Deities that favor this weapon
            "PFS Note": None,  # Skip - PFS-specific note, not weapon stat
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price, bulk, access)
        # - weapon_fields: nested in weapon object (category, favored_weapon)
        # - mode_fields: nested in melee/ranged objects (damage, weapon_type, weapon_group, range, reload, ammunition, hands)
        #   Note: ammunition and hands can appear in weapon_fields OR mode_fields (combination weapons have them mode-specific)
        "shared_fields": ["access", "price", "bulk"],
        "weapon_fields": ["category", "hands", "ammunition", "favored_weapon"],
        "mode_fields": [
            "damage",
            "weapon_type",
            "weapon_group",
            "range",
            "reload",
            "ammunition",
            "hands",
        ],
        "group_table": "weapon_groups",
        "group_sql_module": "pfsrd2.sql.weapon_groups",
        "group_subtype": "weapon_group",
        "schema_file": "equipment.schema.json",
        "output_subdir": "weapons",
        "normalize_fields": None,  # Set after function definition
    },
    "shield": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Price": "price",
            "AC Bonus": "ac_bonus",
            "Speed Penalty": "speed_penalty",
            "Bulk": "bulk",
            "Hardness": "hardness",
            "HP (BT)": "hp_bt",
        },
        "field_destinations": {
            **DEFAULT_FIELD_DESTINATIONS,
            "ac_bonus": "defense",
            "speed_penalty": "defense",
            "hardness": "defense",
            "hp_bt": "defense",
        },
        "schema_file": "equipment.schema.json",
        "output_subdir": "shields",
        "normalize_fields": None,  # Set after function definition
    },
    "siege_weapon": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Price": "price",
            "Usage": "usage",
            "Crew": "crew",
            "Proficiency": "proficiency",
            "Ammunition": "ammunition",
            "Space": "space",
            "AC": "ac",
            "Fort": "fort",
            "Ref": "ref",
            "Hardness": "hardness",
            "HP": "hp_bt",  # HTML has just "HP" (value includes "(BT 20)" part)
            "Immunities": "immunities",
            "Speed": "speed",
            "Bulk": "bulk",
            # Action sections (handled separately by section_pass)
            "Aim": None,
            "Load": None,
            "Launch": None,
            "Ram": None,
            "Effect": None,
            "Requirements": None,
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price)
        # - nested_fields: nested in siege_weapon object (all others)
        "shared_fields": ["price", "bulk"],
        "nested_fields": [
            "usage",
            "crew",
            "proficiency",
            "ammunition",
            "space",
            "ac",
            "fort",
            "ref",
            "hardness",
            "hp_bt",
            "immunities",
            "speed",
        ],
        "schema_file": "equipment.schema.json",
        "output_subdir": "siege_weapons",
        "normalize_fields": None,  # Set after function definition
    },
    "vehicle": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Price": "price",
            "Space": "space",
            "Crew": "crew",
            "Passengers": "passengers",
            "Piloting Check": "piloting_check",
            "AC": "ac",
            "Fort": "fort",
            "Hardness": "hardness",
            "HP": "hp_bt",  # HTML has just "HP" (value includes "(BT 20)" part)
            "Immunities": "immunities",
            "Resistances": "resistances",
            "Weaknesses": "weaknesses",
            "Speed": "speed",
            "Collision": "collision",
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price)
        # - nested_fields: nested in vehicle object (all others)
        "shared_fields": ["price"],
        "nested_fields": [
            "space",
            "crew",
            "passengers",
            "piloting_check",
            "ac",
            "fort",
            "hardness",
            "hp_bt",
            "immunities",
            "resistances",
            "weaknesses",
            "speed",
            "collision",
        ],
        "schema_file": "equipment.schema.json",
        "output_subdir": "vehicles",
        "normalize_fields": None,  # Set after function definition
    },
    "equipment": {
        "recognized_stats": {
            "Source": None,  # Handled separately
            "Price": "price",
            "Bulk": "bulk",
            "Hands": "hands",
            "Usage": "usage",
            "Activate": "activate",
            "Requirements": None,  # Part of activation, handled separately
            "Access": "access",
            "PFS Note": None,  # PFS-specific notes, ignored for now
            "Special": "special",
            "Craft Requirements": "craft_requirements",
            "Destruction": "destruction",
            "Ammunition": "ammunition",
            "Base Weapon": "base_weapon",
            "Base Armor": "base_armor",
            "Base Shield": "base_shield",
            # Intelligent item stats
            "Perception": "perception",
            "Communication": "communication",
            "Languages": "languages",
            "Skills": "skills",
            "Int": "int",
            "Wis": "wis",
            "Cha": "cha",
            "Will": "will",
            # The following are NOT top-level equipment stats - they belong inside
            # abilities or afflictions. Mark with 'ERROR:' prefix to throw clear errors.
            "Effect": "ERROR:abilities",
            "Frequency": "ERROR:abilities",
            "Duration": "ERROR:abilities",
            "Onset": "ERROR:afflictions",
            "Maximum Duration": "ERROR:afflictions",
            "Saving Throw": "ERROR:afflictions",
            "Trigger": "ERROR:abilities",
            "Stage 1": "ERROR:afflictions",
            "Stage 2": "ERROR:afflictions",
            "Stage 3": "ERROR:afflictions",
            "Stage 4": "ERROR:afflictions",
            "Stage 5": "ERROR:afflictions",
            "Stage 6": "ERROR:afflictions",
        },
        # Field destinations: None = stat_block top level, or 'statistics'/'offense'/'defense'
        "field_destinations": {
            **DEFAULT_FIELD_DESTINATIONS,
            "hands": "statistics",
            "usage": "statistics",
            "activate": "statistics",  # Special handling converts to ability
            "special": None,
            "craft_requirements": None,
            "destruction": None,
            "ammunition": "offense",
            "base_weapon": "offense",
            "base_armor": "defense",
            "base_shield": "defense",
            # Intelligent item stats go in statistics
            "perception": "statistics",
            "communication": "statistics",
            "languages": "statistics",
            "skills": "statistics",
            "int": "statistics",
            "wis": "statistics",
            "cha": "statistics",
            "will": "statistics",
        },
        "nested_fields": [],  # No nested object for general equipment
        "schema_file": "equipment.schema.json",
        "output_subdir": "equipment",
        "normalize_fields": None,  # Set after function definition
    },
}


# Equipment items that are allowed to have span tags (for broken HTML with action icons)
# Only add items here after manually verifying the HTML is genuinely broken
EQUIPMENT_SPANS_ALLOWED = [
    "Wand of Continuation",
    "Wand of Widening",
    "Wand of Reaching",
    "Undead Compendium",
    "Ferrofluid Urchin",
    "Horned Hand Rests",
]


def equipment_markdown_valid_set(struct, name, path, validset):
    """Allow additional tags in equipment markdown.

    - h2/h3: Allowed for all equipment as labels for tables in effect text
    - span: Only for specific items with broken HTML (missing <br> or <b> tags)
    """
    # h2/h3 can appear as table labels within effect text (e.g., Rod of Wonder)
    validset.add("h2")
    validset.add("h3")

    if name in EQUIPMENT_SPANS_ALLOWED:
        validset.add("span")


# ============================================================================
# V2 ENTRY POINT - uses parse_universal instead of parse_equipment_html
# ============================================================================


def _strip_equipment_nav(main):
    """Strip navigation elements from equipment HTML.

    Equipment has TWO nav levels in <span> tags before a direct-child <hr>.
    Uses recursive=False to find the correct hr (not one inside a nav span).
    """
    hr = main.find("hr", recursive=False)
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()

    # Unwrap the content span that contains h1
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
            break


def _restructure_h1_title(main, h1):
    """Restructure h1.title to contain the item name with metadata prefix.

    Equipment h1 contains only the PFS icon; the item name follows as a sibling.
    Extracts level, PFS status, and name, then rebuilds h1 as:
        __EQ_META:{pfs}:{level}__ {name}

    Returns (pfs_status, level) or ("Standard", 0) if no h1.
    """
    # Extract level span FIRST (may be inside h1 or a sibling)
    level = 0
    level_span = h1.find("span", style=lambda s: s and "margin-left:auto" in s)
    if not level_span:
        level_span = main.find("span", style=lambda s: s and "margin-left:auto" in s)
    if level_span:
        level_text = get_text(level_span).strip()
        level_match = re.match(r"Item\s+(\d+)", level_text, re.IGNORECASE)
        if level_match:
            level = int(level_match.group(1))
        level_span.decompose()

    # Extract PFS status from img alt text
    pfs_img = h1.find("img", alt=lambda s: s and s.startswith("PFS "))
    pfs_status = "Standard"
    if pfs_img:
        pfs_alt = pfs_img.get("alt", "")
        match = re.match(r"PFS\s+(\w+)", pfs_alt, re.IGNORECASE)
        assert match, f"PFS img found but alt text doesn't match expected format: '{pfs_alt}'"
        pfs_status = match.group(1).capitalize()

    # Remove PFS links/imgs/floating spans from h1
    for a in list(h1.find_all("a")):
        if "PFS" in a.get("href", ""):
            a.decompose()
    for img in list(h1.find_all("img")):
        img.decompose()
    for span in list(h1.find_all("span", style=lambda s: s and "float" in s)):
        span.decompose()

    # Three name structures: (A) sibling link, (B) link in h1, (C) plain text in h1
    remaining_text = get_text(h1).strip()
    if remaining_text:
        h1.clear()
        h1.append(NavigableString(remaining_text))
    else:
        h1.clear()
        for sibling in list(h1.next_siblings):
            if hasattr(sibling, "name") and sibling.name == "a":
                if "PFS" not in sibling.get("href", ""):
                    h1.append(NavigableString(get_text(sibling).strip()))
                    break
            if hasattr(sibling, "name") and sibling.name in ("h2", "h3", "b", "br"):
                break
            if isinstance(sibling, NavigableString):
                text = str(sibling).strip()
                if text and not text.startswith("Item"):
                    h1.append(NavigableString(text))
                    sibling.extract()
                    break

    # Embed metadata prefix for restructure_equipment_v2_pass
    h1.insert(0, NavigableString(f"__EQ_META:{pfs_status}:{level}__ "))


# Supplementary h2 section titles added by AoN after item content.
# In the original HTML these are after <div class="clear"> which lxml
# places outside main.
_SUPPLEMENTARY_H2_TITLES = {
    "Traits",
    "Armor Specialization Effects",
    "Critical Specialization Effects",
    "Specific Magic Armor",
    "Basic Magic Armor",
    "Consumables",
    "Other Consumables",
    "Precious Material Armor",
    "Precious Material Weapons",
    "Specific Magic Weapons",
    "Basic Magic Weapons",
}


def _remove_supplementary_sections(main):
    """Remove supplementary h2 sections and trait-entry divs from main."""
    for h2 in main.find_all("h2", class_="title"):
        if get_text(h2).strip() in _SUPPLEMENTARY_H2_TITLES:
            to_remove = []
            current = h2
            while current:
                to_remove.append(current)
                current = current.next_sibling
            for node in to_remove:
                if hasattr(node, "decompose"):
                    node.decompose()
                elif hasattr(node, "extract"):
                    node.extract()
            break

    for div in main.find_all("div", class_="trait-entry"):
        div.decompose()


def _remove_empty_links(main):
    """Remove empty <a> tags and PFS icon links (but keep PFS Note links)."""
    for a in main.find_all("a"):
        if not a.get_text(strip=True) and not a.find("img"):
            a.decompose()
    for a in main.find_all("a", href=lambda h: h and "PFS.aspx" in h):
        if not a.get_text(strip=True):
            a.decompose()


def _content_filter_v2(soup):
    """Pre-filter for parse_universal: equipment-specific HTML restructuring."""
    main = soup.find(id="main")
    if not main:
        return

    _strip_equipment_nav(main)

    h1 = main.find("h1", class_="title")
    if h1:
        _restructure_h1_title(main, h1)

    _remove_supplementary_sections(main)
    _remove_empty_links(main)


def _sidebar_filter(soup):
    """Pre-filter for parse_universal: remove sidebar divs (supplementary info)."""
    for div in soup.find_all("div", class_="sidebar"):
        div.decompose()


def restructure_equipment_v2_pass(details, equipment_type):
    """Build the standard equipment structure from parse_universal output.

    parse_universal with max_title=1 returns a list with one section dict
    containing the title (h1 text) and all content as 'text'.

    Args:
        details: List of section dicts from parse_universal + entity_pass
        equipment_type: Type of equipment (armor, weapon, etc.)

    Returns:
        Top-level struct dict ready for the standard pipeline
    """
    # With max_title=1, we get one section per h1 title
    assert (
        len(details) >= 1
    ), f"Expected at least 1 section from parse_universal, got {len(details)}"

    first = details[0]
    assert isinstance(first, dict), f"Expected dict, got {type(first)}"

    # Extract name from the section title
    # _content_filter_v2 embedded metadata as a prefix in the h1 text:
    # "__EQ_META:PFS_STATUS:LEVEL__ ActualName"
    raw_name = first.get("name", "")

    # Parse metadata prefix
    meta_match = re.match(r"__EQ_META:(\w+):(\d+)__\s*(.*)", raw_name)
    if not meta_match:
        raise AssertionError(f"Missing __EQ_META__ prefix in section name. Raw: '{raw_name}'")

    name = meta_match.group(3).strip()
    # Remove trailing "Item N" if level span leaked into title
    name = re.sub(r"\s*Item\s+\d+\+?\s*$", "", name).strip()

    if not name:
        raise AssertionError(
            f"Could not extract equipment name from parse_universal output. Raw: '{raw_name}'"
        )

    # Extract text content (everything below the h1)
    text = first.get("text", "")

    # Also collect text from any additional sections (shouldn't normally happen with max_title=1)
    for detail in details[1:]:
        if isinstance(detail, dict) and "text" in detail:
            text += detail["text"]
        elif isinstance(detail, str):
            text += detail

    # PFS and level were extracted from the __EQ_META__ prefix above
    pfs = meta_match.group(1)
    level = int(meta_match.group(2))

    # Extract image if present (same pattern as creatures: <a href="Images\...">)
    image = None
    text_soup = BeautifulSoup(text, "html.parser")
    for a_tag in text_soup.find_all("a"):
        href = a_tag.get("href", "")
        if "Images" not in href:
            continue
        if not image and href:
            image_filename = href.split("\\").pop().split("%5C").pop()
            image = {
                "type": "image",
                "name": name,
                "image": image_filename,
            }
        a_tag.decompose()
    if image:
        text = str(text_soup)

    # Remove Legacy Content h3 if present (converted to edition field, not a section)
    legacy_h3 = text_soup.find("h3", class_="title", string=lambda s: s and "Legacy Content" in s)
    if legacy_h3:
        legacy_h3.decompose()
        text = str(text_soup)

    # Re-insert newlines before structural HTML tags.
    # parse_universal removes all newlines, collapsing everything to one line.
    # section_pass uses BeautifulSoup's sourceline to distinguish stat labels
    # (before <hr>) from description content (after <hr>). Without newlines,
    # all sourceline values are 1 and the position check fails.
    text = (
        text.replace("<hr", "\n<hr")
        .replace("<hr/>", "<hr/>\n")
        .replace("<hr>", "<hr>\n")
        .replace("<h2", "\n<h2")
        .replace("</h2>", "</h2>\n")
        .replace("<h3", "\n<h3")
    )

    # Build stat block section
    sb = {
        "type": "stat_block",
        "subtype": equipment_type,
        "text": text,
        "sections": [],
        "level": level,
    }
    if image:
        sb["image"] = image

    # Build top-level structure
    top = {
        "name": name,
        "type": equipment_type,
        "sources": [],
        "sections": [sb],
        "pfs": pfs,
    }

    return top


def parse_equipment_v2(filename, options):
    """V2 equipment parser - uses parse_universal instead of parse_equipment_html.

    Produces identical output to parse_equipment but uses the standard
    parse_universal entry point like every other parser.
    """
    equipment_type = options.equipment_type
    config = EQUIPMENT_TYPES[equipment_type]

    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")

    # 1. Standard parse_universal entry point
    details = parse_universal(
        filename,
        max_title=1,
        cssclass="main",
        pre_filters=[_content_filter_v2, _sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]

    # 2. Handle alternate edition link
    alternate_link = handle_alternate_link(details, allow_multiple=True)

    # 3. Restructure (equipment-specific)
    struct = restructure_equipment_v2_pass(details, equipment_type)
    if alternate_link:
        # Store single dict (schema expects object, not array).
        # Items split into multiple remastered versions have multiple links;
        # use the first one for compatibility with v1.
        if isinstance(alternate_link, list):
            struct["alternate_link"] = alternate_link[0]
        else:
            struct["alternate_link"] = alternate_link

    # 4. Standard pass pipeline
    aon_pass(struct, basename)
    section_pass(struct, config)

    # Normalize pfs to object form (section_pass may have already converted it
    # via extract_pfs_note; ensure consistency for items without PFS Notes)
    if isinstance(struct.get("pfs"), str):
        struct["pfs"] = {
            "type": "stat_block_section",
            "subtype": "pfs",
            "availability": struct["pfs"],
        }

    restructure_pass(struct, "stat_block", find_stat_block)
    normalize_numeric_fields_pass(struct, config)

    # Determine edition (legacy vs remastered) BEFORE cleanup
    edition = edition_from_alternate_link(struct) or edition_pass(struct["sections"])
    struct["edition"] = edition
    source_edition_override_pass(struct)
    game_id_pass(struct)
    license_pass(struct)
    markdown_pass(struct, struct["name"], "", fxn_valid_tags=equipment_markdown_valid_set)

    # Enrich traits with database data (must be after edition is set)
    universal_trait_db_pass(struct, pre_process=_equipment_trait_pre_process)
    license_consolidation_pass(struct)

    # Enrich equipment groups with database data (only for types that have groups)
    if "group_table" in config:
        equipment_group_pass(struct, config)

    # Populate creature-style buckets (statistics, defense, offense)
    populate_equipment_buckets_pass(struct)
    remove_empty_sections_pass(struct)
    _remove_empty_values_pass(struct)

    # Fix character encoding issues
    recursive_filter_entities(struct)

    # 5. Validate + write
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, config["schema_file"])
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, config["output_subdir"], name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def restructure_equipment_pass(details, equipment_type):
    """
    Build the standard structure from parsed HTML details.
    """
    name = details["name"]
    text = details["text"]
    level = details["level"]  # Level field (0 if not specified)
    pfs = details["pfs"]  # PFS field (Standard, Limited, or Restricted)

    # Build stat block section
    sb = {
        "type": "stat_block",
        "subtype": equipment_type,
        "text": text,
        "sections": [],
        "level": level,  # Always include level
    }
    if "image" in details:
        sb["image"] = details["image"]

    # Build top-level structure
    top = {
        "name": name,
        "type": equipment_type,
        "sources": [],
        "sections": [sb],
        "pfs": pfs,  # Always include PFS
    }

    return top


def find_stat_block(struct):
    """Find the stat_block section in the structure."""
    for s in struct.get("sections", []):
        if s.get("type") == "stat_block":
            return s
    raise AssertionError(
        f"No stat_block found in equipment structure. Type: {struct.get('type', 'unknown')}"
    )


def section_pass(struct, config, debug=False):
    """Extract equipment-specific fields from the stat block HTML.

    Unified section pass for all equipment types. Type-specific behavior is
    driven by hook functions in the EQUIPMENT_TYPES config:
        - extract_stats_fxn: extracts stats from HTML into a dict
        - extract_abilities_fxn: extracts abilities (siege/vehicle only)
    Weapons use a dedicated flow for single/combination mode handling.
    """
    equipment_type = struct["type"]

    # Weapons have a fundamentally different flow (single vs combination modes)
    if equipment_type == "weapon":
        return _weapon_section_pass(struct, config, debug=debug)

    sb = find_stat_block(struct)
    text = sb["text"]
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    # --- Variant detection (generic/equipment only) ---
    h2_tags = bs.find_all("h2", class_="title")
    variant_h2s = [
        h2 for h2 in h2_tags if re.search(r"Item\s+\d+|Sharpness\s+Points?", get_text(h2))
    ]
    if variant_h2s:
        first_h2 = variant_h2s[0]
        main_parts = []
        for elem in bs.children:
            if elem == first_h2:
                break
            main_parts.append(str(elem))
        main_bs = BeautifulSoup("".join(main_parts), "html.parser")
    else:
        main_bs = bs

    # --- Shared extraction (all non-weapon types) ---
    _extract_traits(main_bs, sb)
    _extract_source(main_bs, struct)
    extract_pfs_note(main_bs, struct)

    # --- Type-specific stat extraction via hook ---
    extract_stats_fxn = config.get("extract_stats_fxn")
    if extract_stats_fxn:
        extract_stats_fxn(main_bs, sb, struct, config)
    else:
        # Default: generic stat extraction with field_destinations routing
        stats = {}
        group_subtype = (
            config.get("group_subtype") if "Group" in config["recognized_stats"] else None
        )
        _extract_stats_to_dict(
            main_bs, stats, config["recognized_stats"], struct["type"], group_subtype
        )
        unrec_links = stats.pop("_unrecognized_links", None)
        if unrec_links:
            if "links" not in sb:
                sb["links"] = []
            sb["links"].extend(unrec_links)
        _route_fields_to_destinations(sb, stats, config)

    # --- Intelligent item extraction (generic/equipment only) ---
    _extract_intelligent_item_section(main_bs, sb, debug=debug)

    # --- Type-specific ability extraction via hook ---
    extract_abilities_fxn = config.get("extract_abilities_fxn")
    if extract_abilities_fxn:
        extract_abilities_fxn(main_bs, sb, struct, config)

    # --- Variant processing ---
    if variant_h2s:
        variants = []
        for h2 in variant_h2s:
            variant_sb, _ = _parse_variant_section(
                h2,
                config,
                struct.get("name", ""),
                equipment_type=equipment_type,
                parent_level=sb.get("level"),
                debug=debug,
            )
            if variant_sb:
                variants.append(variant_sb)
            h2.decompose()
        if variants:
            sb["variants"] = variants

    # --- Shared tail (all non-weapon types) ---
    effective_bs = main_bs if variant_h2s else bs
    _remove_redundant_sections(effective_bs, struct.get("name", ""), debug=debug)
    _extract_alternate_link(effective_bs, struct)
    _extract_legacy_content_section(effective_bs, struct)
    _extract_base_material(effective_bs, sb, debug=debug)
    _extract_description(effective_bs, struct, debug=debug)
    _cleanup_stat_block(sb)


def _parse_variant_name_and_level(h2_tag):
    """Extract variant name and level from h2 tag.

    Handles formats like "Artisan's Tools<span>Item 0</span>" or
    "Artisan's Tools (Sterling)<span>Item 3</span>".

    Args:
        h2_tag: The h2 BeautifulSoup element

    Returns:
        Tuple of (name, level) where level is an int
    """
    h2_text = get_text(h2_tag).strip()
    level_match = re.search(r"Item\s+(\d+)", h2_text)
    level = int(level_match.group(1)) if level_match else None
    name = re.sub(r"\s*Item\s+\d+\+?\s*$", "", h2_text).strip()
    return name, level


def _collect_content_until_h2(start_tag):
    """Collect sibling content from a tag until the next h2 or end.

    Args:
        start_tag: Tag to start collecting from (exclusive)

    Returns:
        BeautifulSoup object containing the collected content
    """
    content_parts = []
    current = start_tag.next_sibling
    while current:
        if hasattr(current, "name") and current.name == "h2":
            break
        content_parts.append(str(current))
        current = current.next_sibling
    return BeautifulSoup("".join(content_parts), "html.parser")


def _parse_variant_section(
    h2_tag, config, parent_name, equipment_type="equipment", parent_level=None, debug=False
):
    """Parse a variant section (h2 and its content) into a variant stat block.

    Args:
        h2_tag: The h2 BeautifulSoup element marking the start of the variant
        config: Equipment type configuration
        parent_name: Name of the parent item (for debugging)
        equipment_type: The equipment type (armor, weapon, etc.) for subtype
        debug: Enable debug output

    Returns:
        Tuple of (variant stat block dict, link count removed from variant)
    """
    name, level = _parse_variant_name_and_level(h2_tag)
    bs = _collect_content_until_h2(h2_tag)

    # Create variant struct to hold source (like parent struct)
    variant_struct = {"sources": []}

    # Create variant stat block
    variant_sb = {
        "type": "stat_block",
        "subtype": equipment_type,
        "name": name,
    }
    if level is not None:
        variant_sb["level"] = level
    elif parent_level is not None:
        variant_sb["level"] = parent_level
    else:
        raise AssertionError(f"Variant '{name}' has no level and no parent level")

    # Extract source from variant (has its own source links)
    _extract_source(bs, variant_struct)

    # Fallback: some variant sources lack <a> links (just <b>Source</b> <i>text</i>).
    # _extract_source won't find these. Extract the bare source text and remove it
    # so it doesn't leak into the description.
    if not variant_struct["sources"]:
        source_tag = bs.find("b", string=lambda s: s and s.strip() == "Source")
        if source_tag:
            # Collect text until next <b> or <br>
            source_parts = []
            elements_to_remove = [source_tag]
            current = source_tag.next_sibling
            while current:
                if isinstance(current, Tag) and current.name in ("b", "br", "hr"):
                    break
                source_parts.append(get_text(current) if isinstance(current, Tag) else str(current))
                elements_to_remove.append(current)
                current = current.next_sibling
            source_text = "".join(source_parts).strip()
            if source_text:
                # Parse "Book Name pg. NNN" format
                page_match = re.match(r"(.+?)\s+pg\.\s+(\d+)", source_text)
                if page_match:
                    source_name = page_match.group(1).strip()
                    source_page = int(page_match.group(2))
                    variant_struct["sources"] = [
                        {
                            "type": "source",
                            "name": source_name,
                            "page": source_page,
                        }
                    ]
                else:
                    variant_struct["sources"] = [{"type": "source", "name": source_text}]
            for elem in elements_to_remove:
                if isinstance(elem, Tag):
                    elem.decompose()
                elif isinstance(elem, NavigableString):
                    elem.extract()

    # Extract traits from variant (some variants have their own traits like Uncommon)
    _extract_traits(bs, variant_sb)

    # Extract PFS Note from variant (some variants have their own PFS Notes)
    # Use variant_sb as the target since variants don't have a top-level pfs field
    variant_pfs_holder = {"pfs": "Standard"}
    extract_pfs_note(bs, variant_pfs_holder)
    if isinstance(variant_pfs_holder["pfs"], dict) and "note" in variant_pfs_holder["pfs"]:
        variant_sb["pfs"] = variant_pfs_holder["pfs"]

    # Extract inline intelligent item stats BEFORE stats extraction
    # (stats extraction would consume Perception/Skills/etc. bolds)
    _extract_inline_intelligent_item(bs, variant_sb)

    # Extract stats from variant content
    stats = {}
    recognized_stats = config["recognized_stats"]
    assert "recognized_stats" in config, "Config must contain 'recognized_stats'"
    group_subtype = config.get("group_subtype") if "Group" in recognized_stats else None
    _extract_stats_to_dict(bs, stats, recognized_stats, "equipment", group_subtype)
    # Move unrecognized links from stats dict to variant stat block links
    unrec_links = stats.pop("_unrecognized_links", None)
    if unrec_links:
        if "links" not in variant_sb:
            variant_sb["links"] = []
        variant_sb["links"].extend(unrec_links)

    # Route fields to their proper destinations
    _route_fields_to_destinations(variant_sb, stats, config)

    # Extract abilities (Activate, etc.) from variant content BEFORE extracting description
    # This removes ability content from bs so it doesn't end up in description text
    trait_links_converted = _extract_abilities_from_description(
        bs, variant_sb, equipment_type="equipment"
    )

    # Extract affliction from variant content (if present)
    affliction = None
    affliction_links = []
    if _has_affliction_pattern(bs):
        affliction, affliction_links = _extract_affliction(bs, name)
    if affliction:
        variant_sb["affliction"] = affliction

    # Remove <hr> tags from variant content (stat/description dividers)
    for hr in bs.find_all("hr"):
        hr.decompose()

    # Extract any remaining text as description (with links)
    # Get links from remaining content and unwrap them
    desc_links = get_links(bs, unwrap=True)
    remaining_text = clear_tags(str(bs), ["i", "b", "br"])
    remaining_text = _normalize_whitespace(remaining_text).strip()

    if remaining_text:
        variant_sb["text"] = remaining_text

    # Add links from description if any
    if desc_links:
        if "links" not in variant_sb:
            variant_sb["links"] = []
        variant_sb["links"].extend(desc_links)

    # Add sources to variant if extracted
    if variant_struct["sources"]:
        variant_sb["sources"] = variant_struct["sources"]

    # Normalize variant fields (bulk, hands->statistics, activate->ability)
    # Use the normalizer if this is equipment type
    normalize_func = config.get("normalize_fields")
    if normalize_func:
        trait_links_converted += normalize_func(variant_sb) or 0

    return variant_sb, trait_links_converted


def _route_fields_to_destinations(sb, stats, config):
    """Route extracted fields to their proper destinations in the stat block.

    Uses 'field_destinations' config if available, otherwise falls back to
    'shared_fields' and 'nested_fields' for backward compatibility.

    Destinations:
        None: stat_block top level
        'statistics': sb['statistics']
        'offense': sb['offense']
        'defense': sb['defense']
    """
    field_destinations = config.get("field_destinations")

    if field_destinations:
        # New routing system
        for field, value in stats.items():
            dest = field_destinations.get(field)
            if dest is None:
                # Top level of stat_block
                sb[field] = value
            else:
                # Nested destination (statistics, offense, defense)
                if dest not in sb:
                    sb[dest] = {"type": "stat_block_section", "subtype": dest}
                sb[dest][field] = value
    else:
        # Legacy routing for backward compatibility
        shared_fields = config.get("shared_fields", [])
        nested_fields = config.get("nested_fields", [])
        equipment_type = config.get("output_subdir", "equipment")

        # Add shared fields to top level
        for field in shared_fields:
            if field in stats:
                sb[field] = stats[field]

        # Add nested fields to equipment-specific object
        nested_obj = {}
        for field in nested_fields:
            if field in stats:
                nested_obj[field] = stats[field]

        if nested_obj:
            sb[equipment_type] = nested_obj


# Known fields in intelligent item stat blocks (between two <hr> tags).
# Assert on any unknown field for strategic fragility.
INTELLIGENT_ITEM_FIELDS = {
    "Perception",
    "Communication",
    "Skills",
    "Int",
    "Wis",
    "Cha",
    "Will",
}


def _extract_intelligent_item_section(bs, sb, debug=False):
    """Extract intelligent item stat block section if present.

    Intelligent items have a creature-like stat block between two <hr> tags with
    fields: Perception, Communication, Skills, Int/Wis/Cha, Will. This function
    detects the pattern, extracts it as a structured section, and removes it from
    the soup so <hr> tags don't leak into description text.

    Returns 0 (no link accounting adjustment needed — links in sections are
    counted by _count_links_in_json's recursive walk).
    """
    # Find first <hr> tag
    first_hr = bs.find("hr")
    if not first_hr:
        return 0

    # Check if first bold tag after the <hr> is "Perception"
    first_bold_after_hr = None
    for sibling in first_hr.next_siblings:
        if isinstance(sibling, Tag) and sibling.name == "b":
            first_bold_after_hr = sibling
            break

    if not first_bold_after_hr or first_bold_after_hr.get_text().strip() != "Perception":
        return 0

    if debug:
        sys.stderr.write("DEBUG: Detected intelligent item section\n")

    # Find second <hr> (end of intelligent item section)
    second_hr = None
    for sibling in first_hr.next_siblings:
        if isinstance(sibling, Tag) and sibling.name == "hr":
            second_hr = sibling
            break

    # Collect all elements between first_hr and second_hr (exclusive)
    elements_to_extract = []
    elem = first_hr.next_sibling
    while elem is not None and elem != second_hr:
        elements_to_extract.append(elem)
        elem = elem.next_sibling

    # Build HTML from collected elements for parsing
    section_html = "".join(str(e) for e in elements_to_extract)
    section_soup = BeautifulSoup(section_html, "html.parser")

    # Parse fields: iterate through children, each <b> starts a new field
    fields = {}
    current_label = None
    current_value_parts = []

    for child in section_soup.children:
        if isinstance(child, Tag) and child.name == "b":
            # Save previous field
            if current_label is not None:
                value_html = "".join(current_value_parts).strip().strip(",").strip()
                fields[current_label] = value_html
            current_label = child.get_text().strip()
            assert (
                current_label in INTELLIGENT_ITEM_FIELDS
            ), f"Unknown intelligent item field: '{current_label}'"
            current_value_parts = []
        elif isinstance(child, Tag) and child.name == "br":
            continue  # Skip line breaks
        elif current_label is not None:
            current_value_parts.append(str(child))

    # Save last field
    if current_label is not None:
        value_html = "".join(current_value_parts).strip().strip(",").strip()
        fields[current_label] = value_html

    # Extract links from entire section
    _, links = extract_links(section_html)

    # Build section dict
    field_map = {
        "Perception": "perception",
        "Communication": "communication",
        "Skills": "skills",
        "Int": "int_mod",
        "Wis": "wis_mod",
        "Cha": "cha_mod",
        "Will": "will",
    }

    section = {
        "type": "stat_block_section",
        "subtype": "intelligent_item",
    }

    for label, key in field_map.items():
        if label in fields:
            # Get text-only value (strip HTML, normalize whitespace)
            value_soup = BeautifulSoup(fields[label], "html.parser")
            text = re.sub(r"\s+", " ", value_soup.get_text()).strip()
            section[key] = text

    if links:
        section["links"] = links

    # Add as direct property of stat block (like statistics, defense, offense)
    sb["intelligent_item"] = section

    if debug:
        sys.stderr.write(
            f"DEBUG: Intelligent item section: {list(section.keys())}, " f"{len(links)} links\n"
        )

    # Remove extracted content from soup: first <hr> + all elements up to second <hr>
    for elem in elements_to_extract:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()
    first_hr.decompose()

    return 0


def _collect_bold_field_values(bs, field_names, start_label):
    """Collect field values from consecutive bold tags in soup.

    Walks bs.children starting from the bold matching start_label, collecting
    label-value pairs for labels in field_names. Stops when a bold with a label
    NOT in field_names is encountered.

    Args:
        bs: BeautifulSoup object to scan
        field_names: Set of valid bold label strings to collect
        start_label: The label that triggers collection (must be in field_names)

    Returns:
        Tuple of (fields_dict, elements_to_remove) where fields_dict maps
        label strings to their HTML value strings, and elements_to_remove
        is a list of soup elements that were consumed.
    """
    fields = {}
    current_label = None
    current_value_parts = []
    elements_to_remove = []
    collecting = False

    for child in list(bs.children):
        if isinstance(child, Tag) and child.name == "b":
            label = child.get_text().strip()
            if label == start_label:
                collecting = True
            if collecting and label in field_names:
                # Save previous field
                if current_label is not None:
                    value_html = "".join(current_value_parts).strip().strip(",").strip()
                    fields[current_label] = value_html
                current_label = label
                current_value_parts = []
                elements_to_remove.append(child)
                continue
            elif collecting and label not in field_names:
                # Hit a non-matching bold — stop
                if current_label is not None:
                    value_html = "".join(current_value_parts).strip().strip(",").strip()
                    fields[current_label] = value_html
                break
        elif collecting:
            if isinstance(child, Tag) and child.name == "br":
                elements_to_remove.append(child)
                continue
            elif current_label is not None:
                current_value_parts.append(str(child))
                elements_to_remove.append(child)

    # Save last field if we ended without hitting a non-matching bold
    if current_label is not None and current_label not in fields:
        value_html = "".join(current_value_parts).strip().strip(",").strip()
        fields[current_label] = value_html

    return fields, elements_to_remove


def _extract_inline_intelligent_item(bs, sb):
    """Extract intelligent item stats from inline bold tags (no <hr> required).

    Used for variant sections (e.g., Briar's Sharpness Point tiers) where
    intelligent item stats appear inline rather than between <hr> tags.

    Detects <b>Perception</b> followed by other INTELLIGENT_ITEM_FIELDS bolds,
    extracts them into a structured intelligent_item object, and removes them
    from the soup.
    """
    # Check if there's a <b>Perception</b> tag
    perception_bold = None
    for b in bs.find_all("b"):
        if b.get_text().strip() == "Perception":
            perception_bold = b
            break

    if not perception_bold:
        return

    # Verify at least one more intelligent item field follows
    has_other = False
    for b in perception_bold.find_next_siblings("b"):
        if b.get_text().strip() in INTELLIGENT_ITEM_FIELDS:
            has_other = True
            break
        if b.get_text().strip() not in INTELLIGENT_ITEM_FIELDS:
            break

    if not has_other:
        return

    fields, elements_to_remove = _collect_bold_field_values(
        bs, INTELLIGENT_ITEM_FIELDS, "Perception"
    )

    if not fields:
        return

    # Extract links from collected elements
    section_html = "".join(str(e) for e in elements_to_remove)
    _, links = extract_links(section_html)

    # Build section dict (same structure as _extract_intelligent_item_section)
    field_map = {
        "Perception": "perception",
        "Communication": "communication",
        "Skills": "skills",
        "Int": "int_mod",
        "Wis": "wis_mod",
        "Cha": "cha_mod",
        "Will": "will",
    }

    section = {
        "type": "stat_block_section",
        "subtype": "intelligent_item",
    }

    for label, key in field_map.items():
        if label in fields:
            value_soup = BeautifulSoup(fields[label], "html.parser")
            text = re.sub(r"\s+", " ", value_soup.get_text()).strip()
            section[key] = text

    if links:
        section["links"] = links

    sb["intelligent_item"] = section

    # Remove extracted elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()


def _extract_siege_weapon_stats_hook(bs, sb, struct, config):
    """Hook: extract siege weapon stats and route to nested object."""
    stats = {}
    _extract_siege_weapon_stats(bs, stats, config["recognized_stats"], struct["type"])
    shared_fields = config.get("shared_fields", [])
    nested_fields = config.get("nested_fields", [])
    for field in shared_fields:
        if field in stats:
            sb[field] = stats[field]
    nested_obj = {}
    for field in nested_fields:
        if field in stats:
            nested_obj[field] = stats[field]
    if nested_obj:
        sb["siege_weapon"] = nested_obj


def _extract_vehicle_stats_hook(bs, sb, struct, config):
    """Hook: extract vehicle stats and route to nested object."""
    stats = {}
    _extract_vehicle_stats(bs, stats, config["recognized_stats"], struct["type"])
    shared_fields = config.get("shared_fields", [])
    nested_fields = config.get("nested_fields", [])
    for field in shared_fields:
        if field in stats:
            sb[field] = stats[field]
    nested_obj = {}
    for field in nested_fields:
        if field in stats:
            nested_obj[field] = stats[field]
    if nested_obj:
        sb["vehicle"] = nested_obj


def _extract_abilities_hook(bs, sb, struct, config):
    """Hook: extract action abilities (siege weapons, vehicles)."""
    # _extract_abilities returns (abilities, trait_links_converted_count).
    # The count was used by the removed link accounting system; v2 does not use it.
    abilities, _ = _extract_abilities(bs, struct["type"], config["recognized_stats"])
    if abilities:
        sb["abilities"] = abilities


def _weapon_section_pass(struct, config, debug=False):
    """Weapon-specific section pass that handles melee/ranged modes.

    Weapons have a fundamentally different flow from other equipment types
    because of single vs. combination weapon mode handling.
    """
    sb = find_stat_block(struct)
    text = sb["text"]
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    # Check if this is a combination weapon (has <h2> mode headers for Melee/Ranged)
    h2_tags = bs.find_all("h2", class_="title")
    mode_headers = [h2 for h2 in h2_tags if get_text(h2).strip().lower() in ["melee", "ranged"]]

    if len(mode_headers) > 0:
        _extract_combination_weapon(bs, sb, struct, config)
    else:
        _extract_single_mode_weapon(bs, sb, struct, config)

    _remove_redundant_sections(bs, struct.get("name", ""), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)


def _extract_vehicle_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract vehicle stats which span across multiple <hr> tags.

    Vehicles have stats similar to siege weapons but different fields.
    Removes extracted stat elements from the soup so they don't leak into
    description text.
    """
    # Find all bold tags that are stats (not action names)
    # Vehicles typically don't have action names like siege weapons
    action_names = ["Effect", "Requirements"]  # Keep minimal list just in case

    elements_to_remove = []

    for bold_tag in bs.find_all("b"):
        label = bold_tag.get_text().strip()

        # Skip empty labels
        if not label:
            continue

        # Skip action names (they're handled separately)
        if label in action_names:
            continue

        # Fail fast if we encounter an unknown label
        if label not in recognized_stats:
            # Check if this might be part of the description
            continue

        # Skip labels we handle elsewhere (like Source)
        field_name = recognized_stats[label]
        if field_name is None:
            continue

        # Extract the value - preserve HTML for fields with links
        preserve_html = label in [
            "Immunities",
            "Resistances",
            "Weaknesses",
            "Piloting Check",
            "Speed",
        ]
        value = _extract_stat_value(bold_tag, preserve_html=preserve_html)

        if value:
            stats_dict[field_name] = value

        # Mark bold tag and its value siblings for removal
        elements_to_remove.append(bold_tag)
        current = bold_tag.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                break
            elements_to_remove.append(current)
            current = current.next_sibling

    # Remove extracted stat elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()


def _extract_siege_weapon_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract siege weapon stats which span across multiple <hr> tags.

    Siege weapons have stats before actions, which appear after description.
    """
    # Find all bold tags that are stats (not action/ability names in description area)
    action_names = [
        "Aim",
        "Load",
        "Launch",
        "Ram",
        "Effect",
        "Requirements",
        "Trigger",
        "Activate Drill",
        "Anesthetic Surge",
        "Quick Aim",
        "Reload Hopper",
        "Fire",
        "Critical Success",
        "Success",
        "Failure",
        "Critical Failure",
        "High Dilution",
        "Medium Dilution",
        "Low Dilution",
    ]

    elements_to_remove = []

    for bold_tag in bs.find_all("b"):
        label = bold_tag.get_text().strip()

        # Skip empty labels
        if not label:
            continue

        # Skip action names (they're handled separately)
        if label in action_names:
            continue

        # Fail fast if we encounter an unknown label
        if label not in recognized_stats:
            raise AssertionError(
                f"Unknown siege_weapon stat label: '{label}'. Add it to EQUIPMENT_TYPES['siege_weapon']['recognized_stats']."
            )

        # Skip labels we handle elsewhere (like Source)
        field_name = recognized_stats[label]
        if field_name is None:
            continue

        # Extract the value - preserve HTML for fields with links
        preserve_html = label in ("Immunities", "Ammunition")
        value = _extract_stat_value(bold_tag, preserve_html=preserve_html)
        if value:
            stats_dict[field_name] = value

        # Mark elements for removal: the bold tag and content until next <b>, <br>, or <hr>
        elements_to_remove.append(bold_tag)
        current = bold_tag.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                break
            elements_to_remove.append(current)
            current = current.next_sibling

    # Remove extracted stat elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()


def _extract_traits_from_parentheses(text):
    """Extract trait names from leading parentheses in ability text.

    Format: "(trait1, trait2, ...) rest of text"
    Returns: (trait_names_list, remaining_text)

    Example: "(manipulate, attack) deals damage" -> (["manipulate", "attack"], "deals damage")

    Note: Some traits include additional data (e.g., "range increment 100 feet").
    These are kept as-is and will be looked up in the trait database.
    """
    text = text.strip()
    if text.startswith("("):
        close_paren = text.find(")")
        if close_paren > 0:
            traits_text = text[1:close_paren].strip()
            remaining = text[close_paren + 1 :].strip()

            # Split by comma and clean up each trait name
            trait_names = [t.strip() for t in traits_text.split(",") if t.strip()]
            return trait_names, remaining

    return [], text


def _parse_siege_weapon_launch(text):
    """Parse Launch action text for siege weapons.

    Launch format: (traits) damage, target, save[. or ;] additional text
    Example: "(manipulate) 8d6 fire plus 1d6 persistent fire, 60-foot line or 30-foot cone, DC 23 Reflex. Text."

    Returns tuple: (damage, target, save_dc_obj, remaining_text)
    """
    # Strip leading traits if present (text in parentheses at start)
    # Traits appear as: (attack, manipulate, range increment 120 feet)
    trait_names, text = _extract_traits_from_parentheses(text)

    # Look for "DC \d+ [basic] \w+" pattern (basic is an optional modifier before save type)
    dc_pattern = r"(DC\s+\d+\s+(?:basic\s+)?\w+)"
    match = re.search(dc_pattern, text)
    if not match:
        # No save found - just return the text as-is
        return None, None, None, text

    # Find where the DC ends
    dc_end = match.end()
    text[:dc_end].strip()
    after_dc = text[dc_end:].strip()

    # Split after_dc by ; or . to separate remaining text
    remaining_text = ""
    if after_dc.startswith(";") or after_dc.startswith("."):
        remaining_text = after_dc[1:].strip()
        after_dc = ""
    elif ";" in after_dc:
        parts = after_dc.split(";", 1)
        # The save might have extra text before the semicolon
        if parts[0].strip():
            # This means there's extra text attached to the save - HTML needs fixing
            raise AssertionError(
                f"Save DC has extra text before semicolon - HTML needs fixing. Text: '{text}'"
            )
        remaining_text = parts[1].strip()
    elif "." in after_dc:
        # Period is used as separator (HTML error, but we'll handle it)
        parts = after_dc.split(".", 1)
        if parts[0].strip():
            # Extra text before period
            raise AssertionError(
                f"Save DC has extra text before period - HTML needs fixing. Text: '{text}'"
            )
        remaining_text = parts[1].strip()
    else:
        # No separator found - save is at the end
        if after_dc.strip():
            # There's extra text but no separator - needs fixing
            raise AssertionError(
                f"Save DC has extra text but no separator - HTML needs fixing. Text: '{text}'"
            )

    # Parse the DC text
    dc_text = match.group(1)

    # Get everything before the DC
    text_before_save = text[: match.start()].strip()

    # Remove trailing comma if present
    if text_before_save.endswith(","):
        text_before_save = text_before_save[:-1].strip()

    # Split by commas to get damage and target
    parts = [p.strip() for p in text_before_save.split(",")]

    # Some Launch actions don't have damage, just target (e.g., ID_27, ID_28)
    if len(parts) == 1:
        # Just target, no damage
        damage = None
        target = parts[0]
    elif len(parts) == 2:
        # damage, target
        damage = parts[0]
        target = parts[1]
    else:
        # Unexpected format
        raise AssertionError(
            f"Launch should have damage, target (or just target) before save. Got {len(parts)} parts. Text: '{text}'"
        )

    # Parse the DC using the universal function
    save_dc = universal_handle_save_dc(dc_text)

    return damage, target, save_dc, remaining_text


def _is_ability_bold_tag(
    bold_tag,
    main_abilities,
    stat_labels,
    result_fields,
    equipment_type,
    preview_char_limit=30,
    min_length=15,
):
    """Check if a bold tag represents an ability name.

    Uses three detection strategies:
    1. Known ability name (in main_abilities list)
    2. Action icon immediately following the bold tag
    3. Vehicle heuristic: substantial descriptive text follows the bold tag

    Returns the ability name string if this is an ability, None otherwise.
    """
    ability_name = get_text(bold_tag).strip()

    if ability_name in stat_labels:
        return None

    # Strategy 1: Known ability name
    is_main_ability = ability_name in main_abilities

    # Strategy 2: Action icon follows
    has_action_icon = False
    next_sib = bold_tag.next_sibling
    while next_sib and isinstance(next_sib, NavigableString) and next_sib.strip() == "":
        next_sib = next_sib.next_sibling
    if (
        isinstance(next_sib, Tag)
        and next_sib.name == "span"
        and "action" in next_sib.get("class", [])
    ):
        has_action_icon = True

    # Strategy 3: Vehicle content-length heuristic
    is_vehicle_ability = False
    if equipment_type == "vehicle" and ability_name not in result_fields:
        content_preview = []
        preview_sib = bold_tag.next_sibling
        char_count = 0
        while preview_sib and char_count < preview_char_limit:
            if isinstance(preview_sib, NavigableString):
                content_preview.append(str(preview_sib))
                char_count += len(str(preview_sib).strip())
            elif isinstance(preview_sib, Tag):
                if preview_sib.name in ("b", "hr", "h2"):
                    break
                content_preview.append(preview_sib.get_text())
                char_count += len(preview_sib.get_text().strip())
            preview_sib = preview_sib.next_sibling if hasattr(preview_sib, "next_sibling") else None

        preview_text = "".join(content_preview).strip()
        if len(preview_text) > min_length:
            is_vehicle_ability = True

    if is_main_ability or has_action_icon or is_vehicle_ability:
        return ability_name
    return None


def _collect_ability_content(bold_tag, addon_names, processed_bolds):
    """Walk siblings after a bold tag to collect ability content HTML parts.

    Stops at <br>, <hr>, or <h2> tags. Marks addon bold tags (Requirements, Effect, etc.)
    as processed so they don't create separate abilities.

    Returns (content_parts, resume_sibling) where resume_sibling is the position
    to continue from for result field extraction.
    """
    content_parts = []
    current = bold_tag.next_sibling

    while current:
        if isinstance(current, Tag) and current.name in ("hr", "h2", "div"):
            break
        if isinstance(current, Tag) and current.name == "br":
            break

        # If this is a <b> tag, check if it's an addon (part of current ability)
        # or a new ability boundary
        if isinstance(current, Tag) and current.name == "b":
            tag_text = get_text(current).strip()
            if tag_text in addon_names:
                processed_bolds.add(current)
            else:
                # Non-addon bold tag = start of a new ability, stop here
                break

        if isinstance(current, NavigableString | Tag):
            content_parts.append(str(current))

        current = current.next_sibling

    return content_parts, current


def _extract_addons_from_soup(desc_soup, addon_names):
    """Extract addon fields (Requirements, Effect, etc.) from description soup.

    Walks soup children for bold addon labels, extracts their content,
    strips trailing semicolons, and removes the addon nodes from the soup.

    Returns dict mapping addon field names to their content lists.
    """
    addons = {}
    current_addon = None
    nodes_to_remove = []

    for child in list(desc_soup.children):
        if isinstance(child, Tag) and child.name == "b":
            addon_name = get_text(child).strip()
            if addon_name in addon_names:
                current_addon = addon_name
                if current_addon == "Requirements":
                    current_addon = "Requirement"
                nodes_to_remove.append(child)
        elif current_addon:
            addon_text = str(child)
            if addon_text.strip().endswith(";"):
                addon_text = addon_text.rstrip()[:-1]
            addons.setdefault(current_addon.lower().replace(" ", "_"), []).append(addon_text)
            nodes_to_remove.append(child)

    for node in nodes_to_remove:
        if hasattr(node, "extract"):
            node.extract()

    return addons


def _classify_links(links):
    """Sort links into trait, rules, and other buckets.

    Returns (trait_links, rules_links, other_links).
    """
    trait_links = []
    rules_links = []
    other_links = []

    for link in links:
        game_obj = link.get("game-obj")
        if game_obj == "Traits":
            trait_links.append(link)
        elif game_obj == "Rules":
            rules_links.append(link)
        else:
            other_links.append(link)

    return trait_links, rules_links, other_links


def _parse_trait_parentheses(ability_text, trait_links, rules_links, other_links, all_links):
    """Parse trait names from opening parentheses in ability text.

    If ability_text starts with '(', extracts linked and unlinked trait names
    from the parenthesized section. Trait links in body text are moved to other_links.

    Returns (traits, cleaned_text, converted_count) where:
    - traits: list of trait objects built from extracted names
    - cleaned_text: ability text with parenthesized traits removed
    - converted_count: number of links converted to trait objects
    """
    traits_to_convert = []
    trait_links_in_body = []
    unlinked_trait_names = []
    non_trait_links_in_parens = []

    if ability_text.startswith("("):
        close_paren = ability_text.find(")")
        assert close_paren > 0, f"Unclosed parenthesis in ability text: {ability_text[:100]}"

        parens_content = ability_text[1:close_paren].strip()
        remaining = ability_text[close_paren + 1 :].strip()

        # Check which trait links are actually in the parentheses
        for trait_link in trait_links:
            trait_name = trait_link["name"]
            if trait_name.lower() in parens_content.lower():
                traits_to_convert.append(trait_link)
                parens_content = re.sub(
                    re.escape(trait_name), "", parens_content, flags=re.IGNORECASE
                )
            else:
                trait_links_in_body.append(trait_link)

        # Remove Rules links from parentheses content
        for rules_link in rules_links:
            link_text = rules_link["name"]
            parens_content = re.sub(re.escape(link_text), "", parens_content, flags=re.IGNORECASE)

        # Handle non-Traits links in parentheses (e.g., links to MonsterAbilities, Domains)
        for link in all_links:
            game_obj = link.get("game-obj", "")
            if game_obj and game_obj not in ("Traits", "Rules"):
                link_name = link["name"]
                if link_name.lower() in parens_content.lower():
                    traits_to_convert.append(link)
                    non_trait_links_in_parens.append(link)
                    parens_content = re.sub(
                        re.escape(link_name), "", parens_content, flags=re.IGNORECASE
                    )

        # Remove consumed non-Traits links from other_links
        for consumed_link in non_trait_links_in_parens:
            if consumed_link in other_links:
                other_links.remove(consumed_link)

        # Handle remaining text as unlinked trait names
        parens_content = parens_content.replace(",", "").strip()
        if parens_content:
            potential_traits = parens_content.split()
            for pt in potential_traits:
                pt = pt.strip()
                if pt and not pt.isdigit():
                    unlinked_trait_names.append(pt)

        ability_text = remaining
        other_links.extend(rules_links)
    else:
        # No opening parentheses - all trait links are in body text
        trait_links_in_body = trait_links
        other_links.extend(rules_links)

    # Add trait links from body text to other_links
    other_links.extend(trait_links_in_body)

    # Build trait objects
    trait_names = [tl["name"] for tl in traits_to_convert] + unlinked_trait_names
    traits = build_objects("stat_block_section", "trait", trait_names)

    return traits, ability_text, len(traits_to_convert)


def _parse_ability_description(content_parts, ability, addon_names):
    """Parse ability description from collected HTML content parts.

    Orchestrates action type extraction, link classification, addon extraction,
    trait parsing, and sets fields on the ability dict.

    Returns the number of trait links converted to trait objects.
    """
    combined_html = "".join(content_parts).strip()
    action_soup = BeautifulSoup(combined_html, "html.parser")

    description, action_type = extract_action_type(str(action_soup))

    if description:
        desc_soup = BeautifulSoup(description, "html.parser")
        links = get_links(desc_soup, unwrap=True)

        addons = _extract_addons_from_soup(desc_soup, addon_names)
        trait_links, rules_links, other_links = _classify_links(links)
        ability_text = _normalize_whitespace(str(desc_soup))

        traits, ability_text, converted_count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, links
        )

        if traits:
            ability["traits"] = traits

        # Set addon fields
        for k, v in addons.items():
            if k == "range":
                assert len(v) == 1, f"Malformed range: {v}"
                ability["range"] = universal_handle_range(v[0])
            else:
                ability[k] = clear_garbage(v)

        if ability_text:
            ability["text"] = ability_text

        if other_links:
            ability["links"] = other_links
    else:
        converted_count = 0

    if action_type:
        ability["action_type"] = action_type

    return converted_count


def _extract_result_fields(current, ability, result_fields, processed_bolds):
    """Extract result fields (Success, Failure, etc.) after the main ability text.

    Walks from the resume position (after <br>) looking for bold result field labels
    and their associated content. Sets fields on the ability dict and merges links.
    """
    while current:
        if isinstance(current, Tag) and current.name == "br":
            current = current.next_sibling
            continue
        if isinstance(current, NavigableString) and current.strip() == "":
            current = current.next_sibling
            continue

        if isinstance(current, Tag) and current.name == "b":
            field_name = get_text(current).strip()
            if field_name in result_fields:
                processed_bolds.add(current)

                field_parts = []
                field_current = current.next_sibling

                while field_current:
                    if isinstance(field_current, Tag) and field_current.name in (
                        "b",
                        "hr",
                        "h2",
                        "br",
                    ):
                        break
                    if isinstance(field_current, NavigableString | Tag):
                        field_parts.append(str(field_current))
                    field_current = field_current.next_sibling

                if field_parts:
                    field_html = "".join(field_parts).strip()
                    field_soup = BeautifulSoup(field_html, "html.parser")
                    field_links = get_links(field_soup, unwrap=True)

                    schema_field_name = field_name.lower().replace(" ", "_")
                    ability[schema_field_name] = _normalize_whitespace(str(field_soup))

                    if field_links:
                        if "links" not in ability:
                            ability["links"] = []
                        ability["links"].extend(field_links)

                current = field_current
                continue
            else:
                break

        break


def _extract_abilities(bs, equipment_type="siege_weapon", recognized_stats=None):
    """Extract abilities from equipment HTML.

    Abilities appear as bold titles followed by text and possibly action icons:
    <b>Aim</b> <span class="action" title="Two Actions">[two-actions]</span> action text<br>

    For vehicles, abilities may not have action icons but are distinguished from stats
    by having longer descriptive text with traits in parentheses.

    Some abilities have result fields (Success, Failure, Critical Success, Critical Failure)
    that appear after the main ability text, separated by <br> tags. These are extracted
    as fields on the ability object, not as separate sections.

    Args:
        bs: BeautifulSoup object containing equipment HTML
        equipment_type: Type of equipment (siege_weapon, vehicle, etc.)
        recognized_stats: Dict of recognized stat labels for this equipment type

    Returns:
        List of ability objects matching the ability schema, or None if no abilities found.
    """
    main_abilities = [
        "Aim",
        "Load",
        "Launch",
        "Fire",
        "Ram",
        "Effect",
        "Requirements",
        "Activate Drill",
    ]
    result_fields = ["Success", "Failure", "Critical Success", "Critical Failure"]
    addon_names = constants.CREATURE_ABILITY_ADDON_NAMES

    processed_bolds = set()
    abilities = []
    trait_links_converted_count = 0

    stat_labels = (
        set(recognized_stats.keys()) if recognized_stats and equipment_type == "vehicle" else set()
    )

    for bold_tag in bs.find_all("b"):
        if bold_tag in processed_bolds:
            continue

        ability_name = _is_ability_bold_tag(
            bold_tag, main_abilities, stat_labels, result_fields, equipment_type
        )
        if ability_name is None:
            continue

        ability = {
            "type": "stat_block_section",
            "subtype": "ability",
            "name": ability_name,
            "ability_type": "offensive",
        }

        content_parts, current = _collect_ability_content(bold_tag, addon_names, processed_bolds)

        if content_parts:
            trait_links_converted_count += _parse_ability_description(
                content_parts, ability, addon_names
            )

        # For siege weapon Launch actions, parse structured damage, target, and save
        if equipment_type == "siege_weapon" and ability_name == "Launch" and "text" in ability:
            try:
                damage, target, save_dc, remaining_text = _parse_siege_weapon_launch(
                    ability["text"]
                )
                if damage:
                    ability["damage"] = damage
                if target:
                    ability["target"] = target
                if save_dc:
                    ability["saving_throw"] = save_dc
                if remaining_text:
                    ability["text"] = remaining_text
                else:
                    del ability["text"]
            except AssertionError as e:
                raise AssertionError(f"Launch action parsing failed: {e}") from e

        _extract_result_fields(current, ability, result_fields, processed_bolds)

        has_content = (
            "text" in ability
            or "action_type" in ability
            or "effect" in ability
            or "requirement" in ability
        )
        if has_content:
            abilities.append(ability)

    return (abilities if abilities else None), trait_links_converted_count


def _extract_single_mode_weapon(bs, sb, struct, config):
    """Extract stats for a regular (non-combination) weapon."""

    # Extract shared fields (traits, source, PFS note)
    _extract_traits(bs, sb)
    _extract_source(bs, struct)
    extract_pfs_note(bs, struct)

    # Extract all stats
    stats = {}
    _extract_weapon_stats(bs, stats, config)

    # Separate fields by nesting level
    shared_fields = config.get("shared_fields", [])
    weapon_fields = config.get("weapon_fields", [])
    mode_fields = config.get("mode_fields", [])

    # Extract shared fields to stat_block level
    for field in shared_fields:
        if field in stats:
            sb[field] = stats[field]

    # Create weapon object
    weapon_obj = {}

    # Add weapon-level fields (but skip fields that are also mode fields - they go to mode level)
    for field in weapon_fields:
        if field in stats and field not in mode_fields:
            weapon_obj[field] = stats[field]

    # Determine if this is melee or ranged based on weapon_type
    weapon_type = stats.get("weapon_type", "Melee")
    mode_key = "ranged" if weapon_type == "Ranged" else "melee"

    # Put mode-specific fields into the appropriate mode object
    mode_obj = {"type": "stat_block_section", "subtype": mode_key}
    for field in mode_fields:
        if field in stats:
            mode_obj[field] = stats[field]

    weapon_obj[mode_key] = mode_obj

    sb["weapon"] = weapon_obj


def _extract_combination_weapon(bs, sb, struct, config):
    """Extract stats for a combination weapon with multiple modes."""
    # Extract traits and source that apply to whole weapon
    # Traits before first <h2> are shared
    first_h2 = bs.find("h2", class_="title")
    if first_h2:
        # Extract shared traits (before first h2)
        # Use trait_class_matcher to match trait, traituncommon, traitrare, etc.
        shared_traits = []
        for span in bs.find_all("span", class_=_trait_class_matcher):
            if first_h2.sourceline and span.sourceline and span.sourceline < first_h2.sourceline:
                # This trait is before the h2, so it's shared
                shared_traits.append(span)

        # Process shared traits
        if shared_traits:
            traits = []
            for span in shared_traits:
                children = [c for c in span.children if hasattr(c, "name") and c.name is not None]
                if len(children) == 1 and children[0].name == "a":
                    link = children[0]
                    name = get_text(link).replace(" Trait", "").strip()
                    trait_class = "".join(span.get("class", ["trait"]))
                    if trait_class != "trait":
                        trait_class = trait_class.replace("trait", "")
                    _, link_obj = extract_link(link)
                    trait = {
                        "name": name,
                        "classes": [trait_class if trait_class != "trait" else "trait"],
                        "type": "stat_block_section",
                        "subtype": "trait",
                        "link": link_obj,
                    }
                    traits.append(trait)
            if traits:
                sb["traits"] = traits

        # Remove extracted shared trait spans from soup
        for span in shared_traits:
            span.decompose()

    _extract_source(bs, struct)
    extract_pfs_note(bs, struct)

    # Extract fields before first h2 (both shared and weapon-level)
    shared_fields = config.get("shared_fields", [])
    weapon_fields = config.get("weapon_fields", [])
    all_weapon_stats = {}
    elements_to_remove = []
    hr = bs.find("hr")
    for tag in bs.find_all("b"):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        if (
            first_h2
            and tag.sourceline
            and first_h2.sourceline
            and tag.sourceline >= first_h2.sourceline
        ):
            break

        label = tag.get_text().strip()
        if not label:
            continue

        # FAIL FAST: Assert all labels are recognized
        assert (
            label in config["recognized_stats"]
        ), f"Unknown weapon stat label in combination weapon: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

        field_name = config["recognized_stats"][label]
        if field_name is None:  # Intentionally skipped (like Source)
            continue

        # Extract both shared and weapon-level fields before h2
        if field_name in shared_fields or field_name in weapon_fields:
            if label == "Group":
                value = _extract_group_value(tag, config["group_subtype"])
            elif label == "Favored Weapon":
                # Extract with HTML preserved to capture deity links
                value = _extract_stat_value(tag, preserve_html=True)
            elif label == "Ammunition":
                # Extract with HTML preserved to capture ammunition links
                value = _extract_stat_value(tag, preserve_html=True)
            else:
                value = _extract_stat_value(tag)
            if value:
                all_weapon_stats[field_name] = value

        # Mark elements for removal: the bold tag and content until next <b>, <br>, or <hr>
        elements_to_remove.append(tag)
        current = tag.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                break
            elements_to_remove.append(current)
            current = current.next_sibling

    # Remove extracted stat elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()

    # Add shared fields to stat block top level
    for field in shared_fields:
        if field in all_weapon_stats:
            sb[field] = all_weapon_stats[field]

    # Create weapon object with weapon-level fields
    weapon_obj = {}
    for field in weapon_fields:
        if field in all_weapon_stats:
            weapon_obj[field] = all_weapon_stats[field]

    # Extract mode-specific sections
    h2_tags = bs.find_all("h2", class_="title")
    for h2 in h2_tags:
        mode_name = get_text(h2).strip().lower()
        if mode_name not in ["melee", "ranged"]:
            continue

        # Extract stats for this mode (between this h2 and next h2 or hr)
        mode_stats = {}
        mode_traits = []

        # Find mode-specific traits (after this h2, before next h2 or hr)
        # Use trait_class_matcher to match trait, traituncommon, traitrare, etc.
        next_h2 = h2.find_next_sibling("h2", class_="title")
        trait_spans_to_remove = []
        for span in bs.find_all("span", class_=_trait_class_matcher):
            if not span.sourceline or not h2.sourceline:
                continue
            if span.sourceline <= h2.sourceline:
                continue
            if next_h2 and next_h2.sourceline and span.sourceline >= next_h2.sourceline:
                continue

            children = [c for c in span.children if hasattr(c, "name") and c.name is not None]
            if len(children) == 1 and children[0].name == "a":
                link = children[0]
                name = get_text(link).replace(" Trait", "").strip()
                trait_class = "".join(span.get("class", ["trait"]))
                if trait_class != "trait":
                    trait_class = trait_class.replace("trait", "")
                _, link_obj = extract_link(link)
                trait = {
                    "name": name,
                    "classes": [trait_class if trait_class != "trait" else "trait"],
                    "type": "stat_block_section",
                    "subtype": "trait",
                    "link": link_obj,
                }
                mode_traits.append(trait)
            trait_spans_to_remove.append(span)

        # Remove extracted trait spans from soup
        for span in trait_spans_to_remove:
            span.decompose()

        # Find mode-specific stats (bold tags after this h2, before next h2)
        elements_to_remove = []
        for tag in bs.find_all("b"):
            if not tag.sourceline or not h2.sourceline:
                continue
            if tag.sourceline <= h2.sourceline:
                continue
            if next_h2 and next_h2.sourceline and tag.sourceline >= next_h2.sourceline:
                continue

            label = tag.get_text().strip()
            if not label:
                continue

            # FAIL FAST: Assert all labels are recognized
            assert (
                label in config["recognized_stats"]
            ), f"Unknown weapon stat label in {mode_name} mode: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

            field_name = config["recognized_stats"][label]
            if field_name is None:  # Intentionally skipped (like Source, Favored Weapon)
                continue

            # FAIL FAST: Mode sections should only contain mode-specific fields
            assert field_name in config.get("mode_fields", []), (
                f"Field '{field_name}' from label '{label}' found in {mode_name} mode but not in mode_fields config. "
                f"Mode sections should only contain: {config.get('mode_fields', [])}"
            )

            if label == "Group":
                value = _extract_group_value(tag, config["group_subtype"])
            elif label == "Ammunition":
                # Extract with HTML preserved to capture ammunition links
                value = _extract_stat_value(tag, preserve_html=True)
            else:
                value = _extract_stat_value(tag)
            if value:
                mode_stats[field_name] = value

            # Mark elements for removal: the bold tag and content until next <b>, <br>, or <hr>
            elements_to_remove.append(tag)
            current = tag.next_sibling
            while current:
                if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                    break
                elements_to_remove.append(current)
                current = current.next_sibling

        # Remove extracted stat elements from soup
        for elem in elements_to_remove:
            if isinstance(elem, Tag):
                elem.decompose()
            elif isinstance(elem, NavigableString):
                elem.extract()

        # Build mode object
        mode_obj = {"type": "stat_block_section", "subtype": mode_name}
        if mode_traits:
            mode_obj["traits"] = mode_traits
        mode_obj.update(mode_stats)

        # Set weapon_type based on mode section (combination weapons don't have Type field in HTML)
        mode_obj["weapon_type"] = "Melee" if mode_name == "melee" else "Ranged"

        weapon_obj[mode_name] = mode_obj

    # Remove all h2 sections and their content from soup.
    # Mode h2s (Melee/Ranged) have already had their stats/traits extracted above.
    # Non-mode h2s (Traits, Critical Specialization Effects) are HTML5-added sections
    # whose content we don't need — remove them and everything between them.
    for h2 in bs.find_all("h2", class_="title"):
        # Remove all siblings between this h2 and the next h2 (or end of content)
        current = h2.next_sibling
        while current:
            next_node = current.next_sibling
            if isinstance(current, Tag) and current.name == "h2":
                break
            if isinstance(current, Tag):
                current.decompose()
            elif isinstance(current, NavigableString):
                current.extract()
            current = next_node
        h2.decompose()

    # Add weapon object to stat block
    sb["weapon"] = weapon_obj


def _extract_weapon_stats(bs, stats, config):
    """Extract weapon stats into a flat dictionary."""
    hr = bs.find("hr")
    bold_tags = []
    for tag in bs.find_all("b"):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        bold_tags.append(tag)

    elements_to_remove = []

    for bold_tag in bold_tags:
        label = bold_tag.get_text().strip()
        if not label:
            continue

        assert (
            label in config["recognized_stats"]
        ), f"Unknown weapon stat label: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

        field_name = config["recognized_stats"][label]
        if field_name is None:
            continue

        if label == "Group":
            value = _extract_group_value(bold_tag, config["group_subtype"])
        elif label == "Favored Weapon":
            # Extract with HTML preserved to capture deity links
            value = _extract_stat_value(bold_tag, preserve_html=True)
        elif label == "Ammunition":
            # Extract with HTML preserved to capture ammunition links
            value = _extract_stat_value(bold_tag, preserve_html=True)
        else:
            value = _extract_stat_value(bold_tag)
        if value:
            stats[field_name] = value

        # Mark elements for removal: the bold tag and content until next <b>, <br>, or <hr>
        elements_to_remove.append(bold_tag)
        current = bold_tag.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                break
            elements_to_remove.append(current)
            current = current.next_sibling

    # Remove extracted stat elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()


def _extract_traits(bs, sb):
    """Extract traits from <span class="trait*"> tags (trait, traitrare, traitsize, etc.)."""
    traits = []
    # Match spans where any class starts with 'trait'
    trait_spans = bs.find_all("span", class_=_trait_class_matcher)
    for span in trait_spans:
        # Filter out whitespace text nodes to get actual element children
        children = [c for c in span.children if hasattr(c, "name") and c.name is not None]
        if len(children) == 1 and children[0].name == "a":
            link = children[0]
            name = get_text(link).replace(" Trait", "").strip()
            trait_class = "".join(span.get("class", ["trait"]))
            if trait_class != "trait":
                trait_class = trait_class.replace("trait", "")

            # Build trait object matching trait_parse output
            # Note: Don't include the link here - it will be added by trait_db_pass from the database
            trait = {
                "name": name,
                "classes": [trait_class if trait_class != "trait" else "trait"],
                "type": "stat_block_section",
                "subtype": "trait",
            }
            traits.append(trait)

            # Remove the trait span from the HTML since we've extracted it
            span.decompose()

    # Remove any remaining formatting spans (letter-spacing, etc.) that are empty or whitespace-only
    for span in bs.find_all("span", style=True):
        # Remove spans that are empty or contain only whitespace
        if not span.get_text(strip=True):
            span.decompose()

    if traits:
        sb["traits"] = traits


def _extract_source(bs, struct):
    """Extract source information from <b>Source</b> tag.

    Handles multiple sources separated by commas.
    Example: Source NPC Core pg. 18, Gods & Magic pg. 120 <sup>2.0</sup>
    """
    source_tag = bs.find("b", string=lambda s: s and s.strip() == "Source")
    if not source_tag:
        return

    sources = []

    # Find all source links after the Source tag until we hit the next <b> tag or <br>
    current = source_tag.next_sibling
    current_source_link = None

    while current:
        # Stop at next <b> tag (next field) or <br> tag
        if isinstance(current, Tag) and current.name in ("b", "br", "hr"):
            break

        # Check for source link (italic text inside <a> tag)
        if isinstance(current, Tag) and current.name == "a":
            # Only extract links that are actually sources (have <i> tag for source name)
            # Skip links like "There is a more recent version" which are not sources
            italic = current.find("i")
            if not italic:
                current = current.next_sibling
                continue

            # This is a source link
            current_source_link = current
            source = extract_source(current_source_link)
            if "name" in source:
                source["name"] = source["name"].strip()

            # Check if the next non-whitespace sibling is a <sup> tag (errata)
            next_sib = current_source_link.next_sibling
            while next_sib:
                if isinstance(next_sib, NavigableString):
                    if not next_sib.strip():
                        next_sib = next_sib.next_sibling
                        continue
                    # Hit non-whitespace text (probably a comma), stop looking for errata
                    break

                if isinstance(next_sib, Tag):
                    if next_sib.name == "sup":
                        errata_link = next_sib.find("a")
                        if errata_link:
                            errata = extract_link(errata_link)
                            source["errata"] = errata[1]  # [1] is the link object
                    # Stop after first tag
                    break

                next_sib = next_sib.next_sibling

            sources.append(source)

        current = current.next_sibling

    if sources:
        # Replace any existing sources (don't append - avoids duplicates)
        struct["sources"] = sources

        # Remove the Source tag and all its content from the HTML to avoid double-counting links
        # Remove everything from the <b>Source</b> tag until the next <b> or <br> tag
        current = source_tag
        while current:
            next_node = current.next_sibling
            if isinstance(current, Tag):
                if current.name in ("b", "br", "hr") and current != source_tag:
                    break
                current.decompose()
            elif isinstance(current, NavigableString):
                current.extract()
            current = next_node


def _extract_stats_to_dict(bs, stats_dict, recognized_stats, equipment_type, group_subtype):
    """Extract stats into a dictionary and remove them from the soup.

    Works for any equipment type based on configuration.
    """
    # Find all bold tags that are stats (only in section[0], before first HR)
    # Stats are always in the stat block area before the first <hr>.
    # Content after <hr> is description/ability text and may reuse stat labels
    # (e.g., intelligent item stats in Sharpness Point progression for Briar).
    hr = bs.find("hr")
    bold_tags = []
    for tag in bs.find_all("b"):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        bold_tags.append(tag)

    # Second pass: "Craft Requirements" and "Special" always appear after the
    # description/abilities section (after <hr>), so the main loop above won't
    # find them. Scan specifically for them.
    if hr:
        for tag in bs.find_all("b"):
            if not (tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline):
                continue
            text = tag.get_text().strip()
            if text in ("Craft Requirements", "Special", "Destruction"):
                bold_tags.append(tag)

    # Track elements to remove after extraction (bold tags and their values)
    elements_to_remove = []

    # Extract and validate all labels
    for bold_tag in bold_tags:
        # Skip bold tags inside table elements (table headers/cells, not stat labels)
        if bold_tag.find_parent(["table", "td", "th"]):
            continue

        # Skip bold tags inside sidebar divs (supplementary info, not stat labels)
        if bold_tag.find_parent("div", class_="sidebar"):
            continue

        label = bold_tag.get_text().strip()

        # Skip empty labels
        if not label:
            continue

        # For equipment type, skip unrecognized labels (they may be ability names like Activate)
        # For other types, fail fast on unknown labels
        if label not in recognized_stats:
            if equipment_type == "equipment":
                # Extract links from unrecognized stat fields to prevent link loss.
                # Only extract from bolds BEFORE <hr> (stat area).
                # Bolds after <hr> are in the ability/description section, handled by
                # _extract_abilities_from_description sweep.
                # When no <hr> exists, skip entirely - description extraction handles all links.
                # Skip named activation bolds (em/en-dash prefix like "—Cheat Fate")
                # - these are part of the Activate flow, not stat fields.
                is_named_activation = label and (
                    label[0] in ("\u2014", "\u2013", "-")
                    or (len(label) >= 3 and ord(label[0]) == 226)
                )
                is_ability_field = label in ABILITY_FIELD_NAMES or label == "Activate"
                if (
                    hr
                    and not bold_tag.find_previous("hr")
                    and not is_named_activation
                    and not is_ability_field
                ):
                    unrec_parts = []
                    unrec_current = bold_tag.next_sibling
                    while unrec_current:
                        if isinstance(unrec_current, Tag) and unrec_current.name in ("b", "hr"):
                            break
                        unrec_parts.append(str(unrec_current))
                        unrec_current = unrec_current.next_sibling
                    unrec_html = "".join(unrec_parts)
                    if "<a" in unrec_html:
                        _, unrec_links = extract_links(unrec_html)
                        if unrec_links:
                            if "_unrecognized_links" not in stats_dict:
                                stats_dict["_unrecognized_links"] = []
                            stats_dict["_unrecognized_links"].extend(unrec_links)
                continue  # Skip - might be ability name like Activate, Effect, etc.
            else:
                raise AssertionError(
                    f"Unknown {equipment_type} stat label: '{label}'. Add it to EQUIPMENT_TYPES['{equipment_type}']['recognized_stats']."
                )

        # Skip labels we handle elsewhere (like Source)
        field_name = recognized_stats[label]
        if field_name is None:
            continue

        # Check for ERROR: prefix - these are nested-only fields that shouldn't appear at top level
        # For equipment type, skip these (abilities handled separately by _extract_abilities_from_description)
        if isinstance(field_name, str) and field_name.startswith("ERROR:"):
            if equipment_type == "equipment":
                continue  # Skip - handled by ability extraction
            else:
                nested_location = field_name.split(":")[1]
                raise AssertionError(
                    f"Stat label '{label}' found at top level, but it belongs inside {nested_location}. "
                    f"This item likely has nested abilities/afflictions that need special parsing."
                )

        # For equipment type, skip "Activate" - it's handled by _extract_abilities_from_description
        # which preserves the full ability structure (Frequency, Trigger, Effect fields with links)
        if equipment_type == "equipment" and label == "Activate":
            continue

        # Extract the value (special handling for Group, Activate, and fields with links)
        if label == "Group":
            value = _extract_group_value(bold_tag, group_subtype)
        elif label in (
            "Access",
            "Activate",
            "Base Weapon",
            "Base Armor",
            "Base Shield",
            "Ammunition",
            "Communication",
            "Hands",
            "Languages",
            "Skills",
            "Perception",
            "Craft Requirements",
            "Special",
            "Destruction",
            "Usage",
        ):
            # Preserve HTML for fields that may contain links or action icons
            value = _extract_stat_value(bold_tag, preserve_html=True)
        else:
            value = _extract_stat_value(bold_tag)
        if value:
            stats_dict[field_name] = value

        # Mark elements for removal: the bold tag and content until next <b>, <br>, or <hr>
        elements_to_remove.append(bold_tag)
        current = bold_tag.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
                break
            elements_to_remove.append(current)
            current = current.next_sibling

    # Remove extracted stat elements from soup
    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()


def _extract_stats(bs, sb, recognized_stats, equipment_type, group_subtype):
    """Generic stat extraction - works for any equipment type based on configuration.

    Backward compatibility wrapper that extracts stats and adds them directly to stat_block.
    """
    equipment_stats = {}
    _extract_stats_to_dict(bs, equipment_stats, recognized_stats, equipment_type, group_subtype)
    # Move unrecognized links from stats dict to stat block links
    unrec_links = equipment_stats.pop("_unrecognized_links", None)
    if unrec_links:
        if "links" not in sb:
            sb["links"] = []
        sb["links"].extend(unrec_links)
    sb.update(equipment_stats)


# Maintain backward compatibility - _extract_armor_stats is now an alias
def _extract_armor_stats(bs, sb):
    """Backward compatibility wrapper for _extract_stats."""
    _extract_stats(bs, sb, EQUIPMENT_TYPES["armor"]["recognized_stats"], "armor", "armor_group")


def _extract_stat_value(label_tag, preserve_html=False):
    """Extract the value after a bold label tag, handling em dashes as None.

    Args:
        label_tag: The <b> tag containing the field label
        preserve_html: If True, return HTML string with links intact. If False, return plain text.
    """
    # Collect all content between this label and the next <b> tag, <hr> tag, or semicolon
    # This handles cases like: "+2 (+4<sup>2</sup>)" where content spans multiple siblings
    value_parts = []
    current = label_tag.next_sibling

    while current:
        # Stop at next <b> tag (next field label) or <hr> tag (end of stats section)
        if isinstance(current, Tag) and current.name in ("b", "hr", "br"):
            break

        if isinstance(current, NavigableString):
            text = str(current)
            if text.strip():
                value_parts.append(text)
        elif isinstance(current, Tag):
            # Skip <sup> tags (footnote markers)
            if current.name != "sup":
                if preserve_html:
                    # Keep the HTML structure for links
                    value_parts.append(str(current))
                else:
                    # For other tags, get the text content
                    tag_text = get_text(current)
                    if tag_text.strip():
                        value_parts.append(tag_text)

        current = current.next_sibling

    # Combine collected parts and clean up
    value_text = "".join(value_parts).strip()
    # Strip newlines: HTML5 format adds \n after tags but they carry no semantic value
    value_text = value_text.replace("\n", "")
    # Strip trailing semicolons - they are field separators in the HTML, not part of the value
    value_text = value_text.rstrip(";").strip()

    # Split by semicolon while respecting parentheses (modifiers)
    # e.g., "swim 20 feet (alchemical; underwater only); Collision 2d8" splits to
    # ["swim 20 feet (alchemical; underwater only)", "Collision 2d8"]
    # We only want the first value for this stat
    # Skip for preserve_html fields - they need their full value for link extraction
    # (e.g., Perception: "+25; precise vision 60 feet, imprecise hearing 30 feet")

    if not preserve_html:
        parts = split_maintain_parens(value_text, ";")
        if parts:
            value_text = parts[0].strip()
            # If we're dropping parts, they should be empty or start with a stat
            # label (bold tag text) that will be parsed by the next iteration.
            # Non-empty dropped parts that aren't stat labels indicate lost text.
            for dropped in parts[1:]:
                dropped = dropped.strip()
                if dropped:
                    raise ValueError(
                        f"Semicolon split dropped non-empty text: '{dropped}' "
                        f"(full value was: '{value_text}')"
                    )

    # Return em dash as-is (let field-specific normalizers handle it)
    # E.g., bulk with "—" should become {value: null, text: "—"}

    # Empty string indicates malformed HTML (stat label with no value)
    if value_text == "":
        raise ValueError("Empty value for stat label")

    return value_text


def _extract_group_value(label_tag, group_subtype):
    """Extract group value with link. Group is <u><a href="ArmorGroups.aspx?ID=4">Plate</a></u>."""
    next_sibling = label_tag.next_sibling

    # Skip whitespace-only text nodes
    while next_sibling and isinstance(next_sibling, NavigableString) and not next_sibling.strip():
        next_sibling = next_sibling.next_sibling

    if not next_sibling:
        return None

    # First check if it's a string (em dash for unarmored has no group)
    if isinstance(next_sibling, NavigableString):
        text_value = str(next_sibling).strip()
        if text_value == "—" or text_value == "":
            return None
        # Shouldn't have text-only group (should be in a tag with link)
        return None

    # Group should be a tag containing a link
    if isinstance(next_sibling, Tag):
        link_tag = next_sibling.find("a")
        if link_tag:
            name = get_text(link_tag).strip()
            _, link_obj = extract_link(link_tag)
            return {
                "type": "stat_block_section",
                "subtype": group_subtype,
                "name": name,
                "link": link_obj,
            }

    # Fallback: if no link found, return None (shouldn't have group without link)
    return None


def _remove_redundant_sections(bs, exclude_name="", debug=False):
    """Remove redundant h2 sections (Traits, Armor Specialization Effects, etc.).

    Returns the number of links that were removed with these sections.
    Only counts links that weren't already excluded from the initial count.
    """
    links_removed = 0

    # Remove Traits h2 section (we already extracted traits)
    removed = _remove_h2_section(
        bs, lambda s: s and s.strip() == "Traits", debug=debug, exclude_name=exclude_name
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(f"DEBUG:   Traits section removed {removed} links\n")
    links_removed += removed

    # Remove Armor Specialization Effects h2 section (comes from group, redundant)
    removed = _remove_h2_section(
        bs,
        lambda s: s and "Armor Specialization Effects" in s,
        debug=debug,
        exclude_name=exclude_name,
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(f"DEBUG:   Armor Specialization Effects section removed {removed} links\n")
    links_removed += removed

    # Remove Specific Magic Armor/Weapon/Shield sections (lists of related items)
    removed = _remove_h2_section(
        bs, lambda s: s and "Specific Magic Armor" in s, debug=debug, exclude_name=exclude_name
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(f"DEBUG:   Specific Magic Armor section removed {removed} links\n")
    links_removed += removed

    removed = _remove_h2_section(
        bs, lambda s: s and "Specific Magic Weapon" in s, debug=debug, exclude_name=exclude_name
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(f"DEBUG:   Specific Magic Weapon section removed {removed} links\n")
    links_removed += removed

    removed = _remove_h2_section(
        bs, lambda s: s and "Specific Magic Shield" in s, debug=debug, exclude_name=exclude_name
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(f"DEBUG:   Specific Magic Shield section removed {removed} links\n")
    links_removed += removed

    # Remove Critical Specialization Effects section (weapon groups, redundant)
    removed = _remove_h2_section(
        bs,
        lambda s: s and "Critical Specialization Effects" in s,
        debug=debug,
        exclude_name=exclude_name,
    )
    if debug and removed > 0:
        import sys

        sys.stderr.write(
            f"DEBUG:   Critical Specialization Effects section removed {removed} links\n"
        )
    links_removed += removed

    return links_removed


def _should_exclude_link(link):
    """Check if a link should be excluded from link counting.

    This applies the same exclusion logic as _count_links_in_html.
    Returns True if the link should be excluded (not counted).
    """
    from bs4 import NavigableString, Tag

    from universal.utils import get_text

    # PFS icon links are decorative navigation elements, not content links.
    # Deliberately excluded from both counting and extraction.
    href = link.get("href", "")
    if "PFS.aspx" in href:
        return True

    # Exclude trait links ONLY if inside <span class="trait*"> tags (stat block traits)
    # Regular trait links in text should remain as link objects
    parent = link.parent
    if parent and parent.name == "span":
        parent_classes = parent.get("class", [])
        if isinstance(parent_classes, str):
            if parent_classes.startswith("trait"):
                return True
        else:  # list of classes
            if any(cls.startswith("trait") for cls in parent_classes):
                return True

    # Exclude version navigation links ("more recent version")
    link_text = get_text(link).strip().lower()
    if "more recent version" in link_text or "newer version" in link_text:
        return True

    # Exclude equipment group links (WeaponGroups, ArmorGroups in stat lines)
    game_obj = link.get("game-obj", "")
    if game_obj in ["WeaponGroups", "ArmorGroups"]:
        # Check if it's in a stat line context (parent is <u> with preceding <b> sibling)
        if parent and parent.name == "u":
            prev_sibling = parent.previous_sibling
            # Skip whitespace text nodes
            while prev_sibling:
                if isinstance(prev_sibling, NavigableString):
                    if prev_sibling.strip():
                        break
                    prev_sibling = prev_sibling.previous_sibling
                else:
                    break
            if prev_sibling and isinstance(prev_sibling, Tag) and prev_sibling.name == "b":
                label_text = get_text(prev_sibling).strip()
                if label_text in ["Group", "Armor Group"]:
                    return True

    # Exclude alternate edition links (in siderbarlook divs)
    parent = link.parent
    while parent:
        if isinstance(parent, Tag) and parent.name == "div":
            div_classes = parent.get("class", [])
            if "siderbarlook" in div_classes:
                div_text = get_text(parent).strip()
                return bool("Legacy version" in div_text or "Remastered version" in div_text)
        parent = parent.parent

    return False


def _remove_h2_section(bs, match_func, debug=False, exclude_name=None):
    """Remove an h2 section and all its content until the next h2.

    Returns the number of links (with game-obj attribute) that were removed.
    Only counts links that would have been included in the initial count
    (i.e., not trait links, not group links, not self-references, etc.)
    """
    h2 = bs.find("h2", string=match_func)
    if not h2:
        return 0

    # Collect all elements in this section (for counting links before removal)
    section_elements = [h2]
    current = h2.next_sibling
    while current:
        if isinstance(current, Tag) and current.name == "h2":
            break
        section_elements.append(current)
        current = current.next_sibling

    # Count links in the section before removing
    section_html = "".join(str(e) for e in section_elements)
    section_soup = BeautifulSoup(section_html, "html.parser")
    all_links = section_soup.find_all("a")

    # Filter out excluded links (using same logic as _count_links_in_html)
    from universal.utils import get_text

    links_to_count = []
    for link in all_links:
        # Skip self-references
        if exclude_name and get_text(link).strip() == exclude_name:
            continue
        # Skip other excluded link types
        if _should_exclude_link(link):
            continue
        links_to_count.append(link)

    links_count = len(links_to_count)

    if debug and len(all_links) > 0:
        import sys

        section_name = h2.get_text().strip() if h2 else "unknown"
        sys.stderr.write(
            f"DEBUG:     Section '{section_name}' found {len(all_links)} total links, {links_count} to count (after exclusions):\n"
        )
        for link in all_links:
            excluded = link not in links_to_count
            status = " (EXCLUDED)" if excluded else ""
            sys.stderr.write(f"DEBUG:       - {get_text(link)} ({link.get('game-obj')}){status}\n")

    # Now remove the section
    current = h2.next_sibling
    while current:
        next_sibling = current.next_sibling
        if isinstance(current, Tag):
            if current.name == "h2":
                break
            current.decompose()
        elif isinstance(current, NavigableString):
            current.extract()
        current = next_sibling
    # Remove the h2 itself
    h2.decompose()

    return links_count


def _extract_legacy_content_section(bs, struct):
    """Remove Legacy Content h3 section if present.

    NOTE: Legacy content is now represented via the 'edition' field on the item,
    so we remove this heading rather than creating a section for it.
    """
    # Find and remove Legacy Content h3
    legacy_h3 = bs.find("h3", class_="title")
    if legacy_h3 and "Legacy Content" in get_text(legacy_h3):
        legacy_h3.decompose()


def _extract_base_material(bs, sb, debug=False):
    """Extract 'Base Material' section from special material items.

    These items (e.g., Adamantine Armor, Darkwood Shield) have a section like:
        <h3 class="title">Base Material</h3>
        <u><a href="Equipment.aspx?ID=271">Adamantine</a></u>
        <br>

    This function extracts the material link and removes the section from the soup.

    Returns:
        int: Number of links extracted (for link accounting - 0 or 1)
    """
    if debug:
        h3_tags = bs.find_all("h3", class_="title")
        sys.stderr.write(
            f"DEBUG _extract_base_material: Found {len(h3_tags)} h3 tags with class 'title'\n"
        )
        for h3 in h3_tags:
            sys.stderr.write(f"  - '{get_text(h3)}'\n")

    # Find the "Base Material" h3 header
    for h3 in bs.find_all("h3", class_="title"):
        h3_text = get_text(h3)
        if debug:
            sys.stderr.write(
                f"DEBUG: Checking h3 text: '{h3_text}' - contains 'Base Material': {'Base Material' in h3_text}\n"
            )
        if "Base Material" in h3_text:
            # Found it - extract the material link from the following <u> tag
            u_tag = h3.find_next_sibling("u")
            if debug:
                sys.stderr.write(f"DEBUG: Found Base Material h3, u_tag = {u_tag}\n")
            if u_tag:
                link_tag = u_tag.find("a")
                if link_tag:
                    # Extract the link - extract_link returns (name, link_dict)
                    name, link = extract_link(link_tag)
                    if link:
                        # Create base_material object
                        sb["base_material"] = {
                            "type": "stat_block_section",
                            "subtype": "base_material",
                            "name": name,
                            "link": link,
                        }

                        # Remove the u tag
                        u_tag.decompose()

                # Remove the h3 tag
                h3.decompose()

                # Remove trailing br if present
                for br in bs.find_all("br"):
                    # Check if it's right after where the h3 was
                    # Just remove the first br we find that's not inside another element
                    if br.parent == bs or (
                        hasattr(br, "parent") and br.parent.name in ["div", "span"]
                    ):
                        br.decompose()
                        break

            if debug:
                sys.stderr.write("DEBUG: _extract_base_material returning 1\n")
            return 1  # One link was extracted (moved outside br loop)

    return 0


def _is_variant_marker_heading(tag):
    """Check if a heading tag is a variant marker (not a content section).

    Variant markers contain:
    - PFS.aspx link (PFS icon)
    - "Item X" level indicator

    Args:
        tag: BeautifulSoup heading tag (h1-h6)

    Returns:
        True if this is a variant marker, False if it's a content section heading
    """
    # Check for PFS link - indicator of variant marker
    pfs_link = tag.find("a", href=lambda h: h and "PFS.aspx" in h)
    if pfs_link:
        return True
    # Check for "Item X" level indicator
    return bool(re.search(r"Item\s+\d+", tag.get_text()))


def _get_heading_level(tag):
    """Get numeric level from heading tag (h2 -> 2, h3 -> 3, etc.)."""
    return int(tag.name[1])


def _get_content_until_next_heading(start_heading, all_headings):
    """Get content after a heading until the next heading or end.

    Args:
        start_heading: The heading tag to start from
        all_headings: List of all heading tags to stop at

    Returns:
        HTML string of content between this heading and the next
    """
    content_parts = []
    current = start_heading.next_sibling
    while current:
        if current in all_headings:
            break
        content_parts.append(str(current))
        current = current.next_sibling
    return "".join(content_parts)


def _build_section_from_heading(heading, all_headings):
    """Build a section dict from a heading and its following content.

    Args:
        heading: The heading tag
        all_headings: List of all heading tags (to know where content ends)

    Returns:
        Tuple of (level, section_dict) where level is the heading number
    """
    level = _get_heading_level(heading)
    name = heading.get_text().strip()

    # Extract links from heading itself (e.g., action reference links in h3 titles)
    heading_links = get_links(heading, unwrap=True)

    content = _get_content_until_next_heading(heading, all_headings)

    content_soup = BeautifulSoup(content, "html.parser")
    content_links = get_links(content_soup, unwrap=True)

    all_links = heading_links + content_links

    section = {
        "name": name,
        "type": "section",
        "text": _normalize_whitespace(str(content_soup)),
    }
    if all_links:
        section["links"] = all_links

    return level, section


def _extract_sections_from_headings(desc_soup, debug=False):
    """Extract sections from headings (h1-h6) in description content.

    Builds a nested section structure based on heading hierarchy:
    - Same heading level = siblings in same sections array
    - Larger number (h2 → h3) = child section nested inside
    - Smaller number (h3 → h2) = back up to parent level as sibling

    Args:
        desc_soup: BeautifulSoup object containing description HTML
        debug: Whether to print debug info

    Returns:
        Tuple of (pre_heading_html, sections_list) where:
        - pre_heading_html: HTML content before first heading (main description)
        - sections_list: List of section dicts with name, type, text, sections
    """
    # Find all headings that are NOT variant markers
    headings = [
        tag
        for tag in desc_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if not _is_variant_marker_heading(tag)
    ]

    if not headings:
        return str(desc_soup), []

    # Get content before first heading (this is the main description)
    pre_heading_parts = []
    for elem in desc_soup.children:
        if elem in headings or elem == headings[0]:
            break
        pre_heading_parts.append(str(elem))
    pre_heading_html = "".join(pre_heading_parts)

    # Process headings into nested structure
    sections = []
    section_stack = []  # Stack of (level, section_dict) for tracking hierarchy

    for heading in headings:
        level, section = _build_section_from_heading(heading, headings)

        if not section_stack:
            sections.append(section)
            section_stack.append((level, section))
        else:
            # Pop sections from stack until we find a parent (lower level number)
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()

            if section_stack:
                parent = section_stack[-1][1]
                parent.setdefault("sections", []).append(section)
            else:
                sections.append(section)

            section_stack.append((level, section))

    if debug:
        import sys

        sys.stderr.write(
            f"DEBUG _extract_sections_from_headings: found {len(headings)} headings, {len(sections)} root sections\n"
        )

    return pre_heading_html, sections


def _has_affliction_pattern(soup):
    """Check if soup contains an affliction pattern (Saving Throw + Stages/Duration/Onset).

    Returns True if the soup has a <b>Saving Throw</b> tag followed by at least one of
    <b>Stage</b>, <b>Maximum Duration</b>, or <b>Onset</b>.
    Also returns True for Stage-only patterns (no Saving Throw) like beneficial
    consumables with progression stages (e.g., Heartblood Ring, Phoenix Cinder).
    """
    saving_throw_bold = None
    has_stage = False
    for bold in soup.find_all("b"):
        text = get_text(bold).strip()
        if text == "Saving Throw":
            saving_throw_bold = bold
        if text.startswith("Stage"):
            has_stage = True
    if saving_throw_bold:
        # Classic affliction: Saving Throw + Stages
        for bold in saving_throw_bold.find_all_next("b"):
            text = get_text(bold).strip()
            if text.startswith("Stage") or text == "Maximum Duration" or text == "Onset":
                return True
        return False
    # Stage-only pattern (no Saving Throw)
    return has_stage


def _collect_preceding_whitespace(node):
    """Collect preceding <br> tags and whitespace nodes.

    Args:
        node: Starting node to walk backwards from

    Returns:
        List of br/whitespace nodes preceding the given node
    """
    preceding = []
    prev = node.previous_sibling
    while prev:
        if (isinstance(prev, Tag) and prev.name == "br") or (
            isinstance(prev, NavigableString) and prev.strip() == ""
        ):
            preceding.append(prev)
            prev = prev.previous_sibling
        else:
            break
    return preceding


def _collect_node_and_following(node):
    """Collect a node and all its following siblings.

    Args:
        node: Starting node

    Returns:
        List of nodes from node through end of siblings
    """
    nodes = []
    current = node
    while current:
        nodes.append(current)
        current = current.next_sibling
    return nodes


def _create_affliction_stage(title, text):
    """Create an affliction stage dict.

    Args:
        title: Stage name (e.g., "Stage 1")
        text: Stage effect text

    Returns:
        Stage dict with type, subtype, name, text
    """
    return {
        "type": "stat_block_section",
        "subtype": "affliction_stage",
        "name": title,
        "text": text,
    }


def _normalize_affliction_text(text):
    """Normalize whitespace in affliction text and fix spacing before punctuation.

    Args:
        text: Raw text from affliction HTML

    Returns:
        Cleaned text with normalized whitespace
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r" ([,;.])", r"\1", text)
    return text


def _extract_affliction(desc_soup, item_name):
    """Extract affliction data from description soup into a structured object.

    Finds the <b>Saving Throw</b> tag and collects all subsequent content as
    affliction data. Removes the affliction nodes from desc_soup.

    Args:
        desc_soup: BeautifulSoup object containing the description HTML
        item_name: Name of the equipment item (used as affliction name)

    Returns:
        Tuple of (affliction_dict, affliction_links) or (None, []) if no affliction found.
    """
    # Find the start tag: <b>Saving Throw</b> or first <b>Stage ...</b>
    start_bold = None
    for bold in desc_soup.find_all("b"):
        text = get_text(bold).strip()
        if text == "Saving Throw":
            start_bold = bold
            break
        if text.startswith("Stage") and start_bold is None:
            start_bold = bold
    if not start_bold:
        return None, []

    # Collect nodes to remove: preceding whitespace + affliction content
    nodes_to_remove = _collect_preceding_whitespace(start_bold)
    affliction_nodes = _collect_node_and_following(start_bold)
    nodes_to_remove.extend(affliction_nodes)

    # Build HTML string from affliction nodes (not the preceding brs)
    affliction_html = "".join(str(n) for n in affliction_nodes)

    # Parse affliction HTML to extract links
    affliction_soup = BeautifulSoup(affliction_html, "html.parser")

    # Remove nested Activate content before extracting links.
    # But first, collect any links from the Activate content (e.g., trait links
    # like concentrate, teleportation) so they aren't lost. These links are part
    # of the affliction's content area and won't be seen by ability extraction.
    activate_links = []
    for activate_bold in affliction_soup.find_all(
        "b", string=lambda s: s and s.strip() == "Activate"
    ):
        # Collect links from Activate content before removing it
        current = activate_bold.next_sibling
        while current:
            if isinstance(current, Tag) and current.name == "b":
                txt = get_text(current).strip()
                if txt.startswith("Stage") or txt == "Purging":
                    break
            if isinstance(current, Tag) and current.name == "a":
                href = current.get("href", "")
                if "PFS.aspx" not in href:
                    _, link = extract_link(current)
                    if link:
                        activate_links.append(link)
            current = current.next_sibling
        # Now remove the Activate content from soup
        current = activate_bold
        while current:
            next_node = current.next_sibling
            if isinstance(current, Tag) and current.name == "b" and current is not activate_bold:
                txt = get_text(current).strip()
                if txt.startswith("Stage") or txt == "Purging":
                    break
            if isinstance(current, Tag):
                current.decompose()
            elif isinstance(current, NavigableString):
                current.extract()
            current = next_node

    affliction_links = get_links(affliction_soup, unwrap=True)
    affliction_links.extend(activate_links)

    # Unwrap remaining <a> tags, normalize HR separators, and split by semicolon
    while affliction_soup.a:
        affliction_soup.a.unwrap()
    affliction_text = str(affliction_soup)
    # Normalize <hr> separators to semicolons (stage-based items like Heartblood Ring
    # use HR-separated stages instead of semicolon-separated)
    affliction_text = re.sub(r"<hr\s*/?>", ";", affliction_text)
    parts = [p.strip() for p in affliction_text.split(";")]

    section = {
        "type": "stat_block_section",
        "subtype": "affliction",
        "name": item_name,
    }

    first = True
    for p in parts:
        p_soup = BeautifulSoup(p, "html.parser")
        if p_soup.b:
            title = get_text(p_soup.b.extract()).strip()
            newtext = _normalize_affliction_text(get_text(p_soup))
            if title == "Saving Throw":
                section["saving_throw"] = universal_handle_save_dc(newtext)
            elif title == "Onset":
                section["onset"] = newtext
            elif title == "Maximum Duration":
                section["maximum_duration"] = newtext
            elif title == "Effect":
                section["effect"] = newtext
            elif title.startswith("Stage"):
                section.setdefault("stages", []).append(_create_affliction_stage(title, newtext))
            else:
                section.setdefault("text", newtext)
        else:
            text_content = _normalize_affliction_text(get_text(p_soup))
            if text_content:
                if first:
                    section["context"] = text_content
                else:
                    section.setdefault("text", text_content)
        first = False

    if affliction_links:
        section["links"] = affliction_links

    _remove_soup_nodes(nodes_to_remove)
    return section, affliction_links


def _extract_description(bs, struct, debug=False):
    """Extract description text and links, adding them to the stat_block.

    For equipment with multiple <hr> separators (siege weapons, vehicles), splits by <hr>
    and finds the section with the fewest bold stat labels - this is the description.
    The description is typically pure text with few/no bold tags, while stat sections
    have many bold stat labels.

    For equipment without <hr> separators (armor, weapons), extracts all remaining
    text in the stat block as description.

    Text is added to stat_block['text'], and links (if any) to stat_block['links'].
    Only creates sections if there are actual headings (h2, h3) after the description.
    """
    # Split by <hr> tags to get sections
    text = str(bs)
    if debug:
        bs_link_count = len(BeautifulSoup(text, "html.parser").find_all("a"))
        sys.stderr.write(
            f"DEBUG _extract_description: bs text has {bs_link_count} links, len={len(text)}\n"
        )
    sections = split_on_tag(text, "hr")

    if len(sections) < 2:
        # No <hr> tags - extract all remaining text as description (armor, weapons)
        # For combination weapons, stop at first <h2 class="title"> (mode section header)
        first_h2 = bs.find("h2", class_="title")
        if first_h2:
            # This is a combination weapon - extract only content before first <h2>
            # Create a new soup with only content before the h2
            content_before_h2 = []
            for elem in bs.children:
                if elem == first_h2:
                    break
                content_before_h2.append(str(elem))
            last_section = "".join(content_before_h2)
            desc_soup = BeautifulSoup(last_section, "html.parser")
        else:
            # Single-mode weapon - use all content
            desc_soup = bs
            last_section = text
    else:
        # Multiple <hr> tags - find the section that looks like a description
        # For vehicles: description is in section[1] (after source/price, before stats)
        # For siege weapons: description is in the LAST section (mixed with actions)
        # For other equipment: use the section with fewest bold stat labels

        equipment_type = struct.get("type", "")

        if equipment_type == "vehicle" and len(sections) > 1:
            # Vehicles MAY have description in section[1] (between source/price and stats)
            # But some vehicles have no description - section[1] is stats
            # Check if section[1] starts with a stat label
            section1 = sections[1].strip()
            section1_soup = BeautifulSoup(section1, "html.parser")
            first_bold = section1_soup.find("b")
            vehicle_stat_labels = {"Space", "Crew", "Passengers", "Piloting Check"}

            if first_bold and first_bold.get_text().strip() in vehicle_stat_labels:
                # Section[1] is stats, not description - vehicle has no description
                desc_section = ""
            else:
                # Section[1] is description
                desc_section = section1
        else:
            # Combine all content sections after section[0] (stats area).
            # Section[0] contains the stat block (title, traits, source, etc.)
            # which has already been extracted. Remaining sections are all
            # description content: stage-based items, relic gifts, activations, etc.
            desc_section = "<hr/>".join(sec for sec in sections[1:] if sec.strip())

            if not desc_section:
                # Fallback if all sections are empty
                desc_section = sections[-1] if sections else ""

            # Move Activate content from section[0] to desc_section.
            # In HTML5 format, <hr> sometimes appears after the Activate line,
            # placing it in section[0] (stats area). Stat extraction skips
            # Activate for equipment type, so it stays in section[0] where
            # ability extraction (which runs on desc_soup) wouldn't find it.
            # Use <hr/> separator so _collect_equipment_ability_content stops
            # at the boundary between Activate and description content.
            if equipment_type != "siege_weapon":
                sec0_activate = re.search(r"<b>\s*Activate\s*</b>", sections[0])
                if sec0_activate:
                    activate_content = sections[0][sec0_activate.start() :]
                    sections[0] = sections[0][: sec0_activate.start()]
                    if desc_section:
                        desc_section = activate_content + "<hr/>" + desc_section
                    else:
                        desc_section = activate_content

        desc_soup = BeautifulSoup(desc_section, "html.parser")

        # Remove leading <hr> and <br> tags (artifacts from stat extraction leaving empty sections)
        for child in list(desc_soup.children):
            if isinstance(child, Tag) and child.name in ("hr", "br"):
                child.decompose()
            elif isinstance(child, NavigableString) and not child.strip():
                child.extract()
            else:
                break  # Stop at first real content

        if debug:
            sec0_soup = BeautifulSoup(sections[0], "html.parser")
            sec0_links = sec0_soup.find_all("a")
            sys.stderr.write(
                f"DEBUG: section[0] has {len(sec0_links)} links, sections[1:] combined has {len(desc_soup.find_all('a'))} links, total sections={len(sections)}\n"
            )

        # Rescue non-sidebar links from section[0] (stat area remnants).
        # After stat extraction and Activate content move, section[0] may still
        # have stray links (e.g., from unrecognized stat content). Rescue them
        # into stat_block.links so they aren't lost.
        if sections[0].strip():
            sec0_soup = BeautifulSoup(sections[0], "html.parser")
            # Remove sidebar divs (their links were already excluded from HTML count)
            for sidebar in sec0_soup.find_all("div", class_="sidebar"):
                sidebar.decompose()
            sec0_remaining_links = get_links(sec0_soup, unwrap=True)
            if sec0_remaining_links:
                sb = find_stat_block(struct)
                existing_links = sb.setdefault("links", [])
                existing_keys = {
                    (l.get("name"), l.get("game-obj", l.get("href", ""))) for l in existing_links
                }
                item_name = struct.get("name", "")
                for link in sec0_remaining_links:
                    # Skip self-references (excluded from HTML count)
                    if link.get("name") == item_name:
                        continue
                    # Skip links already in stat_block from stat extraction
                    # (e.g., relic aspect links). Don't skip sec0 duplicates
                    # though — HTML may have multiple <a> tags with same text.
                    key = (link.get("name"), link.get("game-obj", link.get("href", "")))
                    if key not in existing_keys:
                        existing_links.append(link)

        # Note: h2.title headings in content sections (e.g., "Deck Of Illusions Cards",
        # "Dragon") are processed by _extract_sections_from_headings later.
        # The len(sections) < 2 branch has a similar check for combination weapons,
        # which don't have <hr> separators.

    # Extract Stage-only afflictions (no Saving Throw) BEFORE action detection,
    # because stage-based items may have nested Activate bolds within stages that
    # would otherwise trigger the action removal and wipe out stage content.
    # Normal afflictions (with Saving Throw) are extracted AFTER action detection,
    # because they're typically inside an Activate block and the action detection
    # removes the Activate content first.
    affliction = None
    affliction_links = []
    has_saving_throw = desc_soup.find("b", string=lambda s: s and s.strip() == "Saving Throw")
    if not has_saving_throw and _has_affliction_pattern(desc_soup):
        affliction, affliction_links = _extract_affliction(desc_soup, struct.get("name", ""))

    # Extract abilities (Activate, etc.) from desc_soup BEFORE action detection.
    # This properly handles combined sections: abilities are extracted with their links,
    # and non-ability content (like relic gift lists) remains in desc_soup for the
    # description link extraction below. Must run before action detection so that
    # links aren't double-counted between abilities and description.
    # Debug: show links BEFORE ability extraction
    if debug:
        pre_links = desc_soup.find_all("a")
        sys.stderr.write(f"DEBUG: Before ability extraction, {len(pre_links)} links in desc_soup\n")
        for rl in pre_links:
            sys.stderr.write(f"  - {rl.get('href', '')[:60]} text={rl.get_text(strip=True)[:30]}\n")

    sb_for_abilities = find_stat_block(struct)
    trait_links_converted = _extract_abilities_from_description(
        desc_soup, sb_for_abilities, struct, debug=debug
    )

    # Extract abilities from h3.title headings with action links (HTML5 format).
    # Must run before HR cleanup since h3 abilities use <hr> as field/effect separator.
    _extract_h3_abilities(desc_soup, sb_for_abilities, debug=debug)

    # After ability extraction, remove all remaining <hr> tags from desc_soup.
    # These were used as boundary markers: (1) section joins use <hr/> to
    # preserve boundaries between description and supplementary content (relic
    # gifts, tea ceremony, oathbreaker's calamity, etc.), and (2) moved
    # Activate content uses <hr/> to separate from description. After ability
    # extraction consumed the relevant content, orphan <hr> tags would
    # pollute the description text and fail markdown validation.
    for hr in desc_soup.find_all("hr"):
        hr.decompose()

    # Debug: show remaining links after ability extraction
    if debug:
        remaining_links = desc_soup.find_all("a")
        sys.stderr.write(
            f"DEBUG: After ability extraction, {len(remaining_links)} links remain in desc_soup\n"
        )
        for rl in remaining_links:
            sys.stderr.write(f"  - {rl.get('href', '')[:60]} text={rl.get_text(strip=True)[:30]}\n")

    # Find the first action - either a bold tag with action name, or an action icon span
    # We need to find the EARLIEST action in document order, not just the first one we encounter
    known_actions = [
        "Activate",
        "Aim",
        "Load",
        "Launch",
        "Ram",
        "Effect",
        "Requirements",
    ]
    first_action_element = None
    candidates = []

    # Collect all potential action elements
    # 1. Bold tags with action names
    for bold in desc_soup.find_all("b"):
        bold_text = get_text(bold).strip()
        is_known_action = bold_text in known_actions

        # Check if followed by action icon
        next_sib = bold.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and next_sib.strip() == "":
            next_sib = next_sib.next_sibling
        has_action_icon = (
            isinstance(next_sib, Tag)
            and next_sib.name == "span"
            and "action" in next_sib.get("class", [])
        )

        if is_known_action or has_action_icon:
            candidates.append(bold)

    # 2. Action icon spans (for actions without bold tags)
    action_spans = desc_soup.find_all("span", class_="action")
    candidates.extend(action_spans)

    # Find the earliest candidate in document order
    if candidates:
        # Get the position of each candidate by walking through all descendants
        def get_element_index(elem):
            for idx, descendant in enumerate(desc_soup.descendants):
                if descendant is elem:
                    return idx
            return float("inf")

        first_action_element = min(candidates, key=get_element_index)

    # Extract only the content before the first action
    if debug and first_action_element:
        sys.stderr.write(
            f"DEBUG: Action detection found: {first_action_element.name} text='{first_action_element.get_text(strip=True)[:30]}'\n"
        )
        remaining_after = []
        n = first_action_element.next_sibling
        while n:
            if isinstance(n, Tag) and n.name == "a":
                remaining_after.append(n.get("href", "")[:40])
            n = n.next_sibling
        sys.stderr.write(f"DEBUG: Will remove {len(remaining_after)} links after action element\n")

    if first_action_element:
        # Remove everything from the action element onwards
        current = first_action_element

        # If it's an action icon span, also remove preceding action name and <br> tag
        if isinstance(first_action_element, Tag) and first_action_element.name == "span":
            # Action icons follow action names. Remove span, preceding action name text, and br.
            prev = first_action_element.previous_sibling
            # Remove preceding br tag
            if isinstance(prev, Tag) and prev.name == "br":
                prev.extract()
                prev = prev.previous_sibling if prev else None
            # Remove preceding action name text (if it's a NavigableString with an action name)
            if prev and isinstance(prev, NavigableString):
                text = prev.strip()
                if any(action in text for action in known_actions):
                    prev.extract()

        # Remove the action element and everything after it
        while current:
            next_node = current.next_sibling
            if isinstance(current, Tag):
                current.decompose()
            elif isinstance(current, NavigableString):
                current.extract()
            current = next_node

    # Extract normal afflictions (with Saving Throw) AFTER action detection
    if not affliction and _has_affliction_pattern(desc_soup):
        affliction, affliction_links = _extract_affliction(desc_soup, struct.get("name", ""))

    # Extract save outcome labels (Success, Failure, Critical Success, Critical Failure)
    # These are bold labels followed by outcome text, separated by <br> tags.
    # Extract them from the soup and store as structured data on stat_block.
    save_outcome_labels = {
        "Critical Success": "critical_success",
        "Critical Failure": "critical_failure",
        "Success": "success",
        "Failure": "failure",
    }
    save_outcomes = {}
    save_outcome_links = []
    for bold in list(desc_soup.find_all("b")):
        bold_text = get_text(bold).strip()
        if bold_text not in save_outcome_labels:
            continue
        field_name = save_outcome_labels[bold_text]
        # Collect HTML content after the bold until the next <b> or <br> tag
        outcome_parts = []
        current = bold.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "br"):
                break
            outcome_parts.append(str(current))
            current = current.next_sibling
        # Parse the collected HTML to extract links before getting text
        outcome_html = "".join(outcome_parts).strip()
        if outcome_html:
            outcome_soup = BeautifulSoup(outcome_html, "html.parser")
            outcome_links = get_links(outcome_soup, unwrap=True)
            save_outcome_links.extend(outcome_links)
            outcome_text = get_text(outcome_soup).strip()
            if outcome_text:
                save_outcomes[field_name] = outcome_text
        # Remove the bold and its text content from the soup
        to_remove = []
        current = bold.next_sibling
        while current:
            if isinstance(current, Tag) and current.name in ("b", "br"):
                break
            to_remove.append(current)
            current = current.next_sibling
        for elem in to_remove:
            if isinstance(elem, Tag):
                elem.decompose()
            else:
                elem.extract()
        bold.decompose()

    # Collapse runs of 3+ consecutive <br> tags down to 2 (a paragraph break).
    # After extracting save outcome labels, the surrounding <br> separators pile up.
    # Two <br> tags = paragraph break (normal), 3+ = artifact of extraction.
    for br in list(desc_soup.find_all("br")):
        if br.parent is None:
            continue  # Already removed
        # Count consecutive <br> tags (skipping whitespace-only text nodes)
        br_run = [br]
        sibling = br.next_sibling
        while sibling:
            if isinstance(sibling, NavigableString) and sibling.strip() == "":
                sibling = sibling.next_sibling
            elif isinstance(sibling, Tag) and sibling.name == "br":
                br_run.append(sibling)
                sibling = sibling.next_sibling
            else:
                break
        # Only collapse if 3+ <br> tags in a row
        if len(br_run) >= 3:
            # Remove extras, keeping first 2
            for extra_br in br_run[2:]:
                extra_br.decompose()

    # Clean \n from text nodes added by web folder preprocessing (adds \n after
    # every tag). For text nodes with content (e.g., "\n.\n"), remove \n to
    # prevent " ." artifacts. For whitespace-only nodes between sibling tags
    # (e.g., "\n" between </a> and <a>), replace with space to preserve word
    # boundaries. For whitespace-only nodes in other positions (e.g., between
    # a child tag and parent closing tag), remove entirely.
    for text_node in list(desc_soup.find_all(string=True)):
        if "\n" not in text_node:
            continue
        text = str(text_node)
        cleaned = text.replace("\n", "")
        if cleaned.strip():
            # Has real content - keep with \n removed
            text_node.replace_with(cleaned)
        else:
            # Whitespace-only: check if between two sibling tags (word boundary)
            prev_sib = text_node.previous_sibling
            next_sib = text_node.next_sibling
            if (
                prev_sib is not None
                and next_sib is not None
                and isinstance(prev_sib, Tag)
                and isinstance(next_sib, Tag)
            ):
                text_node.replace_with(" ")
            else:
                text_node.extract()

    # Extract sections from headings (h2, h3, etc.) before processing links
    # This separates main description from structured section content
    pre_heading_html, sections = _extract_sections_from_headings(desc_soup, debug=debug)

    # Create soup from pre-heading content for link extraction
    pre_heading_soup = BeautifulSoup(pre_heading_html, "html.parser")

    # Extract links and unwrap <a> tags from main description
    links = get_links(pre_heading_soup, unwrap=True)

    # Keep ALL links including trait links
    # Trait links in description text should be regular link objects, not filtered out
    # (Only trait links in <span class="trait*"> tags or ability parentheses are converted to traits)
    non_trait_links = links

    # Get the cleaned text (only pre-heading content, not sections)
    desc_text = _normalize_whitespace(str(pre_heading_soup))

    # Add text and links to stat_block (not top-level structure)
    # Always clear raw HTML from stat_block's text - replace with clean description or remove
    sb = find_stat_block(struct)

    # Check if desc_text is actual descriptive content or just remnant HTML
    # Items without descriptions may have name + item level left over
    # Skip if it only contains the item name or only has short text with no sentences
    item_name = struct.get("name", "")
    is_valid_description = False
    if desc_text:
        # Get plain text without HTML tags for validation
        plain_text = BeautifulSoup(desc_text, "html.parser").get_text().strip()
        # Valid description should:
        # 1. Be more than just the item name
        # 2. Contain at least one sentence (ends with period or has significant content)
        # 3. Not be just "Item X" level text
        text_without_name = plain_text.replace(item_name, "").strip()
        # Remove "Item X" patterns
        text_without_name = re.sub(r"Item\s+\d+\+?", "", text_without_name).strip()
        # Check if there's meaningful content left
        is_valid_description = len(text_without_name) > 10 and not text_without_name.isdigit()

    if desc_text and is_valid_description:
        sb["text"] = desc_text
    elif "text" in sb:
        # No description found - remove raw HTML that was set by restructure_equipment_pass
        del sb["text"]

    # Store affliction if extracted
    if affliction:
        sb["affliction"] = affliction

    # Store save outcomes if any were extracted
    if save_outcomes:
        sb["save_results"] = {
            "type": "stat_block_section",
            "subtype": "save_results",
        }
        sb["save_results"].update(save_outcomes)
        if save_outcome_links:
            sb["save_results"]["links"] = save_outcome_links

    # Store extracted links if any exist (excluding trait links)
    # Merge with any existing links (e.g., from unrecognized stat fields like Aspects)
    # avoiding duplicates by checking (name, game-obj/href)
    links_deduped = 0
    if non_trait_links:
        existing_links = sb.setdefault("links", [])
        existing_keys = {
            (l.get("name"), l.get("game-obj", l.get("href", ""))) for l in existing_links
        }
        for l in non_trait_links:
            key = (l.get("name"), l.get("game-obj", l.get("href", "")))
            if key not in existing_keys:
                existing_links.append(l)
                existing_keys.add(key)
            else:
                links_deduped += 1

    # Add sections if any were extracted from headings
    if sections:
        sb["sections"] = sections

    if debug:
        sys.stderr.write(
            f"DEBUG _extract_description returning: trait_links_converted={trait_links_converted}, links_deduped={links_deduped}\n"
        )

    return trait_links_converted + links_deduped


def _parse_activation_types(activation_string):
    """Convert activation string to a list of activation_type objects.

    Args:
        activation_string: String like "command, Interact" or "command" or "Interact"

    Returns:
        List of activation_type objects, e.g.:
        [
            {"type": "stat_block_section", "subtype": "activation_type", "value": "command"},
            {"type": "stat_block_section", "subtype": "activation_type", "value": "Interact"}
        ]
    """
    if not activation_string:
        return []

    # Use shared utility that respects parentheses when splitting
    parts = split_comma_and_semicolon(activation_string)
    result = []
    for part in parts:
        value = part.strip()
        if value:
            result.append(
                {
                    "type": "stat_block_section",
                    "subtype": "activation_type",
                    "value": value.lower(),
                }
            )
    return result


def _collect_siblings_until_bold(start_node):
    """Collect sibling nodes starting from start_node until a <b> tag or end.

    Args:
        start_node: The first sibling to examine

    Returns:
        Tuple of (value_parts, nodes_to_remove) where value_parts is list of
        stringified nodes and nodes_to_remove is list of node references.
    """
    value_parts = []
    nodes_to_remove = []
    current = start_node
    while current:
        if isinstance(current, Tag) and current.name == "b":
            break
        value_parts.append(str(current))
        nodes_to_remove.append(current)
        current = current.next_sibling
    return value_parts, nodes_to_remove


def _clean_field_value_html(value_html):
    """Clean field value HTML by removing leading/trailing semicolons and br tags.

    Args:
        value_html: Raw HTML string from field value

    Returns:
        Cleaned HTML string
    """
    value_html = value_html.strip()
    value_html = re.sub(r"^[\s;]+", "", value_html)
    value_html = re.sub(r"<br\s*/?>[\s]*$", "", value_html)
    value_html = re.sub(r"[\s;]+$", "", value_html)
    return value_html


def _remove_soup_nodes(nodes):
    """Remove a list of nodes from their parent soup.

    Args:
        nodes: List of Tag or NavigableString nodes to remove
    """
    for node in nodes:
        if isinstance(node, Tag):
            node.decompose()
        elif isinstance(node, NavigableString):
            node.extract()


# Field names recognized as ability sub-fields
ABILITY_FIELD_NAMES = [
    "Frequency",
    "Trigger",
    "Effect",
    "Requirements",
    "Prerequisite",
    "Critical Success",
    "Success",
    "Failure",
    "Critical Failure",
    "Destruction",
]


def _extract_ability_fields(ability_soup, ability):
    """Extract sub-fields (Frequency, Trigger, Effect, Requirements) from ability soup.

    Modifies ability dict in place, adding fields like 'frequency', 'trigger', etc.
    Also adds any links found in field values to ability['links'].
    Removes the extracted fields from ability_soup.

    Args:
        ability_soup: BeautifulSoup object containing the ability HTML
        ability: dict to populate with extracted fields
    """
    for field in ABILITY_FIELD_NAMES:
        field_bold = ability_soup.find("b", string=lambda s, f=field: s and s.strip() == f)
        if not field_bold:
            continue

        value_parts, nodes_to_remove = _collect_siblings_until_bold(field_bold.next_sibling)
        value_html = _clean_field_value_html("".join(value_parts))

        if value_html:
            # Extract links from value
            value_text, value_links = extract_links(value_html)
            # Convert <br> tags to newlines, then normalize whitespace
            value_text = re.sub(r"<br\s*/?>", "\n", value_text)
            value_text = _normalize_whitespace(value_text)

            field_key = field.lower().replace(" ", "_")
            if field_key == "requirements":
                field_key = "requirement"

            ability[field_key] = value_text

            if value_links:
                ability.setdefault("links", []).extend(value_links)

        _remove_soup_nodes(nodes_to_remove)
        field_bold.decompose()


def _parse_named_activation(act_current):
    """Check if the current element is a named activation bold tag (e.g., "—Dim Sight").

    Named activations start with em-dash, en-dash, regular hyphen, or mojibake patterns.

    Args:
        act_current: The current BeautifulSoup element to check

    Returns:
        tuple: (ability_name, next_sibling) where ability_name is None if not a named activation
    """
    if not (isinstance(act_current, Tag) and act_current.name == "b"):
        return None, act_current

    b_text = act_current.get_text().strip()
    if not b_text:
        return None, act_current

    first_char = b_text[0]
    # Mojibake check: em-dash UTF-8 (E2 80 94) decoded as latin-1 = 'â€"' (3 chars starting with â ord=226)
    is_mojibake_emdash = len(b_text) >= 3 and ord(first_char) == 226

    is_named = (
        first_char == "—"  # em-dash U+2014
        or first_char == "–"  # en-dash U+2013
        or first_char == "-"  # regular hyphen
        or ord(first_char) == 8212  # em-dash decimal
        or b_text.startswith("\u2014")  # em-dash unicode escape
        or is_mojibake_emdash
    )

    if not is_named:
        return None, act_current

    # Extract the name (strip the dash prefix)
    if is_mojibake_emdash:
        ability_name = b_text[3:].strip()  # Remove 3-char mojibake prefix
    else:
        ability_name = b_text[1:].strip()  # Remove the dash prefix

    return ability_name, act_current.next_sibling


def _extract_activation_traits_from_parens(text, trait_links, include_unlinked_traits=False):
    """Extract trait objects from parenthesized content in activation text.

    Given text like "command (manipulate, divine)" and trait links, extracts which
    trait links match names inside parentheses, builds trait objects, and returns
    the text before parens as the activation text.

    Args:
        text: Clean text (links already unwrapped), e.g. "command (manipulate, divine)"
        trait_links: List of trait link dicts (game-obj == "Traits")
        include_unlinked_traits: If True, unlinked text in parens also becomes traits
            (used by legacy activate field). Default False (only linked traits).

    Returns:
        tuple: (traits, text_before, other_links, converted_count) where:
            - traits: list of trait objects (or empty list)
            - text_before: text before parentheses (activation text)
            - other_links: trait links not matched in parentheses
            - converted_count: number of trait links converted
    """
    if "(" not in text:
        return [], text, list(trait_links), 0

    paren_start = text.find("(")
    paren_end = text.find(")")
    if paren_end <= paren_start:
        return [], text, list(trait_links), 0

    parens_content = text[paren_start + 1 : paren_end].strip()
    text_before = text[:paren_start].strip()

    # Build a map of lowercased trait names to original names to preserve casing
    paren_trait_map = {
        name.strip().lower(): name.strip() for name in split_comma_and_semicolon(parens_content)
    }
    traits_to_convert = []
    other_links = []

    for trait_link in trait_links:
        trait_name_lower = trait_link["name"].lower()
        if trait_name_lower in paren_trait_map:
            traits_to_convert.append(trait_link)
            del paren_trait_map[trait_name_lower]
        else:
            other_links.append(trait_link)

    trait_names = [tl["name"] for tl in traits_to_convert]

    if include_unlinked_traits:
        # Add any remaining unlinked traits from the parentheses, sorted for determinism
        for unlinked_trait_lower in sorted(paren_trait_map.keys()):
            unlinked_trait_original = paren_trait_map[unlinked_trait_lower]
            if unlinked_trait_original and not unlinked_trait_original.isdigit():
                trait_names.append(unlinked_trait_original)

    traits = build_objects("stat_block_section", "trait", trait_names) if trait_names else []
    return traits, text_before, other_links, len(traits_to_convert)


def _extract_traits_from_time_part(time_part, ability):
    """Extract traits from a time part that may contain parenthesized trait links.

    Handles patterns like "10 minutes (fortune, mental)" where traits are
    linked inside parentheses after the time value.

    Args:
        time_part: HTML string of the time portion (e.g., "10 minutes (fortune, mental)")
        ability: dict to add extracted traits to

    Returns:
        Tuple of (activation_time, trait_links_converted) where activation_time is the
        cleaned time string and trait_links_converted is count of trait links processed.
    """
    time_soup = BeautifulSoup(time_part, "html.parser")
    time_trait_links = []
    for a_tag in time_soup.find_all("a", attrs={"game-obj": "Traits"}):
        _, link = extract_link(a_tag)
        time_trait_links.append(link)
        a_tag.unwrap()

    time_text = _normalize_whitespace(str(time_soup))
    trait_links_converted = 0

    if time_trait_links and "(" in time_text:
        paren_start = time_text.find("(")
        paren_end = time_text.find(")")
        if paren_end > paren_start:
            trait_names = [tl["name"] for tl in time_trait_links]
            if trait_names:
                traits = build_objects("stat_block_section", "trait", trait_names)
                ability.setdefault("traits", []).extend(traits)
                trait_links_converted = len(time_trait_links)
            # Remove the parenthesized section from the time text
            return time_text[:paren_start].strip(), trait_links_converted
    elif time_trait_links:
        # Non-parenthesized traits in time part (e.g., "auditory, linguistics; 10 minutes")
        # Convert them to traits and extract just the time portion
        trait_names = [tl["name"] for tl in time_trait_links]
        if trait_names:
            traits = build_objects("stat_block_section", "trait", trait_names)
            ability.setdefault("traits", []).extend(traits)
            trait_links_converted = len(time_trait_links)
        # Find the time portion from semicolon-separated segments
        for part in time_text.split(";"):
            if _TIME_PATTERN.search(part):
                return part.strip(), trait_links_converted
        return time_text, trait_links_converted

    return time_text, trait_links_converted


# Regex pattern for detecting time values in activation content
_TIME_PATTERN = re.compile(r"\d+\s*(minute|hour|round|day|action)", re.IGNORECASE)
_TIME_ONLY_PATTERN = re.compile(r"^\d+\s*(minute|hour|round|day|action)s?$", re.IGNORECASE)


def _parse_activation_content(activate_content, ability):
    """Parse activation content to extract traits, activation types, time, and links.

    Handles parsing of text like "command (manipulate)" or "Interact" to extract:
    - Traits from parentheses (e.g., "manipulate" becomes a trait object)
    - Activation types (e.g., "command", "Interact")
    - Activation time (e.g., "1 minute" from "command, envision; 1 minute")
    - Links (non-trait links are added to ability["links"])

    Args:
        activate_content: HTML string of the activation content
        ability: dict to populate with traits, activation_types, activation_time, and links

    Returns:
        int: Count of trait links converted (for link accounting)
    """
    trait_links_converted = 0
    activation_time = None

    # Check for activation_time (semicolon-separated, e.g., "command, envision; 1 minute")
    if ";" in activate_content:
        parts = activate_content.split(";", 1)
        activate_content = parts[0].strip()
        if len(parts) > 1:
            time_part = parts[1].strip()
            if _TIME_PATTERN.search(time_part):
                activation_time, converted = _extract_traits_from_time_part(time_part, ability)
                trait_links_converted += converted
            else:
                # Non-time part may contain trait links (e.g., "auditory, linguistic)")
                # Re-include only if it has <a> tags (links worth preserving).
                # Don't re-include plain text/spans (e.g., "This activation takes
                # [two-actions]...") as it would pollute activation_types.
                if "<a " in time_part or "<a>" in time_part:
                    activate_content = activate_content + " " + time_part

    # Parse the activate content soup to extract links and traits
    content_soup = BeautifulSoup(activate_content, "html.parser")

    # Extract all links first
    all_links = get_links(content_soup, unwrap=True)

    # Separate trait links from other links
    trait_links = [link for link in all_links if link.get("game-obj") == "Traits"]
    other_links = [link for link in all_links if link.get("game-obj") != "Traits"]

    # Get text after unwrapping links
    text = _normalize_whitespace(str(content_soup))

    # Extract traits from parentheses (linked traits only — unlinked text is NOT a trait)
    traits, activation, remaining_trait_links, converted = _extract_activation_traits_from_parens(
        text, trait_links
    )
    trait_links_converted += converted
    other_links.extend(remaining_trait_links)

    if traits:
        ability["traits"] = traits

    # The text before parentheses is the activation (e.g., "command", "Interact")
    # BUT: If it looks like a time value (e.g., "1 minute"), it's activation_time, not activation
    if activation and _TIME_ONLY_PATTERN.match(activation):
        activation_time = activation
        activation = ""

    # Store activation types as list of objects
    if activation:
        ability["activation_types"] = _parse_activation_types(activation)

    # Store activation time if present (e.g., "1 minute")
    if activation_time:
        ability["activation_time"] = activation_time

    if other_links:
        if "links" not in ability:
            ability["links"] = []
        ability["links"].extend(other_links)

    return trait_links_converted


def _extract_h3_abilities(desc_soup, sb, debug=False):
    """Extract abilities from h3.title headings that contain action links.

    These appear in HTML5 format as:
      <h3 class="title"><a href="Actions.aspx?ID=...">name</a>
        <span class="action">[one-action]</span></h3>
      <b>Source</b>...<br/><b>Frequency</b> once per day<hr/>
      Effect description text...

    Extracts them as structured ability objects and removes from desc_soup.

    Args:
        desc_soup: BeautifulSoup object containing description HTML
        sb: Stat block dict to add abilities to
        debug: Enable debug output

    Returns:
        int: 0 (no link accounting adjustment needed)
    """
    # Find h3.title headings that contain action links or action spans.
    # After href_filter(), <a href="Actions.aspx?ID=X"> becomes
    # <a game-obj="Actions" aonid="X">, so check game-obj attribute.
    # Some h3 abilities have empty <a> tags (decomposed by _content_filter)
    # but still have <span class="action"> — detect those too.
    h3_abilities = []
    for h3 in desc_soup.find_all("h3", class_="title"):
        has_action_link = h3.find("a", attrs={"game-obj": "Actions"})
        has_action_span = h3.find("span", class_="action")
        if not has_action_link and not has_action_span:
            continue
        h3_abilities.append(h3)

    if not h3_abilities:
        return 0

    abilities = []
    for i, h3 in enumerate(h3_abilities):
        next_h3 = h3_abilities[i + 1] if i + 1 < len(h3_abilities) else None

        # Extract action name and link from h3
        action_a = h3.find("a", attrs={"game-obj": "Actions"})
        action_link_obj = None
        if action_a:
            ability_name = action_a.get_text().strip()
            _, action_link_obj = extract_link(action_a)
        else:
            ability_name = ""

        # Extract action type from span in h3
        action_span = h3.find("span", class_="action")
        action_type = None
        if action_span:
            title = action_span.get("title", "")
            if title == "Single Action":
                title = "One Action"
            if title:
                action_type = {
                    "type": "stat_block_section",
                    "subtype": "action_type",
                    "name": title,
                }
                # If no name from link, use action type as name
                if not ability_name:
                    ability_name = title

        # Collect content elements after h3 until next h3 ability (or end)
        content_elements = []
        current = h3.next_sibling
        while current:
            if next_h3 and current is next_h3:
                break
            content_elements.append(current)
            current = current.next_sibling

        # Build HTML from content and parse into separate soup for analysis
        content_html = "".join(str(e) for e in content_elements)
        content_soup = BeautifulSoup(content_html, "html.parser")

        # Split on <hr> — before is fields (Source, Frequency, etc.), after is effect
        hr = content_soup.find("hr")
        if hr:
            field_parts = []
            for elem in list(content_soup.children):
                if elem is hr:
                    break
                field_parts.append(str(elem))
            effect_parts = []
            found_hr = False
            for elem in list(content_soup.children):
                if elem is hr:
                    found_hr = True
                    continue
                if found_hr:
                    effect_parts.append(str(elem))
            field_html = "".join(field_parts)
            effect_html = "".join(effect_parts)
        else:
            field_html = ""
            effect_html = content_html

        field_soup = BeautifulSoup(field_html, "html.parser")
        effect_soup = BeautifulSoup(effect_html, "html.parser")

        # Build ability dict
        ability = build_object("stat_block_section", "ability", ability_name)
        ability["ability_type"] = "offensive"

        if action_type:
            ability["action_type"] = action_type

        # Collect links — start with the action link from h3
        ability_links = []
        if action_link_obj:
            ability_links.append(action_link_obj)

        # Handle Source field — extract its link but don't add as a field
        source_bold = field_soup.find("b", string=lambda s: s and s.strip() == "Source")
        if source_bold:
            src_parts = []
            src_current = source_bold.next_sibling
            while src_current:
                if isinstance(src_current, Tag) and src_current.name in ("b", "br"):
                    break
                src_parts.append(str(src_current))
                src_current = src_current.next_sibling
            src_html = "".join(src_parts)
            if src_html:
                src_soup = BeautifulSoup(src_html, "html.parser")
                src_links = get_links(src_soup, unwrap=True)
                ability_links.extend(src_links)

        # Extract standard ability fields (Frequency, Requirements, etc.)
        for field in ABILITY_FIELD_NAMES:
            field_bold = field_soup.find("b", string=lambda s, f=field: s and s.strip() == f)
            if not field_bold:
                continue

            value_parts = []
            val_current = field_bold.next_sibling
            while val_current:
                if isinstance(val_current, Tag) and val_current.name in (
                    "b",
                    "br",
                    "hr",
                ):
                    break
                value_parts.append(str(val_current))
                val_current = val_current.next_sibling
            value_html = "".join(value_parts).strip()

            if value_html:
                value_text, value_links = extract_links(value_html)
                value_text = _normalize_whitespace(value_text)

                field_key = field.lower().replace(" ", "_")
                if field_key == "requirements":
                    field_key = "requirement"

                ability[field_key] = value_text
                ability_links.extend(value_links)

        # Extract effect text and links
        effect_links = get_links(effect_soup, unwrap=True)
        ability_links.extend(effect_links)
        effect_text = _normalize_whitespace(effect_soup.get_text())
        if effect_text:
            ability["effect"] = effect_text

        if ability_links:
            ability["links"] = ability_links

        abilities.append(ability)

        if debug:
            sys.stderr.write(
                f"DEBUG _extract_h3_abilities: extracted '{ability_name}' "
                f"with {len(ability_links)} links\n"
            )

        # Remove h3 and its content from desc_soup
        for elem in content_elements:
            if isinstance(elem, Tag):
                elem.decompose()
            elif isinstance(elem, NavigableString):
                elem.extract()
        h3.decompose()

    # Add abilities to stat block
    if abilities:
        stats = sb.setdefault(
            "statistics",
            {"type": "stat_block_section", "subtype": "statistics"},
        )
        existing_abilities = stats.setdefault("abilities", [])
        existing_abilities.extend(abilities)

    return 0


def _find_ability_bolds(bs):
    """Find all ability-starting bold tags in the soup.

    Identifies two kinds of ability starters:
    1. <b>Activate</b> tags
    2. Bold tags followed by action icon spans (named abilities like "Divert Lightning [reaction]")

    Skips sub-field bolds (Frequency, Trigger, etc.) and named activation bolds
    (em-dash prefixed, which follow an Activate).

    Args:
        bs: BeautifulSoup object to search

    Returns:
        list[Tag]: Bold tags that start new abilities
    """
    sub_field_names = {
        "Frequency",
        "Trigger",
        "Effect",
        "Requirements",
        "Critical Success",
        "Success",
        "Failure",
        "Critical Failure",
        "Destruction",
    }
    ability_bolds = []
    for bold in bs.find_all("b"):
        bold_text = bold.get_text().strip()
        if bold_text == "Activate":
            ability_bolds.append(bold)
            continue
        if bold_text in sub_field_names:
            continue
        if bold_text and (bold_text[0] in "\u2014\u2013-" or ord(bold_text[0]) == 226):
            continue
        next_sib = bold.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and not next_sib.strip():
            next_sib = next_sib.next_sibling
        if (
            isinstance(next_sib, Tag)
            and next_sib.name == "span"
            and "action" in next_sib.get("class", [])
        ):
            ability_bolds.append(bold)
    return ability_bolds


def _collect_equipment_ability_content(ability_bold, next_ability, remaining_bolds):
    """Collect HTML content for a single equipment ability.

    Walks siblings from the ability bold to the next ability bold (or end),
    collecting all content that belongs to this ability.

    Args:
        ability_bold: The bold Tag that starts this ability
        next_ability: The bold Tag of the next ability (or None)
        remaining_bolds: List of all subsequent ability bold Tags

    Returns:
        tuple: (ability_html, ability_elements) where:
            - ability_html: concatenated HTML string of the ability
            - ability_elements: list of DOM elements for later removal
    """
    ability_parts = [str(ability_bold)]
    ability_elements = [ability_bold]
    current = ability_bold.next_sibling

    while current:
        if next_ability and current is next_ability:
            break
        if any(current is ab for ab in remaining_bolds):
            break
        if isinstance(current, Tag) and current.name == "hr":
            break
        ability_parts.append(str(current))
        ability_elements.append(current)
        current = current.next_sibling

    return "".join(ability_parts), ability_elements


def _collect_front_matter_action_spans(ability_soup, semicolon_pos):
    """Collect action spans from the front matter of ability HTML.

    Scans for action spans that appear before the first semicolon separator.
    Detects connector text ("to" or "or") between spans.

    Args:
        ability_soup: BeautifulSoup object of the ability content
        semicolon_pos: Position of first semicolon in text, or -1 if none

    Returns:
        Tuple of (action_titles, connector, front_matter_spans) where
        action_titles is a deduplicated list of canonical action names,
        connector is "to" or "or", and front_matter_spans is the list
        of span elements to decompose.
    """
    action_spans = ability_soup.find_all("span", class_="action")
    action_titles = []
    connector = "or"  # default connector between action spans
    front_matter_spans = []
    for action_span in action_spans:
        # Check if this span appears before the first semicolon
        preceding_text = ""
        for prev in action_span.previous_siblings:
            text = prev.get_text() if hasattr(prev, "get_text") else str(prev)
            preceding_text = text + preceding_text
        span_text_pos = len(preceding_text)

        if semicolon_pos >= 0 and span_text_pos >= semicolon_pos:
            continue

        # Detect connector text ("to" or "or") before this span
        prev_sib = action_span.previous_sibling
        if prev_sib and isinstance(prev_sib, NavigableString):
            prev_text = prev_sib.strip()
            if prev_text == "to":
                connector = "to"
            elif prev_text == "or":
                connector = "or"

        action_title = action_span.get("title", "")
        if action_title:
            if action_title == "Single Action":
                action_title = "One Action"
            action_titles.append(action_title)
        front_matter_spans.append(action_span)

    # Decompose front-matter spans and their connector text
    for action_span in front_matter_spans:
        prev_sib = action_span.previous_sibling
        if (
            prev_sib
            and isinstance(prev_sib, NavigableString)
            and prev_sib.strip()
            in (
                "to",
                "or",
            )
        ):
            prev_sib.extract()
        action_span.decompose()

    # Deduplicate (nested abilities in <ul><li> can cause duplicates)
    seen = set()
    unique_titles = []
    for t in action_titles:
        if t not in seen:
            seen.add(t)
            unique_titles.append(t)

    return unique_titles, connector, front_matter_spans


_ACTION_NAME_MAP = {
    ("One Action", "to", "Two Actions"): "One or Two Actions",
    ("One Action", "to", "Three Actions"): "One to Three Actions",
    ("One Action", "or", "Two Actions"): "One or Two Actions",
    ("One Action", "or", "Three Actions"): "One to Three Actions",
    ("Two Actions", "to", "Three Actions"): "Two to Three Actions",
    ("Two Actions", "or", "Three Actions"): "Two or Three Actions",
    ("Free Action", "or", "One Action"): "Free Action or Single Action",
    ("Reaction", "or", "One Action"): "Reaction or One Action",
}


def _resolve_action_name(action_titles, connector):
    """Resolve a list of action titles and connector to a canonical action name.

    Args:
        action_titles: List of canonical action title strings (e.g., ["One Action", "Three Actions"])
        connector: "to" or "or"

    Returns:
        Canonical action name string (e.g., "One to Three Actions")
    """
    if len(action_titles) == 2:
        key = (action_titles[0], connector, action_titles[1])
        action_name = _ACTION_NAME_MAP.get(key)
        assert action_name, f"Unknown action type combo: {key}"
        return action_name
    elif len(action_titles) == 3:
        assert action_titles == [
            "One Action",
            "Two Actions",
            "Three Actions",
        ], f"Unknown 3-span action combo: {action_titles}"
        return "One to Three Actions"
    else:
        raise AssertionError(
            f"Unexpected number of action spans: {len(action_titles)}: {action_titles}"
        )


def _extract_action_type_from_spans(ability_soup):
    """Extract action type from action icon spans in ability HTML.

    Only extracts action spans from the FRONT of the ability (before the first
    semicolon separator). Action icons deeper in the text (inside Frequency,
    Effect, etc.) are part of the description, not the action type.

    Decomposes the front-matter spans from the soup as a side effect.

    Args:
        ability_soup: BeautifulSoup object of the ability content

    Returns:
        dict or None: Action type object, or None if no action spans found
    """
    full_text = ability_soup.get_text()
    semicolon_pos = full_text.find(";")

    action_titles, connector, _ = _collect_front_matter_action_spans(ability_soup, semicolon_pos)

    if not action_titles:
        return None

    if len(action_titles) == 1:
        # Check for "or more" text following the decomposed action span
        for child in list(ability_soup.children):
            if isinstance(child, NavigableString) and child.strip().startswith("or more"):
                child.replace_with(NavigableString(child.replace("or more", "", 1)))
                return {
                    "type": "stat_block_section",
                    "subtype": "action_type",
                    "name": action_titles[0] + " or more",
                }
        return {
            "type": "stat_block_section",
            "subtype": "action_type",
            "name": action_titles[0],
        }

    action_name = _resolve_action_name(action_titles, connector)
    return {
        "type": "stat_block_section",
        "subtype": "action_type",
        "name": action_name,
    }


def _deduplicate_links_across_abilities(abilities):
    """Remove duplicate links across abilities, keeping the later (more specific) copy.

    When a nested Activate is inside a <ul><li> that's a sibling of an earlier ability,
    sibling traversal includes the <ul> in the earlier ability's content, causing links
    from the nested ability to appear in both. This removes such duplicates from earlier
    abilities. Does NOT deduplicate within a single ability (same spell can appear at
    multiple levels in staves).

    Args:
        abilities: List of ability dicts to deduplicate. Modified in place.

    Returns:
        int: Count of links removed (for link accounting).
    """
    removed_count = 0
    if len(abilities) <= 1:
        return 0
    for i in range(len(abilities) - 1):
        if "links" not in abilities[i]:
            continue
        later_links = set()
        for j in range(i + 1, len(abilities)):
            for link in abilities[j].get("links", []):
                later_links.add((link.get("name"), link.get("game-obj", link.get("href", ""))))
        original_count = len(abilities[i]["links"])
        unique_links = [
            link
            for link in abilities[i]["links"]
            if (link.get("name"), link.get("game-obj", link.get("href", ""))) not in later_links
        ]
        removed_count += original_count - len(unique_links)
        abilities[i]["links"] = unique_links
        if not abilities[i]["links"]:
            del abilities[i]["links"]
    return removed_count


def _clean_activation_cruft_from_text(sb):
    """Remove activation patterns from stat block text after abilities are extracted.

    Cleans up patterns like "**Activate** command; **Frequency** ..." from sb["text"]
    that were already extracted into the abilities array.

    Args:
        sb: Stat block dict whose "text" field may contain activation cruft
    """
    if "text" not in sb or not sb["text"]:
        return
    text = sb["text"]
    text = re.sub(
        r"(?:<br\s*/?>[\s\n]*)*\s*(?:<b>\s*Activate\s*</b>|\*\*Activate\*\*).*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = text.strip()
    if text:
        sb["text"] = text
    else:
        del sb["text"]


def _skip_leading_whitespace(start_node):
    """Skip leading whitespace NavigableString nodes.

    Args:
        start_node: Starting node to examine

    Returns:
        Tuple of (first_non_whitespace_node, whitespace_nodes_to_remove)
    """
    nodes_to_remove = []
    current = start_node
    while current and isinstance(current, NavigableString) and not current.strip():
        nodes_to_remove.append(current)
        current = current.next_sibling
    return current, nodes_to_remove


def _clean_activate_content(content):
    """Clean activation content by removing leading/trailing semicolons and 'to'/'or' prefixes.

    Args:
        content: Raw activation content string

    Returns:
        Cleaned content string
    """
    content = content.strip()
    content = re.sub(r"^[\s;]+", "", content)
    content = re.sub(r"[\s;]+$", "", content)
    content = re.sub(r"^\s*(to|or)\s+", "", content, flags=re.IGNORECASE)
    return content


def _process_activate_content(ability_soup, ability):
    """Process an Activate ability's content: extract named activation, activation types, and traits.

    Finds the Activate bold in the ability soup, walks siblings to collect the activation
    content (before the first sub-field bold), then parses it via _parse_activation_content.
    Cleans up the processed nodes from the soup as a side effect.

    Args:
        ability_soup: BeautifulSoup object of the ability content
        ability: dict to populate with activation fields

    Returns:
        int: Count of trait links converted (for link accounting)
    """
    activate_bold = ability_soup.find("b", string=lambda s: s and s.strip() == "Activate")
    if not activate_bold:
        return 0

    current, nodes_to_remove = _skip_leading_whitespace(activate_bold.next_sibling)

    ability_name, current = _parse_named_activation(current)
    if ability_name:
        ability["ability_name"] = ability_name

    # Collect activation line content until next sub-field bold OR <br>.
    # Stop at <br> to avoid consuming description text that follows the
    # activation line (e.g., Archaic Wayfinder's description with "aeon stone" link).
    content_parts = []
    content_nodes = []
    while current:
        if isinstance(current, Tag):
            if current.name == "b":
                break
            if current.name == "br":
                content_nodes.append(current)
                break
        content_parts.append(str(current))
        content_nodes.append(current)
        current = current.next_sibling
    nodes_to_remove.extend(content_nodes)

    _remove_soup_nodes(nodes_to_remove)

    activate_content = _clean_activate_content("".join(content_parts))
    trait_links_converted = 0
    if activate_content:
        trait_links_converted = _parse_activation_content(activate_content, ability)

    ability["subtype"] = "activation"
    if "ability_name" in ability:
        ability["activation_name"] = ability.pop("ability_name")

    return trait_links_converted


def _extract_abilities_from_description(bs, sb, struct=None, debug=False, equipment_type=None):
    """Extract offensive abilities (Activate, etc.) from content after description.

    These appear as bold-labeled lines after the description text:
    <b>Activate</b> [action] command (traits); <b>Frequency</b> ...; <b>Trigger</b> ...; <b>Effect</b> ...

    Items can have multiple Activate abilities, each starting with <b>Activate</b>.

    Extracts them into statistics.abilities array.
    Returns the count of trait links converted (for link accounting).

    Args:
        bs: BeautifulSoup object containing the content
        sb: Stat block dict to add abilities to
        struct: Parent structure (optional if equipment_type provided)
        debug: Enable debug output
        equipment_type: Override equipment type (for variants without full struct)

    NOTE: This is only for generic equipment. Vehicles and siege weapons have their
    abilities (including Activate) extracted by _extract_abilities() instead.
    """
    # Skip for vehicles and siege weapons - they already have ability extraction via _extract_abilities
    if equipment_type is None:
        equipment_type = struct.get("type", "") if struct else ""
    if equipment_type in ("vehicle", "siege_weapon"):
        return 0

    ability_bolds = _find_ability_bolds(bs)
    if not ability_bolds:
        return 0

    # Count per-(name, game-obj) link occurrences in desc soup BEFORE extraction.
    # Used after dedup to distinguish genuine HTML duplicates from sibling artifacts.
    desc_link_counts = {}
    for link in get_links(bs, unwrap=False):
        key = (link.get("name"), link.get("game-obj", link.get("href", "")))
        desc_link_counts[key] = desc_link_counts.get(key, 0) + 1

    trait_links_converted = 0
    abilities = []
    elements_to_remove = []

    for i, ability_bold in enumerate(ability_bolds):
        bold_text = ability_bold.get_text().strip()
        is_activate = bold_text == "Activate"

        next_ability = ability_bolds[i + 1] if i + 1 < len(ability_bolds) else None
        ability_html, ability_elements = _collect_equipment_ability_content(
            ability_bold, next_ability, ability_bolds[i + 1 :]
        )
        elements_to_remove.extend(ability_elements)

        ability_soup = BeautifulSoup(ability_html, "html.parser")

        ability = build_object("stat_block_section", "ability", bold_text)
        ability["ability_type"] = "offensive"

        action_type = _extract_action_type_from_spans(ability_soup)
        if action_type:
            ability["action_type"] = action_type

        _extract_ability_fields(ability_soup, ability)

        if is_activate:
            trait_links_converted += _process_activate_content(ability_soup, ability)

        # Sweep remaining links not handled by sub-field or activation parsing
        for remaining_a in ability_soup.find_all("a"):
            if "PFS.aspx" in remaining_a.get("href", ""):
                continue
            _, link = extract_link(remaining_a)
            if link:
                if "links" not in ability:
                    ability["links"] = []
                ability["links"].append(link)

        abilities.append(ability)

    if debug:
        for ab_idx, ab in enumerate(abilities):
            ab_links = ab.get("links", [])
            sys.stderr.write(
                f"DEBUG PRE-DEDUP ability[{ab_idx}] '{ab.get('name', '?')}': {len(ab_links)} links: {[(l.get('name'), l.get('game-obj')) for l in ab_links]}\n"
            )
    # Count pre-dedup per-pair occurrences across abilities
    pre_dedup_pairs = {}
    for ab in abilities:
        for l in ab.get("links", []):
            key = (l.get("name"), l.get("game-obj", l.get("href", "")))
            pre_dedup_pairs[key] = pre_dedup_pairs.get(key, 0) + 1

    dedup_removed = _deduplicate_links_across_abilities(abilities)

    # Compute genuine_dedup: how many of the deduped removals correspond to
    # genuinely different HTML <a> tags (vs sibling traversal artifacts that
    # collected the same <a> tag into multiple ability soups).
    # For each deduped pair: genuine = min(times_deduped, html_occurrences - 1)
    genuine_dedup = 0
    if dedup_removed > 0:
        post_dedup_pairs = {}
        for ab in abilities:
            for l in ab.get("links", []):
                key = (l.get("name"), l.get("game-obj", l.get("href", "")))
                post_dedup_pairs[key] = post_dedup_pairs.get(key, 0) + 1
        for key, pre_count in pre_dedup_pairs.items():
            post_count = post_dedup_pairs.get(key, 0)
            if pre_count > post_count:
                html_count = desc_link_counts.get(key, 1)
                genuine_dedup += min(pre_count - post_count, max(0, html_count - 1))
    trait_links_converted += genuine_dedup

    if debug:
        sys.stderr.write(
            f"DEBUG _extract_abilities: trait_links_converted={trait_links_converted}, dedup_removed={dedup_removed}, genuine_dedup={genuine_dedup}, n_abilities={len(abilities)}\n"
        )
        for ab in abilities:
            ab_links = ab.get("links", [])
            sys.stderr.write(
                f"  ability '{ab.get('name', '?')}': {len(ab_links)} links: {[(l.get('name'), l.get('game-obj')) for l in ab_links]}\n"
            )

    # Remove all ability elements from original soup
    # Use getattr for .parent — decompose() on a parent tag destroys descendants,
    # so later elements in the list may already be detached.
    for elem in elements_to_remove:
        if hasattr(elem, "decompose") and getattr(elem, "parent", None) is not None:
            elem.decompose()
        elif isinstance(elem, NavigableString) and getattr(elem, "parent", None) is not None:
            elem.extract()

    if abilities:
        if "statistics" not in sb:
            sb["statistics"] = {"type": "stat_block_section", "subtype": "statistics"}
        if "abilities" not in sb["statistics"]:
            sb["statistics"]["abilities"] = []
        sb["statistics"]["abilities"].extend(abilities)
        _clean_activation_cruft_from_text(sb)

    return trait_links_converted


def _extract_alternate_link(bs, struct):
    """Extract alternate edition link (legacy/remastered) from siderbarlook div.

    The alternate link appears in a <div class="siderbarlook"> containing text like:
    - "There is a Legacy version <a>here</a>."
    - "There is a Remastered version <a>here</a>."

    This should be extracted as an alternate_link at the top level of the struct.
    """
    from universal.universal import extract_link

    # Find the siderbarlook div
    sidebar_div = bs.find("div", class_="siderbarlook")
    if not sidebar_div:
        return

    # Check if it contains alternate version text
    div_text = get_text(sidebar_div)
    if "Legacy version" not in div_text and "Remastered version" not in div_text:
        return

    # Extract the link
    link_tag = sidebar_div.find("a", attrs={"game-obj": True})
    if not link_tag:
        return

    # Build the alternate_link object
    _, link = extract_link(link_tag)

    # Remove fields not needed for alternate_link
    if "alt" in link:
        del link["alt"]
    if "name" in link:
        del link["name"]

    # Set the type and alternate_type
    link["type"] = "alternate_link"
    if "Legacy version" in div_text:
        link["alternate_type"] = "legacy"
    else:
        link["alternate_type"] = "remastered"

    # Add to struct
    struct["alternate_link"] = link

    # Remove the div so it's not counted again
    sidebar_div.decompose()


def _cleanup_stat_block(sb):
    """Clean up stat_block after extraction.

    Note: text and links now remain in stat_block (not moved to top level).
    """
    # Previously deleted text here, but now text stays in stat_block
    pass


def _remove_empty_values_pass(obj):
    """Recursively remove empty lists and empty strings from the structure."""
    if isinstance(obj, dict):
        keys_to_delete = []
        for key, value in obj.items():
            if isinstance(value, list):
                if len(value) == 0:
                    keys_to_delete.append(key)
                else:
                    for item in value:
                        _remove_empty_values_pass(item)
                    # Re-check after recursion — items may have been pruned
                    obj[key] = [v for v in value if v != {} and v != []]
                    if len(obj[key]) == 0:
                        keys_to_delete.append(key)
            elif isinstance(value, dict):
                _remove_empty_values_pass(value)
        for key in keys_to_delete:
            del obj[key]
    elif isinstance(obj, list):
        for item in obj:
            _remove_empty_values_pass(item)


def normalize_numeric_fields_pass(struct, config):
    """Convert numeric string fields to integers and structure complex fields.
    Calls equipment-specific normalizer function from config.

    Returns:
        int: Number of trait links converted to trait objects (for link accounting)
    """
    # Access stat_block after it's been moved to top level by restructure_pass
    sb = struct.get("stat_block")
    if not sb:
        return 0

    # Call equipment-specific normalizer function
    normalizer = config.get("normalize_fields")
    result = 0
    if normalizer:
        result = normalizer(sb) or 0

    # Universal: extract parenthesized modifiers from usage fields
    # Applies to all equipment types (equipment, siege_weapon, vehicle, etc.)
    for container in [sb, sb.get("siege_weapon"), sb.get("vehicle"), sb.get("statistics")]:
        if container and "usage" in container:
            usage = container["usage"]
            if isinstance(usage, str):
                usage = {
                    "type": "stat_block_section",
                    "subtype": "usage",
                    "text": usage.strip(),
                }
                container["usage"] = usage
            if isinstance(usage, dict):
                _extract_usage_modifiers(usage)
            else:
                raise ValueError(f"Unexpected usage type {type(usage)}: {usage}")

    return result


def _normalize_int_field(sb, field_name):
    """Convert a string field to integer, stripping + prefix."""
    if field_name not in sb:
        return

    value = sb[field_name]
    if not value:
        return

    # Em dash means no value - remove the field
    if value.strip() == "—":
        del sb[field_name]
        return

    # Strip leading + sign
    if value.startswith("+"):
        value = value[1:]

    # Parse to int
    sb[field_name] = int(value.strip())


def _normalize_strength(sb):
    """Convert strength string to structured stat requirement object with legacy and remastered values."""
    if "strength" not in sb:
        return

    value_str = sb["strength"]
    if not value_str:
        return

    # Em dash means no strength requirement - remove the field
    if value_str.strip() == "—":
        del sb["strength"]
        return

    # Check if this is a modifier (starts with +) or a stat value
    is_modifier = value_str.startswith("+")

    # Strip leading + sign
    if is_modifier:
        value_str = value_str[1:]

    # Parse to int
    value = int(value_str.strip())

    if is_modifier:
        # Value is a modifier (remastered format like +3)
        # Calculate stat value: modifier * 2 + 10
        modifier = value
        stat_value = modifier * 2 + 10
    else:
        # Value is a stat (legacy format like 16)
        # Calculate modifier: (stat - 10) / 2
        stat_value = value
        modifier = (stat_value - 10) // 2

    # Create stat requirement object and rename to schema-expected field name
    del sb["strength"]
    sb["strength_requirement"] = {
        "type": "stat_block_section",
        "subtype": "stat_requirement",
        "stat": "strength",
        "legacy_value": stat_value,
        "remastered_value": modifier,
    }


def _normalize_ac_bonus(sb, bonus_type="armor"):
    """Convert ac_bonus string to structured bonus object.

    Args:
        sb: stat block dict
        bonus_type: 'armor' for armor, 'shield' for shields
    """
    if "ac_bonus" not in sb:
        return

    value_str = sb["ac_bonus"]
    if not value_str:
        return

    # Em dash means no AC bonus - remove the field
    if value_str.strip() == "—":
        del sb["ac_bonus"]
        return

    # Handle conditional bonuses like "+2 (+4)" - take only the base value
    if "(" in value_str:
        value_str = value_str.split("(")[0].strip()

    # Strip leading + sign
    if value_str.startswith("+"):
        value_str = value_str[1:]

    # Parse to int
    value = int(value_str.strip())
    # Create bonus object with appropriate bonus_type
    sb["ac_bonus"] = {
        "type": "bonus",
        "subtype": "ac",
        "bonus_type": bonus_type,
        "bonus_value": value,
    }


def _normalize_dex_cap(sb):
    """Convert dex_cap string to structured bonus object."""
    if "dex_cap" not in sb:
        return

    value_str = sb["dex_cap"]
    if not value_str:
        return

    # Em dash means no dex cap - remove the field
    if value_str.strip() == "—":
        del sb["dex_cap"]
        return

    # Strip leading + sign
    if value_str.startswith("+"):
        value_str = value_str[1:]

    # Parse to int
    cap = int(value_str.strip())
    # Create bonus object for dexterity cap (limits dexterity bonus to AC)
    sb["dex_cap"] = {"type": "bonus", "subtype": "ac", "bonus_type": "dexterity", "bonus_cap": cap}


def _normalize_check_penalty(sb):
    """Convert check_penalty string to bonus object."""
    if "check_penalty" not in sb:
        return

    value_str = sb["check_penalty"]
    if not value_str:
        return

    # Em dash means no check penalty - remove the field
    if value_str.strip() == "—":
        del sb["check_penalty"]
        return

    # Strip leading - or + sign
    if value_str.startswith("-") or value_str.startswith("+"):
        value_str = value_str[1:]

    # Parse to int
    value = int(value_str.strip())
    # Check penalties are always negative
    if value > 0:
        value = -value
    # Create bonus object for check penalty (skill bonus type)
    sb["check_penalty"] = {
        "type": "bonus",
        "subtype": "skill",
        "bonus_type": "armor",
        "bonus_value": value,
    }


def _normalize_speed_penalty(sb, bonus_type="armor"):
    """Convert speed_penalty string to bonus object.

    Args:
        sb: stat block dict
        bonus_type: 'armor' for armor, 'shield' for shields
    """
    if "speed_penalty" not in sb:
        return

    value_str = sb["speed_penalty"]
    if not value_str:
        return

    # Em dash means no speed penalty - remove the field
    if value_str.strip() == "—":
        del sb["speed_penalty"]
        return

    # Extract unit and value
    unit = None
    if value_str.endswith(" ft."):
        unit = "feet"
        value_str = value_str[:-4]

    # Parse to int
    value = int(value_str.strip())
    # Speed penalties are always negative
    if value > 0:
        value = -value
    # Create bonus object for speed penalty with appropriate bonus_type
    speed_obj = {
        "type": "bonus",
        "subtype": "speed",
        "bonus_type": bonus_type,
        "bonus_value": value,
    }
    if unit:
        speed_obj["unit"] = unit
    sb["speed_penalty"] = speed_obj


def _split_compound_bulk(value_str):
    """Split compound bulk values like "- varies" or "- when not activated".

    Handles three patterns:
    - "- L (...)" or "- varies": dash is noise, use remainder as value
    - "- when not activated": dash is the bulk, rest becomes a modifier
    - Non-compound values: returned unchanged

    Args:
        value_str: Bulk string (already stripped and mdash-converted)

    Returns:
        Tuple of (value_str, modifiers) where value_str is the resolved
        bulk value and modifiers is a list of modifier dicts.
    """
    modifiers = []
    if re.match(r"^-\s+\S", value_str):
        parts = value_str.split(None, 1)  # split on first whitespace
        remainder = parts[1] if len(parts) > 1 else ""
        # Check if remainder is itself a bulk value (e.g., "L", "varies")
        if re.match(r"^L\b", remainder) or remainder.startswith("varies"):
            value_str = remainder
        else:
            value_str = "-"
            modifiers.append(
                {"type": "stat_block_section", "subtype": "modifier", "name": remainder}
            )
    return value_str, modifiers


def _normalize_bulk(sb):
    """Convert bulk string to structured bulk object.

    Parses bulk strings like:
    - "L", "-", "1", "2" (simple values)
    - "L (when not activated)" (with modifier)
    - "1 (3 unfolded)" (with modifier)
    - "varies by armor" (text value)

    Returns object with:
    - type: "stat_block_section"
    - subtype: "bulk"
    - value: integer bulk value (or null for L, -, varies, etc.)
    - text: the base bulk text without modifiers
    - modifiers: list of modifier objects (if parentheses found)
    """
    if "bulk" not in sb:
        return

    value_str = sb["bulk"]
    if not value_str:
        return

    # Skip if already normalized to object
    if isinstance(value_str, dict):
        return

    value_str = value_str.strip()

    # Convert mdash to dash
    value_str = value_str.replace("—", "-")

    # Split compound bulk values
    value_str, modifiers = _split_compound_bulk(value_str)

    # Extract modifier from parentheses if present
    base_value = value_str
    if "(" in value_str and ")" in value_str:
        paren_start = value_str.find("(")
        paren_end = value_str.rfind(")")
        if paren_end > paren_start:
            modifier_text = value_str[paren_start + 1 : paren_end].strip()
            base_value = value_str[:paren_start].strip()
            # Also capture any text after the closing paren
            after_paren = value_str[paren_end + 1 :].strip()
            if after_paren:
                base_value = base_value + " " + after_paren if base_value else after_paren
            if modifier_text:
                modifiers.append(
                    {"type": "stat_block_section", "subtype": "modifier", "name": modifier_text}
                )

    # Determine the numeric value
    int_value = None
    if base_value == "-":
        # Dash means no bulk value
        pass
    elif base_value == "L":
        # "L" (light) gets null for integer value
        pass
    elif base_value.isdigit():
        # Parse as integer
        int_value = int(base_value)

    # Build bulk object
    bulk_obj = {
        "type": "stat_block_section",
        "subtype": "bulk",
        "value": int_value,
        "text": base_value,
    }

    if modifiers:
        bulk_obj["modifiers"] = modifiers

    sb["bulk"] = bulk_obj


def _normalize_price(sb):
    """Convert price string to structured price object.

    Parses price strings like:
    - "3,000 gp"
    - "3,000 gp (can't be crafted)"
    - "varies"
    - "—"

    Returns object with:
    - type: "stat_block_section"
    - subtype: "price"
    - value: integer price value (or null if not parseable)
    - currency: "gp", "sp", "cp", or "pp" (if found)
    - text: the price text without modifiers
    - modifiers: list of modifier objects (if parentheses found)
    """
    if "price" not in sb:
        return

    value_str = sb["price"]
    if not value_str or not isinstance(value_str, str):
        return

    value_str = value_str.strip()

    # Convert mdash to dash
    value_str = value_str.replace("—", "-")

    # Initialize price object
    price_obj = {
        "type": "stat_block_section",
        "subtype": "price",
    }

    # Extract modifiers from parentheses
    modifier_texts = re.findall(r"\(([^)]+)\)", value_str)
    main_text = re.sub(r"\s*\([^)]+\)", "", value_str).strip()

    # Store the main text (without modifiers)
    price_obj["text"] = main_text

    # Parse currency and value
    # Pattern: optional number with commas, followed by currency code
    currency_match = re.search(r"^([\d,]+)\s*(gp|sp|cp|pp)\b", main_text, re.IGNORECASE)
    if currency_match:
        # Extract numeric value (remove commas)
        value_with_commas = currency_match.group(1)
        price_obj["value"] = int(value_with_commas.replace(",", ""))
        price_obj["currency"] = currency_match.group(2).lower()
    else:
        # No parseable price (e.g., "varies", "—", or complex text)
        price_obj["value"] = None

    # Add modifiers if present
    if modifier_texts:
        modifier_names = []
        for mod_text in modifier_texts:
            modifier_names.extend(m.strip() for m in mod_text.split(";") if m.strip())
        if modifier_names:
            price_obj["modifiers"] = build_objects("stat_block_section", "modifier", modifier_names)

    sb["price"] = price_obj


# Equipment-specific field normalizers
def normalize_armor_fields(sb):
    """Normalize armor-specific fields."""
    # Normalize shared fields at top level
    _normalize_bulk(sb)
    _normalize_price(sb)

    # Normalize statistics fields
    if "statistics" in sb:
        stats_obj = sb["statistics"]
        # Strength requirement object (with legacy and remastered values)
        _normalize_strength(stats_obj)

    # Normalize defense fields
    if "defense" in sb:
        defense_obj = sb["defense"]
        # Bonus objects (for stacking rules)
        _normalize_ac_bonus(defense_obj)
        _normalize_dex_cap(defense_obj)
        _normalize_check_penalty(defense_obj)
        _normalize_speed_penalty(defense_obj)


def _normalize_favored_weapon(weapon_obj):
    """Normalize favored_weapon field from HTML string to structured object with text and links.

    Input: "<u><a href='Deities.aspx?ID=72' game-obj='Deities' aonid='72'>Angazhan</a></u>, <u><a ...>Irori</a></u>, ..."
    Output: {"text": "Angazhan, Green Faith, Irori, ...", "links": [{...}, {...}, ...]}
    """
    if "favored_weapon" not in weapon_obj:
        return

    html_str = weapon_obj["favored_weapon"]
    # Empty field cleanup is handled by a separate pass - don't delete here

    # Parse HTML to extract text and links
    soup = BeautifulSoup(html_str, "html.parser")
    links = get_links(soup, unwrap=True)  # Extract links and unwrap <a> tags

    # Get cleaned text
    text = _normalize_whitespace(str(soup))

    # Build structured object
    favored_weapon = {"type": "stat_block_section", "subtype": "favored_weapon", "text": text}
    if links:
        favored_weapon["links"] = links

    weapon_obj["favored_weapon"] = favored_weapon


def _normalize_ammunition(obj):
    """Normalize ammunition field from HTML string to structured object with text and links.

    Works for both weapon-level ammunition and mode-level ammunition.
    Extracts modifiers from parentheses (e.g., "(10 rounds)") and strips HTML tags.

    Input: "<u><a href='Weapons.aspx?ID=211' game-obj='Weapons' aonid='211'>Firearm Ammunition (10 rounds)</a></u>"
    Output: {"type": "stat_block_section", "subtype": "ammunition", "text": "Firearm Ammunition",
             "modifier": "10 rounds", "links": [{...}]}
    """
    if "ammunition" not in obj:
        return

    html_str = obj["ammunition"]
    # Empty field cleanup is handled by a separate pass - don't delete here

    # Parse HTML to extract text and links
    soup = BeautifulSoup(html_str, "html.parser")
    links = get_links(soup, unwrap=True)  # Extract links and unwrap <a> tags

    # Get text without HTML tags (use get_text() to strip all tags)
    text = soup.get_text()
    text = _normalize_whitespace(text)

    # Extract modifier from parentheses at the end
    # Pattern: "Something (modifier)" -> text="Something", modifiers=[{"name": "modifier"}]
    modifier_name = None
    import re

    match = re.match(r"^(.+?)\s*\(([^)]+)\)$", text)
    if match:
        text = match.group(1).strip()
        modifier_name = match.group(2).strip()

        # Also update link names to remove modifier
        for link in links:
            if "name" in link and modifier_name:
                link_text = link["name"]
                # Remove modifier from link name if present
                link_match = re.match(r"^(.+?)\s*\([^)]+\)$", link_text)
                if link_match:
                    link["name"] = link_match.group(1).strip()

    # Build structured object
    ammunition = {"type": "stat_block_section", "subtype": "ammunition", "text": text}
    if modifier_name:
        # Modifiers are always an array of modifier objects
        from universal.universal import build_object, link_modifiers

        ammunition["modifiers"] = link_modifiers(
            [build_object("stat_block_section", "modifier", modifier_name)]
        )
    if links:
        ammunition["links"] = links

    obj["ammunition"] = ammunition


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["armor"]["normalize_fields"] = normalize_armor_fields


def normalize_weapon_fields(sb):
    """Normalize weapon-specific fields in melee/ranged mode objects."""

    # Normalize shared fields at top level
    _normalize_bulk(sb)
    _normalize_price(sb)

    # Normalize weapon-specific fields within weapon object
    if "weapon" in sb:
        weapon_obj = sb["weapon"]
        _normalize_hands(weapon_obj)
        _normalize_favored_weapon(weapon_obj)
        _normalize_ammunition(weapon_obj)  # Ammunition can be at weapon level

        # Normalize mode-specific fields within each mode object
        if "melee" in weapon_obj:
            _normalize_weapon_mode(weapon_obj["melee"])
        if "ranged" in weapon_obj:
            _normalize_weapon_mode(weapon_obj["ranged"])


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["weapon"]["normalize_fields"] = normalize_weapon_fields


def normalize_shield_fields(sb):
    """Normalize shield-specific fields."""
    # Normalize shared fields at top level
    _normalize_bulk(sb)
    _normalize_price(sb)

    # Normalize shield-specific fields within defense bucket
    if "defense" in sb:
        defense_obj = sb["defense"]
        # Bonus objects (for stacking rules) - shields use bonus_type 'shield'
        _normalize_ac_bonus(defense_obj, bonus_type="shield")
        _normalize_speed_penalty(defense_obj, bonus_type="shield")
        # Build hitpoints object from hp_bt, hardness, immunities fields
        _normalize_item_hitpoints(defense_obj)


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["shield"]["normalize_fields"] = normalize_shield_fields


def normalize_siege_weapon_fields(sb):
    """Normalize siege weapon-specific fields."""
    # Normalize shared fields at top level
    _normalize_price(sb)
    _normalize_bulk(sb)  # Portable siege weapons (rams) have bulk

    # Normalize siege weapon-specific fields within siege_weapon object
    if "siege_weapon" in sb:
        sw_obj = sb["siege_weapon"]
        # Normalize defensive stats (AC, Fort, Ref) - must come before hitpoints
        _normalize_defensive_stats(sw_obj)
        # Normalize speed field if present
        _normalize_speed(sw_obj)
        # Normalize ammunition field if present
        _normalize_ammunition(sw_obj)
        # Build hitpoints object from hp_bt, hardness, immunities fields
        # This must come last since it deletes the source fields
        _normalize_item_hitpoints(sw_obj)


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["siege_weapon"]["normalize_fields"] = normalize_siege_weapon_fields


def normalize_vehicle_fields(sb):
    """Normalize vehicle-specific fields."""
    # Normalize shared fields at top level
    # Note: vehicles don't have bulk
    _normalize_price(sb)

    # Normalize vehicle-specific fields within vehicle object
    if "vehicle" in sb:
        vehicle_obj = sb["vehicle"]
        # Normalize defensive stats (AC, Fort) - vehicles don't have Ref
        # Must come before hitpoints
        for field in ["ac", "fort"]:
            if field in vehicle_obj:
                _normalize_int_field(vehicle_obj, field)
        # Normalize speed field if present
        _normalize_speed(vehicle_obj)
        # Normalize piloting_check field (extract links from HTML)
        if "piloting_check" in vehicle_obj:
            _normalize_text_with_links(vehicle_obj, "piloting_check")
        # Parse weaknesses HTML into protection objects
        if "weaknesses" in vehicle_obj:
            weaknesses = _parse_immunities(vehicle_obj["weaknesses"], subtype="weakness")
            if weaknesses:
                vehicle_obj["weaknesses"] = weaknesses
            else:
                del vehicle_obj["weaknesses"]
        # Parse resistances HTML into protection objects
        if "resistances" in vehicle_obj:
            resistances = _parse_immunities(vehicle_obj["resistances"], subtype="resistance")
            if resistances:
                vehicle_obj["resistances"] = resistances
            else:
                del vehicle_obj["resistances"]
        # Build hitpoints object from hp_bt, hardness, immunities fields
        # This must come last since it deletes the source fields
        _normalize_vehicle_hitpoints(vehicle_obj)


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["vehicle"]["normalize_fields"] = normalize_vehicle_fields


def _html_to_stat_block_section(html_string, subtype):
    """Convert an HTML string to a stat_block_section object with text and links.

    Args:
        html_string: HTML string that may contain <a> tags
        subtype: The subtype for the stat_block_section (e.g., 'base_weapon')

    Returns:
        A dict with type, subtype, text, and optionally links array
    """
    # extract_links expects a string, returns (text_without_links, links_list)
    text, links = extract_links(html_string)

    # All links (including non-game-obj) are now tracked by link accounting

    result = {"type": "stat_block_section", "subtype": subtype, "text": text.strip()}

    if links:
        result["links"] = links

    return result


_USAGE_MODIFIER_RE = re.compile(r"\s*\(([^()]+)\)")


def _extract_usage_modifiers(usage_obj):
    """Extract parenthesized modifiers from a usage stat_block_section object.

    Modifies the object in-place: removes (...) from text and adds modifiers list.
    Skips '(s)' which is a pluralization marker, not a modifier.
    """
    text = usage_obj["text"]
    if "(" not in text:
        return

    modifiers = []
    for match in _USAGE_MODIFIER_RE.finditer(text):
        content = match.group(1).strip()
        if content == "s":
            continue
        modifiers.append(content)

    if not modifiers:
        return

    def _repl(m):
        if m.group(1).strip() == "s":
            return m.group(0)  # Keep plural marker
        return ""

    usage_obj["text"] = _USAGE_MODIFIER_RE.sub(_repl, text).strip()
    usage_obj["modifiers"] = modifiers_from_string_list(modifiers)


def normalize_equipment_fields(sb):
    """Normalize general equipment fields.

    Field routing already places fields in their destinations (statistics, offense, etc.).
    This function handles value transformations:
    - bulk: string -> bulk object
    - activate: string -> ability object in statistics.abilities
    - base_weapon: HTML string -> stat_block_section with links
    - ammunition: HTML string -> stat_block_section with links (if string)

    Returns:
        int: Number of trait links converted to trait objects (for link accounting)
    """
    trait_links_converted = 0

    # Normalize bulk (at stat_block level)
    _normalize_bulk(sb)

    # Normalize price (at stat_block level)
    _normalize_price(sb)

    # Normalize craft_requirements - extract links, normalize whitespace, and convert to plain text
    if "craft_requirements" in sb and isinstance(sb["craft_requirements"], str):
        cr_text, cr_links = extract_links(sb["craft_requirements"])
        # Normalize whitespace (collapse newlines from HTML formatting to single spaces)
        sb["craft_requirements"] = _normalize_whitespace(cr_text)
        if cr_links:
            if "links" not in sb:
                sb["links"] = []
            sb["links"].extend(cr_links)

    # Normalize destruction - extract links, normalize whitespace, and convert to plain text
    if "destruction" in sb and isinstance(sb["destruction"], str):
        d_text, d_links = extract_links(sb["destruction"])
        sb["destruction"] = _normalize_whitespace(d_text)
        if d_links:
            if "links" not in sb:
                sb["links"] = []
            sb["links"].extend(d_links)

    # Normalize special - extract links, normalize whitespace, and convert to plain text
    if "special" in sb and isinstance(sb["special"], str):
        sp_text, sp_links = extract_links(sb["special"])
        sb["special"] = _normalize_whitespace(sp_text)
        if sp_links:
            if "links" not in sb:
                sb["links"] = []
            sb["links"].extend(sp_links)

    # Convert activate string to ability in statistics.abilities
    # Activate is routed to statistics by field_destinations
    if "statistics" in sb and "activate" in sb["statistics"]:
        trait_links_converted += _normalize_activate_to_ability(sb["statistics"], sb)

    # Convert base_weapon and ammunition HTML strings to proper objects
    # These are routed to offense by field_destinations
    if "offense" in sb:
        offense = sb["offense"]
        if "base_weapon" in offense and isinstance(offense["base_weapon"], str):
            offense["base_weapon"] = _html_to_stat_block_section(
                offense["base_weapon"], "base_weapon"
            )
        if "ammunition" in offense and isinstance(offense["ammunition"], str):
            offense["ammunition"] = _html_to_stat_block_section(offense["ammunition"], "ammunition")

    # Convert base_armor and base_shield HTML strings to proper objects
    # These are routed to defense by field_destinations
    if "defense" in sb:
        defense = sb["defense"]
        if "base_armor" in defense and isinstance(defense["base_armor"], str):
            defense["base_armor"] = _html_to_stat_block_section(defense["base_armor"], "base_armor")
        if "base_shield" in defense and isinstance(defense["base_shield"], str):
            defense["base_shield"] = _html_to_stat_block_section(
                defense["base_shield"], "base_shield"
            )

    # Convert intelligent item stat HTML strings to proper objects with links
    # These are routed to statistics by field_destinations
    if "statistics" in sb:
        statistics = sb["statistics"]
        for field in ("access", "communication", "languages", "skills", "perception", "usage"):
            if field in statistics and isinstance(statistics[field], str):
                statistics[field] = _html_to_stat_block_section(statistics[field], field)
        # Hands may contain links (e.g., "1 or 2" linked to Rules) - extract links
        # but keep the text value for integer parsing later
        if (
            "hands" in statistics
            and isinstance(statistics["hands"], str)
            and "<a" in statistics["hands"]
        ):
            hands_text, hands_links = extract_links(statistics["hands"])
            statistics["hands"] = hands_text.strip()
            if hands_links:
                if "links" not in sb:
                    sb["links"] = []
                sb["links"].extend(hands_links)

    return trait_links_converted


def _move_to_statistics(sb, field_names):
    """Move fields from stat_block level into statistics sub-object.

    Args:
        sb: The stat_block dict
        field_names: List of field names to move into statistics
    """
    fields_to_move = {name: sb[name] for name in field_names if name in sb}
    if not fields_to_move:
        return

    # Ensure statistics exists
    if "statistics" not in sb:
        sb["statistics"] = {"type": "stat_block_section", "subtype": "statistics"}

    # Move fields
    for name, value in fields_to_move.items():
        sb["statistics"][name] = value
        del sb[name]


def _normalize_activate_to_ability(statistics, sb):
    """Convert activate HTML string to a proper ability object in statistics.abilities.

    The activate field contains HTML like:
    <span class="action" title="Single Action">[one-action]</span> Interact
    or with traits:
    <span class="action" title="Free Action">[free-action]</span> command (<a>divination</a>, <a>magical</a>)

    This should become an ability object with action_type in statistics.abilities.

    Args:
        statistics: The statistics sub-object containing the activate field
        sb: The parent stat_block (for legacy compatibility, not used with new routing)

    Returns:
        int: Number of trait links that were converted to trait objects (for link accounting)
    """
    activate_html = statistics.get("activate")
    if not activate_html:
        return 0

    trait_links_converted = 0

    # Parse the HTML and extract action type
    text, action_type = extract_action_type(activate_html)
    text = text.strip()

    # Build the ability object
    ability = build_object("stat_block_section", "ability", "Activate")
    ability["ability_type"] = "offensive"

    if action_type:
        ability["action_type"] = action_type

    if text:
        # Parse the remaining text to extract trait links and activation type
        text_soup = BeautifulSoup(text, "html.parser")

        # Extract all links (this unwraps them from the soup)
        all_links = get_links(text_soup, unwrap=True)

        # Get clean text after unwrapping
        clean_text = _normalize_whitespace(str(text_soup))

        # Separate trait links from other links
        trait_links = [link for link in all_links if link.get("game-obj") == "Traits"]
        other_links = [link for link in all_links if link.get("game-obj") != "Traits"]

        # Extract traits from parentheses (include unlinked traits for legacy activate field)
        traits, activation, remaining_trait_links, converted = (
            _extract_activation_traits_from_parens(
                clean_text, trait_links, include_unlinked_traits=True
            )
        )
        trait_links_converted = converted
        other_links.extend(remaining_trait_links)

        if traits:
            ability["traits"] = traits

        # Store activation types as list of objects
        if activation:
            ability["activation_types"] = _parse_activation_types(activation)

        # Add any non-trait links to the ability
        if other_links:
            ability["links"] = other_links

    # Transform "Activate" abilities into activation objects
    ability["subtype"] = "activation"

    # Add to statistics.abilities
    if "abilities" not in statistics:
        statistics["abilities"] = []

    statistics["abilities"].append(ability)

    # Remove the raw activate field from statistics
    del statistics["activate"]

    return trait_links_converted


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES["equipment"]["normalize_fields"] = normalize_equipment_fields

# Register section_pass hook functions in EQUIPMENT_TYPES config.
# Types without hooks use the default generic stat extraction path.
# armor, shield, equipment: use default (no hooks needed)
# siege_weapon, vehicle: custom stat extraction + abilities
EQUIPMENT_TYPES["siege_weapon"]["extract_stats_fxn"] = _extract_siege_weapon_stats_hook
EQUIPMENT_TYPES["siege_weapon"]["extract_abilities_fxn"] = _extract_abilities_hook
EQUIPMENT_TYPES["vehicle"]["extract_stats_fxn"] = _extract_vehicle_stats_hook
EQUIPMENT_TYPES["vehicle"]["extract_abilities_fxn"] = _extract_abilities_hook


def _normalize_text_with_links(sb, field_name):
    """Convert HTML text field with links to structured object with extracted links.

    Args:
        sb: stat block dict containing the field
        field_name: name of the field to normalize
    """
    if field_name not in sb:
        return

    html_text = sb[field_name]
    if not html_text:
        return

    # Parse HTML and extract links (unwrap=True removes <a> tags)
    bs = BeautifulSoup(html_text, "html.parser")
    links = get_links(bs, unwrap=True)

    # Get the text with links unwrapped
    text = clear_tags(str(bs), ["i"])

    # Create a structured object with text and links
    text_obj = {"type": "stat_block_section", "subtype": field_name, "text": text.strip()}

    if links:
        text_obj["links"] = links

    sb[field_name] = text_obj


def _normalize_vehicle_hitpoints(sb):
    """Build hitpoints object from hp_bt, hardness, and immunities fields.

    Note: weaknesses field stays separate at vehicle level (not in hitpoints).
    """
    if "hp_bt" not in sb and "hardness" not in sb and "immunities" not in sb:
        return

    # Build hitpoints object
    hitpoints = {"type": "stat_block_section", "subtype": "hitpoints"}

    # Parse HP (BT) string like "6 (3)", "20 (10)", or "40 (BT 20)" if present
    if "hp_bt" in sb:
        value_str = sb["hp_bt"]
        if value_str:
            # Match both "6 (3)" and "40 (BT 20)" formats
            match = re.match(r"(\d+)\s*\((?:BT\s+)?(\d+)\)", value_str.strip())
            if not match:
                raise ValueError(f"Could not parse hp_bt format: '{value_str}'")

            hitpoints["hp"] = int(match.group(1))
            hitpoints["break_threshold"] = int(match.group(2))
        del sb["hp_bt"]

    # Add hardness as integer if present
    if "hardness" in sb:
        hardness_str = str(sb["hardness"]).strip().rstrip(",")  # Clean up trailing commas
        hitpoints["hardness"] = int(hardness_str)
        del sb["hardness"]

    # Parse immunities string into protection objects if present
    if "immunities" in sb:
        immunities = _parse_immunities(sb["immunities"])
        if immunities:
            hitpoints["immunities"] = immunities
        del sb["immunities"]

    # Replace the individual fields with the hitpoints object
    sb["hp_bt"] = hitpoints


def _normalize_item_hitpoints(sb):
    """Build hitpoints object from hp_bt, hardness, and immunities fields.

    Creates a stat_block_section hitpoints object matching creature structure.
    Used by both shields and siege weapons.
    """
    if "hp_bt" not in sb and "hardness" not in sb and "immunities" not in sb:
        return

    # Build hitpoints object
    hitpoints = {"type": "stat_block_section", "subtype": "hitpoints"}

    # Parse HP (BT) string like "6 (3)", "20 (10)", or "40 (BT 20)" if present
    if "hp_bt" in sb:
        value_str = sb["hp_bt"]
        if value_str:
            # Match both "6 (3)" and "40 (BT 20)" formats
            match = re.match(r"(\d+)\s*\((?:BT\s+)?(\d+)\)", value_str.strip())
            if not match:
                raise ValueError(f"Could not parse hp_bt format: '{value_str}'")

            hitpoints["hp"] = int(match.group(1))
            hitpoints["break_threshold"] = int(match.group(2))
        del sb["hp_bt"]

    # Add hardness to hitpoints object if present
    if "hardness" in sb:
        hitpoints["hardness"] = int(sb["hardness"])
        del sb["hardness"]

    # Parse immunities string into protection objects if present
    if "immunities" in sb:
        immunities = _parse_immunities(sb["immunities"])
        if immunities:
            hitpoints["immunities"] = immunities
        del sb["immunities"]

    # Only add hitpoints object if we have at least hp
    if "hp" in hitpoints:
        sb["hitpoints"] = hitpoints


def _parse_immunities(html_text, subtype="immunity"):
    """Parse immunities/weaknesses HTML into array of protection objects with links preserved.

    Follows the creatures.py pattern:
    1. Normalize HTML text (remove embedded newlines)
    2. Split by ; then , using split_stat_block_line()
    3. Rebuild parts that were incorrectly split (when they have modifiers in parentheses)
    4. For each part, extract modifiers with parse_section_modifiers() and values with parse_section_value()
    5. Extract links from original HTML and match to parsed immunity objects

    Args:
        html_text: HTML string that may contain links and embedded newlines, e.g.:
            'object immunities' or
            '<a style="..." href="Rules.aspx?ID=2161">object immunities</a>' or
            'fire 10, <a href="...">cold</a>' or
            '<a>electricity</a>\n 10 (until \n<a>broken</a>)'
        subtype: 'immunity' or 'weakness' (default: 'immunity')

    Returns:
        List of protection objects with type, subtype, name, and optional value/link/modifiers fields
    """
    # Parse the HTML and normalize text to remove embedded newlines
    bs = BeautifulSoup(html_text, "html.parser")
    text = _normalize_whitespace(get_text(bs))

    # Remove trailing semicolon if present
    if text.endswith(";"):
        text = text[:-1].strip()

    # Split by ; then , following creatures.py pattern
    parts = split_stat_block_line(text)

    # Rebuild parts that were incorrectly split (when they have parentheses for modifiers)
    parts = rebuilt_split_modifiers(parts)

    # Extract all links from the original HTML with their text
    # We'll match these to the parsed immunity objects
    links_in_html = []
    for link_tag in bs.find_all("a"):
        link_text = _normalize_whitespace(get_text(link_tag))
        _, link_obj = extract_link(link_tag)
        links_in_html.append((link_text, link_obj))

    immunities = []
    for part in parts:
        if not part.strip():
            continue

        # Create base protection object with the parsed text as name
        immunity = {
            "type": "stat_block_section",
            "subtype": subtype,  # 'immunity' or 'weakness'
            "name": part,  # Clean text without newlines
        }

        # Extract modifiers from () using creatures.py function
        immunity = parse_section_modifiers(immunity, "name")

        # Extract numeric value from name
        # Unlike creatures.py, we need to handle cases where the value is in the middle
        # e.g., "fire 5 until broken" (without parentheses around "until broken")
        name_text = immunity["name"]
        # Try to match: "<name> <number> <optional rest>"
        # First try creatures.py pattern (number at end): "fire 10"
        m = re.match(r"^(.+?)\s+(\d+)$", name_text)
        if m:
            immunity["name"] = m.group(1).strip()
            immunity["value"] = int(m.group(2))
        else:
            # Try pattern with number in middle: "fire 5 until broken"
            m = re.match(r"^(.+?)\s+(\d+)\s+(.+)$", name_text)
            if m:
                immunity["name"] = m.group(1).strip()
                immunity["value"] = int(m.group(2))
                # The rest ("until broken") should be a modifier, but it's not in parentheses
                # Add it as a modifier anyway for consistency
                rest_text = m.group(3).strip()
                from universal.universal import build_object

                modifier = build_object("stat_block_section", "modifier", rest_text)
                # Try to match a link for this modifier text
                rest_text_lower = rest_text.lower()
                for link_text, link_obj in links_in_html:
                    link_text_lower = link_text.lower()
                    # Check if the link text matches or is contained in the modifier text
                    if link_text_lower == rest_text_lower or link_text_lower in rest_text_lower:
                        if "links" not in modifier:
                            modifier["links"] = []
                        modifier["links"].append(link_obj)
                        break
                if "modifiers" not in immunity:
                    immunity["modifiers"] = []
                immunity["modifiers"].append(modifier)

        # Try to match a link from the original HTML to this immunity
        # Look for a link whose text matches or is contained in the immunity name
        name_text = immunity["name"].lower()
        for link_text, link_obj in links_in_html:
            link_text_lower = link_text.lower()
            # Check if the link text matches or is contained in the immunity name
            if link_text_lower == name_text or link_text_lower in name_text:
                immunity["link"] = link_obj
                break

        # Also try to match links to modifiers (both from parentheses and from unparsed text)
        if "modifiers" in immunity:
            for modifier in immunity["modifiers"]:
                if "links" not in modifier:  # Don't overwrite if already set
                    modifier_text = modifier["name"].lower()
                    for link_text, link_obj in links_in_html:
                        link_text_lower = link_text.lower()
                        # Check if the link text matches or is contained in the modifier text
                        if link_text_lower == modifier_text or link_text_lower in modifier_text:
                            if "links" not in modifier:
                                modifier["links"] = []
                            modifier["links"].append(link_obj)
                            break

        immunities.append(immunity)

    return immunities


def _normalize_defensive_stats(sb):
    """Normalize AC, Fort, Ref fields to integer values."""
    for field in ["ac", "fort", "ref"]:
        if field in sb:
            _normalize_int_field(sb, field)


def _normalize_speed(sb):
    """Normalize speed field to speeds container with movement array.

    Handles multiple speeds like creatures do:
      "fly 40 feet (magical), swim 40 feet (magical)" -> speeds with 2 movement entries
      "20 feet (pulled or pushed)" -> speeds with 1 movement entry

    Each movement entry has: movement_type, value, unit, modifiers
    Speed values may contain HTML <a> tags when preserve_html=True was used during
    extraction. Parenthesized modifiers with links are handled by link_modifiers() in
    _parse_single_speed. Non-speed entries after comma split (like "ignores difficult
    terrain") are treated as additional modifiers on the previous speed entry.
    """
    if "speed" not in sb:
        return

    value_str = sb["speed"]
    if not value_str:
        return

    # Split by comma while respecting parentheses to get individual speed entries
    speed_entries = split_maintain_parens(value_str.strip(), ",")

    movement_array = []
    for entry in speed_entries:
        entry = entry.strip()
        # Check if this looks like a speed entry (has digits + feet/ft.)
        # vs an additional modifier (like "ignores difficult terrain" link)
        if re.search(r"\d+\s*(feet|ft\.)", entry) or not movement_array:
            speed_obj = _parse_single_speed(entry)
            if speed_obj:
                movement_array.append(speed_obj)
        else:
            # Non-speed text after comma is an additional modifier on the previous speed
            # (e.g., '<a href="...">ignores difficult terrain</a>')
            prev = movement_array[-1]
            new_mods = link_modifiers(build_objects("stat_block_section", "modifier", [entry]))
            if "modifiers" not in prev:
                prev["modifiers"] = []
            prev["modifiers"].extend(new_mods)

    # Create speeds container (matching creature schema)
    speeds_obj = {"type": "stat_block_section", "subtype": "speeds", "movement": movement_array}

    sb["speed"] = speeds_obj


def _parse_single_speed(entry):
    """Parse a single speed entry like 'fly 40 feet (magical)' into a speed object."""

    # Extract modifiers from parentheses at end
    modifier_text = None
    match = re.match(r"^(.+?)\s*\((.+)\)$", entry)
    if match:
        entry = match.group(1).strip()
        modifier_text = match.group(2).strip()

    # Check for movement type prefix (fly, swim, burrow, climb, etc.)
    movement_type = "walk"  # Default like creatures
    movement_types = ["fly", "swim", "burrow", "climb", "land"]
    for mtype in movement_types:
        if entry.lower().startswith(mtype + " "):
            movement_type = mtype
            entry = entry[len(mtype) :].strip()
            break

    # Extract unit and value
    unit = "feet"  # Default
    if entry.endswith(" feet"):
        entry = entry[:-5]
    elif entry.endswith(" ft."):
        entry = entry[:-4]

    # Parse to int - handle special text cases
    entry_trimmed = entry.strip()
    if entry_trimmed.isdigit():
        value = int(entry_trimmed)
        speed_obj = {
            "type": "stat_block_section",
            "subtype": "speed",
            "name": (
                f"{movement_type} {value} {unit}" if movement_type != "walk" else f"{value} {unit}"
            ),
            "movement_type": movement_type,
            "value": value,
        }
    else:
        # Handle special text cases like "the speed of the slowest pulling creature"
        speed_obj = {
            "type": "stat_block_section",
            "subtype": "speed",
            "name": entry_trimmed,
            "movement_type": movement_type,
        }

    # Add modifiers if present - split by comma or semicolon
    if modifier_text:
        modifier_parts = split_comma_and_semicolon(modifier_text)
        speed_obj["modifiers"] = link_modifiers(
            build_objects("stat_block_section", "modifier", modifier_parts)
        )

    return speed_obj


def _normalize_weapon_mode(mode_obj):
    """Normalize fields within a weapon mode object."""
    _normalize_damage(mode_obj)
    _normalize_range(mode_obj)
    _normalize_reload(mode_obj)
    _normalize_ammunition(mode_obj)  # Ammunition can also be at mode level


def _normalize_damage(sb):
    """Normalize damage field to structured format matching creature attacks.

    Converts strings like '1d8 S' or '1d4 B + 1d4 F' into an array of damage objects.
    """
    if "damage" not in sb:
        return

    value_str = sb["damage"]
    if not value_str:
        return

    # Map single-letter damage type codes to full names (as used in creatures)
    damage_type_map = {
        "B": "bludgeoning",
        "P": "piercing",
        "S": "slashing",
        "F": "fire",
        "modular": "modular",  # Special type for modular weapons
    }

    # Handle special cases
    value_str = value_str.strip()
    if value_str.lower() == "varies":
        sb["damage"] = [
            {"type": "stat_block_section", "subtype": "attack_damage", "notes": "varies"}
        ]
        return
    if not value_str or value_str == "null":
        del sb["damage"]
        return

    # Parse damage components (may be multiple like "1d4 B + 1d4 F")
    damage_parts = value_str.split("+")
    damage_array = []

    for part in damage_parts:
        part = part.strip()
        if not part:
            continue

        # Parse: "1d8 S" -> formula="1d8", damage_type="slashing"
        tokens = part.split()
        if len(tokens) < 2:
            # Just a formula without type, or single token
            if tokens:
                damage_obj = {
                    "type": "stat_block_section",
                    "subtype": "attack_damage",
                    "formula": tokens[0],
                }
                damage_array.append(damage_obj)
            continue

        formula = tokens[0]
        damage_type_code = tokens[1]

        # Map the code to full name - error if unrecognized
        if damage_type_code not in damage_type_map:
            raise ValueError(
                f"Unrecognized damage type code '{damage_type_code}' in damage string: {value_str}"
            )

        damage_type = damage_type_map[damage_type_code]

        damage_obj = {
            "type": "stat_block_section",
            "subtype": "attack_damage",
            "formula": formula,
            "damage_type": damage_type,
        }
        damage_array.append(damage_obj)

    if damage_array:
        sb["damage"] = damage_array
    # If empty, don't set it - cleanup pass will handle any existing empty/null values


def _normalize_hands(sb):
    """Normalize hands field to integer or special value like '0+', '1+', '1 or 2'."""
    if "hands" not in sb:
        return

    value_str = sb["hands"]
    if not value_str:
        return

    # Handle special cases with variable hands
    # '0+', '1+', '1 or 2', etc. - keep as string
    if "+" in value_str or " or " in value_str:
        sb["hands"] = value_str  # Keep as string
        return

    # Otherwise normalize to integer
    _normalize_int_field(sb, "hands")


def _normalize_range(sb):
    """Normalize range field (e.g., '30 ft.' or '60 feet')."""
    if "range" not in sb:
        return

    value_str = sb["range"]
    if not value_str:
        return

    # Em dash means no range - remove the field
    if value_str.strip() == "—":
        del sb["range"]
        return

    # Extract unit and value
    unit = None
    if value_str.endswith(" ft."):
        unit = "feet"
        value_str = value_str[:-4]
    elif value_str.endswith(" feet"):
        unit = "feet"
        value_str = value_str[:-5]

    # Parse to int
    value = int(value_str.strip())
    # Create range object
    range_obj = {"type": "stat_block_section", "subtype": "range", "value": value}
    if unit:
        range_obj["unit"] = unit
    sb["range"] = range_obj


def _normalize_reload(sb):
    """Normalize reload field to structured object with value and unit."""
    if "reload" not in sb:
        return

    value_str = sb["reload"]
    if not value_str:
        return

    # Parse value and unit
    parts = value_str.strip().split(" ", 1)

    value = int(parts[0])
    reload_obj = {"type": "stat_block_section", "subtype": "reload", "value": value}

    # Add unit if specified (e.g., "minute", "rounds")
    if len(parts) > 1:
        # Normalize common units
        unit = parts[1].lower()
        if unit in ["minute", "minutes"]:
            unit = "minute"
        elif unit in ["round", "rounds"]:
            unit = "round"
        elif unit in ["action", "actions"]:
            unit = "action"
        reload_obj["unit"] = unit
    else:
        # No unit specified means actions (default)
        reload_obj["unit"] = "action"

    sb["reload"] = reload_obj


def _equipment_handle_value(trait):
    """Extract value from trait names like 'Entrench Melee' -> name='Entrench', value='Melee'."""
    original_name = trait["name"]
    if original_name.lower().startswith("range increment"):
        trait["name"] = "range"
        trait["value"] = original_name[6:].strip()
        return

    m = re.search(r"(.*) (\+?d?[0-9]+.*)", trait["name"])
    if m:
        name, value = m.groups()
        trait["name"] = name.strip()
        trait["value"] = value.strip()
    elif " " in trait["name"]:
        parts = trait["name"].split(" ", 1)
        trait["name"] = parts[0].strip()
        trait["value"] = parts[1].strip()


def _equipment_trait_pre_process(trait, parent, curs):
    """Pre-process equipment traits: alignment expansion, name fixes, value splitting."""
    # Handle alignment abbreviations (CG -> Chaotic Good, etc.)
    full_alignment = universal_handle_alignment(trait["name"])
    if full_alignment:
        trait["name"] = full_alignment

    # Handle trait name mismatches in source HTML
    trait_name_fixes = {
        "concentration": "Concentrate",
    }
    if trait["name"] in trait_name_fixes:
        trait["name"] = trait_name_fixes[trait["name"]]

    # Try full name first (handles traits like "Ranged Trip", "Double Barrel")
    data = fetch_trait_by_name(curs, trait["name"])

    # If not found and name has space, try splitting into name + value
    if not data and " " in trait["name"]:
        _equipment_handle_value(trait)

    return False  # Continue with universal processing


def equipment_group_pass(struct, config):
    """Enrich equipment group objects with full data from database."""
    group_table = config["group_table"]
    group_subtype = config["group_subtype"]
    group_sql_module = config["group_sql_module"]

    # Dynamically import the SQL module and get the fetch function
    sql_module = importlib.import_module(group_sql_module)
    # Function name pattern: fetch_armor_group_by_name, fetch_weapon_group_by_name, etc.
    group_singular = group_table.rstrip("s")
    fetch_function_name = f"fetch_{group_singular}_by_name"
    fetch_group_by_name = getattr(sql_module, fetch_function_name)

    def _check_equipment_group(equipment_group, parent):
        """Look up equipment group in database and replace with enriched version."""
        # Get the name from the equipment group object
        name = equipment_group.get("name")
        if not name:
            return

        # Query database for equipment group
        fetch_group_by_name(curs, name)
        data = curs.fetchone()

        if not data:
            # If not found in database, leave as-is
            return

        # Parse the full equipment group JSON from database
        # The database column name matches the singular form of the table
        db_equipment_group = json.loads(data[group_singular])

        # Remove fields that shouldn't be in embedded equipment groups
        if "aonid" in db_equipment_group:
            del db_equipment_group["aonid"]
        if "license" in db_equipment_group:
            del db_equipment_group["license"]
        if "schema_version" in db_equipment_group:
            del db_equipment_group["schema_version"]

        # Replace equipment group in parent (similar to trait enrichment)
        assert isinstance(parent, dict), parent
        parent[group_subtype] = db_equipment_group

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()

        # Walk the structure and enrich all equipment groups
        walk(struct, test_key_is_value("subtype", group_subtype), _check_equipment_group)


def _build_statistics_bucket(stat_block):
    """
    Build the statistics bucket from existing equipment data.

    Maps fields from various sources:
    - access (from stat_block top-level) - price and bulk stay at stat_block level
    - category (from weapon/armor object)
    - hands (from weapon object or weapon_mode)
    - usage, crew, proficiency, space (from siege_weapon)
    - strength → strength_requirement (from armor)
    - favored_weapon (from weapon)
    """
    statistics = {"type": "stat_block_section", "subtype": "statistics"}

    # Top-level fields (price and bulk remain at stat_block level)
    if "access" in stat_block:
        statistics["access"] = stat_block["access"]

    # Weapon-specific statistics
    if "weapon" in stat_block:
        weapon = stat_block["weapon"]
        if "category" in weapon:
            statistics["category"] = weapon["category"]
        if "hands" in weapon:
            statistics["hands"] = weapon["hands"]
        if "favored_weapon" in weapon:
            statistics["favored_weapon"] = weapon["favored_weapon"]

    # Armor-specific statistics
    if "armor" in stat_block:
        armor = stat_block["armor"]
        if "category" in armor:
            if "category" in statistics and statistics["category"] != armor["category"]:
                raise ValueError(
                    f"Conflicting 'category' definitions for hybrid weapon/armor item: {statistics['category']} vs {armor['category']}"
                )
            statistics["category"] = armor["category"]
        if "strength" in armor:
            # Rename strength to strength_requirement in new structure
            statistics["strength_requirement"] = armor["strength"]

    # Siege weapon-specific statistics
    if "siege_weapon" in stat_block:
        siege = stat_block["siege_weapon"]
        if "usage" in siege:
            statistics["usage"] = siege["usage"]
        if "crew" in siege:
            statistics["crew"] = siege["crew"]
        if "proficiency" in siege:
            statistics["proficiency"] = siege["proficiency"]
        if "space" in siege:
            statistics["space"] = siege["space"]

    # Vehicle-specific statistics
    if "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "space" in vehicle:
            statistics["space"] = vehicle["space"]
        if "crew" in vehicle:
            statistics["crew"] = vehicle["crew"]
        if "passengers" in vehicle:
            statistics["passengers"] = vehicle["passengers"]
        if "piloting_check" in vehicle:
            statistics["piloting_check"] = vehicle["piloting_check"]

    # Only return statistics if it has fields beyond type/subtype
    if len(statistics) > 2:
        return statistics
    return None


def _build_defense_bucket(stat_block):
    """
    Build the defense bucket from existing equipment data.

    Maps fields from:
    - ac_bonus (from armor, shield)
    - ac (from siege_weapon - raw AC value, not bonus)
    - hardness, hitpoints (from shield, siege_weapon)
    - speed_penalty (from armor, shield)
    - check_penalty, dex_cap (from armor)
    - armor_group (from armor)
    - saves (fort, ref from siege_weapon)
    - speed (from siege_weapon)
    """
    defense = {"type": "stat_block_section", "subtype": "defense"}

    # Armor defensive properties
    if "armor" in stat_block:
        armor = stat_block["armor"]
        if "ac_bonus" in armor:
            defense["ac_bonus"] = armor["ac_bonus"]
        if "dex_cap" in armor:
            defense["dex_cap"] = armor["dex_cap"]
        if "check_penalty" in armor:
            defense["check_penalty"] = armor["check_penalty"]
        if "speed_penalty" in armor:
            defense["speed_penalty"] = armor["speed_penalty"]
        if "armor_group" in armor:
            defense["armor_group"] = armor["armor_group"]

    # Shield defensive properties
    if "shield" in stat_block:
        shield = stat_block["shield"]
        if "ac_bonus" in shield:
            if "ac_bonus" in defense:
                raise ValueError("Conflicting 'ac_bonus' definitions for hybrid armor/shield item.")
            defense["ac_bonus"] = shield["ac_bonus"]
        if "speed_penalty" in shield:
            if "speed_penalty" in defense:
                raise ValueError(
                    "Conflicting 'speed_penalty' definitions for hybrid armor/shield item."
                )
            defense["speed_penalty"] = shield["speed_penalty"]
        if "hitpoints" in shield:
            defense["hitpoints"] = shield["hitpoints"]

    # Siege weapon defensive properties
    if "siege_weapon" in stat_block:
        siege = stat_block["siege_weapon"]
        # Siege weapons have raw AC value, not a bonus
        if "ac" in siege:
            defense["ac"] = siege["ac"]
        if "hitpoints" in siege:
            if "hitpoints" in defense and defense["hitpoints"] != siege["hitpoints"]:
                raise ValueError("Conflicting 'hitpoints' definitions for hybrid item.")
            defense["hitpoints"] = siege["hitpoints"]

        # Build saves container if fort or ref exist
        # Note: old structure has fort/ref as raw integers, need to wrap in save objects
        saves = None
        save_keys = ["fort", "ref"]
        if any(key in siege for key in save_keys):
            saves = {"type": "stat_block_section", "subtype": "saves"}
            for key in save_keys:
                if key in siege:
                    saves[key] = {
                        "type": "stat_block_section",
                        "subtype": "save",
                        "value": siege[key],
                    }
        if saves:
            defense["saves"] = saves

        if "speed" in siege:
            defense["speed"] = siege["speed"]

    # Vehicle defensive properties
    if "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        # Vehicles have raw AC value, not a bonus
        if "ac" in vehicle:
            defense["ac"] = vehicle["ac"]
        if "hardness" in vehicle:
            defense["hardness"] = vehicle["hardness"]
        if "hp_bt" in vehicle:
            # Parse HP (BT X) into hitpoints structure
            defense["hitpoints"] = vehicle["hp_bt"]
        if "immunities" in vehicle:
            defense["immunities"] = vehicle["immunities"]
        if "weaknesses" in vehicle:
            defense["weaknesses"] = vehicle["weaknesses"]

        # Build saves container for fort (vehicles don't have ref)
        if "fort" in vehicle:
            saves = {
                "type": "stat_block_section",
                "subtype": "saves",
                "fort": {"type": "stat_block_section", "subtype": "save", "value": vehicle["fort"]},
            }
            defense["saves"] = saves

    # Only return defense if it has fields beyond type/subtype
    if len(defense) > 2:
        return defense
    return None


def _build_offense_bucket(stat_block):
    """
    Build the offense bucket from existing equipment data.

    Maps fields from:
    - weapon_modes (from weapon.melee, weapon.ranged)
    - ammunition (from weapon, siege_weapon)
    - offensive_abilities (from stat_block.abilities)

    For weapons, converts the old melee/ranged structure into a weapon_modes array.
    """
    offense = {"type": "stat_block_section", "subtype": "offense"}

    # Weapon offensive properties
    if "weapon" in stat_block:
        weapon = stat_block["weapon"]
        weapon_modes = []

        # Convert melee and ranged modes if they exist
        for mode_type in ["melee", "ranged"]:
            if mode_type in weapon:
                mode = weapon[mode_type].copy()
                mode["type"] = "stat_block_section"
                weapon_modes.append(mode)

        if weapon_modes:
            offense["weapon_modes"] = weapon_modes

        # Top-level ammunition for weapons (not mode-specific)
        if "ammunition" in weapon:
            offense["ammunition"] = weapon["ammunition"]

        # Attack roll outcomes (e.g., Big Boom Gun's modified critical failure)
        # For weapons, these are attack outcomes, not save results
        if "save_results" in stat_block:
            sr = stat_block["save_results"]
            attack_roll = {"type": "stat_block_section", "subtype": "attack_roll"}
            for field in ("critical_success", "success", "failure", "critical_failure"):
                if field in sr:
                    attack_roll[field] = sr.pop(field)
            if len(attack_roll) > 2:
                offense["attack_roll"] = attack_roll
            # Remove save_results if empty (only type/subtype left)
            if len(sr) <= 2:
                del stat_block["save_results"]

    # Siege weapon offensive properties
    if "siege_weapon" in stat_block:
        siege = stat_block["siege_weapon"]
        if "ammunition" in siege:
            if "ammunition" in offense and offense["ammunition"] != siege["ammunition"]:
                raise ValueError(
                    "Conflicting 'ammunition' definitions for hybrid weapon/siege_weapon item."
                )
            offense["ammunition"] = siege["ammunition"]

    # Vehicle offensive properties
    if "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "speed" in vehicle:
            offense["speed"] = vehicle["speed"]
        if "collision" in vehicle:
            offense["collision"] = vehicle["collision"]

    # Abilities (offensive_abilities)
    if "abilities" in stat_block:
        offense["offensive_abilities"] = stat_block["abilities"]

    # Only return offense if it has fields beyond type/subtype
    if len(offense) > 2:
        return offense
    return None


def _validate_bucket_data(stat_block, statistics, defense, offense):
    """
    Validate that bucket data matches the old structure data.

    This ensures the migration is correct by verifying that fields copied
    to buckets have the same values as their source in the old structure.
    """
    # Validate statistics bucket
    if statistics:
        # Check access matches top-level (price and bulk stay at stat_block level)
        if "access" in statistics:
            assert (
                statistics["access"] == stat_block["access"]
            ), f"statistics.access mismatch: {statistics['access']} != {stat_block['access']}"

        # Check weapon fields
        if "weapon" in stat_block:
            weapon = stat_block["weapon"]
            if "category" in statistics and "category" in weapon:
                assert (
                    statistics["category"] == weapon["category"]
                ), "statistics.category != weapon.category"
            if "hands" in statistics:
                assert statistics["hands"] == weapon["hands"], "statistics.hands != weapon.hands"
            if "favored_weapon" in statistics:
                assert (
                    statistics["favored_weapon"] == weapon["favored_weapon"]
                ), f"statistics.favored_weapon mismatch: {statistics['favored_weapon']} != {weapon['favored_weapon']}"

        # Check armor fields
        if "armor" in stat_block:
            armor = stat_block["armor"]
            if "category" in statistics and "category" in armor:
                assert (
                    statistics["category"] == armor["category"]
                ), "statistics.category != armor.category"
            if "strength_requirement" in statistics:
                assert (
                    statistics["strength_requirement"] == armor["strength"]
                ), "statistics.strength_requirement != armor.strength"

    # Validate defense bucket
    if defense:
        # Check armor fields
        if "armor" in stat_block:
            armor = stat_block["armor"]
            if "ac_bonus" in defense and "ac_bonus" in armor:
                assert (
                    defense["ac_bonus"] == armor["ac_bonus"]
                ), "defense.ac_bonus != armor.ac_bonus"
            if "dex_cap" in defense:
                assert defense["dex_cap"] == armor["dex_cap"], "defense.dex_cap != armor.dex_cap"
            if "check_penalty" in defense:
                assert (
                    defense["check_penalty"] == armor["check_penalty"]
                ), "defense.check_penalty != armor.check_penalty"
            if "speed_penalty" in defense and "speed_penalty" in armor:
                assert (
                    defense["speed_penalty"] == armor["speed_penalty"]
                ), "defense.speed_penalty != armor.speed_penalty"
            if "armor_group" in defense:
                assert (
                    defense["armor_group"] == armor["armor_group"]
                ), "defense.armor_group != armor.armor_group"

        # Check shield fields
        if "shield" in stat_block:
            shield = stat_block["shield"]
            if "ac_bonus" in defense and "ac_bonus" in shield:
                assert (
                    defense["ac_bonus"] == shield["ac_bonus"]
                ), "defense.ac_bonus != shield.ac_bonus"
            if "speed_penalty" in defense and "speed_penalty" in shield:
                assert (
                    defense["speed_penalty"] == shield["speed_penalty"]
                ), "defense.speed_penalty != shield.speed_penalty"
            if "hitpoints" in defense:
                assert (
                    defense["hitpoints"] == shield["hitpoints"]
                ), "defense.hitpoints != shield.hitpoints"

        # Check siege weapon fields
        if "siege_weapon" in stat_block:
            siege = stat_block["siege_weapon"]
            if "ac" in defense:
                assert defense["ac"] == siege["ac"], "defense.ac != siege.ac"
            if "hitpoints" in defense and "hitpoints" in siege:
                assert (
                    defense["hitpoints"] == siege["hitpoints"]
                ), "defense.hitpoints != siege.hitpoints"
            if "speed" in defense:
                assert defense["speed"] == siege["speed"], "defense.speed != siege.speed"
            # Validate saves (old structure has integers, new has save objects)
            if "saves" in defense:
                if "fort" in siege:
                    assert "fort" in defense["saves"], "Missing fort in defense.saves"
                    assert (
                        defense["saves"]["fort"]["value"] == siege["fort"]
                    ), "defense.saves.fort.value != siege.fort"
                if "ref" in siege:
                    assert "ref" in defense["saves"], "Missing ref in defense.saves"
                    assert (
                        defense["saves"]["ref"]["value"] == siege["ref"]
                    ), "defense.saves.ref.value != siege.ref"

    # Validate offense bucket
    if offense:
        # Check weapon fields - weapon_modes should match melee/ranged
        if "weapon" in stat_block:
            weapon = stat_block["weapon"]
            if "weapon_modes" in offense:
                modes_by_subtype = {m["subtype"]: m for m in offense["weapon_modes"]}
                if "melee" in weapon:
                    assert "melee" in modes_by_subtype, "Missing melee mode in offense.weapon_modes"
                    # Mode data should match completely
                    melee_mode = modes_by_subtype["melee"]
                    for key in weapon["melee"]:
                        assert key in melee_mode, f"Missing {key} in melee weapon_mode"
                        assert melee_mode[key] == weapon["melee"][key], f"melee mode {key} mismatch"
                if "ranged" in weapon:
                    assert (
                        "ranged" in modes_by_subtype
                    ), "Missing ranged mode in offense.weapon_modes"
                    ranged_mode = modes_by_subtype["ranged"]
                    for key in weapon["ranged"]:
                        assert key in ranged_mode, f"Missing {key} in ranged weapon_mode"
                        assert (
                            ranged_mode[key] == weapon["ranged"][key]
                        ), f"ranged mode {key} mismatch"
            if "ammunition" in offense and "ammunition" in weapon:
                assert (
                    offense["ammunition"] == weapon["ammunition"]
                ), "offense.ammunition != weapon.ammunition"

        # Check siege weapon ammunition
        if "siege_weapon" in stat_block:
            siege = stat_block["siege_weapon"]
            if "ammunition" in offense and "ammunition" in siege:
                assert (
                    offense["ammunition"] == siege["ammunition"]
                ), "offense.ammunition != siege.ammunition"

        # Check vehicle collision and speed
        if "vehicle" in stat_block:
            vehicle = stat_block["vehicle"]
            if "speed" in offense:
                assert offense["speed"] == vehicle["speed"], "offense.speed != vehicle.speed"
            if "collision" in offense:
                assert (
                    offense["collision"] == vehicle["collision"]
                ), "offense.collision != vehicle.collision"

    # Validate vehicle fields in statistics
    if statistics and "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "space" in statistics:
            assert statistics["space"] == vehicle["space"], "statistics.space != vehicle.space"
        if "crew" in statistics:
            assert statistics["crew"] == vehicle["crew"], "statistics.crew != vehicle.crew"
        if "passengers" in statistics:
            assert (
                statistics["passengers"] == vehicle["passengers"]
            ), "statistics.passengers != vehicle.passengers"
        if "piloting_check" in statistics:
            assert (
                statistics["piloting_check"] == vehicle["piloting_check"]
            ), "statistics.piloting_check != vehicle.piloting_check"

    # Validate vehicle fields in defense
    if defense and "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "ac" in defense:
            assert defense["ac"] == vehicle["ac"], "defense.ac != vehicle.ac"
        if "hardness" in defense:
            assert (
                defense["hardness"] == vehicle["hardness"]
            ), "defense.hardness != vehicle.hardness"
        if "hitpoints" in defense and "hp_bt" in vehicle:
            assert defense["hitpoints"] == vehicle["hp_bt"], "defense.hitpoints != vehicle.hp_bt"
        if "immunities" in defense:
            assert (
                defense["immunities"] == vehicle["immunities"]
            ), "defense.immunities != vehicle.immunities"
        if "weaknesses" in defense:
            assert (
                defense["weaknesses"] == vehicle["weaknesses"]
            ), "defense.weaknesses != vehicle.weaknesses"
        # Validate fort save
        if "saves" in defense and "fort" in vehicle:
            assert "fort" in defense["saves"], "Missing fort in defense.saves"
            assert (
                defense["saves"]["fort"]["value"] == vehicle["fort"]
            ), "defense.saves.fort.value != vehicle.fort"


def populate_equipment_buckets_pass(struct):
    """
    Populate creature-style buckets (statistics, defense, offense) from old
    type-specific equipment objects, then remove the old objects.

    This completes the migration to the new bucket-based structure by:
    1. Building buckets from old structure
    2. Validating bucket data matches old structure
    3. Removing old deprecated structures (weapon, armor, shield, siege_weapon objects)

    Args:
        struct: The equipment structure with stat_block containing old-style objects
    """
    stat_block = struct.get("stat_block")
    if not stat_block:
        return

    # Build each bucket from existing data
    statistics = _build_statistics_bucket(stat_block)
    defense = _build_defense_bucket(stat_block)
    offense = _build_offense_bucket(stat_block)

    # Validate that bucket data matches old structure (data integrity check)
    _validate_bucket_data(stat_block, statistics, defense, offense)

    # Merge buckets into stat_block (preserving existing bucket content from field_destinations)
    # Only merge if the built bucket has content beyond type/subtype
    if statistics and len(statistics) > 2:
        if "statistics" in stat_block:
            # Merge: built bucket data into existing bucket
            for key, value in statistics.items():
                if key not in stat_block["statistics"]:
                    stat_block["statistics"][key] = value
        else:
            stat_block["statistics"] = statistics
    if defense and len(defense) > 2:
        if "defense" in stat_block:
            for key, value in defense.items():
                if key not in stat_block["defense"]:
                    stat_block["defense"][key] = value
        else:
            stat_block["defense"] = defense
    if offense and len(offense) > 2:
        if "offense" in stat_block:
            for key, value in offense.items():
                if key not in stat_block["offense"]:
                    stat_block["offense"][key] = value
        else:
            stat_block["offense"] = offense

    # Phase 4 cleanup: Remove deprecated old structures and moved fields
    # Note: price and bulk stay at stat_block level (not in statistics)
    # Note: abilities is moved to offense.offensive_abilities
    deprecated_keys = (
        "weapon",
        "armor",
        "shield",
        "siege_weapon",
        "vehicle",
        "access",
        "abilities",
    )
    for key in deprecated_keys:
        if key in stat_block:
            del stat_block[key]
