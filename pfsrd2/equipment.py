import os
import json
import sys
import re
import importlib
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString, Tag
from universal.markdown import markdown_pass
from universal.universal import parse_universal, entity_pass
from universal.universal import is_trait, extract_link, extract_links
from universal.universal import string_with_modifiers_from_string_list
from universal.utils import split_maintain_parens
from universal.universal import source_pass, extract_source
from universal.universal import aon_pass, restructure_pass
from universal.universal import remove_empty_sections_pass, get_links
from universal.universal import walk, test_key_is_value
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.universal import link_modifiers
from universal.universal import link_values, link_value
from universal.universal import edition_pass
from universal.universal import href_filter
from universal.files import makedirs, char_replace
from universal.creatures import write_creature
from universal.utils import log_element, is_tag_named, get_text
from universal.utils import get_unique_tag_set
from universal.utils import get_text, bs_pop_spaces
from universal.utils import clear_garbage
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import trait_parse
from pfsrd2.trait import extract_span_traits
from pfsrd2.action import extract_action_type
from pfsrd2.license import license_pass, license_consolidation_pass
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name, fetch_trait_by_link
import pfsrd2.constants as constants
# Import stat block parsing utilities from creatures.py
from pfsrd2.creatures import split_stat_block_line, rebuilt_split_modifiers
from pfsrd2.creatures import parse_section_modifiers, parse_section_value
# Import DC/save parsing from universal
from universal.creatures import universal_handle_save_dc, universal_handle_range


# Equipment Type Configuration Registry
# To add a new equipment type, just add a configuration dictionary here
# Note: 'normalize_fields' will be populated after the normalizer functions are defined
def _normalize_whitespace(text):
    """Normalize whitespace in text by collapsing multiple whitespace characters to single space.

    After unwrapping links with BeautifulSoup, there may be extra newlines or spaces
    that were part of the HTML formatting. This function normalizes them.
    """
    # Replace any sequence of whitespace characters (spaces, tabs, newlines) with a single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _trait_class_matcher(c):
    """Match BeautifulSoup class attributes that start with 'trait'.

    BeautifulSoup passes class as string if single class, list if multiple, or None if no class.
    This matcher function works with all formats.
    """
    if not c:
        return False
    if isinstance(c, str):
        return c.startswith('trait')
    else:  # list of classes
        return any(cls.startswith('trait') for cls in c)


def _count_links_in_html(html_text, exclude_name=None, debug=False):
    """Count all <a> tags with game-obj attribute in HTML.

    This counts links that need to be extracted into structured link objects.
    Only counts internal game links (with game-obj attribute).

    Excludes:
    - Self-references (links whose text matches exclude_name)
    - Trait name links (links inside <span class="trait*"> tags, replaced by database)
    - Equipment group links (WeaponGroups/ArmorGroups in stat lines, replaced by database)

    Args:
        html_text: HTML text to count links in
        exclude_name: If provided, exclude links whose text matches this name (for self-references)
        debug: If True, print debug info about found links
    """
    soup = BeautifulSoup(html_text, 'html.parser')
    # Find all <a> tags that have game-obj attribute (internal game links)
    all_links = soup.find_all('a', attrs={'game-obj': True})

    if debug:
        import sys
        sys.stderr.write(f"DEBUG: Found {len(all_links)} total <a game-obj> tags\n")
        for link in all_links:
            sys.stderr.write(f"  - {link.get_text().strip()} ({link.get('game-obj')})\n")

    links = all_links

    # Exclude self-references if exclude_name is provided
    if exclude_name:
        before = len(links)
        links = [l for l in links if l.get_text().strip() != exclude_name]
        if debug and len(links) < before:
            sys.stderr.write(f"DEBUG: Excluded {before - len(links)} self-references to '{exclude_name}'\n")

    # Exclude trait links ONLY if inside <span class="trait*"> tags (stat block traits)
    # Regular trait links in text (like description text or ability body text) should
    # remain as link objects, NOT be converted to traits. Only trait links in:
    # 1. <span class="trait*"> tags (main stat block traits at top)
    # 2. Opening parentheses of abilities (handled separately in _extract_abilities)
    # should be converted to trait objects.
    def is_trait_link(link):
        # Check if inside <span class="trait*"> tags (stat block trait)
        parent = link.parent
        if parent and parent.name == 'span':
            parent_classes = parent.get('class', [])
            if isinstance(parent_classes, str):
                return parent_classes.startswith('trait')
            else:  # list of classes
                return any(cls.startswith('trait') for cls in parent_classes)
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
        return 'more recent version' in link_text or 'newer version' in link_text

    # Exclude equipment group links (weapon groups, armor groups)
    # These links are replaced by database group data during equipment_group_pass enrichment
    # Group links appear as: <b>Group</b> <u><a game-obj="WeaponGroups">Brawling</a></u>
    # The <u> parent with a preceding <b>Group</b> sibling indicates this is a stat line group link
    def is_group_link(link):
        # Check if link is to a group object type
        game_obj = link.get('game-obj', '')
        if game_obj not in ['WeaponGroups', 'ArmorGroups']:
            return False

        # Check if it's in a stat line context (parent is <u> with preceding <b> sibling)
        from bs4 import NavigableString, Tag
        parent = link.parent
        if parent and parent.name == 'u':
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

            if prev_sibling and isinstance(prev_sibling, Tag) and prev_sibling.name == 'b':
                from universal.utils import get_text
                label_text = get_text(prev_sibling).strip()
                if label_text in ['Group', 'Armor Group']:
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
            if isinstance(parent, Tag) and parent.name == 'div':
                div_classes = parent.get('class', [])
                if 'siderbarlook' in div_classes:
                    # Check if it contains alternate version text
                    from universal.utils import get_text
                    div_text = get_text(parent).strip()
                    if 'Legacy version' in div_text or 'Remastered version' in div_text:
                        return True
                    return False
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


def _count_links_in_json(obj, debug=False, _links_found=None, _is_top_level=False):
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
        if obj.get('subtype') == 'trait':
            return 0

        # Skip counting links inside weapon/armor group objects (database enrichment adds these)
        # Group subtypes: 'weapon_group', 'armor_group', 'siege_weapon_group'
        subtype = obj.get('subtype', '')
        if 'group' in subtype and subtype != 'item_group':  # item_group is different
            return 0

        # Check if this is a link object (regular link only, not alternate_link)
        # alternate_link objects are excluded from counting because they're extracted from
        # a special siderbarlook div and already excluded from the initial HTML count
        obj_type = obj.get('type')
        if obj_type == 'link':
            count += 1
            if debug and _links_found is not None:
                name = obj.get('name', f"<{obj_type}>")
                _links_found.append(f"{name} ({obj.get('game-obj', '?')})")
        elif obj_type == 'alternate_link':
            # Skip counting alternate_link objects
            if debug and _links_found is not None:
                name = obj.get('name', f"<{obj_type}>")
                _links_found.append(f"{name} ({obj.get('game-obj', '?')}) [SKIPPED - alternate_link]")
            pass  # Don't count alternate_link objects
        else:
            # Only recurse if this is NOT a link object (to avoid double-counting)
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    count += _count_links_in_json(value, debug=debug, _links_found=_links_found, _is_top_level=False)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                count += _count_links_in_json(item, debug=debug, _links_found=_links_found, _is_top_level=False)

    if debug and _is_top_level and _links_found is not None:
        # Top-level call, print results
        import sys
        sys.stderr.write(f"DEBUG: Links found in JSON ({len(_links_found)} total):\n")
        for link in _links_found:
            sys.stderr.write(f"  - {link}\n")

    return count


EQUIPMENT_TYPES = {
    'armor': {
        'recognized_stats': {
            'Source': None,  # Handled separately
            'Access': 'access',
            'Price': 'price',
            'AC Bonus': 'ac_bonus',
            'Dex Cap': 'dex_cap',
            'Check Penalty': 'check_penalty',
            'Speed Penalty': 'speed_penalty',
            'Strength': 'strength',
            'Bulk': 'bulk',
            'Category': 'category',
            'Group': 'armor_group'
        },
        # Fields that are shared (top-level) vs armor-specific (nested in armor object)
        'shared_fields': ['access', 'price', 'bulk'],
        'nested_fields': ['category', 'ac_bonus', 'dex_cap', 'check_penalty', 'speed_penalty', 'strength', 'armor_group'],
        'group_table': 'armor_groups',
        'group_sql_module': 'pfsrd2.sql.armor_groups',
        'group_subtype': 'armor_group',
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'armor',
        'normalize_fields': None,  # Set after function definition
    },
    'weapon': {
        'recognized_stats': {
            'Source': None,  # Handled separately
            'Access': 'access',
            'Price': 'price',
            'Damage': 'damage',
            'Bulk': 'bulk',
            'Hands': 'hands',
            'Range': 'range',
            'Reload': 'reload',
            'Type': 'weapon_type',  # Renamed to avoid collision with structural 'type' field
            'Category': 'category',
            'Group': 'weapon_group',
            'Ammunition': 'ammunition',
            'Favored Weapon': 'favored_weapon',  # Deities that favor this weapon
            'PFS Note': None,  # Skip - PFS-specific note, not weapon stat
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price, bulk, access)
        # - weapon_fields: nested in weapon object (category, favored_weapon)
        # - mode_fields: nested in melee/ranged objects (damage, weapon_type, weapon_group, range, reload, ammunition, hands)
        #   Note: ammunition and hands can appear in weapon_fields OR mode_fields (combination weapons have them mode-specific)
        'shared_fields': ['access', 'price', 'bulk'],
        'weapon_fields': ['category', 'hands', 'ammunition', 'favored_weapon'],
        'mode_fields': ['damage', 'weapon_type', 'weapon_group', 'range', 'reload', 'ammunition', 'hands'],
        'group_table': 'weapon_groups',
        'group_sql_module': 'pfsrd2.sql.weapon_groups',
        'group_subtype': 'weapon_group',
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'weapons',
        'normalize_fields': None,  # Set after function definition
    },
    'shield': {
        'recognized_stats': {
            'Source': None,  # Handled separately
            'Price': 'price',
            'AC Bonus': 'ac_bonus',
            'Speed Penalty': 'speed_penalty',
            'Bulk': 'bulk',
            'Hardness': 'hardness',
            'HP (BT)': 'hp_bt',
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price, bulk)
        # - nested_fields: nested in shield object (ac_bonus, speed_penalty, hardness, hp_bt)
        'shared_fields': ['price', 'bulk'],
        'nested_fields': ['ac_bonus', 'speed_penalty', 'hardness', 'hp_bt'],
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'shields',
        'normalize_fields': None,  # Set after function definition
    },
    'siege_weapon': {
        'recognized_stats': {
            'Source': None,  # Handled separately
            'Price': 'price',
            'Usage': 'usage',
            'Crew': 'crew',
            'Proficiency': 'proficiency',
            'Ammunition': 'ammunition',
            'Space': 'space',
            'AC': 'ac',
            'Fort': 'fort',
            'Ref': 'ref',
            'Hardness': 'hardness',
            'HP': 'hp_bt',  # HTML has just "HP" (value includes "(BT 20)" part)
            'Immunities': 'immunities',
            'Speed': 'speed',
            # Action sections (handled separately by section_pass)
            'Aim': None,
            'Load': None,
            'Launch': None,
            'Ram': None,
            'Effect': None,
            'Requirements': None,
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price)
        # - nested_fields: nested in siege_weapon object (all others)
        'shared_fields': ['price'],
        'nested_fields': ['usage', 'crew', 'proficiency', 'ammunition', 'space',
                          'ac', 'fort', 'ref', 'hardness', 'hp_bt', 'immunities', 'speed'],
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'siege_weapons',
        'normalize_fields': None,  # Set after function definition
    },
    'vehicle': {
        'recognized_stats': {
            'Source': None,  # Handled separately
            'Price': 'price',
            'Space': 'space',
            'Crew': 'crew',
            'Passengers': 'passengers',
            'Piloting Check': 'piloting_check',
            'AC': 'ac',
            'Fort': 'fort',
            'Hardness': 'hardness',
            'HP': 'hp_bt',  # HTML has just "HP" (value includes "(BT 20)" part)
            'Immunities': 'immunities',
            'Resistances': 'resistances',
            'Weaknesses': 'weaknesses',
            'Speed': 'speed',
            'Collision': 'collision',
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price)
        # - nested_fields: nested in vehicle object (all others)
        'shared_fields': ['price'],
        'nested_fields': ['space', 'crew', 'passengers', 'piloting_check',
                          'ac', 'fort', 'hardness', 'hp_bt', 'immunities', 'resistances', 'weaknesses', 'speed', 'collision'],
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'vehicles',
        'normalize_fields': None,  # Set after function definition
    },
}


