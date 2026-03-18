# Monster Families

Monster families group related creatures (e.g., all vampires, all dragons) and provide rules for creating new creatures of that type. The parser extracts these into structured JSON with creation changes, ability subtypes, and machine-readable effects.

## Relationship to Monster Templates

Monster templates and monster families serve different purposes but share the same effects machinery:

- **Monster Templates** (`monster_templates/`) — standalone adjustment rules applied to any creature (Elite, Weak, Ghost, Elemental, etc.)
- **Monster Families** (`monster_families/`) — creature groups that include lore, creation rules, and ability sets specific to that family (Vampire, Ghost, Lich, etc.)

Both use the same `changes` schema with `change_category` and `effects`. The shared effect builder code lives in `monster_template.py` and is imported by `monster_family.py`.

## JSON Structure

```json
{
  "name": "Vampire",
  "type": "monster_family",
  "aonid": 480,
  "game-obj": "MonsterFamilies",
  "sources": [...],
  "text": "Lore description...",
  "monster_family": {
    "name": "Vampire",
    "type": "stat_block_section",
    "subtype": "monster_family",
    "changes": [...],
    "subtypes": [...]
  },
  "sections": [...],
  "edition": "remastered"
}
```

### Top Level

| Field | Description |
|-------|-------------|
| `name` | Family name |
| `text` | Lore/description text |
| `monster_family` | Structured creation rules (changes + subtypes) |
| `sections` | Remaining lore sections (sidebars, flavor text) |
| `edition` | `"legacy"` or `"remastered"` |

### monster_family Object

Contains the structured rules for creating creatures of this family type.

```json
{
  "name": "Vampire",
  "type": "stat_block_section",
  "subtype": "monster_family",
  "changes": [
    {
      "type": "stat_block_section",
      "subtype": "change",
      "text": "Increase the creature's level by 1...",
      "change_category": "combat_stats",
      "effects": [...]
    }
  ],
  "subtypes": [
    {
      "name": "Basic Vampire Abilities",
      "type": "stat_block_section",
      "subtype": "monster_family",
      "changes": [...]
    },
    {
      "name": "True Vampire Abilities",
      "type": "stat_block_section",
      "subtype": "monster_family",
      "changes": [...]
    }
  ]
}
```

**`changes`** — Stat modifications from the "Creating X" section (same schema as monster template changes). Each has `change_category` and `effects`.

**`subtypes`** — Ability groups like "Basic Vampire Abilities" and "True Vampire Abilities". Each subtype is itself a `monster_family` object that can have its own changes, text, and nested subtypes. The abilities within each subtype are wrapped in a change with `change_category: "abilities"`.

### Subtypes

Many families define tiers or categories of abilities:

| Family | Subtypes |
|--------|----------|
| Vampire | Basic Vampire Abilities, True Vampire Abilities |
| Ghost | Ghost Abilities, Special Abilities |
| Ghoul | Ghoul Abilities, Ghast Abilities |
| Lich | Lich Abilities, Alternate Lich Abilities |
| Werecreature | Werecreature Abilities |
| Nosferatu | Basic Nosferatu Abilities, Nosferatu Overlord Abilities, Nosferatu Thrall Abilities |

Each subtype contains a change with `change_category: "abilities"` holding the extracted abilities array.

## Creature Integration

When parsing creatures, the parser replaces the minimal family reference on `stat_block.creature_type.family` with the full DB-loaded family object.

### Before (minimal reference)

```json
{
  "stat_block": {
    "creature_type": {
      "family": {
        "type": "stat_block_section",
        "subtype": "family",
        "name": "Vampire",
        "link": {"game-obj": "MonsterFamilies", "aonid": 97}
      }
    }
  },
  "sections": [
    {"name": "Vampire", "sections": [
      {"name": "Creating a Vampire", "sections": [
        {"name": "Basic Vampire Abilities", ...},
        {"name": "True Vampire Abilities", ...}
      ]}
    ]}
  ]
}
```

### After (DB-enriched)

```json
{
  "stat_block": {
    "creature_type": {
      "family": {
        "name": "Vampire",
        "type": "monster_family",
        "aonid": 97,
        "link": {"game-obj": "MonsterFamilies", "aonid": 97},
        "monster_family": {
          "changes": [...],
          "subtypes": [...]
        },
        "sections": [...],
        "edition": "legacy"
      }
    }
  },
  "sections": [
    {"name": "Vampire Count"}
  ]
}
```

The inline family sections (with all the creation rules and ability text) are dropped from `sections` — that content now lives in the family object on `creature_type.family`.

### Edition Matching

The creature parser prefers the family edition matching the creature's edition. If a legacy creature links to a legacy family that has a remastered counterpart, the parser will use the remastered version for remastered creatures and vice versa. Falls back to the available edition if the preferred one doesn't exist.

## Database

Monster families are loaded into the `pfsrd2.db` SQLite database as part of the dependency pipeline (`pf2_run_deps.sh`).

### Tables

- `monster_families` — Full family JSON indexed by `game_id`, `name`, `aonid`, `edition`
- `monster_family_links` — Legacy/remastered pairs for edition cross-referencing

### Lookup Functions

```python
from pfsrd2.sql.monster_families import (
    fetch_monster_family_by_name,
    fetch_monster_family_by_aonid,
    fetch_monster_family_by_id,
    fetch_monster_family_by_link,
)
```

### Pipeline Order

In `pf2_run_deps.sh`, monster families are parsed and loaded after weapon groups:

```
... → pf2_run_weapon_groups.sh → pf2_weapon_group_load
    → pf2_run_monster_families.sh → pf2_monster_family_load
```

The creature parser (`pf2_run_creatures.sh`) must run AFTER `pf2_run_deps.sh` to have families available in the database.

## Running the Parser

```bash
# Parse all monster families
PFSRD2-Parser/bin/pf2_run_monster_families.sh

# Parse a single family
source PFSRD2-Parser/bin/dir.conf
PFSRD2-Parser/bin/pf2_monster_family_parse -o $PF2_DATA_DIR \
  $PF2_WEB_DIR/MonsterFamilies/MonsterFamilies.aspx.ID_480.html

# Load families into database
PFSRD2-Parser/bin/pf2_monster_family_load -o $PF2_DATA_DIR

# Run full dependency chain (includes families)
PFSRD2-Parser/bin/pf2_run_deps.sh
```

Output goes to `pfsrd2-data/monster_families/<source_name>/`.

## Known Limitations

- **Ability parsing (PFSRD2-Parser-alj)**: Bold sub-fields within abilities (Requirements, Trigger, Effect) are currently parsed as separate abilities instead of fields on the preceding ability. Items like "Immunities", "Climb Speed", "Resistances" are parsed as abilities but should be stat-modification changes.
- **Embedded headings (PFSRD2-Parser-xfl)**: 7 families have `h2`/`h3` tags in section text due to AoN HTML structure. Allowed via `fxn_valid_tags` workaround.
- **Cross-page table reference**: Vampire Vetalarana references the parent Vampire's HP table. Fixed by adding the table to the HTML.

## Coverage

- 632 families parsed, 0 errors, schema validated
- 108 creation changes extracted, 108/108 (100%) with effects
- 2,382 abilities extracted across 167 families
- 202 legacy/remastered edition links
- Members sections stripped from all families
