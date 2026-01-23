# Agents

## shared-utils-reviewer

Review code for duplication of shared utilities. Before reviewing, READ these files to understand what's available:

- `universal/utils.py`
- `universal/universal.py`

**Question any code that reimplements these patterns:**

### Text/String Processing
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `split_maintain_parens(text, split, parenleft, parenright)` | utils.py | Custom splitting that needs to respect parentheses |
| `split_comma_and_semicolon(text, parenleft, parenright)` | utils.py | Manual comma/semicolon splitting |
| `filter_entities(text)` | utils.py | Ad-hoc mojibake/encoding fixes |
| `clear_tags(text, taglist)` | utils.py | Manual tag stripping with regex or loops |
| `clear_end_whitespace(text)` | utils.py | Trailing br/whitespace removal |
| `clear_garbage(text)` | utils.py | Leading/trailing br/hr cleanup |
| `filter_end(text, tokens)` | utils.py | Loops removing trailing tokens |

### BeautifulSoup Helpers
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `get_text(detail)` | utils.py | `''.join(tag.findAll(text=True))` or `.get_text()` patterns |
| `has_name(tag, name)` | utils.py | `hasattr(tag, 'name') and tag.name == x` checks |
| `is_tag_named(element, taglist)` | utils.py | `type(x) == Tag and x.name in [...]` |
| `get_unique_tag_set(text)` | utils.py | Manual tag enumeration |
| `split_on_tag(text, tag)` | utils.py | Manual splitting at tag boundaries |
| `bs_pop_spaces(children)` | utils.py | While loops popping whitespace |

### Link Extraction
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `extract_link(a)` | universal.py | Manual anchor tag parsing |
| `extract_links(text)` | universal.py | Loops extracting multiple links |
| `get_links(bs, unwrap=False)` | universal.py | Manual game-obj link collection |
| `link_value(value, field, singleton)` | universal.py | Manual link extraction into dicts |
| `link_values(values, field, singleton)` | universal.py | Same for lists |
| `link_objects(objects)` | universal.py | Adding links to object lists |
| `link_modifiers(modifiers)` | universal.py | Adding links to modifier lists |

### Structured Object Building
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `build_object(dtype, subtype, name, keys)` | universal.py | Manual `{'type': x, 'subtype': y, 'name': z}` dicts |
| `build_objects(dtype, subtype, names, keys)` | universal.py | List comprehensions building objects |
| `build_value_object(dtype, subtype, value, keys)` | universal.py | Manual value-based object dicts |
| `extract_modifiers(text)` | universal.py | Manual "(mod1, mod2)" parsing |
| `string_with_modifiers(mpart, subtype)` | universal.py | Manual modifier extraction + object building |
| `string_with_modifiers_from_string_list(strlist, subtype)` | universal.py | Loops doing the above |
| `number_with_modifiers(mpart, subtype)` | universal.py | Number parsing with modifiers |
| `modifiers_from_string_list(modlist, subtype)` | universal.py | Manual modifier object creation |
| `parse_number(text)` | universal.py | Manual signed number parsing (handles em-dash for null) |

### Structure Walking
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `walk(struct, test, function, parent)` | universal.py | Recursive loops through nested dicts/lists |
| `test_key_is_value(k, v)` | universal.py | Lambda/function for walk() test |
| `break_out_subtitles(bs, tagname)` | universal.py | Manual splitting by subtitle tags |

### Tag Classification
| Function | Location | Use Instead Of |
|----------|----------|----------------|
| `is_trait(span)` | universal.py | `span.has_attr('class') and 'trait' in ...` |
| `is_action(span)` | universal.py | `span.has_attr('class') and 'action' in ...` |

**Review approach:**
1. Read the utility files first to understand exact signatures and behavior
2. For each new/modified function, ask: "Is this reimplementing something in universal?"
3. If yes, flag it with the specific function that should be used instead
4. Consider edge cases - sometimes a custom version is justified, but demand justification

## schema-consistency-reviewer

