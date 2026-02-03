import importlib
import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString, Tag

import pfsrd2.constants as constants
from pfsrd2.action import extract_action_type

# Import stat block parsing utilities from creatures.py
from pfsrd2.creatures import (
    parse_section_modifiers,
    rebuilt_split_modifiers,
    split_stat_block_line,
)
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.traits import fetch_trait_by_link, fetch_trait_by_name

# Import DC/save parsing from universal
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
    edition_pass,
    extract_link,
    extract_links,
    extract_source,
    game_id_pass,
    get_links,
    href_filter,
    link_modifiers,
    remove_empty_sections_pass,
    restructure_pass,
    test_key_is_value,
    walk,
)
from universal.utils import (
    clear_garbage,
    clear_tags,
    get_text,
    recursive_filter_entities,
    split_comma_and_semicolon,
    split_maintain_parens,
    split_on_tag,
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


def _count_links_in_html(html_text, exclude_name=None, exclude_game_obj=None, debug=False):
    """Count all <a> tags with game-obj attribute in HTML.

    This counts links that need to be extracted into structured link objects.
    Only counts internal game links (with game-obj attribute).

    Excludes:
    - Self-references (links whose text AND game-obj match exclude_name/exclude_game_obj)
    - Trait name links (links inside <span class="trait*"> tags, replaced by database)
    - Equipment group links (WeaponGroups/ArmorGroups in stat lines, replaced by database)

    Args:
        html_text: HTML text to count links in
        exclude_name: If provided, exclude links whose text matches this name (for self-references)
        exclude_game_obj: If provided, also require game-obj to match for self-reference exclusion
        debug: If True, print debug info about found links
    """
    soup = BeautifulSoup(html_text, "html.parser")
    # Find all <a> tags that have game-obj attribute (internal game links)
    all_links = soup.find_all("a", attrs={"game-obj": True})

    if debug:
        import sys

        sys.stderr.write(f"DEBUG: Found {len(all_links)} total <a game-obj> tags\n")
        for link in all_links:
            sys.stderr.write(f"  - {link.get_text().strip()} ({link.get('game-obj')})\n")

    links = all_links

    # Exclude self-references if exclude_name is provided
    # When exclude_game_obj is also provided, both name AND game-obj must match
    # (prevents excluding links to other game objects that share the item's name)
    if exclude_name:
        before = len(links)
        if exclude_game_obj:
            links = [
                l
                for l in links
                if not (
                    l.get_text().strip() == exclude_name and l.get("game-obj") == exclude_game_obj
                )
            ]
        else:
            links = [l for l in links if l.get_text().strip() != exclude_name]
        if debug and len(links) < before:
            sys.stderr.write(
                f"DEBUG: Excluded {before - len(links)} self-references to '{exclude_name}'\n"
            )

    # Exclude trait links ONLY if inside <span class="trait*"> tags (stat block traits)
    # Regular trait links in text (like description text or ability body text) should
    # remain as link objects, NOT be converted to traits. Only trait links in:
    # 1. <span class="trait*"> tags (main stat block traits at top)
    # 2. Opening parentheses of abilities (handled separately in _extract_abilities)
    # should be converted to trait objects.
    def is_trait_link(link):
        # Check if inside <span class="trait*"> tags (stat block trait)
        parent = link.parent
        if parent and parent.name == "span":
            parent_classes = parent.get("class", [])
            if isinstance(parent_classes, str):
                return parent_classes.startswith("trait")
            else:  # list of classes
                return any(cls.startswith("trait") for cls in parent_classes)
        # Regular trait links in text are NOT excluded - they should be link objects
        return False

    before = len(links)
    links = [l for l in links if not is_trait_link(l)]
    if debug and len(links) < before:
        sys.stderr.write(f"DEBUG: Excluded {before - len(links)} trait links\n")

    # Exclude "more recent version" navigation links (not extracted to JSON)
    # These appear as: <strong><u><a>There is a more recent version...</a></u></strong>
    def is_version_link(link):
        from universal.utils import get_text

        link_text = get_text(link).strip().lower()
        return "more recent version" in link_text or "newer version" in link_text

    # Exclude equipment group links (weapon groups, armor groups)
    # These links are replaced by database group data during equipment_group_pass enrichment
    # Group links appear as: <b>Group</b> <u><a game-obj="WeaponGroups">Brawling</a></u>
    # The <u> parent with a preceding <b>Group</b> sibling indicates this is a stat line group link
    def is_group_link(link):
        # Check if link is to a group object type
        game_obj = link.get("game-obj", "")
        if game_obj not in ["WeaponGroups", "ArmorGroups"]:
            return False

        # Check if it's in a stat line context (parent is <u> with preceding <b> sibling)
        from bs4 import NavigableString, Tag

        parent = link.parent
        if parent and parent.name == "u":
            # Look for a preceding <b> sibling with text "Group" or "Armor Group"
            prev_sibling = parent.previous_sibling
            # Skip whitespace text nodes
            while prev_sibling:
                if isinstance(prev_sibling, NavigableString):
                    if prev_sibling.strip():
                        break  # Non-whitespace text, stop looking
                    prev_sibling = prev_sibling.previous_sibling
                else:
                    break  # Found a tag, stop looking

            if prev_sibling and isinstance(prev_sibling, Tag) and prev_sibling.name == "b":
                from universal.utils import get_text

                label_text = get_text(prev_sibling).strip()
                if label_text in ["Group", "Armor Group"]:
                    return True
        return False

    # Exclude alternate edition links (legacy/remastered version links)
    # These are extracted as separate alternate_link objects during parsing
    # They appear inside <div class="siderbarlook"> with text like "There is a Legacy version here"
    def is_alternate_link(link):
        from bs4 import Tag

        # Look for ancestor div with class="siderbarlook"
        parent = link.parent
        while parent:
            if isinstance(parent, Tag) and parent.name == "div":
                div_classes = parent.get("class", [])
                if "siderbarlook" in div_classes:
                    # Check if it contains alternate version text
                    from universal.utils import get_text

                    div_text = get_text(parent).strip()
                    return bool("Legacy version" in div_text or "Remastered version" in div_text)
            parent = parent.parent
        return False

    before = len(links)
    links = [l for l in links if not is_version_link(l)]
    if debug and len(links) < before:
        sys.stderr.write(f"DEBUG: Excluded {before - len(links)} version navigation links\n")

    before = len(links)
    links = [l for l in links if not is_group_link(l)]
    if debug and len(links) < before:
        sys.stderr.write(f"DEBUG: Excluded {before - len(links)} equipment group links\n")

    before = len(links)
    links = [l for l in links if not is_alternate_link(l)]
    if debug and len(links) < before:
        sys.stderr.write(f"DEBUG: Excluded {before - len(links)} alternate edition links\n")

    if debug:
        sys.stderr.write(f"DEBUG: Final count after exclusions: {len(links)}\n")

    return len(links)


def _count_links_in_json(obj, debug=False, _links_found=None, _is_top_level=False, _path=""):
    """Recursively count all link objects in a JSON structure.

    Counts objects with type='link' or type='alternate_link'.
    Excludes links inside trait objects (added by database enrichment).
    """
    if _links_found is None and debug:
        _links_found = []
        _is_top_level = True

    count = 0

    if isinstance(obj, dict):
        # Skip counting links inside trait objects (database enrichment adds these)
        if obj.get("subtype") == "trait":
            return 0

        # Skip counting links inside weapon/armor group objects (database enrichment adds these)
        # Group subtypes: 'weapon_group', 'armor_group', 'siege_weapon_group'
        subtype = obj.get("subtype", "")
        if "group" in subtype and subtype != "item_group":  # item_group is different
            return 0

        # Skip counting links inside base_material objects (link count already subtracted from initial)
        if subtype == "base_material":
            return 0

        # Check if this is a link object (regular link only, not alternate_link)
        # alternate_link objects are excluded from counting because they're extracted from
        # a special siderbarlook div and already excluded from the initial HTML count
        obj_type = obj.get("type")
        if obj_type == "link":
            count += 1
            if debug and _links_found is not None:
                name = obj.get("name", f"<{obj_type}>")
                _links_found.append(f"{name} ({obj.get('game-obj', '?')}) @ {_path}")
        elif obj_type == "alternate_link":
            # Skip counting alternate_link objects
            if debug and _links_found is not None:
                name = obj.get("name", f"<{obj_type}>")
                _links_found.append(
                    f"{name} ({obj.get('game-obj', '?')}) [SKIPPED - alternate_link]"
                )
            pass  # Don't count alternate_link objects
        else:
            # Only recurse if this is NOT a link object (to avoid double-counting)
            for key, value in obj.items():
                if isinstance(value, dict | list):
                    count += _count_links_in_json(
                        value,
                        debug=debug,
                        _links_found=_links_found,
                        _is_top_level=False,
                        _path=f"{_path}.{key}" if _path else key,
                    )

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, dict | list):
                count += _count_links_in_json(
                    item,
                    debug=debug,
                    _links_found=_links_found,
                    _is_top_level=False,
                    _path=f"{_path}[{i}]",
                )

    if debug and _is_top_level and _links_found is not None:
        # Top-level call, print results
        import sys

        sys.stderr.write(f"DEBUG: Links found in JSON ({len(_links_found)} total):\n")
        for link in _links_found:
            sys.stderr.write(f"  - {link}\n")

    return count


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
            "price": None,  # top-level stat_block
            "bulk": None,  # top-level stat_block
            "access": "statistics",
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
            "price": None,  # top-level stat_block
            "bulk": None,  # top-level stat_block
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
        "shared_fields": ["price"],
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
            "Craft Requirements": "craft_requirements",
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
            "price": None,
            "bulk": None,
            "hands": "statistics",
            "usage": "statistics",
            "activate": "statistics",  # Special handling converts to ability
            "access": "statistics",
            "craft_requirements": None,
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
    # Add equipment names here as needed, e.g.:
    # "Vonthos's Golden Bridge",
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


