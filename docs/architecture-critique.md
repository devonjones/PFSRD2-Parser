# PFSRD2-Parser Architecture Critique

This document provides a critical assessment of the PFSRD2-Parser architecture in the context of its problem space.

## Problem Space Analysis

### The Challenge

The PFSRD2-Parser addresses a complex parsing problem:

1. **Source Material**: Semi-structured, hand-maintained HTML from Archives of Nethys
2. **Extraction Goal**: Extract complex tabletop RPG mechanics into structured, discrete fields
3. **Scale**: Process hundreds to thousands of entities per content type
4. **Variability**: Significant format variation within and across content types
5. **Multi-System**: Support multiple game systems (PF1e, PF2e, Starfinder)
6. **Evolution**: Enable iterative improvement as mechanics are progressively extracted
7. **Maintenance**: Adapt as source HTML and game rules evolve

### Success Criteria

For this architecture to succeed, it must:

- **Extract structured mechanics** - Move game mechanics from opaque text to discrete fields
- **Handle variation** - Process inconsistent HTML without silent failures
- **Enable iteration** - Support progressive enhancement over time
- **Maintain quality** - Produce validated, correct data
- **Support debugging** - Make it easy to identify and fix parsing issues
- **Scale appropriately** - Handle thousands of files in reasonable time
- **Remain maintainable** - Allow developers to understand and modify parsers

## Architecture Assessment

### Major Strengths

#### 1. Pass-Based Pipeline Architecture

**Design:**
```
HTML → parse_universal() → entity_pass() → restructure_pass() →
section_pass() → addon_pass() → trait_db_pass() → game_id_pass() →
license_pass() → markdown_pass() → schema validation → JSON output
```

**Assessment: ✅ Excellent Fit**

The multi-stage pipeline is well-suited for progressive extraction:

**Strengths:**
- **Iterative refinement**: Can add new passes without modifying existing ones
- **Separation of concerns**: Each pass has one responsibility
- **Easy debugging**: Can inspect output after each pass to see where issues occur
- **Progressive enhancement**: Directly supports the stated goal of iteratively extracting mechanics
- **Composability**: Passes can be reordered or conditionally applied
- **Clear data flow**: Easy to understand transformation sequence

**Example of effectiveness:**
When adding aura extraction, developers can add a new `aura_pass()` without touching existing passes. The fail-fast behavior ensures the new pass doesn't silently corrupt data.

**Verdict:** This is the **right architectural pattern** for the problem space.

---

#### 2. Fail-Fast Philosophy

**Design:**
```python
assert len(rest) == 0, "More sections than expected (1)"
assert data, "%s | %s" % (data, trait)
assert current in addon_names, "%s, %s" % (current, addon_names)
```

**Assessment: ✅ Correct for This Use Case**

The assertion-heavy, exception-propagating approach is appropriate:

**Strengths:**
- **Immediate feedback**: Errors appear instantly with full context
- **Error log reprocessing**: The `.log` rename trick enables targeted reruns
- **Data quality enforcement**: Forces addressing issues rather than producing bad data
- **Development workflow match**: Aligns with iterative fix-and-rerun cycle
- **No silent failures**: All problems surface immediately
- **Rich error context**: Assertions include variable values for debugging

**The Error Log Pattern:**
```bash
# Run parser, some files fail
./pf2_run_creatures.sh
# Errors logged to: errors.pf2.monsters.log

# Fix parser code, reprocess only failures
mv errors.pf2.monsters.log errors.pf2.monsters
./pf2_run_creatures.sh  # Only processes files in errors.pf2.monsters
```

This is **elegant and effective**. The fail-fast approach feeds this workflow perfectly.

**Trade-off Recognition:**
This would be **wrong for a production API** serving live traffic. But for a data curation tool, it's the **correct choice**.

**Verdict:** Design decision is **well-matched to the problem**.

---

#### 3. Universal/Game-Specific Separation

**Design:**
```
universal/          # Game-agnostic logic
├── universal.py    # Common parsing patterns
├── utils.py        # Shared utilities
└── markdown.py     # Markdown conversion

pfsrd2/            # PF2e-specific logic
├── creatures.py   # PF2e creature parsing
├── trait.py       # PF2e trait parsing
└── constants.py   # PF2e-specific constants
```

**Assessment: ✅ Good Architecture for Multi-System Support**

The separation enables effective code reuse:

**Strengths:**
- **Code reuse**: Common patterns (link extraction, source parsing) shared across systems
- **System isolation**: PF2e-specific rules don't leak into PF1e or Starfinder
- **Clear boundaries**: Easy to understand what's universal vs game-specific
- **Independent evolution**: Can update PF2e without affecting PF1e
- **Maintainability**: Changes to common patterns benefit all systems

**Example:**
The `extract_link()` function in `universal/universal.py` works for all game systems, while `trait_db_pass()` in `pfsrd2/` handles PF2e-specific trait enrichment.

**Verdict:** **Well-designed** separation of concerns.

---

#### 4. Schema-Driven Development

**Design:**
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "properties": {
    "name": {"type": "string"},
    "type": {"enum": ["ability"]},
    "game-id": {"type": "string"},
    "sources": {"$ref": "#/definitions/sources"}
  },
  "required": ["name", "type", "game-id", "sources", "schema_version"]
}
```

**Assessment: ✅ Essential for the Mission**

Using JSON schemas as contracts is the right approach:

**Strengths:**
- **Documentation**: Schemas document the full extent of data exposed
- **Validation**: Catches structural errors and missing required fields
- **Evolution support**: Version tracking enables schema changes over time
- **Consumer contract**: Tools integrating the data know exactly what to expect
- **Mission alignment**: Directly supports "discrete schema that documents the files"

**This directly addresses the project mission:**
> "Our goal is to express every aspect of the game system mechanics through a discrete, structured schema that documents the files so people can integrate with them."

**Verdict:** **Critical architectural component** that enables the core mission.

---

#### 5. Database Enrichment Pattern

**Design:**
```python
def trait_db_pass(struct):
    """Enrich traits from canonical database"""
    # Query trait database
    fetch_trait_by_name(curs, trait['name'])
    db_trait = curs.fetchone()

    # Merge with inline data
    if 'classes' in trait and 'classes' in db_trait:
        db_trait['classes'].extend(trait['classes'])
        db_trait['classes'] = list(set(db_trait['classes']))

    # Replace with enriched version
    parent[index] = db_trait