# Equipment items that are allowed to have span tags (for broken HTML with action icons)
# Only add items here after manually verifying the HTML is genuinely broken
EQUIPMENT_SPANS_ALLOWED = [
    # Add equipment names here as needed, e.g.:
    # "Vonthos's Golden Bridge",
]


def equipment_markdown_valid_set(struct, name, path, validset):
    """Allow span tags in equipment markdown for specific items with broken HTML.

    Like creatures, only specific equipment items are allowed to have spans.
    This is for cases where the HTML is genuinely broken (missing <br> or <b> tags).
    """
    if name in EQUIPMENT_SPANS_ALLOWED:
        validset.add("span")


def parse_equipment(filename, options):
    """Universal equipment parser - supports armor, weapons, and future equipment types."""
    import sys

    equipment_type = options.equipment_type
    config = EQUIPMENT_TYPES[equipment_type]

    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Equipment HTML has flat structure - parse directly from HTML
    details = parse_equipment_html(filename, equipment_type)

    struct = restructure_equipment_pass(details, equipment_type)

    # COUNT INITIAL LINKS: Count all <a> tags with game-obj in the content HTML
    # Exclude self-references (links from item to itself, typically in title)
    item_name = struct.get('name', '')
    debug_mode = False  # Set to filename for debugging, e.g.: basename == "Armor.aspx.ID_36.html"
    initial_link_count = _count_links_in_html(details["text"], exclude_name=item_name, debug=debug_mode)
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
    normalize_numeric_fields_pass(struct, config)
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], '', fxn_valid_tags=equipment_markdown_valid_set)
    # Determine edition (legacy vs remastered) before removing empty sections
    edition = edition_pass(struct['sections'])
    struct['edition'] = edition

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
    if 'group_table' in config:
        equipment_group_pass(struct, config)
    # Populate creature-style buckets (statistics, defense, offense) from old structure
    # This maintains backward compatibility during migration
    populate_equipment_buckets_pass(struct)
    remove_empty_sections_pass(struct)

    if not options.skip_schema:
        struct['schema_version'] = 1.0
        validate_against_schema(struct, config['schema_file'])
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, config['output_subdir'], name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


# Maintain backward compatibility - parse_armor is now an alias
def parse_armor(filename, options):
    """Backward compatibility wrapper for parse_equipment."""
    options.equipment_type = 'armor'
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

    soup = BeautifulSoup(html, 'html.parser')

    # Enrich href attributes with game-obj and aonid (same as parse_universal does)
    href_filter(soup)

    # The content is inside the DetailedOutput span
    detailed_output = soup.find(id="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    assert detailed_output, "Could not find DetailedOutput span"

    # Find h1.title - this contains the PFS icon and the name link follows it
    h1_title = detailed_output.find('h1', class_='title')
    assert h1_title, "Could not find h1.title in DetailedOutput"

    # Extract PFS status from h1 (img alt="PFS Standard/Limited/Restricted")
    pfs = "Standard"
    pfs_img = h1_title.find('img', alt=lambda s: s and s.startswith('PFS '))
    if pfs_img:
        pfs_alt = pfs_img.get('alt', '')
        match = re.match(r'PFS\s+(\w+)', pfs_alt, re.IGNORECASE)
        if match:
            pfs = match.group(1).capitalize()

    # Extract the equipment name from the link that follows DetailedOutput
    name_link = extract_name_link(detailed_output, equipment_type)
    name = get_text(name_link).strip()

    # Extract item level if present (for siege weapons, vehicles, etc.)
    # Item level appears as: <span style="margin-left:auto; margin-right:0">Item 13</span>
    level = 0
    content_container = detailed_output.parent
    level_span = content_container.find('span', style=lambda s: s and 'margin-left:auto' in s)
    if level_span:
        level_text = get_text(level_span).strip()
        match = re.match(r'Item\s+(\d+)', level_text, re.IGNORECASE)
        if match:
            level = int(match.group(1))

    # Remove the h1.title now that we've extracted PFS from it
    h1_title.decompose()

    # Remove Legacy Content h3 if present (converted to edition field, not a section)
    legacy_h3 = detailed_output.find('h3', class_='title', string=lambda s: s and 'Legacy Content' in s)
    if legacy_h3:
        legacy_h3.decompose()

    # Collect content from DetailedOutput onwards
    # Extract the CONTENTS of DetailedOutput (not the span itself to avoid wrapper tags)
    content_parts = [str(child) for child in detailed_output.children]

    # Also collect sibling elements after DetailedOutput
    for sibling in detailed_output.next_siblings:
        if hasattr(sibling, 'name'):  # Only tags, not text nodes
            content_parts.append(str(sibling))
            if sibling.name == 'div' and sibling.get('class') == ['clear']:
                break

    combined_content = ''.join(content_parts)

    result = {
        'name': name,
        'text': combined_content,
        'level': level,  # Always include level (0 if not specified)
        'pfs': pfs       # Always include PFS (Standard if not specified)
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
        'armor': 'Armor',
        'weapon': 'Weapons',
        'shield': 'Shields',
        'siege_weapon': 'SiegeWeapons',
        'vehicle': 'Vehicles',
    }

    # All valid game-obj values (for fallback if equipment_type not provided)
    all_gameobjs = list(type_to_gameobj.values())

    # Get the expected game-obj for this equipment type
    expected_gameobj = type_to_gameobj.get(equipment_type)

    def is_name_link(elem):
        """Check if element is a valid name link."""
        if not hasattr(elem, 'name') or elem.name != 'a':
            return False
        if elem.has_attr('noredirect'):
            return False
        game_obj = elem.get('game-obj', '')
        if expected_gameobj and game_obj == expected_gameobj:
            return True
        return game_obj in all_gameobjs

    # Try Structure A first: name link is a sibling of DetailedOutput
    for sibling in detailed_output.next_siblings:
        if is_name_link(sibling):
            return sibling

    # Try Structure B: name link is inside h1.title within DetailedOutput
    h1_title = detailed_output.find('h1', class_='title')
    if h1_title:
        link = h1_title.find('a', attrs={'game-obj': expected_gameobj or True})
        if link and is_name_link(link):
            return link

    assert False, f"Could not find equipment name link (type={equipment_type})"


def restructure_equipment_pass(details, equipment_type):
    """
    Build the standard structure from parsed HTML details.
    """
    name = details['name']
    text = details['text']
    level = details['level']  # Level field (0 if not specified)
    pfs = details['pfs']      # PFS field (Standard, Limited, or Restricted)

    # Build stat block section
    sb = {
        'type': 'stat_block',
        'subtype': equipment_type,
        'text': text,
        'sections': [],
        'level': level  # Always include level
    }

    # Build top-level structure
    top = {
        'name': name,
        'type': equipment_type,
        'sources': [],
        'sections': [sb],
        'pfs': pfs  # Always include PFS
    }

    return top


def find_stat_block(struct):
    """Find the stat_block section in the structure."""
    for s in struct.get("sections", []):
        if s.get("type") == "stat_block":
            return s
    assert False, f"No stat_block found in equipment structure. Type: {struct.get('type', 'unknown')}"


def section_pass(struct, config, debug=False):
    """Extract equipment-specific fields from the stat block HTML.

    Returns the number of links that were removed from redundant sections.
    """
    equipment_type = struct['type']

    # Dispatch to equipment-specific handlers
    if equipment_type == 'weapon':
        return _weapon_section_pass(struct, config, debug=debug)
    elif equipment_type == 'siege_weapon':
        return _siege_weapon_section_pass(struct, config, debug=debug)
    elif equipment_type == 'vehicle':
        return _vehicle_section_pass(struct, config, debug=debug)
    else:
        # Generic equipment handling (armor, shields, etc.)
        return _generic_section_pass(struct, config, debug=debug)


def _generic_section_pass(struct, config, debug=False):
    """Generic section pass for non-weapon equipment (armor, etc.).

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb['text']  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, 'html.parser')

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    stats = {}
    # Fail fast if Group stat requires group_subtype but it's missing from config
    group_subtype = config['group_subtype'] if 'Group' in config['recognized_stats'] else None
    _extract_stats_to_dict(bs, stats, config['recognized_stats'], struct['type'], group_subtype)

    # Separate shared vs nested fields
    shared_fields = config.get('shared_fields', [])
    nested_fields = config.get('nested_fields', [])
    equipment_type = struct['type']  # 'weapon' or 'armor'

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

    links_removed = _remove_redundant_sections(bs, struct.get('name', ''), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)

    return links_removed


def _weapon_section_pass(struct, config, debug=False):
    """Weapon-specific section pass that handles melee/ranged modes.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb['text']  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, 'html.parser')

    # Check if this is a combination weapon (has <h2> mode headers for Melee/Ranged)
    h2_tags = bs.find_all('h2', class_='title')
    mode_headers = [h2 for h2 in h2_tags if get_text(h2).strip().lower() in ['melee', 'ranged']]
    is_combination = len(mode_headers) > 0

    if is_combination:
        _extract_combination_weapon(bs, sb, struct, config)
    else:
        _extract_single_mode_weapon(bs, sb, struct, config)

    links_removed = _remove_redundant_sections(bs, struct.get('name', ''), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)

    return links_removed


def _siege_weapon_section_pass(struct, config, debug=False):
    """Siege weapon-specific section pass that handles stats and action sections.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb['text']  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, 'html.parser')

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    # For siege weapons, stats span multiple <hr> sections, so we need custom extraction
    stats = {}
    _extract_siege_weapon_stats(bs, stats, config['recognized_stats'], struct['type'])

    # Separate shared vs nested fields
    shared_fields = config.get('shared_fields', [])
    nested_fields = config.get('nested_fields', [])

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
        sb['siege_weapon'] = sw_obj

    # Extract action sections (Aim, Load, Launch, Ram, etc.) as abilities
    abilities, trait_links_converted = _extract_abilities(bs, struct['type'], config['recognized_stats'])
    if abilities:
        sb['abilities'] = abilities

    links_removed = _remove_redundant_sections(bs, struct.get('name', ''), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    return links_removed + trait_links_converted


def _vehicle_section_pass(struct, config, debug=False):
    """Vehicle-specific section pass that handles stats similar to siege weapons.

    Returns the number of links removed from redundant sections.
    """
    sb = find_stat_block(struct)
    text = sb['text']  # Fail if missing
    if not text:
        raise ValueError(f"Stat block text is empty for {struct.get('name', 'unknown')}")

    bs = BeautifulSoup(text, 'html.parser')

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    # Vehicles have stats similar to siege weapons
    stats = {}
    _extract_vehicle_stats(bs, stats, config['recognized_stats'], struct['type'])

    # Separate shared vs nested fields
    shared_fields = config.get('shared_fields', [])
    nested_fields = config.get('nested_fields', [])

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
        sb['vehicle'] = vehicle_obj

    # Extract action sections as abilities (if any)
    abilities, trait_links_converted = _extract_abilities(bs, struct['type'], config['recognized_stats'])
    if abilities:
        sb['abilities'] = abilities

    links_removed = _remove_redundant_sections(bs, struct.get('name', ''), debug=debug)
    _extract_alternate_link(bs, struct)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)  # Use generic description extraction
    _cleanup_stat_block(sb)

    # Add trait links converted to traits to links_removed (they were counted initially but became traits)
    return links_removed + trait_links_converted


def _extract_vehicle_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract vehicle stats which span across multiple <hr> tags.

    Vehicles have stats similar to siege weapons but different fields.
    """
    # Find all bold tags that are stats (not action names)
    # Vehicles typically don't have action names like siege weapons
    action_names = ['Effect', 'Requirements']  # Keep minimal list just in case

    for bold_tag in bs.find_all('b'):
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
        preserve_html = (label in ['Immunities', 'Resistances', 'Weaknesses', 'Piloting Check'])
        value = _extract_stat_value(bold_tag, preserve_html=preserve_html)
        if value:
            stats_dict[field_name] = value


