# PFSRD2-Parser Developer Guide

## Issue Tracking

This project uses **beads** for issue tracking. The beads database is located at:

```
/home/devon/MasterworkTools/pfsrd2/.beads/
```

To create issues for this project, run `bd` commands from `/home/devon/MasterworkTools/pfsrd2/` or any subdirectory (like `PFSRD2-Parser/`).

## Project Mission

The goal of this project is to **express every aspect of the game system mechanics** available in the source HTML files through a **discrete, structured schema**.

### Structured Data Over Text Blocks

We aim to extract game mechanics into structured JSON fields, not leave them buried in opaque text blocks. This allows:

- **Integration** - Other tools can programmatically access game mechanics
- **Discoverability** - The schema documents the full extent of data exposed
- **Validation** - Structured data can be validated against schemas
- **Querying** - Mechanics can be searched and filtered programmatically

### Iterative Extraction

We don't need to extract everything at once. Some details may remain in text:

- **One-off abilities** - A unique monster ability might have mechanics in its description text
- **Edge cases** - Uncommon mechanics that appear rarely
- **Complex narrative** - Flavor text intertwined with minor mechanical details

**The goal is to progressively pull out mechanics over time through iteration.** Each improvement makes more mechanical data available in structured form.

### What This Looks Like

**Bad - Opaque text block:**
```json
{
  "description": "The creature can make a Strike as a reaction when an enemy moves adjacent to it. This Strike deals an extra 2d6 damage."
}
```

**Good - Structured mechanics:**
```json
{
  "trigger": "enemy_moves_adjacent",
  "action_type": "reaction",
  "action": "Strike",
  "damage_bonus": {
    "dice": "2d6",
    "type": "untyped"
  },
  "description": "The creature can make a Strike as a reaction when an enemy moves adjacent to it."
}
```

The structured version exposes the mechanical components so tools can:
- Identify all reaction abilities
- Calculate expected damage
- Understand trigger conditions
- Generate tooltips or UI elements

## Technical/Architecture Philosophy

This section documents the technical philosophy and architectural principles that guide this project's design decisions.

### Unix Philosophy & Influences

- Deeply influenced by "The Art of Unix Programming" - this shaped the fundamental approach
- Unix philosophy: small tools, text interfaces, composability, processes over threads
- Heavy terminal user, bash/zsh expert
- Right tool for the job - pragmatic over dogmatic

### Code & Complexity

**Inherent complexity vs. accidental complexity:**
- Obsessively avoid accidental complexity
- Code bases under **~10k LOC** are in the realm a single human mind can fully understand
- Keep team codebases below this threshold, interface between teams via documented contracts
- **Working code has more value than most people believe** - allergic to rewrites, prefer evolution
- "Prototype before polishing" - get it working, measure, then optimize
- **"The next right thing" approach:** Deploy working solution first, analyze/optimize after. Prevents analysis paralysis while preserving improvement path.

### Architecture Principles

**Service Design:**
- Strong microservices advocate - small, focused services
- Loathes monoliths but recognizes they can sometimes be the right tool
- **Text is superior default** for inter-service communication
- Binary protocols are optimizations - only use when protocol is proven bottleneck
- Documented interfaces and contracts between teams/services

**Scale Patterns:**
- **Isolation prevents cascading failures:** infrastructure, system, and service isolation
- **Pull > Push:** avoid overwhelming systems, create natural backpressure
- **Async > Sync:** transform to asynchronous as early as possible
- **Orders of magnitude thinking:** solutions that work at 1M/hour fail at 100M/hour
- **Swimlanes/pods/shards:** partition for known capacity and fault containment
- **No cross-DC synchronous dependencies** for critical path
- **Local caching, data replication:** minimize bit travel distance

**The Virtuous Cycle:**
- Scalability → Availability → Performance → Scalability
- Each improvement enables the others

### Technology Selection Principles

