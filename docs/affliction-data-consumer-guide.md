# Affliction Data Consumer Guide

For work on top of `pfsrd2-data` now that **curses and diseases ship**. Written
against the two consumers that exist today:

- **`pfsrd2-automation`** — the indexer that builds `pfsrd2.db` from the JSON
- **`pfsrd2-data-api`** — the Go service that serves it

Neither knows about afflictions yet. This is what you need to add them.

Companion to [hazard-data-consumer-guide.md](hazard-data-consumer-guide.md).
Read that one first — this guide assumes its edition and indexing conventions,
and **contradicts one of them on purpose** (see the next section).

The contract is `affliction.schema.1.0.json`, shipped with the data.

---

## Read this first: `game-id` is not unique here

The hazard guide says "key on `game-id`, not `aonid` — all 606 `game-id`s are
unique." **That advice does not carry over.** For afflictions:

| key | unique? |
|---|---|
| `aonid` | ✗ — 81 distinct across 118 documents |
| `game-id` | ✗ — 99 distinct across 118 documents |
| **(`game-obj`, `aonid`)** | ✓ — **118 of 118** |

Two independent reasons:

1. **`aonid` collides across directories.** `Curses.aspx?ID=42` and
   `Diseases.aspx?ID=42` are unrelated entities. 37 aonids appear in both
   trees.
2. **`game-id` collides within a directory.** It is derived from name +
   `game-obj`, not from `aonid`. AoN publishes 19 GM Core / Gatewalkers curses
   **twice**, under two aonids with the same name in the same book — so both
   documents hash to the same `game-id`.

If you key on `game-id`, you will silently drop 19 curses or hit a unique
constraint. **Key on the pair.**

---

## What shipped

**118 documents across 23 books**, in two directories:

| Directory | `game-obj` | Count | Books |
|---|---|---|---|
| `curses/` | `Curses` | 74 | 12 |
| `diseases/` | `Diseases` | 44 | 11 |

