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
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import trait_parse
from pfsrd2.trait import extract_span_traits
from pfsrd2.action import extract_action_type
from pfsrd2.license import license_pass, license_consolidation_pass
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name, fetch_trait_by_link
import pfsrd2.constants as constants


# Equipment Type Configuration Registry
# To add a new equipment type, just add a configuration dictionary here
# Note: 'normalize_fields' will be populated after the normalizer functions are defined
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
            'Group': 'group'
        },
        # Fields that are shared (top-level) vs armor-specific (nested in armor object)
        'shared_fields': ['access', 'price', 'bulk'],
        'nested_fields': ['category', 'ac_bonus', 'dex_cap', 'check_penalty', 'speed_penalty', 'strength', 'group'],
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
            'Group': 'group',
            'Ammunition': 'ammunition',
            'Favored Weapon': None,  # Skip - just deity info, not weapon stat
            'PFS Note': None,  # Skip - PFS-specific note, not weapon stat
        },
        # Fields at different nesting levels:
        # - shared_fields: top-level stat_block (price, bulk, access)
        # - weapon_fields: nested in weapon object (category, hands, ammunition)
        # - mode_fields: nested in melee/ranged objects (damage, weapon_type, group, range, reload)
        'shared_fields': ['access', 'price', 'bulk'],
        'weapon_fields': ['category', 'hands', 'ammunition'],
        'mode_fields': ['damage', 'weapon_type', 'group', 'range', 'reload'],
        'group_table': 'weapon_groups',
        'group_sql_module': 'pfsrd2.sql.weapon_groups',
        'group_subtype': 'weapon_group',
        'schema_file': 'equipment.schema.json',
        'output_subdir': 'weapons',
        'normalize_fields': None,  # Set after function definition
    },
}


def parse_equipment(filename, options):
    """Universal equipment parser - supports armor, weapons, and future equipment types."""
    equipment_type = options.equipment_type
    config = EQUIPMENT_TYPES[equipment_type]

    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Equipment HTML has flat structure - parse directly from HTML
    details = parse_equipment_html(filename)
    struct = restructure_equipment_pass(details, equipment_type)
    aon_pass(struct, basename)
    section_pass(struct, config)
    restructure_pass(struct, "stat_block", find_stat_block)
    normalize_numeric_fields_pass(struct, config)
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], '')
    # Determine edition (legacy vs remastered) before removing empty sections
    edition = edition_pass(struct['sections'])
    struct['edition'] = edition
    # Enrich traits with database data (must be after edition is set)
    trait_db_pass(struct)
    # Enrich equipment groups with database data
    equipment_group_pass(struct, config)
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


def parse_equipment_html(filename):
    """
    Parse armor HTML which has a flat structure (no hierarchical headings).
    Extract the name and content for further processing.
    """
    with open(filename) as fp:
        html = fp.read()

    soup = BeautifulSoup(html, 'html.parser')

    # Enrich href attributes with game-obj and aonid (same as parse_universal does)
    href_filter(soup)

    # The armor name is AFTER the DetailedOutput span as a sibling
    detailed_output = soup.find(id="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    assert detailed_output, "Could not find DetailedOutput span"

    # Get parent container to find name link
    content_container = detailed_output.parent

    # Extract the armor name from the <a> tag
    name_link = extract_name_link(content_container)
    name = get_text(name_link).strip()

    # Collect content from DetailedOutput onwards
    content_parts = [detailed_output]
    for sibling in detailed_output.next_siblings:
        if hasattr(sibling, 'name'):  # Only tags, not text nodes
            content_parts.append(sibling)
            if sibling.name == 'div' and sibling.get('class') == ['clear']:
                break

    combined_content = ''.join(str(part) for part in content_parts)

    return {
        'name': name,
        'text': combined_content
    }


def extract_name_link(container):
    """
    Extract the equipment name link, skipping legacy/remastered note links.
    Try game-obj attribute first (after pfsrd2-web transform), fallback to href.
    Works for both armor and weapons.
    """
    # Try game-obj attribute (from pfsrd2-web transform)
    # Could be 'Armor' or 'Weapons'
    for game_obj in ['Armor', 'Weapons']:
        all_links = container.find_all('a', attrs={'game-obj': game_obj})
        for link in all_links:
            if not link.has_attr('noredirect'):
                return link

    # Fallback: use href attribute
    # Could be 'Armor.aspx?ID=' or 'Weapons.aspx?ID='
    for pattern in ['Armor.aspx?ID=', 'Weapons.aspx?ID=']:
        all_links = container.find_all('a', href=lambda x: x and pattern in x)
        for link in all_links:
            href = link.get('href', '')
            if 'NoRedirect' not in href:
                return link

    assert False, "Could not find equipment name link (tried both Armor and Weapons)"


def restructure_equipment_pass(details, equipment_type):
    """
    Build the standard structure from parsed HTML details.
    """
    name = details['name']
    text = details['text']

    # Build stat block section
    sb = {
        'type': 'stat_block',
        'subtype': equipment_type,
        'text': text,
        'sections': []
    }

    # Build top-level structure
    top = {
        'name': name,
        'type': equipment_type,
        'sources': [],
        'sections': [sb]
    }

    return top


def find_stat_block(struct):
    """Find the stat_block section in the structure."""
    for s in struct.get("sections", []):
        if s.get("type") == "stat_block":
            return s
    assert False, f"No stat_block found in equipment structure. Type: {struct.get('type', 'unknown')}"


def section_pass(struct, config):
    """Extract equipment-specific fields from the stat block HTML."""
    equipment_type = struct['type']

    # Dispatch to equipment-specific handlers
    if equipment_type == 'weapon':
        _weapon_section_pass(struct, config)
    else:
        # Generic equipment handling (armor, etc.)
        _generic_section_pass(struct, config)


def _generic_section_pass(struct, config):
    """Generic section pass for non-weapon equipment (armor, etc.)."""
    sb = find_stat_block(struct)
    text = sb.get('text', '')
    if not text:
        return

    bs = BeautifulSoup(text, 'html.parser')

    _extract_traits(bs, sb)
    _extract_source(bs, struct)

    # Extract stats into a temporary dictionary
    stats = {}
    _extract_stats_to_dict(bs, stats, config['recognized_stats'], struct['type'], config['group_subtype'])

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

    _remove_redundant_sections(bs)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)