- **Scale-appropriate tooling:** Don't use enterprise-grade distributed systems for problems that don't require them
- **Complexity budget:** Complex tools cost learning curve, operational overhead, lock-in - only spend when problem demands it
- **Resist cargo culting:** Popular/trendy ≠ appropriate for your context
- **Deep organizational knowledge compounds:** Team expertise in existing tools is a strategic asset
- **80% fit with known tech > 100% fit with new dependency**
- Justify new dependencies against: learning curve, operational overhead, lock-in, team skill depth, ongoing maintenance burden
- **"Revolutionary" = repackaged patterns:** Vendor claims of breakthrough innovation usually just cross-domain transfer of existing patterns. Look for what they're actually borrowing from.

**Concurrency & Communication:**
- Prefer **processes over threads**
- Prefer **queues over locks**
- Async message passing over shared state

**Object Orientation:**
- Dislikes OOP in most cases
- Prefers **procedural with good interfaces at service level** - less prone to bloat
- Composition over inheritance when OOP is necessary

### Language Selection Pattern

- Python for development speed, readability, most services
- Go for performance-critical paths
- Right tool for the job, not religious about it

### Response Approach for Technical Questions

**DO:**
- Question whether complexity is inherent or accidental
- Suggest simpler alternatives with trade-offs
- Call out when scale doesn't justify tool choice
- Consider failure modes and cascading failures
- Think about orders of magnitude changes
- Propose evolutionary changes over rewrites
- Use text/documented interfaces as default

**DON'T:**
- Assume latest/shiniest tech is best
- Propose rewrites when evolution is viable
- Over-engineer for scale that doesn't exist yet
- Suggest OOP inheritance hierarchies
- Recommend shared state over message passing
- Ignore the cost/complexity of adding new dependencies

**Key Questions to Ask:**
- What's the actual bottleneck? (measure first)
- What's the inherent vs. accidental complexity here?
- Can we evolve existing code instead of rewrite?
- Is this tool justified at current/projected scale?
- What are the failure modes?
- How does this fail at 10x scale? 100x?
- Can we do this with text interfaces first?
- What's the 80% solution using tech we already know?

### Architectural Review Lens

When describing a system or reviewing architecture:
1. Identify coupling points and failure domains
2. Look for synchronous dependencies that could be async
3. Question if scale justifies complexity of proposed tools
4. Suggest isolation strategies to prevent cascade
5. Consider the 10k LOC boundary - should this be multiple services?
6. Check if working code exists that could evolve vs. rewrite

## Architecture Documentation

**Before modifying parsers or adding new content types, read the comprehensive architecture guide:**

→ **[docs/architecture.md](docs/architecture.md)** - Complete parser architecture and design patterns

This document covers:
- Multi-stage pipeline architecture
- Pass-based processing patterns
- HTML extraction techniques
- Structured data extraction strategies
- Database integration patterns
- Schema usage and validation
- Helper functions and utilities
- Error handling patterns
- Best practices and design principles

**For adding new content types specifically:**

→ **[docs/adding-new-parser.md](docs/adding-new-parser.md)** - Step-by-step guide for new parsers

Understanding these patterns is essential for:
- Implementing new parsers correctly
- Following established conventions
- Extracting mechanics into structured fields
- Maintaining consistency across the codebase

**Before creating or modifying schemas:**

→ **[docs/schema-guide.md](docs/schema-guide.md)** - Schema consistency and design guide

This document covers:
- Standard definitions that MUST be identical across all schemas
- Top-level property conventions
- Field ordering and naming patterns
- Schema validation workflow
- Common mistakes to avoid
- When to increment schema versions

**Critical:** Standard definitions (link, source, section, license, etc.) must be copied exactly from existing schemas. Never modify them.

## Running the Code

All parser scripts must be run from inside the `bin/` directory:

```bash
cd PFSRD2-Parser/bin
```

Before running any parser, you must source the configuration:

```bash
source dir.conf
```

The `dir.conf` file sets up necessary environment variables that point to the web and data directories.

### Output Directory Handling

**You don't need to delete the data directory between runs.** The parsers overwrite existing JSON files automatically. This means:

```bash
# ❌ Not needed - wastes time
rm -rf ../../pfsrd2-data/shields
./pf2_run_equipment.sh shield

# ✅ Just run directly - files are overwritten
./pf2_run_equipment.sh shield
```

Exception: Only delete data directories when you need to ensure removed items are actually gone (e.g., testing deletion of deprecated content).

### Viewing Content on Archives of Nethys

To see how content renders on the actual website, you can construct URLs from file IDs:

