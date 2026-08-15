# Slot Data Consumer Guide

For an agent building something on top of `pfsrd2-data` — particularly anything
that answers **"what can be applied to this item?"** for a given weapon, armor
or shield.

Three slot systems ship in the data. All three follow the same principle:
**the published prose is authoritative and always retained; structured fields
sit beside it.** If a structured field is absent, that is a deliberate signal,
not an oversight — see [Absence is meaningful](#absence-is-meaningful).

- **Runes** — `stat_block.rune`, `stat_block.effects` (155 items)
- **Materials** — `stat_block.material`, `stat_block.material_use` (30 materials, 68 use pages)
- **Spell slots** — `stat_block.spell_slots` (152 holders: 90 staves, 60 wands, 2 scroll templates)

The contract is `equipment.schema.1.0.json`, shipped alongside the data.

---

## The one thing to get right first: editions

**511 name+category pairs appear more than once in the equipment corpus.** Nearly
every item exists in both a legacy (pre-remaster) and a remastered form, as
separate documents with different `aonid`s and different rules text.

```
runes:         121 remastered + 34 legacy
materials:      23 remastered +  7 legacy
spell holders: 124 remastered + 28 legacy
```

Consequences:

- **Key on `game-id`**, not on name. `game-id` is stable and unique per document.
- **Filter by `edition`** in every query, or pick one edition at load time.
  Mixing them silently doubles results and produces contradictory answers
  (e.g. legacy *Elven Chain* is mithral, remastered is dawnsilver).
- `aonid` is Archives of Nethys' id — useful for linking back to the source
  page, and it is what cross-references (spell links, `base_material` links)
  actually carry.

---

## Indexing for "what can go on this item?"

### The key insight

Rune eligibility is expressed as JSONPath clauses, but **the path vocabulary is
closed — five paths across the entire corpus**:

| Clauses | Path | Values seen |
|---|---|---|
| 23 | `$.stat_block.offense.weapon_modes[*].weapon_type` | `Melee`, `Ranged` |
| 11 | `$.stat_block.offense.weapon_modes[*].damage[*].damage_type` | `piercing`, `slashing`, `bludgeoning` |
| 11 | `$.stat_block.statistics.category` | `Light`, `Medium`, `Heavy` (armor); `Simple`, `Martial`, `Advanced` (weapons) |
| 5 | `$.name` | `Clan Dagger` |
| 4 | `$.stat_block.traits[*].name` | `Thrown`, `Monk` |

So **do not evaluate JSONPath at query time.** Flatten each item into an
attribute table keyed on the *same path strings*, and eligibility becomes pure
set logic that a database can index.

### Schema sketch

```sql
-- One row per (item, path, value). This is the join surface.
CREATE TABLE item_attribute (
    item_id   INTEGER NOT NULL,      -- FK to your item table (game-id keyed)
    path      TEXT    NOT NULL,      -- exactly the clause path strings above
    value     TEXT    NOT NULL COLLATE NOCASE
);
CREATE INDEX item_attr_lookup ON item_attribute (item_id, path, value);
CREATE INDEX item_attr_reverse ON item_attribute (path, value);   -- "which items match X?"

CREATE TABLE rune (
    rune_id       INTEGER PRIMARY KEY,
    game_id       TEXT NOT NULL UNIQUE,
    aonid         INTEGER NOT NULL,
    edition       TEXT NOT NULL,      -- ALWAYS filter on this
    name          TEXT NOT NULL,
    form          TEXT NOT NULL,      -- fundamental | property
    slot          TEXT NOT NULL,      -- weapon_potency|striking|armor_potency|
                                      -- resilient|reinforcing|property
    host          TEXT NOT NULL,      -- weapon | armor | shield | accessory
    needs_review  INTEGER NOT NULL DEFAULT 0,
    level         INTEGER,
    price_value   INTEGER
);
CREATE INDEX rune_host_form ON rune (edition, host, form);
CREATE INDEX rune_slot      ON rune (edition, slot);

-- requires[] EXPLODED: one row per value, not per clause.
-- A clause is satisfied when ANY of its values matches (OR);
-- a rune is eligible when EVERY clause is satisfied (AND).
CREATE TABLE rune_requirement (
    rune_id    INTEGER NOT NULL,
    clause_idx INTEGER NOT NULL,      -- groups values belonging to one clause
    path       TEXT    NOT NULL,
    value      TEXT    NOT NULL COLLATE NOCASE
);
CREATE INDEX rune_req_lookup ON rune_requirement (rune_id, clause_idx);

CREATE TABLE rune_conflict (            -- from conflicts_with[]
    rune_id       INTEGER NOT NULL,
    conflicts_with TEXT   NOT NULL COLLATE NOCASE   -- a rune NAME, lowercased,
);                                                  -- "rune" suffix stripped
CREATE INDEX rune_conflict_lookup ON rune_conflict (rune_id);
```

`clause_idx` is what makes AND-of-ORs work. Without it you cannot distinguish
"slashing OR piercing" (one clause, two values) from "slashing AND piercing"
(two clauses) — and the corpus contains both shapes.

### The eligibility query

A rune fits an item when it has **no clause the item fails**:

```sql
SELECT r.*
FROM rune r
WHERE r.edition = :edition
  AND r.host    = :item_host              -- weapon | armor | shield
  AND NOT EXISTS (
        SELECT 1
        FROM (SELECT DISTINCT rune_id, clause_idx
              FROM rune_requirement WHERE rune_id = r.rune_id) c
        WHERE NOT EXISTS (
              SELECT 1
              FROM rune_requirement rr
              JOIN item_attribute ia
                ON ia.path = rr.path AND ia.value = rr.value
              WHERE rr.rune_id    = c.rune_id
                AND rr.clause_idx = c.clause_idx
                AND ia.item_id    = :item_id
        )
  );
```

A rune with no `requires` rows passes trivially — which is correct for
`etched onto a weapon`, and correct for accessory runes, but **is not correct
for the three `needs_review` runes**. See the gotchas.

### Populating `item_attribute`

For every weapon, armor and shield, emit rows for exactly the five paths:

```
$.name                                                    -> item name
$.stat_block.statistics.category                          -> Light/Medium/Heavy or Simple/Martial/Advanced
$.stat_block.traits[*].name                               -> one row per trait
$.stat_block.offense.weapon_modes[*].weapon_type          -> one row per mode (Melee/Ranged)
$.stat_block.offense.weapon_modes[*].damage[*].damage_type-> one row per damage type
```

Emit one row per value for the `[*]` paths — a weapon with both a melee and a
ranged mode gets two `weapon_type` rows, and a clause matching either is
satisfied. That is the intended semantics.

---

## Capacity, and what is NOT in the data

Several facts are **deliberately derived rather than stored**, because storing
them on ~1,800 base items would let them drift. Your loader must compute them.

### Property rune capacity

Capacity equals the numeric value of the item's **potency** rune, published as
an effect on the potency rune's variants:

```
Weapon Potency (+1) -> property_rune_slots 1     Armor Potency (+1) -> 1
Weapon Potency (+2) -> 2                          Armor Potency (+2) -> 2
Weapon Potency (+3) -> 3                          Armor Potency (+3) -> 3
Mythic Weapon Potency -> 4                        Mythic Armor Potency -> 4
```

Index those as a lookup:

```sql
CREATE TABLE rune_effect (
    rune_id   INTEGER NOT NULL,
    variant   TEXT,                    -- NULL for the base item's own effects
    operation TEXT NOT NULL,           -- set | add_modifier
    subject   TEXT NOT NULL,           -- property_rune_slots | weapon_damage_dice |
                                       -- attack | ac | save | hardness |
                                       -- hit_points | break_threshold
    value     INTEGER,                 -- when operation = set
    bonus_value INTEGER,               -- when operation = add_modifier
    bonus_type  TEXT,                  -- always 'item' for rune bonuses
    maximum     INTEGER                -- reinforcing caps
);
CREATE INDEX rune_effect_subject ON rune_effect (subject);
```

Then: `capacity = (SELECT value FROM rune_effect WHERE subject='property_rune_slots' AND …)`
for whichever potency variant the item has. Fundamental runes never consume
capacity; only `form='property'` runes do.

### Rules that are not fields

These are stated in the rules and must be enforced in your logic, because
nothing in the data encodes them per item:

| Rule | How to apply it |
|---|---|
| Shields take **no** property runes, only `reinforcing` | Gate on `host='shield'` |
| **Specific** magic items take no property runes | `item_subcategory` IN (`Specific Magic Weapons`, `Specific Magic Armor`, `Specific Shields`) |
| **Staves** take fundamental runes but **not** property runes | `item_category='Staves'` |
| Duplicate property runes: only the highest-level applies | Dedupe by rune name, keep max level |
| A property rune beyond capacity goes **dormant**, not invalid | Retain it; mark inactive. A rune list is *not* an active-effect list |
| Item level = `max(base level, all rune levels, material level)` | Compute |
| Any rune on armor grants the **invested** trait | Compute |

---

## Materials

```sql
CREATE TABLE material (
    material_id INTEGER PRIMARY KEY,
    game_id  TEXT NOT NULL UNIQUE,
    edition  TEXT NOT NULL,
    name     TEXT NOT NULL,
    precious INTEGER NOT NULL          -- the gate for EVERYTHING below
);

CREATE TABLE material_grade (
    material_id    INTEGER NOT NULL,
    grade          TEXT NOT NULL,      -- low | standard | high
    max_item_level INTEGER,            -- ABSENT for high grade = unbounded
    max_rune_level INTEGER             -- ABSENT for high grade = unbounded
);
CREATE INDEX material_grade_lookup ON material_grade (material_id, grade);

CREATE TABLE material_statistics (     -- Hardness/HP/BT grid
    material_id INTEGER NOT NULL,
    form        TEXT NOT NULL,         -- thin | item | structure
    grade       TEXT,                  -- NULL for common materials
    hardness INTEGER, hit_points INTEGER, break_threshold INTEGER
);
CREATE INDEX material_stats_lookup ON material_statistics (material_id, form, grade);

CREATE TABLE material_grants_trait (   -- from grants_traits[]
    material_id INTEGER NOT NULL,
    trait_name  TEXT NOT NULL
);

CREATE TABLE material_use (            -- the 68 "<Material> Armor/Shield/Weapon" pages
    material_id INTEGER,               -- via base_material link; NULL for Elven Chain
    host        TEXT NOT NULL,         -- armor | shield | weapon
    item_form   TEXT NOT NULL,         -- armor|weapon|shield|buckler|tower shield
    grade       TEXT NOT NULL,
    level INTEGER, price_value INTEGER,
    hardness INTEGER, hit_points INTEGER, break_threshold INTEGER   -- shields only
);
CREATE INDEX material_use_lookup ON material_use (host, item_form, grade);
```

**"Which materials can this weapon be made of?"** → `material_use WHERE host='weapon'`.
Note the rules make the GM the final arbiter, so treat this as the published
set, not a closed one.

### Two cross-constraints worth indexing for

1. **Material grade caps rune level.** A standard-grade item holds runes up to
   15th level; low-grade up to 8th; high-grade is unbounded (the caps are
   *absent* from the JSON, not null). So the rune eligibility query above
   should also filter `rune.level <= material_grade.max_rune_level` when the
   item is made of a precious material. This is the single most important
   interaction between the two systems.
2. **Wand durability** is "the Hardness, HP and BT of a **thin** item of its
   material" — i.e. `material_statistics WHERE form='thin'`.

### Trait propagation

An item made of a material gains the material's traits, **except `precious`**
(which classifies the material itself and appears on none of the 68 published
use pages). Rarity does **not** union — an item has exactly one, so take the
more restrictive of the item's own and the material's over
`common < uncommon < rare < unique`. 300 base items already carry a rarity, so
this matters.

---

## Spell slots

```sql
CREATE TABLE spell_slots (
    item_id  INTEGER PRIMARY KEY,
    holder   TEXT NOT NULL,            -- scroll | wand | staff
    capacity INTEGER,                  -- 1 for scroll/wand; absent for staves
    max_rank INTEGER,                  -- 10 scroll, 9 wand
    cantrips_free INTEGER,             -- staves
    fixed_spell_aonid INTEGER,         -- wands that always hold one spell
    constraint_text TEXT               -- specialty wands: PROSE, unstructured
);
CREATE TABLE spell_slot_excluded_type (item_id INTEGER, spell_type TEXT);
                                       -- wands: cantrip, focus, ritual

CREATE TABLE spell_slot_entry (        -- staves
    item_id INTEGER NOT NULL,
    variant TEXT,                      -- NULL = base; grades are CUMULATIVE
    rank    TEXT NOT NULL,             -- 'cantrip' or 1..10 — NOT an integer column
    spell_name  TEXT NOT NULL,
    spell_aonid INTEGER,
    note        TEXT                   -- "fungus only", "6th", ...
);
CREATE INDEX spell_slot_entry_spell ON spell_slot_entry (spell_aonid);
CREATE INDEX spell_slot_entry_rank  ON spell_slot_entry (item_id, rank);
```

`rank` is **not** a plain integer — `cantrip` is a legitimate value. Store it
as text, or as an integer with a separate `is_cantrip` flag; do not coerce
cantrip to 0 without documenting it.

**Staff grades are cumulative.** A variant's `spell_slots.cumulative = true`
means its entries *add to* the lower grades. A Greater staff holds the base
staff's spells plus its own. Do not treat a variant as a replacement — that is
the opposite of how rune grades work, where a higher grade *replaces* the
lower.

**"Which spells fit this wand?"** → spells where `rank <= max_rank` and type not
in the excluded set. For the 10 specialty wands, `constraint_text` is prose
("must have a casting time of ◆ or ◆◆, can't have a duration, and must have an
area of burst, cone, or line") — it is deliberately unstructured because the
predicate ranges over spell fields not modelled here. Surface it to a human;
do not attempt to parse it into a filter without verifying against the spell
data.

Charge economy is **not** in the data because it is identical for all 90
staves: charges = the preparer's highest spell rank, casting costs charges
equal to the spell's rank, cantrips are free.

---

## Absence is meaningful

| Field absent | Means |
|---|---|
| `rune.requires` **with** `needs_review: true` | The usage line could not be fully parsed. **Not** "fits everything" — the item is genuinely unconstrained-unknown. Exclude from eligibility results or flag it |
| `rune.requires` **without** `needs_review` | Genuinely unconstrained ("etched onto a weapon"), or an accessory rune whose eligibility is prose by design |
| `material_grade.max_rune_level` | High grade — unbounded, not unknown |
| `material.grades` | The material is not `precious`; it is never graded and imposes no rune cap |
| `spell_slots.entries` on a staff | Only Whispering Staff, which functions as a *major staff of the unblinking eye* and delegates |

---

## Known gaps

Verified, deliberate, and tracked — don't treat these as parser bugs:

- **3 runes carry `needs_review`**: *Malleable*, *Magnetizing*, *Shadow*. They
  require "metal armor" / "nonmetallic armor", and armor items don't model
  material. Tracked as `PFSRD2-Parser-4lx6`. They ship with **no** `requires`
  clauses rather than partial ones, because a partial list would call every
  medium armor legal for a rune that needs a metal one.
- **`humanoid transformation`** is referenced by the legacy *Staff of
  Transmutation* and resolves to nothing. AoN writes it unlinked and publishes
  no page — the remaster renamed the spell to *humanoid form*. A gap in the
  source.
- **Property rune effects are not extracted.** Only the 22 fundamental and
  reinforcing grades carry `effects`; the other 124 property runes carry their
  mechanics as prose in `text`. Tracked as `PFSRD2-Parser-14ie`.
- **`schema_version` is 1.0** even though these fields are additive additions
  that the schema guide would bump to 1.1. Deliberate, tracked as
  `PFSRD2-Parser-dx1g`. Don't infer field availability from the version.

## Verifying your loader

Four verifiers ship with the parser and encode the invariants your loader
should preserve. Running them tells you what "correct" looks like:

```
bin/pf2_verify_runes         # every requires clause matches >=1 real item
bin/pf2_verify_materials     # trait propagation vs AoN's own published pages
bin/pf2_verify_spell_slots   # all 1,275 slotted spells resolve; ranks legal
bin/pf2_check_completeness   # published rules lines appear in the JSON
```

The most useful property to copy: **a query that matches nothing should be
loud, not empty.** Every one of those verifiers fails when it has nothing to
check, because a filter that silently returns zero rows is indistinguishable
from a filter that is broken.
