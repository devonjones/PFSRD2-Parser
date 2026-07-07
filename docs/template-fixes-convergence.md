# Template-Fixes Convergence Report

**Date:** 2026-07-07 · **Scope:** make the parse → enrich → seed → re-parse cycle
reproduce the hand-verified remastered-template data (pfsrd2-data branch
`template-fixes`, PFSRD2-Data#4) · **PRs:** PFSRD2-Parser#112, PFSRD2-Web#1
(both merged) · **Tracking:** beads epic `PFSRD2-Parser-jzl5`

## Result

Running the full cycle on a synced checkout:

```bash
bin/pf2_run_monster_templates.sh    # stage raw change records
bin/pf2_enrich_changes              # regex categorize + build effects
bin/pf2_seed_change_overrides       # seed hand-verified overrides (must exit 0)
bin/pf2_run_monster_templates.sh    # merge effects into output JSON
```

produces, against `template-fixes`:

- **34 of 40 touched files converge exactly** (differing only by trailing
  newline — the hand edits added one; parser output does not emit one).
- **`monsters/monster_core_2/trained_raven.json` converges exactly** (em-dash
  fixed in the source HTML).
- **2 files improve beyond the branch** (`dark_archive/{primeval,rumored}_cryptid.json`
  gain badge-mirror removals from the systemic extractor fix).
- **4 documented deviations** where the parser output is *more correct* than
  the hand data (see below and beads `PFSRD2-Parser-ymwp`, human-flagged).

**Recommendation:** regenerate `template-fixes` from parser output (i.e. commit
the current pfsrd2-data working tree) rather than amending the branch by hand;
every remaining hunk is an improvement or a fabricated-text removal.

## What was built

### Override layer (24 change + 2 ability entries)
`overrides/change_overrides.json` + `overrides/ability_overrides.json`, seeded
by `bin/pf2_seed_change_overrides` as `extraction_method='manual'`,
`human_verified=1`. Carries the enrichments regex cannot produce: Elite/Weak
conditional level chains, Frostbound/Sandbound resistance bands, Wood's
weakness split + Plant `select`, all five `add_strike` derivations (vampire
fangs, dwarf clan dagger w/ `select` + gear, kholo/ratfolk jaws, tengu beak),
Miniature size-trait object replaces + `set_reach`, tiered speed grants with
presence guards (Air/Earth/Water/Winged/Sandbound), Earth's imprecise
tremorsense, Guerrilla's conditional Athletics −2, Amphibious trait swap,
Fire's dead-effect removal, Corrupt/Tengu ability routing; Cold Stasis →
`automatic`, Mythic Power (Recharge Spell) → `offensive`.

Staleness is loud: identity hashes cover the source text, so errata/HTML
changes make the seeder exit nonzero listing the stale entries.

### Parser/extractor code fixes (systemic)
- Creature-type removals mirror onto `$.creature_type.traits` (stale-badge
  fix; 17 NPC Core ancestries, leshy, cryptids). `ENRICHMENT_VERSION` → 20.
- `CATEGORY_TARGETS["interaction"]` → `$.interaction_abilities` (Zombie's Slow
  was routed to a dead path).
- `reorder_changes_pass`: hit_points band changes precede the level adjustment
  (bands evaluate on starting level).
- Schema: `alternate_link.game-obj` + `MonsterTemplates`; `effect.operation`
  + `add_strike`.

### pfsrd2-web HTML fixes (one-offs)
- Tengu (ID_54): inline `&bull;` bullets → `<ul><li>` (only template not using
  a list; all four bullets were unparsed).
- Elite/Weak (ID_1/2/22/23): Legacy/Remastered `siderbarlook` cross-link divs
  so `handle_alternate_link` fires.
- Trained Raven (ID_4527): `1d4&mdash;1` → `1d4-1`.

## Documented deviations (beads `PFSRD2-Parser-ymwp`)

1. **tengu.json** — hand edit placed links/abilities at top level and authored
   change text `"- Add the following abilities."`; the parser keeps ability
   names in the change text and attaches links/abilities at change level,
   consistent with zombie and every sibling template.
2. **corrupt.json** — hand edit added a fabricated change (no such `<li>`).
   The `add_items` (Official Bully → `$.interaction_abilities`) now rides the
   real li via override — which also replaces the junk
   `"Official Bully Ability For That"` skill artifact still present in
   template-fixes.
3. **broodpiercer.json** — fabricated abilities block dropped; the abilities
   live in a titled section, the engine routes them from the ability pool, and
   Cold Stasis's category is corrected via override.
4. **amphibious.json** — override adds the Aquatic badge-mirror removal that
   the hand data lacked (stale-badge bug in the verified data, caught in
   review).

## Open items

- `PFSRD2-Parser-ymwp` (**human**): bless the four deviations / regenerate
  template-fixes.
- `PFSRD2-Parser-u0w4`: Miniature 0-ft reach reduction needs engine support
  (no Reach trait on baseline strikes to lower; no lowest-reach selector).
- `PFSRD2-Parser-c0m5`: hermetic subprocess test for the seeder CLI exit code
  (needs injectable enrichment-DB path).
- Family output will pick up badge-mirror effects on the next
  `pf2_run_monster_families.sh` (correct fallout of the systemic fix; not run
  as part of this work).
