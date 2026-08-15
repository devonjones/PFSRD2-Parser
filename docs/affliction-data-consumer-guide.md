# Affliction Data Consumer Guide

For work on top of `pfsrd2-data` now that **curses and diseases ship**. Written
against the two consumers that exist today:

- **`pfsrd2-automation`** — the indexer that builds `pfsrd2.db` from the JSON
- **`pfsrd2-data-api`** — the Go service that serves it

Neither knows about afflictions yet. This is what you need to add them.

Companion to [hazard-data-consumer-guide.md](hazard-data-consumer-guide.md).
Read that one first — this guide assumes its edition and indexing conventions.

The contract is `affliction.schema.1.0.json`, shipped with the data.

---

## What shipped

**99 documents across 23 books**, in two directories:

| Directory | `game-obj` | Count | Books |
|---|---|---|---|
| `curses/` | `Curses` | 55 | 12 |
| `diseases/` | `Diseases` | 44 | 11 |

Levels run **0 to 20** on 97 documents; 2 publish no number (see
[level is optional](#level-is-optional)). 54 legacy, 45 remastered. Every
document is PFS `Standard`.

**Key on `game-id`**, as with every other content type — all 99 are unique.
`aonid` is *not* a key on its own: only 78 are distinct, because `Curses` and
`Diseases` share an aonid space (`Curses.aspx?ID=42` and `Diseases.aspx?ID=42`
are unrelated). If you need the AoN id, key on `(game-obj, aonid)`.

### 19 curse aonids do not resolve

AoN lists 19 GM Core / Gatewalkers curses **twice** — two aonids, same book,
same page, same name, byte-identical bodies. `game-id` is
`md5("source: page: name")`, so both entries hash to one id: they are one
publication listed twice, not two curses.

The parser takes the later entry. So a handful of `Curses.aspx?ID=` values
(the earlier half of each pair) resolve to no document. That is intended —
`game-id` uniqueness is the contract, and shipping two documents under one id
would break the key you index on.

If you resolve inbound AoN links by aonid, expect misses on those 19 and fall
back to name.

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

| Field | curses (55) | diseases (44) | Shape |
|---|---|---|---|
| `level` | 54 | 43 | integer |
| `traits` | 54 | 38 | array of enriched `trait` |
| `saving_throw` | 39 | 44 | `save_dc` |
| `links` | 39 | 15 | array of `link` |
| `effect` | **36** | **0** | string |
| `stages` | **4** | **44** | array of `affliction_stage` |
| `onset` | 3 | 31 | string |
| `usage` | **15** | **0** | string |
| `tempted_curse` | **8** | **0** | string |
| `special` | 2 | 0 | string |
| `level_text` | 1 | 1 | string |
| `escalations` | 1 | 0 | array of `affliction_escalation` |

Read that as: **a disease is a staged progression** (all 44 have `stages`, 219
stage entries in total, 31 have an `onset`). **A curse is usually a single
standing effect** (36 of 55 carry `effect`; only 4 are staged). Anything
rendering both from one template needs to handle both shapes.

`usage`, `tempted_curse`, `effect` and `special` are curse-only. Do not build a
shared column expecting them on diseases.

---

## The integration trap: `affliction_stage` is not the creature shape

Both creature/hazard abilities and affliction documents emit objects with
`subtype: "affliction_stage"`. **The payloads are disjoint.**

| | count | keys |
|---|---|---|
| creature / hazard abilities | 711 | `name`, `type`, `subtype`, **`text`** |
| affliction documents | 219 | `name`, `type`, `subtype`, **`stage`**, **`effect`**, `duration`, `links` |

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

Of the 219 affliction stages: 189 carry a `duration`, 92 carry `links`. Stage
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

97 documents carry an integer `level`. **2 carry `level_text` instead** — the
badge reads `Curse Level Varies`, because the level depends on the item or
ritual that inflicted it.

The schema enforces exactly one of the two (`oneOf`), so:

- do not default a missing `level` to 0 — that is a fabricated number
- a level column must be nullable, with `level_text` carried alongside
- sorting by level must decide where the 2 go; putting them at the end is
  honest, putting them at 0 is not

---

## `saving_throw` has three shapes, and is sometimes absent

| shape | count | what it means |
|---|---|---|
| `dc` (integer) + `save_type` | 80 | the normal case |
| `text` + `save_type`, **no `dc`** | 3 | the source published a formula, not a number |
| absent | 16 | the source published no save at all |

The 3 without a DC are real published text like *"Will save, with a high spell
DC for a monster of its level"*. The parser deliberately does not invent a
number for these. A `dc` column must be nullable and the `text` preserved.

`save_type` is `Fort` (57) or `Will` (26) — no affliction in the corpus uses
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
- 19 curses have no `effect` — they are the staged ones, or carry the mechanics
  in `description`

Do not fill these with defaults.

---

## Editions

Same machinery as hazards and equipment: 54 legacy, 45 remastered, with
`alternate_link` on 30 documents (15 pointing at a legacy counterpart, 15 at a
remastered one).

**Edition drives the licence.** Legacy content is OGL, remastered is ORC, and
`doc.license` reflects it. If you display or export licence text, it must come
from the document rather than a per-repo constant.

> Historical note worth knowing: until this release, 394 of 594 hazards and 39
> afflictions were mislabelled `remastered` — and therefore carried the wrong
> licence notice. If you have a cached index built before the affliction
> release, **rebuild it**; the edition and licence fields on hazards changed
> underneath you.

---

## Indexing

### What an `AfflictionExtractor` should emit

Two content types sharing one extractor, on the equipment pattern:

```python
{
  "game_id":   doc["game-id"],        # primary key — unique across all 99
  "aonid":     doc["aonid"],          # NOT unique alone; pair with game_obj
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

Primary key `game_id`. Add a unique index on `(game_obj, aonid)` too — it is
the right key for resolving an inbound AoN link, and it will hold.

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

Parser: `pfsrd2/affliction.py`, merged in **PFSRD2-Parser#162**.

Both content types parse with **zero errors**. Every field count in this guide
was measured against the shipped JSON, and cross-checked 1:1 against the source
HTML (`Saving Throw`, `Onset`, `Effect`, `Usage`, `Special`, `Stage N`).
