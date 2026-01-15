# Adding a New Content Type Parser

This guide explains how to add support for parsing a new content type (e.g., items, armor, weapons, spells).

## Overview

Adding a new parser requires creating 4 files:

1. **Parser module** - `pfsrd2/<type>.py` - Python code that parses HTML to JSON
2. **Parse script** - `bin/pf2_<type>_parse` - Entry point for parsing individual files
3. **Load script** - `bin/pf2_<type>_load` - Database loader (optional, for later)
4. **Runner script** - `bin/pf2_run_<type>s.sh` - Shell script that runs the full pipeline

## Step 1: Create the Parser Module

Create `pfsrd2/<type>.py` based on an existing simple parser like `skill.py`.

### Basic Structure

```python
import os
import json
import sys
from pprint import pprint
from bs4 import BeautifulSoup, Tag
from universal.universal import parse_universal, entity_pass
from universal.universal import extract_link, extract_links, extract_source
from universal.universal import aon_pass
from universal.utils import is_tag_named, get_text
from pfsrd2.license import license_pass, license_consolidation_pass


def parse_<type>(filename, options):
    """Main parsing function - entry point for the parser"""
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Parse HTML into initial structure
    details = parse_universal(filename, subtitle_text=True, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)

    # Restructure and process
    struct = restructure_<type>_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)

    # License information (always include)
    license_pass(struct)
    license_consolidation_pass(struct)

    # For development: just print the structure
    pprint(struct)

    # Later: uncomment these for schema validation and file output
    # if not options.skip_schema:
    #    struct['schema_version'] = 1.0
    #    validate_against_schema(struct, "<type>.schema.json")
    # if not options.dryrun:
    #    output = options.output
    #    jsondir = makedirs(output, '<type>s')
    #    write_creature(jsondir, struct, char_replace(struct['name']))


def restructure_<type>_pass(details):
    """Create the basic structure for this content type"""
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)

    # Top-level structure
    top = {'name': sb['name'], 'type': '<type>', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    sb['subtype'] = '<type>'

    # Flatten sections
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []

    return top


def section_pass(struct):
    """Extract structured data from sections"""
    def _handle_source(section):
        """Extract source book information"""
        # Implementation here - see skill.py for example
        pass

    def _clear_garbage(section):
        """Remove unwanted HTML elements"""
        # Implementation here - see skill.py for example
        pass

    def _clear_links(section):
        """Extract links into structured format"""
        text = section.setdefault('text', "")
        links = section.setdefault('links', [])
        text, links = extract_links(text)

    _handle_source(struct)
    _clear_garbage(struct)
    _clear_links(struct)
```

### Key Points

- **Start simple** - Just get the basic structure working with `pprint()`
- **Use existing helpers** - Import from `universal.universal` and `universal.utils`
- **Fail fast** - Don't catch exceptions unless you're 100% certain how to handle them
- **Iterate** - Add structured extraction passes incrementally

## Step 2: Create the Parse Script

Create `bin/pf2_<type>_parse` - this is the command-line entry point.

```python
#!/usr/bin/env python
import sys
import os
from pfsrd2.<type> import parse_<type>
from universal.warnings import WarningReporting
from universal.options import exec_main, option_parser


def main():
    usage = "usage: %prog [options] [filenames]\nParses <type>s from pfsrd2 html to json and writes them to the specified directory"
    parser = option_parser(usage)
    (options, args) = parser.parse_args()
    options.subtype = "<type>"
    exec_main(options, args, parse_<type>, "<type>s")


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x bin/pf2_<type>_parse
```

## Step 3: Create the Load Script (Optional)

Create `bin/pf2_<type>_load` - for loading parsed JSON into a database.

This can be created later once you have stable JSON output. For now, just create a placeholder:

```python
#!/usr/bin/env python
import sys
import os
import json
from sh import find
from optparse import OptionParser
from pfsrd2.sql import get_db_path, create_db
from pfsrd2.sql.<type>s import insert_<type>, truncate_<type>s


def load_<type>s(conn, options):
    path = options.output + "/" + "<type>s"
    assert os.path.exists(path), "JSON Directory doesn't exist: %s" % path
    files = find(path, "-type", "f", "-name", "*.json").strip().split("\n")
    files = [os.path.abspath(f) for f in files]
    curs = conn.cursor()
    truncate_<type>s(curs)
    for f in files:
        with open(f) as fp:
            data = json.load(fp)
            print(data['name'])
            insert_<type>(curs, data)
    conn.commit()


def option_parser(usage):
    parser = OptionParser(usage=usage)
    parser.add_option(
        "-o", "--output", dest="output",
        help="Output data directory.  Should be top level directory of psrd data. (required)")
    return parser


def main():
    usage = "usage: %prog [options] [filenames]\nReads <type> json and inserts them into a <type> db"
    parser = option_parser(usage)
    (options, args) = parser.parse_args()
    db_path = get_db_path("pfsrd2.db")
    conn = create_db(db_path)
    load_<type>s(conn, options)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x bin/pf2_<type>_load
```

## Step 4: Create the Runner Script

Create `bin/pf2_run_<type>s.sh` - the pipeline script that processes all files.

```bash
#!/bin/bash

source dir.conf

rm errors.pf2.<type>.log

if test -f "errors.pf2.<type>"; then
	cat errors.pf2.<type> | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_<type>_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.<type>.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/<ContentDir>/<Pattern> | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_<type>_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.<type>.log
		fi
	done
fi
```

**Replace:**
- `<type>` - Your content type (e.g., `item`, `spell`, `feat`)
- `<ContentDir>` - Directory in web files (e.g., `Armor`, `Spells`, `Feats`)
- `<Pattern>` - File pattern to match (e.g., `Armor.aspx.ID_*`, `Spells.aspx.ID_*`)

Make it executable:
```bash
chmod +x bin/pf2_run_<type>s.sh
```

### How the Runner Works

1. **Sources dir.conf** - Loads `$PF2_DATA_DIR` and `$PF2_WEB_DIR` environment variables
2. **Clears old error log** - Removes `errors.pf2.<type>.log`
3. **Checks for error file** - If `errors.pf2.<type>` exists (no .log), only process those files
4. **Otherwise processes all files** - Matches pattern and processes each file
5. **Logs failures** - Any failed file gets written to `errors.pf2.<type>.log`

## Step 5: Test the Parser

```bash
cd PFSRD2-Parser/bin
source dir.conf

# Test on a single file
./pf2_<type>_parse -o $PF2_DATA_DIR $PF2_WEB_DIR/<ContentDir>/<specific_file>

# Run the full pipeline
./pf2_run_<type>s.sh

# Check for errors
cat errors.pf2.<type>.log
```

## Step 6: Iterate on Structured Extraction

Once you have basic parsing working:

1. **Examine the output** - Look at the `pprint()` output to see what data exists
2. **Identify mechanics in text** - Find game mechanics buried in text blocks
3. **Extract to structured fields** - Create new passes to pull out structured data
4. **Update the schema** - Document new fields in `pfsrd2/schema/<type>.schema.json`

### Common Extraction Patterns

Look for these in text blocks to extract:

- **Action types** - "as a reaction", "two actions", etc.
- **Traits** - Often in `<span>` tags with special styling
- **Requirements** - "You must be wielding...", etc.
- **Durations** - "for 1 minute", "until the end of your turn"
- **Costs** - "1 action", "10 gp", etc.
- **Conditions** - "frightened 1", "stunned"
- **Damage** - "2d6 fire damage"

Create focused passes to extract each category.

## Example: Items/Armor

For armor, you might add passes to extract:

```python
def armor_stats_pass(struct):
    """Extract armor-specific mechanics"""
    # AC bonus: +3 AC
    # Dex cap: max Dex +2
    # Check penalty: -2 to checks
    # Speed penalty: -5 ft speed
    # Strength requirement: Str 16
    # Armor group: plate
    # Traits: bulwark, noisy
    pass
```

Each pass should extract specific mechanical properties into discrete fields rather than leaving them as opaque text.

## File Naming Conventions

