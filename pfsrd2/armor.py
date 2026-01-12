import os
import json
import sys
import re
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
from pfsrd2.sql.armor_groups import fetch_armor_group_by_name
import pfsrd2.constants as constants
import re


def parse_armor(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Armor HTML has flat structure - parse directly from HTML
    details = parse_armor_html(filename)
    struct = restructure_armor_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)
    restructure_pass(struct, "stat_block", find_stat_block)
    normalize_numeric_fields_pass(struct)
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], '')
    # Determine edition (legacy vs remastered) before removing empty sections
    edition = edition_pass(struct['sections'])
    struct['edition'] = edition
    # Enrich traits with database data (must be after edition is set)
    trait_db_pass(struct)
    # Enrich armor groups with database data
    armor_group_pass(struct)
    remove_empty_sections_pass(struct)
    if not options.skip_schema:
        struct['schema_version'] = 1.0
        validate_against_schema(struct, "armor.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, 'armor', name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def parse_armor_html(filename):
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
    Extract the armor name link, skipping legacy/remastered note links.
    Try game-obj attribute first (after pfsrd2-web transform), fallback to href.
    """
    # Try game-obj attribute (from pfsrd2-web transform)
    all_armor_links = container.find_all('a', attrs={'game-obj': 'Armor'})
    for link in all_armor_links:
        if not link.has_attr('noredirect'):
            return link

    # Fallback: use href attribute
    all_armor_links = container.find_all('a', href=lambda x: x and 'Armor.aspx?ID=' in x)
    for link in all_armor_links:
        href = link.get('href', '')
        if 'NoRedirect' not in href:
            return link

    assert False, "Could not find armor name link"


def restructure_armor_pass(details):
    """
    Build the standard structure from parsed HTML details.
    """
    name = details['name']
    text = details['text']

    # Build stat block section
    sb = {
        'type': 'stat_block',
        'subtype': 'armor',
        'text': text,
        'sections': []
    }

    # Build top-level structure
    top = {
        'name': name,
        'type': 'armor',
        'sources': [],
        'sections': [sb]
    }

    return top


def find_stat_block(struct):
    """Find the stat_block section in the structure."""
    for s in struct["sections"]:
        if s["type"] == "stat_block":
            return s
    assert False, "No stat_block found in armor structure"


def section_pass(struct):
    """Extract armor-specific fields from the stat block HTML."""
    sb = find_stat_block(struct)
    text = sb.get('text', '')
    if not text:
        return

    bs = BeautifulSoup(text, 'html.parser')

    _extract_traits(bs, sb)
    _extract_source(bs, struct)
    _extract_armor_stats(bs, sb)
    _remove_redundant_sections(bs)
    _extract_legacy_content_section(bs, struct)
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)


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


def _extract_armor_stats(bs, sb):
    """Extract armor stats from bold labels. Fail fast on unknown labels."""
    # Map of recognized label text to field names
    RECOGNIZED_STAT_LABELS = {
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
    }

    armor_stats = {}

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
        assert label in RECOGNIZED_STAT_LABELS, \
            f"Unknown armor stat label: '{label}'. Add it to RECOGNIZED_STAT_LABELS."

        # Skip labels we handle elsewhere (like Source)
        field_name = RECOGNIZED_STAT_LABELS[label]
        if field_name is None:
            continue

        # Extract the value (special handling for Group which has a link)
        if label == 'Group':
            value = _extract_group_value(bold_tag)
        else:
            value = _extract_stat_value(bold_tag)
        if value:
            armor_stats[field_name] = value

    sb.update(armor_stats)


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


def _extract_group_value(label_tag):
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
                'subtype': 'armor_group',
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


def normalize_numeric_fields_pass(struct):
    """Convert numeric string fields to integers and structure complex fields."""
    # Access stat_block after it's been moved to top level by restructure_pass
    sb = struct.get('stat_block')
    if not sb:
        return

    # Strength requirement object (with legacy and remastered values)
    _normalize_strength(sb)

    # Bonus objects (for stacking rules)
    _normalize_ac_bonus(sb)
    _normalize_dex_cap(sb)
    _normalize_check_penalty(sb)
    _normalize_speed_penalty(sb)

    # Other structured fields
    _normalize_bulk(sb)


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
    except ValueError:
        # If it can't be parsed, leave it as-is (shouldn't happen with good data)
        pass


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
    except ValueError:
        # If it can't be parsed, leave it as-is
        pass


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
    except ValueError:
        # If it can't be parsed, leave it as-is
        pass


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
    except ValueError:
        # If it can't be parsed, leave it as-is
        pass


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
    except ValueError:
        # If it can't be parsed, leave it as-is
        pass


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
    except ValueError:
        # If it can't be parsed, leave it as-is
        pass


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
        except ValueError:
            # If it can't be parsed, keep as structured object with string
            sb['bulk'] = {
                'type': 'stat_block_section',
                'subtype': 'bulk',
                'value': None,
                'display': value_str.strip()
            }


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
            # Numeric values like "range increment 60 feet"
            name, value = m.groups()
            trait["name"] = name
            trait["value"] = value
        elif " " in trait["name"]:
            # Word values like "Entrench Melee"
            parts = trait["name"].split(" ", 1)
            # Try with first word as the base trait name
            trait["name"] = parts[0]
            trait["value"] = parts[1]

    def _check_trait(trait, parent):
        """Look up trait in database and replace with enriched version."""
        # Try to extract value from trait name first
        _handle_value(trait)

        fetch_trait_by_name(curs, trait["name"])
        data = curs.fetchone()
        assert data, "Trait not found in database: %s" % trait["name"]

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
    conn = get_db_connection(db_path)
    curs = conn.cursor()

    # Walk the structure and enrich all traits
    walk(struct, test_key_is_value("subtype", "trait"), _check_trait)


def armor_group_pass(struct):
    """Enrich armor_group objects with full data from database."""
    def _check_armor_group(armor_group, parent):
        """Look up armor group in database and replace with enriched version."""
        # Get the name from the armor group object
        name = armor_group.get("name")
        if not name:
            return

        # Query database for armor group
        fetch_armor_group_by_name(curs, name)
        data = curs.fetchone()

        if not data:
            # If not found in database, leave as-is
            return

        # Parse the full armor group JSON from database
        db_armor_group = json.loads(data["armor_group"])

        # Remove fields that shouldn't be in embedded armor groups
        if "aonid" in db_armor_group:
            del db_armor_group["aonid"]
        if "license" in db_armor_group:
            del db_armor_group["license"]
        if "schema_version" in db_armor_group:
            del db_armor_group["schema_version"]

        # Replace armor group in parent (similar to trait enrichment)
        assert isinstance(parent, dict), parent
        parent["group"] = db_armor_group

    db_path = get_db_path("pfsrd2.db")
    conn = get_db_connection(db_path)
    curs = conn.cursor()

    # Walk the structure and enrich all armor groups
    walk(struct, test_key_is_value("subtype", "armor_group"), _check_armor_group)
