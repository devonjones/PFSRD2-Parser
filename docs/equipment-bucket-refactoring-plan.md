# Equipment Schema Refactoring Plan: Creature-Style Buckets

## Goal
Refactor equipment schema from type-specific objects (weapon_object, armor_object, etc.) to creature-style buckets (defense, offense, statistics) to support hybrid equipment like:
- Shield with built-in weapon
- Siege weapon with armor properties
- Wearable item that functions as a weapon

## Current Structure (Rigid)

```
equipment_stat_block:
  - level, price, bulk, access, traits
  - weapon: weapon_object
  - armor: armor_object
  - shield: shield_object
  - siege_weapon: siege_weapon_object
  - abilities
```

### Current Type-Specific Objects:

**weapon_object:**
- category, hands, ammunition, favored_weapon
- melee: weapon_mode (damage, traits, group, range, reload)
- ranged: weapon_mode (damage, traits, group, range, reload)

**armor_object:**
- category, ac_bonus, dex_cap, check_penalty, speed_penalty
- strength (requirement)
- group (armor_group) ← RENAME to armor_group

**shield_object:**
- ac_bonus, speed_penalty
- hitpoints (hp, hardness, break_threshold, immunities)

**siege_weapon_object:**
- usage, crew, proficiency, ammunition, space
- ac, fort, ref
- hitpoints
- speed

## Proposed Structure (Flexible)

```
equipment_stat_block:
  - type, subtype (keep for compatibility)
  - level, traits (metadata stays at top level)
  - statistics: {price, bulk, access, usage, hands, category, proficiency}
  - defense: {ac, hardness, hitpoints, speed_penalty, check_penalty, dex_cap, saves}
  - offense: {damage, range, reload, ammunition, weapon_modes}
  - abilities: (already exists)
```

## Mapping: Current Fields → New Buckets

### STATISTICS Bucket (General Properties)
Maps from: All types
- `price` (all)
- `bulk` (all)
- `access` (all)
- `level` (all - may stay top-level)
- `category` (weapon: Unarmed/Simple/Martial/Advanced/Ammunition, armor: Unarmored/Light/Medium/Heavy)
- `hands` (weapon, weapon_mode)
- `usage` (siege_weapon)
- `crew` (siege_weapon)
- `proficiency` (siege_weapon)
- `space` (siege_weapon)
- `strength` → `strength_requirement` (armor)

### DEFENSE Bucket (Defensive Properties)
Maps from: armor, shield, siege_weapon
- `ac_bonus` (armor, shield)
- `ac` → `ac_value` (siege_weapon - raw AC, not bonus)
- `hardness` (shield.hitpoints, siege_weapon.hitpoints)
- `hitpoints` (shield, siege_weapon)
  - `hp`
  - `hardness`
  - `break_threshold` (BT)
  - `immunities`
- `speed_penalty` (armor, shield)
- `check_penalty` (armor)
- `dex_cap` (armor)
- `saves` → new container for:
  - `fort` (siege_weapon)
  - `ref` (siege_weapon)

### OFFENSE Bucket (Offensive Properties)
Maps from: weapon, siege_weapon
- `damage` (weapon_mode, abilities)
- `range` (weapon_mode)
- `reload` (weapon_mode)
- `ammunition` (weapon, weapon_mode, siege_weapon)
- `weapon_modes` → replaces melee/ranged:
  - `subtype`: "melee" | "ranged"
  - `traits` (weapon-specific traits like finesse, trip)
  - `damage` array
  - `weapon_type`: "Melee" | "Ranged"
  - `weapon_group` ← RENAME from group
  - `range` (for ranged)
  - `reload` (for ranged)
  - `ammunition` (if mode-specific)
  - `hands` (if mode-specific)

### Top-Level (Unchanged)
- `name`, `type`, `aonid`, `game-obj`, `game-id`
- `sources`, `sections`, `alternate_link`
- `edition`, `pfs`, `schema_version`, `license`
- `stat_block` (but contents refactored)
- `traits` (may move into stat_block or stay top-level with stat_block.traits for equipment-specific traits)

## Special Fields

