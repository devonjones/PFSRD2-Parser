# Schema Design Guide

## Critical Philosophy: Consistency Across Schemas

**The most important rule:** Standard definitions must be **identical** across all schemas.

When you see a definition like `link`, `source`, `section`, `license`, `trait`, etc. in one schema, copy it **exactly** to any new schema. Do not modify it. Do not "simplify" it. Do not add or remove fields.

## Standard Definitions (Copy Exactly)

These definitions should be identical across **all** schemas. When creating a new schema, copy these from an existing schema like `condition.schema.json` or `creature.schema.json`:

### Universal Core Definitions

**alternate_link** - Links to alternate versions (legacy/remastered)
```json
"alternate_link": {
    "type": "object",
    "properties": {
        "type": {"enum": ["alternate_link"]},
        "game-obj": {"enum": [
            "Actions", "Ancestries", "Archetypes", "Armor",
            "Classes", "Conditions", "Deities", "Diseases",
            "Domains", "Equipment", "Feats", "Heritages",
            "Languages", "MonsterAbilities", "MonsterFamilies",
            "Monsters", "NPCs", "Planes", "Rituals", "Rules",
            "Shields", "SiegeWeapons", "Skills", "Sources",
            "Spells", "Traits", "WeaponGroups", "Weapons"
        ]},
        "game-id": {"type": "string"},
        "alternate_type": {"enum": ["legacy", "remastered"]},
        "aonid": {"type": "integer"}
    },
    "required": ["game-obj", "aonid"],
    "additionalProperties": false
}
```

**image** - Image metadata
```json
"image": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["image"]},
        "game-obj": {"type": "string"},
        "image": {"type": "string"}
    },
    "required": ["name", "type", "image"],
    "additionalProperties": false
}
```

**link** - Links to other content
```json
"link": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["link"]},
        "alt": {"type": "string"},
        "href": {"type": "string"},
        "game-obj": {"enum": [
            "Actions", "Ancestries", "AnimalCompanions", "Archetypes",
            "Armor", "Backgrounds", "Bloodlines", "Causes", "Classes",
            "Conditions", "Curses", "Deities", "DeityCategories",
            "Diseases", "Doctrines", "Domains", "DruidicOrders",
            "Equipment", "Familiars", "Feats", "Hazards", "Heritages",
            "HuntersEdge", "HybridStudies", "Instincts", "Languages",
            "MonsterAbilities", "MonsterFamilies", "MonsterTemplates",
            "Monsters", "Muses", "Mysteries", "NPCs", "Patrons",
            "Planes", "Rackets", "Relics", "ResearchFields", "Rituals",
            "Rules", "Shields", "Skills", "Sources", "Spells", "Traits",
            "WeaponGroups", "Weapons"
        ]},
        "aonid": {"type": "integer"}
    },
    "required": ["name", "type", "alt"],
    "additionalProperties": false
}
```

**license** - OGL license information
```json
"license": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["section"]},
        "subtype": {"enum": ["license"]},
        "license": {"enum": [
            "OPEN GAME LICENSE Version 1.0a",
            "Open RPG Creative license"]},
        "text": {"type": "string"},
        "sections": {"$ref": "#/definitions/sections"}
    },
    "additionalProperties": false
}
```

**source** - Source book reference
```json
"source": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["source"]},
        "link": {"$ref": "#/definitions/link"},
        "note": {"$ref": "#/definitions/link"},
        "page": {"type": "integer"},
        "errata": {"$ref": "#/definitions/link"}
    },
    "required": ["name", "type", "link", "page"],
    "additionalProperties": false
}
```

**sources** - Array of sources
```json
"sources": {
    "type": "array",
    "items": {"$ref": "#/definitions/source"},
    "additionalItems": false
}
```