def _extract_siege_weapon_stats(bs, stats_dict, recognized_stats, equipment_type):
    """Extract siege weapon stats which span across multiple <hr> tags.

    Siege weapons have stats before actions, which appear after description.
    """
    # Find all bold tags that are stats (not action names)
    action_names = ['Aim', 'Load', 'Launch', 'Ram', 'Effect', 'Requirements']

    for bold_tag in bs.find_all('b'):
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
        preserve_html = (label == 'Immunities')
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
    if text.startswith('('):
        close_paren = text.find(')')
        if close_paren > 0:
            traits_text = text[1:close_paren].strip()
            remaining = text[close_paren + 1:].strip()

            # Split by comma and clean up each trait name
            trait_names = [t.strip() for t in traits_text.split(',') if t.strip()]
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
    dc_pattern = r'(DC\s+\d+\s+\w+)'
    match = re.search(dc_pattern, text)
    if not match:
        # No save found - just return the text as-is
        return None, None, None, text

    # Find where the DC ends
    dc_end = match.end()
    before_dc = text[:dc_end].strip()
    after_dc = text[dc_end:].strip()

    # Split after_dc by ; or . to separate remaining text
    remaining_text = ''
    if after_dc.startswith(';'):
        remaining_text = after_dc[1:].strip()
        after_dc = ''
    elif after_dc.startswith('.'):
        remaining_text = after_dc[1:].strip()
        after_dc = ''
    elif ';' in after_dc:
        parts = after_dc.split(';', 1)
        # The save might have extra text before the semicolon
        if parts[0].strip():
            # This means there's extra text attached to the save - HTML needs fixing
            assert False, f"Save DC has extra text before semicolon - HTML needs fixing. Text: '{text}'"
        remaining_text = parts[1].strip()
    elif '.' in after_dc:
        # Period is used as separator (HTML error, but we'll handle it)
        parts = after_dc.split('.', 1)
        if parts[0].strip():
            # Extra text before period
            assert False, f"Save DC has extra text before period - HTML needs fixing. Text: '{text}'"
        remaining_text = parts[1].strip()
    else:
        # No separator found - save is at the end
        if after_dc.strip():
            # There's extra text but no separator - needs fixing
            assert False, f"Save DC has extra text but no separator - HTML needs fixing. Text: '{text}'"

    # Parse the DC text
    dc_text = match.group(1)

    # Get everything before the DC
    text_before_save = text[:match.start()].strip()

    # Remove trailing comma if present
    if text_before_save.endswith(','):
        text_before_save = text_before_save[:-1].strip()

    # Split by commas to get damage and target
    parts = [p.strip() for p in text_before_save.split(',')]

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
        assert False, f"Launch should have damage, target (or just target) before save. Got {len(parts)} parts. Text: '{text}'"

    # Parse the DC using the universal function
    save_dc = universal_handle_save_dc(dc_text)

    return damage, target, save_dc, remaining_text


def _extract_abilities(bs, equipment_type='siege_weapon', recognized_stats=None):
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
    from universal.universal import get_links

    # Main abilities that are top-level abilities (siege weapons)
    # For siege weapons, these are the known action names
    main_abilities = ['Aim', 'Load', 'Launch', 'Ram', 'Effect', 'Requirements']
    # Result fields that are nested within abilities
    result_fields = ['Success', 'Failure', 'Critical Success', 'Critical Failure']

    # Track which bold tags we've already processed (to skip result fields)
    processed_bolds = set()
    abilities = []

    # Track how many trait links were converted to traits (for link accounting)
    trait_links_converted_count = 0

    # For vehicles, get the list of recognized stat labels to exclude
    stat_labels = set(recognized_stats.keys()) if recognized_stats and equipment_type == 'vehicle' else set()

    for bold_tag in bs.find_all('b'):
        if bold_tag in processed_bolds:
            continue

        ability_name = get_text(bold_tag).strip()

        # Check if this is a known stat label (skip it, already extracted)
        if ability_name in stat_labels:
            continue

        # Only extract main abilities (or bold tags with action icons)
        is_main_ability = ability_name in main_abilities
        has_action_icon = False
        next_sib = bold_tag.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and next_sib.strip() == '':
            next_sib = next_sib.next_sibling
        if isinstance(next_sib, Tag) and next_sib.name == 'span' and 'action' in next_sib.get('class', []):
            has_action_icon = True

        # For vehicles, also extract bold tags that look like abilities:
        # - Not a result field (Success, Failure, etc.)
        # - Has substantial text after it (indicating description, not just a value)
        is_vehicle_ability = False
        if equipment_type == 'vehicle' and ability_name not in result_fields:
            # Check if there's substantial content after this bold tag
            # Vehicle abilities typically have 20+ characters of descriptive text
            content_preview = []
            preview_sib = bold_tag.next_sibling
            char_count = 0
            while preview_sib and char_count < 30:
                if isinstance(preview_sib, NavigableString):
                    content_preview.append(str(preview_sib))
                    char_count += len(str(preview_sib).strip())
                elif isinstance(preview_sib, Tag):
                    if preview_sib.name in ('b', 'hr', 'h2'):
                        break
                    content_preview.append(preview_sib.get_text())
                    char_count += len(preview_sib.get_text().strip())
                preview_sib = preview_sib.next_sibling if hasattr(preview_sib, 'next_sibling') else None

            # If we found substantial text (>15 chars), treat as ability
            preview_text = ''.join(content_preview).strip()
            if len(preview_text) > 15:
                is_vehicle_ability = True

        if not (is_main_ability or has_action_icon or is_vehicle_ability):
            continue

        # Found a main ability
        ability = {
            'type': 'stat_block_section',
            'subtype': 'ability',
            'name': ability_name,
            'ability_type': 'offensive'  # Equipment abilities are offensive actions
        }

        # Extract main ability text (up to first <br>)
        # Note: Don't stop at <b> tags - those are addons like Requirements, Effect, etc.
        # But do mark addon <b> tags as processed so they don't create separate abilities
        addon_names = ['Frequency', 'Trigger', 'Effect', 'Duration', 'Requirement',
                       'Requirements', 'Prerequisite', 'Critical Success', 'Success',
                       'Failure', 'Critical Failure', 'Range', 'Cost']

        content_parts = []
        current = bold_tag.next_sibling

        while current:
            if isinstance(current, Tag) and current.name in ('hr', 'h2'):
                break
            if isinstance(current, Tag) and current.name == 'br':
                break

            # If this is a <b> tag with an addon name, mark it as processed
            if isinstance(current, Tag) and current.name == 'b':
                tag_text = get_text(current).strip()
                if tag_text in addon_names:
                    processed_bolds.add(current)

            if isinstance(current, NavigableString) or isinstance(current, Tag):
                content_parts.append(str(current))

            current = current.next_sibling

        if content_parts:
            combined_html = ''.join(content_parts).strip()
            action_soup = BeautifulSoup(combined_html, 'html.parser')

            # Use extract_action_type to parse action cost icon
            description, action_type = extract_action_type(str(action_soup))

            # Extract links from description and unwrap <a> tags
            if description:
                desc_soup = BeautifulSoup(description, 'html.parser')

                # First, extract all links before processing addons
                links = get_links(desc_soup, unwrap=True)

                # Extract addons (Requirements, Effect, etc.) after unwrapping links
                # Addons are marked by <b> tags within the ability text
                # Similar to creature ability addon handling
                addon_names = ['Frequency', 'Trigger', 'Effect', 'Duration', 'Requirement',
                               'Requirements', 'Prerequisite', 'Critical Success', 'Success',
                               'Failure', 'Critical Failure', 'Range', 'Cost']

                addons = {}
                current_addon = None
                nodes_to_remove = []  # Track addon nodes to remove after extraction

                # Walk through all children to find and extract addons
                for child in list(desc_soup.children):
                    if isinstance(child, Tag) and child.name == 'b':
                        addon_name = get_text(child).strip()
                        if addon_name in addon_names:
                            current_addon = addon_name
                            if current_addon == "Requirements":
                                current_addon = "Requirement"
                            nodes_to_remove.append(child)
                            # Mark this <b> tag for removal
                    elif current_addon:
                        # This is addon content - extract it
                        addon_text = str(child)
                        if addon_text.strip().endswith(";"):
                            addon_text = addon_text.rstrip()[:-1]
                        addons.setdefault(current_addon.lower().replace(" ", "_"), []).append(addon_text)
                        nodes_to_remove.append(child)
                        # Continue collecting until we hit another <b> or end

                # Remove addon nodes from the soup
                for node in nodes_to_remove:
                    if hasattr(node, 'extract'):
                        node.extract()

                # Separate trait links from other links
                # Trait links have game-obj="Traits"
                # Rules links in parentheses (like "range 250 feet") should also be kept separate
                trait_links = [link for link in links if link.get('game-obj') == 'Traits']
                rules_links_in_parens = []
                other_links = []

                for link in links:
                    if link.get('game-obj') == 'Traits':
                        continue  # Already in trait_links
                    elif link.get('game-obj') == 'Rules':
                        # Rules links might be in parentheses (e.g., "range 250 feet")
                        rules_links_in_parens.append(link)
                    else:
                        other_links.append(link)

                ability_text = _normalize_whitespace(str(desc_soup))

                # Only convert trait links to traits if they're in opening parentheses
                # Trait links in body text should remain as regular links
                traits_to_convert = []  # Trait links that are actually in parentheses
                trait_links_in_body = []  # Trait links that are NOT in parentheses
                unlinked_trait_names = []  # Unlinked trait names in parentheses
                non_trait_links_in_parens = []  # Non-Traits links consumed as traits

                # Check if ability text starts with parentheses (trait list)
                # Traits can be: Traits links, non-Traits links (MonsterAbilities, Domains), or unlinked text
                if ability_text.startswith('('):
                    close_paren = ability_text.find(')')
                    assert close_paren > 0, f"Unclosed parenthesis in ability text: {ability_text[:100]}"

                    # Extract the parentheses content
                    parens_content = ability_text[1:close_paren].strip()
                    remaining = ability_text[close_paren + 1:].strip()

                    # Check which trait links are actually in the parentheses
                    for trait_link in trait_links:
                        trait_name = trait_link['name']
                        # Check if this trait name appears in the parentheses (case-insensitive)
                        if trait_name.lower() in parens_content.lower():
                            traits_to_convert.append(trait_link)
                            # Remove the trait name from parentheses content
                            parens_content = parens_content.replace(trait_name, '')
                            parens_content = parens_content.replace(trait_name.lower(), '')
                        else:
                            # This trait link is NOT in the parentheses, it's in body text
                            trait_links_in_body.append(trait_link)

                    # Remove Rules links from parentheses content
                    for rules_link in rules_links_in_parens:
                        link_text = rules_link['name']
                        parens_content = parens_content.replace(link_text, '')
                        parens_content = parens_content.replace(link_text.lower(), '')

                    # Handle non-Traits links in parentheses (e.g., links to MonsterAbilities, Domains)
                    # These are still trait names, just linked to explanatory pages instead of Traits.aspx
                    for link in links:
                        game_obj = link.get('game-obj', '')
                        if game_obj and game_obj not in ('Traits', 'Rules'):
                            link_name = link['name']
                            if link_name.lower() in parens_content.lower():
                                # This is a trait linked to a non-Traits page (e.g., aura -> MonsterAbilities)
                                traits_to_convert.append(link)
                                non_trait_links_in_parens.append(link)
                                parens_content = parens_content.replace(link_name, '')
                                parens_content = parens_content.replace(link_name.lower(), '')

                    # Remove the non-Traits links from other_links (they were consumed as traits)
                    for consumed_link in non_trait_links_in_parens:
                        if consumed_link in other_links:
                            other_links.remove(consumed_link)

                    # Clean up commas and whitespace
                    parens_content = parens_content.replace(',', '').strip()

                    # Handle any remaining text in parentheses as unlinked trait names
                    # This handles cases where trait names aren't linked at all
                    if parens_content:
                        # Split by whitespace to get individual words that might be traits
                        potential_traits = parens_content.split()
                        for pt in potential_traits:
                            pt = pt.strip()
                            if pt and not pt.isdigit():  # Skip numbers
                                unlinked_trait_names.append(pt)

                    # Remove the now-empty parentheses
                    ability_text = remaining

                    # Add Rules links back to other_links (they're not in parentheses anymore)
                    other_links.extend(rules_links_in_parens)
                else:
                    # No opening parentheses - all trait links are in body text
                    trait_links_in_body = trait_links
                    # Rules links are also in body text (not in opening parens)
                    other_links.extend(rules_links_in_parens)

                # Add trait links from body text to other_links (they should be regular links)
                other_links.extend(trait_links_in_body)

                # Build trait objects from:
                # 1. Trait links that were in parentheses (traits_to_convert)
                # 2. Unlinked trait names in parentheses (unlinked_trait_names)
                from universal.universal import build_objects
                trait_names = [tl['name'] for tl in traits_to_convert] + unlinked_trait_names
                traits = build_objects('stat_block_section', 'trait', trait_names)

                # Track how many links were converted to traits (for link accounting)
                # This includes both Traits links and non-Traits links in parentheses
                trait_links_converted_count += len(traits_to_convert)
                # Also count non-Traits links that were consumed as traits (they're in traits_to_convert)
                # but we need to NOT double-count since they're already in traits_to_convert
                # Note: non_trait_links_in_parens items were added to traits_to_convert, so no need to add again

                if traits:
                    ability['traits'] = traits

                # Set the extracted addons as separate fields
                for k, v in addons.items():
                    if k == "range":
                        assert len(v) == 1, f"Malformed range: {v}"
                        ability["range"] = universal_handle_range(v[0])
                    else:
                        ability[k] = clear_garbage(v)

                # Set main text
                ability['text'] = ability_text

                if other_links:
                    ability['links'] = other_links

            if action_type:
                ability['action_type'] = action_type

        # For siege weapon Launch actions, parse structured damage, target, and save
        if equipment_type == 'siege_weapon' and ability_name == 'Launch' and 'text' in ability:
            try:
                damage, target, save_dc, remaining_text = _parse_siege_weapon_launch(ability['text'])
                if damage:
                    ability['damage'] = damage
                if target:
                    ability['target'] = target
                if save_dc:
                    ability['saving_throw'] = save_dc
                # Replace text with just the remaining text (after the semicolon/period)
                if remaining_text:
                    ability['text'] = remaining_text
                else:
                    # No remaining text - remove the text field
                    del ability['text']
            except AssertionError as e:
                # Re-raise assertion errors with context about which siege weapon
                raise AssertionError(f"Launch action parsing failed: {e}")

        # Now look for result fields (Success, Failure, etc.) after the <br>
        # Continue from where we stopped
        while current:
            # Skip <br> tags and whitespace
            if isinstance(current, Tag) and current.name == 'br':
                current = current.next_sibling
                continue
            if isinstance(current, NavigableString) and current.strip() == '':
                current = current.next_sibling
                continue

            # Check if this is a result field
            if isinstance(current, Tag) and current.name == 'b':
                field_name = get_text(current).strip()
                if field_name in result_fields:
                    processed_bolds.add(current)

                    # Extract text for this result field (up to next <br>)
                    field_parts = []
                    field_current = current.next_sibling

                    while field_current:
                        if isinstance(field_current, Tag) and field_current.name in ('b', 'hr', 'h2', 'br'):
                            break
                        if isinstance(field_current, NavigableString) or isinstance(field_current, Tag):
                            field_parts.append(str(field_current))
                        field_current = field_current.next_sibling

                    if field_parts:
                        field_html = ''.join(field_parts).strip()
                        field_soup = BeautifulSoup(field_html, 'html.parser')
                        field_links = get_links(field_soup, unwrap=True)

                        # Map field name to schema field name (lowercase with underscores)
                        schema_field_name = field_name.lower().replace(' ', '_')
                        ability[schema_field_name] = _normalize_whitespace(str(field_soup))

                        # Add links if any (merge with existing links)
                        if field_links:
                            if 'links' not in ability:
                                ability['links'] = []
                            ability['links'].extend(field_links)

                    current = field_current
                    continue
                else:
                    # Hit a different bold tag (next main ability), stop
                    break

            # Hit something else, stop
            break

        # Only add if we have actual content
        if 'text' in ability or 'action_type' in ability:
            abilities.append(ability)

    # Return abilities and the count of trait links that were converted
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
    shared_fields = config.get('shared_fields', [])
    weapon_fields = config.get('weapon_fields', [])
    mode_fields = config.get('mode_fields', [])

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
    weapon_type = stats.get('weapon_type', 'Melee')
    mode_key = 'ranged' if weapon_type == 'Ranged' else 'melee'

    # Put mode-specific fields into the appropriate mode object
    mode_obj = {
        'type': 'stat_block_section',
        'subtype': mode_key
    }
    for field in mode_fields:
        if field in stats:
            mode_obj[field] = stats[field]

    weapon_obj[mode_key] = mode_obj

    sb['weapon'] = weapon_obj


