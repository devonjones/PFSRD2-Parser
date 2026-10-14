# shared-utils-reviewer
model: sonnet
verification: evidence-query — greps `universal/utils.py` and `universal/universal.py` for the helper that matches the inline code and quotes both the inline snippet and the helper signature.
**Checks:** Inline reimplementation of `universal/` helpers (text splitting, tag cleanup, link extraction, object building, tree walking) and generic parser-local helpers that belong in `universal/`.
**Spawn when:** diff adds or changes a `def` or BeautifulSoup, regex or string-splitting code in a `.py` file under `pfsrd2/` (not `tests/`); skip otherwise.
**Contents:** Question any code that reimplements these patterns · Text/String Processing · BeautifulSoup Helpers · Link Extraction · Structured Object Building · Structure Walking · Tag Classification · Patterns to FLAG: Reimplementing a `universal/` function inline; Near-duplicates that diverge in subtle ways; Parser-local utility files that should live in `universal/` · Do NOT flag · Review approach · Severity · Scope

Review code for duplication of shared utilities. The pfsrd2-parser project has a `universal/` package containing common helpers used across all parsers; reimplementing them inline creates drift and bypasses battle-tested edge-case handling.

Before reviewing, READ these files to understand what's available:

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

**Patterns to FLAG:**

1. **Reimplementing a `universal/` function inline** — flag with the specific function that should be used instead. Suggest the one-line replacement.

2. **Near-duplicates that diverge in subtle ways** — e.g., a custom paren-aware split that handles `[` `]` instead of `(` `)`. Often the right fix is to extend the universal function with a parameter, not to keep a parallel implementation.

3. **Parser-local utility files that should live in `universal/`** — if a helper in `pfsrd2/<type>.py` is generic (no type-specific logic, uses only BeautifulSoup/stdlib) and could plausibly help another parser, recommend moving it.

**Do NOT flag:**

- Type-specific extraction logic that happens to look superficially similar to a universal helper.
- One-off uses where the universal helper would require awkward parameter passing.

**Review approach:**

1. Read the utility files first to understand exact signatures and behavior.
2. For each new/modified function, ask: "Is this reimplementing something in universal?"
3. If yes, flag it with the specific function that should be used instead.
4. Consider edge cases — sometimes a custom version is justified, but demand justification.

**Severity:** P3 by default. May be deferred with a beads ticket.

**Scope:** `.py` files under `pfsrd2/` that the diff adds or changes; not `tests/`, not `universal/` itself. Leave the question of how to split a long function to `complexity-reviewer`; you only flag reimplementation of an existing helper or a generic helper that belongs in `universal/`.

---
