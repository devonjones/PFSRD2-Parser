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