def _extract_combination_weapon(bs, sb, struct, config):
    """Extract stats for a combination weapon with multiple modes."""
    # Extract traits and source that apply to whole weapon
    # Traits before first <h2> are shared
    first_h2 = bs.find('h2', class_='title')
    if first_h2:
        # Extract shared traits (before first h2)
        # Use trait_class_matcher to match trait, traituncommon, traitrare, etc.
        shared_traits = []
        for span in bs.find_all('span', class_=_trait_class_matcher):
            if first_h2.sourceline and span.sourceline and span.sourceline < first_h2.sourceline:
                # This trait is before the h2, so it's shared
                shared_traits.append(span)

        # Process shared traits
        if shared_traits:
            traits = []
            for span in shared_traits:
                children = [c for c in span.children if hasattr(c, 'name') and c.name is not None]
                if len(children) == 1 and children[0].name == 'a':
                    link = children[0]
                    name = get_text(link).replace(" Trait", "").strip()
                    trait_class = ''.join(span.get('class', ['trait']))
                    if trait_class != 'trait':
                        trait_class = trait_class.replace('trait', '')
                    _, link_obj = extract_link(link)
                    trait = {
                        'name': name,
                        'classes': [trait_class if trait_class != 'trait' else 'trait'],
                        'type': 'stat_block_section',
                        'subtype': 'trait',
                        'link': link_obj
                    }
                    traits.append(trait)
            if traits:
                sb['traits'] = traits

    _extract_source(bs, struct)

    # Extract fields before first h2 (both shared and weapon-level)
    shared_fields = config.get('shared_fields', [])
    weapon_fields = config.get('weapon_fields', [])
    all_weapon_stats = {}
    hr = bs.find('hr')
    for tag in bs.find_all('b'):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        if first_h2 and tag.sourceline and first_h2.sourceline and tag.sourceline >= first_h2.sourceline:
            break

        label = tag.get_text().strip()
        if not label:
            continue

        # FAIL FAST: Assert all labels are recognized
        assert label in config['recognized_stats'], \
            f"Unknown weapon stat label in combination weapon: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

        field_name = config['recognized_stats'][label]
        if field_name is None:  # Intentionally skipped (like Source)
            continue

        # Extract both shared and weapon-level fields before h2
        if field_name in shared_fields or field_name in weapon_fields:
            if label == 'Group':
                value = _extract_group_value(tag, config['group_subtype'])
            elif label == 'Favored Weapon':
                # Extract with HTML preserved to capture deity links
                value = _extract_stat_value(tag, preserve_html=True)
            elif label == 'Ammunition':
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
    h2_tags = bs.find_all('h2', class_='title')
    for h2 in h2_tags:
        mode_name = get_text(h2).strip().lower()
        if mode_name not in ['melee', 'ranged']:
            continue

        # Extract stats for this mode (between this h2 and next h2 or hr)
        mode_stats = {}
        mode_traits = []

        # Find mode-specific traits (after this h2, before next h2 or hr)
        # Use trait_class_matcher to match trait, traituncommon, traitrare, etc.
        next_h2 = h2.find_next_sibling('h2', class_='title')
        for span in bs.find_all('span', class_=_trait_class_matcher):
            if not span.sourceline or not h2.sourceline:
                continue
            if span.sourceline <= h2.sourceline:
                continue
            if next_h2 and next_h2.sourceline and span.sourceline >= next_h2.sourceline:
                continue

            children = [c for c in span.children if hasattr(c, 'name') and c.name is not None]
            if len(children) == 1 and children[0].name == 'a':
                link = children[0]
                name = get_text(link).replace(" Trait", "").strip()
                trait_class = ''.join(span.get('class', ['trait']))
                if trait_class != 'trait':
                    trait_class = trait_class.replace('trait', '')
                _, link_obj = extract_link(link)
                trait = {
                    'name': name,
                    'classes': [trait_class if trait_class != 'trait' else 'trait'],
                    'type': 'stat_block_section',
                    'subtype': 'trait',
                    'link': link_obj
                }
                mode_traits.append(trait)

        # Find mode-specific stats (bold tags after this h2, before next h2)
        for tag in bs.find_all('b'):
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
            assert label in config['recognized_stats'], \
                f"Unknown weapon stat label in {mode_name} mode: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

            field_name = config['recognized_stats'][label]
            if field_name is None:  # Intentionally skipped (like Source, Favored Weapon)
                continue

            # FAIL FAST: Mode sections should only contain mode-specific fields
            assert field_name in config.get('mode_fields', []), \
                f"Field '{field_name}' from label '{label}' found in {mode_name} mode but not in mode_fields config. " \
                f"Mode sections should only contain: {config.get('mode_fields', [])}"

            if label == 'Group':
                value = _extract_group_value(tag, config['group_subtype'])
            elif label == 'Ammunition':
                # Extract with HTML preserved to capture ammunition links
                value = _extract_stat_value(tag, preserve_html=True)
            else:
                value = _extract_stat_value(tag)
            if value:
                mode_stats[field_name] = value

        # Build mode object
        mode_obj = {
            'type': 'stat_block_section',
            'subtype': mode_name
        }
        if mode_traits:
            mode_obj['traits'] = mode_traits
        mode_obj.update(mode_stats)

        # Set weapon_type based on mode section (combination weapons don't have Type field in HTML)
        mode_obj['weapon_type'] = 'Melee' if mode_name == 'melee' else 'Ranged'

        weapon_obj[mode_name] = mode_obj

    # Add weapon object to stat block
    sb['weapon'] = weapon_obj


def _extract_weapon_stats(bs, stats, config):
    """Extract weapon stats into a flat dictionary."""
    hr = bs.find('hr')
    bold_tags = []
    for tag in bs.find_all('b'):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        bold_tags.append(tag)

    for bold_tag in bold_tags:
        label = bold_tag.get_text().strip()
        if not label:
            continue

        assert label in config['recognized_stats'], \
            f"Unknown weapon stat label: '{label}'. Add it to EQUIPMENT_TYPES['weapon']['recognized_stats']."

        field_name = config['recognized_stats'][label]
        if field_name is None:
            continue

        if label == 'Group':
            value = _extract_group_value(bold_tag, config['group_subtype'])
        elif label == 'Favored Weapon':
            # Extract with HTML preserved to capture deity links
            value = _extract_stat_value(bold_tag, preserve_html=True)
        elif label == 'Ammunition':
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
    trait_spans = bs.find_all('span', class_=_trait_class_matcher)
    for span in trait_spans:
        # Filter out whitespace text nodes to get actual element children
        children = [c for c in span.children if hasattr(c, 'name') and c.name is not None]
        if len(children) == 1 and children[0].name == 'a':
            link = children[0]
            name = get_text(link).replace(" Trait", "").strip()
            trait_class = ''.join(span.get('class', ['trait']))
            if trait_class != 'trait':
                trait_class = trait_class.replace('trait', '')

            # Build trait object matching trait_parse output
            # Note: Don't include the link here - it will be added by trait_db_pass from the database
            trait = {
                'name': name,
                'classes': [trait_class if trait_class != 'trait' else 'trait'],
                'type': 'stat_block_section',
                'subtype': 'trait'
            }
            traits.append(trait)

            # Remove the trait span from the HTML since we've extracted it
            span.decompose()

    # Remove any remaining formatting spans (letter-spacing, etc.) that are empty or whitespace-only
    for span in bs.find_all('span', style=True):
        # Remove spans that are empty or contain only whitespace
        if not span.get_text(strip=True):
            span.decompose()

    if traits:
        sb['traits'] = traits


def _extract_source(bs, struct):
    """Extract source information from <b>Source</b> tag.

    Handles multiple sources separated by commas.
    Example: Source NPC Core pg. 18, Gods & Magic pg. 120 <sup>2.0</sup>
    """
    source_tag = bs.find('b', string=lambda s: s and s.strip() == 'Source')
    if not source_tag:
        return

    sources = []

    # Find all source links after the Source tag until we hit the next <b> tag or <br>
    current = source_tag.next_sibling
    current_source_link = None

    while current:
        # Stop at next <b> tag (next field) or <br> tag
        if isinstance(current, Tag) and current.name in ('b', 'br', 'hr'):
            break

        # Check for source link (italic text inside <a> tag)
        if isinstance(current, Tag) and current.name == 'a':
            # Only extract links that are actually sources (have <i> tag for source name)
            # Skip links like "There is a more recent version" which are not sources
            italic = current.find('i')
            if not italic:
                current = current.next_sibling
                continue

            # This is a source link
            current_source_link = current
            source = extract_source(current_source_link)
            if 'name' in source:
                source['name'] = source['name'].strip()

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
                    if next_sib.name == 'sup':
                        errata_link = next_sib.find('a')
                        if errata_link:
                            errata = extract_link(errata_link)
                            source['errata'] = errata[1]  # [1] is the link object
                    # Stop after first tag
                    break

                next_sib = next_sib.next_sibling

            sources.append(source)

        current = current.next_sibling

    if sources:
        # Replace any existing sources (don't append - avoids duplicates)
        struct['sources'] = sources

        # Remove the Source tag and all its content from the HTML to avoid double-counting links
        # Remove everything from the <b>Source</b> tag until the next <b> or <br> tag
        current = source_tag
        while current:
            next_node = current.next_sibling
            if isinstance(current, Tag):
                if current.name in ('b', 'br', 'hr') and current != source_tag:
                    break
                current.decompose()
            elif isinstance(current, NavigableString):
                current.extract()
            current = next_node


