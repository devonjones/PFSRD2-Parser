# Hazard Data Consumer Guide

For work on top of `pfsrd2-data` now that **hazards ship**. Written against the
two consumers that exist today:

- **`pfsrd2-automation`** — the indexer that builds `pfsrd2.db` from the JSON
- **`pfsrd2-data-api`** — the Go service that serves it

Neither knows about hazards yet. This is what you need to add them.

Companion to [slot-data-consumer-guide.md](slot-data-consumer-guide.md), which
covers runes, materials and spell slots. Read that one first if you are also
touching equipment — it establishes the edition and indexing conventions this
guide assumes.

The contract is `hazard.schema.1.0.json`, shipped with the data.

---

## What shipped

**606 documents across 82 books**, in two directories:

| Directory | `game-obj` | Count |
|---|---|---|
| `hazards/` | `Hazards` | 594 |
| `weatherhazards/` | `WeatherHazards` | 12 |

They share an aonid space with each other but not with anything else, so
**key on `game-id`, not `aonid`** — all 606 `game-id`s are unique.

Levels run **-1 to 23**. 548 remastered, 58 legacy. 328 Simple, 266 Complex,
12 with no complexity (the weather hazards).

---

## The document shape is *not* the creature shape

This trips people first. Creatures nest everything under `stat_block` with
`defense`/`offense`/`statistics` sub-objects. Hazards follow the
`feat`/`spell` convention instead: **one flat object under a `hazard` key**.

```
creature:  doc.stat_block.defense.hp
hazard:    doc.hazard.hp
```

Top level, always present:

```
aonid  edition  game-id  game-obj  hazard  license  name  pfs
schema_version  sources  type
```

