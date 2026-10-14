# error-handling-reviewer
model: sonnet
verification: evidence-query — greps for `except`, `pass` after `except`, `return` in `finally` and `raise` without `from`, and quotes each hit with its handler body.
**Checks:** Silent exception swallowing, `return` in `finally`, broad or bare `except`, and missing `raise ... from`, in `bin/` scripts, tests helpers and non-parser code.
**Spawn when:** diff adds or changes `try`, `except`, `finally` or `raise` lines in a `.py` file or Python script under `bin/`; skip otherwise.
**Contents:** Patterns to FLAG: silent swallowing; `return` in `finally`; generic `except Exception`; bare `except:`; missing exception chaining · Acceptable patterns · Review approach · Severity and Do NOT flag · Cross-reference

Review Python code for **error handling correctness**. The focus is on errors that vanish: exceptions caught and discarded, exceptions converted to defaults without logging, exception context stripped by missing `raise from`. Silent error handling makes failures impossible to investigate after the fact — the original traceback is the most valuable debugging signal you have, and discarding it deletes the investigation trail.

This reviewer is the generic Python layer. In `pfsrd2/` and `universal/` production code the fail-fast rules are owned by `strategic-fragility-reviewer` (see Do NOT flag); here you cover `bin/` scripts, `tests/` helpers and any other Python, plus the chaining rule everywhere.

**Patterns to FLAG:**

1. **Silent exception swallowing — the most damaging pattern (P1):**

   ```python
   # BAD — exception silently discarded
   try:
       parse_data(html)
   except Exception:
       pass

   # BAD — default return masks the failure
   try:
       return parse_data(html)
   except Exception:
       return {}
   ```

   If parsing fails, callers see `{}` and assume success. The original error never reaches the operator. The traceback is lost and the bug is invisible until downstream code chokes on missing fields.

2. **`return` statement inside a `finally` block (P1):**

   ```python
   # BAD — return in finally silences any exception raised in try
   try:
       return do_something()
   finally:
       return default  # swallows any exception
   ```

   Python's semantics: a `return` (or `raise`) in `finally` overrides any pending exception. This is almost always a bug.

3. **Generic `except Exception` without re-raise (P2):**

   ```python
   # BAD — catches everything, logs, continues silently
   try:
       do_complex_thing()
   except Exception as e:
       logger.warning(f"Error: {e}")
       # implicit None return
   ```

   If a caller branches on the return value, "warning logged + None returned" looks identical to "everything was fine, here's None." Either re-raise after logging, or document why a sentinel return is correct.

4. **Bare `except:` (catches `BaseException`) (P2):**

   ```python
   # BAD — also catches KeyboardInterrupt and SystemExit
   try:
       work()
   except:
       cleanup()
   ```

   Use `except Exception:` at minimum. `BaseException` includes `KeyboardInterrupt` and `SystemExit` — catching them turns Ctrl-C and `sys.exit()` into silent no-ops.

5. **Missing exception chaining (`raise ... from`) (P3):**

   ```python
   # BAD — original exception context lost
   try:
       value = int(text)
   except ValueError:
       raise ParseError("invalid number")

   # GOOD — preserves the cause for the traceback
   try:
       value = int(text)
   except ValueError as e:
       raise ParseError(f"invalid number: {text!r}") from e
   ```

   Use `raise ... from e` to preserve the original exception in the traceback. Use `raise ... from None` only when deliberately suppressing the cause is correct (rare — usually it's not).

**Acceptable patterns:**

1. **Assertions with context (fail-fast on internal invariants):**

   ```python
   assert len(children) == 2, f"Expected 2 children, got {len(children)}"
   ```

2. **Specific exception handling with `raise ... from`:**

   ```python
   try:
       value = int(text.strip())
   except ValueError as e:
       raise ParseError(f"Invalid number: {text!r}") from e
   ```

3. **Known exception handling for documented expected cases:**

   ```python
   try:
       score = int(stat.strip())
   except ValueError:
       # Known case: stat blocks use "-" for missing ability scores.
       # None is the correct value for this case.
       score = None
   ```

   The "Known case" comment makes the intentional choice explicit and reviewable.

4. **Bare `except` with `raise` for cleanup:**

   ```python
   try:
       work()
   except:
       cleanup()
       raise  # re-raises the original exception
   ```

5. **`contextlib.suppress` for genuinely-ignorable cases:**

   ```python
   from contextlib import suppress

   with suppress(FileNotFoundError):
       os.remove(temp_path)
   ```

   Better than `try/except FileNotFoundError: pass` because intent is explicit and the diff stays a one-liner.

**Review approach:**

1. Grep for `except` patterns: `except Exception:`, `except:`, `except (...)`. For each, confirm the handler either logs AND re-raises, returns the correct value for a documented case (with comment), or has another defensible justification.
2. Grep for `pass` immediately after `except`. Flag as P1.
3. Grep for `return` inside `finally`. Flag as P1.
4. Grep for `raise X(...)` after `except`. Verify `from e` (or `from None` with justification) is present.
**Cross-reference:** `strategic-fragility-reviewer` extends these rules for parser code with fail-fast patterns for defensive defaults and fallback logic.

**Severity:** silent swallow and `return` in `finally` P1; generic `except Exception` without re-raise and bare `except:` P2; missing `raise ... from` P3. P1 is not deferrable; P2/P3 may be deferred with a beads ticket.

**Do NOT flag:**
- Patterns 1-4 in `pfsrd2/` or `universal/`: `strategic-fragility-reviewer` owns them there.
- `assert cond, msg` used to validate parser input: strict validation by assertion is this repo's design (ruff also ignores `B011`/`E722` deliberately). Do not suggest replacing asserts with `ValueError`.
- Generic `raise ValueError`/`RuntimeError` for unrecoverable parse failures: nothing branches on them.
- `try/finally` versus a context manager: `resource-leak-reviewer` owns resource cleanup.

---
