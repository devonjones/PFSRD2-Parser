# Slot Data Consumer Guide

For work on top of `pfsrd2-data` — particularly anything that answers
**"what can be applied to this item?"** for a weapon, armor or shield.

Written against the two consumers that exist today:

- **`pfsrd2-automation`** — the indexer that builds `pfsrd2.db` from the JSON
- **`pfsrd2-data-api`** — the Go service that serves it, and the template
  engine that *applies* effects and emits RFC 6902 JSON Patch

If you are adding a third consumer, read those two first; this guide assumes
their conventions rather than inventing new ones.

Three slot systems ship in the data. All follow the same principle: **the
published prose is authoritative and always retained; structured fields sit
beside it.** An absent structured field is a deliberate signal — see
[Absence is meaningful](#absence-is-meaningful).

- **Runes** — `stat_block.rune`, `stat_block.effects` (155 items)
- **Materials** — `stat_block.material`, `stat_block.material_use` (30 materials, 68 use pages)
- **Spell slots** — `stat_block.spell_slots` (152 holders: 90 staves, 60 wands, 2 scroll templates)

The contract is `equipment.schema.1.0.json`, shipped with the data.

---

## Editions: use the machinery that already exists

**511 name+category pairs appear more than once** — nearly every item exists in
both legacy and remastered form, as separate documents with different `aonid`s
and different rules text.

```
runes:         121 remastered + 34 legacy
materials:      23 remastered +  7 legacy
spell holders: 124 remastered + 28 legacy
```

The indexer already solves this. Don't re-solve it:

- `entries.edition` is `legacy` or `remastered` — filter on it.
- **`alternates(game_id, alternate_game_id, alternate_type)`** links the two
  editions of the same entity, stored in both directions. Use it to hop
  between editions rather than matching on name.
- `equivalents` does the same for curated cross-*type* edition equivalents.
- Key on `game_id`. `aonid` is Archives of Nethys' id and is what
  cross-references (spell links, `base_material` links) actually carry.

Matching on name silently doubles results and produces contradictions — legacy
*Elven Chain* is mithral, remastered is dawnsilver.

---

## Indexing eligibility: fit it to the existing schema

The indexer is **not** a normalized star schema. It is one `entries` row per
entity with a JSON `attrs` column, FTS5 over `search_text`, and a trigram
index over `name`. The documented way to add a queryable field
(`indexer/schema.py`) is:

1. add it to `attrs` in `extract.py` for the relevant type
2. if you need to filter or sort in SQL, add a generated column:
   `ALTER TABLE entries ADD COLUMN x TEXT GENERATED ALWAYS AS (json_extract(attrs,'$.x')) VIRTUAL`
3. add it to `search_text` for FTS

Follow that. Do not add side tables unless a query genuinely cannot be
expressed against `attrs`.

### The eligibility vocabulary is tiny and closed

Rune eligibility is expressed as JSONPath clauses, but **only five paths
appear across the entire corpus**:

| Clauses | Path | Values |
|---|---|---|
| 23 | `$.stat_block.offense.weapon_modes[*].weapon_type` | `Melee`, `Ranged` |
| 11 | `$.stat_block.offense.weapon_modes[*].damage[*].damage_type` | `piercing`, `slashing`, `bludgeoning` |
| 11 | `$.stat_block.statistics.category` | `Light`/`Medium`/`Heavy`; `Simple`/`Martial`/`Advanced` |
| 5 | `$.name` | `Clan Dagger` |
| 4 | `$.stat_block.traits[*].name` | `Thrown`, `Monk` |

So you never need a JSONPath engine at query time — you need those five values
on the item, and the clause values on the rune.

### What the indexer already gives you, and the one gap

Already in `attrs` today:

| Clause path | Where it lives |
|---|---|
| `$.name` | `entries.name` |
| `$.stat_block.statistics.category` | `attrs.weapon_category` / `attrs.armor_category` |
| `$.stat_block.traits[*].name` | `attrs.traits` |

**Missing — this is the gap to close first:** `WeaponExtractor` emits
`traits, item_category, item_subcategory, weapon_category, weapon_group,
price, bulk, pfs` but **not** `weapon_type` or `damage_type`. Those are two of
the five clause paths, so rune eligibility for weapons cannot be answered
until they are indexed.

The fix is a few lines in `pfsrd2/indexer/extract.py`:

```python
modes = offense.get("weapon_modes", []) if isinstance(offense, dict) else []
attrs["weapon_types"] = sorted({m.get("weapon_type") for m in modes if m.get("weapon_type")})
attrs["damage_types"] = sorted({
    d.get("damage_type")
    for m in modes for d in (m.get("damage") or [])
    if d.get("damage_type")
})
```

Both are lists, so query them with `json_each`:

```sql
SELECT e.* FROM entries e
WHERE e.type = 'weapons' AND e.edition = :edition
  AND EXISTS (SELECT 1 FROM json_each(e.attrs,'$.damage_types') j
              WHERE j.value = 'slashing');
```

### Evaluating a rune's clauses

Clauses are **AND of ORs**: a rune is eligible when *every* clause is
satisfied, and a clause is satisfied when *any* of its `values` matches. The
corpus contains both shapes, so a flattened list of values loses meaning —
keep clause grouping.

For a per-item answer, the cheapest correct approach is to load the candidate
runes for the host (`attrs.rune_host`, see below) and evaluate their clauses in
application code against the item's five attribute values. That is a few
hundred comparisons, not a join problem.

Rune fields worth putting in `attrs` when you index the rune side:

```
rune_form        fundamental | property
rune_slot        weapon_potency|striking|armor_potency|resilient|reinforcing|property
rune_host        weapon | armor | shield | accessory
rune_needs_review  bool  -- see Absence is meaningful
```

`rune_host` plus `rune_form` is the coarse filter that removes most of the
corpus before any clause evaluation.

---

## Effects are executable — use the engine, don't reimplement it

`stat_block.effects` on a rune uses **the same vocabulary as monster template
effects**, so `pfsrd2-data-api`'s template engine can apply them. Do not write
a second applier.

```json
{
  "type": "stat_block_section",
  "subtype": "rune_effect",
  "operation": "add_modifier",
  "target": "$.stat_block.offense.weapon_modes[*].modifiers",
  "modifier": {"type":"bonus","subtype":"attack","bonus_type":"item","bonus_value": 2}
}
```

The operations used are drawn from the engine's existing set:

| Rune | operation | target |
|---|---|---|
| Weapon potency | `add_modifier` | `$.stat_block.offense.weapon_modes[*].modifiers` |
| Armor potency, Resilient | `add_modifier` | `$.stat_block.defense.modifiers` |
| Striking | `replace` | `$.stat_block.offense.weapon_modes[*].damage[*].dice_count` |
| Reinforcing | `adjustment` | `$.stat_block.defense.hitpoints.{hardness,hp,break_threshold}` |

Notes that matter when applying them:

- `add_modifier` **creates its target array when absent** — that is how a
  potency rune grants an attack bonus to a base weapon that carries no
  modifier list.
- `adjustment` adds a delta **and syncs the sibling display text**, which is
  exactly the reinforcing wording ("Hardness increases by 3").
- `replace` sets a value and also syncs text.
- Striking targets `dice_count`, which weapon damage now exposes alongside
  `formula`: `{"formula":"1d8","dice_count":1,"die_size":8}`. Apply the rune by
  setting the count, then re-render the formula — don't string-munge `"1d8"`.
- **`maximum` is not yet honoured by the engine.** Reinforcing caps ship in
  the data (`maximum: 8`) but the engine has `Minimum` and no `Maximum`, so a
  caller must clamp until that lands. Tracked as `PFSRD2-Parser-omdz`'s
  follow-up.

### Capacity is not an effect

Property rune capacity mutates nothing on the host, so it is **not** in
`effects`. It rides on the rune block:

```
rune.grants_property_slots   1 | 2 | 3 | 4   (potency grades only)
```

Capacity equals the value on whichever potency grade the item carries.
Fundamental runes never consume capacity; only `form: "property"` does.

---

## Rules that are not fields

Deliberately derived rather than stored, because storing them on ~1,800 base
items would let them drift. Your loader computes them:

| Rule | How |
|---|---|
| Shields take no property runes, only `reinforcing` | gate on `host='shield'` |
| **Specific** magic items take no property runes | `item_subcategory` in `Specific Magic Weapons`/`Specific Magic Armor`/`Specific Shields` |
| **Staves** take fundamental runes but not property runes | `item_category='Staves'` |
| Duplicate property runes: only the highest-level applies | dedupe by name, keep max level |
| A rune beyond capacity goes **dormant**, not invalid | retain, mark inactive — a rune list is not an active-effect list |
| Item level = `max(base, all runes, material)` | compute |
| Any rune on armor grants **invested** | compute |

---

## Materials

`stat_block.material` on the 30 material items:

```
precious          bool — the gate for everything below
grades[]          {grade, max_item_level, max_rune_level}  — caps ABSENT for high = unbounded
grants_traits[]   trait names an item made of it gains
statistics[]      {form: thin|item|structure, grade, hardness, hit_points, break_threshold}
```

`stat_block.material_use` on the 68 use pages, plus per-variant
`{host, item_form, grade}` where `item_form` is `armor|weapon|shield|buckler|tower shield`.
"Which materials can this weapon be made of?" → use pages with `host='weapon'`.
The rules make the GM the final arbiter, so treat it as the published set, not
a closed one.

Two cross-constraints worth indexing for:

1. **Material grade caps rune level** — low ≤ 8th, standard ≤ 15th, high
   unbounded. When an item is made of a precious material, rune eligibility
   must also filter `rune.level <= max_rune_level`. This is the most important
   interaction between the two systems.
2. **Wand durability** is "a thin item of its material" —
   `statistics` where `form='thin'`.

**Trait propagation:** an item gains the material's traits except `precious`
(which classifies the material, and appears on none of the 68 published use
pages). Rarity does *not* union — an item has exactly one, so take the more
restrictive of the item's own and the material's over
`common < uncommon < rare < unique`. 300 base items already carry a rarity.

---

## Spell slots

```
spell_slots.holder            scroll | wand | staff
spell_slots.capacity          1 for scroll/wand
spell_slots.max_rank          10 scroll, 9 wand
spell_slots.excluded_spell_types  wands: cantrip, focus, ritual
spell_slots.spell             wands that always hold one spell (45 of 60)
spell_slots.constraint_text   specialty wands (10) — PROSE, deliberately unstructured
spell_slots.entries[]         staves: {rank, spells[{name, aonid, note}]}
variant.spell_rank            the rank a scroll/wand variant is priced for
```

- **`rank` is not an integer** — `cantrip` is a legitimate value. Store as text,
  or as an integer plus an `is_cantrip` flag; don't silently coerce cantrip to 0.
- **Staff grades are cumulative.** `cumulative: true` on a variant means its
  entries *add to* the lower grades. This is the opposite of rune grades, where
  a higher grade replaces the lower.
- **"Which spells fit this wand?"** → rank ≤ `max_rank`, type not in
  `excluded_spell_types`. For the 10 specialty wands `constraint_text` is prose
  ("casting time of ◆ or ◆◆, no duration, an area of burst, cone or line") —
  it ranges over spell fields not modelled here. Surface it to a human rather
  than guessing a filter.
- Charge economy is **not** in the data because it is identical for all 90
  staves: charges = preparer's highest spell rank, cost = the spell's rank,
  cantrips free.

---

## Absence is meaningful

| Absent | Means |
|---|---|
| `rune.requires` **with** `needs_review: true` | usage could not be fully parsed. **Not** "fits everything" — unconstrained-*unknown*. Exclude or flag |
| `rune.requires` without `needs_review` | genuinely unconstrained ("etched onto a weapon"), or an accessory rune whose eligibility is prose by design |
| `rune.grants_property_slots` | not a potency rune; grants no capacity |
| `material_grade.max_rune_level` | high grade — unbounded, not unknown |
| `material.grades` | not `precious`; never graded, imposes no rune cap |
| `spell_slots.entries` on a staff | only Whispering Staff, which delegates to *major staff of the unblinking eye* |
| `damage.dice_count` | flat damage (`"1"`), no dice to scale |

---

## Known gaps

Verified and tracked — not parser bugs:

- **3 runes carry `needs_review`**: *Malleable*, *Magnetizing*, *Shadow*. They
  require "metal armor"/"nonmetallic armor" and armor doesn't model material
  (`PFSRD2-Parser-4lx6`). They ship with **no** clauses rather than partial
  ones, which would call every medium armor legal for a metal-only rune.
- **`humanoid transformation`** on the legacy Staff of Transmutation resolves
  to nothing — AoN writes it unlinked and publishes no page; the remaster
  renamed it *humanoid form*.
- **Property rune effects are not extracted.** Only the 22 fundamental and
  reinforcing grades carry `effects`; the other 124 property runes keep their
  mechanics as prose (`PFSRD2-Parser-14ie`).
- **`schema_version` is 1.0** though these fields would warrant 1.1 — a
  deliberate scoping choice (`PFSRD2-Parser-dx1g`). Don't infer field
  availability from the version.

## Verifying your loader

Four verifiers ship with the parser and encode the invariants to preserve:

```
bin/pf2_verify_runes         # requires clauses AND effect targets resolve on real items
bin/pf2_verify_materials     # trait propagation vs AoN's own published pages
bin/pf2_verify_spell_slots   # all 1,275 slotted spells resolve; ranks legal
bin/pf2_check_completeness   # published rules lines appear in the JSON
```

The property worth copying: **a query that matches nothing should be loud, not
empty.** Every one of those fails when it has nothing to check, because a
filter returning zero rows is indistinguishable from a filter that is broken.