**Pattern:** `https://2e.aonprd.com/<ContentType>.aspx?ID=<ID>&NoRedirect=1`

**Examples:**
- Armor ID 2: `https://2e.aonprd.com/Armor.aspx?ID=2&NoRedirect=1`
- Monster ID 123: `https://2e.aonprd.com/Monsters.aspx?ID=123&NoRedirect=1`
- Skill ID 5: `https://2e.aonprd.com/Skills.aspx?ID=5&NoRedirect=1`

The `&NoRedirect=1` parameter prevents redirects to remastered/legacy versions, showing the specific version you're parsing.

## Pipeline Architecture

Each shell script in `bin/` encodes a complete pipeline for parsing a single content type:

- `pf2_run_creatures.sh` - Creatures/monsters
- `pf2_run_npcs.sh` - NPCs
- `pf2_run_traits.sh` - Traits
- `pf2_run_conditions.sh` - Conditions
- `pf2_run_skills.sh` - Skills
- `pf2_run_monster_abilities.sh` - Monster abilities
- `pf2_run_sources.sh` - Source books
- `pf2_run_licenses.sh` - License information
- `pf2_run_armor.sh` - Armor

These pipelines process hundreds or thousands of files, so they can take significant time to complete.

## Error Handling and Recovery

### Error Logging

As pipelines run, errors are recorded in `bin/errors.*.log` files:

```
errors.pf2.monsters.log
errors.pf2.npcs.log
errors.pf2.conditions.log
```

### Reprocessing Failed Files

To reprocess only the files that failed:

1. Remove the `.log` extension from the error file:
   ```bash
   mv errors.pf2.monsters.log errors.pf2.monsters
   ```

2. Run the pipeline again:
   ```bash
   ./pf2_run_creatures.sh
   ```

The pipeline will now only process the files listed in the error file.

## Exception Handling Philosophy

**Fail Fast: Exceptions Should Propagate**

We intentionally let exceptions bubble up immediately rather than catching them. This is because:

1. **Faster debugging** - Immediate failures are easier to diagnose than silent errors
2. **Error log accuracy** - Failed files get logged for targeted reprocessing
3. **Clean recovery** - The error file reprocessing feature works best with fast failures

### When to Catch Exceptions

**Only catch exceptions when:**

1. You know **exactly** what the problem is
2. You can handle it correctly for **100% of cases**
3. The exception represents expected behavior (not a bug)

### When NOT to Catch

**Do NOT catch exceptions for:**

- Parsing edge cases you're unsure about
- HTML structure variations that might indicate bugs
- Cases where you're guessing at the right behavior
- Anything that should be investigated manually

**Example - Bad:**
```python
try:
    parse_creature_stats(html)
except Exception:
    pass  # Silent failure - we don't know what went wrong
```

**Example - Good:**
```python
# Let it fail fast - the error log will capture it
parse_creature_stats(html)
```

**Example - Acceptable catch:**
```python
try:
    ability_score = int(stat_text.strip())
except ValueError:
    # This is a known case: some creatures have "-" for missing scores
    # We handle this 100% correctly by setting to None
    ability_score = None
```

## Development Workflow: Start Simple, Iterate

When implementing a new parser, follow this proven workflow:

### 1. Look at Existing Parsers First

**Before writing any code, examine similar parsers:**
- Adding armor parser? Look at how creatures handle stat blocks
- Need edition detection? Check how traits or creatures do it
- Extracting bonus values? See how creatures handle AC/saves
- Building structured objects? Find examples in creature.schema.json

**Why:** Consistency matters. Reusing patterns means:
- Less debugging (patterns are already proven)
- Easier maintenance (everything works the same way)
- Better integration (consumers understand the patterns)

**Example workflow:**
```bash
# Need to add edition field to armor?
grep -r "edition" pfsrd2/*.py
# Find: creatures.py uses edition_pass()
# Copy that pattern exactly
```

### 2. Start Simple, Let Data Teach You

**Phase 1 - Basic extraction:**
- Get the name
- Extract a few obvious fields
- Run on ALL files
- See what breaks

**Phase 2 - Discovery:**
- Errors reveal edge cases
- Missing data shows new fields
- Assertions catch unknowns