def _extract_stats_to_dict(bs, stats_dict, recognized_stats, equipment_type, group_subtype):
    """Extract stats into a dictionary - works for any equipment type based on configuration."""
    # Find all bold tags before the hr (stats section)
    hr = bs.find('hr')
    bold_tags = []
    for tag in bs.find_all('b'):
        if hr and tag.sourceline and hr.sourceline and tag.sourceline > hr.sourceline:
            break
        bold_tags.append(tag)

    # Extract and validate all labels
    for bold_tag in bold_tags:
        label = bold_tag.get_text().strip()

        # Skip empty labels
        if not label:
            continue

        # Fail fast if we encounter an unknown label
        assert label in recognized_stats, \
            f"Unknown {equipment_type} stat label: '{label}'. Add it to EQUIPMENT_TYPES['{equipment_type}']['recognized_stats']."

        # Skip labels we handle elsewhere (like Source)
        field_name = recognized_stats[label]
        if field_name is None:
            continue

        # Extract the value (special handling for Group which has a link)
        if label == 'Group':
            value = _extract_group_value(bold_tag, group_subtype)
        else:
            value = _extract_stat_value(bold_tag)
        if value:
            stats_dict[field_name] = value


def _extract_stats(bs, sb, recognized_stats, equipment_type, group_subtype):
    """Generic stat extraction - works for any equipment type based on configuration.

    Backward compatibility wrapper that extracts stats and adds them directly to stat_block.
    """
    equipment_stats = {}
    _extract_stats_to_dict(bs, equipment_stats, recognized_stats, equipment_type, group_subtype)
    sb.update(equipment_stats)


# Maintain backward compatibility - _extract_armor_stats is now an alias
def _extract_armor_stats(bs, sb):
    """Backward compatibility wrapper for _extract_stats."""
    _extract_stats(bs, sb, EQUIPMENT_TYPES['armor']['recognized_stats'], 'armor', 'armor_group')


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
        if isinstance(current, Tag) and current.name in ('b', 'hr', 'br'):
            break

        if isinstance(current, NavigableString):
            text = str(current)
            if text.strip():
                value_parts.append(text)
        elif isinstance(current, Tag):
            # Skip <sup> tags (footnote markers)
            if current.name != 'sup':
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
    value_text = ''.join(value_parts).strip()

    # Split by semicolon while respecting parentheses (modifiers)
    # e.g., "swim 20 feet (alchemical; underwater only); Collision 2d8" splits to
    # ["swim 20 feet (alchemical; underwater only)", "Collision 2d8"]
    # We only want the first value for this stat
    from universal.utils import split_maintain_parens
    parts = split_maintain_parens(value_text, ';')
    if parts:
        value_text = parts[0].strip()

    # Return em dash as-is (let field-specific normalizers handle it)
    # E.g., bulk with "—" should become {value: null, text: "—"}

    # Empty string indicates malformed HTML (stat label with no value)
    if value_text == '':
        raise ValueError(f"Empty value for stat label")

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
        if text_value == '—' or text_value == '':
            return None
        # Shouldn't have text-only group (should be in a tag with link)
        return None

    # Group should be a tag containing a link
    if isinstance(next_sibling, Tag):
        link_tag = next_sibling.find('a')
        if link_tag:
            name = get_text(link_tag).strip()
            _, link_obj = extract_link(link_tag)
            return {
                'type': 'stat_block_section',
                'subtype': group_subtype,
                'name': name,
                'link': link_obj
            }

    # Fallback: if no link found, return None (shouldn't have group without link)
    return None