Review JSON schema changes in `pfsrd2/schema/` for consistency with existing patterns. Before reviewing, READ the existing schemas to understand established conventions.

**Core rules to enforce:**

1. **Arrays must contain typed objects**: Arrays should be arrays of objects with `type` and `subtype` properties, not arrays of primitives (unless matching an existing pattern).

2. **Object structure consistency**: If an object represents the same concept as one in another schema (e.g., `link`, `source`, `ability`), it should have the same superset of fields. Enum values can differ, but field names and types should match.

3. **Definition reuse**: Common objects should be defined in `#/definitions` and referenced with `$ref`, not duplicated inline.

4. **Required fields**: Objects should declare appropriate `required` fields matching the pattern of similar objects elsewhere.

**Review approach:**
1. For each schema change, identify the object type being added/modified
2. Search other schemas for the same object type (by subtype value or structure)
3. Compare field sets - flag missing fields that exist in other schemas
4. Verify arrays use object wrappers with type/subtype, not bare primitives
5. Check that new definitions are reused via `$ref` where appropriate

**Note:** It is acceptable to acknowledge a schema inconsistency and defer the fix by creating a beads ticket for schema re-alignment, rather than fixing it in the current PR.

## complexity-reviewer

Review **production code only** for function complexity. **Skip all files in `tests/` directory** - test files often have long test classes and helper functions that don't need the same complexity constraints.

Apply these heuristics:

1. **"And/Or" test**: Minimize the number of "and" or "or" needed to describe what a function does. If you need multiple conjunctions, the function is doing too much.
   - Good: "This function extracts traits from a stat block"
   - Bad: "This function extracts traits AND normalizes them AND adds links AND handles edge cases for variants"

2. **One-screen rule**: Functions should fit on one screen (~50-60 lines) so they can be reviewed at a glance. Longer functions are harder to reason about.
   - **Internal functions don't count**: When a function contains internal helper functions (defined with `def` inside the parent), the lines of those internal functions do NOT count against the parent's line limit. Only the "main body" lines count.
   - **Internal functions at the top**: Internal private functions should be declared at the top of their parent function, before the main logic begins.

3. **Extractable inner structures**: If a block of code within a function can be described on its own (has a clear purpose), consider extraction:
   - **First choice**: Extract to `universal/` if the pattern is reusable across multiple parsers
   - **Second choice**: Extract to module level (prefixed with `_`) if reusable within the file
   - **Last choice**: Keep as internal function if truly specific to the parent function's context

**Review approach:**
1. **Skip test files** - do not review files in `tests/` directory
2. For each new/modified function, try to describe it in one sentence without "and"/"or"
3. If the description requires conjunctions, identify which parts should be separate functions
4. Flag functions over ~50 lines (excluding internal function definitions) and suggest logical split points
5. Look for nested loops, long conditionals, or repeated patterns that could be extracted
6. For extractable code, prefer moving to `universal/` over local extraction when the pattern would benefit other parsers

**Note:** It is acceptable to acknowledge complexity and defer refactoring by creating a beads ticket, rather than fixing it in the current PR.

## import-reviewer

Review code for PEP8-compliant import practices. Imports belong at the top of the file, not inside functions.

**Rules to enforce:**

1. **Imports at top of file**: All imports should be at module level, after any module docstring and before any code.

2. **No function-level imports**: Flag any `import` or `from ... import` statements inside functions. These should be moved to the top of the file.

3. **Import ordering** (PEP8):
   - Standard library imports first
   - Blank line
   - Related third-party imports
   - Blank line
   - Local application/library imports

**Exceptions:**
- Conditional imports for optional dependencies (wrapped in try/except)
- Imports that would cause circular dependency issues (should be documented with a comment explaining why)

**Review approach:**
1. Search for `import` statements inside function bodies (`def` blocks)
2. Flag each with the specific function name and line
3. Suggest moving to the appropriate import section at file top

**Note:** It is acceptable to acknowledge import issues and defer cleanup by creating a beads ticket, rather than fixing it in the current PR.