def _weapon_section_pass(struct, config):
    """Weapon-specific section pass that handles melee/ranged modes."""

    sb = find_stat_block(struct)
    text = sb.get('text', '')
    if not text:
        return

    bs = BeautifulSoup(text, 'html.parser')

    # Check if this is a combination weapon (has <h2> mode headers for Melee/Ranged)
    h2_tags = bs.find_all('h2', class_='title')
    mode_headers = [h2 for h2 in h2_tags if get_text(h2).strip().lower() in ['melee', 'ranged']]
    is_combination = len(mode_headers) > 0

    if is_combination:
        _extract_combination_weapon(bs, sb, struct, config)
    else:
        _extract_single_mode_weapon(bs, sb, struct, config)

    _remove_redundant_sections(bs)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)


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

    # Add weapon-level fields
    for field in weapon_fields:
        if field in stats:
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
        shared_traits = []
        for span in bs.find_all('span', class_='trait'):
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
        if not label or label not in config['recognized_stats']:
            continue

        field_name = config['recognized_stats'][label]
        # Extract both shared and weapon-level fields before h2
        if field_name and (field_name in shared_fields or field_name in weapon_fields):
            if label == 'Group':
                value = _extract_group_value(tag, config['group_subtype'])
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
        next_h2 = h2.find_next_sibling('h2', class_='title')
        for span in bs.find_all('span', class_='trait'):
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
            if not label or label not in config['recognized_stats']:
                continue

            field_name = config['recognized_stats'][label]
            if not field_name:
                continue

            # Only extract mode-specific fields for modes
            if field_name not in config.get('mode_fields', []):
                continue

            if label == 'Group':
                value = _extract_group_value(tag, config['group_subtype'])
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
        else:
            value = _extract_stat_value(bold_tag)
        if value:
            stats[field_name] = value


def _extract_traits(bs, sb):
    """Extract traits from <span class="trait"> tags."""
    traits = []
    trait_spans = bs.find_all('span', class_='trait')
    for span in trait_spans:
        # Filter out whitespace text nodes to get actual element children
        children = [c for c in span.children if hasattr(c, 'name') and c.name is not None]
        if len(children) == 1 and children[0].name == 'a':
            link = children[0]
            name = get_text(link).replace(" Trait", "").strip()
            trait_class = ''.join(span.get('class', ['trait']))
            if trait_class != 'trait':
                trait_class = trait_class.replace('trait', '')

            # Extract link object
            _, link_obj = extract_link(link)

            # Build trait object matching trait_parse output
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