`alternate_link` on 116 documents (see [Editions](#editions)). Note that
creatures have **no** top-level `game-id`; hazards do, like equipment.

### `doc.hazard` field census

Always present: `name`, `type`, `subtype`, `level`, `description`, `sources`.

Everything else is optional, and **absence is meaningful** — see below.

| Field | Count | Shape |
|---|---|---|
| `abilities` | 605 | array of `ability` — *identical to creature's* |
| `traits` | 597 | array of enriched `trait` |
| `complexity` | 594 | `"Simple"` \| `"Complex"` |
| `disable` | 590 | string |
| `stealth` | 588 | object — DC **or** modifier, see below |
| `links` | 582 | array of `link` |
| `reset` | 382 | string |
| `ac` / `saves` | 284 | integer / array of `save` |
| `immunities` | 266 | array of `protection` |
| `routine` | 266 | string |
| `hp` | 209 | integer |
| `bt` | 174 | integer (break threshold) |
| `hardness` | 155 | integer |
| `attacks` | 124 | array of `attack` — *identical to creature's* |
| `components` | 83 | array of `hazard_component` |
| `weaknesses` | 61 | array of `protection` |
| `text` | 32 | residual published prose |
| `hp_note` / `hardness_note` | 27 / 6 | what the number is qualified by |
| `saving_throw` | 24 | `save_dc` |
| `maximum_duration` | 19 | string |
| `resistances` | 12 | array of `protection` |
| `speed` / `special` / `bypass` | 8 / 6 / 6 | string |

---

## The schema shapes are shared; the *code* is not

The hazard schema reuses `creature.schema.json`'s definitions **byte-for-byte**:

`ability`, `abilities`, `action_type`, `affliction_stage`, `area`, `attack`,
`attack_bonus`, `attack_damage`, `link`, `modifier`, `modifiers`,
`protection`, `range`, `save`, `save_dc`, `trait`, `traits`,
`universal_monster_ability`

Hazard-specific: `hazard`, `hazard_component`, `hazard_stealth`.

**Do not read that as "your creature code just works."** It does not, in either
repo, and for concrete reasons:

- **Go (`pfsrd2-data-api`) has no typed model for any of this.** Every document
  is `map[string]any`. There is no `Attack`, `Ability`, `Save`, `Protection`,
  `Trait` or `Link` struct anywhere in `service/internal`. What encodes
  creature shape is string paths in `template/engine.go` — `lowestMeleeStrike`,
  `hasWeapon`, `strikeTraits`, `applyAddStrike` — reading
  `wrapper["attack"]["weapon"]` directly.
- **Python (`pfsrd2-automation`) touches none of it.** `MonsterExtractor` pulls
  trait names, family name and a flat list of ability *names*. Nothing reads
  attacks, saves or protections. The one genuinely reusable helper is
  `_trait_names(traits)` in `extract.py`, which works on `hazard.traits`
  unchanged.
- **The wrapping differs even where the objects match.** A creature Strike is
  the inner `attack` of an `offensive_actions` entry; a hazard's is unwrapped
  in a flat `hazard.attacks` array. Same object, different container.

So: the schema equivalence means you can *trust the field shapes* and copy
existing test fixtures. It does not hand you a renderer.

### The template engine cannot take hazards as-is

`template.ApplyWithSelectionsResolver` (`template/engine.go`) hard-requires
`working["stat_block"]` and errors with `"creature has no stat_block"`.
Hazard documents have no `stat_block`. Reuse needs a root parameter or a
hazard-side alias — see [Effects vocabulary](#effects-vocabulary-not-applicable)
for why you probably do not want to go there yet.

### Attacks

128 Strikes, 52 carrying traits (with magnitudes: `range 120 feet`,
`versatile S`, `deadly 1d12`).

```json
{
  "type": "stat_block_section", "subtype": "attack",
  "name": "Ranged", "attack_type": "ranged", "weapon": "water jet",
  "bonus": { "type": "stat_block_section", "subtype": "attack_bonus",
             "bonuses": [11] },
  "damage": [ { "type": "stat_block_section", "subtype": "attack_damage",
                "formula": "2d8", "damage_type": "piercing",
                "notes": "no multiple attack penalty" } ],
  "traits": [ /* enriched trait objects */ ]
}
```

`attack.note` exists on exactly one hazard and holds a note the source printed
where traits go (`"can target any creature in area A8"`). Creatures never have
it.

### Abilities

781 of them, and the shape is the creature `ability`. Worth knowing what is
actually populated:

`ability_type` (781) · `name` (781) · `trigger` (597) · `effect` (591) ·
`action_type` (636) · `links` (520) · `traits` (323) · `text` (179) ·
`failure` (159) · `success` (158) · `critical_failure` (157) ·
`critical_success` (151) · `stages` (24) · `universal_monster_ability` (4)

The four degrees of success sit **on the ability that rolled the save**, not
beside it as siblings. If you see them as standalone abilities you are reading
pre-`#157` data.

---

## `stealth` is a DC *or* a modifier, and you cannot derive which

GM Core 100: the Stealth entry is *"the Stealth modifier for a complex hazard's
initiative or the Stealth DC to detect a simple hazard, followed by the minimum
proficiency rank to detect the hazard (if any)."*

```json
{ "type": "stat_block_section", "subtype": "stealth", "name": "Stealth",
  "dc": 25, "proficiency": "trained" }
```

`dc` (339) and `value` (249) are mutually exclusive — the schema enforces
`oneOf`. `proficiency` is one of the five ranks. `note` carries anything else
printed.

**Do not infer the form from `complexity`.** 563 of 588 follow the convention,
but 19 Complex hazards publish a DC and 6 Simple ones publish a modifier.
Read the field that is present.

(Five hazards additionally have a `complexity` that disagrees with their own
Complex trait and Routine — `PFSRD2-Parser-kwr4`. Unresolved, and another
reason not to key behaviour off `complexity`.)

---

## Absence is meaningful

The same principle as the slot data: an absent field is a signal, not a hole.

- **322 hazards have no `ac`** and **397 have no `hp`** — there is nothing
  physical to attack. 116 of these are haunts. Rendering "AC —" is right;
  treating it as unknown data is not.
- **327 Simple hazards have no `routine`**, because a simple hazard fires once
  and is done. 253 of 266 Complex ones do.
- **`bt` without `hp`** never happens; `hp` without `bt` does (35 cases) — the
  source simply did not print a break threshold.

---

## Editions: the same machinery as equipment

**58 names are shared by more than one hazard.** 55 of those are
legacy/remastered pairs — separate documents, different `aonid`s, different
rules text. Use `alternate_link` (present on 116 documents) exactly as the
equipment indexer already does.

The other **3 are genuinely distinct same-edition hazards that share a name**:
Pathfinder #184 publishes two different *Glyph of Warding* (levels 13 and 14),
#157 two *Summoning Rune*. Their filenames carry the aonid
(`glyph_of_warding_263.json`) precisely because they collide.

**Never key on name.** Doubling results is the mild failure; silently
overwriting one is the one that already happened during development.

---

## Indexing

### First, the trap

`extract.py:walk_data` **auto-discovers content types** — it lists every
subdirectory of the pfsrd2-data checkout and treats the directory name as the
type. Nothing registers a type for walking.

So **the next index build will pick hazards up whether or not you have done
anything**, and route them through `GenericExtractor`, which reads
`data["traits"]` at the top level. Hazards keep traits at `hazard.traits`.

The result is 606 rows that look fine and are useless: `level` NULL, `attrs`
empty, `search_text` reduced to name plus source. Nothing errors. Do the work
below before the next build, or know that this is what you are looking at.

### Three places to register, only one mandatory

All in `pfsrd2-automation/pfsrd2/indexer/extract.py`:

| Place | Consequence of skipping it |
|---|---|
| `EXTRACTORS` (~line 897) | Falls back to `GenericExtractor` — the useless-rows case above |
| `_detect_schema_versions:prefix_to_dir` (~1039) | `hazard` → `hazards` currently works *by luck* (fallback is `prefix + "s"`). `weatherhazards/` has no schema file and defaults to `"1.0"`, also by luck — both break the moment the schema bumps to 1.1. Add `"hazard": "hazards"` and a `weatherhazards → hazards` alias in `schema_aliases` (~1071), same pattern as `npcs → monsters` |
| `_GAME_OBJ_TO_TYPE` (~1085) | **116 hazard files carry `alternate_link`.** Without `"Hazards"` and `"WeatherHazards"` entries, all 116 fail to resolve and silently bump the unresolved counter |

### What a `HazardExtractor` should emit

Read from `data["hazard"]`, not `stat_block`. `_core()` picks up `edition` for
free. `_trait_names(h["traits"])` works unchanged.

| `attrs` key | Source | Why |
|---|---|---|
| `level` | `hazard.level` | The primary encounter-building filter. Range -1..23 |
| `complexity` | `hazard.complexity` | `Simple` (328) / `Complex` (266) — the other primary filter |
| `traits` | `_trait_names(hazard.traits)` | `Trap` 335, `Magical` 220, `Mechanical` 167, `Environmental` 118, `Haunt` 116 |
| `hazard_type` | `game-obj` | Separates `WeatherHazards` from `Hazards` |
| `has_routine` | `"routine" in hazard` | Cheap proxy for "acts each round" |
| `stealth_dc` / `stealth_modifier` | `hazard.stealth.dc` / `.value` | Mutually exclusive; see above |
| `disable_skills` | skill links in `hazard.links` | "which hazards can Thievery disable" is the obvious query |

Into `search_text`: `description` above all, then `disable` and `routine` —
that is where the flavour lives. Ability and attack names are worth adding.

`level` and `complexity` want generated columns, since range and equality
filtering in SQL is the point:

```sql
ALTER TABLE entries ADD COLUMN hazard_level INTEGER
  GENERATED ALWAYS AS (json_extract(attrs,'$.level')) VIRTUAL;
ALTER TABLE entries ADD COLUMN complexity TEXT
  GENERATED ALWAYS AS (json_extract(attrs,'$.complexity')) VIRTUAL;
```

`traits` and `disable_skills` are lists — query with `json_each`, as the
equipment extractor already does for traits.

No migration is needed; the DB is rebuilt from scratch each run. Note that
`cli.py:build_index` prunes ghosts only for types present in the current walk,
so a `--type hazards` build is safe for everything else.

### The Go service needs no changes

`GET /types` is `SELECT type, COUNT(*) ... GROUP BY type`. The list route is a
chi wildcard `/{type}`, documents are `/{type}/{schemaVersion}/{book}/{filename}`,
and search takes `type` as an opaque string. There is no enum to extend —
`openapi.yaml` mentions types only in prose examples. **Hazards serve the
moment they are in the index.**

The exception is `attrs` filtering: `db.go:addAttrFilters` keys on
`$.traits`, `$.item_category`, `$.item_subcategory`. Hazards get those only if
the extractor populates them. Same for `db.Facets` and `db.SuggestTraits`.

### Deploy order

Indexer change → merge to main in `pfsrd2-automation` (auto-builds the staging
index) → nothing to deploy in `pfsrd2-data-api`. A running Lambda picks up the
new DB within the hour, or immediately via `POST /db/refresh`.

No auth to wire (there is none), no migrations, no codegen — both repos
hand-write their models, and `hazard.schema.1.0.json` is uploaded to S3 as a
static artifact used for nothing at runtime.

### Tests

`pfsrd2-automation/tests/test_extract.py` is stdlib-only, run as
`python3 tests/test_extract.py`. Its `test_extractors_never_store_dicts`
iterates `EXTRACTORS`, so it covers a new `HazardExtractor` automatically.

The Go repo has no `testdata/` — fixtures are inline Go literals. If you need a
hazard fixture, `template/offense_wrap_test.go` and `add_strike_test.go` have
the creature-shape literals to copy from.

### What hazards reference

Useful for cross-references. Outbound link targets across all 606 documents:

`Sources` 6365 · `Skills` 1077 · `Rules` 579 · `Conditions` 563 ·
`Traits` 510 · `Actions` 411 · `Spells` 268 · `Monsters` 46 ·
`Equipment` 32 · `MonsterAbilities` 17

The `Skills` volume is `disable` entries — that link is the backbone of any
"what can my rogue turn off" query.

---

## Effects vocabulary: not applicable

`pfsrd2-data-api`'s template engine (`service/internal/template/`) applies
`{target: JSONPath, operation}` effects through 13 operations — `adjustment`,
`add_modifier`, `add_strike`, `replace_one_die` and so on — and emits grouped
RFC 6902 patches. It drives monster templates and, via `itemapply.AsTemplate`,
rune applies.

**Hazards publish no effects and need none.** Nothing is applied *to* a hazard;
there is no hazard-template content type. They are content to render and query,
not to transform.

If that ever changes, two things block reuse: the engine requires a
`stat_block` root (hazards have none), and `abilityCategoryTargets` routes
abilities to creature-specific containers (`$.defense.reactive_abilities` and
friends) that hazards do not have. Leave it out of a first pass.

---

## Known gaps

Open tickets, none blocking consumption:

| Ticket | What |
|---|---|
| `PFSRD2-Parser-2lpx` | One hazard publishes a d6 random table as `<ol><li>`, so it renders as six abilities named `1`–`6`. Wheel of Misery only. |
| `PFSRD2-Parser-8631` | `parse_attack_damage` splits on `and`/`plus` inside parentheses, leaving a stray `)` in one damage note. |
| `PFSRD2-Parser-kwr4` | Five hazards whose `complexity` disagrees with their Complex trait and Routine. |

Nothing here loses data — all three are shape problems in published content
that is otherwise present.

---

## Provenance

Parser: `PFSRD2-Parser#154` (initial), `#157` (attacks, stealth, saving
throws). Data: `PFSRD2-Data#5`, `#6`.

Worth knowing when you hit something odd: the first pass parsed 606/606 files
with zero errors **and was still wrong in four ways** — degrees of success as
standalone abilities, break thresholds never captured, two hazards silently
overwritten by a filename collision, and a component's stats overwriting the
hazard's own. All produced schema-valid output. Five rounds of review found
them.

The lesson for you as a consumer: if a hazard looks wrong, it may well be
wrong. File it against the parser rather than working around it downstream —
47 source errors in `pfsrd2-web` were fixed during this work, and that is the
layer such problems belong in.