```

**Assessment: ✅ Smart Solution**

Using SQLite for reference data solves real problems:

**Strengths:**
- **Consistency**: Traits/abilities pulled from canonical source
- **Deduplication**: Trait defined once, referenced many times
- **Edition handling**: Links legacy and remastered versions elegantly
- **Performance**: Fast lookups during parsing (indexed queries)
- **Data quality**: Reduces redundancy and inconsistency
- **Cross-referencing**: Enables linking between entity types

**Example Use Case:**
The "fire" trait appears in hundreds of creatures. Database ensures all references use identical trait data, including proper classes and edition links.

**Verdict:** **Well-designed pattern** for the problem domain.

---

### Significant Concerns

#### 1. Fragile Stateful Parsing

**Problem:**
```python
def process_stat_block(sb, sections):
    stats = sections.pop(0)      # Assumes first is stats
    defense = sections.pop(0)    # Assumes second is defense
    offense = sections.pop(0)    # Assumes third is offense
```

**Assessment: 🟡 Medium Impact - Brittle but Recoverable**

The `pop(0)` sequential consumption pattern makes strong ordering assumptions:

**Issues:**
- **Implicit ordering**: Nowhere explicitly states "sections must be [Stats, Defense, Offense]"
- **Evolution fragility**: HTML structure changes break parsing
- **Hard to debug**: Error messages don't explain what section was expected

**Why Not High Risk:**
- ✅ **Fails fast**: Breaks immediately with clear stack trace, not silently
- ✅ **Error logs capture it**: Failed files logged to `errors.pf2.*.log`
- ✅ **HTML is curated**: Can fix structure issues in pfsrd2-web if needed
- ✅ **Recovery is straightforward**: Error log reprocessing enables targeted reruns

**Example Failure Scenario:**
If Archives of Nethys adds a new optional section before "Defense", parser fails immediately with IndexError or wrong data assertion.

**Better Approach:**
```python
def process_stat_block(sb, sections):
    """Process stat block with named section lookup"""

    # Tag sections with identifiers during initial parse
    stats = get_section_by_name(sections, "Statistics", required=True)
    defense = get_section_by_name(sections, "Defense", required=True)
    offense = get_section_by_name(sections, "Offense", required=True)

    # Or use lookahead pattern
    if sections and is_stats_section(sections[0]):
        stats = sections.pop(0)
    else:
        raise ParseError(f"Expected Statistics section, got: {sections[0]}")
```

**Benefits:**
- Explicit about what's expected
- Better error messages showing what was expected vs. received
- More resilient to structure changes
- Can handle missing optional sections

**Recommendation:** Add defensive section identification before pop() for better error messages and resilience.

**Impact:** 🟡 **Medium** - Will break when HTML structure evolves, but fails fast with good recovery mechanisms

---

#### 2. No Abstraction for Common Patterns

**Problem:**
The same parsing patterns appear repeatedly without abstraction:

```python
# This pattern appears dozens of times across parsers
bs = BeautifulSoup(text, 'html.parser')
children = list(bs.children)
while children:
    child = children.pop(0)
    if child.name == 'b':
        # extract label
    elif child.name == 'a':
        # extract link
    elif child.name == 'br':
        # handle break
```

**Assessment: 🟡 Medium Impact - Reduces Maintainability**

**Issues:**
- **Code duplication**: Same logic repeated in every parser
- **Inconsistency risk**: Each implementation slightly different
- **Hard to improve**: Changes require updating many files
- **No reusable patterns**: Each parser reinvents extraction logic
- **Cognitive load**: Developers must understand low-level parsing repeatedly

**Examples of Repeated Patterns:**

1. **Labeled field extraction** (appears in ~10 parsers):
```python
# Repeated pattern
current = None
parts = []
while children:
    child = children.pop(0)
    if child.name == 'b':
        if current:
            save_field(current, parts)
        current = get_text(child)
        parts = []
    else:
        parts.append(child)
```

2. **Split and repair parentheses** (appears in multiple parsers):
```python
# Same logic in creatures.py, skill.py, etc.
parts = text.split(",")
newparts = []
while parts:
    part = parts.pop(0)
    if "(" in part and ")" not in part:
        while ")" not in part:
            part += ", " + parts.pop(0)
    newparts.append(part)
```

**Better Approach:**

Create reusable extraction primitives:

```python
# Generic labeled field extractor
def extract_labeled_fields(html, labels, optional=False):
    """
    Extract fields marked with bold labels

    Example:
        HTML: "<b>Frequency</b> once per day; <b>Trigger</b> you are hit"
        labels: ['Frequency', 'Trigger']
        Returns: {
            'frequency': 'once per day',
            'trigger': 'you are hit'
        }
    """
    pass

# Generic split-and-repair
def split_maintain_semantic_units(text, delimiter, units=['()']):
    """Split on delimiter but preserve parenthetical units"""
    pass

# Generic pattern matcher with better errors
class PatternMatcher:
    def __init__(self, patterns, examples):
        self.patterns = patterns
        self.examples = examples

    def match(self, text):
        for name, pattern in self.patterns.items():
            m = re.match(pattern, text)
            if m:
                return name, m.groups()

        # Better error message
        raise ParseError(
            f"No pattern matched: {text}\n"
            f"Expected one of:\n" +
            "\n".join(f"  {name}: {ex}" for name, ex in self.examples.items())
        )
```

**Usage:**
```python
# Before (creatures.py, monster_ability.py, skill.py all duplicate this)
bs = BeautifulSoup(text, 'html.parser')
children = list(bs.children)
# ... 30 lines of extraction logic ...

