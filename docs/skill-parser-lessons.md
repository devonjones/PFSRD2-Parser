# Lessons Learned: Building the Skill Parser

This document captures practical lessons from building `pfsrd2/skill.py` end-to-end.
Use this as a companion to `adding-new-parser.md` and `architecture.md`.

## Pipeline Order Matters

The skill parser pipeline demonstrates critical ordering dependencies:

```python
def parse_skill(filename, options):
    # 1. Parse HTML into sections
    details = parse_universal(filename, max_title=4, cssclass="main",
                              pre_filters=[_content_filter, _sidebar_filter])
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]

    # 2. Build initial structure
    struct = restructure_skill_pass(details)

    # 3. Content-specific extraction (BEFORE links are stripped)
    skill_struct_pass(struct)          # Extract source from each section
    source_pass(struct, find_skill)    # Universal source handling
    _extract_key_ability(struct)       # Parse "(Dex)" from name
    _remove_related_feats(struct)      # Filter noise sections
    _strip_details_tags(struct)        # Remove widget HTML
    action_extract_pass(struct)        # Build structured actions
    skill_link_pass(struct)            # Extract links, strip <a> tags

    # 4. Universal passes
    aon_pass(struct, basename)         # Add aonid, game-obj
    restructure_pass(struct, "skill", find_skill)  # Move skill to top-level key
    remove_empty_sections_pass(struct)
    game_id_pass(struct)

    # 5. Content cleanup (AFTER restructure_pass moved skill)
    skill_cleanup_pass(struct)         # Promote fields to top-level

    # 6. Edition detection
    set_edition_from_db_pass(struct)   # DB lookup for edition

    # 7. License and markdown (LAST)
    license_pass(struct)
    _strip_block_tags(struct)          # Pre-strip <p>/<div> before markdown
    universal_markdown_pass(struct, struct["name"], "")

    # 8. Final cleanup
    _remove_empty_fields(struct)

    # 9. Validation
    struct["schema_version"] = 1.0
    validate_against_schema(struct, "skill.schema.json")
```

### Key ordering lessons

- **Extract action types BEFORE `skill_link_pass`**: Action span titles (e.g.,
  `<span class="action" title="Single Action">`) must be read before links are
  stripped. The `_extract_action_type_from_name` function parses these spans.
- **`restructure_pass` changes struct layout**: After this call, `find_skill(struct)`
  no longer works because the skill moves from `struct["sections"]` to
  `struct["skill"]`. Use `struct["skill"]` directly in `skill_cleanup_pass`.
- **`_strip_block_tags` before `universal_markdown_pass`**: The universal markdown_pass
  validates tags strictly. If your HTML has `<p>` or non-empty `<div>` tags, they must
  be unwrapped before reaching markdown validation. Write a pre-pass to handle this.
- **Edition detection**: Use `set_edition_from_db_pass` to look up edition from the
  sources database, OR use `edition_pass` from universal if your content has "Legacy
  Content" markers in sections.

## Use Universal Passes — Don't Reimplement

The biggest review feedback was about reimplemented utilities. Always check before
writing custom code:

### Must use from `universal/markdown.py`

- **`markdown_pass(struct, name, path, fxn_valid_tags=None)`** — Recursively walks the
  struct, validates tags, converts HTML to markdown. Do NOT write your own version.
- **`md(html)`** — Converts HTML string to markdown using `PFSRDConverter` (handles
  action spans, underlines, list formatting). Do NOT use `html2markdown.convert()`
  directly — it bypasses custom converters and produces inconsistent output.

### Must use from `universal/universal.py`

- **`get_links(bs, unwrap=True)`** — Extracts link objects from BeautifulSoup AND
  unwraps `<a>` tags in place. Do NOT write separate `while bs.a: bs.a.unwrap()` loops.
- **`build_object(dtype, subtype, name, keys=None)`** — Creates typed objects with
  consistent structure. Always use this instead of manual dict construction.
- **`extract_link(a_tag)`** — Parses anchor tags into link objects.
- **`extract_source(tag)`** — Parses source book references.

### Import patterns

```python
# Correct: use universal markdown_pass with alias
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.markdown import md

# Correct: import specific functions
from universal.universal import (
    aon_pass, build_object, entity_pass, extract_link, extract_source,
    game_id_pass, get_links, parse_universal, remove_empty_sections_pass,
    restructure_pass, source_pass,
)
from universal.utils import get_text
```

## HTML5 AoN Content Filter Pattern

All HTML5 AoN parsers need a `_content_filter` pre-filter:

```python
def _content_filter(soup):
    """Remove navigation elements before <hr> and unwrap the content span."""
    main = soup.find("div", id="main")
    if not main:
        return
    # Strip nav before first <hr>
    hr = main.find("hr")
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()
    # Unwrap content span containing h1
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
    # Remove empty anchors (AoN artifacts)
    for a in main.find_all("a"):
        if not a.string and not a.contents:
            a.decompose()
```

Use `cssclass="main"` with `parse_universal()` (not the old
`"ctl00_RadDrawer1_Content_MainContent_DetailedOutput"`).

## Action Classification Heuristic

Skills have both "real actions" (game actions with mechanics) and "descriptive sections"
(tables, condition descriptions) mixed together. The heuristic:

```python
if "action_type" in section or "source" in section:
    # Real action — has game mechanics
    section["type"] = "stat_block_section"
    section["subtype"] = "skill_action"
else:
    # Descriptive section — attach to preceding action
    section["type"] = "section"
```

- **`action_type`** comes from `<span class="action">` in the section name
- **`source`** (singular) comes from `<b>Source</b>` in the action text
- Descriptive sections get attached as subsections of the preceding action

When reclassifying a section from potential-action to plain-section, use
`_strip_action_fields()` to remove any action-specific keys that were extracted.

## Strategic Fragility Assertions

The parser should fail fast on unexpected data. Key patterns:

```python
# Assert skill section exists — every skill page must have one
skill = find_skill(struct)
assert skill is not None, f"No skill section found in {struct.get('name', 'unknown')}"

# Assert known action titles — catch new/changed AoN formats
assert title in _ACTION_TITLE_MAP, f"Unknown action title: {title}"

# Assert known attributes — catch typos and format changes
assert attr in KINGDOM_ATTRIBUTES, \
    f"Unknown parenthesized attribute '{attr}' in skill '{text}'"

# Direct access when key must exist at this pipeline stage
assert "skill" in struct, f"No skill object found in struct: {struct.get('name')}"
skill = struct["skill"]
```

Do NOT use defensive patterns like `struct.get("skill")` when the key must exist.
Silent `None` propagation produces empty output with no error.

## Schema Consistency Rules

When creating a new schema:

1. **Copy standard definitions** (`link`, `source`, `section`, `license`, etc.) from an
   existing schema like `creature.schema.json`
2. **Match field names** — use `requirement` (singular), not `requirements`
3. **Match enum values** — copy the full `action_type` name enum from creature schema
4. **Use `$ref`** for all reusable definitions
5. **Don't add fields that aren't populated** — remove speculative fields until data
   actually uses them (but keep fields the parser actively extracts)
6. **Separate parallel concepts** — use `key_ability` for character skills and
   `key_kingdom_ability` for kingdom skills, not one field with mixed semantics

## Empty Field Stripping

Add a `_remove_empty_fields` pass near the end of the pipeline (after markdown, before
schema validation) to clean up `""`, `None`, `[]`, `{}`:

```python
def _remove_empty_fields(obj):
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            _remove_empty_fields(obj[key])
            if _is_empty(obj[key]):
                del obj[key]
    elif isinstance(obj, list):
        for item in obj:
            _remove_empty_fields(item)
        obj[:] = [item for item in obj if not _is_empty(item)]
```

This must handle lists correctly — after recursing into list items, filter out items
that became empty (e.g., `[{"a": ""}]` → `[{}]` → `[]`).

## Testing

Write `tests/test_<type>.py` with the PR. Focus on:

1. **Pure extraction functions** — `_extract_bold_fields`, `_extract_result_blocks`,
   `_extract_sample_tasks` — these take HTML strings and produce dicts, easy to test
2. **Classification logic** — action vs section heuristic, skill type detection
3. **Edge cases** — empty inputs, missing fields, unknown values (assert failures)
4. **Empty field stripping** — `_is_empty` and `_remove_empty_fields` are trivial to test

You do NOT need to test the full pipeline end-to-end in unit tests — the parser run
against all files serves as the integration test.

## Common Pitfalls

1. **Don't use `html2markdown` directly** — always use `md()` from `universal.markdown`
2. **Don't reimplement tag stripping** — use `get_links(unwrap=True)` not manual loops
3. **Don't write a local `markdown_pass`** — use the universal one with `fxn_valid_tags`
   callback if you need custom tag handling
4. **Don't use `struct.get()` defensively** — use assertions when keys must exist
5. **`<span>` in markdown validation = unparsed content** — fix the extraction, don't
   add `span` to the valid tag set
6. **Watch `restructure_pass` layout changes** — after it runs, sections move to a
   top-level key. Code that searches `struct["sections"]` for the content type will
   break; use `struct["<type>"]` directly
7. **Pre-commit runs black and ruff** — run `ruff check --fix` before committing to
   catch import ordering and unused imports