- **Parser module:** `pfsrd2/<type>.py` (singular)
- **Parse script:** `bin/pf2_<type>_parse` (singular, no extension)
- **Load script:** `bin/pf2_<type>_load` (singular, no extension)
- **Runner script:** `bin/pf2_run_<type>s.sh` (plural, .sh extension)
- **Error log:** `bin/errors.pf2.<type>.log` (singular)
- **Error file:** `bin/errors.pf2.<type>` (singular, no extension)
- **Output directory:** `pfsrd2-data/<type>s/` (plural)

## Summary Checklist

- [ ] Create `pfsrd2/<type>.py` with `parse_<type>()` function
- [ ] Create `bin/pf2_<type>_parse` (make executable)
- [ ] Create `bin/pf2_<type>_load` (make executable, can be placeholder)
- [ ] Create `bin/pf2_run_<type>s.sh` (make executable)
- [ ] Update script with correct content directory and file pattern
- [ ] Test on a single file first
- [ ] Run full pipeline and check errors
- [ ] Iterate on extracting structured mechanics
- [ ] Create/update JSON schema when ready

## Advanced Parsing Patterns

### Text vs Sections: The H2 Rule

**Key principle:** Text immediately after stats goes in top-level `text` field, NOT in a Description section. Only create sections when there are actual headings (h2, h3) in the content.

```python
def _extract_description(bs, struct):
    """Extract description text and links to top level.

    Text from the first content area after stats (before any h2 headings)
    should be added to struct['text'], not wrapped in a section.
    """
    # Extract text from remaining HTML
    desc_text = _normalize_whitespace(str(bs))
    links = get_links(bs, unwrap=True)

    # Add to top level, NOT as a section
    if desc_text:
        struct['text'] = desc_text
    if links:
        struct['links'] = links
```

**Why?** This matches how other parsers work - the initial description is metadata about the item, while sections (with h2/h3 headings) represent distinct subsections like "Heightened Effects", "Variants", etc.

**In schema:**
- Make `sections` field optional (not required)
- Add `text` and `links` as optional top-level fields
- Sections only populated when h2/h3 headings exist

### When to Break Out Modifiers

Modifiers should be extracted when they represent **conditional bonuses, penalties, or situational effects** that apply to a base value.

**Extract modifiers when:**
- Text contains parenthetical conditions: "20 feet (40 feet with haste)"
- Bonuses depend on circumstances: "+2 (+4 against undead)"
- Multiple damage types: "1d6 + 1d4 fire"
- Conditional effects: "Speed 10 feet (pushed or pulled)"

**Example: Speed with modifiers**
```python
def _normalize_speed(sb):
    """Parse '10 feet (pushed or pulled)' into structured object."""
    value_str = sb['speed']

    # Extract modifiers from parentheses
    modifier_text = None
    match = re.match(r'^(.+?)\s*\((.+)\)$', value_str.strip())
    if match:
        value_str = match.group(1).strip()
        modifier_text = match.group(2).strip()

    # Parse base value
    value = int(value_str.replace(' feet', ''))

    speed_obj = {
        'type': 'stat_block_section',
        'subtype': 'speed',
        'value': value,
        'unit': 'feet'
    }

    # Add modifiers if present
    if modifier_text:
        speed_obj['modifiers'] = [{
            'type': 'stat_block_section',
            'subtype': 'modifier',
            'name': modifier_text
        }]

    sb['speed'] = speed_obj
```

**Don't extract modifiers when:**
- Text is purely descriptive: "made of iron"
- Information is clarifying, not mechanical: "see below for details"
- Single static value with no conditions

### Abilities: Structure and Extraction

Abilities represent **actions, special abilities, or activated effects** on items, creatures, or classes.

**Identifying abilities in HTML:**
1. Bold title at start: `<b>Aim</b>` or `<b>Activate</b>`
2. Often followed by action icon: `<span class="action">[two-actions]</span>`
3. May have result fields: **Success**, **Failure**, **Critical Success**, **Critical Failure**

**Ability schema structure:**
```json
{
  "type": "stat_block_section",
  "subtype": "ability",
  "name": "Aim",
  "ability_type": "offensive",
  "text": "Description of what the ability does",
  "action_type": {
    "type": "stat_block_section",
    "subtype": "action_type",
    "name": "Two Actions"
  },
  "links": [...],
  "success": "Text for success result",
  "failure": "Text for failure result"
}
```

