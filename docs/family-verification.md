# Monster Family Creation-Rules Verification

Pre-remaster (and remastered) monster families carrying "Creating a..."
rules are the legacy equivalents of remastered monster templates. This
report covers their extraction, enrichment, engine application, and
clause-level verification — the same bar as docs/clause-verification.md
established for the 55 monster templates.

## Result

**41 family documents · 558 clauses · 5,450 assertions · 0 failures · 0 todo.**

Every clause of every family with creation changes was applied to up to 10
qualifying same-edition creatures through the live engine
(pfsrd2-data-api `/templates/apply` against staging data) and asserted
exactly: adjustments with a cumulative cross-change delta model
(including value_from replaces that later sweeps stack on), replaces
(including `high_for_level` table semantics with the published
"unless it was already higher" max rule), add_item/add_items (including
section-pool sources), size increments, trait add/removes, and
gate-false sides.

## Family target-type constraint pools

Selection respected published prerequisites:

| Family | Pool constraint | Qualifying (legacy/remastered) |
|---|---|---|
| Werecreature | humanoids, non-undead | 878 / 557 |
| Ravener | caster dragons, level ≥ 13 | per-edition dragon casters |
| Lich | spellcasters, non-undead | 1,037 legacy non-undead casters |
| Blackfrost Dead, Herexen | existing undead | undead pool |
| all other transforms | living (non-undead, non-construct) | ~2,212 / ~1,619 |

## Engine work this goal delivered (pfsrd2-data-api)

- **#42** — apply endpoint reads `monster_family` rules (Rules()
  precedence); resolution/S3/alternates were already type-agnostic
  (632 family entries indexed; 404 family↔family alternate rows).
- **#43** — `add_items` sources that point into the display sections
  tree (`$.sections[?(@.name=='Nymph Queen Abilities')].abilities`)
  resolve recursively; zero matches is an error, not a silent no-op.

**Cross-edition wiring decision:** legacy↔remastered resolution uses the
existing family↔family `alternates` rows (from AoN alternate links).
Family↔template equivalence is deliberately NOT wired — alternate links
connect same-page editions only, so an equivalence map would be invented
data. Each edition's creatures get their own edition's family rules.

## Parser work this goal delivered (PFSRD2-Parser)

- **#121/#122** — ability-enrichment staleness oscillation fixed
  (identity-hash drift classification, nested trait links); `--heal-stale`
  drained the 1,218-record backlog; `--audit-enriched` corrective sweep.
- **#123** — prose stat-instruction extraction from creation sections
  (whole-line + sentence-level, single-polarity, anaphora/grant-marker
  exclusions): 80 recovered changes across 35 families, including missing
  level bumps in every vampire variant, werecreature, divine warden,
  graveknights, ghost, ghoul, lich, and ravener.
- **#124** — change extractor v24: spell-scoped stat adjustments,
  word-bounded gates ("reACh"/"reflection" false positives), clause-bounded
  value pairing, generalized level subjects.
- **#125** — parser-encoded structural changes bypass regex categorization
  (was 433 of 498 family review flags).
- **#126/#127/#129** — 66 overrides + 26 documented quarantines; the
  family review queue ended at **0 undispositioned records**.

## Documented shortfalls (never padded)

- **Quarantines (26, four distinct reasons):** `gm_judgment_loss`
  ("loses all abilities that come from being a living creature" — which
  abilities is a per-creature GM call; the paired trait-loss sentences DO
  encode Human/Humanoid removals), `conditional_on_choice` (werecreature
  size bump depends on the chosen animal), `add_strike_ranged_pending`
  (woodblessed splinter — engine derives melee strikes only),
  `orphaned_by_reparse` (texts excluded by design, records retained for
  audit), plus ravener innate-spell rank lists pending spells-op support.
- **Pool shortfalls (< 10 qualifying creatures):** 15 clauses, all with
  pool 0–2 — every one is the reactive-ability save-DC adjustment target
  (`$.defense.reactive_abilities[*].saving_throw[*].dc`) or an equally
  rare feature combination; pools of 0 mean no qualifying creature exists
  in the corpus (the op is valid but unexercisable). Verified passes are
  reported for every creature that does qualify.