**Phase 3 - Refactor:**
- Break large functions into helpers
- Add structured objects for mechanics
- Update schema

**Don't try to be perfect on the first pass.** Run early, run often, let failures guide you.

### 3. The Pass-Based Pipeline

Every parser follows the same pipeline pattern. Order matters:

```python
def parse_armor(filename, options):
    # 1. Extract from HTML
    details = parse_armor_html(filename)

    # 2. Build initial structure
    struct = restructure_armor_pass(details)

    # 3. Extract mechanics and content
    aon_pass(struct, basename)
    section_pass(struct)

    # 4. Restructure for output format
    restructure_pass(struct, "stat_block", find_stat_block)

    # 5. Normalize data types
    normalize_numeric_fields_pass(struct)

    # 6. Add metadata
    game_id_pass(struct)
    license_pass(struct)

    # 7. Format text content
    markdown_pass(struct, struct["name"], '')

    # 8. Determine edition BEFORE cleanup
    edition = edition_pass(struct['sections'])
    struct['edition'] = edition

    # 9. Clean up (must be last!)
    remove_empty_sections_pass(struct)

    # 10. Validate
    validate_against_schema(struct, "armor.schema.json")
```

**Critical ordering:**
- `edition_pass()` before `remove_empty_sections_pass()` (needs section structure intact)
- `normalize_numeric_fields_pass()` after text extraction (converts strings to objects)
- Schema validation last (catches all issues)

### 4. Test Incrementally

```bash
# Single file (fast feedback)
./pf2_armor_parse -o $PF2_DATA_DIR $PF2_WEB_DIR/Armor/Armor.aspx.ID_10.html

# Full pipeline (find all edge cases)
./pf2_run_armor.sh

# Check results
cat errors.pf2.armor.log
```

**Iterate quickly:** single file → fix → single file → fix → full pipeline

## Function Design Philosophy

### Optimize for Brittleness, Not Defensiveness

**Bad - Defensive programming that silently ignores unknowns:**
```python
# Only extract fields we know about, ignore everything else
known_fields = {'Price': 'price', 'AC Bonus': 'ac_bonus'}
for label_text, field_name in known_fields.items():
    label_tag = bs.find('b', string=lambda s: s and s.strip() == label_text)
    if label_tag:
        value = extract_value(label_tag)
        if value:
            stats[field_name] = value
```

**Good - Fail fast when encountering unknowns:**
```python
# Extract ALL labels from HTML and fail if we don't recognize one
recognized_labels = {'Price', 'AC Bonus', 'Dex Cap', 'Source'}
for bold_tag in bs.find_all('b'):
    label = bold_tag.get_text().strip()
    assert label in recognized_labels, f"Unknown label: {label}"
    # ... extract the value
```

**Why:** If the HTML changes or new fields are added, we want to fail immediately rather than silently skipping data. This makes the parser brittle by design - it will break when something unexpected appears, forcing us to investigate and update the parser.

### Keep Functions Small and Focused

Functions should be:
- **Short** - Most functions should fit on one screen (< 50 lines)
- **Simple to describe** - If you need multiple "and" or "or" clauses to describe what a function does, it's probably doing too much
- **Single responsibility** - Each function handles one transformation or extraction task

**Exceptions:** Main parse functions (like `parse_armor()`) can be longer if they're just a clean list of pass function calls.

### Use Local Helper Functions Liberally

Use private functions (prefixed with `_`) to break down complex logic:

```python
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
    _extract_description(bs, struct)
    _cleanup_stat_block(sb)
```

Each `_handle_*` or `_extract_*` function is focused on one specific task and easy to understand in isolation.

**Example from creatures.py:**
```python
def creature_stat_block_pass(struct):
    def _handle_sections(sb, struct):
        # ... focused on moving sections

    def _handle_title_before_speed(sb):
        # ... focused on title handling

    def _strip_br(data):
        # ... focused on cleaning breaks

    # Main logic is clean and readable
    sb = find_stat_block(struct)
    _handle_title_before_speed(sb)
    # ... more calls to focused functions
```

### Use .strip() Liberally

**Always use `.strip()` after extracting text from HTML.** HTML often contains leading/trailing whitespace, newlines, and other invisible characters.