def _extract_source(bs, struct):
    """Extract source information from <b>Source</b> tag."""
    source_tag = bs.find('b', string=lambda s: s and s.strip() == 'Source')
    if source_tag:
        source_link = source_tag.find_next_sibling('a')
        if source_link:
            source = extract_source(source_link)
            if 'name' in source:
                source['name'] = source['name'].strip()

            # Check for errata sup tag
            sup = source_link.find_next_sibling('sup')
            if sup:
                errata_link = sup.find('a')
                if errata_link:
                    errata = extract_link(errata_link)
                    source['errata'] = errata[1]  # [1] is the link object

            struct['sources'] = [source]


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


def _extract_stat_value(label_tag):
    """Extract the value after a bold label tag, handling em dashes as None."""
    next_sibling = label_tag.next_sibling

    # Skip whitespace-only text nodes
    while next_sibling and isinstance(next_sibling, NavigableString) and not next_sibling.strip():
        next_sibling = next_sibling.next_sibling

    if not next_sibling:
        return None

    # Extract text from sibling
    if isinstance(next_sibling, NavigableString):
        value_text = str(next_sibling).strip()
    else:
        # It might be a tag (like <u><a>Cloth</a></u> for Group)
        value_text = get_text(next_sibling).strip()

    # Split on semicolon if present
    if ';' in value_text:
        value_text = value_text.split(';')[0].strip()

    # Handle em dash (—) as None/absent
    if value_text == '—' or value_text == '':
        return None

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


def _remove_redundant_sections(bs):
    """Remove redundant h2 sections (Traits and Armor Specialization Effects)."""
    # Remove Traits h2 section (we already extracted traits)
    _remove_h2_section(bs, lambda s: s and s.strip() == 'Traits')

    # Remove Armor Specialization Effects h2 section (comes from group)
    _remove_h2_section(bs, lambda s: s and 'Armor Specialization Effects' in s)


def _remove_h2_section(bs, match_func):
    """Remove an h2 section and all its content until the next h2."""
    h2 = bs.find('h2', string=match_func)
    if h2:
        # Remove all siblings until the next h2 or end
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


def _extract_legacy_content_section(bs, struct):
    """Extract Legacy Content h3 section if present."""
    h3 = bs.find('h3', string=lambda s: s and 'Legacy Content' in s)
    if h3:
        legacy_section = {
            'type': 'section',
            'name': 'Legacy Content',
            'sections': []
        }
        struct['sections'].append(legacy_section)


def _extract_description(bs, struct):
    """Extract description text and create a separate section for it."""
    hr = bs.find('hr')
    if not hr:
        return

    # Get text after hr until next h2
    description_parts = []
    for sibling in hr.next_siblings:
        if isinstance(sibling, Tag) and sibling.name == 'h2':
            break
        if isinstance(sibling, Tag) and sibling.name in ['div', 'br', 'span']:
            continue
        if isinstance(sibling, NavigableString):
            text_content = str(sibling).strip()
            if text_content:
                description_parts.append(text_content)
        elif isinstance(sibling, Tag):
            text_content = get_text(sibling).strip()
            if text_content:
                description_parts.append(text_content)

    if description_parts:
        desc_section = {
            'type': 'section',
            'name': 'Description',
            'text': ' '.join(description_parts),
            'sections': []
        }
        struct['sections'].append(desc_section)


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

    # Strip leading + sign
    if value.startswith('+'):
        value = value[1:]

    # Parse to int
    try:
        sb[field_name] = int(value.strip())
    except ValueError as e:
        raise ValueError(f"Could not parse {field_name} value: '{sb[field_name]}'") from e


def _normalize_strength(sb):
    """Convert strength string to structured stat requirement object with legacy and remastered values."""
    if 'strength' not in sb:
        return

    value_str = sb['strength']
    if not value_str:
        return

    # Check if this is a modifier (starts with +) or a stat value
    is_modifier = value_str.startswith('+')

    # Strip leading + sign
    if is_modifier:
        value_str = value_str[1:]

    # Parse to int
    try:
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
    except ValueError as e:
        raise ValueError(f"Could not parse strength value: '{sb['strength']}'") from e


def _normalize_ac_bonus(sb):
    """Convert ac_bonus string to structured bonus object."""
    if 'ac_bonus' not in sb:
        return

    value_str = sb['ac_bonus']
    if not value_str:
        return

    # Strip leading + sign
    if value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    try:
        value = int(value_str.strip())
        # Create bonus object for armor's AC bonus (armor bonus type)
        sb['ac_bonus'] = {
            'type': 'bonus',
            'subtype': 'ac',
            'bonus_type': 'armor',
            'bonus_value': value
        }
    except ValueError as e:
        raise ValueError(f"Could not parse ac_bonus value: '{sb['ac_bonus']}'") from e