### favored_weapon (weapon only)
Could go in:
- **statistics** (since it's metadata about the weapon)
- **offense** (since it relates to weapon usage)
**Recommendation**: Keep in statistics or create separate `metadata` section

### group → weapon_group / armor_group Renaming
**armor:**
- `armor_object.group` → `armor_object.armor_group`
- References `armor_group` definition (already exists)

**weapon:**
- `weapon_mode.group` → `weapon_mode.weapon_group`
- References `weapon_group` definition (already exists)

## Migration Strategy

### Phase 1: Schema Updates ✅ COMPLETE
1. ✅ Created `defense`, `offense`, `statistics` bucket definitions
2. ✅ Mapped existing fields to new buckets
3. ✅ Renamed `group` → `weapon_group`/`armor_group`
4. ✅ Kept old fields for backward compatibility during migration

### Phase 2: Parser Updates ✅ COMPLETE
1. ✅ Updated equipment.py to populate new bucket structure
2. ✅ Kept populating old fields during transition
3. ✅ Added validation that both old and new structures match
4. ✅ All 4 equipment parsers validated successfully

### Phase 3: Data Migration ✅ COMPLETE
1. ✅ Parser generates new bucket format
2. ✅ Data integrity validated (buckets match old structure 100%)
3. ✅ Schema validation passes with bucket structure

### Phase 4: Cleanup ✅ COMPLETE
1. ✅ Removed deprecated object definitions from schema (weapon_object, armor_object, shield_object, siege_weapon_object)
2. ✅ Old objects deleted from stat_block after bucket population
3. ✅ All 4 equipment parsers pass schema validation with new structure only

## Example: Shield with Weapon (Hybrid Equipment)

```json
{
  "name": "Spiked Shield",
  "stat_block": {
    "type": "stat_block",
    "subtype": "shield",
    "level": 0,
    "traits": [...],
    "statistics": {
      "type": "stat_block_section",
      "subtype": "statistics",
      "price": "5 sp",
      "bulk": {"value": 1, "display": "1"},
      "hands": 1,
      "category": "Martial"
    },
    "defense": {
      "type": "stat_block_section",
      "subtype": "defense",
      "ac_bonus": {
        "type": "bonus",
        "subtype": "ac",
        "bonus_type": "shield",
        "bonus_value": 2
      },
      "hitpoints": {
        "type": "stat_block_section",
        "subtype": "hitpoints",
        "hp": 6,
        "hardness": 3,
        "break_threshold": 3
      }
    },
    "offense": {
      "type": "stat_block_section",
      "subtype": "offense",
      "weapon_modes": [
        {
          "type": "stat_block_section",
          "subtype": "melee",
          "weapon_group": {"name": "Shield", ...},
          "damage": [
            {
              "type": "stat_block_section",
              "subtype": "attack_damage",
              "formula": "1d6",
              "damage_type": "piercing"
            }
          ],
          "traits": [...]
        }
      ]
    }
  }
}
```

## Benefits

1. **Hybrid Equipment**: Single item can have both offensive and defensive properties
2. **Consistency**: Aligns with proven creature schema design
3. **Extensibility**: Easy to add new equipment types without schema changes
4. **Clarity**: Properties grouped by purpose (offense/defense/stats)
5. **Query-Friendly**: "Show me all equipment with defense properties" is now trivial

## Risks & Mitigations

**Risk**: Breaking existing data consumers
**Mitigation**: Maintain both formats during transition period

**Risk**: Increased schema complexity
**Mitigation**: Well-documented bucket definitions, clear migration path

**Risk**: Parser refactoring effort
**Mitigation**: Incremental migration, validate at each step

## Next Steps

1. Review and approve this plan
2. Update schema with new bucket definitions
3. Begin Phase 1 (schema updates)
4. Create test cases for hybrid equipment
5. Update parser incrementally

## Notes

- Some creatures don't have `senses` (neither do most equipment) - bucket only needed when applicable
- `abilities` already exists and works well - keep as-is
- Consider whether `traits` should be top-level or in stat_block (creatures have it in creature_type, which is in stat_block)