**section** - Content section (narrative/descriptive text)
```json
"section": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["section"]},
        "text": {"type": "string"},
        "sections": {"$ref": "#/definitions/sections"},
        "sources": {"$ref": "#/definitions/sources"},
        "subtype": {"enum": ["sidebar", "index"]},
        "sidebar_type": {"enum": [
            "treasure_and_rewards", "related_creatures", "locations",
            "additional_lore", "advice_and_rules", "geb"
        ]},
        "sidebar_heading": {"type": "string"},
        "image": {"$ref": "#/definitions/image"},
        "links": {
            "type": "array",
            "items": {"$ref": "#/definitions/link"},
            "additionalItems": false
        }
    },
    "additionalProperties": false
}
```

**sections** - Array of sections
```json
"sections": {
    "type": "array",
    "items": {"$ref": "#/definitions/section"},
    "additionalItems": false
}
```

**trait** - Enriched trait object (for stat blocks)
```json
"trait": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["trait"]},
        "game-id": {"type": "string"},
        "game-obj": {"enum": ["Traits"]},
        "value": {"type": "string"},
        "text": {"type": "string"},
        "classes": {
            "type": "array",
            "items": {"type": "string"},
            "additionalItems": false
        },
        "sources": {"$ref": "#/definitions/sources"},
        "sections": {"$ref": "#/definitions/sections"},
        "links": {
            "type": "array",
            "items": {"$ref": "#/definitions/link"},
            "additionalItems": false
        },
        "alternate_link": {"$ref": "#/definitions/alternate_link"},
        "schema_version": {"enum": [1.1]},
        "edition": {"enum": ["legacy", "remastered"]}
    },
    "required": ["name", "type", "game-id", "game-obj", "sources", "schema_version", "edition"],
    "additionalProperties": false
}
```

**traits** - Array of enriched traits
```json
"traits": {
    "type": "array",
    "items": {"$ref": "#/definitions/trait"},
    "additionalItems": false
}
```

**Important:** Traits are enriched via `trait_db_pass()` which looks up minimal trait objects in the database and replaces them with full trait data including sources, text, links, and metadata. Never create content-specific trait definitions (like `armor_trait`) - always use the standard `trait` definition.

### Creature/Stat Block Definitions

If your content type has stat blocks (like creatures, NPCs, hazards), you may need these:

**action_type** - Action economy (one action, two actions, reaction, etc.)
**modifier** / **modifiers** - Conditional modifiers to values
**ability** / **abilities** - Special abilities
**ac** - Armor class
**save** / **saves** - Saving throws
**save_dc** - DC for saving throws
**affliction** - Diseases, poisons, curses
**trait** / **traits** - Game traits (see note below about trait formats)

**Important:** For these definitions, copy from `creature.schema.json` as the reference implementation.

## Standard Top-Level Properties

Every content type schema should have these top-level properties (order matters for readability):

```json
"type": "object",
"properties": {
    "name": {"type": "string"},
    "type": {"enum": ["armor"]},           // Content type
    "aonid": {"type": "integer"},          // Archives of Nethys ID
    "game-obj": {"enum": ["Armor"]},       // Game object type
    "game-id": {"type": "string"},         // Unique identifier hash

    // Content-specific fields here
    "stat_block": {...},

    // Standard metadata (always in this order)
    "sources": {"$ref": "#/definitions/sources"},
    "sections": {"$ref": "#/definitions/sections"},
    "alternate_link": {"$ref": "#/definitions/alternate_link"},
    "edition": {"enum": ["legacy", "remastered"]},
    "schema_version": {"type": "number"},
    "license": {"$ref": "#/definitions/license"}
},
"required": ["name", "type", "aonid", "game-obj", "game-id", "sources", "sections", "edition", "license", "schema_version"],
"additionalProperties": false
```

**Note:** Not all content types have `alternate_link` - only include if the content type has legacy/remastered variants.

## Content-Specific Definitions

Content-specific definitions (like `armor_stat_block`, `armor_trait`, `bonus`, `bulk`) should be:

1. **Prefixed** with the content type (e.g., `armor_trait` not just `trait`)
2. **Documented** with comments explaining their purpose
3. **Validated** against actual parser output

### Example: Armor-Specific Definitions

```json
"armor_stat_block": {
    "type": "object",
    "properties": {
        "type": {"enum": ["stat_block"]},
        "subtype": {"enum": ["armor"]},
        "traits": {"$ref": "#/definitions/armor_traits"},
        // ... armor-specific fields
    },
    "required": ["type", "subtype"],
    "additionalProperties": false
}
```

**Why prefix?** Prevents confusion between content-specific traits and universal traits. `armor_trait` is a simple {name, link} object, while universal `trait` is a complex enriched object.

## Field Ordering Conventions

Within definitions, order fields consistently:

1. **type** - Always first
2. **subtype** - Always second (if present)
3. **name** - Third (if present)
4. **Core fields** - Main data fields
5. **Metadata fields** - links, modifiers, sources
6. **Text fields** - text, description (last)

```json
{
    "type": "stat_block_section",      // 1. type
    "subtype": "speed_penalty",        // 2. subtype
    "name": "speed penalty",           // 3. name
    "value": -5,                       // 4. core field
    "unit": "feet",                    // 4. core field
    "modifiers": [...]                 // 5. metadata
}
```

## Schema Validation Workflow

When creating or modifying a schema:

### 1. Start with an Existing Schema

```bash
# Copy a similar schema as starting point
cp pfsrd2/schema/condition.schema.json pfsrd2/schema/newtype.schema.json
```

### 2. Update Standard Definitions

- Keep all standard definitions identical (alternate_link, image, link, license, source, section)
- Only modify the content-specific definitions

### 3. Test Against Real Data

```bash
# Parse a single file
./pf2_newtype_parse -o $PF2_DATA_DIR $PF2_WEB_DIR/NewType/File.html

# Check validation errors
echo $?  # 0 = success, non-zero = validation failed
```

### 4. Fix Validation Errors

Common errors:

**"Additional properties are not allowed"**
- You're missing a field in the schema that the parser outputs
- Add the field to the appropriate definition

**"'value' is not of type 'object'"**
- Schema expects object but parser outputs string/integer
- Check if you need to normalize the field in the parser

**"required property 'field' missing"**
- Schema requires a field but parser doesn't always output it
- Either make it optional in schema or ensure parser always outputs it

### 5. Run Full Pipeline

```bash
# Test all files
./pf2_run_newtype.sh

# Check for any failures
cat errors.pf2.newtype.log
```

## Common Mistakes to Avoid

### ❌ Don't: Modify Standard Definitions

```json
// WRONG - Modified standard source definition
"source": {
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["source"]},
        "link": {"$ref": "#/definitions/link"},
        "page": {"type": "integer"}
        // Missing: note, errata
    },
    "required": ["name", "type", "link", "page"]  // Added page to required
}
```

### ✅ Do: Copy Standard Definitions Exactly

```json
// CORRECT - Copied from condition.schema.json exactly
"source": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["source"]},
        "link": {"$ref": "#/definitions/link"},
        "note": {"$ref": "#/definitions/link"},
        "page": {"type": "integer"},
        "errata": {"$ref": "#/definitions/link"}
    },
    "required": ["name", "type", "link"],  // page is optional
    "additionalProperties": false
}
```

### ❌ Don't: Create Simplified Versions of Standard Definitions

```json
// WRONG - Simplified trait definition instead of using standard
"armor_trait": {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "link": {"type": "string"}  // String instead of link object
    },
    "required": ["name", "link"]
}
// This breaks trait enrichment via trait_db_pass()
```

### ✅ Do: Use Standard Definitions Even for Complex Structures

```json
// CORRECT - Use standard trait definition
"traits": {
    "type": "array",
    "items": {"$ref": "#/definitions/trait"},  // Standard enriched trait
    "additionalItems": false
}
// Traits are enriched via trait_db_pass() with full metadata
```

