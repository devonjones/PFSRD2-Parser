# Enrichment Process Guide

How to add structured field extraction to a content type that currently has mechanics buried in text. This documents the pattern established by ability enrichment and is intended for future context windows extending this to other object types.

## When to Use Enrichment

Use this process when:
- A schema already defines structured fields (damage, DC, range, etc.) but the parser leaves them in `text`
- The text patterns are varied enough that a static parser can't reliably extract 100% of them
- You want to iteratively improve extraction without re-parsing everything
- Multiple objects share the same text (deduplication matters)

Don't use this process when:
- The data is consistently formatted with bold labels — just fix the parser directly
- There are fewer than ~50 objects to extract — manual fixes are faster

## Architecture Overview

```
Parser run → populates enrichment DB (raw records)
                    ↓
Offline enrichment → regex tier → LLM tier → manual review
                    ↓
Next parser run → merges enriched fields into JSON output
```

The enrichment DB (`~/.pfsrd2/enrichment.db`) is separate from the main `pfsrd2.db` and survives rebuilds. It has its own migration chain in `pfsrd2/sql/enrichment/`.

## Step-by-Step Process

### 1. Identify What to Extract

Survey the data to understand the scope:

```python
# How many objects have the keyword in text?
sqlite3 ~/.pfsrd2/enrichment.db "
SELECT COUNT(*) FROM ability_records
WHERE json_extract(raw_json, '$.text') LIKE '%DC %';
"
```

Categorize what you see:
- **Clearly extractable** — consistent patterns like "DC 30 basic Reflex save"
- **Variable** — same concept but different phrasing
- **Contextual** — keyword present but not an extractable mechanic (false alarms)

### 2. Check the Schema

Before writing extraction code, verify the schema already has the fields you need. If not, add them:

```json
// creature.schema.json — already has these on ability:
"saving_throw": { ... },
"damage": { ... },
"area": { ... },
"range": { ... },
"frequency": { "type": "string" }
```

New definitions go in the schema's `definitions` section. Follow existing patterns exactly — see `docs/schema-guide.md`. Required fields should be optional initially (only `type`, `subtype`, `text` required) so objects with partial extraction still validate.

### 3. Build the Population Pass

The population pass runs during the main parser pipeline. It:
1. Walks all objects of the target type
2. Computes an identity hash for each
3. Inserts raw records + links into the enrichment DB
4. On subsequent runs, merges enriched data back into the objects

See `pfsrd2/ability_enrichment.py` for the reference implementation. Key design:

- **Identity hash** — built from the fields that define the object's content (name, text, traits, etc.). If any of these change, the hash changes and the old record is marked stale.
- **Merge, don't replace** — enriched fields are added alongside existing fields. Text is never modified.
- **Array fields use dedup merge** — `saving_throw`, `area`, `damage` merge by identity key to avoid duplicates when both parser and enrichment produce the same field.

Wire the pass into the parser pipeline after the object is fully structured but before markdown/validation:

```python
# In parse_creature():
monster_ability_db_pass(struct)
ability_enrichment_pass(struct)  # <-- here
license_pass(struct)
```

### 4. Build the Regex Extractor

Start with conservative regex patterns. The goal is to catch the easy 70-80% without false positives.

Structure: `pfsrd2/enrichment/regex_extractor.py`

Each extraction type gets:
- A pattern or set of patterns
- An extraction function that returns structured objects or empty list
- A keyword detector for flagging (detects the keyword is present even if extraction fails)

```python
def extract_save_dc(text):
    """Returns a list of save_dc objects."""
    ...

def extract_area(text):
    """Returns a list of area objects."""
    ...
```

The top-level `extract_all()` runs all extractors and returns:
- The enriched object (or None if nothing extracted)
- A dict of missed keywords `{keyword: (detected_count, extracted_count)}`

### 5. Build False Alarm Filters

Many keyword detections are false alarms — "damage" in "resistance to damage", "DC" in "creature's Fortitude DC". Build patterns that suppress these:

```python
_FALSE_ALARM_PATTERNS = {
    "damage": [
        re.compile(r"resistance \d+ to .{0,30}damage", re.I),
        re.compile(r"(?:bonus|penalty) to (?:attack and )?damage", re.I),
        ...
    ],
}
```

The keyword count minus false alarm count determines whether to flag for review. Iterate on these — sample flagged records, classify them, add patterns for the clear false alarms.

### 6. Run the Regex Enrichment

```bash
# First time: populate DB (run the parser)
PFSRD2-Parser/bin/pf2_run_creatures.sh

# Back up the loaded DB for fast iteration
cp ~/.pfsrd2/enrichment.db ~/.pfsrd2/enrichment.db.loaded

# Run regex enrichment
bin/pf2_enrich_abilities --force-version

# Check stats
bin/pf2_enrich_abilities --stats

# Iterate: restore backup, tweak regex, re-enrich
cp ~/.pfsrd2/enrichment.db.loaded ~/.pfsrd2/enrichment.db
bin/pf2_enrich_abilities --force-version
```

### 7. Analyze Flagged Records

After regex enrichment, examine what's flagged:

```bash
# By type
sqlite3 ~/.pfsrd2/enrichment.db "
SELECT review_reason, COUNT(*) FROM ability_records
WHERE needs_review = 1
GROUP BY review_reason ORDER BY COUNT(*) DESC;
"

# Sample a category
sqlite3 ~/.pfsrd2/enrichment.db "
SELECT name, json_extract(raw_json, '$.text')
FROM ability_records
WHERE review_reason = 'unextracted: damage(1)'
ORDER BY RANDOM() LIMIT 20;
"
```

For each category, decide:
- **More regex patterns** — if there's a consistent pattern the regex missed
- **HTML fix** — if the issue is inconsistent formatting in the source HTML (e.g., "15-foot-radius emanation" should be "15-foot emanation")
- **False alarm filter** — if the keyword appears in a non-extractable context
- **LLM tier** — if the pattern is too variable for regex

### 8. Fix HTML Where Appropriate

When the issue is inconsistent HTML formatting rather than a parser limitation, fix the HTML in `pfsrd2-web/`. This is the project's core philosophy — HTML bugs get fixed in HTML, not worked around in code.

Example: "15-foot-radius emanation" → "15-foot emanation" across 15 creature files.

After fixing HTML:
1. Delete the enrichment DB
2. Re-run the parser (repopulates DB with corrected text)
3. Re-run enrichment

### 9. Build LLM Prompts

For patterns too variable for regex, build per-type LLM prompts. The prompt structure that works:

1. **State the task clearly** — "You are extracting X from Pathfinder 2E ability text"
2. **List specific patterns to look for** — bullet list of patterns
3. **List what NOT to extract** — important for reducing false positives
4. **Give examples** — 3-4 input/output examples including a "none" case
5. **Specify output format** — semicolon-separated list, or "none"

```python
FREQUENCY_PROMPT = """You are extracting frequency constraints from Pathfinder 2E ability text.

Scan the ENTIRE text carefully. Look for ALL instances of:
- "once per X"
- "X times per Y"
- "can't ... again for X"

Return every frequency constraint found as a semicolon-separated list.

Ability: {name}
Text: {text}

Frequency constraints found:"""
```

**Iterate the prompt against known test cases.** Write validation tests that run against the local LLM:

```python
@skip_no_ollama
class TestFrequencyLLM:
    def test_breath_weapon_recharge(self):
        result = extract_frequency_llm("Breath Weapon", "...")
        assert "1d4 rounds" in result
```

The LLM response parser should:
- Filter "none" and noise phrases
- Validate extracted values against the original text (prevents hallucination)
- Deduplicate

### 10. Run LLM Enrichment

```bash
# Per type
bin/pf2_enrich_abilities --llm frequency
bin/pf2_enrich_abilities --llm area
bin/pf2_enrich_abilities --llm dc
bin/pf2_enrich_abilities --llm damage
```

