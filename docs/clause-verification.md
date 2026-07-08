# Clause-Level Template Verification

**Date:** 2026-07-08 · **Bar:** every clause of every template verified against
≥10 distinct qualifying creatures with exact-value assertions · **Tracking:**
beads epic `bd_521Studios-nak` (55 per-template tickets carry full matrices)

## Final state

**647 clauses · 6,446 clause-tests · 0 failures · 0 unimplemented asserts ·
3 documented shortfalls.**

A *clause* is the atomic unit of a template: each effect of each change, each
conditional branch (every level band separately), each presence-gate's true
AND false side, each selection descriptor and option, each `value_from`
derivation. Creatures were selected per-clause from a 4,565-creature feature
index (levels, movements, skills, senses, casters, reach, limited-use,
resistances, editions), spread across level bands, same-edition as the
template; cross-edition resolution rides the alternate-link tests.

The 3 shortfalls are one corpus fact: exactly 2 creatures possess a reactive
ability with a saving-throw DC, so the reactive-DC adjustment clause of
Elite/Weak/Broodpiercer tests 2-of-2 (both pass).

## Bugs found and fixed (all caught by the sweep)

| Finding | Detector | Fix |
|---|---|---|
| Broodpiercer's 4 host abilities never applied (engine synthesizes only for templates with NO changes) | engine-synthesis clause failed 10/10 | #117: granting sections ("gain(s) the following abilities") become changes; modal/choose wording stays pooled |
| Experimental/Rumored Cryptid grants also unconverted (+ raw-link crash) | corpus scan in review round | #117 round 1: parse_change-style link extraction |
| Int-floor effects targeted `$.creature_type.{attr}_modifier` — exists on zero creatures | qualifying pool provably empty | #116: `$.statistics.{str..cha}` + full-word validation ("internal" ≠ int) |
| `$.traits` is a phantom path — zero of 4,565 creatures have it; all 4 rarity-badge effects dead | pool=0 | #118: badge array `$.creature_type.traits`; adds carry full canonical trait objects from the traits DB (schema-whitelisted, rarity classes derived, remastered-preferred) |
| Lizardfolk fist→claw name replace never fired (weapon replace killed the shared filter) | filtered-replace pairing | #118: name replace precedes weapon replace |
| set_reach emission targeted orphan `.attack.bonus` | engine type-assert no-op | #118: `.attack` |
| Vampire-family fragment "traits" (Condition, Feet) | TraitLookupError | quarantined as `unknown_trait:` review records — a display-crashing badge can never ship |
| Legacy Bestiary Elite/Weak have no level clause (AoN omits the printed sentence; legacy math differs: "instead increase its level TO 1") | legacy creatures' level never changed | **open — bd_521Studios-zew, needs printed-text confirmation** |

## Deliberate deferrals

- Dark Archive choose-from pools (Primeval "gain two from the list", Mutant's
  four) stay warn-only pending selection support; recorded per-ticket.
- Mutant's "have all four the following abilities" grant phrasing:
  `bd_521Studios-c44`.

## Harness (scratchpad `clausev/`)

`build_inventory.py` (clause extraction + predicate compilation from
conditionals), `build_creature_index.py` (feature index), `selector.py`
(deterministic band-spread selection; shortfalls reported, never padded),
`runner.py` (staging-backed apply + per-op assertion engine: cumulative
cross-change delta model mirroring `isAccumulatingOp`/first-match chains,
name-paired array comparison, filtered-replace index pairing, gate-false
no-op checks, selection-descriptor payload checks, magnitude recording on
every miss). `bin/json_map` output seeded the field-example lookups.

Every fix flowed through the permanent layers (parser PRs #116–#118,
overrides, HTML) and the regeneration cycle; `template-fixes` and staging
carry the regenerated output. Nothing was hand-edited.
