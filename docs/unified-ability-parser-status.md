# Unified Ability Parser — Status & Next Steps

## What We Built

### `universal/ability.py`
A single ability parser that replaces independent implementations across parsers. Two entry points:

- **`parse_abilities_from_nodes(nodes)`** — parses `<br>`-delimited BS4 node sequences into structured ability objects. Used by monster families and templates.
- **`parse_ability_from_html(name, html_text)`** — parses a single ability from HTML text. Ready for creatures, feats, skills (not yet wired).

### What It Handles
- **Action types**: extracted from `<span class="action">` elements via `extract_action_type()` from `action.py`
- **Traits**: extracted in two passes — first from parenthesized text, then after action extraction (handles both `(traits) [action]` and `[action] (traits)` ordering)
- **Addon fields**: Requirements, Trigger, Effect, Frequency, Cost, Duration, etc. merged into preceding ability
- **Result blocks**: Critical Success, Success, Failure, Critical Failure
- **Affliction detection**: Saving Throw OR Stage N → `ability_type: "affliction"` (afflictions are abilities, not a separate type)
- **Saving throw parsing**: produces array of `save_dc` objects (structured when DC present, text-only fallback). Only catches ValueError, not AssertionError — assertion failures propagate (strategic fragility).
- **Damage parsing**: produces array of `attack_damage` objects via creature parser's `parse_attack_damage`. Only catches ImportError — assertion failures propagate.
- **Universal monster ability detection**: from `<a>` links to MonsterAbilities.aspx (both `<a><b>Name</b></a>` and `<b><a>Name</a></b>` patterns)
- **Non-ability name blocklist**: "Related Groups", "Source" — prevents structural labels from being parsed as abilities
- **Aura parsing**: abilities with `aura` trait get range/damage/DC extracted from the first sentence into structured fields. Assertions fire when the first sentence has aura stats keywords but doesn't parse — fix is in the HTML (pull structured data to comma-separated format at start, keep remaining text intact).
- **Strategic fragility assertions**: `_assert_no_unextracted_frontmatter` fails fast on literal `[action]` text in first 30 chars, and on unextracted parenthesized traits at text start (multiple comma-separated lowercase words). Fix is always in the HTML, not the parser.

### `universal/monster_ability.py`
Database pass that enriches abilities with full universal monster ability records. Looks up by link to MonsterAbilities OR by presence of UMA skeleton from parser. Strips `schema_version`, `license`, and `trait_template` entries from DB records. Removes incomplete skeletons when DB lookup fails.

### Ability Enrichment Pipeline
- **`pfsrd2/ability_enrichment.py`** — two passes:
  - `ability_enrichment_pass(struct)` — for creatures. Populates enrichment DB with ability records + creature links. Merges enriched fields back. Wires up UMAs from monster abilities DB (lazy connection, only opened when needed).
  - `template_ability_enrichment_pass(struct)` — for families/templates. Same enrichment, plus applies `ability_category` and deterministic classification. No creature links created.
- **`pfsrd2/enrichment/llm_cache.py`** — persistent LLM response cache at `~/.pfsrd2/llm_cache.db`. Keyed on `(prompt_hash, model)`. Survives enrichment DB rebuilds. Prompt template changes automatically invalidate stale entries.
- **`pfsrd2/ability_placement.py`** — category lookup for ability routing in change enrichment. Maps ability names to JSONPath targets using majority vote from creature data.

### Ability Classification
Every template/family ability gets an `ability_category` field:
1. **Deterministic** (action type): Reaction → `reactive`, 1/2/3 actions → `offensive`, Free Action + trigger → `reactive`. Runs first, no DB needed.
2. **Creature links**: Direct copy from `ability_creature_links.ability_category`.
3. **Name lookup**: Case-insensitive match against creature data (majority vote).
4. **UMA detection**: Name match against `monster_abilities` table in pfsrd2.db.
5. **LLM**: Ollama classify with stat block structure prompt. Default to `offensive` when uncertain.

Valid categories: `offensive`, `automatic`, `reactive`, `interaction`, `special_sense`, `hp_automatic`, `communication`

**Not categorized**: result blocks (Critical Success/Failure), affliction stages (Stage N), spell noise (~900 records of spell levels/list items parsed as abilities — PFSRD2-Parser-udk4).

**Creature abilities** get category stored in enrichment DB but NOT in JSON output (redundant with stat block position). Template/family abilities get it in JSON.

### Creature `special_senses`
Special senses now produce `subtype: "ability"` with `ability_type: "special_sense"` instead of `subtype: "special_sense"`. They participate in enrichment like any other ability — getting UMA objects, enriched fields, etc.