The LLM tier clears the `needs_review` flag for each type it processes (whether it extracts something or confirms there's nothing to extract).

### 11. Apply Enrichments

Re-run the parser to merge enriched data into JSON output:

```bash
PFSRD2-Parser/bin/pf2_run_creatures.sh
```

The enrichment pass checks the DB for each object's identity hash. If enriched data exists and isn't stale, it merges the structured fields into the object.

### 12. Review the Output

```bash
# Check data diff
cd pfsrd2-data && git diff --stat

# Spot-check specific files
git diff monsters/bestiary/adult_black_dragon.json

# Verify only expected changes
# - New structured fields added alongside text: correct
# - Text unchanged: correct
# - Files with no enrichable content unchanged: correct
```

## Key Design Decisions

### Identity Hashing

The identity hash determines whether two objects are "the same" for deduplication. Include fields that define the object's mechanical identity:
- `name`, `text`, `effect`, `frequency`, `trigger`, `requirement`, `cost`
- `action_type.name`
- Sorted trait names

Exclude fields that don't affect mechanics: `links`, `sources`, `universal_monster_ability`.

### Merge vs Replace

Enrichment **merges** — it adds new fields but never overwrites existing ones. For array fields (`saving_throw`, `area`, `damage`), it deduplicates by identity key:
- Save DCs: `(dc_value, save_type)`
- Areas: `(size, shape, unit)`
- Damage: `(formula, damage_type, persistent)`

### Enrichment Versioning

The `enrichment_version` on each record tracks which version of the extraction code produced it. When you make significant changes to extractors, bump the version. The `--force-version` flag re-processes records below the current version (skips human-verified).

### Stale Detection

When the parser re-runs and an object's text has changed (identity hash differs), the old enrichment record is marked `stale`. Stale enrichments are not applied. The offline enrichment process can re-extract them.

## Change Enrichment (Template/Family Rules)

Template and monster family construction rules use the same enrichment architecture, extended for rule extraction. The base parser extracts raw change text from `<li>` elements; all categorization and effect building happens offline.

### Architecture

```
Parser run → identifies construction sections, extracts raw <li> text
                    ↓
Population pass → stores raw changes + adjustments + links in enrichment DB
                    ↓
Offline enrichment → regex categorization + effect building
                    ↓
Next parser run → merges enriched change_category + effects into JSON output
```

### Effect Types

Effects use JSONPath-style targets and operations:

| Operation | Description |
|-----------|-------------|
| `adjustment` | Add/subtract from a numeric value |
| `replace` | Replace a value entirely |
| `add_item` | Append an item to an array |
| `remove_item` | Remove a named item from an array |
| `add_items` | Append multiple items (from a source path) |
| `replace_one_die` | Change one damage die to a new type |
| `replace_highest_with` | Replace highest speed with a new type |
| `size_increment` | Increase size by N categories |
| `select` | Human/tool choice required (see below) |

### Unified Select

All choice/selection operations use a single `select` type with `min`/`max` cardinality:

```json
{
    "operation": "select",
    "target": "$.creature_type.creature_types",
    "selection": {
        "type": "select",
        "min": 0,
        "max": 1,
        "options": [
            {
                "target": "$.creature_type.creature_types",
                "operation": "add_item",
                "name": "Mindless"
            }
        ],
        "description": "optionally add Mindless"
    }
}
```

**Cardinality patterns:**

| Pattern | min | max | Example |
|---------|-----|-----|---------|
| Required choice of one | 1 | 1 | "either amphibious or aquatic trait" |
| Optional | 0 | 1 | "optionally, the mindless trait" |
| Choose any number | 0 | *(omit)* | "any number of the creature's Strikes" |
| Required, unbounded | 1 | *(omit)* | "add drain life to at least one Strike" |

**Options are full objects**, not strings. Each option is either:
- A complete effect object (with `target`, `operation`, `name`) for the consumer to apply directly
- A complete data object (with `type`, `subtype`, `name`) to insert at the target

This means consumers never need to construct objects — they pick from the options array and apply as-is.

**Optional `action` field** for select operations that modify existing items:
- `"action": "replace"` — selected items are replaced
- `"action": "remove"` — selected items are removed

### Damage Adjustments

Flat damage modifiers use `attack_damage` objects (not modifier objects):

```json
{
    "target": "$.offense.offensive_actions[*].attack.damage",
    "operation": "add_item",
    "item": {
        "type": "stat_block_section",
        "subtype": "attack_damage",
        "formula": "+2",
        "notes": "Elite"
    }
}
```

The `notes` field carries the template/family name. Dice formulas like `"2d6"` work in `formula` as well. The `damage_type` field is included when the text specifies one (e.g., `"damage_type": "negative"`).

### Link-Based Trait Extraction

Trait effects use `game-obj: "Traits"` links from the raw HTML as the authoritative source, supplemented by regex for traits whose links point to wrong game-obj (e.g., "vampire" linking to MonsterFamilies instead of Traits). Non-Traits links in trait changes produce stderr warnings as potential HTML bugs.

### Adjustment Table Column Selection

When building level-conditional effects from adjustment tables, the enrichment extractor prefers domain-specific columns:
- HP effects: prefer columns with "hp" in the name
- Resistance effects: prefer columns with "resist" in the name
- Weakness effects: prefer columns with "weak" in the name

This avoids picking the wrong column when tables have multiple value columns (e.g., `hp_decrease` + `resistance/feed_hp`).

### CLI

```bash
bin/pf2_enrich_changes                # Enrich unenriched records
bin/pf2_enrich_changes --force        # Re-enrich all (except human-verified)
bin/pf2_enrich_changes --stats        # Show enrichment statistics
bin/pf2_enrich_changes --unknown      # Show records that couldn't be categorized
bin/pf2_enrich_changes --sample 5     # Show sample enriched records
```

## Files Reference

### Ability Enrichment

| File | Purpose |
|------|---------|
| `pfsrd2/ability_enrichment.py` | Population pass + merge logic |
| `pfsrd2/ability_identity.py` | Identity hashing |
| `pfsrd2/enrichment/regex_extractor.py` | Regex extraction + false alarm filters |
| `pfsrd2/enrichment/llm_extractor.py` | LLM prompts + response parsers |
| `bin/pf2_enrich_abilities` | Offline enrichment CLI |
| `bin/pf2_ability_review` | Inspection/review CLI |
| `docs/ability-enrichment.md` | Design doc for the ability enrichment system |

### Change Enrichment (Template/Family Rules)

| File | Purpose |
|------|---------|
| `pfsrd2/change_enrichment.py` | Population pass + merge logic |
| `pfsrd2/change_identity.py` | Identity hashing for change objects |
| `pfsrd2/change_extraction.py` | Shared HTML extraction (parse_change, abilities, adjustments) |
| `pfsrd2/enrichment/change_extractor.py` | Regex categorization + effect building |
| `bin/pf2_enrich_changes` | Offline enrichment CLI |

### Shared Infrastructure

| File | Purpose |
|------|---------|
| `pfsrd2/sql/enrichment/__init__.py` | DB connection + migration chain |
| `pfsrd2/sql/enrichment/tables.py` | Table/index DDL |
| `pfsrd2/sql/enrichment/queries.py` | CRUD operations |

## Extending to New Object Types

To enrich a new object type (e.g., spell effects, hazard mechanics):

1. **Add tables** — new migration in `pfsrd2/sql/enrichment/__init__.py` for object-specific tables (or reuse existing if the schema fits)
2. **Add identity hash** — determine which fields define the object's identity
3. **Add population pass** — walk the objects in the parser pipeline, insert into DB
4. **Add extractors** — regex patterns in `enrichment/`, LLM prompts in `llm_extractor.py`
5. **Add CLI support** — new script in `bin/` or extend existing
6. **Add tests** — identity hash stability, DB CRUD, extraction patterns, LLM validation
7. **Run the full pipeline** — populate → enrich → apply → verify

The enrichment DB is designed to be shared across object types. The migration chain and connection management host tables for both ability and change enrichment.