# After
addons = extract_labeled_fields(
    text,
    labels=['Frequency', 'Trigger', 'Effect', 'Duration'],
    optional=True
)
ability.update(addons)
```

**Benefits:**
- Reduces duplication from ~100 lines per parser to ~5 lines
- Ensures consistency across parsers
- Makes improvements benefit all parsers
- Easier to understand (high-level intent vs low-level mechanics)
- Better error messages in one place

**Recommendation:** Create `universal/extractors.py` with common patterns.

**Impact:** 🟡 **Medium** - Makes maintenance harder but not blocking

---

#### 3. Regex Brittleness

**Problem:**
Complex regex patterns scattered throughout with poor documentation:

```python
# From creatures.py - what does this match?
m = re.search(r"^(.*) ([+-]\d*) \[(.*)\] \((.*)\), (.*)$", text)

# From skills.py - unclear what format this expects
m = re.match(r"^\(?(\d*)[snrt][tdh]\)?$", level_text)
```

**Assessment: 🟡 Medium Impact - Hard to Debug**

**Issues:**
- **Unclear intent**: Hard to understand what format is being matched
- **Poor debugging**: Failures give cryptic "no match" errors
- **No examples**: No documentation of valid input strings
- **Maintenance burden**: Modifying regex requires deep pattern knowledge
- **No explanation**: Why these specific patterns?

**Example of Poor Error:**
```
AssertionError: Failed to parse: longsword +16 [+12/+8] (magical), Damage 2d8+10
```
What was expected? What part failed to match?

**Better Approach:**

1. **Use named capture groups:**
```python
ATTACK_PATTERN = re.compile(
    r"^(?P<weapon>.*)"           # Weapon name
    r" (?P<bonus>[+-]\d+)"       # Attack bonus
    r" \[(?P<map>.*)\]"          # Multiple Attack Penalty
    r"(?: \((?P<traits>.*)\))?"  # Optional traits
    r", (?P<damage>.*)$"         # Damage
)

m = ATTACK_PATTERN.match(text)
if m:
    data = m.groupdict()
    # Access as data['weapon'], data['bonus'], etc.
```

2. **Document patterns with examples:**
```python
ATTACK_PATTERNS = {
    'with_traits': {
        'pattern': r"^(.*) ([+-]\d*) \[(.*)\] \((.*)\), (.*)$",
        'description': "Attack with traits in parentheses",
        'examples': [
            "longsword +16 [+12/+8] (magical, versatile P), Damage 2d8+10",
            "claw +18 [+14/+10] (agile, reach 10 feet), Damage 3d6+9 slashing"
        ]
    },
    'without_traits': {
        'pattern': r"^(.*) ([+-]\d*) \[(.*)\], (.*)$",
        'description': "Attack without traits",
        'examples': [
            "bite +15 [+10/+5], Damage 2d6+8 piercing",
        ]
    }
}
```

3. **Better error messages:**
```python
def parse_attack_with_patterns(text):
    for name, pattern_info in ATTACK_PATTERNS.items():
        m = re.match(pattern_info['pattern'], text)
        if m:
            return name, m.groups()

    # No pattern matched - give helpful error
    raise ParseError(
        f"Attack format not recognized: {text}\n\n"
        f"Expected one of:\n" +
        "\n".join(
            f"  {name}: {info['description']}\n"
            f"    Example: {info['examples'][0]}"
            for name, info in ATTACK_PATTERNS.items()
        )
    )
```

**Benefits:**
- Clear documentation of expected formats
- Better error messages show what was expected
- Named groups make code self-documenting
- Examples serve as tests and documentation
- Easier to add new pattern variants

**Recommendation:** Create `pfsrd2/patterns.py` with documented pattern registry.

**Impact:** 🟡 **Medium** - Makes debugging painful but patterns work

---

#### 4. Strict HTML Structure Validation: A Design Choice

**Design Decision:**
Parsers make strong assumptions about HTML structure and fail immediately when violated:

```python
# From creatures.py
assert len(children) == 2, "Expected 2 children"
assert children[0].__class__ == NavigableString, "Expected string"
assert children[1].name == "ul", "Expected <ul>"

# Assumes specific positions
obj = children[0]  # Must be text
ul = children[1]   # Must be list
```

**Assessment: ✅ Deliberate and Correct**

**Why This Approach is Right:**

This isn't accidental brittleness - it's a **deliberate design choice** that serves the core goal: **catching errors, not hiding them**.

**Critical Insight: Archives of Nethys introduces bugs**

The source HTML can have:
- **HTML structural bugs** - Malformed tags, missing elements, broken nesting
- **Data corruption** - Missing stat block sections, deleted content, incomplete entries
- **Inconsistencies** - Same entity type with different HTML structure

**Goal: Surface errors immediately, don't hide them**

The fail-fast, assertion-heavy approach ensures:
- ✅ **AoN HTML bugs are immediately visible** - Malformed HTML causes instant failure
- ✅ **Data corruption is caught** - Missing sections trigger assertions
- ✅ **Nothing silently produces wrong data** - No partial/incorrect parsing
- ✅ **Error location is obvious** - Assertion shows exactly what's wrong
- ✅ **Forces fixing root cause** - Can't ship bad data

**Why "Graceful Degradation" Would Be Worse:**

Alternative approach (try to be "robust" with fallbacks):
- ❌ AoN bugs might go unnoticed until much later
- ❌ Data corruption could silently propagate to output
- ❌ Wrong data is MUCH worse than no data
- ❌ Debugging becomes detective work ("which field is wrong?")
- ❌ Users get incomplete/incorrect game data

**Wrong data is worse than no data** - for a game system reference, correctness is paramount.

**HTML Coupling is Inherent:**

You cannot parse HTML without coupling to its structure. This is the nature of the problem:
- **Any HTML parser** must make assumptions about structure
- **Structural changes will break parsing** - this is unavoidable
- **But fixes are localized** - Usually 1-2 spots in code

**When AoN Changes Structure:**

**Large changes:**
- Parser fails loudly and obviously (good!)
- Fix is typically in 1-2 places
- Error logs show which files affected
- Reprocess only affected entities

**Small changes (adding optional fields):**
- May or may not break depending on what changed
- Assertions make expectations explicit
- Easy to add handling for new optional fields

**Example: AoN Bug Caught by Parser:**

```python
# AoN accidentally deletes defense section from a creature
def process_stat_block(sections):
    stats = sections.pop(0)
    defense = sections.pop(0)  # ← Fails here with IndexError
    offense = sections.pop(0)
