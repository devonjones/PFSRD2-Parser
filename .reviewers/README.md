# Reviewer roster notes (orchestrator only)

This file is never shown to reviewers. Anything a reviewer needs lives in its own file.

1. **Project.** PFSRD2-Parser: Python HTML to JSON parsers on BeautifulSoup, with a deliberate fail-fast ("strategic fragility") design. Shared helpers live in `universal/`; parsers in `pfsrd2/`; entry points are extensionless Python scripts and `*.sh` runners in `bin/`.
2. **Roster.** The starters `code-reviewer`, `pr-test-analyzer`, `type-design-analyzer`, plus the project reviewers. A reviewer runs only if its file is in this directory.
3. **Dropped defaults.** `silent-failure-hunter` is covered by `error-handling-reviewer` and `strategic-fragility-reviewer`; `comment-analyzer` by `clarity-reviewer`; `code-simplifier` by `complexity-reviewer` and `dead-code-reviewer`.
4. **Ownership split.** `strategic-fragility-reviewer` owns exception swallowing and defensive defaults in `pfsrd2/` and `universal/`; `error-handling-reviewer` covers everything else (`bin/`, tests helpers). `concurrency-reviewer` owns thread/task lifecycle; `resource-leak-reviewer` owns handles, connections and caches. The Do NOT lists encode this.
5. **Acknowledged overlap.** `test-coverage-reviewer` and `pr-test-analyzer` overlap on purpose (config.json): hard coverage rules versus criticality-scored gaps. `overlap_acknowledged` takes one partner per key; use Do NOT carve-outs for any other overlap.
6. **CI facts the specs rely on** (`.github/workflows/lint.yml`, `pyproject.toml`): black, `ruff check` (E, W, F, I, UP, B, C4, SIM; E722, SIM102, SIM108, SIM115, B011 ignored on purpose; `bin/` excluded), JSON schema formatting check, `pytest tests/`. There is no mypy, pyright, bandit, vulture, C901 or coverage run, so reviewers do not assume them.
7. **Existing code is not a baseline for findings.** Existing code already breaks the C901, indented-import and defensive-`.get()` floors. Specs scope findings to added or changed lines; untouched offenders are P3 at most.
8. **Severity.** Each reviewer states its own P1/P2/P3 defaults. P1 blocks and is not deferrable; P2/P3 may be deferred with a beads ticket. Starters keep their Critical/High scale and Output format (tracked upstream).
9. **Data repo.** `pfsrd2-data` and `pfsrd2-web` are separate repos; this roster reviews `PFSRD2-Parser` only.
10. **Fast-iteration seed files** (`bin/errors.pf2.<type>`) and the parser-run protocol are developer workflow in CLAUDE.md, not review rules.