## Current Migration Status

| Parser | Status | Notes |
|--------|--------|-------|
| Monster families | ✅ 191/191 passing | Fully migrated, enrichment wired |
| Monster templates | ✅ 55/55 passing | Fully migrated, enrichment wired |
| Creatures | ❌ Not migrated | PFSRD2-Parser-ob6w (ability parsing only — enrichment IS wired) |
| Feats | ❌ Not migrated | PFSRD2-Parser-91hd |
| Skills | ❌ Not migrated | PFSRD2-Parser-91hd |
| Equipment | N/A | Stays separate (activation system is fundamentally different) |

## Schema State

Monster family and template schemas have **identical** ability definitions with 35 properties (34 + `ability_category`). Creature schema has 34 (no `ability_category` — intentional, category is redundant with stat block position).

Key schema decisions:
- `ability_type` required on all abilities
- `ability_category` enum on family/template schemas only: `[offensive, automatic, reactive, interaction, special_sense, hp_automatic, communication]`
- `save_dc.dc` optional (template rules don't always specify DC)
- Trait `required` relaxed to `[name, type]` (ability-level traits are minimal)
- Trait `type` allows both `"trait"` and `"stat_block_section"`
- UMA `required`: `[name, type, game-id, game-obj]` — game-id comes from DB pass

## Lessons Learned

### Pipeline Ordering Matters
- **Ability extraction MUST run before link pass** — `monster_family_link_pass` unwraps `<a>` tags, destroying the `game-obj="Traits"` attributes that `extract_starting_traits` needs.
- **UMA DB pass MUST run after edition detection** — needs `struct["edition"]` to pick the right DB record.
- **Trait extraction needs two passes** — traits can appear before OR after action spans.
- **Enrichment DB writes MUST be sequential** — SQLite silently drops concurrent writes. Never run parsers in parallel when they write to enrichment.db.
- **Abilities must be enriched before changes** — change records contain abilities. If abilities get enriched (category, UMA, mechanics), re-run families/templates to update the change records before running change enrichment.

### HTML Quality Issues
- **Template leaks**: `<t>`, `<action.types#2%%>`, `<rules%235%%>`, `<TABLESHTML#208%%>` — server-side template strings leaking into HTML. Fixed by manual removal.
- **Missing trait links**: Bare text traits `(disease)` need linked `(<a href="Traits.aspx?ID=46">disease</a>)`. The parser asserts on unextracted traits (strategic fragility). Fix is in HTML.
- **Wrong trait links**: `aura` linking to `MonsterAbilities.aspx` instead of `Traits.aspx`. Fixed by correcting the href.
- **Missing ability links**: `<b>Change Shape</b>` without `<a href="MonsterAbilities.aspx">` wrapper. Enrichment UMA detection handles this by name lookup.
- **Both `<a><b>` and `<b><a>` patterns**: The parser handles both — `<a>` wrapping `<b>` and `<b>` wrapping `<a>`. Both extract the link correctly.
- **Literal action text**: `[one-action]`, `[two-actions]`, `[reaction]` as text instead of `<span class="action">`. The parser asserts on these. Fix by adding the proper span in HTML.
- **Missing period after aura range**: e.g., `10 feet A creature entering` needs `10 feet. A creature entering`. The aura parser splits on the first period.
- **Non-numeric DCs in auras**: e.g., `DC equal to the siabrae's spell DC – 4`. Pull the range to front as `20 feet.` and leave the DC in the description text.
- **Bold game terms in trigger text**: `<b>Strike</b>` as a game term inside trigger text gets parsed as a new ability. Change to `<strong>Strike</strong>` — the parser only treats `<b>` as ability name delimiters, not `<strong>`.
- **Missing space after link close tags**: `concealment</a>caused` needs `concealment</a> caused`.

### When Fixing HTML for Auras
Pull structured data (range, DC) to comma-separated format at the front of the aura text. Keep the remaining description text intact — don't rewrite it:
```
BEFORE: ) The air within 5 feet of the ghost is supernaturally cold.
AFTER:  ) 5 feet. The air within 5 feet of the ghost is supernaturally cold.
```

### Content Filter Lessons
- **Don't promote h3 to h2** — `parse_universal`'s `title_collapse_pass` handles the heading hierarchy.
- **Keep the h3 body split** — needed for `parse_universal` to create proper sections.
- **Don't unwrap action spans** — the unified parser needs them intact.
- **h4 support added** — `subtitle_pass` now handles `<h4>` when `max_title >= 4`.

### Non-Ability Bold Labels
"Related Groups" appears as `<b>Related Groups</b>` in 86+ files. Fixed with `_NOT_ABILITY_NAMES` blocklist in code (not 86 HTML fixes).

### Trait Extraction Bug Fix
`_extract_trait` in `trait.py` was dropping the opening `(` when parenthesized text wasn't a trait (e.g., `(Frailty)`). Fixed by preserving the `(` in the else branch. Non-trait parenthesized text stays in the ability text as-is.

### Leading Semicolons
After trait extraction, text sometimes starts with `;` (e.g., `(divine, necromancy); When...` → `; When...`). The unified parser cleans leading semicolons after trait extraction.

## Next Steps

### Phase 2: Migrate Creature Parser (PFSRD2-Parser-ob6w)
The creature parser has 4 nested ability functions inside `creature_stat_block_pass`. These work on tuples from `split_stat_block_line`, not BS4 nodes. Options:
1. Reconstruct HTML from tuple fields and call `parse_ability_from_html` (lower risk)
2. Rework tuple splitting to pass raw nodes (cleaner but bigger change)

### Phase 3: Migrate Feat/Skill Parsers (PFSRD2-Parser-91hd)
Lower risk — fewer files, simpler structure.

### Open Tickets
- **PFSRD2-Parser-ob6w**: Migrate creature parser to unified ability parser
- **PFSRD2-Parser-91hd**: Migrate feat/skill parsers
- **PFSRD2-Parser-pigb**: Universalize creature spell parser for families/templates
- **PFSRD2-Parser-udk4**: Spells parsed as abilities in monster families/templates (~900 records)
- **PFSRD2-Parser-165k**: Add unit tests for ability enrichment pipeline new code (P1)
- **PFSRD2-Parser-9n48**: Fix abilities with inconsistent category across creatures
- **PFSRD2-Parser-k1k9**: Fix wrong effect targets in change enrichment
- **PFSRD2-Parser-l6s8**: Deduplicate `_extract_abilities_from_bs` across parsers
- **PFSRD2-Parser-jp6d**: Refactor `run_classify`/`run_llm_classify` complexity
- **PFSRD2-Parser-1ipj**: 'Saving Throw' parsed as standalone ability instead of addon
- **PFSRD2-Parser-zezi**: Extract shared schema definitions into reusable files
- **PFSRD2-Parser-npfy**: Monster family sections tree unmodified by consolidation
- **PFSRD2-Parser-h68p**: Extract images from monster family pages

### Known Remaining Issues
- **Spell noise**: ~900 enrichment records are spell levels/list items from families (PFSRD2-Parser-udk4, blocked by PFSRD2-Parser-pigb)
- **~5 borderline `special_sense` classifications**: Abilities like "Burning Eyes" and "Eager for Battle" that grant senses but aren't purely senses. Tracked in PFSRD2-Parser-9n48.
- **Result blocks as separate abilities**: Critical Success/Failure/Stage N appear as standalone abilities in some families instead of nested in their parent ability.

## File Reference

| File | Purpose |
|------|---------|
| `universal/ability.py` | Unified ability parser (action types, traits, addons, afflictions, auras) |
| `universal/monster_ability.py` | Universal monster ability DB pass |
| `universal/creatures.py` | `universal_handle_special_senses` — now produces `subtype: "ability"` |
| `pfsrd2/ability_enrichment.py` | Enrichment passes for creatures and templates/families |
| `pfsrd2/ability_placement.py` | Category lookup for ability routing in change enrichment |
| `pfsrd2/ability_identity.py` | Identity hashing for abilities |
| `pfsrd2/enrichment/llm_extractor.py` | LLM prompts for mechanics extraction + category classification |
| `pfsrd2/enrichment/llm_cache.py` | Persistent LLM response cache |
| `pfsrd2/enrichment/regex_extractor.py` | Regex extraction for ability mechanics |
| `pfsrd2/change_extraction.py` | Change/li extraction (uses unified parser for abilities) |
| `pfsrd2/monster_family.py` | Monster family parser (fully migrated) |
| `pfsrd2/monster_template.py` | Monster template parser (fully migrated) |
| `pfsrd2/sql/enrichment/` | Enrichment DB connection, migrations, queries |
| `bin/pf2_enrich_abilities` | Offline enrichment CLI (regex, LLM, classify, UMA) |
| `bin/pf2_enrich_changes` | Offline change enrichment CLI |
| `tests/test_unified_ability.py` | 32 unit tests for unified parser |
| `tests/test_ability_enrichment.py` | Tests for creature ability enrichment pass |
| `docs/enrichment-process.md` | Enrichment pipeline documentation |
| `.claude/skills/rebuild-enrichment.md` | Skill for managing full enrichment rebuilds |
