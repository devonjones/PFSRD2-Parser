# PFSRD2-Parser Architecture

This document describes the complete architecture and design patterns used in the PFSRD2-Parser system.

## Overview

The parser follows a **multi-stage pipeline architecture** where HTML content from Archives of Nethys (AoN) is transformed through a series of passes into structured JSON data that conforms to defined schemas.

The core philosophy is to extract game mechanics into discrete, structured fields rather than leaving them as opaque text blocks, enabling programmatic access to game system data.

## The Complete Data Curation Pipeline

The PFSRD2-Parser is **part of a larger data curation pipeline**, not just an HTML parser. Understanding this complete workflow is essential to understanding the architecture decisions.

### Full Pipeline Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Archives of Nethys Website (2e.aonprd.com)              │
│    - Hand-maintained HTML                                   │
│    - Can contain bugs and inconsistencies                   │
└────────────────────────────┬────────────────────────────────┘
                             │ wget (pfsrd2-web/download.sh)
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Raw HTML Download                                        │
│    - Downloaded with wget -rp                               │
│    - Preserves all content and structure                    │
└────────────────────────────┬────────────────────────────────┘
                             │ Transform (pfsrd2-web/*.sh)
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Normalized HTML [upstream branch]                        │
│    - xmllint --format (pretty print)                        │
│    - One tag per line (minimal git diffs)                   │
│    - Organized into directories                             │
└────────────────────────────┬────────────────────────────────┘
                             │ Merge + Manual HTML Fixes
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Curated HTML [modified branch]                           │
│    pfsrd2-web repository                                    │
│    - Fixed AoN HTML bugs                                    │
│    - Corrected data errors                                  │
│    - Version controlled fixes                               │
└────────────────────────────┬────────────────────────────────┘
                             │ Parse (PFSRD2-Parser)
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Structured JSON [pfsrd2-data]                            │
│    - Validated against schemas                              │
│    - Discrete fields for game mechanics                     │
│    - Ready for consumption by tools                         │
└─────────────────────────────────────────────────────────────┘
```

### pfsrd2-web: The HTML Curation Layer

The `pfsrd2-web` repository is a critical component that sits **before** the parser:

#### Transform Pipeline (pfsrd2-web/*.sh)

**Purpose:** Normalize HTML for clean git diffs and merges

```bash
# 1. Download from AoN
wget -rp --compression=auto --no-parent http://2e.aonprd.com

# 2. Normalize filenames
rename 's/\?/./g' *    # ? becomes .
rename 's/\&/./g' *    # & becomes .
rename 's/\=/\_/g' *   # = becomes _

# 3. Organize into directories
mkdir -p Monsters
mv Monsters.aspx* Monsters/

# 4. Transform HTML for minimal diffs
for file in Monsters/*ID*[0-9]; do
  xmllint --format --html --htmlout --pretty 2 $file > $file.html
  sed -i -e ':a;N;$!ba;s/\n//g' $file.html       # Remove ALL newlines
  sed -i -e 's/>/>\n/g' $file.html                # Add newline after each >
  rm $file
done
```

**Result:** One HTML tag per line = single-line git diffs

**Example transformation:**
```html
<!-- Before: Hard to diff -->
<div class="stat-block"><h1>Goblin</h1><span>Level -1</span></div>

<!-- After: Each tag on own line -->
<div class="stat-block">
<h1>Goblin</h1>
<span>Level -1</span>
</div>
```

This means:
- Changing a tag's attribute = 1 line in git diff
- Adding/removing a tag = 1 line in git diff
- Easy to see exactly what changed
- Git merges are manageable

#### Git Branch Strategy in pfsrd2-web

**Two branches:**

**`upstream` branch:**
- Clean downloads from AoN after transform
- Represents "what AoN publishes"
- Never has manual edits
- Updated when downloading new AoN data

**`modified` branch:**
- Starts from upstream
- Contains HTML fixes for AoN bugs
- Contains data corrections
- This is what PFSRD2-Parser reads

**Workflow when AoN updates:**
```bash
# 1. Create new upstream branch
git checkout -b upstream-2026-01-11
cd 2e.aonprd.com && rm -rf *

# 2. Download and transform
../download.sh          # wget from AoN
../1.start.sh          # Normalize filenames
../2.images.sh         # Organize images
../3.6.monsters.sh     # Transform monsters HTML
# ... other transform scripts

# 3. Commit transformed HTML
git add .
git commit -m "2026-01-11 AoN download"

# 4. Merge into modified branch
git checkout modified
git merge upstream-2026-01-11

# 5. Resolve conflicts (AoN changes vs your fixes)
# - Keep your fixes where AoN still has bugs
# - Accept AoN changes where they fixed issues
# - Update your fixes if AoN structure changed

git commit -m "Merge AoN 2026-01-11 update"
```

### Why Fix HTML in Source, Not Code

**When AoN has an HTML bug, the choice is:**

❌ **Make parser handle bad HTML:**
```python
# Parser becomes complex with workarounds
if malformed_html:
    try_to_fix_it()
elif missing_section:
    use_default()
elif inconsistent_format:
    guess_what_was_meant()
```
- Parser complexity grows
- Workarounds accumulate
- Hard to remove workarounds later
- Can't distinguish bugs from features

✅ **Fix the HTML in pfsrd2-web:**
```bash
# Edit the HTML file directly
vim 2e.aonprd.com/Monsters/Monsters.aspx.ID_123.html
# Fix the malformed tag
git commit -m "Fix malformed defense section in Goblin Warrior"
```
- Parser stays simple
- Fix is version controlled
- Git history explains why
- Can remove fix if AoN fixes it upstream

### Benefits of This Architecture

**1. Parser Can Be Strict**
- Assumes well-formed HTML (because it's curated)
- Fail-fast catches when HTML fixes don't work
- No need for workarounds or fallbacks

**2. Provenance is Clear**
- Git shows: what's from AoN vs what you fixed
- Git blame shows: when and why you fixed it
- Can track if AoN fixed their bug

**3. Fixes Are Portable**
- HTML fixes help any tool parsing AoN data
- Not locked into this parser's quirks
- Other parsers benefit from cleaned HTML

**4. Updates Are Manageable**
- Git merge handles AoN updates
- Conflicts surface when AoN changes what you fixed
- Decision point: keep fix, update fix, or remove fix

**5. Complexity Is Isolated**
- Transform complexity in pfsrd2-web scripts
- Parser complexity in PFSRD2-Parser
- Each repository has clear responsibility

### Three Git Repositories

The complete system uses three repositories:

**pfsrd2-web** (HTML source):
- Downloads and transforms HTML from AoN
- Maintains HTML bug fixes
- Branches: upstream (clean AoN) + modified (fixed)

**PFSRD2-Parser** (parsing code):
- Python parsers for each content type
- Reads from pfsrd2-web/2e.aonprd.com
- Strict parsing with fail-fast

**pfsrd2-data** (JSON output):
- Structured JSON output
- Validated against schemas
- Consumed by tools and applications

**All three are version controlled**, enabling:
- Tracking changes in source (HTML)
- Tracking changes in code (parsers)
- Tracking changes in output (JSON)
- Understanding causality: "This JSON changed because I fixed that HTML bug"

This architecture is **not just parsing - it's data curation**.

### Data Versioning Strategy (pfsrd2-data)

The **pfsrd2-data** repository uses a git branching strategy for schema versioning:

#### Schema Version Branches

**When schemas change in backwards-incompatible ways:**
- Create a new branch in pfsrd2-data with the last data at the previous schema version
- Branch name typically: `schema-v1.0`, `schema-v2.0`, etc.
- This preserves a stable version for consumers

**What counts as breaking?**
- ✅ Removing fields
- ✅ Renaming fields
- ✅ Changing field types
- ✅ Changing field semantics
- ❌ Adding new fields (non-breaking, stays on main)

**Example workflow:**
```bash
# Parser evolves, schema changes in breaking way
# Before making breaking change:
cd pfsrd2-data
git checkout -b schema-v1.0  # Preserve old schema version
git push origin schema-v1.0

# Now continue development on main with new schema
git checkout main
# Update parser to produce new schema
# Update schema files to reflect changes
```

#### Consumer Contract

**Consumers should NOT use `main` branch:**
- ❌ `main` is active development - schema may change
- ✅ Pin to a specific schema version branch for stability

**Recommended consumer usage:**
```bash
# Clone specific schema version
git clone -b schema-v1.0 https://github.com/user/pfsrd2-data.git

# Or add as submodule at specific version
git submodule add -b schema-v1.0 https://github.com/user/pfsrd2-data.git data
```

#### Benefits of This Approach

**1. Stability for Consumers**
- Applications can rely on stable schema
- No surprise breaking changes
- Clear versioning contract

**2. Freedom to Evolve**
- Parser development can continue on main
- Breaking changes are OK (just branch first)
- Additive changes are free (non-breaking)

**3. Git-Native Versioning**
- No separate versioning infrastructure needed
- Git branches are the version mechanism
- Easy to see what changed between versions

**4. Multiple Versions Coexist**
- Old applications on schema-v1.0 continue working
- New applications can use schema-v2.0
- No forced upgrades

**Example: Breaking vs. Non-Breaking Changes**

**Non-breaking (no new branch needed):**
```json
// Before
{
  "name": "Goblin",
  "level": -1
}

// After (added field)
{
  "name": "Goblin",
  "level": -1,
  "rarity": "common"  // New field added
}
```
Old consumers simply ignore new field - still works.

**Breaking (requires new branch):**
```json
// Before (schema-v1.0)
{
  "name": "Goblin",
  "hit_points": 6
}

// After (main, schema-v2.0)
{
  "name": "Goblin",
  "hp": {  // Field renamed and restructured
    "value": 6,
    "formula": "1d6"
  }
}
```
Old consumers break - `hit_points` no longer exists.

#### Practical Usage

**For parser development:**
- Work on main freely
- Add fields without branching (non-breaking)
- Branch before making breaking changes
- Update schema files to match output

**For consumers:**
- Clone a specific schema version branch
- Don't pull from main in production
- Upgrade to new schema version deliberately
- Test against new schema before upgrading

This versioning strategy provides **stability without sacrificing evolution**.

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                       HTML Input Files                       │
│                  (pfsrd2-web/2e.aonprd.com)                 │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    Universal Parsers                         │
│            (universal/ - game-agnostic logic)                │
│  • parse_universal() - Initial HTML parsing                  │
│  • entity_pass() - Entity normalization                      │
│  • extract helpers - Links, sources, traits                  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                  Game-Specific Parsers                       │
│          (pfsrd2/ - Pathfinder 2e specific logic)           │
│  • restructure_<type>_pass() - Domain structure              │
│  • section_pass() - Extract structured data                 │
│  • addon_pass() - Extract mechanics                         │
│  • <type>_specific_passes() - Type-specific extraction       │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    Database Enrichment                       │
│               (pfsrd2/sql/ - reference data)                 │
│  • trait_db_pass() - Enrich trait data                      │
│  • monster_ability_db_pass() - Enrich abilities              │
│  • Database provides: traits, sources, abilities             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                  Schema Validation                           │
│            (pfsrd2/schema/ - validation rules)               │
│  • Validates structure against JSON schema                   │
│  • Ensures required fields present                          │
│  • Type checking and enumeration validation                 │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                     JSON Output Files                        │
│                    (pfsrd2-data/<type>s/)                   │
│           Organized by: type/source/name.json                │
└─────────────────────────────────────────────────────────────┘
```

## Parser Structure Pattern

Every parser follows a consistent structure:

### Main Parse Function

```python
def parse_<entity_type>(filename, options):
    # 1. Initial HTML parsing using universal parser
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    details = parse_universal(
        filename,
        subtitle_text=True,
        max_title=4,
        cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput"
    )

    # 2. Entity normalization (HTML entities, special characters)
    details = entity_pass(details)

    # 3. Restructuring into domain structure
    struct = restructure_<entity_type>_pass(details)

    # 4. Extract AoN metadata (game-obj, aonid)
    aon_pass(struct, basename)

    # 5. Multiple transformation passes
    section_pass(struct)
    addon_pass(struct)
    trait_db_pass(struct)
    game_id_pass(struct)

    # 6. License information
    license_pass(struct)
    license_consolidation_pass(struct)

    # 7. Convert to markdown (optional)
    markdown_pass(struct, struct["name"], '')

    # 8. Cleanup
    remove_empty_sections_pass(struct)

    # 9. Schema validation
    if not options.skip_schema:
        struct['schema_version'] = 1.2
        validate_against_schema(struct, "<entity>.schema.json")

    # 10. File output
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, '<entity>s', name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))
```

### Standard Pass Order

1. **parse_universal()** - Initial HTML parsing
2. **entity_pass()** - Normalize entities
3. **restructure_<type>_pass()** - Create domain structure
4. **aon_pass()** - Extract AoN metadata
5. **section_pass()** - Process sections
6. **<type>_specific_passes()** - Extract type-specific mechanics
7. **trait_db_pass()** - Enrich traits from database
8. **game_id_pass()** - Generate unique IDs
9. **license_pass()** - Add license info
10. **license_consolidation_pass()** - Consolidate licenses
11. **markdown_pass()** - Convert HTML to markdown
12. **remove_empty_sections_pass()** - Cleanup
13. **validate_against_schema()** - Validate structure
14. **write output** - Write JSON files

## Pass-Based Processing

The parser uses a **pass-based architecture** where each pass performs a specific transformation on the data structure. Passes are functions that mutate the structure in place.

### Universal Passes

Located in `universal/universal.py`:

#### parse_universal(filename, subtitle_text=False, max_title=2, cssclass=None)
- **Purpose:** Initial HTML parsing and section extraction
- **Input:** HTML file path
- **Output:** List of parsed section dictionaries
- **Process:**
  - Parse HTML with BeautifulSoup
  - Find main content by CSS class
  - Extract title and sections
  - Build nested section structure based on heading levels

#### entity_pass(details)
- **Purpose:** Normalize HTML entities and special characters
- **Process:**
  - Walk entire structure
  - Convert HTML entities to Unicode
  - Normalize special characters
  - Handle common encoding issues

#### aon_pass(struct, basename)
- **Purpose:** Extract Archives of Nethys metadata
- **Process:**
  - Parse filename for IDs
  - Extract `game-obj` attribute (creature type, trait category, etc.)
  - Extract `aonid` attribute (unique AoN identifier)
  - Store in top-level structure

#### source_pass(struct)
- **Purpose:** Extract and propagate source information
- **Process:**
  - Find source book references
  - Extract page numbers
  - Handle errata links
  - Propagate to all sections

#### game_id_pass(struct)
- **Purpose:** Generate unique game identifiers
- **Process:**
  - Combine type and name
  - Normalize to lowercase, underscore-separated
  - Ensure uniqueness within type

#### restructure_pass(struct)
- **Purpose:** Restructure data into final format
- **Process:**
  - Flatten nested sections if needed
  - Move metadata to appropriate levels
  - Normalize section types

#### remove_empty_sections_pass(struct)
- **Purpose:** Remove sections with no content
- **Process:**
  - Recursively walk structure
  - Remove sections with empty text and no subsections
  - Clean up empty lists

#### markdown_pass(struct, name, path)
- **Purpose:** Convert HTML to markdown
- **Process:**
  - Walk structure finding text fields
  - Convert using custom markdown converter
  - Validate remaining HTML tags
  - Store original HTML in separate field

### Game-Specific Passes

Located in `pfsrd2/<type>.py`:

#### restructure_<type>_pass(details)
- **Purpose:** Transform initial structure into type-specific format
- **Example (monster_ability):**
  ```python
  def restructure_monster_ability_pass(details):
      sb = details[0]  # First section is the stat block
      rest = details[1:]  # Remaining sections

      assert len(rest) == 0, "More sections than expected (1)"
      assert len(sb['sections']) == 0

      sb['type'] = 'ability'
      sb['ability_type'] = 'universal_monster_ability'
      return sb
  ```

#### section_pass(struct)
- **Purpose:** Extract structured data from sections
- **Common sub-operations:**
  - Fix name (clean HTML)
  - Extract action types
  - Extract source information
  - Extract traits
  - Extract links
  - Clear garbage HTML
- **Example:**
  ```python
  def section_pass(struct):
      _fix_name(struct)
      _handle_action_types(struct)
      _handle_source(struct)
      _handle_traits(struct)
      _clear_links(struct)
      _clear_garbage(struct)
  ```

#### addon_pass(struct)
- **Purpose:** Extract structured addons from text
- **Recognized addons:**
  - Frequency
  - Trigger
  - Effect
  - Duration
  - Requirement/Requirements
  - Prerequisite
  - Critical Success/Success/Failure/Critical Failure
  - Range
  - Cost
- **Pattern:**
  ```python
  def addon_pass(struct):
      text = struct['text']
      bs = BeautifulSoup(text, 'html.parser')
      children = list(bs)

      addons = {}
      current = None
      parts = []

      while len(children) > 0:
          child = children.pop(0)
          if child.name == 'b':
              # Bold text indicates addon name
              current = get_text(child).strip()
          elif current:
              # Following text is addon value
              addons[current.lower().replace(" ", "_")] = str(child)
          else:
              # Regular text
              parts.append(str(child))

      struct.update(addons)
      struct['text'] = ''.join(parts)
  ```

#### trait_db_pass(struct)
- **Purpose:** Enrich traits from database
- **Process:**
  - Walk structure finding all traits
  - Query database for each trait
  - Merge classes from database
  - Handle legacy/remastered versions
  - Handle variable traits (e.g., "[magical tradition]")

#### monster_ability_db_pass(struct)
- **Purpose:** Enrich monster abilities from database
- **Process:**
  - Find all ability references
  - Query database for universal abilities
  - Replace references with full data

## HTML Extraction Patterns

### BeautifulSoup Processing

All parsers use BeautifulSoup for HTML manipulation:

```python
bs = BeautifulSoup(text, 'html.parser')
children = list(bs.children)

# Sequential processing pattern
while children:
    child = children.pop(0)

    if child.name == 'b':
        # Process bold text (usually labels)
        label = get_text(child).strip()
    elif child.name == 'a':
        # Extract links
        name, link = extract_link(child)
    elif child.name == 'span':
        # Extract special elements (actions, traits)
        process_span(child)
    elif isinstance(child, NavigableString):
        # Process text content
        text = str(child).strip()
```

### Link Extraction

```python
def extract_link(a):
    """Extract structured link data from anchor tag"""
    name = get_text(a)
    link = {
        'type': 'link',
        'name': name.strip(),
        'alt': name.strip()
    }

    # Extract AoN metadata
    if a.has_attr('game-obj'):
        link['game-obj'] = a['game-obj']
    if a.has_attr('aonid'):
        link['aonid'] = int(a['aonid'])

    return name, link

def extract_links(text):
    """Extract all links from HTML text"""
    bs = BeautifulSoup(text, 'html.parser')
    links = []

    for a in bs.find_all('a'):
        name, link = extract_link(a)
        links.append(link)
        # Replace link with just the text
        a.replace_with(name)

    return str(bs), links
```

### Source Extraction

```python
def extract_source(a):
    """Extract source book information from anchor"""
    text = get_text(a)

    # Parse "Source Book pg. 123" format
    parts = text.split(" pg. ")
    name = parts[0].replace("Source ", "").strip()
    page = int(parts[1]) if len(parts) > 1 else None

    source = {
        'type': 'source',
        'name': name,
        'link': a['href'] if a.has_attr('href') else None
    }

    if page:
        source['page'] = page

    return source
```

### Trait Extraction

```python
def extract_span_traits(text):
    """Extract traits from span elements"""
    bs = BeautifulSoup(text, 'html.parser')
    traits = []

    for span in bs.find_all('span', class_='trait'):
        name = get_text(span).strip()
        trait = {
            'type': 'stat_block_section',
            'subtype': 'trait',
            'name': name
        }

        if span.has_attr('game-obj'):
            trait['game-obj'] = span['game-obj']
        if span.has_attr('aonid'):
            trait['aonid'] = int(span['aonid'])

        traits.append(trait)
        span.decompose()  # Remove from HTML

    return str(bs), traits

def extract_starting_traits(text):
    """Extract traits from parentheses at start of text"""
    # Example: "(arcane, attack, evocation)"
    if not text.strip().startswith("("):
        return text, []

    # Extract traits from parentheses
    match = re.match(r'^\((.*?)\)', text)
    if not match:
        return text, []

    trait_text = match.group(1)
    traits = [t.strip() for t in trait_text.split(',')]

    # Remove traits from text
    text = text[match.end():].strip()

    return text, traits
```

### Action Type Extraction

```python
def extract_action_type(text, return_object=False):
    """Extract action type from text or span"""
    # Look for action icons in spans
    # [#] = One Action
    # [##] = Two Actions
    # [###] = Three Actions
    # [-] = Free Action
    # [@] = Reaction

    bs = BeautifulSoup(text, 'html.parser')
    span = bs.find('span', class_='action')

    if not span:
        return text, None

    action_name = span.get('title', '').lower().replace(' ', '_')

    if return_object:
        action = {
            'type': 'stat_block_section',
            'subtype': 'action_type',
            'name': action_name
        }
    else:
        action = action_name

    span.decompose()
    return str(bs).strip(), action
```

## Structured Data Extraction

### The Goal: Discrete Fields vs. Opaque Text

**Bad - Opaque text block:**
```json
{
  "text": "The creature can Grab using only one hand. It can move even if it has a creature grabbed or restrained, but it must attempt a DC 25 Acrobatics check or suffer a -10-foot circumstance penalty to its Speed."
}
```

**Good - Structured mechanics:**
```json
{
  "name": "Grab",
  "action_type": "reaction",
  "trigger": "creature_successful_strike",
  "requirement": "one_hand_free",
  "effect": "attempt_athletics_to_grab",
  "special": [
    "can_move_while_grabbing",
    "acrobatics_dc_25_or_speed_penalty_10"
  ],
  "text": "The creature can Grab using only one hand..."
}
```

### Addon Extraction Pattern

Many game mechanics use a standard format:

```
<description text>

Frequency <value>
Trigger <value>
Effect <value>
```

Extract these into structured fields:

```python
def addon_pass(struct):
    """Extract structured addons from text"""

    def _extract_addons(text):
        bs = BeautifulSoup(text, 'html.parser')
        children = list(bs.children)

        # Reorder if hr separator exists
        _reorder_children(children)

        addons = {}
        current = None
        parts = []

        while children:
            child = children.pop(0)

            if child.name == 'b':
                # Bold text = addon name
                current = get_text(child).strip()
                if current == "Requirements":
                    current = "Requirement"
            elif current:
                # Text after bold = addon value
                addon_text = str(child)
                if addon_text.strip().endswith(";"):
                    addon_text = addon_text.rstrip()[:-1]
                addons[current.lower().replace(" ", "_")] = addon_text
            else:
                # Regular description text
                parts.append(str(child))

        return ''.join(parts), addons

    text, addons = _extract_addons(struct.get('text', ''))
    struct['text'] = text
    struct.update(addons)
```

### Identifying Extraction Opportunities

Look for these patterns in text to extract:

**Action Types:**
- "as a reaction"
- "as a free action"
- "one action", "two actions", "three actions"
- Action icons: [#], [##], [###], [-], [@]

**Conditions:**
- "frightened 1", "frightened 2"
- "stunned", "prone", "off-guard"
- "until the end of its next turn"

**Damage:**
- "2d6 fire damage"
- "1d8 persistent bleed damage"
- "extra 1d6 damage"

**Triggers:**
- "when an enemy moves adjacent"
- "at the start of its turn"
- "when you make a Strike"

**Durations:**
- "for 1 minute"
- "until the end of your next turn"
- "for 1 round"
- "sustained up to 1 minute"

**Requirements:**
- "must be wielding a shield"
- "only against flat-footed targets"
- "requires one hand free"

**Frequency:**
- "once per day"
- "once per round"
- "three times per day"

**Ranges:**
- "range 30 feet"
- "within 60 feet"
- "touch range"

## Database Integration

### Database Structure

SQLite database (`pfsrd2.db`) with versioned schema:

```python
def create_db(db_path):
    """Create or open database with version migration"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    curs = conn.cursor()

    # Check current version
    ver = get_version(curs)

    # Run migrations
    ver = create_db_v_1(conn, curs, ver)
    ver = create_db_v_2(conn, curs, ver)
    ver = create_db_v_3(conn, curs, ver)

    return conn

def create_db_v_1(conn, curs, ver):
    """Version 1: Create traits table"""
    if ver >= 1:
        return ver

    curs.execute("""
        CREATE TABLE traits (
            aonid INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            trait TEXT NOT NULL
        )
    """)
    curs.execute("CREATE INDEX traits_name_idx ON traits(name)")

    set_version(curs, 1)
    conn.commit()
    return 1
```

### Reference Tables

#### traits table
- **Purpose:** Store trait definitions with classes and edition info
- **Schema:**
  ```sql
  CREATE TABLE traits (
      aonid INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      trait TEXT NOT NULL  -- JSON blob
  )
  ```
- **Usage:** Enrich trait references with full trait data

#### trait_links table
- **Purpose:** Link legacy and remastered trait versions
- **Schema:**
  ```sql
  CREATE TABLE trait_links (
      legacy_aonid INTEGER,
      legacy_name TEXT,
      remaster_aonid INTEGER,
      remaster_name TEXT
  )
  ```
- **Usage:** Handle edition conversions

#### monster_abilities table
- **Purpose:** Store universal monster ability definitions
- **Schema:**
  ```sql
  CREATE TABLE monster_abilities (
      aonid INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      ability TEXT NOT NULL  -- JSON blob
  )
  ```
- **Usage:** Enrich ability references in creatures

#### sources table
- **Purpose:** Store source book information
- **Schema:**
  ```sql
  CREATE TABLE sources (
      aonid INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      source TEXT NOT NULL  -- JSON blob
  )
  ```

### Database Enrichment Pattern

```python
def trait_db_pass(struct):
    """Enrich traits from database"""
    db_path = get_db_path("pfsrd2.db")
    conn = get_db_connection(db_path)
    curs = conn.cursor()

    def _check_trait(trait, parent):
        # Query database
        fetch_trait_by_name(curs, trait['name'])
        data = curs.fetchone()

        if not data:
            return  # Trait not in database

        # Parse stored JSON
        db_trait = json.loads(data['trait'])

        # Merge classes
        if 'classes' in trait and 'classes' in db_trait:
            db_trait['classes'].extend(trait['classes'])
            db_trait['classes'] = list(set(db_trait['classes']))

        # Replace in parent structure
        index = parent.index(trait)
        parent[index] = db_trait

    # Walk structure finding all traits
    walk(struct, test_key_is_value('subtype', 'trait'), _check_trait)

    conn.close()
```

### Handling Edition Changes

PF2e has legacy (pre-remaster) and remastered editions:

```python
def handle_remaster_traits(struct):
    """Link legacy and remastered traits"""

    def _link_traits(trait, parent):
        if trait.get('remaster_aonid'):
            # This is a legacy trait with remaster link
            fetch_trait_by_aonid(curs, trait['remaster_aonid'])
            remaster_trait = curs.fetchone()

            # Add both versions
            trait['remaster_version'] = json.loads(remaster_trait['trait'])

    walk(struct, test_key_is_value('subtype', 'trait'), _link_traits)
```

## Helper Functions and Utilities

### Universal Utilities (universal/utils.py)

#### split_maintain_parens(text, delimiter=',')
- **Purpose:** Split text respecting parentheses
- **Example:** `"foo (bar, baz), qux"` → `["foo (bar, baz)", "qux"]`

#### split_comma_and_semicolon(text)
- **Purpose:** Complex delimiter handling
- **Handles:** Commas and semicolons with parentheses respect

#### clear_tags(text, tags=['br', 'hr'])
- **Purpose:** Remove specific HTML tags
- **Process:** Decompose tags from BeautifulSoup tree

#### get_text(element)
- **Purpose:** Extract text content from BeautifulSoup element
- **Safe:** Returns empty string for None

#### is_tag_named(element, names)
- **Purpose:** Type-safe tag name checking
- **Example:** `is_tag_named(child, ['b', 'strong'])`

#### get_unique_tag_set(text)
- **Purpose:** Find all unique tag names in HTML
- **Usage:** Validate acceptable tags

### Data Structure Utilities (universal/universal.py)

#### build_object(type, subtype, name, **kwargs)
- **Purpose:** Consistent object creation
- **Returns:** Dictionary with standard fields
- **Example:**
  ```python
  obj = build_object("stat_block_section", "trait", "fire")
  # Returns: {'type': 'stat_block_section', 'subtype': 'trait', 'name': 'fire'}
  ```

#### walk(struct, predicate, callback)
- **Purpose:** Tree traversal with predicates
- **Process:**
  - Recursively walk structure
  - Call predicate on each node
  - If predicate returns True, call callback
- **Example:**
  ```python
  def fix_all_traits(trait, parent):
      trait['name'] = trait['name'].title()

  walk(struct, test_key_is_value('subtype', 'trait'), fix_all_traits)
  ```

#### test_key_is_value(key, value)
- **Purpose:** Predicate builder for tree walking
- **Returns:** Function that tests if dict[key] == value
- **Example:**
  ```python
  predicate = test_key_is_value('type', 'link')
  walk(struct, predicate, process_link)
  ```

### Text Processing

#### filter_entities(text)
- **Purpose:** Normalize Unicode entities
- **Handles:** `&nbsp;`, `&mdash;`, `&hellip;`, etc.

#### clear_end_whitespace(text)
- **Purpose:** Remove trailing whitespace and punctuation
- **Process:** Strip from end while preserving internal whitespace

#### bs_pop_spaces(children)
- **Purpose:** Navigate through whitespace nodes
- **Usage:** Pop empty text nodes from BeautifulSoup children list

### String Utilities

#### string_with_modifiers_from_string_list(strings)
- **Purpose:** Parse stat strings with modifiers
- **Example:** `"Perception +15"` → `{'name': 'Perception', 'modifier': 15}`

#### char_replace(text)
- **Purpose:** Sanitize filenames
- **Process:**
  - Remove invalid filename characters
  - Replace spaces with underscores
  - Normalize for cross-platform compatibility

## Schema Usage and Validation

### Schema-Driven Development

Every entity type has a JSON schema defining valid structure:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Monster Ability",
  "type": "object",

  "properties": {
    "name": {
      "type": "string",
      "description": "The name of the monster ability"
    },
    "type": {
      "type": "string",
      "enum": ["ability"]
    },
    "ability_type": {
      "type": "string",
      "enum": ["universal_monster_ability"]
    },
    "game-id": {
      "type": "string",
      "pattern": "^[a-z0-9_]+$"
    },
    "sources": {
      "$ref": "#/definitions/sources"
    },
    "traits": {
      "type": "array",
      "items": {"$ref": "#/definitions/trait"}
    },
    "text": {
      "type": "string"
    },
    "frequency": {
      "type": "string"
    },
    "trigger": {
      "type": "string"
    },
    "effect": {
      "type": "string"
    }
  },

  "required": ["name", "type", "game-id", "sources", "schema_version"],

  "definitions": {
    "sources": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {"const": "source"},
          "name": {"type": "string"},
          "link": {"type": "string"},
          "page": {"type": "integer"}
        },
        "required": ["type", "name"]
      }
    },
    "trait": {
      "type": "object",
      "properties": {
        "type": {"const": "stat_block_section"},
        "subtype": {"const": "trait"},
        "name": {"type": "string"},
        "game-obj": {"type": "string"},
        "aonid": {"type": "integer"}
      },
      "required": ["type", "subtype", "name"]
    }
  }
}
```

### Common Schema Patterns

#### Enumerations
- **Purpose:** Strict type control
- **Example:** `"enum": ["ability", "feat", "spell"]`

#### References
- **Purpose:** Reusable definitions
- **Example:** `"$ref": "#/definitions/trait"`

#### Required Fields
- **Purpose:** Data integrity
- **Example:** `"required": ["name", "type", "sources"]`

#### Version Tracking
- **Purpose:** Schema evolution
- **Field:** `"schema_version": 1.2`

### Validation

```python
from pfsrd2.schema import validate_against_schema

if not options.skip_schema:
    struct['schema_version'] = 1.2
    validate_against_schema(struct, "monster_ability.schema.json")
```

Validation catches:
- Missing required fields
- Wrong field types
- Invalid enum values
- Schema violations

## Error Handling Patterns

### Assertion-Based Validation

Use assertions to enforce invariants:

```python
assert len(rest) == 0, "More sections than expected (1)"
assert data, "%s | %s" % (data, trait)
assert current in addon_names, "%s, %s" % (current, addon_names)
```

**Assertions provide:**
- Fail-fast behavior
- Clear error messages with context
- Immediate feedback during development

### Defensive Checks

Check before accessing:

```python
if 'text' not in section:
    return

if not children:
    return

children = [c for c in children if str(c).strip() != '']
```

### Error Context

Include context in error messages:

```python
assert trait['link']['aonid'] == db_trait['aonid'], \
    "%s : %s" % (trait, db_trait)
```

**Good error messages include:**
- What failed
- Expected vs actual values
- Context (variable contents, file being processed)

### When to Catch Exceptions

**Only catch when:**
1. You know exactly what the problem is
2. You can handle it correctly for 100% of cases
3. The exception represents expected behavior (not a bug)

**Example - Acceptable catch:**
```python
try:
    ability_score = int(stat_text.strip())
except ValueError:
    # Known case: creatures can have "-" for missing scores
    # We handle this 100% correctly by setting to None
    ability_score = None
```

**Example - Bad catch:**
```python
try:
    parse_creature_stats(html)
except Exception:
    pass  # Silent failure - we don't know what went wrong!
```

## Markdown Conversion

### Custom Markdown Converter

```python
from markdownify import MarkdownConverter

class PFSRDConverter(MarkdownConverter):
    """Custom converter for PFSRD HTML to Markdown"""

    def convert_span(self, el, text, convert_as_inline):
        """Convert action icons to text symbols"""
        if not el.has_attr('title'):
            return text

        match el["title"]:
            case "Reaction":
                return "[@]"
            case "Free Action":
                return "[-]"
            case "Single Action":
                return "[#]"
            case "Two Actions":
                return "[##]"
            case "Three Actions":
                return "[###]"
            case _:
                return text

    def convert_a(self, el, text, convert_as_inline):
        """Convert links to markdown links"""
        href = el.get('href', '')
        return f"[{text}]({href})"

def markdown_pass(struct, name, path):
    """Convert HTML to markdown throughout structure"""

    def _validate_acceptable_tags(text):
        """Ensure only safe tags remain"""
        validset = set(['i', 'b', 'u', 'strong', 'ol', 'ul', 'li', 'br'])
        tags = get_unique_tag_set(text)
        assert tags.issubset(validset), \
            "%s : %s - %s" % (name, text, tags)

    def _convert_field(field, parent):
        if 'text' not in field:
            return

        text = field['text']

        # Convert to markdown
        md = PFSRDConverter().convert(text)

        # Store both versions
        field['text'] = md
        field['html'] = text

        # Validate remaining HTML
        _validate_acceptable_tags(text)

    walk(struct, lambda f, p: 'text' in f, _convert_field)
```

## File Output

### Directory Structure

```
pfsrd2-data/
├── monsters/
│   ├── Core_Rulebook/
│   │   ├── Goblin_Warrior.json
│   │   └── Orc_Brute.json
│   └── Bestiary_2/
│       └── Dragon_Turtle.json
├── monster_abilities/
│   └── Core_Rulebook/
│       ├── Grab.json
│       └── Swallow_Whole.json
├── traits/
│   └── Core_Rulebook/
│       ├── Fire.json
│       └── Evil.json
└── conditions/
    └── Core_Rulebook/
        ├── Frightened.json
        └── Stunned.json
```

### Output Pattern

```python
def write_creature(jsondir, struct, name):
    """Write structured data to JSON file"""
    filename = os.path.join(jsondir, name + '.json')

    with open(filename, 'w') as f:
        json.dump(struct, f, indent=2, sort_keys=False)

# Usage in parser
if not options.dryrun:
    output = options.output
    for source in struct['sources']:
        source_name = char_replace(source['name'])
        jsondir = makedirs(output, 'monster_abilities', source_name)
        write_creature(jsondir, struct, char_replace(struct['name']))
```

### File Naming

```python
def char_replace(text):
    """Sanitize text for use in filenames"""
    # Replace problematic characters
    replacements = {
        '/': '_',
        '\\': '_',
        ':': '_',
        '*': '_',
        '?': '_',
        '"': '_',
        '<': '_',
        '>': '_',
        '|': '_',
        ' ': '_'
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove duplicate underscores
    while '__' in text:
        text = text.replace('__', '_')

    return text.strip('_')
```

## Advanced Parsing Patterns

The following patterns are used in complex parsers like `creatures.py` for handling sophisticated parsing requirements. These patterns go beyond the basic techniques and represent advanced parsing strategies.

### Stateful Parsing Patterns

#### Tuple-Based Intermediate Representation

Complex parsers use a two-phase strategy: collect data as tuples, then transform into structured objects.

**Pattern from creatures.py:**
```python
def creature_stat_block_pass():
    """Phase 1: Collect data as tuples"""
    data = []  # List of (key, value, link, action) tuples
    key = None
    value = []
    link = None
    action = None

    def add_to_data(key, value, data, link, action):
        if key:
            data.append((
                key.strip(),
                "".join([str(v) for v in value]).strip(),
                link,
                action
            ))
            key = None
            value = []
            link = None
            action = None
        return key, value, data, link, action

    # Scan HTML accumulating tuples
    for obj in objs:
        if obj.name == "br":
            # Line break signals end of current item
            key, value, data, link, action = add_to_data(
                key, value, data, link, action
            )
        elif obj.name == "b":
            # Bold text = new key
            key = get_text(obj)
            if obj.a:
                _, link = extract_link(obj.a)
        else:
            # Regular content = value
            value.append(obj)

    # Phase 2: Transform tuples into structured objects
    for key, value, link, action in data:
        process_stat_entry(key, value, link, action)
```

**Why use this pattern:**
- Handles incomplete/ambiguous data during initial scan
- Allows reordering or filtering before final transformation
- Separates scanning logic from structure building
- Useful when HTML structure doesn't directly map to output structure

#### Sequential Consumption with State

For ordered data like creature stat blocks, consume sections sequentially using pop():

```python
def process_stat_block(sb, sections):
    """Process three-section stat block: Stats/Defense/Offense"""

    # Stats section (first)
    stats = sections.pop(0)
    sb["senses"] = process_senses(stats.pop(0))
    sb["statistics"] = process_statistics(stats)

    # Defense section (second)
    defense = sections.pop(0)
    sb["defense"]["ac"] = process_ac(defense.pop(0))
    sb["defense"]["saves"] = process_saves(
        defense.pop(0), defense.pop(0), defense.pop(0)
    )

    # Offense section (third)
    offense = sections.pop(0)
    sb["offense"]["speed"] = process_speed(offense.pop(0))
```

**Key aspects:**
- Strict ordering assumptions (Stats, Defense, Offense)
- Stateful consumption (each pop() advances position)
- Sequential processing with known structure
- Defensive assertions to catch structure violations

#### Lookahead-Based Optional Field Processing

Handle optional fields by peeking at the next item before consuming:

```python
def process_defense(defense):
    """Process defense section with optional fields"""

    # Required fields
    ac = defense.pop(0)
    saves = [defense.pop(0), defense.pop(0), defense.pop(0)]
    hp = defense.pop(0)

    # Optional fields - check before consuming
    if len(defense) > 0 and defense[0][0] == "Hardness":
        hardness = defense.pop(0)

    if len(defense) > 0 and defense[0][0] == "Immunities":
        immunities = defense.pop(0)

    if len(defense) > 0 and defense[0][0] == "Resistances":
        resistances = defense.pop(0)

    if len(defense) > 0 and defense[0][0] == "Weaknesses":
        weaknesses = defense.pop(0)

    # Process remaining items (defensive abilities)
    while len(defense) > 0:
        process_defensive_ability(defense.pop(0))
```

**Pattern:**
1. Check if more data exists: `len(defense) > 0`
2. Peek at next field name: `defense[0][0]`
3. Conditionally consume if match: `defense.pop(0)`
4. Continue with remaining items

### Split and Repair Strategies

#### Rebuilding Split Parenthetical Content

When splitting on delimiters breaks semantic units (like parentheses), repair them:

```python
def rebuilt_split_modifiers(parts):
    """
    Recombines parts that were incorrectly split across parentheses

    Input:  ["skill +10 (bonus", "modifier)", "another +5"]
    Output: ["skill +10 (bonus, modifier)", "another +5"]
    """
    newparts = []
    while len(parts) > 0:
        part = parts.pop(0)

        if part.find("(") > 0:
            # Opening paren found
            newpart = part

            # Keep consuming until closing paren
            while newpart.find(")") == -1:
                newpart = newpart + ", " + parts.pop(0)

            newparts.append(newpart)
        else:
            # No paren issue
            newparts.append(part)

    return newparts
```

**Usage:**
```python
# Naive split breaks parentheses
parts = text.split(",")
# ["Perception +15 (low-light vision", "darkvision)", "Athletics +10"]

# Repair the split
parts = rebuilt_split_modifiers(parts)
# ["Perception +15 (low-light vision, darkvision)", "Athletics +10"]
```

**When to use:**
- After splitting on commas/semicolons
- When parenthetical content may contain the delimiter
- For skill modifiers, spell lists, ability text

### Polymorphic Parsing Dispatch

#### Content-Based Type Detection

Determine what parser to use by inspecting content:

```python
def process_offensive_action(section):
    """Route to appropriate parser based on content analysis"""

    # Check name for exact matches
    if section["name"] in ["Melee", "Ranged"]:
        section["offensive_action_type"] = "attack"
        return parse_attack_action(section, section["name"].lower())

    # Check name patterns
    name_parts = section["name"].split(" ")
    if "Spells" in name_parts or section["name"].endswith("Rituals"):
        section["offensive_action_type"] = "spells"
        return parse_spells(section)

    # Check against exclusion list
    if section['name'] in constants.CREATURE_NOT_SPELLS:
        section["offensive_action_type"] = "ability"
        return parse_offensive_ability(section)

    # Inspect text for structural markers
    bs = BeautifulSoup(section["text"], "html.parser")
    titles = [get_text(b) for b in bs.findAll("b")]

    if "Saving Throw" in titles or "Stage 1" in titles:
        section["offensive_action_type"] = "affliction"
        return parse_affliction(section)

    # Default case
    section["offensive_action_type"] = "ability"
    return parse_offensive_ability(section)
```

**Detection strategies:**
- Exact name matching
- Name pattern matching
- Exclusion lists
- Text content inspection
- Structural marker detection

#### Format-Based Polymorphic Parsing

Same function returns different structures based on format detection:

```python
def parse_attack_damage(text):
    """Parse damage - returns different structure for dice vs effects"""

    damages = []
    for d in text.split(" plus "):
        damage = {"type": "stat_block_section", "subtype": "attack_damage"}
        parts = d.split(" ")
        dice = parts.pop(0).strip()

        # Try to match dice pattern: 2d6, 1d8+5, etc.
        m = re.match(r"^\d*d\d*.?[0-9]*?$", dice)
        if not m:
            # Try to match plain number: 10
            m = re.match(r"^\d*$", dice)

        if m:
            # It's numeric damage
            damage["formula"] = dice.replace("–", "-")
            damage_type = " ".join(parts)

            # Extract modifiers
            if damage_type.startswith("persistent"):
                damage_type = damage_type.replace("persistent ", "")
                damage["persistent"] = True

            damage["damage_type"] = damage_type
        else:
            # It's an effect, not numeric damage
            parts.insert(0, dice)
            damage["effect"] = " ".join(parts)

        damages.append(damage)

    return damages
```

**Example inputs and outputs:**
```python
# Dice damage
"2d6+10 bludgeoning"
→ [{"formula": "2d6+10", "damage_type": "bludgeoning"}]

# Multiple damage types
"2d6 fire plus 1d6 evil"
→ [{"formula": "2d6", "damage_type": "fire"},
    {"formula": "1d6", "damage_type": "evil"}]

# Effect (not damage)
"see Sphere of Oblivion"
→ [{"effect": "see Sphere of Oblivion"}]
```

### Progressive Extraction Patterns

#### Stacked Modifier Extraction

Extract multiple modifiers/flags sequentially:

```python
def parse_spell_list(part):
    """
    Handle stacked modifiers: Constant (6th) or Cantrips (3rd)
    """
    spell_list = {"type": "stat_block_section", "subtype": "spell_list"}
    bs = BeautifulSoup(part, "html.parser")

    if bs.b:
        # Extract first modifier
        level_text = get_text(bs.b.extract())

        # Check if it's a flag, extract next if so
        if level_text == "Constant":
            spell_list["constant"] = True
            level_text = get_text(bs.b.extract())  # Get next bold

        # Check for second flag
        if level_text == "Cantrips":
            spell_list["cantrips"] = True
            level_text = get_text(bs.b.extract())  # Get next bold

        # Now parse the actual level
        m = re.match(r"^\(?(\d*)[snrt][tdh]\)?$", level_text)
        spell_list["level"] = int(m.groups()[0])

    # Continue with spell parsing...
    return spell_list
```

**Handles:**
- `"3rd cone of cold"` → level 3
- `"Cantrips (5th) detect magic"` → level 5, cantrips=true
- `"Constant (6th) true seeing"` → level 6, constant=true

#### Progressive Regex Matching with Fallbacks

Try specific patterns first, fall back to simpler ones:

```python
def parse_attack_action(section):
    """Parse attack with progressive regex matching"""
    text = section["text"]

    # Try pattern with traits first (most specific)
    m = re.search(
        r"^(.*) ([+-]\d*) \[(.*)\] \((.*)\), (.*)$",
        text
    )

    if not m:
        # Fall back to pattern without traits
        m = re.search(
            r"^(.*) ([+-]\d*) \[(.*)\], (.*)$",
            text
        )

    assert m, "Failed to parse: %s" % (text)

    # Extract matched groups
    attack_data = list(m.groups())
    # ... process attack_data
```

**Pattern progression:**
1. Try most specific: `weapon +bonus [MAP] (traits), Damage`
2. Fall back to simpler: `weapon +bonus [MAP], Damage`
3. Assert if no pattern matches

### Trait-Driven Parsing

#### Semantic Extraction Based on Trait Context

When a trait indicates special semantics, trigger custom extraction:

```python
def handle_aura(ability):
    """Extract aura mechanics when 'aura' trait is present"""

    # Check for aura trait
    found = False
    if "traits" in ability:
        for trait in ability["traits"]:
            if trait["name"] == "aura":
                found = True
                break

    if not found or "text" not in ability:
        return

    # Check if first sentence contains aura stats
    parts = ability["text"].split(".")
    first_sentence = parts[0]

    if not _test_aura(first_sentence):
        return

    # Extract structured data from first sentence
    test_parts = split_maintain_parens(first_sentence, ",")

    while test_parts:
        part = test_parts.pop(0)

        if "DC" in part:
            # Extract saving throw
            save = universal_handle_save_dc(part.strip())
            ability["saving_throw"] = save

        elif "feet" in part or "miles" in part:
            # Extract range
            range = universal_handle_range(part.strip())
            ability["range"] = range

        elif "damage" in part:
            # Extract damage
            damage = parse_attack_damage(part)
            ability["damage"] = damage

    # Remove processed sentence from text
    parts.pop(0)
    ability["text"] = ".".join(parts).strip()

def _test_aura(text):
    """Detect if text contains aura statistics"""
    return any([
        "damage" in text,
        "DC" in text,
        "feet" in text,
        "miles" in text
    ])
```

**Example:**
- Input: Ability with `aura` trait and text `"30 feet, DC 25 Will; The creature emits..."`
- Output: Extracts `range: {value: 30, unit: "feet"}`, `saving_throw: {dc: 25, type: "Will"}`, removes from text

**Key aspects:**
- Trait presence enables special logic
- Semantic understanding based on game rules
- Automatic field extraction
- Text modification (removes extracted parts)

### Complex Text Reconstruction

#### Context-Sensitive Text Splitting

Different splitting strategies based on content markers:

```python
def _handle_requirements(section, text):
    """Extract Requirements from mixed text"""

    if "Requirements" not in text:
        return text

    if "Effect" in text:
        # Split on Effect
        parts = text.split("Effect")
        assert len(parts) == 2, text

        text = parts.pop()  # Text after Effect
        requirements = parts.pop()  # Text before Effect

        # Clean up HTML tags
        assert text.startswith("</b>"), text
        requirements += "</b>"
        text = text[4:].strip()
    else:
        # No Effect, split on Requirements tag
        parts = text.split("<b>Requirements</b>")
        assert len(parts) == 2, text

        requirements = "<b>Requirements</b>" + parts.pop()
        text = parts.pop()

    # Clean requirements text
    bs = BeautifulSoup(requirements, "html.parser")
    for b in bs.findAll('b'):
        b.extract()

    requirements = get_text(bs).strip()
    if requirements.endswith(";"):
        requirements = requirements[:-1]

    section['requirement'] = requirements
    return text
```

**Handles:**
- `"Requirements shield; Effect gain +2"` → separate requirement and effect
- `"Requirements wielding weapon"` → just requirement
- Mixed HTML and text content
- Trailing punctuation cleanup

### Nested HTML Structure Navigation

#### Hierarchical Structure with Assertions

Navigate complex nested HTML with structural expectations:

```python
def parse_mythic_ability(parent_section):
    """Parse mythic ability with nested list structure"""
    text = parent_section["text"]
    bs = BeautifulSoup(text, "html.parser")
    children = list(bs.children)

    # Assert expected structure
    assert len(children) == 2, "Expected 2 children"

    # First child: points text (NavigableString)
    obj = children[0]
    assert obj.__class__ == NavigableString, "Expected string"
    point_text = str(obj)
    assert "Mythic Points" in point_text

    mythic_ability = {
        "type": "stat_block_section",
        "subtype": "mythic_ability",
        "name": parent_section["name"],
        "mythic_points": int(point_text.split(" ")[0].strip()),
        "mythic_activations": []
    }

    # Second child: <ul> list
    ul = children[1]
    assert ul.name == "ul", "Expected <ul>"

    # Process each <li> as activation
    for li in ul.find_all("li"):
        cont = list(li.contents)
        assert is_tag_named(cont[0], ['i', 'b']), "Expected italic or bold"

        title = get_text(cont.pop(0))
        activation_text = ''.join([str(c) for c in cont])

        activation = _parse_mythic_activation(title, activation_text)
        mythic_ability["mythic_activations"].append(activation)

    return mythic_ability
```

**Pattern:**
- Assert structure at each level
- Navigate by position when structure is known
- Validate types (NavigableString vs Tag)
- Recursively process nested elements
- Build hierarchical objects

### When to Use Advanced Patterns

**Use stateful parsing when:**
- Data has strict ordering requirements
- You need to consume items sequentially
- Optional fields need lookahead
- Building intermediate representations

**Use split-and-repair when:**
- Delimiters appear inside semantic units
- Parentheses contain the delimiter
- Need to preserve grouping after split

**Use polymorphic dispatch when:**
- Same structure can represent different types
- Type depends on content inspection
- Multiple specialized parsers exist
- Need format detection before parsing

**Use progressive extraction when:**
- Multiple optional modifiers can stack
- Need to peel off layers of prefixes
- Flags and values are intermixed

**Use trait-driven parsing when:**
- Traits indicate semantic meaning
- Game rules enable special extraction
- Text structure follows trait conventions

**Use nested navigation when:**
- HTML structure is complex and predictable
- Can assert structural expectations
- Need to extract from specific positions
- Building hierarchical objects

## Design Philosophy: Strict Validation Over Graceful Degradation

### Core Principle: Catch Errors, Don't Hide Them

The PFSRD2-Parser makes a **deliberate design choice** to fail fast and loudly rather than attempt graceful degradation. This is not accidental brittleness - it's a design decision that serves the core goal of data quality.

### The Problem: Source HTML Contains Bugs

Archives of Nethys (AoN) is hand-maintained and can contain:
- **HTML structural bugs** - Malformed tags, missing elements, broken nesting
- **Data corruption** - Missing stat block sections, deleted content, incomplete entries
- **Inconsistencies** - Same entity type with varying HTML structure

### Goal: Surface Errors Immediately

The fail-fast, assertion-heavy approach ensures:

✅ **AoN HTML bugs are immediately visible**
- Malformed HTML causes instant failure with clear error
- Error log identifies problematic files
- Human can investigate and fix

✅ **Data corruption is caught before output**
- Missing sections trigger assertions
- Incomplete stat blocks fail parsing
- No partial/incorrect data in output

✅ **Nothing silently produces wrong data**
- No guessing at missing fields
- No defaulting to empty values
- No "best effort" parsing

✅ **Error location is obvious**
- Assertions show exactly what failed
- Stack trace points to parsing logic
- Context provided for debugging

✅ **Forces fixing root cause**
- Can't ship bad data
- Must address source issue
- Either fix HTML or update parser

### Why Graceful Degradation Would Be Wrong

Alternative approach (try to be "robust" with fallbacks and defaults):

❌ **AoN bugs might go unnoticed**
- Parser silently works around issues
- Bad HTML gets committed to repository
- Problem discovered much later (if at all)

❌ **Data corruption silently propagates**
- Missing defense section → output creature with no defenses
- Deleted ability → no error, just missing from output
- Users get incomplete game data

❌ **Wrong data is worse than no data**
- For a game system reference, correctness is paramount
- Players rely on accurate stats for gameplay
- Incorrect AC or HP breaks game balance
- Missing abilities changes encounter difficulty

❌ **Debugging becomes detective work**
- "Why does this creature have no saves?"
- "When did this ability disappear?"
- "Is this field supposed to be empty?"

❌ **Quality degrades over time**
- Small issues accumulate
- Hard to distinguish bugs from features
- Technical debt grows

### Example: AoN Bug Caught by Parser

**Scenario:** AoN accidentally deletes the defense section from a creature's HTML.

**With fail-fast (current approach):**
```python
def process_stat_block(sections):
    stats = sections.pop(0)
    defense = sections.pop(0)  # ← Fails here with IndexError
    offense = sections.pop(0)

# Result:
# ✅ Parser immediately fails
# ✅ Error: list index out of range
# ✅ Error log identifies creature file
# ✅ Human investigates HTML
# ✅ Discovers missing defense section
# ✅ Fix in pfsrd2-web or report to AoN
# ✅ Reprocess only that creature
```

**With graceful degradation:**
```python
def process_stat_block(sections):
    stats = sections.pop(0) if sections else {}
    defense = sections.pop(0) if sections else {}  # Silently defaults
    offense = sections.pop(0) if sections else {}

# Result:
# ❌ Parser succeeds
# ❌ Outputs creature with empty defense
# ❌ Wrong data committed to pfsrd2-data
# ❌ Users get creature with AC 0, no saves, no HP
# ❌ Problem noticed later (maybe)
# ❌ Hard to trace back to source
```

### HTML Coupling is Inherent

You **cannot parse HTML without coupling to its structure**. This is the nature of the problem:

- Any HTML parser must make assumptions about structure
- BeautifulSoup, lxml, or any tool faces this
- Structural changes will break parsing - unavoidable
- But fixes are typically localized (1-2 spots in code)

### When AoN Changes Structure

**Large structural changes:**
- Parser fails loudly and obviously (this is good!)
- Fix is typically in one or two places
- Error logs show which files are affected
- Reprocess only affected entities

**Example:** AoN changes creature format to add new optional section
```python
# Before: Stats, Defense, Offense
# After: Stats, Defense, Offense, Variants

# Parser fails at:
assert len(sections) == 3  # Now there are 4

# Fix:
# Option 1: Handle variants section
if len(sections) == 4:
    variants = sections.pop()
else:
    variants = None

# Option 2: Assert on minimum
assert len(sections) >= 3, f"Expected at least 3 sections, got {len(sections)}"
```

**Small changes (new optional fields):**
- May or may not break depending on change
- Assertions make expectations explicit
- Easy to add handling for new optional content

### Assertion Best Practices

Current approach is correct, but assertions can provide better context:

```python
# Minimal: Just checks condition
assert len(children) == 2, "Expected 2 children"

# Better: Provides context for debugging
if len(children) != 2:
    raise ParseError(
        f"Mythic ability expects 2 children (text + list), got {len(children)}\n"
        f"Children types: {[type(c).__name__ for c in children]}\n"
        f"Content preview: {text[:200]}...\n"
        f"This usually means AoN HTML structure changed or has a bug.\n"
        f"Check the source HTML file for structural issues."
    )

# Even better: Include file context (when available)
if len(children) != 2:
    raise ParseError(
        f"Mythic ability parsing failed in {filename}\n"
        f"Expected: 2 children (text + list)\n"
        f"Got: {len(children)} children\n"
        f"Types: {[type(c).__name__ for c in children]}\n"
        f"This indicates HTML structure issue - check source file."
    )
```

### When Strict Validation is Appropriate

**Use fail-fast with assertions when:**
- ✅ Data quality is paramount (like game system reference)
- ✅ Wrong data is worse than no data
- ✅ Source data can contain bugs
- ✅ Human review of errors is feasible
- ✅ Batch processing allows reprocessing
- ✅ Error logs enable targeted fixes

**Don't use fail-fast when:**
- ❌ Serving live traffic (availability > perfection)
- ❌ Can't afford downtime
- ❌ Source is trusted and validated
- ❌ Partial data is better than no data
- ❌ No human review possible

For PFSRD2-Parser, fail-fast is the **correct choice**.

### Key Takeaways

1. **Brittleness is a feature** - It catches errors before they become bad data
2. **HTML coupling is inherent** - Can't parse without structure assumptions
3. **Wrong data is worse than no data** - For reference material, correctness matters
4. **Fail-fast enables quality** - Forces addressing root causes
5. **Error visibility is critical** - Silent failures are dangerous

This design philosophy ensures the PFSRD2-Parser produces **correct, validated data** rather than **silently wrong data**.

## Testing Strategy

### Data-Driven Regression Testing

The PFSRD2-Parser uses a **sophisticated data-driven testing approach** where the actual dataset serves as the comprehensive test suite. This is the primary validation method for parser correctness.

### How It Works

```bash
# 1. Make changes to parser
vim pfsrd2/creatures.py

# 2. Progressive validation
./pf2_creature_parse goblin_warrior.html    # Simple case (seconds)
./pf2_run_creatures.sh -n 100                # First 100 (minutes)
./pf2_run_creatures.sh                       # Full dataset (hours)

# 3. Check what changed
cd ../pfsrd2-data
git diff monsters/

# 4. Validate changes
# - No diff = safe refactoring ✓
# - Small diff = investigate (bug fix or regression?)
# - Large unexpected diff = broke something
```

### Why This Approach Works

**Strengths of data-driven testing:**

✅ **Real-world validation** - Tests against actual HTML from Archives of Nethys, not synthetic fixtures
✅ **Comprehensive coverage** - Every entity in the dataset is a test case
✅ **No maintenance burden** - Data evolves naturally, no test fixtures to update
✅ **Git provides diffing** - Visual validation of what changed
✅ **Progressive validation** - Fast inner loop for simple cases, full validation when needed
✅ **Tests full pipeline** - Validates entire parsing flow, not just isolated units
✅ **Catches edge cases** - Real data includes all the weird corner cases

This is similar to how **compilers are tested** - while you have unit tests for components, the ultimate test is "does it correctly compile real programs?"

### Complementary Unit Testing

While data-driven testing validates full parsers excellently, **unit tests add value for reusable components:**

#### High Value: Extraction Helper Tests

When you create common extraction primitives (like `extract_labeled_fields()`), unit tests enable fast iteration:

```python
# tests/test_extractors.py
def test_extract_labeled_fields():
    """Test generic addon extractor - runs in milliseconds"""
    html = "<b>Frequency</b> once per day; <b>Trigger</b> hit by attack"
    result = extract_labeled_fields(html, ['Frequency', 'Trigger'])

    assert result['frequency'] == "once per day"
    assert result['trigger'] == "hit by attack"

def test_split_maintain_parens():
    """Test parentheses-aware splitting"""
    text = "skill +10 (bonus, modifier), another +5"
    result = split_maintain_parens(text, ",")

    assert len(result) == 2
    assert result[0] == "skill +10 (bonus, modifier)"

def test_extract_action_type():
    """Test action type extraction"""
    html = '<span title="Single Action">[#]</span> Strike'
    text, action = extract_action_type(html)

    assert action['name'] == 'single_action'
    assert '[#]' not in text
```

**Benefits:**
- **Fast feedback loop** - Milliseconds vs hours for full dataset
- **Isolated testing** - Test helper in isolation
- **Documentation** - Shows how helper is meant to be used
- **Confident refactoring** - Can change helper knowing tests will catch breaks

**Workflow for creating helpers:**
1. Create helper function
2. Validate with data-driven testing (run on full dataset)
3. Add unit tests for helper
4. Now can refactor helper with fast feedback
5. Use helper in multiple parsers with confidence

#### Medium Value: Edge Case Documentation

Unit tests can document edge cases not well-represented in current dataset:

```python
def test_attack_damage_edge_cases():
    """Document tricky parsing scenarios"""

    # Persistent damage with parenthetical note
    result = parse_attack_damage("3d6 persistent fire (from ghost touch)")
    assert result[0]['persistent'] == True
    assert result[0]['notes'] == "from ghost touch"

    # Effect instead of damage
    result = parse_attack_damage("see Sphere of Oblivion")
    assert 'formula' not in result[0]
    assert result[0]['effect'] == "see Sphere of Oblivion"

    # Complex stacking
    result = parse_attack_damage("2d6 fire plus 1d6 evil plus 1d4 persistent bleed")
    assert len(result) == 3
    assert result[2]['persistent'] == True
```

**Benefits:**
- Documents tricky behaviors
- Catches regressions in edge cases
- Serves as specification

#### Low Value: Full Parser Unit Tests

**Don't unit test full parsers** - data-driven testing already provides this effectively.

Testing full parsers with fixtures would:
- ❌ Be redundant with data-driven testing
- ❌ Require maintaining fixture files
- ❌ Be less comprehensive than real dataset
- ❌ Add maintenance burden

The data-driven approach is **superior for full parser validation**.

### Hybrid Testing Strategy

```
┌─────────────────────────────────────────────────┐
│  Unit Tests (seconds)                           │
│  - Extraction helper functions                  │
│  - Regex pattern matchers                       │
│  - Utility functions                            │
│  - Edge case documentation                      │
│  Purpose: Fast inner loop for helpers           │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Progressive Data Testing (minutes to hours)    │
│  1. Simple case: goblin_warrior.html            │
│  2. First 100 creatures                         │
│  3. Full dataset (1000+ entities)               │
│  Purpose: Real-world validation                 │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Git Diff Review                                │
│  - No change: safe refactoring ✓                │
│  - Expected change: feature working ✓           │
│  - Unexpected change: investigate               │
│  Purpose: Ultimate arbiter of correctness       │
└─────────────────────────────────────────────────┘
```

### When to Use Each Approach

**Use data-driven testing for:**
- ✅ Full parser validation
- ✅ Regression detection
- ✅ Validating refactoring didn't break anything
- ✅ Verifying new features work across all data

**Use unit tests for:**
- ✅ Extraction helper functions
- ✅ Utility functions (split, parse, extract)
- ✅ Regex pattern matchers
- ✅ Edge case documentation
- ✅ Fast iteration when refactoring helpers

**Don't use unit tests for:**
- ❌ Full parser validation (use data-driven testing)
- ❌ Testing against fixture HTML (use real data)
- ❌ Integration testing (data-driven testing covers this)

### Test Organization

If you add unit tests for helpers:

```
tests/
├── test_extractors.py     # Extraction helper tests
├── test_utils.py          # Utility function tests
├── test_patterns.py       # Regex pattern tests
└── test_edge_cases.py     # Edge case documentation
```

**Don't create:**
- ❌ `fixtures/` directory with sample HTML
- ❌ `test_creatures.py` for full creature parsing
- ❌ Integration tests (data-driven testing provides this)

### Key Principles

1. **Data is the test suite** - Real dataset provides comprehensive validation
2. **Git diff is the arbiter** - Visual validation of what changed
3. **Progressive validation** - Fast inner loop for simple cases
4. **Unit tests for helpers only** - Not for full parsers
5. **Fast iteration on utilities** - Unit tests enable refactoring helpers
6. **No fixture maintenance** - Avoid maintaining synthetic test data

This testing strategy is **sophisticated and appropriate** for a data curation tool that processes hand-maintained HTML from a relatively stable source.

## Best Practices

### 1. Immutable Transformations
Each pass should be clear about what it modifies:
```python
def section_pass(struct):
    """Modifies struct in place"""
    # Clear what's being changed
```

### 2. Early Validation
Use assertions throughout processing:
```python
assert len(sections) > 0, "Expected at least one section"
assert 'name' in struct, "Missing required name field"
```

### 3. Logging
Log progress to stderr:
```python
if not options.stdout:
    sys.stderr.write("%s\n" % basename)
```

### 4. Version Tracking
Always include schema version:
```python
struct['schema_version'] = 1.2
```

### 5. Reference Data
Use database for consistency:
```python
trait_db_pass(struct)  # Enrich from canonical source
```

### 6. Defensive Programming
Check existence before access:
```python
text = section.get('text', '')
if 'sections' not in section:
    return
```

### 7. Clear Naming
Functions describe their purpose:
```python
def extract_action_type(text):
def _handle_source(section):
def _clear_garbage(section):
```

### 8. Modularity
Small, focused functions:
```python
def section_pass(struct):
    _fix_name(struct)
    _handle_source(struct)
    _handle_traits(struct)
    _clear_links(struct)
```

### 9. Documentation
Comments for complex logic:
```python
# Reorder children to process hr separator first
# This handles the common pattern where mechanics
# are listed after a horizontal rule
```

### 10. Testing Support
Options for development:
```python
if options.stdout:
    print(json.dumps(struct, indent=2))
if options.dryrun:
    # Skip file writing
```

## Design Principles

### Separation of Concerns

- **Universal** - Game-system agnostic logic
- **Game-specific** - PF2e, PF1e, Starfinder rules
- **SQL** - Database operations isolated
- **Schema** - Validation separated from transformation

### Reusability

- Common passes shared across entity types
- Helper functions extracted to utilities
- Database operations abstracted
- Markdown conversion centralized

### Extensibility

- New passes can be added to pipeline
- Database versioning supports evolution
- Schema validation catches breaking changes
- Constants file for configuration

### Data Integrity

- Schema validation ensures correctness
- Database provides canonical data
- Assertions catch invariant violations
- Version tracking enables migration

### Progressive Enhancement

- Start with basic structure
- Iteratively extract mechanics
- One-off cases can remain in text
- Common patterns become structured

This architecture provides a robust, maintainable system for parsing complex structured game data from HTML into validated JSON, with excellent separation of concerns and reusability across different game systems.