## test-coverage-reviewer

Review code changes to ensure adequate test coverage and documentation for bug fixes.

**Rules to enforce:**

1. **Unit tests for touched code**: Any modified or new function should have corresponding unit tests in `tests/`. If tests don't exist for the modified code path, flag it.

2. **Bug fix documentation**: If the code change appears to be fixing a bug (based on commit message, PR title, variable names like `fix_`, comments mentioning "bug", "issue", "broken", etc.), require:
   - A comment explaining what was broken and why the fix works
   - Ideally a unit test that would have caught the bug (regression test)

3. **Test file naming**: Tests should be in `tests/test_<module>.py` matching the module being tested.

**Indicators of a bug fix:**
- Commit/PR title contains "fix", "bug", "issue", "broken", "regression"
- Code changes defensive checks or edge case handling
- Changes to exception handling or validation logic
- Comments in diff mentioning problems being solved

**Review approach:**
1. Identify which functions/methods were modified
2. Check if `tests/` contains tests for those functions
3. If the change looks like a bug fix, verify there's a comment explaining the bug
4. Suggest specific test cases that would validate the fix
5. For complex fixes, recommend a regression test that reproduces the original bug

**Good bug fix comment example:**
```python
# Fix: Previously, prices with modifiers like "(can't be crafted)" were not
# being parsed correctly - the modifier was left in the main price text.
# Now we extract modifiers into a separate list before parsing the value.
```

**Note:** It is acceptable to acknowledge missing tests and defer by creating a beads ticket, rather than adding tests in the current PR. However, bug fixes without explanatory comments should be flagged for immediate attention.

## strategic-fragility-reviewer

Review code to ensure it follows the **strategic fragility** design philosophy. This parser deliberately uses fail-fast, assertion-heavy patterns because **wrong data is worse than no data**.

**Core principle:** The parser should fail loudly and immediately when encountering unexpected conditions, rather than silently producing incorrect data.

**Reference:** Read `docs/architecture.md` section "Design Philosophy: Strict Validation Over Graceful Degradation" for full context.

**Patterns to FLAG (these damage strategic fragility):**

1. **Silent exception swallowing:**
   ```python
   # BAD - hides errors
   try:
       parse_data(html)
   except Exception:
       pass  # Silent failure!

   # BAD - returns default on error
   try:
       return parse_data(html)
   except:
       return {}  # Wrong data is worse than no data
   ```

2. **Return in finally blocks:**
   ```python
   # BAD - return in finally silences exceptions
   try:
       return do_something()
   finally:
       return default  # This silences any exception!
   ```

3. **Overly defensive defaults that mask missing data:**
   ```python
   # BAD - masks parsing failures
   defense = sections.pop(0) if sections else {}

   # GOOD - fails fast if section missing
   defense = sections.pop(0)  # Will raise IndexError if missing
   ```

4. **Generic exception handling without re-raising:**
   ```python
   # BAD - catches too much, doesn't re-raise
   try:
       complex_operation()
   except Exception as e:
       log.warning(f"Error: {e}")
       # Continues silently!
   ```

5. **Fallback logic that hides structural problems:**
   ```python
   # BAD - tries to "handle" bad HTML instead of failing
   if malformed_html:
       try_to_fix_it()
   elif missing_section:
       use_default()
   ```

**Patterns that ARE ACCEPTABLE:**

1. **Assertions with context:**
   ```python
   # GOOD - fails immediately with context
   assert len(children) == 2, f"Expected 2 children, got {len(children)}"
   ```

2. **Specific exception handling with re-raise:**
   ```python
   # GOOD - handles specific case, re-raises with context
   try:
       value = int(text.strip())
   except ValueError as e:
       raise ParseError(f"Invalid number format: {text}") from e
   ```

3. **Known exception handling for expected cases:**
   ```python
   # GOOD - handles documented case (creatures can have "-" for scores)
   try:
       ability_score = int(stat_text.strip())
   except ValueError:
       # Known case: creatures can have "-" for missing scores
       ability_score = None  # This is the CORRECT value for this case
   ```