```

**With fail-fast:**
- ✅ Parser immediately fails with clear error
- ✅ Error log identifies the problematic file
- ✅ Human investigates and finds missing defense section
- ✅ Fix HTML in pfsrd2-web or report to AoN

**With graceful degradation:**
- ❌ Parser might assume no defense section
- ❌ Outputs creature with missing defense stats
- ❌ Wrong data gets committed
- ❌ Users get incorrect game information
- ❌ Harder to notice problem later

**Better Error Messages:**

Current approach is correct, but error messages could be more helpful:

```python
# Current: Minimal context
assert len(children) == 2, "Expected 2 children"

# Better: Rich context for debugging
if len(children) != 2:
    raise ParseError(
        f"Mythic ability expects 2 children (text + list), got {len(children)}\n"
        f"Content: {text[:200]}...\n"
        f"Children types: {[type(c).__name__ for c in children]}\n"
        f"This usually means AoN HTML structure changed or has a bug."
    )
```

**Critical Architecture Decision: Fix HTML in Source, Not in Code**

When AoN has HTML bugs, the approach is:
- ✅ **Fix the HTML directly in pfsrd2-web repository**
- ✅ Maintain fixes in `modified` branch
- ✅ Keep parser simple (assumes clean HTML)
- ❌ Don't make parser handle bad HTML

**The pfsrd2-web Transform Pipeline:**

```bash
# 1. Download raw HTML from AoN
wget -rp http://2e.aonprd.com

# 2. Transform for minimal diffs
xmllint --format --html --htmlout $file > $file.html  # Pretty print
sed -e ':a;N;$!ba;s/\n//g' $file.html                 # Remove all newlines
sed -e 's/>/>\n/g' $file.html                         # Add newline after each >

# Result: One tag per line = minimal git diffs
```

**Git Workflow in pfsrd2-web:**
1. `upstream` branch: Clean downloads from AoN (transformed)
2. `modified` branch: upstream + your HTML fixes
3. On AoN update: merge upstream → modified, resolve conflicts
4. Git tracks: What's from AoN vs what you fixed

**Why This is Brilliant:**

✅ **Parser stays simple** - Handles clean HTML only, no workarounds for bad HTML
✅ **Fixes are version controlled** - Git history shows what you changed and why
✅ **Provenance is clear** - Can distinguish AoN bugs from your corrections
✅ **Transform minimizes diff noise** - One tag per line creates clean, readable diffs
✅ **Merge workflow handles updates** - Git merge handles AoN changes, surfaces conflicts
✅ **Fail-fast validates fixes** - Parser errors mean your HTML fix didn't work

**This Changes Everything:**

This isn't just an HTML parser - it's a **sophisticated data curation pipeline**:

```
AoN Website
    ↓ wget
Raw HTML Download
    ↓ Transform (xmllint + sed)
Normalized HTML [upstream branch]
    ↓ Merge
HTML Fixes [modified branch] ← Fix AoN bugs here
    ↓ PFSRD2-Parser
Validated JSON [pfsrd2-data]
```

**HTML coupling is not a weakness** - it's part of a deliberate strategy:
- You **control the HTML** (pfsrd2-web modified branch)
- Parser **validates your fixes** (fail-fast catches mistakes)
- Git **tracks provenance** (what's upstream vs your changes)
- Transform **enables clean diffs** (one tag per line)

**Recommendation:**
- ✅ Keep strict structural assertions (they validate HTML fixes)
- ✅ Fix HTML bugs in pfsrd2-web, not parser code
- ✅ Use fail-fast to catch when fixes don't work
- ✅ Improve error messages to aid debugging
- ❌ Don't add graceful degradation (hides problems)
- ❌ Don't make parser handle bad HTML (fix source instead)

**Impact:** ✅ **Excellent Design** - Part of a sophisticated data curation pipeline, not just parsing

---

#### 5. Testing Strategy: Data-Driven Regression Testing

**Actual Approach:**
The codebase uses **data-driven regression testing** - the actual dataset serves as the test suite.

**Assessment: ✅ Sophisticated and Appropriate**

**Current Workflow:**

```bash
# 1. Make changes to parser
vim pfsrd2/creatures.py

# 2. Progressive validation
./pf2_creature_parse goblin_warrior.html    # Simple case (seconds)
./pf2_run_creatures.sh -n 100                # First 100 (minutes)
./pf2_run_creatures.sh                       # Full dataset (hours)

# 3. Check what changed
cd ../pfsrd2-data
git diff monsters/

# 4. Validate changes
# - No diff = safe refactoring ✓
# - Small diff = investigate (bug fix or regression?)
# - Large unexpected diff = broke something
```

**Why This Works Well:**

✅ **Tests against real data**, not synthetic fixtures
✅ **Catches actual regressions** in production data
✅ **Git diff shows exactly what changed** and where
✅ **Progressive validation** (simple → 100 → all) for fast iteration
✅ **No test maintenance burden** - data IS the test
✅ **Tests the full pipeline**, not just isolated units
✅ **Comprehensive coverage** - all real-world edge cases included

**This is similar to how compilers are tested:**
- Unit tests for compiler components
- But ultimate validation is: does it correctly compile real programs?

**Trade-offs:**

**Strengths:**
- Real-world validation
- No fixture maintenance
- Comprehensive coverage
- Git provides diff visualization

**Limitations:**
- Slow feedback loop for full validation (hours)
- Can't easily test hypothetical edge cases
- Hard to isolate specific parsing scenarios
- No fast inner loop for helper refactoring

**Complementary Unit Testing:**

While data-driven testing validates full parsers, **unit tests would add value for specific components:**

### High Value: Testing Extraction Helpers

If you create common extraction primitives, unit tests enable fast iteration:

```python
# tests/test_extractors.py
def test_extract_labeled_fields():
    """Test generic addon extractor - runs in milliseconds"""
    html = "<b>Frequency</b> once per day; <b>Trigger</b> hit by attack"
    result = extract_labeled_fields(html, ['Frequency', 'Trigger'])

    assert result['frequency'] == "once per day"
    assert result['trigger'] == "hit by attack"

def test_split_maintain_parens():
    """Test parentheses-aware splitting"""
    text = "skill +10 (bonus, modifier), another +5"
    result = split_maintain_parens(text, ",")

    assert len(result) == 2
    assert result[0] == "skill +10 (bonus, modifier)"