def _remove_redundant_sections(bs, exclude_name='', debug=False):
    """Remove redundant h2 sections (Traits, Armor Specialization Effects, etc.).

    Returns the number of links that were removed with these sections.
    Only counts links that weren't already excluded from the initial count.
    """
    links_removed = 0

    # Remove Traits h2 section (we already extracted traits)
    removed = _remove_h2_section(bs, lambda s: s and s.strip() == 'Traits', debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Traits section removed {removed} links\n")
    links_removed += removed

    # Remove Armor Specialization Effects h2 section (comes from group, redundant)
    removed = _remove_h2_section(bs, lambda s: s and 'Armor Specialization Effects' in s, debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Armor Specialization Effects section removed {removed} links\n")
    links_removed += removed

    # Remove Specific Magic Armor/Weapon/Shield sections (lists of related items)
    removed = _remove_h2_section(bs, lambda s: s and 'Specific Magic Armor' in s, debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Specific Magic Armor section removed {removed} links\n")
    links_removed += removed

    removed = _remove_h2_section(bs, lambda s: s and 'Specific Magic Weapon' in s, debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Specific Magic Weapon section removed {removed} links\n")
    links_removed += removed

    removed = _remove_h2_section(bs, lambda s: s and 'Specific Magic Shield' in s, debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Specific Magic Shield section removed {removed} links\n")
    links_removed += removed

    # Remove Critical Specialization Effects section (weapon groups, redundant)
    removed = _remove_h2_section(bs, lambda s: s and 'Critical Specialization Effects' in s, debug=debug, exclude_name=exclude_name)
    if debug and removed > 0:
        import sys
        sys.stderr.write(f"DEBUG:   Critical Specialization Effects section removed {removed} links\n")
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
    if parent and parent.name == 'span':
        parent_classes = parent.get('class', [])
        if isinstance(parent_classes, str):
            if parent_classes.startswith('trait'):
                return True
        else:  # list of classes
            if any(cls.startswith('trait') for cls in parent_classes):
                return True

    # Exclude version navigation links ("more recent version")
    link_text = get_text(link).strip().lower()
    if 'more recent version' in link_text or 'newer version' in link_text:
        return True

    # Exclude equipment group links (WeaponGroups, ArmorGroups in stat lines)
    game_obj = link.get('game-obj', '')
    if game_obj in ['WeaponGroups', 'ArmorGroups']:
        # Check if it's in a stat line context (parent is <u> with preceding <b> sibling)
        if parent and parent.name == 'u':
            prev_sibling = parent.previous_sibling
            # Skip whitespace text nodes
            while prev_sibling:
                if isinstance(prev_sibling, NavigableString):
                    if prev_sibling.strip():
                        break
                    prev_sibling = prev_sibling.previous_sibling
                else:
                    break
            if prev_sibling and isinstance(prev_sibling, Tag) and prev_sibling.name == 'b':
                label_text = get_text(prev_sibling).strip()
                if label_text in ['Group', 'Armor Group']:
                    return True

    # Exclude alternate edition links (in siderbarlook divs)
    parent = link.parent
    while parent:
        if isinstance(parent, Tag) and parent.name == 'div':
            div_classes = parent.get('class', [])
            if 'siderbarlook' in div_classes:
                div_text = get_text(parent).strip()
                if 'Legacy version' in div_text or 'Remastered version' in div_text:
                    return True
                return False
        parent = parent.parent

    return False


def _remove_h2_section(bs, match_func, debug=False, exclude_name=None):
    """Remove an h2 section and all its content until the next h2.

    Returns the number of links (with game-obj attribute) that were removed.
    Only counts links that would have been included in the initial count
    (i.e., not trait links, not group links, not self-references, etc.)
    """
    h2 = bs.find('h2', string=match_func)
    if not h2:
        return 0

    # Collect all elements in this section (for counting links before removal)
    section_elements = [h2]
    current = h2.next_sibling
    while current:
        if isinstance(current, Tag) and current.name == 'h2':
            break
        section_elements.append(current)
        current = current.next_sibling

    # Count links in the section before removing
    section_html = ''.join(str(e) for e in section_elements)
    section_soup = BeautifulSoup(section_html, 'html.parser')
    all_links = section_soup.find_all('a', attrs={'game-obj': True})

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
        sys.stderr.write(f"DEBUG:     Section '{section_name}' found {len(all_links)} total links, {links_count} to count (after exclusions):\n")
        for link in all_links:
            excluded = link not in links_to_count
            status = " (EXCLUDED)" if excluded else ""
            sys.stderr.write(f"DEBUG:       - {get_text(link)} ({link.get('game-obj')}){status}\n")

    # Now remove the section
    current = h2.next_sibling
    while current:
        next_sibling = current.next_sibling
        if isinstance(current, Tag):
            if current.name == 'h2':
                break
            current.decompose()
        elif isinstance(current, NavigableString):
            current.extract()
        current = next_sibling
    # Remove the h2 itself
    h2.decompose()

    return links_count


def _extract_legacy_content_section(bs, struct):
    """Extract Legacy Content h3 section if present.

    NOTE: Legacy content is now represented via the 'edition' field on the item,
    so we no longer need to create a separate section for it.
    """
    # Legacy content is indicated by the 'edition' field, not a section
    pass


def _extract_description(bs, struct):
    """Extract description text and links, adding them to the top-level structure.

    For equipment with multiple <hr> separators (siege weapons, vehicles), splits by <hr>
    and finds the section with the fewest bold stat labels - this is the description.
    The description is typically pure text with few/no bold tags, while stat sections
    have many bold stat labels.

    For equipment without <hr> separators (armor, weapons), extracts all remaining
    text in the stat block as description.

    Text is added to struct['text'], and links (if any) to struct['links'].
    Only creates sections if there are actual headings (h2, h3) after the description.
    """
    import sys
    from universal.utils import split_on_tag
    from universal.universal import get_links

    # Split by <hr> tags to get sections
    text = str(bs)
    sections = split_on_tag(text, 'hr')

    if len(sections) < 2:
        # No <hr> tags - extract all remaining text as description (armor, weapons)
        # For combination weapons, stop at first <h2 class="title"> (mode section header)
        first_h2 = bs.find('h2', class_='title')
        if first_h2:
            # This is a combination weapon - extract only content before first <h2>
            # Create a new soup with only content before the h2
            content_before_h2 = []
            for elem in bs.children:
                if elem == first_h2:
                    break
                content_before_h2.append(str(elem))
            last_section = ''.join(content_before_h2)
            desc_soup = BeautifulSoup(last_section, 'html.parser')
        else:
            # Single-mode weapon - use all content
            desc_soup = bs
            last_section = text
    else:
        # Multiple <hr> tags - find the section that looks like a description
        # For vehicles: description is in section[1] (after source/price, before stats)
        # For siege weapons: description is in the LAST section (mixed with actions)
        # For other equipment: use the section with fewest bold stat labels

        equipment_type = struct.get('type', '')

        if equipment_type == 'vehicle' and len(sections) > 1:
            # Vehicles MAY have description in section[1] (between source/price and stats)
            # But some vehicles have no description - section[1] is stats
            # Check if section[1] starts with a stat label
            section1 = sections[1].strip()
            section1_soup = BeautifulSoup(section1, 'html.parser')
            first_bold = section1_soup.find('b')
            vehicle_stat_labels = {'Space', 'Crew', 'Passengers', 'Piloting Check'}

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

        desc_soup = BeautifulSoup(desc_section, 'html.parser')

        # For combination weapons, stop at first <h2 class="title"> (mode section header)
        first_h2 = desc_soup.find('h2', class_='title')
        if first_h2:
            # This is a combination weapon - extract only content before first <h2>
            content_before_h2 = []
            for elem in desc_soup.children:
                if elem == first_h2:
                    break
                content_before_h2.append(str(elem))
            last_section = ''.join(content_before_h2)
            desc_soup = BeautifulSoup(last_section, 'html.parser')

    # Find the first action - either a bold tag with action name, or an action icon span
    # We need to find the EARLIEST action in document order, not just the first one we encounter
    known_actions = ['Aim', 'Load', 'Launch', 'Ram', 'Effect', 'Requirements',
                     'Success', 'Failure', 'Critical Success', 'Critical Failure']
    first_action_element = None
    candidates = []

    # Collect all potential action elements
    # 1. Bold tags with action names
    for bold in desc_soup.find_all('b'):
        bold_text = get_text(bold).strip()
        is_known_action = bold_text in known_actions

        # Check if followed by action icon
        next_sib = bold.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and next_sib.strip() == '':
            next_sib = next_sib.next_sibling
        has_action_icon = (isinstance(next_sib, Tag) and next_sib.name == 'span' and
                          'action' in next_sib.get('class', []))

        if is_known_action or has_action_icon:
            candidates.append(bold)

    # 2. Action icon spans (for actions without bold tags)
    action_spans = desc_soup.find_all('span', class_='action')
    candidates.extend(action_spans)

    # Find the earliest candidate in document order
    if candidates:
        # Get the position of each candidate by walking through all descendants
        def get_element_index(elem):
            for idx, descendant in enumerate(desc_soup.descendants):
                if descendant == elem:
                    return idx
            return float('inf')

        first_action_element = min(candidates, key=get_element_index)

    # Extract only the content before the first action
    if first_action_element:
        # Remove everything from the action element onwards
        current = first_action_element

        # If it's an action icon span, also remove preceding action name and <br> tag
        if isinstance(first_action_element, Tag) and first_action_element.name == 'span':
            # Action icons follow action names. Remove span, preceding action name text, and br.
            prev = first_action_element.previous_sibling
            # Remove preceding br tag
            if isinstance(prev, Tag) and prev.name == 'br':
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

    # Extract links and unwrap <a> tags
    links = get_links(desc_soup, unwrap=True)

    # Keep ALL links including trait links
    # Trait links in description text should be regular link objects, not filtered out
    # (Only trait links in <span class="trait*"> tags or ability parentheses are converted to traits)
    non_trait_links = links

    # Get the cleaned text
    desc_text = _normalize_whitespace(str(desc_soup))

    # Add text and links to top-level structure (not as a section)
    if desc_text:
        struct['text'] = desc_text

    # Store extracted links if any exist (excluding trait links)
    if non_trait_links:
        struct['links'] = non_trait_links


def _extract_alternate_link(bs, struct):
    """Extract alternate edition link (legacy/remastered) from siderbarlook div.

    The alternate link appears in a <div class="siderbarlook"> containing text like:
    - "There is a Legacy version <a>here</a>."
    - "There is a Remastered version <a>here</a>."

    This should be extracted as an alternate_link at the top level of the struct.
    """
    from universal.universal import extract_link

    # Find the siderbarlook div
    sidebar_div = bs.find('div', class_='siderbarlook')
    if not sidebar_div:
        return

    # Check if it contains alternate version text
    div_text = get_text(sidebar_div)
    if 'Legacy version' not in div_text and 'Remastered version' not in div_text:
        return

    # Extract the link
    link_tag = sidebar_div.find('a', attrs={'game-obj': True})
    if not link_tag:
        return

    # Build the alternate_link object
    _, link = extract_link(link_tag)

    # Remove fields not needed for alternate_link
    if 'alt' in link:
        del link['alt']
    if 'name' in link:
        del link['name']

    # Set the type and alternate_type
    link['type'] = 'alternate_link'
    if 'Legacy version' in div_text:
        link['alternate_type'] = 'legacy'
    else:
        link['alternate_type'] = 'remastered'

    # Add to struct
    struct['alternate_link'] = link

    # Remove the div so it's not counted again
    sidebar_div.decompose()


def _cleanup_stat_block(sb):
    """Remove text field from stat_block (no longer needed after extraction)."""
    if 'text' in sb:
        del sb['text']


def normalize_numeric_fields_pass(struct, config):
    """Convert numeric string fields to integers and structure complex fields.
    Calls equipment-specific normalizer function from config."""
    # Access stat_block after it's been moved to top level by restructure_pass
    sb = struct.get('stat_block')
    if not sb:
        return

    # Call equipment-specific normalizer function
    normalizer = config.get('normalize_fields')
    if normalizer:
        normalizer(sb)


def _normalize_int_field(sb, field_name):
    """Convert a string field to integer, stripping + prefix."""
    if field_name not in sb:
        return

    value = sb[field_name]
    if not value:
        return

    # Em dash means no value - remove the field
    if value.strip() == '—':
        del sb[field_name]
        return

    # Strip leading + sign
    if value.startswith('+'):
        value = value[1:]

    # Parse to int
    sb[field_name] = int(value.strip())


def _normalize_strength(sb):
    """Convert strength string to structured stat requirement object with legacy and remastered values."""
    if 'strength' not in sb:
        return

    value_str = sb['strength']
    if not value_str:
        return

    # Em dash means no strength requirement - remove the field
    if value_str.strip() == '—':
        del sb['strength']
        return

    # Check if this is a modifier (starts with +) or a stat value
    is_modifier = value_str.startswith('+')

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

    # Create stat requirement object
    sb['strength'] = {
        'type': 'stat_block_section',
        'subtype': 'stat_requirement',
        'stat': 'strength',
        'legacy_value': stat_value,
        'remastered_value': modifier
    }


def _normalize_ac_bonus(sb, bonus_type='armor'):
    """Convert ac_bonus string to structured bonus object.

    Args:
        sb: stat block dict
        bonus_type: 'armor' for armor, 'shield' for shields
    """
    if 'ac_bonus' not in sb:
        return

    value_str = sb['ac_bonus']
    if not value_str:
        return

    # Em dash means no AC bonus - remove the field
    if value_str.strip() == '—':
        del sb['ac_bonus']
        return

    # Handle conditional bonuses like "+2 (+4)" - take only the base value
    if '(' in value_str:
        value_str = value_str.split('(')[0].strip()

    # Strip leading + sign
    if value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    value = int(value_str.strip())
    # Create bonus object with appropriate bonus_type
    sb['ac_bonus'] = {
        'type': 'bonus',
        'subtype': 'ac',
        'bonus_type': bonus_type,
        'bonus_value': value
    }


def _normalize_dex_cap(sb):
    """Convert dex_cap string to structured bonus object."""
    if 'dex_cap' not in sb:
        return

    value_str = sb['dex_cap']
    if not value_str:
        return

    # Em dash means no dex cap - remove the field
    if value_str.strip() == '—':
        del sb['dex_cap']
        return

    # Strip leading + sign
    if value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    cap = int(value_str.strip())
    # Create bonus object for dexterity cap (limits dexterity bonus to AC)
    sb['dex_cap'] = {
        'type': 'bonus',
        'subtype': 'ac',
        'bonus_type': 'dexterity',
        'bonus_cap': cap
    }


def _normalize_check_penalty(sb):
    """Convert check_penalty string to bonus object."""
    if 'check_penalty' not in sb:
        return

    value_str = sb['check_penalty']
    if not value_str:
        return

    # Em dash means no check penalty - remove the field
    if value_str.strip() == '—':
        del sb['check_penalty']
        return

    # Strip leading - or + sign
    if value_str.startswith('-') or value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    value = int(value_str.strip())
    # Check penalties are always negative
    if value > 0:
        value = -value
    # Create bonus object for check penalty (skill bonus type)
    sb['check_penalty'] = {
        'type': 'bonus',
        'subtype': 'skill',
        'bonus_type': 'armor',
        'bonus_value': value
    }


def _normalize_speed_penalty(sb, bonus_type='armor'):
    """Convert speed_penalty string to bonus object.

    Args:
        sb: stat block dict
        bonus_type: 'armor' for armor, 'shield' for shields
    """
    if 'speed_penalty' not in sb:
        return

    value_str = sb['speed_penalty']
    if not value_str:
        return

    # Em dash means no speed penalty - remove the field
    if value_str.strip() == '—':
        del sb['speed_penalty']
        return

    # Extract unit and value
    unit = None
    if value_str.endswith(' ft.'):
        unit = 'feet'
        value_str = value_str[:-4]

    # Parse to int
    value = int(value_str.strip())
    # Speed penalties are always negative
    if value > 0:
        value = -value
    # Create bonus object for speed penalty with appropriate bonus_type
    speed_obj = {
        'type': 'bonus',
        'subtype': 'speed',
        'bonus_type': bonus_type,
        'bonus_value': value
    }
    if unit:
        speed_obj['unit'] = unit
    sb['speed_penalty'] = speed_obj


def _normalize_bulk(sb):
    """Convert bulk string to structured bulk object."""
    if 'bulk' not in sb:
        return

    value_str = sb['bulk']
    if not value_str:
        return

    value_str = value_str.strip()

    # Create bulk object with both string and integer values
    if value_str == '—':
        # Em dash means no bulk value
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': None,
            'text': '—'
        }
    elif value_str == 'L':
        # "L" (light) gets null for integer value
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': None,
            'text': 'L'
        }
    else:
        # Parse as integer
        int_value = int(value_str)
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': int_value,
            'text': value_str
        }


# Equipment-specific field normalizers
def normalize_armor_fields(sb):
    """Normalize armor-specific fields."""
    # Normalize shared field at top level
    _normalize_bulk(sb)

    # Normalize armor-specific fields within armor object
    if 'armor' in sb:
        armor_obj = sb['armor']
        # Strength requirement object (with legacy and remastered values)
        _normalize_strength(armor_obj)

        # Bonus objects (for stacking rules)
        _normalize_ac_bonus(armor_obj)
        _normalize_dex_cap(armor_obj)
        _normalize_check_penalty(armor_obj)
        _normalize_speed_penalty(armor_obj)

def _normalize_favored_weapon(weapon_obj):
    """Normalize favored_weapon field from HTML string to structured object with text and links.

    Input: "<u><a href='Deities.aspx?ID=72' game-obj='Deities' aonid='72'>Angazhan</a></u>, <u><a ...>Irori</a></u>, ..."
    Output: {"text": "Angazhan, Green Faith, Irori, ...", "links": [{...}, {...}, ...]}
    """
    if 'favored_weapon' not in weapon_obj:
        return

    html_str = weapon_obj['favored_weapon']
    # Empty field cleanup is handled by a separate pass - don't delete here

    # Parse HTML to extract text and links
    soup = BeautifulSoup(html_str, 'html.parser')
    links = get_links(soup, unwrap=True)  # Extract links and unwrap <a> tags

    # Get cleaned text
    text = _normalize_whitespace(str(soup))

    # Build structured object
    favored_weapon = {
        'type': 'stat_block_section',
        'subtype': 'favored_weapon',
        'text': text
    }
    if links:
        favored_weapon['links'] = links

    weapon_obj['favored_weapon'] = favored_weapon


def _normalize_ammunition(obj):
    """Normalize ammunition field from HTML string to structured object with text and links.

    Works for both weapon-level ammunition and mode-level ammunition.
    Extracts modifiers from parentheses (e.g., "(10 rounds)") and strips HTML tags.

    Input: "<u><a href='Weapons.aspx?ID=211' game-obj='Weapons' aonid='211'>Firearm Ammunition (10 rounds)</a></u>"
    Output: {"type": "stat_block_section", "subtype": "ammunition", "text": "Firearm Ammunition",
             "modifier": "10 rounds", "links": [{...}]}
    """
    if 'ammunition' not in obj:
        return

    html_str = obj['ammunition']
    # Empty field cleanup is handled by a separate pass - don't delete here

    # Parse HTML to extract text and links
    soup = BeautifulSoup(html_str, 'html.parser')
    links = get_links(soup, unwrap=True)  # Extract links and unwrap <a> tags

    # Get text without HTML tags (use get_text() to strip all tags)
    text = soup.get_text()
    text = _normalize_whitespace(text)

    # Extract modifier from parentheses at the end
    # Pattern: "Something (modifier)" -> text="Something", modifiers=[{"name": "modifier"}]
    modifier_name = None
    import re
    match = re.match(r'^(.+?)\s*\(([^)]+)\)$', text)
    if match:
        text = match.group(1).strip()
        modifier_name = match.group(2).strip()

        # Also update link names to remove modifier
        for link in links:
            if 'name' in link and modifier_name:
                link_text = link['name']
                # Remove modifier from link name if present
                link_match = re.match(r'^(.+?)\s*\([^)]+\)$', link_text)
                if link_match:
                    link['name'] = link_match.group(1).strip()

    # Build structured object
    ammunition = {
        'type': 'stat_block_section',
        'subtype': 'ammunition',
        'text': text
    }
    if modifier_name:
        # Modifiers are always an array of modifier objects
        from universal.universal import build_object, link_modifiers
        ammunition['modifiers'] = link_modifiers([
            build_object('stat_block_section', 'modifier', modifier_name)
        ])
    if links:
        ammunition['links'] = links

    obj['ammunition'] = ammunition


# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES['armor']['normalize_fields'] = normalize_armor_fields


def normalize_weapon_fields(sb):
    """Normalize weapon-specific fields in melee/ranged mode objects."""

    # Normalize shared fields at top level
    _normalize_bulk(sb)

    # Normalize weapon-specific fields within weapon object
    if 'weapon' in sb:
        weapon_obj = sb['weapon']
        _normalize_hands(weapon_obj)
        _normalize_favored_weapon(weapon_obj)
        _normalize_ammunition(weapon_obj)  # Ammunition can be at weapon level

        # Normalize mode-specific fields within each mode object
        if 'melee' in weapon_obj:
            _normalize_weapon_mode(weapon_obj['melee'])
        if 'ranged' in weapon_obj:
            _normalize_weapon_mode(weapon_obj['ranged'])

# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES['weapon']['normalize_fields'] = normalize_weapon_fields


def normalize_shield_fields(sb):
    """Normalize shield-specific fields."""
    # Normalize shared field at top level
    _normalize_bulk(sb)

    # Normalize shield-specific fields within shield object
    if 'shield' in sb:
        shield_obj = sb['shield']
        # Bonus objects (for stacking rules) - shields use bonus_type 'shield'
        _normalize_ac_bonus(shield_obj, bonus_type='shield')
        _normalize_speed_penalty(shield_obj, bonus_type='shield')
        # Build hitpoints object from hp_bt, hardness, immunities fields
        _normalize_item_hitpoints(shield_obj)

# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES['shield']['normalize_fields'] = normalize_shield_fields


def normalize_siege_weapon_fields(sb):
    """Normalize siege weapon-specific fields."""
    # Normalize shared field at top level (price only for siege weapons)
    # Note: siege weapons don't have bulk

    # Normalize siege weapon-specific fields within siege_weapon object
    if 'siege_weapon' in sb:
        sw_obj = sb['siege_weapon']
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
EQUIPMENT_TYPES['siege_weapon']['normalize_fields'] = normalize_siege_weapon_fields


def normalize_vehicle_fields(sb):
    """Normalize vehicle-specific fields."""
    # Normalize shared field at top level (price only for vehicles)
    # Note: vehicles don't have bulk

    # Normalize vehicle-specific fields within vehicle object
    if 'vehicle' in sb:
        vehicle_obj = sb['vehicle']
        # Normalize defensive stats (AC, Fort) - vehicles don't have Ref
        # Must come before hitpoints
        for field in ['ac', 'fort']:
            if field in vehicle_obj:
                _normalize_int_field(vehicle_obj, field)
        # Normalize speed field if present
        _normalize_speed(vehicle_obj)
        # Normalize piloting_check field (extract links from HTML)
        if 'piloting_check' in vehicle_obj:
            _normalize_text_with_links(vehicle_obj, 'piloting_check')
        # Parse weaknesses HTML into protection objects
        if 'weaknesses' in vehicle_obj:
            weaknesses = _parse_immunities(vehicle_obj['weaknesses'], subtype='weakness')
            if weaknesses:
                vehicle_obj['weaknesses'] = weaknesses
            else:
                del vehicle_obj['weaknesses']
        # Parse resistances HTML into protection objects
        if 'resistances' in vehicle_obj:
            resistances = _parse_immunities(vehicle_obj['resistances'], subtype='resistance')
            if resistances:
                vehicle_obj['resistances'] = resistances
            else:
                del vehicle_obj['resistances']
        # Build hitpoints object from hp_bt, hardness, immunities fields
        # This must come last since it deletes the source fields
        _normalize_vehicle_hitpoints(vehicle_obj)

# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES['vehicle']['normalize_fields'] = normalize_vehicle_fields


def _normalize_text_with_links(sb, field_name):
    """Convert HTML text field with links to structured object with extracted links.

    Args:
        sb: stat block dict containing the field
        field_name: name of the field to normalize
    """
    from universal.universal import get_links
    from universal.utils import clear_tags

    if field_name not in sb:
        return

    html_text = sb[field_name]
    if not html_text:
        return

    # Parse HTML and extract links (unwrap=True removes <a> tags)
    bs = BeautifulSoup(html_text, 'html.parser')
    links = get_links(bs, unwrap=True)

    # Get the text with links unwrapped
    text = clear_tags(str(bs), ["i"])

    # Create a structured object with text and links
    text_obj = {
        'type': 'stat_block_section',
        'subtype': field_name,
        'text': text.strip()
    }

    if links:
        text_obj['links'] = links

    sb[field_name] = text_obj


def _normalize_vehicle_hitpoints(sb):
    """Build hitpoints object from hp_bt, hardness, and immunities fields.

    Note: weaknesses field stays separate at vehicle level (not in hitpoints).
    """
    if 'hp_bt' not in sb and 'hardness' not in sb and 'immunities' not in sb:
        return

    # Build hitpoints object
    hitpoints = {
        'type': 'stat_block_section',
        'subtype': 'hitpoints'
    }

    # Parse HP (BT) string like "6 (3)", "20 (10)", or "40 (BT 20)" if present
    if 'hp_bt' in sb:
        value_str = sb['hp_bt']
        if value_str:
            # Match both "6 (3)" and "40 (BT 20)" formats
            match = re.match(r'(\d+)\s*\((?:BT\s+)?(\d+)\)', value_str.strip())
            if not match:
                raise ValueError(f"Could not parse hp_bt format: '{value_str}'")

            hitpoints['hp'] = int(match.group(1))
            hitpoints['break_threshold'] = int(match.group(2))
        del sb['hp_bt']

    # Add hardness as integer if present
    if 'hardness' in sb:
        hardness_str = str(sb['hardness']).strip().rstrip(',')  # Clean up trailing commas
        hitpoints['hardness'] = int(hardness_str)
        del sb['hardness']

    # Parse immunities string into protection objects if present
    if 'immunities' in sb:
        immunities = _parse_immunities(sb['immunities'])
        if immunities:
            hitpoints['immunities'] = immunities
        del sb['immunities']

    # Replace the individual fields with the hitpoints object
    sb['hp_bt'] = hitpoints


def _normalize_item_hitpoints(sb):
    """Build hitpoints object from hp_bt, hardness, and immunities fields.

    Creates a stat_block_section hitpoints object matching creature structure.
    Used by both shields and siege weapons.
    """
    if 'hp_bt' not in sb and 'hardness' not in sb and 'immunities' not in sb:
        return

    # Build hitpoints object
    hitpoints = {
        'type': 'stat_block_section',
        'subtype': 'hitpoints'
    }

    # Parse HP (BT) string like "6 (3)", "20 (10)", or "40 (BT 20)" if present
    if 'hp_bt' in sb:
        value_str = sb['hp_bt']
        if value_str:
            # Match both "6 (3)" and "40 (BT 20)" formats
            match = re.match(r'(\d+)\s*\((?:BT\s+)?(\d+)\)', value_str.strip())
            if not match:
                raise ValueError(f"Could not parse hp_bt format: '{value_str}'")

            hitpoints['hp'] = int(match.group(1))
            hitpoints['break_threshold'] = int(match.group(2))
        del sb['hp_bt']

    # Add hardness to hitpoints object if present
    if 'hardness' in sb:
        hitpoints['hardness'] = int(sb['hardness'])
        del sb['hardness']

    # Parse immunities string into protection objects if present
    if 'immunities' in sb:
        immunities = _parse_immunities(sb['immunities'])
        if immunities:
            hitpoints['immunities'] = immunities
        del sb['immunities']

    # Only add hitpoints object if we have at least hp
    if 'hp' in hitpoints:
        sb['hitpoints'] = hitpoints


def _parse_immunities(html_text, subtype='immunity'):
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
    bs = BeautifulSoup(html_text, 'html.parser')
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
    for link_tag in bs.find_all('a'):
        # Skip links without game-obj attribute - they're not counted in link accounting
        if not link_tag.has_attr('game-obj'):
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
            'type': 'stat_block_section',
            'subtype': subtype,  # 'immunity' or 'weakness'
            'name': part  # Clean text without newlines
        }

        # Extract modifiers from () using creatures.py function
        immunity = parse_section_modifiers(immunity, 'name')

        # Extract numeric value from name
        # Unlike creatures.py, we need to handle cases where the value is in the middle
        # e.g., "fire 5 until broken" (without parentheses around "until broken")
        name_text = immunity['name']
        # Try to match: "<name> <number> <optional rest>"
        # First try creatures.py pattern (number at end): "fire 10"
        m = re.match(r'^(.+?)\s+(\d+)$', name_text)
        if m:
            immunity['name'] = m.group(1).strip()
            immunity['value'] = int(m.group(2))
        else:
            # Try pattern with number in middle: "fire 5 until broken"
            m = re.match(r'^(.+?)\s+(\d+)\s+(.+)$', name_text)
            if m:
                immunity['name'] = m.group(1).strip()
                immunity['value'] = int(m.group(2))
                # The rest ("until broken") should be a modifier, but it's not in parentheses
                # Add it as a modifier anyway for consistency
                rest_text = m.group(3).strip()
                from universal.universal import build_object
                modifier = build_object('stat_block_section', 'modifier', rest_text)
                # Try to match a link for this modifier text
                rest_text_lower = rest_text.lower()
                for link_text, link_obj in links_in_html:
                    link_text_lower = link_text.lower()
                    # Check if the link text matches or is contained in the modifier text
                    if link_text_lower == rest_text_lower or link_text_lower in rest_text_lower:
                        if 'links' not in modifier:
                            modifier['links'] = []
                        modifier['links'].append(link_obj)
                        break
                if 'modifiers' not in immunity:
                    immunity['modifiers'] = []
                immunity['modifiers'].append(modifier)

        # Try to match a link from the original HTML to this immunity
        # Look for a link whose text matches or is contained in the immunity name
        name_text = immunity['name'].lower()
        for link_text, link_obj in links_in_html:
            link_text_lower = link_text.lower()
            # Check if the link text matches or is contained in the immunity name
            if link_text_lower == name_text or link_text_lower in name_text:
                immunity['link'] = link_obj
                break

        # Also try to match links to modifiers (both from parentheses and from unparsed text)
        if 'modifiers' in immunity:
            for modifier in immunity['modifiers']:
                if 'links' not in modifier:  # Don't overwrite if already set
                    modifier_text = modifier['name'].lower()
                    for link_text, link_obj in links_in_html:
                        link_text_lower = link_text.lower()
                        # Check if the link text matches or is contained in the modifier text
                        if link_text_lower == modifier_text or link_text_lower in modifier_text:
                            if 'links' not in modifier:
                                modifier['links'] = []
                            modifier['links'].append(link_obj)
                            break

        immunities.append(immunity)

    return immunities


def _normalize_defensive_stats(sb):
    """Normalize AC, Fort, Ref fields to integer values."""
    for field in ['ac', 'fort', 'ref']:
        if field in sb:
            _normalize_int_field(sb, field)


def _normalize_speed(sb):
    """Normalize speed field to speeds container with movement array.

    Handles multiple speeds like creatures do:
      "fly 40 feet (magical), swim 40 feet (magical)" -> speeds with 2 movement entries
      "20 feet (pulled or pushed)" -> speeds with 1 movement entry

    Each movement entry has: movement_type, value, unit, modifiers
    """
    if 'speed' not in sb:
        return

    value_str = sb['speed']
    if not value_str:
        return

    from universal.universal import build_objects, link_modifiers
    from universal.utils import split_maintain_parens, split_comma_and_semicolon

    # Split by comma while respecting parentheses to get individual speed entries
    speed_entries = split_maintain_parens(value_str.strip(), ',')

    movement_array = []
    for entry in speed_entries:
        speed_obj = _parse_single_speed(entry.strip())
        if speed_obj:
            movement_array.append(speed_obj)

    # Create speeds container (matching creature schema)
    speeds_obj = {
        'type': 'stat_block_section',
        'subtype': 'speeds',
        'movement': movement_array
    }

    sb['speed'] = speeds_obj


def _parse_single_speed(entry):
    """Parse a single speed entry like 'fly 40 feet (magical)' into a speed object."""
    from universal.universal import build_objects, link_modifiers
    from universal.utils import split_comma_and_semicolon

    # Extract modifiers from parentheses at end
    modifier_text = None
    match = re.match(r'^(.+?)\s*\((.+)\)$', entry)
    if match:
        entry = match.group(1).strip()
        modifier_text = match.group(2).strip()

    # Check for movement type prefix (fly, swim, burrow, climb, etc.)
    movement_type = 'walk'  # Default like creatures
    movement_types = ['fly', 'swim', 'burrow', 'climb', 'land']
    for mtype in movement_types:
        if entry.lower().startswith(mtype + ' '):
            movement_type = mtype
            entry = entry[len(mtype):].strip()
            break

    # Extract unit and value
    unit = 'feet'  # Default
    if entry.endswith(' feet'):
        entry = entry[:-5]
    elif entry.endswith(' ft.'):
        entry = entry[:-4]

    # Parse to int - handle special text cases
    entry_trimmed = entry.strip()
    if entry_trimmed.isdigit():
        value = int(entry_trimmed)
        speed_obj = {
            'type': 'stat_block_section',
            'subtype': 'speed',
            'name': f"{movement_type} {value} {unit}" if movement_type != 'walk' else f"{value} {unit}",
            'movement_type': movement_type,
            'value': value
        }
    else:
        # Handle special text cases like "the speed of the slowest pulling creature"
        speed_obj = {
            'type': 'stat_block_section',
            'subtype': 'speed',
            'name': entry_trimmed,
            'movement_type': movement_type
        }

    # Add modifiers if present - split by comma or semicolon
    if modifier_text:
        modifier_parts = split_comma_and_semicolon(modifier_text)
        speed_obj['modifiers'] = link_modifiers(
            build_objects('stat_block_section', 'modifier', modifier_parts)
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
    if 'damage' not in sb:
        return

    value_str = sb['damage']
    if not value_str:
        return

    # Map single-letter damage type codes to full names (as used in creatures)
    damage_type_map = {
        'B': 'bludgeoning',
        'P': 'piercing',
        'S': 'slashing',
        'F': 'fire',
        'modular': 'modular',  # Special type for modular weapons
    }

    # Handle special cases
    value_str = value_str.strip()
    if value_str.lower() == 'varies':
        sb['damage'] = [{'type': 'stat_block_section', 'subtype': 'attack_damage', 'notes': 'varies'}]
        return
    if not value_str or value_str == 'null':
        del sb['damage']
        return

    # Parse damage components (may be multiple like "1d4 B + 1d4 F")
    damage_parts = value_str.split('+')
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
                    'type': 'stat_block_section',
                    'subtype': 'attack_damage',
                    'formula': tokens[0]
                }
                damage_array.append(damage_obj)
            continue

        formula = tokens[0]
        damage_type_code = tokens[1]

        # Map the code to full name - error if unrecognized
        if damage_type_code not in damage_type_map:
            raise ValueError(f"Unrecognized damage type code '{damage_type_code}' in damage string: {value_str}")

        damage_type = damage_type_map[damage_type_code]

        damage_obj = {
            'type': 'stat_block_section',
            'subtype': 'attack_damage',
            'formula': formula,
            'damage_type': damage_type
        }
        damage_array.append(damage_obj)

    if damage_array:
        sb['damage'] = damage_array
    # If empty, don't set it - cleanup pass will handle any existing empty/null values


def _normalize_hands(sb):
    """Normalize hands field to integer or special value like '0+', '1+', '1 or 2'."""
    if 'hands' not in sb:
        return

    value_str = sb['hands']
    if not value_str:
        return

    # Handle special cases with variable hands
    # '0+', '1+', '1 or 2', etc. - keep as string
    if '+' in value_str or ' or ' in value_str:
        sb['hands'] = value_str  # Keep as string
        return

    # Otherwise normalize to integer
    _normalize_int_field(sb, 'hands')


def _normalize_range(sb):
    """Normalize range field (e.g., '30 ft.' or '60 feet')."""
    if 'range' not in sb:
        return

    value_str = sb['range']
    if not value_str:
        return

    # Em dash means no range - remove the field
    if value_str.strip() == '—':
        del sb['range']
        return

    # Extract unit and value
    unit = None
    if value_str.endswith(' ft.'):
        unit = 'feet'
        value_str = value_str[:-4]
    elif value_str.endswith(' feet'):
        unit = 'feet'
        value_str = value_str[:-5]

    # Parse to int
    value = int(value_str.strip())
    # Create range object
    range_obj = {
        'type': 'stat_block_section',
        'subtype': 'range',
        'value': value
    }
    if unit:
        range_obj['unit'] = unit
    sb['range'] = range_obj


def _normalize_reload(sb):
    """Normalize reload field to structured object with value and unit."""
    if 'reload' not in sb:
        return

    value_str = sb['reload']
    if not value_str:
        return

    # Parse value and unit
    parts = value_str.strip().split(' ', 1)

    value = int(parts[0])
    reload_obj = {
        'type': 'stat_block_section',
        'subtype': 'reload',
        'value': value
    }

    # Add unit if specified (e.g., "minute", "rounds")
    if len(parts) > 1:
        # Normalize common units
        unit = parts[1].lower()
        if unit in ['minute', 'minutes']:
            unit = 'minute'
        elif unit in ['round', 'rounds']:
            unit = 'round'
        elif unit in ['action', 'actions']:
            unit = 'action'
        reload_obj['unit'] = unit
    else:
        # No unit specified means actions (default)
        reload_obj['unit'] = 'action'

    sb['reload'] = reload_obj


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
        assert data, "%s | %s" % (data, trait)
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

        # Try full name first (handles traits like "Ranged Trip", "Double Barrel", "Critical Fusion")
        data = fetch_trait_by_name(curs, trait["name"])

        # If not found and name has space, try splitting into name + value
        # E.g., "Entrench Melee" -> name="Entrench", value="Melee"
        if not data and " " in trait["name"]:
            _handle_value(trait)
            data = fetch_trait_by_name(curs, trait["name"])

        assert data, "Trait not found in database: %s (original: %s)" % (trait["name"], original_name)

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
    sb = struct.get('stat_block', {})

    group_table = config['group_table']
    group_subtype = config['group_subtype']
    group_sql_module = config['group_sql_module']

    # Dynamically import the SQL module and get the fetch function
    sql_module = importlib.import_module(group_sql_module)
    # Function name pattern: fetch_armor_group_by_name, fetch_weapon_group_by_name, etc.
    group_singular = group_table.rstrip('s')
    fetch_function_name = f'fetch_{group_singular}_by_name'
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
    statistics = {
        "type": "stat_block_section",
        "subtype": "statistics"
    }

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
                raise ValueError(f"Conflicting 'category' definitions for hybrid weapon/armor item: {statistics['category']} vs {armor['category']}")
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
    defense = {
        "type": "stat_block_section",
        "subtype": "defense"
    }

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
                raise ValueError("Conflicting 'speed_penalty' definitions for hybrid armor/shield item.")
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
            saves = {
                "type": "stat_block_section",
                "subtype": "saves"
            }
            for key in save_keys:
                if key in siege:
                    saves[key] = {
                        "type": "stat_block_section",
                        "subtype": "save",
                        "value": siege[key]
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
                "fort": {
                    "type": "stat_block_section",
                    "subtype": "save",
                    "value": vehicle["fort"]
                }
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
    offense = {
        "type": "stat_block_section",
        "subtype": "offense"
    }

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

    # Siege weapon offensive properties
    if "siege_weapon" in stat_block:
        siege = stat_block["siege_weapon"]
        if "ammunition" in siege:
            if "ammunition" in offense and offense["ammunition"] != siege["ammunition"]:
                raise ValueError("Conflicting 'ammunition' definitions for hybrid weapon/siege_weapon item.")
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
            assert statistics["access"] == stat_block["access"], \
                f"statistics.access mismatch: {statistics['access']} != {stat_block['access']}"

        # Check weapon fields
        if "weapon" in stat_block:
            weapon = stat_block["weapon"]
            if "category" in statistics and "category" in weapon:
                assert statistics["category"] == weapon["category"], \
                    f"statistics.category != weapon.category"
            if "hands" in statistics:
                assert statistics["hands"] == weapon["hands"], \
                    f"statistics.hands != weapon.hands"
            if "favored_weapon" in statistics:
                assert statistics["favored_weapon"] == weapon["favored_weapon"], \
                    f"statistics.favored_weapon mismatch: {statistics['favored_weapon']} != {weapon['favored_weapon']}"

        # Check armor fields
        if "armor" in stat_block:
            armor = stat_block["armor"]
            if "category" in statistics and "category" in armor:
                assert statistics["category"] == armor["category"], \
                    f"statistics.category != armor.category"
            if "strength_requirement" in statistics:
                assert statistics["strength_requirement"] == armor["strength"], \
                    f"statistics.strength_requirement != armor.strength"

    # Validate defense bucket
    if defense:
        # Check armor fields
        if "armor" in stat_block:
            armor = stat_block["armor"]
            if "ac_bonus" in defense and "ac_bonus" in armor:
                assert defense["ac_bonus"] == armor["ac_bonus"], \
                    f"defense.ac_bonus != armor.ac_bonus"
            if "dex_cap" in defense:
                assert defense["dex_cap"] == armor["dex_cap"], \
                    f"defense.dex_cap != armor.dex_cap"
            if "check_penalty" in defense:
                assert defense["check_penalty"] == armor["check_penalty"], \
                    f"defense.check_penalty != armor.check_penalty"
            if "speed_penalty" in defense and "speed_penalty" in armor:
                assert defense["speed_penalty"] == armor["speed_penalty"], \
                    f"defense.speed_penalty != armor.speed_penalty"
            if "armor_group" in defense:
                assert defense["armor_group"] == armor["armor_group"], \
                    f"defense.armor_group != armor.armor_group"

        # Check shield fields
        if "shield" in stat_block:
            shield = stat_block["shield"]
            if "ac_bonus" in defense and "ac_bonus" in shield:
                assert defense["ac_bonus"] == shield["ac_bonus"], \
                    f"defense.ac_bonus != shield.ac_bonus"
            if "speed_penalty" in defense and "speed_penalty" in shield:
                assert defense["speed_penalty"] == shield["speed_penalty"], \
                    f"defense.speed_penalty != shield.speed_penalty"
            if "hitpoints" in defense:
                assert defense["hitpoints"] == shield["hitpoints"], \
                    f"defense.hitpoints != shield.hitpoints"

        # Check siege weapon fields
        if "siege_weapon" in stat_block:
            siege = stat_block["siege_weapon"]
            if "ac" in defense:
                assert defense["ac"] == siege["ac"], \
                    f"defense.ac != siege.ac"
            if "hitpoints" in defense and "hitpoints" in siege:
                assert defense["hitpoints"] == siege["hitpoints"], \
                    f"defense.hitpoints != siege.hitpoints"
            if "speed" in defense:
                assert defense["speed"] == siege["speed"], \
                    f"defense.speed != siege.speed"
            # Validate saves (old structure has integers, new has save objects)
            if "saves" in defense:
                if "fort" in siege:
                    assert "fort" in defense["saves"], "Missing fort in defense.saves"
                    assert defense["saves"]["fort"]["value"] == siege["fort"], \
                        f"defense.saves.fort.value != siege.fort"
                if "ref" in siege:
                    assert "ref" in defense["saves"], "Missing ref in defense.saves"
                    assert defense["saves"]["ref"]["value"] == siege["ref"], \
                        f"defense.saves.ref.value != siege.ref"

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
                        assert melee_mode[key] == weapon["melee"][key], \
                            f"melee mode {key} mismatch"
                if "ranged" in weapon:
                    assert "ranged" in modes_by_subtype, "Missing ranged mode in offense.weapon_modes"
                    ranged_mode = modes_by_subtype["ranged"]
                    for key in weapon["ranged"]:
                        assert key in ranged_mode, f"Missing {key} in ranged weapon_mode"
                        assert ranged_mode[key] == weapon["ranged"][key], \
                            f"ranged mode {key} mismatch"
            if "ammunition" in offense and "ammunition" in weapon:
                assert offense["ammunition"] == weapon["ammunition"], \
                    f"offense.ammunition != weapon.ammunition"

        # Check siege weapon ammunition
        if "siege_weapon" in stat_block:
            siege = stat_block["siege_weapon"]
            if "ammunition" in offense and "ammunition" in siege:
                assert offense["ammunition"] == siege["ammunition"], \
                    f"offense.ammunition != siege.ammunition"

        # Check vehicle collision and speed
        if "vehicle" in stat_block:
            vehicle = stat_block["vehicle"]
            if "speed" in offense:
                assert offense["speed"] == vehicle["speed"], \
                    f"offense.speed != vehicle.speed"
            if "collision" in offense:
                assert offense["collision"] == vehicle["collision"], \
                    f"offense.collision != vehicle.collision"

    # Validate vehicle fields in statistics
    if statistics and "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "space" in statistics:
            assert statistics["space"] == vehicle["space"], \
                f"statistics.space != vehicle.space"
        if "crew" in statistics:
            assert statistics["crew"] == vehicle["crew"], \
                f"statistics.crew != vehicle.crew"
        if "passengers" in statistics:
            assert statistics["passengers"] == vehicle["passengers"], \
                f"statistics.passengers != vehicle.passengers"
        if "piloting_check" in statistics:
            assert statistics["piloting_check"] == vehicle["piloting_check"], \
                f"statistics.piloting_check != vehicle.piloting_check"

    # Validate vehicle fields in defense
    if defense and "vehicle" in stat_block:
        vehicle = stat_block["vehicle"]
        if "ac" in defense:
            assert defense["ac"] == vehicle["ac"], \
                f"defense.ac != vehicle.ac"
        if "hardness" in defense:
            assert defense["hardness"] == vehicle["hardness"], \
                f"defense.hardness != vehicle.hardness"
        if "hitpoints" in defense and "hp_bt" in vehicle:
            assert defense["hitpoints"] == vehicle["hp_bt"], \
                f"defense.hitpoints != vehicle.hp_bt"
        if "immunities" in defense:
            assert defense["immunities"] == vehicle["immunities"], \
                f"defense.immunities != vehicle.immunities"
        if "weaknesses" in defense:
            assert defense["weaknesses"] == vehicle["weaknesses"], \
                f"defense.weaknesses != vehicle.weaknesses"
        # Validate fort save
        if "saves" in defense and "fort" in vehicle:
            assert "fort" in defense["saves"], "Missing fort in defense.saves"
            assert defense["saves"]["fort"]["value"] == vehicle["fort"], \
                f"defense.saves.fort.value != vehicle.fort"


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

    # Add buckets to stat_block (only if they have content)
    if statistics:
        stat_block["statistics"] = statistics
    if defense:
        stat_block["defense"] = defense
    if offense:
        stat_block["offense"] = offense

    # Phase 4 cleanup: Remove deprecated old structures and moved fields
    # Note: price and bulk stay at stat_block level (not in statistics)
    # Note: abilities is moved to offense.offensive_abilities
    deprecated_keys = ("weapon", "armor", "shield", "siege_weapon", "vehicle", "access", "abilities")
    for key in deprecated_keys:
        if key in stat_block:
            del stat_block[key]
