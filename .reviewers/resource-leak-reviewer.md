# resource-leak-reviewer
model: sonnet
verification: evidence-query — greps for `open(`, `Popen`, `sqlite3.connect` and `tempfile`, then traces every return and raise path for a close, and quotes the path that skips it.
**Checks:** Files, sqlite connections, subprocess pipes and temp files not closed on every path; unbounded caches; manual `try/finally` chains that `ExitStack` would handle.
**Spawn when:** diff adds lines containing `open(`, `Popen`, `sqlite3.connect`, `tempfile`, `lru_cache` or a module-level dict/set cache in a non-test `.py` file or Python script under `bin/`; skip otherwise.
**Contents:** Patterns to FLAG: `open()` without close; `subprocess.Popen` without wait; database connections not closed; `lru_cache` without `maxsize`; module-level caches without eviction; temp files; ExitStack candidates; identity-keyed caches · Do NOT flag · Severity and scope · Review approach · Cross-reference

Review Python code for **resource leaks** in long batch runs (parsers walk thousands of files per run; loaders write to sqlite). Python's GC is forgiving but not magic: file handles, connections and subprocess pipes pile up when a loop reopens them per element without closing.

**Patterns to FLAG:**

1. **`open()` without a context manager:**

   ```python
   # BAD — file handle relies on GC; on CPython may stay open indefinitely if a reference survives
   f = open(path)
   data = f.read()

   # GOOD
   with open(path) as f:
       data = f.read()
   ```

2. **`subprocess.Popen` without `.wait()` or context manager:**

   ```python
   # BAD — zombie process, fd leak
   p = subprocess.Popen(["git", "fetch"])
   # ... no .wait()
   ```

   Use `subprocess.run(...)` for one-shot commands, or `with subprocess.Popen(...) as p:` for streaming I/O.

3. **Database connections not closed:**

   ```python
   # BAD — connection leaked
   conn = sqlite3.connect(path)
   cursor = conn.execute(query)

   # GOOD
   with sqlite3.connect(path) as conn:
       cursor = conn.execute(query)
   ```

   Note: the `sqlite3` connection context manager commits/rolls back but does NOT close — close explicitly if the connection isn't intended to outlive the block.

4. **`functools.lru_cache` without `maxsize=` on unbounded key spaces:**

   ```python
   # BAD — cache grows without bound when keys come from external input
   @functools.lru_cache(maxsize=None)
   def fetch(user_id):
       ...
   ```

   Set `maxsize=` to a sensible cap when keys derive from external input. Or use `cachetools.TTLCache`.

5. **Long-lived module-level dicts/sets as caches without eviction:**

   ```python
   # BAD — grows forever as long as the process is up
   _CACHE: dict[str, Any] = {}

   def serve(req):
       _CACHE[req.key] = compute(req)
   ```

   Use `functools.lru_cache`, `cachetools`, or an explicit eviction policy.

6. **`tempfile.NamedTemporaryFile(delete=False)` without explicit cleanup:**

    `delete=False` is sometimes necessary (the file is consumed by a subprocess after the Python writer closes it), but always pair it with `finally: os.unlink(name)` or use `tempfile.TemporaryDirectory()` for batches.

7. **Manual `try/finally` chains where `contextlib.ExitStack` would do:**

    ```python
    # BAD — fragile when N varies, breaks on intermediate failure
    f1 = open(a)
    try:
        f2 = open(b)
        try:
            f3 = open(c)
            try:
                ...
            finally:
                f3.close()
        finally:
            f2.close()
    finally:
        f1.close()

    # GOOD — ExitStack handles unwinding even when count varies at runtime
    from contextlib import ExitStack
    with ExitStack() as stack:
        files = [stack.enter_context(open(p)) for p in paths]
        ...
    ```

    Flag manual try/finally chains protecting two or more resources, especially when the resource count is dynamic. `ExitStack` is the right pattern.

8. **Long-lived caches keyed by object identity without `weakref`:**

    ```python
    # BAD — cache pins the keys in memory forever, prevents GC
    _cache: dict[SomeObject, Result] = {}

    # GOOD — entries vanish when the key is GC'd elsewhere
    import weakref
    _cache: weakref.WeakKeyDictionary[SomeObject, Result] = weakref.WeakKeyDictionary()
    ```

    When a cache is keyed by an object (rather than a primitive ID or string), plain `dict` holds a strong reference to the key, preventing the key from being garbage collected even after the rest of the program has dropped its references. `weakref.WeakKeyDictionary` (for object keys) and `weakref.WeakValueDictionary` (for object values) let cache entries evict naturally when the underlying objects are no longer reachable.

**Cross-reference:** thread, process and task lifecycle (daemon threads, dropped `asyncio.create_task` references) belongs to `concurrency-reviewer`. This reviewer covers files, connections, subprocess pipes, temp files and caches.

**Do NOT flag:**
- An explicit `f = open(...)` ... `f.close()` pair: it is this repo's accepted style (`SIM115` is ignored in `pyproject.toml`). Flag only a path (early return, raise) that skips the close.
- Thread/process lifetime and daemon threads: `concurrency-reviewer`.
- Existing handles the PR does not add or change.

- `pathlib.Path.read_text()` / `read_bytes()` — closes the file internally.
- `with` blocks that close resources in normal flow.
- Bounded `functools.lru_cache` with an explicit `maxsize`.
- One-shot scripts that exit shortly after the work (CLIs, build scripts) — the leak shape doesn't apply when the process exits in seconds.

**Review approach:**

1. For each `open()`, `subprocess.Popen`, `sqlite3.connect`: verify a `with` block or an explicit close on every return and raise path.
2. For each module-level `dict` / `set` written from multiple call sites: ask about eviction.
3. For each `lru_cache`: verify `maxsize` is set when the key space is external.

**Severity:** P2 by default; P1 when the leak repeats per element of a batch loop (a handle or connection opened per file and never closed). P1 is not deferrable; P2/P3 may be deferred with a beads ticket. Findings apply to added or changed code only.

---