```

**Value:** Tightens inner loop from hours to seconds when refactoring helpers

### Medium Value: Edge Case Documentation

Test specific patterns not well-represented in current dataset:

```python
def test_attack_damage_edge_cases():
    """Document tricky parsing scenarios"""

    # Persistent with parenthetical note
    result = parse_attack_damage("3d6 persistent fire (from ghost touch)")
    assert result[0]['persistent'] == True
    assert result[0]['notes'] == "from ghost touch"

    # Effect (not damage)
    result = parse_attack_damage("see Sphere of Oblivion")
    assert result[0]['effect'] == "see Sphere of Oblivion"
```

**Value:** Documents edge cases, complements data-driven testing

### Low Value: Full Parser Unit Tests

Your data-driven approach already provides this. Testing full parsers with fixtures would be:
- Redundant with real data testing
- Require fixture maintenance
- Less comprehensive than real dataset

**Hybrid Testing Strategy:**

```
┌─────────────────────────────────────────────────┐
│  Unit Tests (seconds)                           │
│  - Extraction helpers                           │
│  - Regex patterns                               │
│  - Edge cases                                   │
│  Purpose: Fast inner loop for utilities         │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Progressive Data Testing (minutes to hours)    │
│  1. Simple case: goblin_warrior.html            │
│  2. First 100 creatures                         │
│  3. Full dataset                                │
│  Purpose: Real-world validation                 │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Git Diff Review                                │
│  - No change: safe refactoring ✓                │
│  - Expected change: feature working ✓           │
│  - Unexpected change: investigate               │
│  Purpose: Ultimate arbiter of correctness       │
└─────────────────────────────────────────────────┘
```

**Recommendation:**
- Continue using data-driven testing for full parsers (it works well)
- Add unit tests when creating reusable extraction helpers
- Use unit tests to document edge cases
- Don't bother with fixture-based full parser tests

**Impact:** 🟡 **Medium** - Unit tests would complement but not replace data-driven approach

---

#### 6. Limited State Dumping for Debugging

**Problem:**
When parsers fail, debugging requires manual code inspection and state emission:

**Current Debugging Workflow:**
1. Parser fails on specific file
2. Developer manually adds print/pprint statements to emit state
3. Run parser against failed file to see state
4. Fix issue based on inspection
5. Remove debug statements

**Assessment: 🟡 Medium Impact - Manageable but Could Be Better**

**Issues:**
- **Manual state inspection**: Requires code modification to see state
- **Agent-based work harder**: Agents can't easily see parser state at failure point
- **No standard approach**: Each developer adds their own debug code
- **Time consuming**: Add debug code → run → remove debug code cycle

**Why It Works Currently:**
- ✅ **Small team**: Developer knows where to look
- ✅ **Fail-fast helps**: Error location is usually clear
- ✅ **Error logs identify files**: Know exactly which file failed

**Better Approach for Agent-Based Work:**

```python
# Add structured state dumping on failure
def parse_creature(filename, options):
    try:
        # ... normal parsing ...
        return struct
    except Exception as e:
        if options.debug or options.dump_on_error:
            # Dump parser state to file
            debug_output = {
                'filename': filename,
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc(),
                'parser_state': {
                    'details': details if 'details' in locals() else None,
                    'struct': struct if 'struct' in locals() else None,
                    'current_pass': get_current_pass_name(),
                }
            }
            dump_path = f"debug/{os.path.basename(filename)}.debug.json"
            with open(dump_path, 'w') as f:
                json.dump(debug_output, f, indent=2, default=str)

            sys.stderr.write(f"Debug state dumped to: {dump_path}\n")
        raise
```

**Benefits:**
- Automatic state capture on failure
- Agent can read debug files to understand what went wrong
- Standard format for debugging information
- No manual code modification needed
- Structured data (JSON) for easy inspection

**Recommendation:**
- Add `--debug` or `--dump-on-error` flag to parsers
- Dump parser state to `debug/` directory on failure
- Include: error, traceback, parser state, intermediate structures
- Especially useful for agent-based development

**Impact:** 🟡 **Medium** - Would improve debugging workflow, especially for agent-based work

---

### Architectural Trade-offs

#### Fail-Fast vs. Robustness

**Decision Made:** Fail fast with assertions

**Context:**
- Development tool for data curation
- Batch processing, not real-time serving
- Data quality is paramount
- Errors should be fixed, not silently tolerated

**Assessment:** ✅ **Correct choice for this use case**

**Would be wrong for:**
- Production API serving live traffic
- Real-time parsing on user input
- Systems requiring high availability

**Would be right for:**
- Data pipelines and batch processing ✓
- Development and data curation tools ✓
- Systems where data quality > availability ✓

---

#### Simplicity vs. Abstraction

**Decision Made:** Prefer simple, explicit parsing logic over abstractions

**Rationale:**
- Easier for domain experts to understand
- Clear what each parser does
- No "magic" abstraction layers

**Assessment:** 🟡 **Reasonable but taken too far**

**Benefits:**
- ✅ Easy to understand individual parsers
- ✅ No complex framework to learn
- ✅ Domain experts can contribute

**Costs:**
- ❌ Too much code duplication
- ❌ Inconsistency across parsers
- ❌ Changes are expensive
- ❌ Common patterns not reusable

**Better Balance:**
- Keep explicit logic in parsers
- Extract common patterns to utilities
- Provide helper functions, not frameworks
- Document patterns well

**Example:**
```python
# Good: Explicit but uses helpers
def parse_monster_ability(html):
    name = extract_name(html)
    traits = extract_traits(html)
    addons = extract_labeled_fields(html, ['Frequency', 'Trigger'])
    text = extract_text_after_addons(html)

    return {
        'name': name,
        'traits': traits,
        **addons,
        'text': text
    }

# Bad: Too abstract
def parse_monster_ability(html):
    return GenericParser(html)\
        .with_extractor(NameExtractor())\
        .with_extractor(TraitExtractor())\
        .with_extractor(AddonExtractor(['Frequency', 'Trigger']))\
        .parse()
