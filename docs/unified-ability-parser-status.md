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
- **Affliction detection**: Saving Throw + Stage N → `ability_type: "affliction"` (afflictions are abilities, not a separate type)
- **Saving throw parsing**: produces array of `save_dc` objects (structured when DC present, text-only fallback)
- **Damage parsing**: produces array of `attack_damage` objects
- **Universal monster ability detection**: from `<a>` links to MonsterAbilities.aspx
- **Non-ability name blocklist**: "Related Groups", "Source" — prevents structural labels from being parsed as abilities

### `universal/monster_ability.py`
Database pass that enriches abilities with full universal monster ability records. Looks up by link to MonsterAbilities OR by presence of UMA skeleton from parser. Strips `schema_version`, `license`, and `trait_template` entries from DB records. Removes incomplete skeletons when DB lookup fails.

## Current Migration Status

| Parser | Status | Notes |
|--------|--------|-------|
| Monster families | ✅ 191/191 passing | Fully migrated, DB pass wired |
| Monster templates | ✅ 55/55 passing | Fully migrated, DB pass wired |
| Creatures | ❌ Not migrated | PFSRD2-Parser-ob6w |
| Feats | ❌ Not migrated | PFSRD2-Parser-91hd |
| Skills | ❌ Not migrated | PFSRD2-Parser-91hd |
| Equipment | N/A | Stays separate (activation system is fundamentally different) |

## Schema State

All three schemas (creature, monster_family, monster_template) have **identical** ability definitions with 34 properties using the same `$ref` definitions. Shared definitions copied from creature: `range`, `save_dc`, `attack_damage`, `area`, `modifiers`, `modifier`, `affliction_stage`, `traits`, `trait`, `universal_monster_ability`.

