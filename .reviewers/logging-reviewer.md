# logging-reviewer
model: sonnet
verification: evidence-query — greps the diff for output calls and quotes the interpolated variable names or the target stream (stdout vs stderr).
**Checks:** Secrets interpolated into output, warnings printed to stdout alongside parser JSON, and logging misuse if `logging` is introduced.
**Spawn when:** diff adds lines containing `print(`, `sys.stderr`, `WarningReporting`, `logging.` or `logger.` in a non-test `.py` file or Python script under `bin/`; skip otherwise.
**Contents:** What to flag · Do NOT flag · Severity · Review approach

Review Python code for **diagnostic output discipline**. This repo does not use the `logging` module. Parsers `print()` their JSON result and a per-file progress line to stdout (for example `print(json.dumps(struct, indent=2, sort_keys=True))` and `print("{} ({}): {}".format(...))`), and send parse warnings through `universal/warnings.py` (`WarningReporting.report(...)`, which writes to stderr). Judge new output against that convention; do not demand a migration to `logging`.

**What to flag (added or changed lines only):**
1. **Secrets in output (P1):** interpolating variables named `token`, `password`, `secret`, `api_key`, `credential`, `auth`, `cookie`, `session`, `private_key` or `bearer`, or dumping whole request/response/environment objects, into `print`, `sys.stderr.write`, `WarningReporting.report`, logger calls or exception messages. LLM enrichment code (`pfsrd2/enrichment/`) handles credentials.
2. **Warnings printed to stdout (P2):** a new warning or error message emitted with `print()` where it would mix into the JSON a caller redirects from stdout. Use `WarningReporting.report(...)` or `sys.stderr`. The `--output` JSON dump and the one-line progress print are the accepted stdout uses.
3. **If `logging` is introduced:** `logger.error(...)` inside an `except` block without `exc_info=True` (use `logger.exception`, P2); `logging.basicConfig()` outside an entry point (P2); f-string formatting in a debug call inside a per-element loop (P3).

**Do NOT flag:**
- `print()` in tests, in extensionless scripts under `bin/`, or the JSON-result and progress prints described above.
- Existing `print()` / stderr calls the PR does not add or change.
- The absence of `-v` / `-q` flags, log levels or a logger: none exist in this repo.

**Severity:** as marked above. P1 is not deferrable; P2/P3 may be deferred with a beads ticket.

**Review approach:**
1. Grep the diff for `print(`, `sys.stderr`, `WarningReporting`, `logging.` and `logger.`.
2. For each hit, read the interpolated names for item 1 and decide stdout versus stderr for item 2.
3. Quote the line and the variable or stream in the finding.

---
