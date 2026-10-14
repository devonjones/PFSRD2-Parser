# importlib-resources-reviewer
model: sonnet
verification: evidence-query — greps the diff for `__file__` and quotes the path it resolves to, then greps the repo for accessor calls that already read the same file.
**Checks:** New `__file__`-relative reads of bundled data or schema files that bypass `get_data()` / `get_schema()`.
**Spawn when:** diff adds `__file__` in a non-test `.py` file outside `bin/`, or adds a file under `pfsrd2/data/` or `pfsrd2/schema/`; skip otherwise.
**Contents:** FLAG when added code · Do NOT flag · Severity · Review approach

Review Python code for **how bundled data and schema files are read**. This repo is not packaged (no build backend in `pyproject.toml`; code runs from the checkout with `PYTHONPATH`), so `importlib.resources` is not required. Instead, bundled files are read through two accessors, which resolve their directory via `__file__` on purpose:

- `pfsrd2.data.get_data(name)` for files in `pfsrd2/data/`
- `pfsrd2.schema.get_schema(name)` for files in `pfsrd2/schema/`

**FLAG when added or changed code:**
- Reads a file from `pfsrd2/data/` or `pfsrd2/schema/` by navigating from `__file__` (`Path(__file__).parent`, `os.path.dirname(__file__)`, `__file__.parents[N]`) instead of calling the accessor above. Fix: call the accessor.
- Adds a data or schema file under `pfsrd2/data/` or `pfsrd2/schema/` that nothing reads through an accessor.
- Introduces packaging (a `[build-system]` or `package-data` entry in `pyproject.toml`) while the accessors still use `__file__`: then recommend `importlib.resources.files("pfsrd2.data")` inside the accessors only.

**Do NOT flag:**
- The accessor definitions themselves (`pfsrd2/data/__init__.py`, `pfsrd2/schema/__init__.py`).
- `__file__` in `tests/` and in extensionless scripts under `bin/` (they locate the repo root, not bundled data).
- `__file__` used for write paths, and `pathlib` use that does not read bundled data.

**Severity:** P3. May be deferred with a beads ticket.

**Review approach:**
1. Grep the diff for `__file__`; for each hit outside tests and `bin/`, decide whether the path resolves into `pfsrd2/data/` or `pfsrd2/schema/`.
2. For each new file under those two directories, grep the repo for its name and confirm an accessor call reads it.

---