def _normalize_dex_cap(sb):
    """Convert dex_cap string to structured bonus object."""
    if 'dex_cap' not in sb:
        return

    value_str = sb['dex_cap']
    if not value_str:
        return

    # Strip leading + sign
    if value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    try:
        cap = int(value_str.strip())
        # Create bonus object for dexterity cap (limits dexterity bonus to AC)
        sb['dex_cap'] = {
            'type': 'bonus',
            'subtype': 'ac',
            'bonus_type': 'dexterity',
            'bonus_cap': cap
        }
    except ValueError as e:
        raise ValueError(f"Could not parse dex_cap value: '{sb['dex_cap']}'") from e


def _normalize_check_penalty(sb):
    """Convert check_penalty string to bonus object."""
    if 'check_penalty' not in sb:
        return

    value_str = sb['check_penalty']
    if not value_str:
        return

    # Strip leading - or + sign
    if value_str.startswith('-') or value_str.startswith('+'):
        value_str = value_str[1:]

    # Parse to int
    try:
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
    except ValueError as e:
        raise ValueError(f"Could not parse check_penalty value: '{sb['check_penalty']}'") from e


def _normalize_speed_penalty(sb):
    """Convert speed_penalty string to bonus object."""
    if 'speed_penalty' not in sb:
        return

    value_str = sb['speed_penalty']
    if not value_str:
        return

    # Extract unit and value
    unit = None
    if value_str.endswith(' ft.'):
        unit = 'feet'
        value_str = value_str[:-4]

    # Parse to int
    try:
        value = int(value_str.strip())
        # Speed penalties are always negative
        if value > 0:
            value = -value
        # Create bonus object for speed penalty
        speed_obj = {
            'type': 'bonus',
            'subtype': 'speed',
            'bonus_type': 'armor',
            'bonus_value': value
        }
        if unit:
            speed_obj['unit'] = unit
        sb['speed_penalty'] = speed_obj
    except ValueError as e:
        raise ValueError(f"Could not parse speed_penalty value: '{sb['speed_penalty']}'") from e


def _normalize_bulk(sb):
    """Convert bulk string to structured bulk object."""
    if 'bulk' not in sb:
        return

    value_str = sb['bulk']
    if not value_str:
        return

    # Create bulk object with both string and integer values
    # "L" (light) gets null for integer, numbers get parsed
    if value_str.strip() == 'L':
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': None,
            'display': 'L'
        }
    else:
        # Try to parse as integer
        try:
            int_value = int(value_str.strip())
            sb['bulk'] = {
                'type': 'stat_block_section',
                'subtype': 'bulk',
                'value': int_value,
                'display': value_str.strip()
            }
        except ValueError as e:
            raise ValueError(f"Could not parse bulk value: '{sb['bulk']}' (expected integer or 'L')") from e


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

        # Normalize mode-specific fields within each mode object
        if 'melee' in weapon_obj:
            _normalize_weapon_mode(weapon_obj['melee'])
        if 'ranged' in weapon_obj:
            _normalize_weapon_mode(weapon_obj['ranged'])

# Register normalizer in EQUIPMENT_TYPES config
EQUIPMENT_TYPES['weapon']['normalize_fields'] = normalize_weapon_fields


def _normalize_weapon_mode(mode_obj):
    """Normalize fields within a weapon mode object."""
    _normalize_damage(mode_obj)
    _normalize_range(mode_obj)
    _normalize_reload(mode_obj)


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
    elif 'damage' in sb:
        del sb['damage']


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

    # Extract unit and value
    unit = None
    if value_str.endswith(' ft.'):
        unit = 'feet'
        value_str = value_str[:-4]
    elif value_str.endswith(' feet'):
        unit = 'feet'
        value_str = value_str[:-5]

    # Parse to int
    try:
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
    except ValueError as e:
        raise ValueError(f"Could not parse range value: '{sb['range']}'") from e


def _normalize_reload(sb):
    """Normalize reload field to structured object with value and unit."""
    if 'reload' not in sb:
        return

    value_str = sb['reload']
    if not value_str:
        return

    # Parse value and unit
    parts = value_str.strip().split(' ', 1)

    try:
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
    except ValueError as e:
        raise ValueError(f"Could not parse reload value: '{sb['reload']}'") from e


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

        # First try to look up the full name as-is
        fetch_trait_by_name(curs, trait["name"])
        data = curs.fetchone()

        # If not found, try extracting value from trait name
        if not data:
            _handle_value(trait)
            fetch_trait_by_name(curs, trait["name"])
            data = curs.fetchone()

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
        parent["group"] = db_equipment_group

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()

        # Walk the structure and enrich all equipment groups
        walk(struct, test_key_is_value("subtype", group_subtype), _check_equipment_group)
