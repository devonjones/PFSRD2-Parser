# Ability Enrichment System

## Problem

Monster abilities have a schema that already supports structured fields (damage, saving_throw, range, frequency, effect, trigger, etc.) but most abilities only have these mechanics in the `text` field. This matters for:

1. **Monster templates** (elite, weak, etc.) — need to know if an ability has frequency/damage to apply correct adjustments (+2 damage default, +4 for limited-use)
2. **Monster families** — need structured ability data
3. **MonsterLab** (planned tool) — needs a repository of structured ability data

Many abilities are shared across multiple creatures and should only be structured once.

## Architecture

### Separate SQLite Database

The enrichment database lives at `~/.pfsrd2/ability_enrichment.db`, separate from the main `pfsrd2.db` which gets rebuilt by `pf2_run_deps.sh`. Enrichments accumulate over time (regex, LLM, manual review) and must survive rebuilds.

### Database Schema

```sql
ability_records:
  ability_id INTEGER PK
  name TEXT NOT NULL
  identity_hash TEXT NOT NULL UNIQUE  -- hash of normalized ability fields
  raw_json TEXT NOT NULL              -- full ability object as JSON
  enriched_json TEXT                  -- enriched ability object, nullable
  enrichment_version INT              -- null = unenriched
  extraction_method TEXT              -- 'regex', 'llm:qwen', 'manual', null
  human_verified BOOLEAN DEFAULT false
  stale BOOLEAN DEFAULT false
  created_at TEXT
  updated_at TEXT

ability_creature_links:
  ability_id INTEGER FK
  creature_game_id TEXT NOT NULL
  creature_name TEXT NOT NULL
  creature_level INT
  creature_traits TEXT                -- JSON array of trait names
  source_name TEXT
  UNIQUE(ability_id, creature_game_id)
```

### Identity Hash

Built from the ability object fields that define its identity: `name`, `text`, `effect`, `frequency`, `trigger`, `requirement`, `cost`, `action_type.name`, and sorted trait names. Normalized (strip, collapse whitespace, NFC normalize) then hashed.

### Parser Integration

`ability_enrichment_pass(struct)` runs after `monster_ability_db_pass`, before `license_pass`.

- **First run**: populates DB with raw ability records + creature links. Zero changes to JSON output.
- **Subsequent runs**: if enriched record exists and isn't stale, merges structured fields into ability object. Text field is untouched — enrichment adds structured peers alongside it.
- **Text changes**: if identity hash doesn't match, marks existing record stale, updates raw_json.

### Enrichment Versioning

- `enrichment_version` tracks which version of the extraction code produced the data
- Bump version when extraction code changes significantly
- Offline process re-runs records where `enrichment_version < current_version`
- Records with `human_verified = true` are skipped unless explicitly forced

### Schema Extensions

Added to creature schema:

**`area` definition** (new):
```json
"area": {
  "type": "object",
  "properties": {
    "type": {"enum": ["stat_block_section"]},
    "subtype": {"enum": ["area"]},
    "text": {"type": "string"},
    "shape": {"enum": ["line", "cone", "burst", "emanation", "wall", "cylinder"]},
    "size": {"type": "integer"},
    "unit": {"enum": ["feet", "miles"]}
  },
  "required": ["type", "subtype", "text"],
  "additionalProperties": false
}
```

**`basic` boolean** added to `save_dc` definition.

**`area` field** added to `ability` definition.

All new fields are optional — existing creatures pass validation unchanged.

### Offline Enrichment Pipeline (tiered)

1. **Regex tier** — conservative patterns for DC/save, XdY damage, X-foot area shapes, frequency. Targets ~70-80%.
2. **LLM tier** (future) — for abilities with mechanical keywords that resist regex.
3. **Manual tier** — CLI tool for human review and editing.

### CLI Tools

**`bin/pf2_enrich_abilities`** — offline enrichment runner. Processes unenriched records, respects enrichment_version, skips human_verified.

**`bin/pf2_ability_review`** — inspection and manual review:
- `stats` — enrichment counts by status
- `show <name>` — display ability with raw and enriched JSON
- `list --unenriched|--stale|--method regex` — filter abilities
- `verify <hash>` — mark human_verified
- `edit <hash>` — open in $EDITOR
- `creatures <hash>` — list creatures with this ability

## Phased Implementation

### Phase 1: Schema Updates
- Add `area` definition, `basic` on `save_dc`, `area` field on `ability`
- Bump schema_version
- Zero output changes

### Phase 2: Enrichment DB Module
- `pfsrd2/sql/ability_enrichment.py` — tables, CRUD
- `pfsrd2/sql/ability_enrichment_db.py` — separate connection + version chain
- `pfsrd2/ability_identity.py` — deterministic identity hash
- Unit tests

### Phase 3: Population Pass
- `ability_enrichment_pass()` wired into creature parser
- First run: DB-only, zero JSON changes
- Subsequent runs: detect text changes, mark stale

### Phase 4: Regex Extraction (Offline)
- `pfsrd2/enrichment/regex_extractor.py` — conservative patterns
- `bin/pf2_enrich_abilities` CLI
- Reuse patterns from `universal/creatures.py` (`universal_handle_save_dc`, `universal_handle_range`)

### Phase 5: Enrichment Application
- Pass merges enriched fields into ability objects
- Text untouched, structured fields added alongside

### Phase 6: CLI Review Tool
- `bin/pf2_ability_review` — inspect, edit, verify enrichments

### Phase 7 (Future): LLM Enrichment Tier

## Dependency Graph

```
Phase 1 (schema) ──────────────────────────┐
                                            │
Phase 2 (DB module) ───┐                    │
                        ▼                   │
Phase 3 (population) ──┤                    │
                        │                   │
Phase 4 (regex) ────────┤                   │
                        ▼                   ▼
Phase 5 (application) ── needs 1, 3, 4
                        │
Phase 6 (CLI) ── needs 2, 3
```

## Data Scale

~16,863 unique abilities across ~4,565 creature/NPC files (~32,080 total ability instances). From sampling: ~1,260 DCs, ~691 dice expressions, ~346 area patterns trapped in text per 500 creatures.
