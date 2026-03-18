# Monster Templates

Monster templates are rule sets that modify existing creatures to create variants (elite, weak, undead, elemental, ancestry-adjusted NPCs, etc.). The parser extracts these into structured JSON with machine-readable effects that can drive programmatic template application.

## Architecture

The template data is designed for a two-stage workflow:

1. **Parser** (this code) extracts structured instructions from HTML
2. **Downstream service** reads those instructions and generates RFC 6902 JSON Patches via [wI2L/jsondiff](https://github.com/wI2L/jsondiff) (Go) or [fast-json-patch](https://github.com/nicedoc/fast-json-patch) (Node)

The parser never modifies creature JSON directly. It produces the *instructions* that tell downstream code what patches to build.

## JSON Structure

```
{
  "name": "Elite",
  "type": "monster_template",
  "aonid": 22,
  "game-obj": "MonsterTemplates",
  "game-id": "...",
  "sources": [...],
  "text": "Description text...",
  "monster_template": {
    "name": "Elite",
    "type": "stat_block_section",
    "subtype": "monster_template",
    "changes": [...],        // Array of change objects
    "abilities": [...],      // Abilities to add (optional)
    "adjustments": [...]     // Level-based value table (optional)
  },
  "edition": "remastered",
  "license": {...},
  "schema_version": 1.0
}
```

### Change Objects

Each `<li>` item from the template's adjustment list becomes a change object:

```json
{
  "type": "stat_block_section",
  "subtype": "change",
  "text": "Increase the creature's AC, attack modifiers, DCs...",
  "change_category": "combat_stats",
  "effects": [...]
}
```

**`change_category`** classifies what the change modifies:

| Category | Description |
|----------|-------------|
| `level` | Creature level adjustment |
| `combat_stats` | AC, saves, perception, skills, attack bonuses, DCs |
| `damage` | Strike and ability damage |
| `hit_points` | HP adjustments (often table-driven) |
| `traits` | Add/remove/replace creature traits |
| `immunities` | Add immunities |
| `weaknesses` | Add weaknesses (may be level-dependent) |
| `resistances` | Add resistances (may be level-dependent) |
| `languages` | Add languages |
| `senses` | Add darkvision, tremorsense, etc. |
| `speed` | Add or modify movement speeds |
| `skills` | Add or modify skills |
| `spells` | Add or replace spells |
| `strikes` | Add or modify Strikes |
| `abilities` | Add new abilities |
| `attributes` | Modify attribute modifiers |
| `size` | Change creature size |
| `gear` | Add or remove equipment |

### Effect Objects

Each effect is a single instruction for the patch generator:

```json
{
  "target": "$.defense.ac.value",
  "operation": "adjustment",
  "value": 2
}
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `target` | yes | JSONPath to the field(s) being modified |
| `operation` | yes | What to do (see operations table) |
| `value` | no | Literal value for the operation |
| `value_from` | no | JSONPath expression to compute the value |
| `conditional` | no | JSONPath predicate — skip if false |
| `item` | no | Object to add (for `add_item`) |
| `modifier` | no | Modifier object to append (for `add_modifier`) |
| `selection` | no | Selection descriptor (for `select`) |
| `minimum` | no | Floor value when `value_from` uses division |

**Operations:**

| Operation | Description |
|-----------|-------------|
| `adjustment` | Add `value` to the target's current numeric value |
| `add_item` | Append `item` to the target array |
| `add_items` | Append multiple items (from `source` path) |
| `add_modifier` | Append `modifier` to the target's modifiers array |
| `replace` | Replace the target's value with `value` |
| `replace_one_die` | Change one damage die's type to `value` |
| `replace_highest_with` | Replace the highest speed with a new movement type |
| `remove_item` | Remove item matching `name` from the target array |
| `set_reach` | Set Strike reach to `value` |
| `select` | Requires human input (see Selection Framework) |

### Conditionals

Conditionals are JSONPath predicates evaluated against the creature being modified. The patch generator should evaluate them and skip the effect if false.

```json
{"conditional": "$.creature_type.level <= 0", ...}
{"conditional": "default", ...}
{"conditional": "$.offense.speed.movement[?(@.movement_type=='land')].value > 20", ...}
```

`"default"` means "apply this effect if no other conditional in the same change matched."

When multiple effects in the same change have conditionals, they form a conditional chain — evaluate in order, apply the first match, or fall through to `"default"`.

### Computed Values

Some effects derive their value from the creature's existing stats:

```json
{
  "target": "$.offense.speed.movement",
  "operation": "add_item",
  "item": {"type": "stat_block_section", "subtype": "speed",
           "name": "swim", "movement_type": "swim"},
  "value_from": "$.offense.speed.movement[?(@.movement_type=='land')].value / 2",
  "minimum": 15
}
```

The `value_from` field is a JSONPath expression with optional operators (`/ 2`, `| max`, `| min`). The `minimum` field sets a floor.

| Expression | Meaning |
|------------|---------|
| `$.skills[*].value \| max` | Highest skill modifier |
| `$.offense.speed.movement[*].value \| max` | Fastest speed |
| `$.offense.speed.movement[?(@.movement_type=='land')].value / 2` | Half land speed |
| `$.skills \| high_for_level` | High skill value from the building rules table |

## Selection Framework

Some template changes require human decisions. These use `operation: "select"` with a `selection` descriptor that tells the UI what to present.

### Selection Types

**`select_one`** — Choose exactly one option.

```json
{
  "target": "$.offense.offensive_actions[*].attack.traits",
  "operation": "select",
  "selection": {
    "type": "select_one",
    "options": ["versatile P", "versatile S"],
    "description": "...original rules text..."
  }
}
```

Used for: Vampire resistance bypass material, Metal Strike versatile trait.

**`select_n`** — Choose any number of items from a set.

```json
{
  "target": "$.offense.offensive_actions[*].attack",
  "operation": "select",
  "selection": {
    "type": "select_n",
    "description": "Add drain life to any number of the creature's Strikes..."
  }
}
```

Used for: Wight drain life on Strikes, Ghoul paralysis on Strikes.

**`replace_n`** — Replace N existing items with alternatives from a constrained set.

```json
{
  "target": "$.offense.offensive_actions[*].spells.spell_list[*].spells",
  "operation": "select",
  "selection": {
    "type": "replace_n",
    "constraint": "fire",
    "description": "If the creature can cast spells, you can replace spells with fire spells..."
  }
}
```

Used for: All six elemental templates (Air, Earth, Fire, Metal, Water, Wood).

**`remove_n`** — Remove N items based on context.

```json
{
  "target": "$.statistics.gear",
  "operation": "select",
  "selection": {
    "type": "remove_n",
    "description": "Typically, you remove any combat items..."
  }
}
```

Used for: Retired template gear removal.

### Selection Fields

| Field | Description |
|-------|-------------|
| `type` | `select_one`, `select_n`, `replace_n`, or `remove_n` |
| `options` | Explicit list of choices (when known) |
| `constraint` | Named constraint for the choices (e.g., `"lore"`, `"bypass_material"`, element name) |
| `description` | Original rules text — display to the user |

### UI Integration

The downstream application should:

1. Walk the `effects` array for each change
2. For non-`select` operations, compute and apply the patch directly
3. For `select` operations, present the selection UI based on `selection.type`
4. After user input, generate the appropriate patches
5. Apply all patches to a copy of the creature JSON
6. The original + patch set enables showing a diff of what changed

## Abilities

Templates that add abilities have them pre-extracted as structured objects:

```json
{
  "type": "stat_block_section",
  "subtype": "ability",
  "name": "Ghostly Passage",
  "action_type": {
    "type": "stat_block_section",
    "subtype": "action_type",
    "name": "One Action"
  },
  "text": "The creature Flies and can pass through walls...",
  "links": [...]
}
```

Abilities appear in two locations:
- **On a change object** (`change.abilities`) — when the change says "Add the following abilities" and lists them inline
- **On the stat block** (`monster_template.abilities`) — when abilities appear outside the `<ul>` list

The `abilities` change category effect points to these:

```json
{
  "target": "$.defense.automatic_abilities",
  "operation": "add_items",
  "source": "$.monster_template.changes[*].abilities"
}
```

## Adjustments Tables

Level-dependent values (HP, weaknesses, resistances) are stored both as raw table data and as computed effects.

**Raw table (for display):**

```json
"adjustments": [
  {"type": "stat_block_section", "subtype": "adjustment",
   "starting_level": "1 or lower", "hp_increase": "10"},
  {"type": "stat_block_section", "subtype": "adjustment",
   "starting_level": "2-4", "hp_increase": "15"},
  ...
]
```

**Computed effects (for patching):**

```json
"effects": [
  {"conditional": "$.creature_type.level <= 1",
   "target": "$.defense.hitpoints[*].hp",
   "operation": "adjustment", "value": 10},
  {"conditional": "$.creature_type.level >= 2 && $.creature_type.level <= 4",
   "target": "$.defense.hitpoints[*].hp",
   "operation": "adjustment", "value": 15},
  ...
]
```

The adjustments table is preserved for UI display. The effects are the machine-readable version for patch generation.

## Template Coverage

All 55 templates parse with 0 errors. All 216 changes across all templates have structured effects (100% coverage). 12 changes use the selection framework for human decisions.

### Template Sources

| Source | Templates | IDs |
|--------|-----------|-----|
| Bestiary (legacy) | Elite, Weak | 1-2 |
| Book of the Dead | Undead, Ghost, Ghoul, Mummy, Shadow, Skeleton, Vampire, Wight, Zombie | 3-11 |
| Dark Archive | Experimental/Mutant/Primeval/Rumored Cryptid | 12-15 |
| Rage of Elements | Air, Earth, Fire, Metal, Water, Wood | 16-21 |
| Monster Core (remastered) | Elite, Weak | 22-23 |
| Howl of the Wild | Amphibious, Frostbound, Miniature, Sandbound, Twinned, Winged, Broodpiercer | 24-30 |
| War of Immortals | Mythic Ambusher/Brute/Caster/Striker | 31-34 |
| NPC Core | Role templates + 17 ancestry templates | 35-55 |

### JSONPath Targets

Effects reference the creature schema. Common targets:

| Target | Description |
|--------|-------------|
| `$.creature_type.level` | Creature level |
| `$.creature_type.size` | Size category |
| `$.creature_type.rarity` | Rarity (Common/Uncommon/Rare/Unique) |
| `$.creature_type.creature_types` | Trait list |
| `$.defense.ac.value` | Armor Class |
| `$.defense.saves.fort.value` | Fortitude save |
| `$.defense.saves.ref.value` | Reflex save |
| `$.defense.saves.will.value` | Will save |
| `$.defense.hitpoints[*].hp` | Hit Points |
| `$.defense.hitpoints[*].immunities` | Immunities array |
| `$.defense.hitpoints[*].weaknesses` | Weaknesses array |
| `$.defense.hitpoints[*].resistances` | Resistances array |
| `$.senses.perception.value` | Perception modifier |
| `$.skills[*].value` | All skill modifiers |
| `$.offense.offensive_actions[*].attack.bonus.bonuses` | Attack bonuses |
| `$.offense.offensive_actions[*].attack.damage` | Strike damage |
| `$.offense.offensive_actions[*].spells.saving_throw.dc` | Spell DCs |
| `$.offense.speed.movement` | Speed array |
| `$.languages.languages` | Languages array |
| `$.statistics.gear` | Gear array |

## Running the Parser

```bash
# Parse all templates
PFSRD2-Parser/bin/pf2_run_monster_templates.sh

# Parse a single template
source PFSRD2-Parser/bin/dir.conf
PFSRD2-Parser/bin/pf2_monster_template_parse -o $PF2_DATA_DIR \
  $PF2_WEB_DIR/MonsterTemplates/MonsterTemplates.aspx.ID_22.html

# Dry run with stdout
PFSRD2-Parser/bin/pf2_monster_template_parse -d --stdout \
  $PF2_WEB_DIR/MonsterTemplates/MonsterTemplates.aspx.ID_22.html
```

Output goes to `pfsrd2-data/monstertemplates/<source_name>/`.

## Downstream Patch Generation (Planned)

The intended workflow for applying a template to a creature:

```
1. Load creature JSON (e.g., goblin_warrior.json)
2. Load template JSON (e.g., elite.json)
3. For each change in template.monster_template.changes:
   a. Evaluate conditionals against creature
   b. For select operations, collect user choices
   c. Compute values (value_from expressions, table lookups)
   d. Build RFC 6902 patch operations
4. Apply patches to a copy of the creature JSON
5. Output: original creature + patch array + modified creature
```

The patch array enables:
- Showing a highlighted diff of what changed
- Reverting specific changes
- Stacking multiple templates (apply patches in sequence)
- Auditing what a template actually did to a specific creature