### ❌ Don't: Make Required Fields Optional

```json
// WRONG - edition should always be present
"required": ["name", "type", "aonid", "game-id", "sources"]
// Missing: edition, license, schema_version
```

### ✅ Do: Require Core Metadata Fields

```json
// CORRECT - All core metadata required
"required": [
    "name", "type", "aonid", "game-obj", "game-id",
    "sources", "sections", "stat_block",
    "edition", "license", "schema_version"
]
```

## Schema Version Management

Each schema includes a `schema_version` field in the JSON output:

```json
{
    "name": "Breastplate",
    "schema_version": 1.0,
    // ...
}
```

**When to increment schema version:**

- **1.0 → 1.1** (minor): Adding optional fields, new enums
- **1.0 → 2.0** (major): Removing fields, renaming fields, changing types

**Where to update:**

1. Schema file: Update the enum in top-level properties
2. Parser: Update the version in parse function
3. Git: Create schema-vX.Y branch in data repo before breaking changes

## Reference Schemas

Use these as templates:

- **Simple content**: `condition.schema.json` - Minimal structure, just text and metadata
- **Stat blocks**: `creature.schema.json` - Complex stat blocks with abilities
- **Equipment**: `armor.schema.json` - Equipment with stat blocks and bonus objects

## Checklist for New Schemas

- [ ] Copied standard definitions exactly (alternate_link, image, link, license, source, section, trait if needed)
- [ ] Use standard trait definition (not content-specific like `armor_trait`)
- [ ] Implemented trait_db_pass() if content has traits
- [ ] Content-specific definitions use prefixed names for non-standard types (e.g., `armor_stat_block`)
- [ ] Top-level properties include all standard metadata (sources, sections, edition, license, schema_version)
- [ ] Field ordering follows conventions (type, subtype, name, core, metadata, text)
- [ ] Required fields include core metadata (name, type, aonid, game-obj, game-id, edition, license, schema_version)
- [ ] Tested against single file successfully
- [ ] Tested against full pipeline successfully
- [ ] No validation errors in error log

## Quick Copy-Paste Template

```json
{
    "$schema": "http://json-schema.org/draft-07/schema#",

    "definitions": {
        // Copy these exactly from creature.schema.json:
        // - alternate_link (if needed)
        // - image
        // - link
        // - license
        // - source
        // - sources
        // - section
        // - sections
        // - trait (if content has traits)
        // - traits (if content has traits)

        // Add content-specific definitions here:
        // - mytype_stat_block
        // - mytype_specific_thing
    },
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"enum": ["mytype"]},
        "aonid": {"type": "integer"},
        "game-obj": {"enum": ["MyTypes"]},
        "game-id": {"type": "string"},

        // Content-specific properties
        "stat_block": {"$ref": "#/definitions/mytype_stat_block"},

        // Standard metadata (always in this order)
        "sources": {"$ref": "#/definitions/sources"},
        "sections": {"$ref": "#/definitions/sections"},
        "alternate_link": {"$ref": "#/definitions/alternate_link"},
        "edition": {"enum": ["legacy", "remastered"]},
        "schema_version": {"type": "number"},
        "license": {"$ref": "#/definitions/license"}
    },
    "required": [
        "name", "type", "aonid", "game-obj", "game-id",
        "sources", "sections", "stat_block",
        "edition", "license", "schema_version"
    ],
    "additionalProperties": false
}
```

## Why This Matters

**Consistency enables:**
- Tools that work across all content types
- Shared code for common operations
- Predictable structure for consumers
- Easy validation and debugging

**Inconsistency causes:**
- Duplicate code for each content type
- Confusing differences for consumers
- Hard-to-debug validation errors
- Technical debt accumulation

When in doubt: **Copy from an existing schema. Don't innovate on standard definitions.**
