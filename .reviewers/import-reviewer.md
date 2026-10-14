# import-reviewer
model: sonnet
verification: evidence-query — greps the changed files for indented `import` / `from` lines and for `from ...` relative imports, and quotes each with the presence or absence of a justifying comment.
**Checks:** Function-level imports without a justifying comment and relative imports across package boundaries; import order only in `bin/` scripts that ruff skips.
**Spawn when:** diff adds or changes an `import` or `from ... import` line (including indented ones) in a `.py` file or Python script under `bin/`; skip otherwise.
**Contents:** Patterns to FLAG: Function-level imports; Relative imports past package boundaries · Acceptable function-level imports · Review approach · Severity and scope

Review Python imports for **PEP 8 compliance and placement discipline**. Most import-ordering issues are caught by `ruff check --select I`; this reviewer focuses on the structural rules ruff doesn't enforce.

**Patterns to FLAG:**

1. **Function-level imports:**

   ```python
   # BAD — import inside a function
   def parse(path):
       import json
       return json.loads(open(path).read())

   # GOOD — top of file
   import json

   def parse(path):
       with open(path) as f:
           return json.load(f)
   ```

2. **Relative imports past package boundaries:**

   ```python
   # BAD — fragile, breaks under restructuring
   from ...other_package import thing
   ```

   Use absolute imports for cross-package references.

**Acceptable function-level imports** (each requires a comment explaining why):

- Optional dependencies wrapped in `try`/`except ImportError` — the dep may not be installed.
- Imports that genuinely break a circular dependency. The comment should name the cycle.
- Imports deferred to minimize CLI startup latency (heavy modules like `numpy`, `pandas`, `torch`). The comment should justify the latency budget.

**Review approach:**

1. Grep for `^\s+import` and `^\s+from` (indented import statements) — these are function-level.
2. For each, check if it falls into an acceptable exception. If yes, verify the documenting comment is present.
3. In extensionless Python scripts under `bin/` (excluded from ruff in `pyproject.toml`), also flag PEP 8 import-order violations and unused imports by reading them.

**Severity:** P3. May be deferred with a beads ticket.

**Scope:** added or changed import lines only. CI runs ruff `I` and `F` on `pfsrd2/`, `universal/` and `tests/`, so order, unused imports and wildcard imports are not yours there. Existing code has many indented imports (`import sys` under `__main__`, circular-import deferrals in `universal/utils.py`, lazy imports in `pfsrd2/sql/`); untouched ones are never findings.

**Do NOT flag:** imports inside `if __name__ == "__main__":` blocks.

---