**Extraction pattern:**
```python
def _extract_abilities(bs):
    """Extract abilities from sections with bold titles and action icons."""
    abilities = []
    known_abilities = ['Aim', 'Load', 'Launch', 'Activate']
    result_fields = ['Success', 'Failure', 'Critical Success', 'Critical Failure']

    for bold_tag in bs.find_all('b'):
        ability_name = get_text(bold_tag).strip()

        # Check if followed by action icon
        next_sib = bold_tag.next_sibling
        while next_sib and isinstance(next_sib, NavigableString) and next_sib.strip() == '':
            next_sib = next_sib.next_sibling
        has_action_icon = (isinstance(next_sib, Tag) and next_sib.name == 'span'
                          and 'action' in next_sib.get('class', []))

        if ability_name in known_abilities or has_action_icon:
            ability = {
                'type': 'stat_block_section',
                'subtype': 'ability',
                'name': ability_name,
                'ability_type': 'offensive'  # or 'defensive', 'interaction', etc.
            }

            # Extract description text (up to <br> tag)
            # Extract action_type using extract_action_type()
            # Extract result fields (Success, Failure, etc.)

            abilities.append(ability)

    return abilities if abilities else None
```

**Where abilities go:**
- Equipment: `stat_block.abilities` array
- Creatures: Top-level `offense.special_abilities` or `defense.special_abilities`
- Feats/Spells: Top-level `ability` field (single ability)

**Result fields are NOT separate sections** - they're fields on the ability object:
```json
{
  "name": "Launch",
  "text": "Main ability text",
  "success": "The target takes full damage",
  "failure": "The target takes half damage"
}
```

### Field Normalization: Types and Patterns

After extracting text values, normalize them into structured objects for mechanical use.

**Common normalization patterns:**

#### 1. Numeric Fields (AC, Fort, Ref)
```python
def _normalize_int_field(sb, field_name):
    """Convert '+3' or '3' to integer 3."""
    value = sb[field_name]
    if value.startswith('+'):
        value = value[1:]
    sb[field_name] = int(value.strip())
```

#### 2. Bonus Objects (AC Bonus, Dex Cap, Check Penalty)
```python
def _normalize_ac_bonus(sb, bonus_type='armor'):
    """Convert '+2' to structured bonus object."""
    value_str = sb['ac_bonus']

    # Handle conditional bonuses: '+2 (+4)' -> take base value
    if '(' in value_str:
        value_str = value_str.split('(')[0].strip()

    value = int(value_str.lstrip('+'))

    sb['ac_bonus'] = {
        'type': 'bonus',
        'subtype': 'ac',
        'bonus_type': bonus_type,  # 'armor' or 'shield'
        'bonus_value': value
    }
```

#### 3. Stat Requirements (Strength)
```python
def _normalize_strength(sb):
    """Convert 'Str 16' or '+3' to dual-format object."""
    value_str = sb['strength']
    is_modifier = value_str.startswith('+')

    if is_modifier:
        # Remastered format: +3 modifier
        modifier = int(value_str[1:])
        stat_value = modifier * 2 + 10  # +3 -> 16
    else:
        # Legacy format: 16 stat
        stat_value = int(value_str)
        modifier = (stat_value - 10) // 2  # 16 -> +3

    sb['strength'] = {
        'type': 'stat_block_section',
        'subtype': 'stat_requirement',
        'stat': 'strength',
        'legacy_value': stat_value,
        'remastered_value': modifier
    }
```

#### 4. Damage Arrays
```python
def _normalize_damage(sb):
    """Convert '1d8 S + 1d4 F' to array of damage objects."""
    damage_type_map = {
        'B': 'bludgeoning', 'P': 'piercing', 'S': 'slashing',
        'F': 'fire', 'C': 'cold', 'E': 'electricity', 'A': 'acid'
    }

    damage_parts = sb['damage'].split('+')
    damage_array = []

    for part in damage_parts:
        tokens = part.strip().split()
        if len(tokens) >= 2:
            formula = tokens[0]  # '1d8'
            damage_type_code = tokens[1]  # 'S'

            damage_array.append({
                'type': 'stat_block_section',
                'subtype': 'attack_damage',
                'formula': formula,
                'damage_type': damage_type_map[damage_type_code]
            })

    sb['damage'] = damage_array
```