def parse_equipment(filename, options):
    """Universal equipment parser - supports armor, weapons, and future equipment types."""
    import sys

    equipment_type = options.equipment_type
    config = EQUIPMENT_TYPES[equipment_type]

    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")

    # Equipment HTML has flat structure - parse directly from HTML
    details = parse_equipment_html(filename, equipment_type)

    struct = restructure_equipment_pass(details, equipment_type)

    # COUNT INITIAL LINKS: Count all <a> tags with game-obj in the content HTML
    # Exclude self-references (links from item to itself, typically in title)
    # Map equipment types to their game-obj values for self-reference detection
    EQUIPMENT_TYPE_GAME_OBJ = {
        "equipment": "Equipment",
        "weapon": "Weapons",
        "armor": "Armor",
        "shield": "Shields",
        "siege_weapon": "SiegeWeapons",
        "vehicle": "Vehicles",
    }
    item_name = struct.get("name", "")
    item_game_obj = EQUIPMENT_TYPE_GAME_OBJ.get(equipment_type)
    debug_mode = False  # Set to basename == "Equipment.aspx.ID_XXX.html" for debugging
    initial_link_count = _count_links_in_html(
        details["text"], exclude_name=item_name, exclude_game_obj=item_game_obj, debug=debug_mode
    )
    aon_pass(struct, basename)
    links_removed = section_pass(struct, config, debug=debug_mode)
    # Subtract links that were intentionally removed from redundant sections
    if debug_mode:
        import sys

        sys.stderr.write(f"DEBUG: links_removed from redundant sections: {links_removed}\n")
        sys.stderr.write(f"DEBUG: initial_link_count before subtraction: {initial_link_count}\n")
    initial_link_count -= links_removed
    if debug_mode:
        import sys

        sys.stderr.write(f"DEBUG: initial_link_count after subtraction: {initial_link_count}\n")
    restructure_pass(struct, "stat_block", find_stat_block)
    normalize_trait_links = normalize_numeric_fields_pass(struct, config)
    # Subtract trait links converted during normalization pass (they become trait objects, not link objects)
    initial_link_count -= normalize_trait_links
    if debug_mode:
        sys.stderr.write(f"DEBUG: normalize_trait_links: {normalize_trait_links}\n")
        sys.stderr.write(f"DEBUG: initial_link_count after normalize: {initial_link_count}\n")
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], "", fxn_valid_tags=equipment_markdown_valid_set)
    # Determine edition (legacy vs remastered) before removing empty sections
    edition = edition_pass(struct["sections"])
    struct["edition"] = edition

    # LINK ACCOUNTING: Verify all links were extracted into structured objects
    # Must be done BEFORE trait_db_pass, which adds links from database that weren't in the HTML
    final_link_count = _count_links_in_json(struct, debug=debug_mode)
    if debug_mode:
        sys.stderr.write(f"DEBUG: Final JSON link count: {final_link_count}\n")
        sys.stderr.write(f"DEBUG: Initial HTML link count (after removals): {initial_link_count}\n")
    if final_link_count != initial_link_count:
        raise AssertionError(
            f"Link accounting failed in {basename}: "
            f"started with {initial_link_count} links in HTML, "
            f"ended with {final_link_count} link objects in JSON. "
            f"Links were lost during parsing - check that all <a> tags "
            f"are being extracted into structured link objects."
        )

    # Enrich traits with database data (must be after edition is set)
    trait_db_pass(struct)
    # Enrich equipment groups with database data (only for equipment types that have groups)
    if "group_table" in config:
        equipment_group_pass(struct, config)
    # Populate creature-style buckets (statistics, defense, offense) from old structure
    # This maintains backward compatibility during migration
    populate_equipment_buckets_pass(struct)
    remove_empty_sections_pass(struct)

    # Fix character encoding issues (UTF-8 interpreted as Latin-1)
    recursive_filter_entities(struct)

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


# Maintain backward compatibility - parse_armor is now an alias
def parse_armor(filename, options):
    """Backward compatibility wrapper for parse_equipment."""
    options.equipment_type = "armor"
    return parse_equipment(filename, options)