```

**Recommendation:** Add targeted abstractions for most common patterns while keeping parsers explicit.

---

#### Performance vs. Maintainability

**Decision Made:** Optimize for maintainability over performance

**Evidence:**
- Uses BeautifulSoup (slow but easy) over lxml (fast but complex)
- No optimization of pass ordering
- Recreates BeautifulSoup objects frequently
- No caching of database queries

**Assessment:** ✅ **Correct priority**

**Context:**
- Batch processing, not real-time
- Run pipelines occasionally, not continuously
- Developer time more expensive than CPU time
- Readability matters more than speed

**Performance Characteristics:**
- Parsing ~1000 creatures takes minutes, not hours
- Database lookups are fast (indexed)
- Bottleneck is likely I/O, not CPU

**Is Performance a Problem?**
- No evidence of performance complaints
- Pipeline completes in reasonable time
- Error log reprocessing enables incremental runs

**When Performance Would Matter:**
- If datasets grow to 100,000+ entities
- If real-time parsing is needed
- If parsers run continuously

**Recommendation:** Continue optimizing for maintainability until performance becomes a problem.

---

#### Flexibility vs. Strictness

**Decision Made:** Strict structure assumptions with assertions

**Rationale:**
- Validate HTML structure
- Catch errors immediately
- Make assumptions explicit

**Assessment:** 🟡 **Slightly too strict, but reasonable**

**Benefits:**
- ✅ Catches structure bugs
- ✅ Forces fixing inconsistencies
- ✅ Makes expectations explicit

**Costs:**
- ❌ Brittle to HTML changes
- ❌ No tolerance for variations
- ❌ Requires ongoing maintenance

**Better Balance:**
- Keep assertions for critical structure
- Add flexibility for minor variations
- Provide better error messages
- Consider fallback strategies

**Example:**
```python
# Current: Strict
assert len(children) == 2

# Better: Strict but informative
if len(children) != 2:
    raise ParseError(f"Expected 2 children, got {len(children)}: {children}")

# Even better: Flexible for minor variations
if not (1 <= len(children) <= 3):
    raise ParseError(f"Expected 1-3 children, got {len(children)}")

# Handle variations
text_node = find_child(children, NavigableString)
list_node = find_child(children, lambda c: c.name == 'ul')
```

**Recommendation:** Maintain strictness but add escape hatches for known variations.

---

### Missing Components

The following components would significantly improve the architecture:

#### 1. Parser Combinators or Builder Pattern (Priority: Low)

**What's Missing:**
Higher-level primitives for composing parsers

**Current Approach:**
```python
# Low-level parsing everywhere
bs = BeautifulSoup(text, 'html.parser')
children = list(bs.children)
# ... 30 lines of extraction logic ...
```

**Potential Improvement:**
```python
# Hypothetical high-level API
ability_parser = (
    ExtractField('name', required=True)
    .then(ExtractTraits())
    .then(ExtractLabeledValue('Frequency', optional=True))
    .then(ExtractLabeledValue('Trigger', optional=True))
    .then(ExtractText())
)
result = ability_parser.parse(html)
```

**Assessment:**
- **Nice to have** but not critical
- Would reduce duplication
- Risk of over-abstraction
- **Recommendation:** Start with simple helper functions first

---

#### 2. Change Detection / HTML Monitoring (Priority: Medium)

**What's Missing:**
No way to detect when HTML structure changes

**Current Approach:**
- Parsers break when HTML changes
- Discover changes when parsers fail
- Reactive rather than proactive

**Potential Improvement:**
```python
# Monitor HTML structure
def monitor_html_structure(html, expected_structure):
    actual = analyze_structure(html)
    differences = compare_structures(expected, actual)

    if differences:
        log_warning(f"HTML structure changed: {differences}")

# Store expected structures
CREATURE_HTML_STRUCTURE = {
    'stat_block_sections': 3,  # Stats, Defense, Offense
    'required_tags': ['span', 'a', 'b'],
    'required_attributes': ['game-obj', 'aonid']
}
```

**Benefits:**
- Proactive detection of HTML changes
- Early warning before parsers break
- Understanding of what changed

**Assessment:**
- **Would be helpful** for maintenance
- Not critical for current operation
- **Recommendation:** Add when parsers stabilize

---

#### 3. Format Documentation (Priority: High)

**What's Missing:**
No explicit documentation of expected HTML formats

**Questions Not Answered:**
- What HTML structure does each parser expect?
- What variations are handled?
- What are examples of valid input?

**Current Approach:**
- Format expectations implicit in code
- Must read parser code to understand
- No examples without looking at actual HTML

**Potential Improvement:**

Create format documentation:
```python
# pfsrd2/formats.py
CREATURE_ATTACK_FORMAT = """
Expected HTML format for creature attacks:

<div class="stat-block">
  <b>Melee</b>
  <span class="action">Single Action</span>
  longsword +16
  <a href="...">+12/+8</a>
  (magical, versatile P),
  <b>Damage</b> 2d8+10 slashing
</div>

Regex patterns:
  with_traits: ^(.*) ([+-]\\d*) \\[(.*)\\] \\((.*)\\), (.*)$
  without_traits: ^(.*) ([+-]\\d*) \\[(.*)\\], (.*)$

Examples:
  - longsword +16 [+12/+8] (magical, versatile P), Damage 2d8+10
  - claw +18 [+14/+10], Damage 3d6+9 slashing
  - bite +15 [+10/+5] (agile), Damage 2d6+8 piercing plus Grab
"""
```

**Benefits:**
- Documents expectations explicitly
- Helps developers understand parsers
- Serves as specification for HTML
- Examples for testing

**Assessment:**
- **High value** for maintenance
- Relatively easy to add
- **Recommendation:** Document formats for each parser

---

#### 4. Data Quality Metrics (Priority: Medium)

**What's Missing:**
No measurement of extraction completeness

**Questions Not Answered:**
- How many creatures have all fields extracted?
- Which fields are still opaque text?
- What's the progress toward structured extraction goals?

**Current Approach:**
- No quantitative measurement
- Can't track improvement over time
- Don't know which areas need work

**Potential Improvement:**

```python
# After parsing, collect metrics
def collect_metrics(parsed_data):
    metrics = {
        'total_entities': len(parsed_data),
        'fields_extracted': count_extracted_fields(parsed_data),
        'fields_remaining_text': count_text_fields(parsed_data),
        'extraction_completeness': calculate_completeness(parsed_data)
    }

    # Track over time
    store_metrics(metrics, timestamp=now())

    # Report
    print(f"Extraction completeness: {metrics['extraction_completeness']}%")
    print(f"Entities with structured addons: {metrics['entities_with_addons']}")