#### 5. Bulk Objects
```python
def _normalize_bulk(sb):
    """Convert 'L' or '2' to structured object."""
    value_str = sb['bulk'].strip()

    if value_str == 'L':
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': None,  # L has no integer value
            'display': 'L'
        }
    else:
        sb['bulk'] = {
            'type': 'stat_block_section',
            'subtype': 'bulk',
            'value': int(value_str),
            'display': value_str
        }
```

**When to normalize:**
- Create a `normalize_fields_pass()` function called after stats are extracted
- Run BEFORE schema validation (normalized fields must match schema)
- Run AFTER trait enrichment (traits may have normalized fields too)

### Link Accounting: Ensuring No Links Lost

**Problem:** HTML has links that must become structured link objects. If links are lost during parsing, we've failed to preserve data.

**Solution:** Count links in HTML, count link objects in JSON, assert they match.

```python
def parse_equipment(filename, options):
    # ... parse HTML ...

    # COUNT INITIAL LINKS: All <a game-obj> tags in HTML
    item_name = struct.get('name', '')
    initial_link_count = _count_links_in_html(details['text'], exclude_name=item_name)

    # ... extract sections, stats, etc. ...

    links_removed = section_pass(struct, config)  # Returns count of intentionally removed links
    initial_link_count -= links_removed

    # ... more processing ...

    # COUNT FINAL LINKS: All link objects in JSON
    final_link_count = _count_links_in_json(struct)

    if final_link_count != initial_link_count:
        raise AssertionError(
            f"Link accounting failed: started with {initial_link_count} links in HTML, "
            f"ended with {final_link_count} link objects in JSON. "
            f"Links were lost during parsing."
        )
```

**Exclusions from counting:**
- Self-references (links from item to itself)
- Trait name links (replaced by database trait data during enrichment)
- Intentionally removed redundant sections (must be counted and subtracted)

**Link extraction patterns:**
```python
# Extract links and unwrap <a> tags
from universal.universal import get_links

soup = BeautifulSoup(html, 'html.parser')
links = get_links(soup, unwrap=True)

if links:
    section['links'] = links
```

### Trait Enrichment from Database

**Pattern:** HTML has minimal trait objects (just name + link). We enrich them with full data from the database.

```python
def trait_db_pass(struct):
    """Replace minimal trait objects with full database data."""
    def _check_trait(trait, parent):
        # Look up trait by name in database
        data = fetch_trait_by_name(curs, trait['name'])

        # Handle value extraction: 'Deadly d8' -> name='Deadly', value='d8'
        if not data:
            _handle_value(trait)  # Extract value from name
            data = fetch_trait_by_name(curs, trait['name'])

        # Handle edition matching (legacy vs remastered)
        db_trait = _handle_trait_link(data)

        # Replace trait in parent list
        parent[parent.index(trait)] = db_trait

    # Walk structure and enrich all traits
    walk(struct, test_key_is_value('subtype', 'trait'), _check_trait)
```

**Edition handling:** If trait edition doesn't match item edition, follow `alternate_link` to get correct version.

**Value extraction:** Some traits have values in their name:
- "Deadly d8" -> `name="Deadly"`, `value="d8"`
- "Entrench Melee" -> `name="Entrench"`, `value="Melee"`
- "Range 100 feet" -> `name="Range"`, `value="100 feet"`

### Equipment-Specific Patterns

#### Shared vs Nested Fields

Equipment stats have different nesting levels based on applicability:

```python
# Shared fields: Apply to all equipment regardless of type
shared_fields = ['price', 'bulk', 'access']

# Nested fields: Specific to equipment subtype
armor_nested = ['ac_bonus', 'dex_cap', 'check_penalty', 'speed_penalty', 'strength', 'group']
weapon_nested = ['damage', 'weapon_type', 'group', 'range', 'reload']
```

**Structure in JSON:**
```json
{
  "stat_block": {
    "price": "35 gp",       // Shared field
    "bulk": {...},          // Shared field
    "armor": {              // Armor-specific object
      "ac_bonus": {...},    // Nested field
      "dex_cap": {...}      // Nested field
    }
  }
}
```