4. **Bare except with re-raise (for cleanup):**
   ```python
   # GOOD - catches for cleanup, always re-raises
   try:
       do_something()
   except:
       cleanup()
       raise  # Re-raises original exception
   ```

**Why this matters:**

- Archives of Nethys HTML contains bugs and inconsistencies
- If parser silently handles bad HTML, bugs propagate to output data
- Users rely on accurate game data; incorrect AC/HP/abilities break gameplay
- Fail-fast surfaces problems immediately for human investigation
- HTML bugs should be fixed in pfsrd2-web, not worked around in parser

**Review approach:**
1. Search for `try/except` blocks - evaluate if they're swallowing errors
2. Check for `return` statements inside `finally` blocks
3. Look for defensive defaults like `x if y else {}` that could mask missing data
4. Identify bare `except:` without `raise`
5. Flag generic `except Exception` that doesn't re-raise

**Well-documented exceptions are acceptable:**

If the code includes a comment explaining *why* a particular pattern is used (e.g., a default value or exception handling), and the reasoning is sound and battle-tested, it's acceptable. The key is intentionality - the developer understood the trade-off and made a deliberate choice.

```python
# ACCEPTABLE - well-documented intentional choice
try:
    value = parse_optional_field(html)
except FieldNotFound:
    # This field was added in Bestiary 3; older creatures won't have it.
    # None is the correct value for pre-Bestiary 3 creatures.
    value = None
```

**Note:** If unsure whether a pattern damages strategic fragility, ask: "If the HTML is malformed here, would this code silently produce wrong data?" If yes and there's no documentation explaining the intentional choice, it should be flagged.

# Parser Testing Protocol

**Before starting a fix loop**, check for uncommitted changes in the output directory:
```bash
git -C ../pfsrd2-data status <type>/
```
If there are outstanding changes, **WARN the user** - uncommitted changes make it hard to identify drift from your fixes.

**After EACH parser fix**, run the validation cycle:

1. **Run the parser**:
   ```bash
   cd bin && ./pf2_run_<type>.sh <type>
   ```

   Parser script mapping:
   | Parser File | Script | Output Dir | Error Log |
   |-------------|--------|------------|-----------|
   | `equipment.py` | `pf2_run_equipment.sh equipment` | `pfsrd2-data/equipment/` | `errors.pf2.equipment.log` |
   | `creatures.py` | `pf2_run_creatures.sh` | `pfsrd2-data/monsters/` | `errors.pf2.creatures.log` |
   | `trait.py` | `pf2_run_traits.sh` | `pfsrd2-data/traits/` | `errors.pf2.traits.log` |
   | `condition.py` | `pf2_run_conditions.sh` | `pfsrd2-data/conditions/` | `errors.pf2.conditions.log` |
   | `skill.py` | `pf2_run_skills.sh` | `pfsrd2-data/skills/` | `errors.pf2.skills.log` |

2. **Check error log**:
   ```bash
   cat bin/errors.pf2.<type>.log
   ```
   - New errors = your fix broke something
   - Fewer errors = progress
   - Same errors = fix didn't help or wrong file

3. **Check for data drift**:
   ```bash
   git -C ../pfsrd2-data diff <type>/
   ```

   **Concerning changes to flag:**
   - Files you didn't intend to modify
   - Unexpected field removals or nullifications
   - Large-scale changes from a "small" fix
   - Data that looks corrupted or truncated

   **Expected changes:**
   - Files related to your fix
   - Consistent field additions/corrections across similar items

4. **If drift is concerning**, revert and reconsider the approach before proceeding.

# Guidelines

- **HTML bugs vs Code bugs**: One-off HTML errors get fixed in pfsrd2-web. Consistent patterns get handled in parser code.
- **Evolution over rewrites**: Extend existing patterns rather than creating parallel implementations.
- **Measure before optimizing**: Don't add complexity without demonstrated need.