# Example output
"""
Creature Parsing Metrics:
  Total creatures: 1,234
  Fully structured: 856 (69%)
  Partial structure: 312 (25%)
  Mostly text: 66 (5%)

  Field extraction:
    - Auras structured: 234/234 (100%)
    - Frequency extracted: 456/678 (67%)
    - Trigger extracted: 389/678 (57%)
    - Effect as text: 523/678 (77%)
"""
```

**Benefits:**
- Tracks progress toward structured extraction
- Identifies areas needing work
- Motivates improvement
- Shows value of changes

**Assessment:**
- **Medium value** for understanding progress
- Relatively easy to add
- **Recommendation:** Add basic metrics collection

---

### What Works Really Well

#### 1. Error Log Reprocessing Pattern

**The Pattern:**
```bash
# Run parser, some files fail
./pf2_run_creatures.sh
# Errors logged to: errors.pf2.monsters.log

# Fix parser code, reprocess only failures
mv errors.pf2.monsters.log errors.pf2.monsters
./pf2_run_creatures.sh  # Only processes files in errors.pf2.monsters
```

**Assessment:** ⭐ **Brilliant and elegant**

**Why It Works:**
- Simple implementation (just check for file existence)
- Enables fast iteration (only reprocess failures)
- Works perfectly with fail-fast approach
- No complex infrastructure needed
- Shell-script friendly

**This is exactly the right solution for this problem.**

---

#### 2. Progressive Enhancement Model

**The Approach:**
1. Start with basic structure (name, type, text)
2. Add pass to extract traits from text
3. Add pass to extract action types
4. Add pass to extract addons (Frequency, Trigger)
5. Continue extracting mechanics iteratively

**Assessment:** ⭐ **Perfect match for the mission**

**Why It Works:**
- Aligns with stated goal: "get there over time through iteration"
- Enables incremental improvement
- One-off cases can remain as text
- No need to handle everything at once
- Each improvement adds value

**Example:**
```json
// Iteration 1: Basic structure
{
  "name": "Grab",
  "text": "[one-action] Frequency once per day; The creature can Grab..."
}

// Iteration 2: Action type extracted
{
  "name": "Grab",
  "action_type": "one_action",
  "text": "Frequency once per day; The creature can Grab..."
}

// Iteration 3: Addons extracted
{
  "name": "Grab",
  "action_type": "one_action",
  "frequency": "once per day",
  "text": "The creature can Grab..."
}
```

**This architecture enables exactly this workflow.**

---

#### 3. Database Enrichment Pattern

**The Implementation:**
```python
# Traits appear in hundreds of creatures
# Database provides single source of truth
trait_db_pass(struct)

# Handles edition linking automatically
# Legacy "alignment" → Remastered "spirit"
```

**Assessment:** ⭐ **Well-designed for the problem**

**Why It Works:**
- Solves real problem (trait consistency)
- Enables edition handling (legacy/remaster)
- Reduces redundancy
- Centralized updates benefit all entities
- Fast lookups (indexed queries)

**Real Impact:**
- "Fire" trait appears in 300+ creatures
- Database ensures all use identical definition
- Update trait once, all creatures benefit
- Edition links handled automatically

---

#### 4. Documentation Quality

**What We Created:**
- `architecture.md` - Comprehensive pattern guide
- `adding-new-parser.md` - Step-by-step guide
- `claude.md` - Mission and principles
- `architecture-critique.md` - This document

**Assessment:** ⭐ **Excellent foundation**

**Why It Matters:**
- Makes architecture understandable
- Enables new developers to contribute
- Documents patterns and rationale
- Provides decision context
- Facilitates maintenance

**This will significantly help long-term maintainability.**

---

#### 5. Git-Based Schema Versioning

**The Strategy:**
- Breaking schema changes trigger a new branch in pfsrd2-data
- Branch preserves last data at previous schema version
- Consumers pin to specific schema version branches, not main
- Additive changes (non-breaking) stay on main

**Assessment:** ⭐ **Elegant and practical**

**Why It Works:**

**Stability for Consumers:**
```bash
# Consumers pin to stable schema version
git clone -b schema-v1.0 https://github.com/user/pfsrd2-data.git
# No surprise breaking changes
```

**Freedom to Evolve:**
- Main branch is active development
- Breaking changes are OK (just branch first)
- Additive changes don't require branching
- Clear distinction: breaking vs non-breaking

**Git-Native Versioning:**
- No separate version management needed
- Branches ARE the version mechanism
- Easy to see diffs between versions
- Multiple versions coexist naturally

**Consumer Contract is Clear:**
- ❌ Don't use main in production (active development)
- ✅ Pin to schema-vX.Y branch (stable)
- ✅ Upgrade deliberately by switching branches
- ✅ Test before upgrading

**Example:**

**Breaking change requires new branch:**
```bash
# Before breaking change
cd pfsrd2-data
git checkout -b schema-v1.0  # Preserve current version
git push origin schema-v1.0