def parse_equipment_html(filename, equipment_type=None):
    """
    Parse equipment HTML which has a flat structure (no hierarchical headings).
    Extract the name and content for further processing.

    Args:
        filename: Path to HTML file
        equipment_type: Type of equipment ('armor', 'weapon', 'shield', 'siege_weapon', 'vehicle')
    """
    with open(filename) as fp:
        html = fp.read()

    soup = BeautifulSoup(html, "html.parser")

    # Enrich href attributes with game-obj and aonid (same as parse_universal does)
    href_filter(soup)

    # The content is inside the DetailedOutput span
    detailed_output = soup.find(id="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    assert detailed_output, "Could not find DetailedOutput span"

    # Find h1.title - this contains the PFS icon and the name link follows it
    h1_title = detailed_output.find("h1", class_="title")
    assert h1_title, "Could not find h1.title in DetailedOutput"

    # Extract PFS status from h1 (img alt="PFS Standard/Limited/Restricted")
    pfs = "Standard"
    pfs_img = h1_title.find("img", alt=lambda s: s and s.startswith("PFS "))
    if pfs_img:
        pfs_alt = pfs_img.get("alt", "")
        match = re.match(r"PFS\s+(\w+)", pfs_alt, re.IGNORECASE)
        if match:
            pfs = match.group(1).capitalize()

    # Extract the equipment name from the link that follows DetailedOutput
    # For general equipment, this may return a plain string instead of a tag
    name_link = extract_name_link(detailed_output, equipment_type)
    name = name_link if isinstance(name_link, str) else get_text(name_link).strip()

    # Extract item level if present (for siege weapons, vehicles, etc.)
    # Item level appears as: <span style="margin-left:auto; margin-right:0">Item 13</span>
    level = 0
    content_container = detailed_output.parent
    level_span = content_container.find("span", style=lambda s: s and "margin-left:auto" in s)
    if level_span:
        level_text = get_text(level_span).strip()
        match = re.match(r"Item\s+(\d+)", level_text, re.IGNORECASE)
        if match:
            level = int(match.group(1))

    # Remove the h1.title now that we've extracted PFS from it
    h1_title.decompose()

    # Remove Legacy Content h3 if present (converted to edition field, not a section)
    legacy_h3 = detailed_output.find(
        "h3", class_="title", string=lambda s: s and "Legacy Content" in s
    )
    if legacy_h3:
        legacy_h3.decompose()

    # Collect content from DetailedOutput onwards
    # Extract the CONTENTS of DetailedOutput (not the span itself to avoid wrapper tags)
    content_parts = [str(child) for child in detailed_output.children]

    # Also collect sibling elements after DetailedOutput
    for sibling in detailed_output.next_siblings:
        if hasattr(sibling, "name"):  # Only tags, not text nodes
            content_parts.append(str(sibling))
            if sibling.name == "div" and sibling.get("class") == ["clear"]:
                break

    combined_content = "".join(content_parts)

    result = {
        "name": name,
        "text": combined_content,
        "level": level,  # Always include level (0 if not specified)
        "pfs": pfs,  # Always include PFS (Standard if not specified)
    }

    return result


def extract_name_link(detailed_output, equipment_type=None):
    """
    Extract the equipment name link from the h1.title region.

    Two HTML structures exist (after href_filter):

    Structure A (most common):
        <span id="DetailedOutput">
            <h1 class="title">...PFS icon...</h1>
        </span>
        <span class="likeButton">...</span>
        <a game-obj="Weapons" aonid="468">Breaching Pike</a>  <-- name link is sibling of DetailedOutput

    Structure B (some older items):
        <span id="DetailedOutput">
            <h1 class="title">
                <span class="likeButton">...</span>
                <a game-obj="Weapons" aonid="113">Throwing Knife</a>  <-- name link is inside h1
            </h1>
        </span>

    Args:
        detailed_output: The DetailedOutput span BeautifulSoup element
        equipment_type: Equipment type ('armor', 'weapon', 'shield', 'siege_weapon', 'vehicle')
    """
    # Map equipment_type to game-obj value (href_filter converts href to game-obj attribute)
    type_to_gameobj = {
        "armor": "Armor",
        "weapon": "Weapons",
        "shield": "Shields",
        "siege_weapon": "SiegeWeapons",
        "vehicle": "Vehicles",
        "equipment": "Equipment",
    }

    # All valid game-obj values (for fallback if equipment_type not provided)
    all_gameobjs = list(type_to_gameobj.values())

    # Get the expected game-obj for this equipment type
    expected_gameobj = type_to_gameobj.get(equipment_type)

    def is_name_link(elem):
        """Check if element is a valid name link."""
        if not hasattr(elem, "name") or elem.name != "a":
            return False
        if elem.has_attr("noredirect"):
            return False
        game_obj = elem.get("game-obj", "")
        if expected_gameobj and game_obj == expected_gameobj:
            return True
        return game_obj in all_gameobjs

    # For general Equipment, name may be plain text (not a link)
    # Check for text node FIRST before looking for links
    if equipment_type == "equipment":
        for sibling in detailed_output.next_siblings:
            if isinstance(sibling, NavigableString):
                text = str(sibling).strip()
                if text and not text.startswith("Item"):  # Skip "Item X" level text
                    # Return plain string - calling code handles this
                    return text
            elif hasattr(sibling, "name") and sibling.name == "span":
                # Check if span contains item level - skip to next sibling
                span_text = sibling.get_text().strip()
                if span_text.startswith("Item"):
                    continue
            elif hasattr(sibling, "name") and sibling.name in ("h3", "b", "br"):
                # Reached stat block content without finding name - stop looking
                break

    # Try Structure A: name link is a sibling of DetailedOutput
    for sibling in detailed_output.next_siblings:
        if is_name_link(sibling):
            return sibling

    # Try Structure B: name link is inside h1.title within DetailedOutput
    h1_title = detailed_output.find("h1", class_="title")
    if h1_title:
        link = h1_title.find("a", attrs={"game-obj": expected_gameobj or True})
        if link and is_name_link(link):
            return link

    # Try Structure C: name is plain text inside h1.title (no link)
    # e.g., <h1 class="title">Blackaxe<span>Item 25</span></h1>
    if h1_title:
        for child in h1_title.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    return text
            elif hasattr(child, "name") and child.name == "span":
                # Skip item level spans like "Item 25"
                continue
            elif hasattr(child, "name") and child.name == "a":
                # Skip PFS links without game-obj
                href = child.get("href", "")
                if "PFS" in href or not child.get("game-obj"):
                    continue

    raise AssertionError(f"Could not find equipment name link (type={equipment_type})")


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

    Returns the number of links that were removed from redundant sections.
    """
    equipment_type = struct["type"]

    # Dispatch to equipment-specific handlers
    if equipment_type == "weapon":
        return _weapon_section_pass(struct, config, debug=debug)
    elif equipment_type == "siege_weapon":
        return _siege_weapon_section_pass(struct, config, debug=debug)
    elif equipment_type == "vehicle":
        return _vehicle_section_pass(struct, config, debug=debug)
    else:
        # Generic equipment handling (armor, shields, etc.)
        return _generic_section_pass(struct, config, debug=debug)


def _parse_variant_section(h2_tag, config, parent_name, debug=False):
    """Parse a variant section (h2 and its content) into a variant stat block.

    Args:
        h2_tag: The h2 BeautifulSoup element marking the start of the variant
        config: Equipment type configuration
        parent_name: Name of the parent item (for debugging)
        debug: Enable debug output

    Returns:
        Tuple of (variant stat block dict, link count removed from variant)
    """
    # Extract variant name and level from h2
    # Format: "Artisan's Tools<span>Item 0</span>" or "Artisan's Tools (Sterling)<span>Item 3</span>"
    h2_text = get_text(h2_tag).strip()
    level_match = re.search(r"Item\s+(\d+)", h2_text)
    level = int(level_match.group(1)) if level_match else 0

    # Name is everything before "Item N"
    name = re.sub(r"\s*Item\s+\d+\+?\s*$", "", h2_text).strip()

    # Collect content from h2 until next h2 or end
    content_parts = []
    current = h2_tag.next_sibling
    while current:
        if hasattr(current, "name") and current.name == "h2":
            break  # Stop at next variant
        content_parts.append(str(current))
        current = current.next_sibling

    variant_html = "".join(content_parts)
    bs = BeautifulSoup(variant_html, "html.parser")

    # Create variant struct to hold source (like parent struct)
    variant_struct = {"sources": []}

    # Create variant stat block
    variant_sb = {
        "type": "stat_block",
        "subtype": config.get("output_subdir", "equipment"),
        "name": name,
        "level": level,
    }

    # Extract source from variant (has its own source links)
    _extract_source(bs, variant_struct)

    # Extract traits from variant (some variants have their own traits like Uncommon)
    _extract_traits(bs, variant_sb)

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


def _generic_section_pass(struct, config, debug=False):
    """Generic section pass for non-weapon equipment (armor, etc.).

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb["text"]  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    # Check for variant h2 headers (not mode headers like Melee/Ranged)
    h2_tags = bs.find_all("h2", class_="title")
    # Filter out mode headers - variants have "Item N" in them
    variant_h2s = [h2 for h2 in h2_tags if re.search(r"Item\s+\d+", get_text(h2))]

    # If we have variants, we need to extract main content (before first h2) separately
    if variant_h2s:
        # Find the first h2 and split content
        first_h2 = variant_h2s[0]

        # Build main content (everything before first h2)
        main_parts = []
        for elem in bs.children:
            if elem == first_h2:
                break
            main_parts.append(str(elem))
        main_html = "".join(main_parts)
        main_bs = BeautifulSoup(main_html, "html.parser")
    else:
        main_bs = bs

    _extract_traits(main_bs, sb)
    _extract_source(main_bs, struct)

    # Extract stats into a temporary dictionary (from main content only)
    stats = {}
    # Fail fast if Group stat requires group_subtype but it's missing from config
    group_subtype = config["group_subtype"] if "Group" in config["recognized_stats"] else None
    _extract_stats_to_dict(
        main_bs, stats, config["recognized_stats"], struct["type"], group_subtype
    )
    # Move unrecognized links from stats dict to stat block links
    unrec_links = stats.pop("_unrecognized_links", None)
    if unrec_links:
        if "links" not in sb:
            sb["links"] = []
        sb["links"].extend(unrec_links)

    # Route fields to their destinations based on config
    _route_fields_to_destinations(sb, stats, config)

    # Process variants if present
    variant_trait_links = 0
    if variant_h2s:
        variants = []
        for h2 in variant_h2s:
            variant_sb, variant_links = _parse_variant_section(
                h2, config, struct.get("name", ""), debug=debug
            )
            if variant_sb:
                variants.append(variant_sb)
            variant_trait_links += variant_links
            # Remove h2 and its content from main bs (so it doesn't affect description)
            h2.decompose()
        if variants:
            sb["variants"] = variants

    links_removed = _remove_redundant_sections(
        bs if not variant_h2s else main_bs, struct.get("name", ""), debug=debug
    )
    _extract_alternate_link(bs if not variant_h2s else main_bs, struct)
    _extract_legacy_content_section(bs if not variant_h2s else main_bs, struct)
    base_material_links = _extract_base_material(
        bs if not variant_h2s else main_bs, sb, debug=debug
    )
    trait_links_converted = _extract_description(
        bs if not variant_h2s else main_bs, struct, debug=debug
    )
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    # Also add base_material links which are stored in structured objects, not the links array
    # Also add variant_trait_links for trait links converted in variant abilities
    total_removed = (
        links_removed + (trait_links_converted or 0) + base_material_links + variant_trait_links
    )
    if debug:
        sys.stderr.write(
            f"DEBUG _generic_section_pass: links_removed={links_removed}, trait_links_converted={trait_links_converted}, base_material_links={base_material_links}, variant_trait_links={variant_trait_links}, total={total_removed}\n"
        )
    return total_removed


def _weapon_section_pass(struct, config, debug=False):
    """Weapon-specific section pass that handles melee/ranged modes.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb["text"]  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    # Check if this is a combination weapon (has <h2> mode headers for Melee/Ranged)
    h2_tags = bs.find_all("h2", class_="title")
    mode_headers = [h2 for h2 in h2_tags if get_text(h2).strip().lower() in ["melee", "ranged"]]
    is_combination = len(mode_headers) > 0

    if is_combination:
        _extract_combination_weapon(bs, sb, struct, config)
    else:
        _extract_single_mode_weapon(bs, sb, struct, config)

    links_removed = _remove_redundant_sections(bs, struct.get("name", ""), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    trait_links_converted = _extract_description(bs, struct)
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    return links_removed + (trait_links_converted or 0)


def _siege_weapon_section_pass(struct, config, debug=False):
    """Siege weapon-specific section pass that handles stats and action sections.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb["text"]  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    # For siege weapons, stats span multiple <hr> sections, so we need custom extraction
    stats = {}
    _extract_siege_weapon_stats(bs, stats, config["recognized_stats"], struct["type"])

    # Separate shared vs nested fields
    shared_fields = config.get("shared_fields", [])
    nested_fields = config.get("nested_fields", [])

    # Add shared fields to top level
    for field in shared_fields:
        if field in stats:
            sb[field] = stats[field]

    # Add nested fields to siege_weapon object
    sw_obj = {}
    for field in nested_fields:
        if field in stats:
            sw_obj[field] = stats[field]

    if sw_obj:
        sb["siege_weapon"] = sw_obj

    # Extract action sections (Aim, Load, Launch, Ram, etc.) as abilities
    abilities, trait_links_converted = _extract_abilities(
        bs, struct["type"], config["recognized_stats"]
    )
    if abilities:
        sb["abilities"] = abilities

    links_removed = _remove_redundant_sections(bs, struct.get("name", ""), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    desc_trait_links = _extract_description(bs, struct)
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    return links_removed + trait_links_converted + (desc_trait_links or 0)


def _vehicle_section_pass(struct, config, debug=False):
    """Vehicle-specific section pass that handles stats similar to siege weapons.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb["text"]  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, "html.parser")

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    # Vehicles have stats similar to siege weapons
    stats = {}
    _extract_vehicle_stats(bs, stats, config["recognized_stats"], struct["type"])

    # Separate shared vs nested fields
    shared_fields = config.get("shared_fields", [])
    nested_fields = config.get("nested_fields", [])

    # Add shared fields to top level
    for field in shared_fields:
        if field in stats:
            sb[field] = stats[field]

    # Add nested fields to vehicle object
    vehicle_obj = {}
    for field in nested_fields:
        if field in stats:
            vehicle_obj[field] = stats[field]

    if vehicle_obj:
        sb["vehicle"] = vehicle_obj

    # Extract action sections as abilities (if any)
    abilities, trait_links_converted = _extract_abilities(
        bs, struct["type"], config["recognized_stats"]
    )
    if abilities:
        sb["abilities"] = abilities

    links_removed = _remove_redundant_sections(bs, struct.get("name", ""), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    desc_trait_links = _extract_description(bs, struct)  # Use generic description extraction
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    return links_removed + trait_links_converted + (desc_trait_links or 0)


def _extract_vehicle_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract vehicle stats which span across multiple <hr> tags.

    Vehicles have stats similar to siege weapons but different fields.
    """
    # Find all bold tags that are stats (not action names)
    # Vehicles typically don't have action names like siege weapons
    action_names = ["Effect", "Requirements"]  # Keep minimal list just in case

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
        preserve_html = label in ["Immunities", "Resistances", "Weaknesses", "Piloting Check"]
        value = _extract_stat_value(bold_tag, preserve_html=preserve_html)
        if value:
            stats_dict[field_name] = value


def _extract_siege_weapon_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract siege weapon stats which span across multiple <hr> tags.

    Siege weapons have stats before actions, which appear after description.
    """
    # Find all bold tags that are stats (not action names)
    action_names = ["Aim", "Load", "Launch", "Ram", "Effect", "Requirements"]

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
            # (some siege weapons have bold text in descriptions)
            continue

        # Skip labels we handle elsewhere (like Source)
        field_name = recognized_stats[label]
        if field_name is None:
            continue

        # Extract the value - preserve HTML for immunities to keep links
        preserve_html = label == "Immunities"
        value = _extract_stat_value(bold_tag, preserve_html=preserve_html)
        if value:
            stats_dict[field_name] = value


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

    # Look for "DC \d+ \w+" pattern
    dc_pattern = r"(DC\s+\d+\s+\w+)"
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
        if isinstance(current, Tag) and current.name in ("hr", "h2"):
            break
        if isinstance(current, Tag) and current.name == "br":
            break

        # If this is a <b> tag with an addon name, mark it as processed
        if isinstance(current, Tag) and current.name == "b":
            tag_text = get_text(current).strip()
            if tag_text in addon_names:
                processed_bolds.add(current)

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
    trait_links = [link for link in links if link.get("game-obj") == "Traits"]
    rules_links = []
    other_links = []

    for link in links:
        if link.get("game-obj") == "Traits":
            continue
        elif link.get("game-obj") == "Rules":
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
                parens_content = parens_content.replace(trait_name, "")
                parens_content = parens_content.replace(trait_name.lower(), "")
            else:
                trait_links_in_body.append(trait_link)

        # Remove Rules links from parentheses content
        for rules_link in rules_links:
            link_text = rules_link["name"]
            parens_content = parens_content.replace(link_text, "")
            parens_content = parens_content.replace(link_text.lower(), "")

        # Handle non-Traits links in parentheses (e.g., links to MonsterAbilities, Domains)
        for link in all_links:
            game_obj = link.get("game-obj", "")
            if game_obj and game_obj not in ("Traits", "Rules"):
                link_name = link["name"]
                if link_name.lower() in parens_content.lower():
                    traits_to_convert.append(link)
                    non_trait_links_in_parens.append(link)
                    parens_content = parens_content.replace(link_name, "")
                    parens_content = parens_content.replace(link_name.lower(), "")

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
    main_abilities = ["Aim", "Load", "Launch", "Ram", "Effect", "Requirements"]
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

        if "text" in ability or "action_type" in ability:
            abilities.append(ability)

    return (abilities if abilities else None), trait_links_converted_count


def _extract_single_mode_weapon(bs, sb, struct, config):
    """Extract stats for a regular (non-combination) weapon."""

    # Extract shared fields (traits, source)
    _extract_traits(bs, sb)
    _extract_source(bs, struct)

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

    _extract_source(bs, struct)

    # Extract fields before first h2 (both shared and weapon-level)
    shared_fields = config.get("shared_fields", [])
    weapon_fields = config.get("weapon_fields", [])
    all_weapon_stats = {}
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

        # Find mode-specific stats (bold tags after this h2, before next h2)
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

        # Build mode object
        mode_obj = {"type": "stat_block_section", "subtype": mode_name}
        if mode_traits:
            mode_obj["traits"] = mode_traits
        mode_obj.update(mode_stats)

        # Set weapon_type based on mode section (combination weapons don't have Type field in HTML)
        mode_obj["weapon_type"] = "Melee" if mode_name == "melee" else "Ranged"

        weapon_obj[mode_name] = mode_obj

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
    # Find all bold tags that are stats
    # For most equipment, stats are before the hr
    # For intelligent items (equipment type), stats can also be after the hr
    hr = bs.find("hr")
    bold_tags = []
    for tag in bs.find_all("b"):
        # For equipment type, don't stop at hr (intelligent items have stats after hr)
        if equipment_type != "equipment":
            if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
                break
        bold_tags.append(tag)

    # Track elements to remove after extraction (bold tags and their values)
    elements_to_remove = []

    # Extract and validate all labels
    for bold_tag in bold_tags:
        # Skip bold tags inside table elements (table headers/cells, not stat labels)
        if bold_tag.find_parent(["table", "td", "th"]):
            continue

        label = bold_tag.get_text().strip()

        # Skip empty labels
        if not label:
            continue

        # For equipment type, skip unrecognized labels (they may be ability names like Activate)
        # For other types, fail fast on unknown labels
        if label not in recognized_stats:
            if equipment_type == "equipment":
                # Only extract links from unrecognized bolds BEFORE the <hr>
                # (bolds after <hr> are in the ability/description section, handled by
                # _extract_abilities_from_description sweep - extracting here would double-count)
                # When no <hr> exists, skip entirely - description extraction handles all links
                if hr and not bold_tag.find_previous("hr"):
                    # This bold is in the stat area (before hr, hr exists)
                    # Extract links to prevent link loss (e.g., "Devil" field on contracts)
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
                        unrec_links = [l for l in unrec_links if "game-obj" in l]
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
    all_links = section_soup.find_all("a", attrs={"game-obj": True})

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
    # Variant markers are headings that contain:
    # - PFS.aspx link (PFS icon)
    # - "Item X" level indicator (span with "Item \d+")
    # Regular section headings may have class="title" but lack these indicators
    headings = []
    for tag in desc_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        # Check for PFS link - indicator of variant marker
        pfs_link = tag.find("a", href=lambda h: h and "PFS.aspx" in h)
        if pfs_link:
            continue  # Skip variant markers

        # Check for "Item X" level indicator
        tag_text = tag.get_text()
        if re.search(r"Item\s+\d+", tag_text):
            continue  # Skip variant markers

        headings.append(tag)

    if not headings:
        # No section headings found - return all content as main text
        return str(desc_soup), []

    # Get content before first heading (this is the main description)
    pre_heading_parts = []
    for elem in desc_soup.children:
        if elem in headings:
            break
        if elem == headings[0]:
            break
        pre_heading_parts.append(str(elem))
    pre_heading_html = "".join(pre_heading_parts)

    # Build section tree
    # Each section has: name, type, text (content), sections (children)
    def get_heading_level(tag):
        return int(tag.name[1])  # h2 -> 2, h3 -> 3, etc.

    def get_content_until_next_heading(start_heading, all_headings, heading_idx):
        """Get content after a heading until the next heading or end."""
        content_parts = []
        current = start_heading.next_sibling

        while current:
            if current in all_headings:
                break
            content_parts.append(str(current))
            current = current.next_sibling

        return "".join(content_parts)

    # Process headings into nested structure
    sections = []
    section_stack = []  # Stack of (level, section_dict) for tracking hierarchy

    for i, heading in enumerate(headings):
        level = get_heading_level(heading)
        name = heading.get_text().strip()
        content = get_content_until_next_heading(heading, headings, i)

        # Extract links from content and unwrap <a> tags
        content_soup = BeautifulSoup(content, "html.parser")
        content_links = get_links(content_soup, unwrap=True)

        section = {
            "name": name,
            "type": "section",
            "text": _normalize_whitespace(str(content_soup)),
        }
        if content_links:
            section["links"] = content_links

        # Determine where this section belongs based on heading level
        if not section_stack:
            # First section - add to root
            sections.append(section)
            section_stack.append((level, section))
        else:
            # Pop sections from stack until we find a parent (lower level number)
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()

            if section_stack:
                # Add as child of the section at top of stack
                parent = section_stack[-1][1]
                if "sections" not in parent:
                    parent["sections"] = []
                parent["sections"].append(section)
            else:
                # No parent - add to root
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
    """
    saving_throw_bold = None
    for bold in soup.find_all("b"):
        if get_text(bold).strip() == "Saving Throw":
            saving_throw_bold = bold
            break
    if not saving_throw_bold:
        return False
    # Check if any subsequent bold tag is a stage, duration, or onset
    for bold in saving_throw_bold.find_all_next("b"):
        text = get_text(bold).strip()
        if text.startswith("Stage") or text == "Maximum Duration" or text == "Onset":
            return True
    return False


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
    # Find the <b>Saving Throw</b> tag
    saving_throw_bold = None
    for bold in desc_soup.find_all("b"):
        if get_text(bold).strip() == "Saving Throw":
            saving_throw_bold = bold
            break
    if not saving_throw_bold:
        return None, []

    # Collect all nodes from Saving Throw bold to the end of desc_soup
    # Also collect preceding <br> tags (separators between narrative text and affliction)
    nodes_to_remove = []

    # Walk backwards from Saving Throw to collect preceding <br> tags and whitespace
    prev = saving_throw_bold.previous_sibling
    preceding_brs = []
    while prev:
        if (isinstance(prev, Tag) and prev.name == "br") or (
            isinstance(prev, NavigableString) and prev.strip() == ""
        ):
            preceding_brs.append(prev)
            prev = prev.previous_sibling
        else:
            break
    nodes_to_remove.extend(preceding_brs)

    # Collect from Saving Throw bold through end of content
    affliction_nodes = []
    current = saving_throw_bold
    while current:
        affliction_nodes.append(current)
        current = current.next_sibling
    nodes_to_remove.extend(affliction_nodes)

    # Build HTML string from affliction nodes (not the preceding brs)
    affliction_html = "".join(str(n) for n in affliction_nodes)

    # Parse affliction HTML to extract links
    affliction_soup = BeautifulSoup(affliction_html, "html.parser")
    affliction_links = get_links(affliction_soup, unwrap=True)

    # Unwrap remaining <a> tags (already extracted links above) and get HTML text
    while affliction_soup.a:
        affliction_soup.a.unwrap()
    affliction_html_text = str(affliction_soup)
    parts = [p.strip() for p in affliction_html_text.split(";")]

    section = {
        "type": "stat_block_section",
        "subtype": "affliction",
        "name": item_name,
    }

    def _handle_stage(title, text):
        stage = {
            "type": "stat_block_section",
            "subtype": "affliction_stage",
            "name": title,
            "text": text,
        }
        section.setdefault("stages", []).append(stage)

    first = True
    for p in parts:
        p_soup = BeautifulSoup(p, "html.parser")
        if p_soup.b:
            title = get_text(p_soup.b.extract()).strip()
            # Normalize whitespace: collapse \n and multiple spaces from HTML formatting
            # Also fix spaces before punctuation left by unwrapped tags
            newtext = re.sub(r"\s+", " ", get_text(p_soup)).strip()
            newtext = re.sub(r" ([,;.])", r"\1", newtext)
            if title == "Saving Throw":
                section["saving_throw"] = universal_handle_save_dc(newtext)
            elif title == "Onset":
                section["onset"] = newtext
            elif title == "Maximum Duration":
                section["maximum_duration"] = newtext
            elif title == "Effect":
                section["effect"] = newtext
            elif title.startswith("Stage"):
                _handle_stage(title, newtext)
            else:
                # Unknown bold label - store as context
                section.setdefault("text", newtext)
        else:
            text_content = re.sub(r"\s+", " ", get_text(p_soup)).strip()
            if text_content:
                if first:
                    section["context"] = text_content
                else:
                    section.setdefault("text", text_content)
        first = False

    if affliction_links:
        section["links"] = affliction_links

    # Remove affliction nodes from desc_soup
    for node in nodes_to_remove:
        if isinstance(node, Tag):
            node.decompose()
        elif isinstance(node, NavigableString):
            node.extract()

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
            # Get the last non-empty section (siege weapons, etc.)
            desc_section = None
            for section in reversed(sections):
                if section.strip():
                    desc_section = section
                    break

            if not desc_section:
                # Fallback if all sections are empty
                desc_section = sections[-1] if sections else ""

        desc_soup = BeautifulSoup(desc_section, "html.parser")

        # For combination weapons, stop at first <h2 class="title"> (mode section header)
        first_h2 = desc_soup.find("h2", class_="title")
        if first_h2:
            # This is a combination weapon - extract only content before first <h2>
            content_before_h2 = []
            for elem in desc_soup.children:
                if elem == first_h2:
                    break
                content_before_h2.append(str(elem))
            last_section = "".join(content_before_h2)
            desc_soup = BeautifulSoup(last_section, "html.parser")

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

    # Extract affliction (Saving Throw + Stages pattern)
    affliction = None
    affliction_links = []
    if _has_affliction_pattern(desc_soup):
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
    if non_trait_links:
        sb["links"] = non_trait_links

    # Add sections if any were extracted from headings
    if sections:
        sb["sections"] = sections

    # Extract abilities from content after description (Activate, etc.)
    # This uses the original bs which still has the action content
    trait_links_converted = _extract_abilities_from_description(bs, sb, struct, debug=debug)

    return trait_links_converted


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


def _extract_ability_fields(ability_soup, ability):
    """Extract sub-fields (Frequency, Trigger, Effect, Requirements) from ability soup.

    Modifies ability dict in place, adding fields like 'frequency', 'trigger', etc.
    Also adds any links found in field values to ability['links'].
    Removes the extracted fields from ability_soup.

    Args:
        ability_soup: BeautifulSoup object containing the ability HTML
        ability: dict to populate with extracted fields
    """
    field_names = [
        "Frequency",
        "Trigger",
        "Effect",
        "Requirements",
        "Critical Success",
        "Success",
        "Failure",
        "Critical Failure",
        "Destruction",
    ]
    for field in field_names:
        field_bold = ability_soup.find("b", string=lambda s, f=field: s and s.strip() == f)
        if not field_bold:
            continue

        # Get value after the bold tag until next bold or end
        value_parts = []
        nodes_to_remove = []
        field_current = field_bold.next_sibling
        while field_current:
            if isinstance(field_current, Tag) and field_current.name == "b":
                break
            value_parts.append(str(field_current))
            nodes_to_remove.append(field_current)
            field_current = field_current.next_sibling

        value_html = "".join(value_parts).strip()
        # Clean up: remove leading semicolons and whitespace
        value_html = re.sub(r"^[\s;]+", "", value_html)
        # Remove trailing <br> tags and semicolons
        value_html = re.sub(r"<br\s*/?>[\s]*$", "", value_html)
        value_html = re.sub(r"[\s;]+$", "", value_html)

        if value_html:
            # Extract links from value
            value_text, value_links = extract_links(value_html)
            # Only include links with game-obj attribute (for link accounting consistency)
            value_links = [link for link in value_links if "game-obj" in link]
            # Convert <br> tags to newlines, then normalize whitespace
            value_text = re.sub(r"<br\s*/?>", "\n", value_text)
            # Normalize whitespace (collapse multiple spaces/newlines)
            value_text = _normalize_whitespace(value_text)

            field_key = field.lower().replace(" ", "_")
            if field_key == "requirements":
                field_key = "requirement"

            ability[field_key] = value_text

            # Add links to ability's links array
            if value_links:
                if "links" not in ability:
                    ability["links"] = []
                ability["links"].extend(value_links)

        # Remove the field bold and its value nodes from soup
        for node in nodes_to_remove:
            if isinstance(node, Tag):
                node.decompose()
            elif isinstance(node, NavigableString):
                node.extract()
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

    # Check for activation_time (semicolon-separated, e.g., "command, envision; 1 minute")
    # Split on semicolon first to separate activation types from time
    activation_time = None
    if ";" in activate_content:
        parts = activate_content.split(";", 1)
        activate_content = parts[0].strip()
        if len(parts) > 1:
            time_part = parts[1].strip()
            # Check if it looks like a time value (contains number + time unit)
            if re.search(r"\d+\s*(minute|hour|round|day|action)", time_part, re.IGNORECASE):
                # time_part may contain parenthesized trait links, e.g.,
                # "10 minutes (fortune, mental)" with <a game-obj="Traits"> tags.
                # Extract those traits before storing activation_time.
                time_soup = BeautifulSoup(time_part, "html.parser")
                time_trait_links = []
                for a_tag in time_soup.find_all("a", attrs={"game-obj": "Traits"}):
                    _, link = extract_link(a_tag)
                    time_trait_links.append(link)
                    a_tag.unwrap()
                time_text = _normalize_whitespace(str(time_soup))
                # Extract trait names from parentheses and build trait objects
                if time_trait_links and "(" in time_text:
                    paren_start = time_text.find("(")
                    paren_end = time_text.find(")")
                    if paren_end > paren_start:
                        trait_names = [tl["name"] for tl in time_trait_links]
                        if trait_names:
                            traits = build_objects("stat_block_section", "trait", trait_names)
                            if "traits" not in ability:
                                ability["traits"] = traits
                            else:
                                ability["traits"].extend(traits)
                            trait_links_converted += len(time_trait_links)
                        # Remove the parenthesized section from the time text
                        activation_time = time_text[:paren_start].strip()
                    else:
                        activation_time = time_text
                else:
                    activation_time = time_text

    # Parse the activate content soup to extract links and traits
    content_soup = BeautifulSoup(activate_content, "html.parser")

    # Extract all links first
    all_links = get_links(content_soup, unwrap=True)

    # Separate trait links from other links
    trait_links = [link for link in all_links if link.get("game-obj") == "Traits"]
    other_links = [link for link in all_links if link.get("game-obj") != "Traits"]

    # Get text after unwrapping links
    text = _normalize_whitespace(str(content_soup))

    # Check if there are traits in parentheses
    traits_to_convert = []
    if "(" in text:
        paren_start = text.find("(")
        paren_end = text.find(")")
        if paren_end > paren_start:
            parens_content = text[paren_start + 1 : paren_end].strip()
            text_before = text[:paren_start].strip()

            # Check which trait links are in the parentheses
            for trait_link in trait_links:
                trait_name = trait_link["name"]
                if trait_name.lower() in parens_content.lower():
                    traits_to_convert.append(trait_link)
                    # Remove trait name from parens content
                    parens_content = parens_content.replace(trait_name, "")
                    parens_content = parens_content.replace(trait_name.lower(), "")
                else:
                    # Trait link not in parentheses - keep as regular link
                    other_links.append(trait_link)

            # Build trait objects from linked traits only
            # Note: Plain text in parentheses (like "Treat Disease") is NOT a trait -
            # only actual Traits.aspx links should be converted to trait objects
            trait_names = [tl["name"] for tl in traits_to_convert]
            if trait_names:
                traits = build_objects("stat_block_section", "trait", trait_names)
                ability["traits"] = traits
                trait_links_converted = len(traits_to_convert)

            # The text before parentheses is the activation (e.g., "command", "Interact")
            # BUT: If text_before looks like a time value (e.g., "1 minute"), it's activation_time, not activation
            if text_before and re.search(
                r"^\d+\s*(minute|hour|round|day|action)s?$", text_before, re.IGNORECASE
            ):
                # Text before parens is a time value
                activation_time = text_before
                activation = ""
            else:
                activation = text_before
            # Note: In remastered format, parentheses contain traits like (concentrate, manipulate)
            # which describe the action's traits, not the activation method. These stay as traits only.
    else:
        # No parentheses - all trait links are body links
        other_links.extend(trait_links)
        # The entire text is the activation
        activation = text

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

    # Find all ability-starting bold tags:
    # 1. <b>Activate</b> tags
    # 2. Bold tags followed by action icon spans (named abilities like "Divert Lightning [reaction]")
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
        # Skip sub-field bolds - these are part of an ability, not a new ability
        if bold_text in sub_field_names:
            continue
        # Skip named activation bolds (start with dash - these follow Activate)
        if bold_text and (bold_text[0] in "\u2014\u2013-" or ord(bold_text[0]) == 226):
            continue
        # Check if followed by action icon span (named ability with action cost)
        next_sib = bold.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and not next_sib.strip():
            next_sib = next_sib.next_sibling
        if (
            isinstance(next_sib, Tag)
            and next_sib.name == "span"
            and "action" in next_sib.get("class", [])
        ):
            ability_bolds.append(bold)

    if not ability_bolds:
        return 0

    trait_links_converted = 0
    abilities = []
    elements_to_remove = []  # Track all elements belonging to abilities for cleanup

    # Process each ability (Activate or named)
    for i, ability_bold in enumerate(ability_bolds):
        bold_text = ability_bold.get_text().strip()
        is_activate = bold_text == "Activate"

        # Collect content from this ability until next ability or end
        ability_parts = [str(ability_bold)]
        ability_elements = [ability_bold]  # Track actual elements for removal
        current = ability_bold.next_sibling

        # Find where this ability ends (next ability bold or end)
        next_ability = ability_bolds[i + 1] if i + 1 < len(ability_bolds) else None

        while current:
            # Stop if we hit the next ability bold (use identity, not equality)
            if next_ability and current is next_ability:
                break
            # Also check against remaining ability bolds
            if any(current is ab for ab in ability_bolds[i + 1 :]):
                break
            # Stop at <hr> tags - content after hr is description, not ability
            if isinstance(current, Tag) and current.name == "hr":
                break
            ability_parts.append(str(current))
            ability_elements.append(current)
            current = current.next_sibling

        # Track elements for later removal from bs
        elements_to_remove.extend(ability_elements)

        ability_html = "".join(ability_parts)
        ability_soup = BeautifulSoup(ability_html, "html.parser")

        # Build ability object
        ability = build_object("stat_block_section", "ability", bold_text)
        ability["ability_type"] = "offensive"

        # Extract action type from action icon span(s)
        # Some abilities have variable action cost like "[one-action] to [two-actions]"
        action_spans = ability_soup.find_all("span", class_="action")
        action_titles = []
        for action_span in action_spans:
            action_title = action_span.get("title", "")
            if action_title:
                # Normalize action names to match schema
                if action_title == "Single Action":
                    action_title = "One Action"
                action_titles.append(action_title)
            action_span.decompose()

        # Deduplicate action titles (nested abilities in <ul><li> can cause
        # the parent ability to collect action spans from both itself and the nested one)
        seen_actions = set()
        unique_action_titles = []
        for t in action_titles:
            if t not in seen_actions:
                seen_actions.add(t)
                unique_action_titles.append(t)
        action_titles = unique_action_titles

        if action_titles:
            if len(action_titles) == 1:
                # Single action type
                ability["action_type"] = {
                    "type": "stat_block_section",
                    "subtype": "action_type",
                    "name": action_titles[0],
                }
            else:
                # Variable action cost (e.g., "[one-action] to [two-actions]")
                # Map to valid schema values: "One or Two Actions", "One to Three Actions", etc.
                action_name = " or ".join(action_titles)
                # Handle common patterns
                action_name_map = {
                    "One Action or Two Actions": "One or Two Actions",
                    "Two Actions or Three Actions": "Two or Three Actions",
                    "One Action or Three Actions": "One or Three Actions",
                    "One Action or Two Actions or Three Actions": "One to Three Actions",
                    "Free Action or One Action": "Free Action or Single Action",
                    "Reaction or One Action": "Reaction or One Action",
                }
                action_name = action_name_map.get(action_name, action_name)
                ability["action_type"] = {
                    "type": "stat_block_section",
                    "subtype": "action_type",
                    "name": action_name,
                }

        # Extract sub-fields: Frequency, Trigger, Effect, Requirements, etc.
        _extract_ability_fields(ability_soup, ability)

        if is_activate:
            # Extract the main text after Activate (before first sub-field)
            # This is typically "Interact" or "command (traits)"
            activate_bold_new = ability_soup.find(
                "b", string=lambda s: s and s.strip() == "Activate"
            )
            if activate_bold_new:
                # Collect content after Activate bold until next <b> tag
                # BUT: If next <b> is a named activation (starts with em-dash), include content after it
                content_parts = []
                nodes_to_remove_act = []
                act_current = activate_bold_new.next_sibling

                # Skip whitespace NavigableStrings to find first non-whitespace sibling
                while (
                    act_current
                    and isinstance(act_current, NavigableString)
                    and not act_current.strip()
                ):
                    nodes_to_remove_act.append(act_current)
                    act_current = act_current.next_sibling

                # Check if immediately followed by a named activation bold (e.g., "—Dim Sight")
                ability_name, act_current = _parse_named_activation(act_current)
                if ability_name:
                    ability["ability_name"] = ability_name

                while act_current:
                    if isinstance(act_current, Tag) and act_current.name == "b":
                        break
                    content_parts.append(str(act_current))
                    nodes_to_remove_act.append(act_current)
                    act_current = act_current.next_sibling

                # Remove activation content nodes from ability_soup so sweep doesn't re-extract
                for node in nodes_to_remove_act:
                    if isinstance(node, Tag):
                        node.decompose()
                    elif isinstance(node, NavigableString):
                        node.extract()

                activate_content = "".join(content_parts).strip()
                # Clean up leading/trailing semicolons
                activate_content = re.sub(r"^[\s;]+", "", activate_content)
                activate_content = re.sub(r"[\s;]+$", "", activate_content)
                # Clean up leading "to" or "or" from variable action cost patterns
                # e.g., "[one-action] to [two-actions] command" becomes "to command" after span removal
                activate_content = re.sub(
                    r"^\s*(to|or)\s+", "", activate_content, flags=re.IGNORECASE
                )

                if activate_content:
                    trait_links_converted += _parse_activation_content(activate_content, ability)

            # Transform "Activate" abilities into activation objects
            ability["subtype"] = "activation"
            # If there's an ability_name, move it to activation_name
            if "ability_name" in ability:
                ability["activation_name"] = ability["ability_name"]
                del ability["ability_name"]

        # Sweep remaining ability_soup for any unextracted links
        # This captures links in content not handled by sub-field extraction or
        # activation parsing (e.g., poison sections, non-Activate ability content)
        for remaining_a in ability_soup.find_all("a", attrs={"game-obj": True}):
            _, link = extract_link(remaining_a)
            if link:
                if "links" not in ability:
                    ability["links"] = []
                ability["links"].append(link)

        abilities.append(ability)

    # Deduplicate links ACROSS abilities only - when a nested Activate is inside a
    # <ul><li> that's a sibling of an earlier ability, the sibling traversal
    # includes the <ul> in the earlier ability's content, causing links from the
    # nested ability to appear in both. Keep links in the later (more specific) ability.
    # Do NOT deduplicate within a single ability (same spell can appear at multiple
    # levels in staves, e.g., fireball at 3rd and 6th level).
    if len(abilities) > 1:
        for i in range(len(abilities) - 1):
            if "links" not in abilities[i]:
                continue
            # Collect links from all later abilities
            later_links = set()
            for j in range(i + 1, len(abilities)):
                for link in abilities[j].get("links", []):
                    later_links.add((link.get("name"), link.get("game-obj"), link.get("aonid", "")))
            # Remove from this ability any links that also appear in later abilities
            unique_links = [
                link
                for link in abilities[i]["links"]
                if (link.get("name"), link.get("game-obj"), link.get("aonid", ""))
                not in later_links
            ]
            abilities[i]["links"] = unique_links
            if not abilities[i]["links"]:
                del abilities[i]["links"]

    # Remove all ability elements from original soup (not just Activate bold tags)
    for elem in elements_to_remove:
        if hasattr(elem, "decompose") and elem.parent is not None:  # Tag with parent still in tree
            elem.decompose()
        elif isinstance(elem, NavigableString) and elem.parent is not None:
            elem.extract()

    # Add abilities to statistics.abilities
    if abilities:
        if "statistics" not in sb:
            sb["statistics"] = {"type": "stat_block_section", "subtype": "statistics"}
        if "abilities" not in sb["statistics"]:
            sb["statistics"]["abilities"] = []
        sb["statistics"]["abilities"].extend(abilities)

        # Clean up sb["text"] to remove activation cruft that was extracted
        # The text may contain patterns like "**Activate** command; **Frequency** ..." that
        # were already extracted into abilities
        if "text" in sb and sb["text"]:
            text = sb["text"]
            # Remove activation patterns: <b>Activate</b> or **Activate** followed by content until end
            # Handles: <br/> tags, whitespace, and optional space inside <b> tag
            # Combined pattern handles both HTML and markdown formats with consistent flags
            text = re.sub(
                r"(?:<br\s*/?>[\s\n]*)*\s*(?:<b>\s*Activate\s*</b>|\*\*Activate\*\*).*$",
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # Normalize whitespace and trailing content
            text = text.strip()
            if text:
                sb["text"] = text
            else:
                del sb["text"]

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
    if normalizer:
        result = normalizer(sb)
        return result if result else 0
    return 0


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

    # Extract modifier from parentheses if present
    modifiers = []
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
    # Note: siege weapons don't have bulk
    _normalize_price(sb)

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

    # Only include links with game-obj attribute - these are the ones tracked by
    # link accounting. Links without game-obj (e.g., listing page links like
    # Innovations.aspx) are not counted in the HTML pass and would cause overcounting.
    links = [link for link in links if "game-obj" in link]

    result = {"type": "stat_block_section", "subtype": subtype, "text": text.strip()}

    if links:
        result["links"] = links

    return result


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
        # Only include links with game-obj attribute (for link accounting consistency)
        cr_links = [link for link in cr_links if "game-obj" in link]
        # Normalize whitespace (collapse newlines from HTML formatting to single spaces)
        sb["craft_requirements"] = _normalize_whitespace(cr_text)
        if cr_links:
            if "links" not in sb:
                sb["links"] = []
            sb["links"].extend(cr_links)

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
            hands_links = [link for link in hands_links if "game-obj" in link]
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

        # Check if there are traits in parentheses
        if "(" in clean_text and ")" in clean_text:
            paren_start = clean_text.find("(")
            paren_end = clean_text.find(")")
            if paren_end > paren_start:
                parens_content = clean_text[paren_start + 1 : paren_end].strip()
                text_before = clean_text[:paren_start].strip()

                # Match trait links to content in parentheses
                traits_to_convert = []
                for trait_link in trait_links:
                    trait_name = trait_link["name"]
                    if trait_name.lower() in parens_content.lower():
                        traits_to_convert.append(trait_link)
                        # Remove trait name from parens content
                        parens_content = parens_content.replace(trait_name, "")
                        parens_content = parens_content.replace(trait_name.lower(), "")
                    else:
                        # Trait link not in parentheses - keep as regular link
                        other_links.append(trait_link)

                # Clean up commas and whitespace from parens content
                parens_content = parens_content.replace(",", "").strip()

                # Handle any remaining text in parentheses as unlinked trait names
                unlinked_traits = []
                if parens_content:
                    for pt in parens_content.split():
                        pt = pt.strip()
                        if pt and not pt.isdigit():
                            unlinked_traits.append(pt)

                # Build trait objects
                trait_names = [tl["name"] for tl in traits_to_convert] + unlinked_traits
                if trait_names:
                    traits = build_objects("stat_block_section", "trait", trait_names)
                    ability["traits"] = traits
                    trait_links_converted = len(traits_to_convert)

                # Store activation types as list of objects
                if text_before:
                    ability["activation_types"] = _parse_activation_types(text_before)
        else:
            # No parentheses - all trait links are body links
            other_links.extend(trait_links)
            # Store activation types as list of objects
            if clean_text:
                ability["activation_types"] = _parse_activation_types(clean_text)

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
    # Only extract links with game-obj attribute (for link accounting)
    links_in_html = []
    for link_tag in bs.find_all("a"):
        # Skip links without game-obj attribute - they're not counted in link accounting
        if not link_tag.has_attr("game-obj"):
            continue
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
        speed_obj = _parse_single_speed(entry.strip())
        if speed_obj:
            movement_array.append(speed_obj)

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


def trait_db_pass(struct):
    """Enrich minimal trait objects with full trait data from database."""

    def _merge_classes(trait, db_trait):
        """Merge class arrays from extracted trait and database trait."""
        trait_classes = set(trait.get("classes", []))
        db_trait_classes = set(db_trait.get("classes", []))
        db_trait["classes"] = list(trait_classes | db_trait_classes)

    def _handle_trait_link(db_trait):
        """Handle edition matching for traits with alternate links."""
        trait = json.loads(db_trait["trait"])
        edition = trait["edition"]
        if edition == struct["edition"]:
            return trait
        if "alternate_link" not in trait:
            return trait
        # Fetch the alternate edition version
        kwargs = {}
        if edition == "legacy":
            kwargs["legacy_trait_id"] = db_trait["trait_id"]
        else:
            kwargs["remastered_trait_id"] = db_trait["trait_id"]
        data = fetch_trait_by_link(curs, **kwargs)
        assert data, f"{data} | {trait}"
        return json.loads(data["trait"])

    def _handle_value(trait):
        """Extract value from trait names like 'Entrench Melee' -> name='Entrench', value='Melee'."""
        # Special case: "range increment X feet" -> name="range", value="increment X feet"
        original_name = trait["name"]
        if original_name.lower().startswith("range increment"):
            trait["name"] = "range"
            trait["value"] = original_name[6:].strip()  # Everything after "range "
            return

        m = re.search(r"(.*) (\+?d?[0-9]+.*)", trait["name"])
        if m:
            # Numeric or dice values like "Deadly d8"
            name, value = m.groups()
            trait["name"] = name.strip()  # Remove trailing whitespace
            trait["value"] = value.strip()
        elif " " in trait["name"]:
            # Word values like "Entrench Melee"
            parts = trait["name"].split(" ", 1)
            # Try with first word as the base trait name
            trait["name"] = parts[0].strip()
            trait["value"] = parts[1].strip()

    def _check_trait(trait, parent):
        """Look up trait in database and replace with enriched version."""

        original_name = trait["name"]

        # Handle alignment abbreviations (CG -> Chaotic Good, LG -> Lawful Good, etc.)
        full_alignment = universal_handle_alignment(trait["name"])
        if full_alignment:
            trait["name"] = full_alignment

        # Handle trait name mismatches in source HTML
        trait_name_fixes = {
            "concentration": "Concentrate",  # HTML link text doesn't match trait name
        }
        if trait["name"] in trait_name_fixes:
            trait["name"] = trait_name_fixes[trait["name"]]

        # Try full name first (handles traits like "Ranged Trip", "Double Barrel", "Critical Fusion")
        data = fetch_trait_by_name(curs, trait["name"])

        # If not found and name has space, try splitting into name + value
        # E.g., "Entrench Melee" -> name="Entrench", value="Melee"
        if not data and " " in trait["name"]:
            _handle_value(trait)
            data = fetch_trait_by_name(curs, trait["name"])

        assert data, "Trait not found in database: {} (original: {})".format(
            trait["name"],
            original_name,
        )

        db_trait = _handle_trait_link(data)
        _merge_classes(trait, db_trait)

        # Note: Don't verify link aonid matches db_trait aonid because traits can have
        # legacy/remastered versions with different aonids. The link points to the
        # original version, but _handle_trait_link fetches the edition-appropriate version.

        # Replace trait in parent list
        assert isinstance(parent, list), parent
        index = parent.index(trait)

        # Preserve value if extracted
        if "value" in trait:
            db_trait["value"] = trait["value"]

        # Remove fields that shouldn't be in embedded traits
        if "aonid" in db_trait:
            del db_trait["aonid"]
        if "license" in db_trait:
            del db_trait["license"]

        # Sort classes for consistency
        db_trait["classes"].sort()
        parent[index] = db_trait

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()

        # Walk the structure and enrich all traits
        walk(struct, test_key_is_value("subtype", "trait"), _check_trait)


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