#### Combination Weapons (Multiple Modes)

Some weapons have melee AND ranged modes:

```python
if is_combination_weapon:
    weapon_obj = {
        'category': 'Martial',  // Weapon-level field
        'melee': {
            'damage': [...],
            'weapon_type': 'Melee',
            'group': {...}
        },
        'ranged': {
            'damage': [...],
            'weapon_type': 'Ranged',
            'range': {...},
            'reload': {...}
        }
    }
```

#### Item Hitpoints (Shields, Siege Weapons)

```python
def _normalize_item_hitpoints(sb):
    """Build hitpoints object from hp_bt, hardness, immunities."""
    hitpoints = {
        'type': 'stat_block_section',
        'subtype': 'hitpoints'
    }

    # Parse "20 (BT 10)" or "40 (BT 20)"
    match = re.match(r'(\d+)\s*\((?:BT\s+)?(\d+)\)', sb['hp_bt'])
    hitpoints['hp'] = int(match.group(1))
    hitpoints['break_threshold'] = int(match.group(2))

    # Add hardness
    if 'hardness' in sb:
        hitpoints['hardness'] = int(sb['hardness'])
        del sb['hardness']

    # Parse immunities HTML into protection objects
    if 'immunities' in sb:
        hitpoints['immunities'] = _parse_immunities(sb['immunities'])
        del sb['immunities']

    sb['hitpoints'] = hitpoints
    del sb['hp_bt']
```

### Parsing Order and Dependencies

**Correct order matters.** Follow this sequence:

```python
def parse_equipment(filename, options):
    # 1. Parse HTML to initial structure
    details = parse_equipment_html(filename)
    struct = restructure_equipment_pass(details, equipment_type)

    # 2. Count initial links (before any extraction)
    initial_link_count = _count_links_in_html(details['text'], exclude_name=item_name)

    # 3. Add aonid and game-obj
    aon_pass(struct, basename)

    # 4. Extract sections (stats, description, abilities)
    links_removed = section_pass(struct, config)
    initial_link_count -= links_removed

    # 5. Restructure (move stat_block to top level)
    restructure_pass(struct, "stat_block", find_stat_block)

    # 6. Normalize numeric fields
    normalize_numeric_fields_pass(struct, config)

    # 7. Add game-id
    game_id_pass(struct)

    # 8. Add license
    license_pass(struct)
    license_consolidation_pass(struct)

    # 9. Convert markdown
    markdown_pass(struct, struct["name"], '')

    # 10. Determine edition (legacy vs remastered)
    edition = edition_pass(struct['sections'])
    struct['edition'] = edition

    # 11. VERIFY LINKS (before trait enrichment adds new links)
    final_link_count = _count_links_in_json(struct)
    assert final_link_count == initial_link_count

    # 12. Enrich traits from database (adds links from database)
    trait_db_pass(struct)

    # 13. Enrich equipment groups from database
    equipment_group_pass(struct, config)

    # 14. Remove empty sections
    remove_empty_sections_pass(struct)

    # 15. Validate schema
    if not options.skip_schema:
        struct['schema_version'] = 1.0
        validate_against_schema(struct, config['schema_file'])

    # 16. Write output
    if not options.dryrun:
        write_creature(jsondir, struct, name)
```

**Key insights:**
- Link accounting happens BEFORE trait enrichment (which adds database links)
- Normalization happens AFTER extraction but BEFORE schema validation
- Edition determination happens BEFORE trait enrichment (needed for edition-aware lookups)
- Schema validation is the final check before writing

## Philosophy

Remember the project mission:

- **Structured over opaque** - Extract mechanics into discrete fields, not buried in text
- **Fail fast** - Let exceptions propagate for easier debugging
- **Iterate progressively** - Don't extract everything at once
- **Schema as contract** - Document what data is exposed
- **Links are data** - Every HTML link must become a structured link object
- **Normalize for mechanics** - "+2" as text is useless; `{"bonus_value": 2}` is actionable

Start simple, get it working, then progressively extract more structured data over time.