Key schema decisions:
- `ability_type` required on all abilities
- `save_dc.dc` optional (template rules don't always specify DC)
- Trait `required` relaxed to `[name, type]` (ability-level traits are minimal)
- Trait `type` allows both `"trait"` and `"stat_block_section"`
- UMA `required`: `[name, type, game-id, game-obj]` — game-id comes from DB pass

## Lessons Learned

### Pipeline Ordering Matters
- **Ability extraction MUST run before link pass** — `monster_family_link_pass` unwraps `<a>` tags, destroying the `game-obj="Traits"` attributes that `extract_starting_traits` needs. Fixed by moving `_extract_section_abilities` before `monster_family_link_pass`.
- **UMA DB pass MUST run after edition detection** — needs `struct["edition"]` to pick the right DB record.
- **Trait extraction needs two passes** — traits can appear before OR after action spans: `(divine, void) [free-action]` vs `[one-action] (arcane, transmutation)`. The parser tries `extract_starting_traits` before `extract_action_type`, then again after.

### HTML Quality Issues
- **Template leaks**: `<t>`, `<action.types#2%%>`, `<rules%235%%>`, `<TABLESHTML#208%%>` — server-side template strings leaking into HTML. lxml parses these as tags that wrap subsequent content, breaking the heading hierarchy. Fixed by downloading fresh HTML (most fixed on live site) or manual removal.
- **Missing trait links**: Some legacy HTML has bare text traits `(disease)` instead of linked `(<a href="Traits.aspx?ID=46">disease</a>)`. The trait parser requires `game-obj="Traits"` on links to detect them. Fixed by adding links to the HTML.
- **Missing ability links**: Some families have `<b>Change Shape</b>` without the `<a href="MonsterAbilities.aspx?ID=55">` wrapper. The UMA detection relies on the DB pass name lookup rather than the link.
- **Literal action text**: One file (Ghoul template ID 5) has `[one-action]` as literal text instead of `<span class="action">`. HTML bug.
- **Missing headings**: Dragon Resurrection had 3 unnamed ability groups that needed `<h4>` headings added.
- **Abilities inside `<li>`**: Military family had Pounce ability defined inside a `<ul><li>` change list item. Moved to after `</ul>`.

### Content Filter Lessons
- **Don't promote h3 to h2** — removed the old `h3.framing → h2` promotion. `parse_universal`'s `title_collapse_pass` handles the heading hierarchy correctly when the HTML is clean.
- **Keep the h3 body split** — some h3 tags have body content (abilities, descriptions) inline. The split (extract title → clean h3, unwrap body) is needed for `parse_universal` to create proper sections.
- **Don't unwrap action spans** — the unified parser needs them intact. Removed from monster_family content filter.
- **h4 support added** — `subtitle_pass` now handles `<h4>` when `max_title >= 4`.

### Non-Ability Bold Labels
"Related Groups" appears as `<b>Related Groups</b>` in 86+ monster family files. The ability parser was treating it as an ability name. Fixed with `_NOT_ABILITY_NAMES` blocklist in `universal/ability.py`. Better than fixing 86 HTML files because new families will have the same pattern.

### Creation Section Detection
`_is_creation_section` expanded to match: "creating", "building", "abilities", "spellcasters", "adjustments". Many families have creation-type sections that don't use "Creating X" naming.

## Next Steps

### Phase 2: Migrate Creature Parser (PFSRD2-Parser-ob6w)
The creature parser has 4 nested ability functions inside `creature_stat_block_pass`:
- `process_interaction_ability` — receives `(name, description, link, action)` tuples
- `process_defensive_ability` — same tuple format
- `parse_offensive_ability` — nested inside `process_offensive_action`
- `parse_affliction` — nested inside `process_offensive_action`

**Challenge**: These work on tuples from `split_stat_block_line`, not BS4 nodes. Options:
1. Reconstruct HTML from tuple fields and call `parse_ability_from_html` (lower risk)
2. Rework tuple splitting to pass raw nodes (cleaner but bigger change)

**Risk**: 4000+ creature files. Must use error seed workflow extensively.

**Key migration**: Move `_handle_trait_template` logic to `universal/monster_ability.py` so all parsers handle trait templates consistently.

### Phase 3: Migrate Feat/Skill Parsers (PFSRD2-Parser-91hd)
- Feats: `_extract_action_type`, `_extract_bold_fields`, `_parse_called_action`
- Skills: `_extract_action_type_from_name`, `_extract_action_text`

Lower risk — fewer files, simpler structure.

### Other Tickets
- **PFSRD2-Parser-aad8**: Handle `special_senses → ability array` schema change
- **PFSRD2-Parser-zezi**: Extract shared schema definitions into reusable files
- **PFSRD2-Parser-ltp2**: Cache LLM responses to survive enrichment DB rebuilds
- **PFSRD2-Parser-npfy**: Monster family sections tree should remain unmodified by consolidation
- **PFSRD2-Parser-h68p**: Extract images from monster family pages
- **PFSRD2-Parser-l9sd**: Comprehensive test coverage for enrichment `_build_*` functions

### Known Remaining Issues
- **3 action text leaks**: Literal `[one-action]` in ability text from HTML bugs (Ghoul Swift Leap, Mana Wastes Energy Blast, Hellbound Mortal Shield)
- **Creature parser still has its own `monster_ability_db_pass`**: Should be migrated to call `universal/monster_ability.py` (with trait template handling moved there)
- **`_detect_universal_monster_ability` creates skeletons**: These get cleaned up by the DB pass, but ideally the parser wouldn't create them — let the DB pass handle everything

## File Reference

| File | Purpose |
|------|---------|
| `universal/ability.py` | Unified ability parser (action types, traits, addons, afflictions) |
| `universal/monster_ability.py` | Universal monster ability DB pass |
| `pfsrd2/change_extraction.py` | Change/li extraction (uses unified parser for abilities) |
| `pfsrd2/monster_family.py` | Monster family parser (fully migrated) |
| `pfsrd2/monster_template.py` | Monster template parser (fully migrated) |
| `tests/test_unified_ability.py` | 22 unit tests for unified parser |
| `docs/enrichment-process.md` | Enrichment pipeline documentation |