# Now make breaking changes on main
git checkout main
# Update parser for new schema
```

**Non-breaking change (add field) - no branch:**
```json
// Just add to existing structure
{
  "name": "Goblin",
  "level": -1,
  "rarity": "common"  // New field - old consumers ignore it
}
```

**Benefits:**
- Stability without stagnation
- Multiple versions coexist
- No forced upgrades
- Git provides all version infrastructure
- Clear semantic contract (breaking vs additive)

**This is sophisticated version management with minimal infrastructure.**

---

### Improvement Priorities

#### 🔴 Priority 1: High-Impact, Should Do Soon

**1. Create Common Extraction Primitives**
```python
# universal/extractors.py
def extract_labeled_fields(html, labels, optional=False)
def split_maintain_semantic_units(text, delimiter)
def extract_traits(html)
def extract_action_type(html)
```

**Why:** Reduces duplication, ensures consistency

**Effort:** Medium (1-2 weeks)

**Impact:** 🔴 High - Makes parsers clearer and more maintainable

**Validation approach:**
1. Create helper using data-driven testing (run on full dataset)
2. Add unit tests for helper (fast iteration)
3. Use helper in multiple parsers with confidence

---

**2. Add Defensive Parsing Helpers**
```python
def get_section_by_name(sections, name, required=True)
def get_section_by_pattern(sections, predicate)
def peek_next_section(sections, expected)
```

**Why:** Reduces brittleness to structure changes

**Effort:** Low (few days)

**Impact:** 🟡 Medium - Makes parsers more resilient

---

#### 🟡 Priority 2: Medium-Impact, Good to Have

**3. Add Unit Tests for Extraction Helpers**

Once extraction helpers exist (Priority 1), add unit tests:
```python
# tests/test_extractors.py
def test_extract_labeled_fields()
def test_split_maintain_parens()
def test_extract_traits()
```

**Why:** Fast iteration when refactoring helpers, documents edge cases

**Effort:** Low (after helpers exist)

**Impact:** 🟡 Medium - Complements data-driven testing

**Note:** Don't unit test full parsers - data-driven testing already validates those effectively.

---

**4. Document Expected Formats**

Create format documentation for each parser:
- Expected HTML structure
- Regex patterns with explanations
- Examples of valid input

**Effort:** Medium (1 week)

**Impact:** 🟡 Medium - Improves maintainability

---

**5. Add Debug State Dumping**

Add `--debug` or `--dump-on-error` flag to parsers:
```python
parse_creature(html, options)  # Dumps state on error if --debug enabled
```

**Why:** Improves debugging workflow, especially for agent-based development

**Effort:** Low-Medium (few days)

**Impact:** 🟡 Medium - Particularly valuable for agent-based work

---

**6. Improve Regex Patterns**

- Use named capture groups
- Document patterns with examples
- Better error messages

**Effort:** Low-Medium

**Impact:** 🟡 Medium - Easier debugging

---

#### 🟢 Priority 3: Nice-to-Have

**7. Add Change Detection**

Monitor HTML structure for changes

**Effort:** Medium

**Impact:** 🟢 Low - Helpful but not critical

---

**8. Add Data Quality Metrics**

Track extraction completeness over time

**Effort:** Medium

**Impact:** 🟢 Low - Nice for visibility

---

**9. Parser Visualization**

Show what passes extracted what fields

**Effort:** High

**Impact:** 🟢 Low - Useful for debugging

---

## Overall Verdict

### Architecture Grade: **B+ (Good, with room for improvement)**

### Strengths Summary

✅ **Excellent Fits:**
- Pass-based pipeline for progressive extraction
- Fail-fast philosophy for data quality
- Strict HTML validation catches source errors
- Schema-driven development for mission
- Error log reprocessing pattern
- Progressive enhancement model
- Data-driven regression testing
- Git-based schema versioning (stability + evolution)

### Weaknesses Summary

🔴 **Critical Gaps:**
- Too much code duplication without abstraction

🟡 **Moderate Issues:**
- Fragile stateful parsing (pop pattern) - brittle but recoverable
- Regex brittleness and poor documentation
- Limited state dumping for debugging (especially for agent-based work)
- No unit tests for reusable helpers (when they exist)

### Strengths in Testing

✅ **Data-driven regression testing is sophisticated:**
- Uses actual dataset as comprehensive test suite
- Git diff provides validation
- Progressive validation (simple → 100 → all)
- No test maintenance burden

### Suitability for Problem Space

**Development/Data Curation Tool:** ✅ **Excellent fit**
- Correct trade-offs for batch processing
- Fail-fast appropriate for curation
- Error reprocessing enables workflow
- Data-driven testing validates effectively

**Production API:** ❌ **Would need significant changes**
- Fail-fast approach not suitable for live traffic
- Would need error recovery and partial results
- Performance not optimized

**Long-Term Maintenance:** 🟡 **Good but could be better**
- Solid foundation
- Documentation helps significantly
- Data-driven testing provides validation
- Would benefit from extraction abstractions
- Unit tests would complement helpers

### Key Insights

1. **Trade-offs are appropriate for the problem space**
   - Fail-fast is correct for data curation
   - Strictness enforces data quality
   - Data-driven testing provides comprehensive validation
   - Simplicity aids understanding

2. **Strict validation is a feature, not a bug**
   - HTML coupling is inherent to parsing HTML
   - Brittleness catches AoN bugs immediately
   - Wrong data is worse than no data
   - Graceful degradation would hide errors

3. **Architecture enables the mission**
   - Progressive enhancement works as intended
   - Schema-driven approach exposes mechanics
   - Iterative improvement is supported

4. **Git-native infrastructure is elegant**
   - pfsrd2-web branches for HTML curation (upstream + modified)
   - pfsrd2-data branches for schema versioning
   - No separate version management needed
   - Stability for consumers, freedom to evolve

5. **Biggest wins would come from:**
   - Common extraction primitives (reduces duplication)
   - Defensive parsing helpers (reduces fragility)
   - Unit tests for helpers once they exist (fast iteration)

6. **Data-driven testing is underrated**
   - Sophisticated approach using actual dataset as test suite
   - Git diff provides validation
   - Progressive validation enables fast iteration
   - Better than fixture-based tests for full parsers

7. **Documentation significantly helps**
   - Architecture guide documents patterns
   - Adding-parser guide enables contribution
   - Critique provides improvement roadmap

### Final Assessment

The architecture has a **solid foundation** and makes the **right trade-offs** for its problem space. The main gap is **excessive code duplication** - the primary opportunity for improvement without major architectural changes.

The **data-driven regression testing** approach is sophisticated and appropriate. Unit tests would complement this by enabling fast iteration on extraction helpers, but are not needed for full parser validation.

The parser accomplishes its mission of progressive extraction of structured mechanics, and the documentation we've created will significantly aid maintenance and evolution.

**Recommendation:** Focus on Priority 1 improvements (extraction primitives and defensive helpers) to reduce duplication and fragility. Add unit tests for helpers as they're created to enable fast iteration during refactoring.