**Good:**
```python
trait_name = get_text(link).strip()
trait_link = link.get('href', '').strip()
label = bold_tag.get_text().strip()
source['name'] = source['name'].strip()
```

**Why:** Prevents data quality issues like:
- Trailing spaces before punctuation (`"gauntlets ."`)
- Extra newlines in field values (`"\nSource"`)
- Inconsistent spacing causing comparison failures

**Rule of thumb:** If you're extracting text from HTML or getting an attribute value, immediately call `.strip()` on it.

## JSON Schemas: The Contract

The JSON schema files in `pfsrd2/schema/` are **documentation contracts** that define:

1. **What fields exist** - The complete structure of each data type
2. **What data is exposed** - All mechanical properties available for integration
3. **Field types and constraints** - Valid values, required vs optional fields
4. **How to consume the data** - Tools can parse schemas to understand the data

### Schema Philosophy

When adding new structured fields:

1. **Update the schema** - The schema should always reflect current output
2. **Document intent** - Use descriptions to explain what mechanics each field captures
3. **Think about consumers** - What would someone integrating this data need to know?

If you extract a new mechanical property from text into structured data, update the schema to reflect it. The schema is how we communicate "the full extent of data exposed" to integrators.

## Structured Data for Game Mechanics

### Bonus Objects: Supporting Pathfinder's Stacking Rules

Pathfinder 2e has specific bonus stacking rules: bonuses of the same type don't stack (only highest applies), but bonuses of different types do stack. To support this, we use structured bonus objects:

**Bad - Just a number:**
```json
{
  "ac_bonus": 4,
  "check_penalty": -2
}
```

**Good - Bonus objects with type information:**
```json
{
  "ac_bonus": {
    "type": "bonus",
    "subtype": "ac",
    "bonus_type": "armor",
    "bonus_value": 4
  },
  "check_penalty": {
    "type": "bonus",
    "subtype": "skill",
    "bonus_type": "armor",
    "bonus_value": -2
  }
}
```

**Why this matters:**
- Game logic can check `bonus_type` to determine stacking
- Multiple armor bonuses don't stack (same `bonus_type: "armor"`)
- Armor bonus + shield bonus DO stack (different `bonus_type`)
- Consistent structure across all bonus/penalty fields

**IMPORTANT - Choosing bonus_type:**

When implementing bonuses and penalties, **always check with the user about what `bonus_type` to use**. The correct bonus_type depends on game mechanics:

- **Armor**: `bonus_type: "armor"` for AC bonuses and penalties from wearing armor
- **Shields**: `bonus_type: "shield"` for AC bonuses and speed penalties from shields
- **Dexterity**: `bonus_type: "dexterity"` for dex cap on armor

Don't assume - different equipment types may use different bonus_type values even for similar-looking fields. For example:
- Armor speed penalty: `bonus_type: "armor"`
- Shield speed penalty: `bonus_type: "shield"`

**Common bonus patterns:**
```json
// AC bonuses
{"type": "bonus", "subtype": "ac", "bonus_type": "armor", "bonus_value": 4}
{"type": "bonus", "subtype": "ac", "bonus_type": "shield", "bonus_value": 2}
{"type": "bonus", "subtype": "ac", "bonus_type": "dexterity", "bonus_cap": 3}

// Speed penalties (negative values)
{"type": "bonus", "subtype": "speed", "bonus_type": "armor", "bonus_value": -5, "unit": "feet"}
{"type": "bonus", "subtype": "speed", "bonus_type": "shield", "bonus_value": -5, "unit": "feet"}

// Skill penalties
{"type": "bonus", "subtype": "skill", "bonus_type": "armor", "bonus_value": -2}
```

### Complex Field Structures

Some game mechanics need more than simple values:

**Bulk (handles special "L" value):**
```json
{
  "bulk": {
    "type": "stat_block_section",
    "subtype": "bulk",
    "value": 2,        // integer or null for "L"
    "display": "2"     // string representation
  }
}
```

**Speed penalties (with unit):**
```json
{
  "speed_penalty": {
    "type": "bonus",
    "subtype": "speed",
    "bonus_type": "armor",
    "bonus_value": -5,
    "unit": "feet"     // explicit unit for clarity
  }
}
```