Levels run **0 to 20** on 115 documents; 3 publish no number (see
[level vs level_text](#level-is-optional)). 64 remastered, 54 legacy. Every
document is PFS `Standard`.

### The 19 duplicated curses

38 files carry an aonid suffix — `thiefs_retribution_28.json` and
`thiefs_retribution_90.json`. Those are the two halves of a duplicate pair,
not two different curses: the bodies are byte-identical apart from the id.

They are both written deliberately, so that **every published `Curses.aspx` id
resolves to a document**. Before this, one silently overwrote the other and 19
aonids resolved to nothing.

For a consumer this means:

- **do not** assume one file per name, or one file per `game-id`
- **do** expect `(game-obj, aonid)` to be 1:1 with files
- if you surface afflictions by name, dedupe on `game-id` and pick either —
  they are the same content

---

## Document shape

Afflictions follow the `feat`/`spell`/`hazard` convention, **not** the creature
one: a single flat object under an `affliction` key.

```
creature:    doc.stat_block.defense.hp
hazard:      doc.hazard.hp
affliction:  doc.affliction.saving_throw
```

Top level, always present:

```
affliction  aonid  edition  game-id  game-obj  license  name  pfs
schema_version  sources  type
```

Plus `alternate_link` on 30 documents and `sections` on 5 (spoiler warnings —
see [Known gaps](#known-gaps)).

### `doc.affliction` field census

Always present: `name`, `type`, `subtype`, `affliction_type`, `description`,
`sources`.

The split by type is the useful part — **curses and diseases are modelled
differently by the source, not by the parser**:

| Field | curses (74) | diseases (44) | Shape |
|---|---|---|---|
| `level` | 72 | 43 | integer |
| `traits` | 73 | 38 | array of enriched `trait` |
| `saving_throw` | 58 | 44 | `save_dc` |
| `links` | 52 | 15 | array of `link` |
| `effect` | **53** | **0** | string |
| `stages` | **6** | **44** | array of `affliction_stage` |
| `onset` | 4 | 31 | string |
| `usage` | **15** | **0** | string |
| `tempted_curse` | **8** | **0** | string |
| `level_text` | 2 | 1 | string |
| `special` | 2 | 0 | string |
| `escalations` | 1 | 0 | array of `affliction_escalation` |

Read that as: **a disease is a staged progression** (all 44 have `stages`,
228 stage entries total, 31 have an `onset`). **A curse is usually a single
standing effect** (53 of 74 carry `effect`; only 6 are staged). Anything that
renders both from one template needs to handle both shapes.

`usage` and `tempted_curse` are curse-only. `effect` is curse-only. Do not
build a shared column expecting them on diseases.

---

## The integration trap: `affliction_stage` is not the creature shape

Both creature/hazard abilities and affliction documents emit objects with
`subtype: "affliction_stage"`. **The payloads are disjoint.**

| | count | keys |
|---|---|---|
| creature / hazard abilities | 711 | `name`, `type`, `subtype`, **`text`** |
| affliction documents | 228 | `name`, `type`, `subtype`, **`stage`**, **`effect`**, `duration`, `links` |

```jsonc
// creature or hazard — prose and duration unsplit, in `text`
{"name": "Stage 1", "subtype": "affliction_stage",
 "text": "carrier with no ill effect (1 minute)"}

// affliction document — split, and numbered
{"name": "Stage 1", "subtype": "affliction_stage", "stage": 1,
 "effect": "sickened 1", "duration": "1 day",
 "links": [{"name": "sickened", "game-obj": "Conditions", "aonid": 29}]}
```

Code that reads `stage["text"]` **KeyErrors on every affliction document**, and
code that reads `stage["effect"]` KeyErrors on all 711 creature/hazard stages.
Branch on the presence of `stage`, or normalise at the boundary.

This divergence is deliberate and documented in the schema; unifying the two is
tracked as **PFSRD2-Parser-3xoc**. Do not build anything that assumes it will
stay this way in both directions.

Of the 228 affliction stages: 197 carry a `duration`, 94 carry `links`. Stage
numbers are always a run from 1 — the parser asserts it.

---

## `escalations` — a shape you have not seen before

One document (`All-Consuming Hubris`, 2 entries) uses this. An adventure-path
curse can grow stronger as the story runs, published as bold `Curse 5` /
`Curse 6` labels on a curse whose own badge reads `Curse 4`.

```jsonc
{"name": "Curse 5", "subtype": "affliction_escalation", "level": 5,
 "effect": "At the beginning of Chapter 2, increase the spirit damage to 2d10..."}
```

An escalation is **not** a stage. A stage is a step through one affliction; an
escalation replaces the whole thing with a higher-level version. Rendering them
as stages would invent a staged curse that does not exist.

It is one document today, so it is safe to ignore initially — but the field is
in the schema and will not be removed.

---

## `level` is optional

115 documents carry an integer `level`. **3 carry `level_text` instead** — the
badge reads `Curse Level Varies`, because the level depends on the item or
ritual that inflicted it.

The schema enforces exactly one of the two (`oneOf`), so:

- do not default a missing `level` to 0 — that is a fabricated number
- a level column must be nullable, with `level_text` carried alongside
- sorting by level must decide where the 3 go; putting them at the end is
  honest, putting them at 0 is not

---

## `saving_throw` has three shapes, and is sometimes absent

| shape | count | what it means |
|---|---|---|
| `dc` (integer) + `save_type` | 98 | the normal case |
| `text` + `save_type`, **no `dc`** | 4 | the source published a formula, not a number |
| absent | 16 | the source published no save at all |

The 4 without a DC are real published text like *"Will save, with a high spell
DC for a monster of its level"*. The parser deliberately does not invent a
number for these. A `dc` column must be nullable and the `text` preserved.

`save_type` is `Fort` (66) or `Will` (36) — no affliction in the corpus uses
Reflex. Do not hardcode that; the vocabulary is the shared one.

---

## Absence is meaningful

Same rule as hazards. The parser is brittle by design: an unrecognised label
fails the file rather than being dropped. So a missing field means **the source
did not publish it**, not that parsing failed.

Concretely:

- 16 afflictions genuinely have no saving throw
- 7 have **no traits at all** (1 curse, 6 diseases) — the source publishes no
  trait spans on those pages. Not a parse gap.
- 21 curses have no `effect` — they are the staged ones, or carry the mechanics
  in `description`

Do not fill these with defaults.

---

## Editions

Same machinery as hazards and equipment: 64 remastered, 54 legacy, with
`alternate_link` on 30 documents (15 pointing at a legacy counterpart, 15 at a
remastered one).

**Edition drives the licence.** Legacy content is OGL, remastered is ORC, and
`doc.license` reflects it. If you display or export licence text, it must come
from the document rather than a per-repo constant.

> Historical note worth knowing: until this release, 394 of 594 hazards and 39
> afflictions were mislabelled `remastered` — and therefore carried the wrong
> licence notice. If you have a cached index built before
> `PFSRD2-Data` commit `9ce1e319e`, **rebuild it**; the edition and licence
> fields on hazards changed underneath you.

---

## Indexing

### What an `AfflictionExtractor` should emit

Two content types sharing one extractor, on the equipment pattern:

```python
{
  "game_id":   doc["game-id"],        # NOT unique — see the top of this guide
  "aonid":     doc["aonid"],
  "game_obj":  doc["game-obj"],       # "Curses" | "Diseases"
  "name":      doc["name"],
  "edition":   doc["edition"],
  "level":     doc["affliction"].get("level"),        # nullable
  "level_text": doc["affliction"].get("level_text"),  # nullable
  "affliction_type": doc["affliction"]["affliction_type"],  # "curse" | "disease"
  "save_dc":   (doc["affliction"].get("saving_throw") or {}).get("dc"),  # nullable
  "save_type": (doc["affliction"].get("saving_throw") or {}).get("save_type"),
  "stage_count": len(doc["affliction"].get("stages", [])),
  "json":      doc,
}
```

**Primary key `(game_obj, aonid)`.** Index `game_id` non-uniquely — it is still
the right key for "show me this affliction regardless of which duplicate entry
the user hit."

### What afflictions reference

`links` point at `Conditions` (overwhelmingly), `Traits`, `Skills`, `Actions`,
`Sources` and `Rules`. Nothing points *at* afflictions from creature or hazard
documents yet — creature afflictions are inline ability text, not links. So
there is no back-reference to resolve, and no ordering constraint on load
beyond traits and sources existing first.

### Deploy order

1. Load traits and sources (unchanged).
2. Load afflictions — no dependency on creatures or hazards.
3. **Reload hazards.** Their edition and licence changed in the same release.

---

## Known gaps

- **5 disease documents carry a top-level `sections` entry** holding a spoiler
  warning (*"This Disease may contain spoilers from the Rusthenge Adventure"*).
  It is real published content with a name and no body. Render it or ignore it;
  do not treat it as a parse artefact.
- **`affliction_stage` divergence** from the creature/hazard shape —
  PFSRD2-Parser-3xoc.
- **No affliction ↔ creature linkage.** A ghoul's *Ghoul Fever* ability and the
  `Diseases` document for it are not connected in the data. Matching them by
  name is possible but unverified, and out of scope here.
- **`escalations`** is a one-document feature; treat it as experimental.

---

## Provenance

Parser: `pfsrd2/affliction.py`, merged in **PFSRD2-Parser#162**
(`d2af706`). Data: **PFSRD2-Data#7** (`9ce1e319e`).

Both content types parse with **zero errors**. Every field count in this guide
was measured against the shipped JSON, and cross-checked 1:1 against the source
HTML (`Saving Throw`, `Onset`, `Effect`, `Usage`, `Special`, `Stage N`).
