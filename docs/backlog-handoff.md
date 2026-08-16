# Backlog Handoff

Working notes for autonomous backlog sessions. Read this before starting; the
tickets carry the repros, this carries the ordering, the judgement calls, and
the mistakes already made so they are not made twice.

Written 2026-08-16, after the affliction parser and the monster-family
degree-of-success work.

---

## Where things stand

**PR #165** (`fix/monster-family-result-labels`) — degrees of success fold into
the ability that rolled the check. 0 errors, 17 `monster_families/` files,
1696 tests. Round 2 converged after the repeated-label assert was split out into
`xzij`. Needs one more verification round because the split landed after round 2,
then merge — code and its 17-file data change.

**Merged this session:** affliction parser (#162), game-id uniqueness (#164),
plus data PRs #7 and #8.

---

## Order of work

### 1. `xzij` (P1) — the only actively destructive bug

13 files silently lose published text when an addon label repeats:
`_apply_addon` ends in `ability[key] = value`, so the second value overwrites
the first and the earlier sentence exists nowhere in the output.

Confirmed shipped: `hazards/gm_core/confounding_betrayal.json` is missing
Unmask's first `critical_success` — *"The creature sees through the illusions
entirely and is temporarily immune to the haunt's routine for 1 minute."*

Files: `MonsterFamilies.aspx.ID_396`, `ID_585`; `Hazards.aspx.ID_45, 48, 282,
351, 382, 393, 458, 487, 488, 568, 609`.

**Diagnosis already done for ID_45.** The bold sequence is:

```
Unmask … Critical Success / Success / Critical Failure … Routine …
Critical Success / Success / Critical Failure
```

`Routine` is a hazard `FIELD_LABEL`, not an ability, so the Unmask ability is
still open when the second degree run arrives and swallows it. Fix that
attribution and most of the 11 hazards should fall out together. The 2 family
cases are `Effect` / `Frequency` repeats and may be HTML bugs instead.

Per file, decide HTML bug vs code bug — one-off in the source → fix
`pfsrd2-web`; consistent across many files → fix the parser.

Land the assert once all 13 parse clean, then re-run and **review the recovered
text in the data diff**. Text should come *back*; that is the whole point.

### 2. Work without asking

| ticket | note |
|---|---|
| `4bcm` P2 | Thread `consumed=` through `monster_family`/`monster_template` so unclaimed ability nodes stop vanishing. Expect a data diff of recovered text. **Do not** blanket-assert in `_split_nodes` — it fails 6 existing tests, because an unconsumed node is legitimate for callers that *do* pass `consumed=`. |
| `mgz4` P3 | Empty addon values vanish (`if value:` guard); degree fields get no structured damage/save extraction. Shared code — validate with a **full creature run** before merging. Note it reaches creature output: `creatures.py:445` inlines the whole family object, so ~52 monster/NPC files move on the next family DB reload. |
| `8fbe` P3 | `universal/` inlines the `nodes_after` walk three times; two are free swaps, the third is entangled with `nlf1`. |
| `nlf1` P3 | `extract_bold_fields` `stop_at_br`, which deletes `_split_trailing_prose`. Touches ~8 parsers — needs a verification sweep across all of them. |
| `165k` P1 | Unit tests for the ability enrichment pipeline. |
| `npfy` P1 | Consolidation should stop stripping ability sections out of the family sections tree; subtypes should reference sections instead of consuming them. |

### 3. Ask, do not decide

- **`t0ws`** — `Immunities`, `Resistances`, `Weaknesses`, `Fly`/`Climb`/`Swim
  Speed` are unambiguously stat changes; fix those. But `Darkvision` and
  `Low-Light Vision` are senses that creatures legitimately model as abilities.
  Leave those two and ask. Also normalise the `Low-Light` / `Low-light` casing.
- **`r0wc`** — 6 monster files where committed data holds structured objects the
  current parser no longer produces. Could be stale committed data, or
  enrichment-DB drift (`_pick_best_ability` logs "no edition match … using first
  of 2"). See `.claude/skills/rebuild-enrichment.md`. Do not pick a direction.
- **`l1li`** — realign `creature.schema.json` or repoint the schema guide.
- **`wjja`** — Recall Knowledge missing from creature output; the ticket notes
  say it may resolve once change enrichment runs. Investigate and report.

---

## Mistakes already made — do not repeat

- **Reported "0 errors" measured at the wrong commit, twice.** Re-measure
  *after* every commit that touches parser code. A reviewer caught the second
  one; 13 files were failing.
- **`git status` on `pfsrd2-data` is unreliable while parsers are writing.**
  Two reviewers and I all drew false conclusions from mid-run reads — one
  phantom "stale file", one phantom set of hazard modifications. Wait for a
  quiescent tree.
- **Clear `__pycache__` between mutation runs.** Stale bytecode manufactured a
  test failure that cost real time to chase.
- **Do not arm `sleep`-based waiters** to poll long runs; they linger. Check on
  demand.
- **Mutation-test your own tests, and mutate the orchestrator, not just the
  leaves.** A test proving a shared constant works does *not* prove the callers
  pass it — that exact gap survived a first review round twice.
- **Verify a bug's mechanism before filing it.** `tdtn` was filed on a misread
  and cost a 65-minute regeneration to disprove: the two "colliding" feats write
  to different book directories.
- **Budget for run times.** Feats ~65 min (8142 files), creatures ~20 min
  (3670), families/templates/hazards a few minutes each.

---

## Standing rules

- Zero-errors policy: never merge with any file failing to parse.
- Never paper over an assert. Fix the root cause, or split it out with a ticket
  carrying the repro.
- Never fabricate a value the source did not publish.
- `game-id` is intended to be unique. A collision is a parser bug: take the
  later duplicate, or fold edition into the id.
- Every code change goes through a full `pr-review-loop` to convergence.
  Reviewers post findings as line comments; reply to every thread.
- `.beads`-only commits are allowed directly on `main`; everything else needs a
  branch.