- **Family subtypes** (Bestiary/Book of the Dead variant ability lists,
  dragon alternate-ability pools) are structural `add_items` selections
  surfaced to clients via `mf.subtypes` — selections are client-driven by
  design and are not auto-applied, exactly like template select effects.

## Per-family matrix

| Family file | Edition | Clauses | Passes | Fails |
|---|---|---|---|---|
| bestiary/ghost.json | legacy | 12 | 120 | 0 |
| bestiary/ghoul.json | legacy | 22 | 220 | 0 |
| bestiary/lich.json | legacy | 4 | 40 | 0 |
| bestiary/nymph.json | legacy | 1 | 10 | 0 |
| bestiary/vampire.json | legacy | 27 | 270 | 0 |
| bestiary/werecreature.json | legacy | 19 | 181 | 0 |
| bestiary_2/ravener.json | legacy | 15 | 141 | 0 |
| bestiary_2/vampire_vrykolakas.json | legacy | 24 | 240 | 0 |
| bestiary_2/worm_that_walks.json | legacy | 15 | 150 | 0 |
| bestiary_3/divine_warden.json | legacy | 14 | 140 | 0 |
| bestiary_3/phantom.json | legacy | 6 | 60 | 0 |
| bestiary_3/vampire_nosferatu.json | legacy | 26 | 260 | 0 |
| book_of_the_dead/herexen.json | legacy | 2 | 20 | 0 |
| book_of_the_dead/siabrae.json | legacy | 5 | 50 | 0 |
| book_of_the_dead/vampire_jiang-shi.json | legacy | 26 | 260 | 0 |
| book_of_the_dead/vampire_vetalarana.json | legacy | 25 | 250 | 0 |
| gatewalkers_hardcover/blackfrost_dead.json | remastered | 2 | 20 | 0 |
| impossible_lands/mana_wastes_mutant.json | legacy | 1 | 10 | 0 |
| monster_core/dragon_omen.json | remastered | 2 | 20 | 0 |
| monster_core/ghost.json | remastered | 20 | 192 | 0 |
| monster_core/ghoul.json | remastered | 21 | 202 | 0 |
| monster_core/graveknight.json | remastered | 12 | 120 | 0 |
| monster_core/herexen.json | remastered | 2 | 20 | 0 |
| monster_core/lich.json | remastered | 9 | 90 | 0 |
| monster_core/nymph.json | remastered | 1 | 10 | 0 |
| monster_core/phantom.json | remastered | 5 | 50 | 0 |
| monster_core/vampire.json | remastered | 28 | 272 | 0 |
| monster_core/werecreature.json | remastered | 20 | 190 | 0 |
| monster_core_2/divine_warden.json | remastered | 14 | 132 | 0 |
| monster_core_2/ravener.json | remastered | 16 | 150 | 0 |
| monster_core_2/swarm_strider.json | remastered | 6 | 60 | 0 |
| monster_core_2/vampire_nosferatu.json | remastered | 27 | 262 | 0 |
| pathfinder_172_secrets_of_the_temple_city/graveknight.json | legacy | 11 | 110 | 0 |
| pathfinder_189_dreamers_of_the_nameless_spires/blackfrost_dead.json | legacy | 2 | 20 | 0 |
| pathfinder_192_worst_of_all_possible_worlds/harrowkin.json | legacy | 5 | 50 | 0 |
| pathfinder_193_mantle_of_gold/sporeborn.json | remastered | 7 | 50 | 0 |
| pathfinder_202_severed_at_the_root/woodblessed.json | remastered | 12 | 112 | 0 |
| pathfinder_207_resurrection_flood/floodslain_creature.json | remastered | 19 | 182 | 0 |
| pathfinder_215_to_blot_out_the_sun/vampire_strigoi.json | remastered | 28 | 272 | 0 |
| shadows_at_sundown/vampire_strigoi.json | legacy | 27 | 270 | 0 |
| shining_kingdoms/failed_prophet.json | remastered | 18 | 172 | 0 |
## Regeneratable end state

Full cycle verified clean: parse templates+families → `pf2_enrich_changes`
→ `pf2_seed_change_overrides` (exit 0, 66/66 overrides + 26/26
quarantines) → re-parse ⇒ **zero errors.pf2.\*, zero data drift**.
Data on `pfsrd2-data` branch `family-fixes`; staging S3 synced
(json/monster_families + index DB; production untouched).