**Trait links (minimal structure):**
```json
{
  "traits": [
    {
      "name": "Comfort",
      "link": "/Traits.aspx?ID=203"
    }
  ]
}
```

### The 'sections' Key Requirement

Many universal passes (like `edition_pass()`) recursively walk section trees. This requires all sections to have a `sections` key, even if empty:

**Will break edition_pass:**
```python
{
  'type': 'section',
  'name': 'Description',
  'text': 'Some text'
  # Missing 'sections' key!
}
```

**Works correctly:**
```python
{
  'type': 'section',
  'name': 'Description',
  'text': 'Some text',
  'sections': []  # Even if empty!
}
```

**Why:** Universal functions like `edition_pass()` do:
```python
for detail in details:
    result = edition_pass(detail['sections'])  # Assumes key exists
```

**Rule:** When creating section objects, always include `'sections': []`

### Edition Detection Pattern

The `edition_pass()` function determines legacy vs remastered:

```python
def edition_pass(details):
    for detail in details:
        if detail['name'] == "Legacy Content":
            return "legacy"
        result = edition_pass(detail['sections'])
        if result == "legacy":
            return result
    return "remastered"
```

**To use it:**
1. Extract any "Legacy Content" section from HTML
2. Call `edition_pass(struct['sections'])` BEFORE `remove_empty_sections_pass()`
3. Set `struct['edition']` with result
4. Now cleanup passes can remove the empty Legacy Content section

**Example:**
```python
# 1. During extraction, create Legacy Content marker if h3 found
if h3_legacy_content:
    struct['sections'].append({
        'type': 'section',
        'name': 'Legacy Content',
        'sections': []
    })

# 2. Later in pipeline, determine edition
edition = edition_pass(struct['sections'])
struct['edition'] = edition

# 3. Finally cleanup (removes empty Legacy Content section)
remove_empty_sections_pass(struct)
```

## Data Versioning for Consumers

**IMPORTANT:** If you're consuming the JSON output data, you should understand the versioning strategy.

### Schema Version Branches

The **pfsrd2-data** repository (JSON output) uses git branches for schema versioning:

**`main` branch:**
- Active development
- Schema may change (including breaking changes)
- ❌ **Do NOT use in production**

**`schema-vX.Y` branches:**
- Stable schema versions
- Created before breaking changes
- ✅ **Use these in production**

### What is a Breaking Change?

**Breaking changes (require new branch):**
- Removing fields
- Renaming fields
- Changing field types
- Changing field semantics

**Non-breaking changes (stay on main):**
- Adding new fields (consumers can ignore them)

### Consumer Best Practice

```bash
# ✅ Good: Pin to a stable schema version
git clone -b schema-v1.0 https://github.com/user/pfsrd2-data.git

# Or use as submodule
git submodule add -b schema-v1.0 https://github.com/user/pfsrd2-data.git data

# ❌ Bad: Use main branch in production
git clone https://github.com/user/pfsrd2-data.git  # main may break
```

**When upgrading schema versions:**
1. Test against new schema version branch
2. Update your code to handle new structure
3. Switch to new schema version branch
4. No forced upgrades - old versions remain available

This ensures **stability for consumers** while allowing **evolution of the parser**.

## Database Integration Pattern

Most content types support optional database loading for enrichment and querying.

### SQL Module Structure

Each content type with database support has a module in `pfsrd2/sql/`:

**Example: `pfsrd2/sql/armor.py`**
```python
# Table creation
def create_armor_table(curs):
    sql = """CREATE TABLE armor (
        armor_id INTEGER PRIMARY KEY,
        game_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        aonid INTEGER NOT NULL,
        category TEXT,
        armor_group TEXT,
        armor TEXT
    )"""
    curs.execute(sql)

# Index creation (for common queries)
def create_armor_index(curs):
    sql = "CREATE INDEX armor_game_id ON armor (game_id)"
    curs.execute(sql)

def create_armor_category_index(curs):
    sql = "CREATE INDEX armor_category ON armor (category)"
    curs.execute(sql)

# Data manipulation
def truncate_armor(curs):
    sql = "DELETE FROM armor"
    curs.execute(sql)

def insert_armor(curs, armor):
    text = json.dumps(armor)
    values = [
        armor['game-id'],
        armor['name'].lower(),  # Lowercase for case-insensitive search
        armor['aonid'],
        armor.get('stat_block', {}).get('category'),
        armor.get('stat_block', {}).get('group'),
        text
    ]
    sql = """INSERT INTO armor
        (game_id, name, aonid, category, armor_group, armor)
        VALUES (?, ?, ?, ?, ?, ?)"""
    curs.execute(sql, values)
    return curs.lastrowid

# Query functions
def fetch_armor_by_aonid(curs, aonid):
    sql = "SELECT * FROM armor WHERE aonid = ?"
    curs.execute(sql, (aonid,))
    return curs.fetchone()

def fetch_armor_by_category(curs, category):
    sql = "SELECT * FROM armor WHERE category = ?"
    curs.execute(sql, (category,))
    return curs.fetchall()
```

### Database Versioning

The database uses a versioning system in `pfsrd2/sql/__init__.py`:

```python
def create_db_v_6(conn, curs, ver, source=None):
    if ver >= 6:
        return ver
    ver = 6
    create_armor_table(curs)
    create_armor_index(curs)
    create_armor_aonid_index(curs)
    create_armor_category_index(curs)
    set_version(curs, ver)
    conn.commit()
    return ver
```

**When adding new tables:**
1. Create `pfsrd2/sql/yourtype.py` with table/index/query functions
2. Add imports to `pfsrd2/sql/__init__.py`
3. Create new `create_db_v_X()` function
4. Add call to `get_db_connection()`

**What to index:**
- `game_id` - Always (used for lookups)
- `aonid` - Always (Archives of Nethys ID)
- Category/type fields - If used for filtering
- Name - If doing prefix searches

### Load Scripts

Load scripts read JSON files and populate the database:

**Pattern: `bin/pf2_armor_load`**
```python
def load_armor(conn, options):
    path = options.output + "/armor"
    files = find(path, "-type", "f", "-name", "*.json").strip().split("\n")
    curs = conn.cursor()
    truncate_armor(curs)  # Clear existing data
    for f in files:
        with open(f) as fp:
            data = json.load(fp)
            print(data['name'])
            insert_armor(curs, data)
    conn.commit()
```

**Usage:**
```bash
./pf2_armor_load -o ../../pfsrd2-data
```

### Why Database + JSON?

**JSON files are the source of truth:**
- Version controlled
- Human readable
- Schema validated
- Easy to diff and review

**Database is for enrichment and queries:**
- Fast lookups during parsing (trait enrichment, ability lookups)
- Cross-referencing data
- Development queries
- Not for production deployment (use JSON)

## Directory Structure

```
PFSRD2-Parser/
├── bin/                    # Shell scripts - run from here
│   ├── dir.conf           # Config - must source this
│   ├── pf2_run_*.sh       # Pipeline scripts
│   ├── pf2_*_parse        # Individual parser runners
│   ├── pf2_*_load         # Database loader scripts
│   └── errors.*.log       # Error logs from runs
├── pfsrd2/                # Python parser modules
│   ├── creatures.py       # Creature/monster parser
│   ├── condition.py       # Condition parser
│   ├── skill.py           # Skill parser
│   ├── trait.py           # Trait parser
│   ├── monster_ability.py # Monster ability parser
│   ├── source.py          # Source book parser
│   ├── armor.py           # Armor parser
│   ├── constants.py       # Shared constants
│   ├── schema/            # JSON schemas - the documentation contract
│   │   ├── creature.schema.json
│   │   ├── armor.schema.json
│   │   └── ...
│   └── sql/               # Database utilities
│       ├── __init__.py    # Database versioning
│       ├── armor.py       # Armor table functions
│       ├── traits.py      # Trait table functions
│       └── ...
└── requirements.txt       # Python dependencies
```

## Workflow Example

Typical workflow when fixing a parser bug:

```bash
# 1. Navigate to bin directory
cd PFSRD2-Parser/bin

# 2. Source configuration
source dir.conf

# 3. Run the pipeline
./pf2_run_creatures.sh

# 4. Check for errors
cat errors.pf2.monsters.log

# 5. If there are errors, investigate the first one
# Edit the parser code to fix the issue

# 6. Reprocess only failed files
mv errors.pf2.monsters.log errors.pf2.monsters
./pf2_run_creatures.sh

# 7. Verify the fix worked
git status ../pfsrd2-data/
git diff ../pfsrd2-data/monsters/[affected-file].json
```

## Parser Module Structure

Each parser module in `pfsrd2/` typically follows this pattern:

1. Parse HTML using BeautifulSoup
2. Extract structured data
3. Convert to JSON-compatible dictionary
4. Write to output file in `pfsrd2-data/`

Parsers use:
- `beautifulsoup4` - HTML parsing
- `lxml` - Fast XML/HTML parsing backend
- `markdownify` - Convert HTML to Markdown (used sparingly)

## Iterative Improvement Process

When you identify mechanical data trapped in text blocks:

1. **Survey the scope** - How common is this pattern? Is it in 1 file or 100?
2. **Design the structure** - What fields would expose this mechanic clearly?
3. **Update the parser** - Extract the mechanic into structured fields
4. **Update the schema** - Document the new fields
5. **Verify output** - Check that mechanics are correctly extracted

### Identifying Extraction Opportunities

Look for patterns like:
- **Action types** - "as a reaction", "as a free action", "three actions"
- **Conditions** - "frightened 1", "stunned", "off-guard until end of turn"
- **Damage** - "2d6 fire damage", "1d8 persistent bleed"
- **Triggers** - "when an enemy moves adjacent", "at the start of its turn"
- **Durations** - "for 1 minute", "until the end of its next turn"
- **Requirements** - "must be wielding a shield", "only against flat-footed targets"
- **Frequency** - "once per day", "once per round"

If you see these appearing as text in multiple files, consider extracting them.

### One-Off vs. Systemic

- **One-off** - Single monster has unique ability with embedded mechanics → okay to leave as text for now
- **Systemic** - Pattern appears across many files → extract into structured fields

The iterative approach means we chip away at this over time, progressively exposing more mechanics.

## Key Principles

### Development Philosophy
1. **Look at existing parsers first** - Copy proven patterns before inventing new ones
2. **Start simple, iterate** - Run early, let failures guide you, refactor when patterns emerge
3. **Optimize for brittleness** - Fail fast on unknowns rather than silently ignoring them
4. **Small focused functions** - Break complexity into `_helper_functions()` with single responsibilities

### Data Structure
5. **Structured over opaque** - Extract mechanics into discrete fields, not text blocks
6. **Bonus objects for stacking** - Use structured bonus objects with `bonus_type` for game mechanics
7. **Always include 'sections'** - Section objects need `'sections': []` for recursive passes
8. **Edition before cleanup** - Call `edition_pass()` before `remove_empty_sections_pass()`

### Code Quality
9. **Use .strip() liberally** - Always strip text after extracting from HTML
10. **Pass-based architecture** - Main parse function is a clean list of passes
11. **Order matters** - Normalization after extraction, edition before cleanup, validation last

### PR Review Feedback
12. **Evaluate each suggestion on its merits** - Don't blanket-dismiss reviewer feedback as "out of scope." Every PR should leave the codebase better off.
13. **Tests are never out of scope** - Unit tests for changed code are part of the PR, not a follow-up ticket.
14. **Quick wins over tickets** - If a reviewer suggestion can be addressed with a small, focused change (redundant imports, extracting a helper, fixing a bug), do it now. Only create follow-up tickets for changes that would genuinely expand the PR's scope into a different concern.
15. **Be skeptical, not dismissive** - Evaluate whether a suggestion actually improves the code. Skip suggestions that are pedantic, platform-inappropriate, or add unnecessary complexity. But when a suggestion is valid, act on it.

### Operations
12. **Run from bin/** - Always execute scripts from the bin directory
13. **Source dir.conf** - Configuration must be loaded first
14. **Test incrementally** - Single file → full pipeline → check errors
15. **Error log reprocessing** - Use the `.log` rename trick for targeted reruns

### Integration
16. **Schema as contract** - Keep schemas updated to document exposed data
17. **Database for enrichment** - JSON is source of truth, database is for lookups/queries
18. **Iterate progressively** - Don't need to extract everything at once
