# AoN HTML5 Common Error Patterns

A living reference for recurring HTML bugs in Archives of Nethys HTML5 pages
that cause parser failures. AoN updates frequently, and these same patterns
repeat in new files — use this doc to identify and fix them quickly.

## Confirmed Patterns (fixable in HTML)

### 1. Empty duplicate `<a>` tags
**Pattern**: `<a href="Traits.aspx?ID=X">\n</a>\n<a href="Traits.aspx?ID=X">\ntrait_name</a>`
**Fix**: Delete the empty `<a>...</a>` tag entirely, keeping only the second one with content.
**Variant**: Sometimes the empty `<a>` has a different aonid than the real one (e.g., N 3369: aonid 712 empty, aonid 647 real). Still delete the empty one.
**Detection regex**: `<a([^>]*)>\s*</a>\s*(?=<a)` (empty `<a>` followed by another `<a>`)
**Files fixed**: M 2767, M 2780, M 3348, N 3369, M 3898, M 4057

### 2. Focus Points inside `<b>` tag
**Pattern**: `<b>\nRanger Warden Spells 2 Focus Points,</b>`
**Expected**: `<b>\nRanger Warden Spells</b>\n 2 Focus Points,`
**Fix**: Move "N Focus Point(s)," from inside `<b>` to after `</b>`. The spell type name goes in bold, the focus point count goes outside as metadata.
**Detection regex**: `<b>\n([^<]+?) (\d+ Focus Points?,)</b>` → `<b>\n\1</b>\n \2`
**Files fixed**: 21 files (M: 3329,3330,3840,3842,3844,3857,4016,4315; N: 2379,3831,3832,3868,3877,3884,3889,3897,3976,3992,4038,4043,4046)

### 3. `<br>` before affliction stage headers
**Pattern**: `...(1 day);<br>\n <b>\nStage 2</b>\n ...`
**Expected**: `...(1 day); <b>\nStage 2</b>\n ...`
**Fix**: Remove `<br>` tag that appears immediately before `<b>Stage N</b>`, `<b>Saving Throw</b>`, `<b>Onset</b>`, or `<b>Maximum Duration</b>`.
**Detection regex**: `<br>\s*\n(\s*<b>\s*\n(?:Stage\s+\d+|Saving Throw|Onset|Maximum Duration))`
**Files fixed**: 13 files (M: 282,283,1876,1877,2604,2862-2864,3082,3926,4288,4289; N: 4261)

### 4. Misplaced trait closing parenthesis
**Pattern**: `(fire, occult Trigger The bul-gae takes damage) Effect ...`
**Expected**: `(fire, occult) <b>Trigger</b> The bul-gae takes damage; <b>Effect</b> ...`
**Fix**: Move `)` to right after the last trait `</a>`. Add `<b>` tags around Trigger/Effect keywords. Add `;` separator between Trigger and Effect clauses.
**Also watch for**: Broken `<a>` wrapping regular text (M 2780 had aura text wrapped in trait link)
**Files fixed**: M 2767, M 2780

### 5. "No Icon" broken `<img>` tags
**Pattern**: `<img alt="No Icon" title="No Icon" style="height:18px; padding:2px 10px 0px 2px" src="Images%5CIcons%5C/">`
**Context**: Appears inside `<h3 class="title">` for abilities, representing broken/missing action icon references.
**Fix**: Delete the entire `<img>` line. The parser doesn't need these non-functional icon placeholders.
**Detection**: `<img alt="No Icon"[^>]*>`
**Scope**: 167 monster files, 1 NPC file
**Files fixed**: All 168 files with pattern (bulk sed)

### 6. Double `<b>` tags
**Pattern**: `<b>\n<b>\nTrue Temptation</b>`
**Expected**: `<b>\nTrue Temptation</b>`
**Fix**: Remove the extra opening `<b>` tag.
**Files fixed**: N 3369

### 7. Trait text absorbed into link
**Pattern**: `<a href="Traits.aspx?ID=X">magical reach 20 feet</a>` (should be two traits or trait + text)
**Variants**:
- `necromancy Any living` (ability text merged with trait)
- `disease Saving Throw DC 22 Fortitude` (stat block text in trait link)
- `concentrate Cost 1 Mythic Point` (mythic ability text in trait link)
- `occult Trigger The skaveling...` (trigger text in trait link)
**Fix**: Split the link at the first trait boundary. Trait link should only contain the trait name; extra text goes outside.
**Files fixed**: M 3335, 3816, 4140, 4200, 4264, 4545; N 3629, 3832, 4037, 4038, 4240

### 8. Missing `<span class="hanging-indent">` wrapper for abilities
**Pattern**: Interaction abilities (before first `<hr>`) with `<b>Trigger</b>`, `<b>Effect</b>`, `<b>Frequency</b>` etc. get split into separate stat block keys.
**Fix**: Wrap the ability in `<span class="hanging-indent">...</span>`. Also required parser fix: `process_interaction_ability()` now consumes addon sections (Trigger, Effect, Frequency, etc.) from the stats list, matching how `process_defensive_ability()` and `parse_offensive_ability()` work.
**Parser change**: Added `sections` parameter to `process_interaction_ability()` with addon consumption loop.
**Files fixed**: N 3629 (Dwarf General - Opening Orders)

## `<span class="action">` in description text (114 creatures)

Action icon spans (`<span class="action">`) appearing in ability description/text
content instead of being at the start of a properly-structured ability. Causes
`_validate_acceptable_tags` failures because `span` is not in the markdown validset.

**114 total**: 27 pre-3000 (known pre-existing), 87 new (3000+)

### 9a. Troop multi-action abilities (33 files)
**Pattern**: Troop creatures have abilities where damage scales with action count.
The `<span class="action">` tags in Effect addon text and ability text fail markdown
validation because `span` is not in the default validset.
**Two sub-issues**:
1. ALL 33 troops need `CREATURE_SPANS_ALLOWED` entries — the markdown converter
   (`PFSRDConverter.convert_span()`) correctly converts spans to `[#]`/`[##]`/`[###]`
   but validation happens first and rejects `span` tags. Old troops (e.g. Skeleton Infantry
   ID 1300) were already in the allow list.
2. 5 abilities across 5 files were also missing `<b>Effect</b>` wrapper — the description
   text with damage-by-action goes into `text` field instead of `effect` field.
**Fix applied**:
- Added 44 troops to `CREATURE_SPANS_ALLOWED` in constants.py (403 total)
- Added `<b>\nEffect</b>\n` to 5 HTML files: M 3901 (Sword Bash), M 3911 (Draconic Onslaught),
  M 3920 (Dogpile), M 3942 (Hateful Daggers), M 3943 (Pack Hunt)
**Detection**: Troop abilities with `[one-action] to [three-actions]` header followed by
damage-by-action text containing additional `<span class="action">` tags.
**Files fixed (batch 1)**: M 3827, 3901, 3905, 3906, 3908, 3909, 3911, 3912, 3916-3920, 3922-3924,
3927-3929, 3931, 3933-3935, 3938, 3940, 3942-3946, 3952, 3996, 4334
**Files fixed (batch 2)**: M 3898 (Angelic Chorus), 3900 (Apprentice Magician Clique), 3903 (Archon Bastion), 3910 (Dezullon Thicket), 3913 (Druid Circle), 3921 (Halfling Lucky Draw), 3930 (Omox Slime Pool), 3932 (Protean Tumult), 3939 (Vanth Guardian Flock), 3941 (Vordine Legion), 3969 (Gale Frenzy)
**Sub-fix**: M 3969 also had Putrid Plague disease embedded inside the Form Up ability text — separated into its own `<span class="hanging-indent">` so the disease parses as a standalone affliction.

### 9b. Dragon/creature building-block text (~20+ files)
**Pattern**: Description text listing alternative abilities a GM can substitute.
These are sidebar-style content embedded in the creature's description, documenting
abilities with action costs:
```
<b>Cloud of Ashes</b> <span class="action">[one-action]</span> (primal) The dragon...
<b>Inflame Emotions</b> <span class="action">[two-actions]</span> (aura, fire...) The dragon...
```
**Tag set**: typically `{span, br, b}` or `{span, br, b, i}`
**Example files**: M 3834 (Skeletal Rat Swarm), M 3835 (Zombie Bear), M 3836 (Undead Murder), M 4345 (Young Cinder Dragon), M 4097-4109 (Archdragons), M 4294-4365 (various)
**Fix**: Added dragons + building-block creatures to `CREATURE_SPANS_ALLOWED` in constants.py. These are prose documenting abilities, not parseable ability definitions.
**Includes**: Dragons (55), undead customization (Skeletal Rat Swarm, Zombie Bear, Undead Murder, Ossuary Warden, Zombie Desecrator), clockwork (Spy, Soldier, Mage), lycanthropes (Batkin Guard, Werebat Warrior), variant creatures (Shade, Spawning Soulrider, Kandirvek), and others (Deathless Pirate, Skittering Slayer, Worm Prophet, Thousand Thieves).

### 9c. Mythic Power sub-abilities (~10 files)
**Pattern**: Mythic Power abilities use `<ul><li><i>` structure for sub-abilities:
```
<b>Mythic Power</b> 3 Mythic Points <ul>
<li><i>Mythic Skill</i> <span class="action">[free-action]</span> <b>Cost</b> 1 Mythic Point; ...</li>
<li><i>Remove a Condition</i> <span class="action">[one-action]</span> ...</li>
</ul>
```
**Tag set**: `{span, br, b, ul, li, i}`
**Example files**: M 3858, M 3902, M 3915, M 4105
**Fix**: Added creatures to `CREATURE_UL_ALLOWED` in constants.py (3 entries: Archer Regiment, First-Class Infantry, Vampire Servant). `markdown_valid_set()` adds `ul` and `li` to validset for these creatures.

### 10. Perception modifier after semicolon (15 files)
**Pattern**: Perception line has modifier placed AFTER the semicolon instead of before it:
```
Perception +33; (35 to Sense Motive) darkvision, scent (imprecise) 60 feet
```
**Expected**: `Perception +33 (35 to Sense Motive); darkvision, scent (imprecise) 60 feet`
**Why it fails**: `process_senses()` splits by `;`, then `startswith("(")` check merges the modifier + entire senses list back into perception value. `extract_modifiers()` then asserts modifiers must be at end only.
**Sub-patterns**:
- `(N to Sense Motive)` — most with `<a>` link, one plain text (10 files)
- `(N initiative)` — single-line (4 files)
**Fix**: Move `(modifier)` from after `;` to before `;`.
**Files fixed**: M 4110, 4119-4122, 4182-4185, 4212, 4330, 4366-4368, 4469

### 11. Affliction keywords missing `<b>` tags (15 files)
**Pattern**: Affliction fields like `Onset`, `Maximum Duration`, and later `Stage` entries appear as plain text instead of being wrapped in `<b>` tags:
```
DC 23 Fortitude; Onset 1 day; <b>Stage 1</b>...
```
**Expected**: `DC 23 Fortitude; <b>Onset</b> 1 day; <b>Stage 1</b>...`
**Sub-patterns**:
- Missing `<b>Onset</b>`: 6 files (1 day ×3, 1 hour ×2, 1d4 days ×1)
- Missing `<b>Maximum Duration</b>`: 2 files
- Missing `<b>Stage 5</b>`: 2+1 files (Stage 5 death)
- Missing `<b>Stage 2</b>`+ (later stages inline): 3 files
- Affliction prose text not ending with period: 1 file
**Fix**: Add `<b>...</b>` wrappers around the keyword. For prose text, add missing period.
**Files fixed**: M 3910, 3969, 4071, 4077, 4116, 4118, 4222, 4328, 4341, 4402, 4418, 4419, 4466, 4487, 4516

### 12. Singular "Spell" instead of "Spells" in spell headers (7 files)
**Pattern**: Focus/innate spell headers use singular form:
```
<b>Champion Focus Spell</b> DC 17, 1 Focus Point; <b>1st</b> lay on hands
```
**Expected**: `<b>Champion Focus Spells</b> DC 17, 1 Focus Point; <b>1st</b> lay on hands`
**Why it fails**: `_is_spell_section()` checks for `"Spells" in parts` — singular "Spell" doesn't match, so it's treated as an offensive ability.
**Variant**: One file (4338) had trailing comma: `Divine Domain Spells,`
**Variant**: Missing class prefix: `Druid Focus Spell` → `Druid Focus Spells` (added to schema)
**Fix**: Change singular to plural, remove trailing comma, add class prefix where needed.
**Schema additions**: `Druid Focus Spells`, `Domain Spells` (removed — use `Cleric` prefix in HTML instead)
**Files fixed**: M 3893, 4018-4021, 4338, 4590

### 13. Damage punctuation / extra text / missing damage type in attack damage (16 files)
**Pattern**: Attack damage strings contain trailing punctuation, commas where `plus` should be, reference text, or missing damage type:
- `2d6 cold.` — trailing period
- `piercing, plus mischief` — comma before "plus"
- `fire, xiuh coatl venom, and Grab` — commas instead of ` plus `
- `acid; see detritus` — reference text in damage
- `2d4+8 fist` — weapon name instead of damage type (should be `bludgeoning`)
- `3d8 bludgeonin` — truncated damage type (should be `bludgeoning`)
- `3d8+14 plus Grab` — missing damage type entirely before `plus` (infer from weapon: jaws=piercing, claw=slashing, javelin=piercing, bone=bludgeoning)
**Fix**: HTML corrections — remove trailing punctuation, change `, ` to ` plus `, remove reference text, fix/add damage types.
**Files fixed**: M 3772, 3993, 4159, 4160, 4232, 4299, 4305, 4460, 4488, 4494, 4536, 4550, 4611; also 3972, 3985

### 14. Missing comma in affliction DC (1 file)
**Pattern**: `DC 21 1 Focus Point` — missing comma between DC value and Focus Point count.
**Expected**: `DC 21, 1 Focus Point`
**Fix**: Add comma.
**Files fixed**: M 4338

### 15. Non-alphabetical damage type ordering (1 file)
**Pattern**: `bludgeoning, slashing, or piercing` — schema expects alphabetical: `bludgeoning, piercing, or slashing`.
**Fix**: Reorder in HTML to match schema.
**Files fixed**: M 4494

### 9d. Ability embedded in another ability's text (2 files)
**Pattern**: One ability's content is embedded inside another's `<span class="hanging-indent">`:
```
<span class="hanging-indent">
<b>Hyponatremia</b> (...) A living creature...
Tidal Wave <span class="action">[three-actions]</span> (arcane, manipulate, water);
<b>Frequency</b> once per 10 minutes; <b>Effect</b> The dragon...
</span>
<span class="hanging-indent">
<b>Tidal Wave</b> <span class="action">[three-actions]</span> ...  ← proper duplicate exists
</span>
```
**Fix**: HTML fix — close the first ability's span, start a new hanging-indent for the embedded ability.
**Example files**: M 4168 (Ancient Sea Dragon), M 4169 (Sea Archdragon)

### 9e. calledAction div blocks (5 files total, 1 in error set)
**Pattern**: `<div class="calledAction">` blocks with `<h3>` headers contain action spans:
```
<div class="calledAction"><h3 class="title">Insult Ordulf <span class="action">[two-actions]</span></h3>...
```
**Tag set**: `{div, h3, span, br, b, i, hr}`
**Example files**: M 3377 (Ordulf Bladecaller)
**Fix needed**: Extract calledAction divs as separate sections/sidebars before markdown validation.

## Spell Type Issues (needs human judgment)
HTML5 omits class prefix from spell type names. Parser requires full name.
**NOT auto-fixable** — requires knowing which class the creature uses.

**Pending decisions**:
- "Bloodline Spells" → "Sorcerer Bloodline Spells"?
- "Animal Order Spells" → "Druid Order Spells"?
- "Domain Spells" → "Cleric Domain Spells"?
- Other stripped spell types TBD

### 16. Troop spell blocks missing `<span class="hanging-indent">` wrapper (12 files)
**Pattern**: Troop creatures have spell lists (e.g., `<b>Divine Innate Spells</b>`) that appear as bare `<b>` tags between the Speed line and the first `<span class="hanging-indent">` ability. `parse_universal()` puts bare text into the parent section's text rather than creating a separate section. When `_handle_title_before_speed()` merges everything up to the Speed section into `sb["text"]`, the spells end up in the offense tuple list. The `process_stat_block()` assertion at line 965 fails because offense should only contain Speed.
**Root cause**: In working creatures, spells come after `</span>` of a hanging-indent attack, creating a section boundary. In failing troops, spells follow `Speed<br>` with no section boundary.
**Fix**: Wrap spell blocks in `<span class="hanging-indent">...</span>` so `parse_universal()` creates them as separate sections.
**Detection regex**: `troop movement.*?<br>\s*\n\s*<b>\s*\n\s*(?:Divine|Arcane|Occult|Primal)\s+(?:Innate|Prepared|Spontaneous)\s+Spells`
**Files fixed**: M 1275, 3898, 3900, 3903, 3913, 3921, 3925, 3926, 3930, 3932, 3939, 3941

### 17. Missing source page number (1 file)
**Pattern**: Source link text has no `pg. N` suffix: `<i>Foolish Housekeeping and Other Articles</i>`
**Expected**: `<i>Foolish Housekeeping and Other Articles pg. 1</i>`
**Fix**: Add `pg. N` to source link text.
**Files fixed**: M 3681

### 18. Image `<a>` tag parsed as source link (1 file)
**Pattern**: Thumbnail image links (`<a href="Images%5CMonsters%5C...webp">`) appear before traits in the stat block and get parsed as a source entry with empty name.
**Fix**: Delete the `<a><img></a>` blocks for thumbnail images.
**Files fixed**: M 4103

### Schema additions
- **damage_type enum**: `shepherd's touch` (M 3149 Morrigna)
- **game-obj enum**: `WeatherHazards` (M 4170-4173 Sky Dragons)

### 19. Aura DC not in parseable position (9 files)
**Pattern**: The `handle_aura()` function expects DC info in a comma-separated header after the range: `) 30 feet, DC 25 Fortitude. Description text...`. When the DC is only in the description text (not the header), `universal_handle_save_dc()` receives the full sentence and fails on unexpected words.
**Working format**: `) 30 feet, DC 25 Fortitude. When a creature ends its turn...` or `) DC 27 Fortitude, 20 feet. Description...`
**Sub-patterns**:
- **DC buried in description** (5 files): `) 90 feet, A creature who enters... DC 21 Fortitude save.` — DC is in prose, not header. Fix: Add `DC ## SaveType` after range: `) 90 feet, DC 21 Fortitude. A creature who...`
  - Files fixed: M 3811, 4202, 4203, 4204, 4205
- **Wrong separator after DC** (1 file): `) 30 feet, DC 16; Undead are immune...` — semicolon instead of period after DC value. Fix: Change `;` to `.`
  - Files fixed: M 3875
- **Damage before DC with `<a>` link around "basic"** (3 files): `) 5 feet, 5d6 fire damage (DC 40 <a>basic</a> Reflex)` — damage first, DC in parens, "basic" is a link tag. Fix: Restructure to `DC ## basic Reflex, Xd6 fire damage` matching the working format from M 702.
  - Files fixed: M 4098, 4346, 4347
- **Death burst with no range** (1 file): `) When the bloodsiphon dies... DC 21 Reflex save.` — no range, DC only in prose. Fix: Add `DC ## SaveType` at start: `) DC 21 Reflex. When the bloodsiphon dies...`
  - Files fixed: M 4033
**Reference**: Working examples — M 702 (Hound of Tindalos): `DC 25 basic Fortitude, 4d6 slashing damage`; M 297 (Medusa): `30 feet, DC 25 Fortitude`; M 3744 (gambling devil): `30 feet, DC 21 Will`

### 20. Mythic Power formatting variants (4 files)
**Pattern**: `parse_mythic_ability()` (creatures.py:2247) expects the section text to have exactly 2 children: a NavigableString `"3 Mythic Points"` and a `<ul>` element containing `<li>` entries for each mythic activation. Several HTML variants break this.
**Working format** (M 4264): `<b>Mythic Power 3 Mythic Points</b>` — text inside `<b>` makes it part of the ability name, sub-abilities are separate hanging-indent spans (not parsed as mythic).
**Working format** (M 4273 after fix): `<b>Mythic Power</b> 3 Mythic Points <ul><li><b>Recharge</b>...</li></ul>` — plain text + `<ul>` = 2 children, parsed as mythic ability.
**Sub-patterns**:
- **Prose instead of format** (1 file): `Gavergash has 3 Mythic Points.` — parser tries `int("Gavergash")`. Fix: Change to `3 Mythic Points`.
  - Files fixed: M 4273
- **"Mythic Points" in `<a>` link, no `<ul>`** (1 file): `3 <a>Mythic Points</a>` then span closes — gives 2 children but first is `'3 '` which fails `find("Mythic Points")`. Sub-abilities are separate hanging-indent spans. Fix: Move "3 Mythic Points" inside `<b>` tag to match M 4264 pattern.
  - Files fixed: M 4265
- **"Mythic Points" in `<a>` link, with `<ul>`** (1 file): `3 <a>Mythic Points</a> <ul>...` — gives 3 children instead of 2. Fix: Remove `<a>` link, use plain text `3 Mythic Points`.
  - Files fixed: M 4275
- **`<br>&bull;` bullets instead of `<ul><li>`** (1 file): Sub-abilities use `<br>&bull;<i>Name</i>` format instead of `<ul><li><i>Name</i>...</li></ul>`. Also missing `<b>` around addon keywords like "Cost". Fix: Replace with `<ul><li>` structure, add `<b>` wrappers.
  - Files fixed: M 3983

### 21. Spell list missing semicolon and `<b>` on level (1 file)
**Pattern**: Spell list header `DC 24 7th interplanar teleport` — missing semicolon between DC and spell level, and spell level not wrapped in `<b>` tags.
**Expected**: `DC 24; <b>7th</b> interplanar teleport`
**Fix**: Add semicolon after DC, wrap spell level in `<b>` tags.
**Files fixed**: M 3962

### 22. Spell list as reference to later section (1 file)
**Pattern**: `Arcane Prepared Spells DC 30, attack +22; see Risen Runelord Spells below.` — stat block spell list has no actual spell entries, just a cross-reference. The real spells are in a building-block `<h2>` section organized by sin type.
**Fix**: Rename stat block entry to `Arcane Prepared Spell List` (drops "Spells" so parser treats it as ability). Add `DC 30, attack +22;` and rename each sin spell list (`Envy Spells` → `Arcane Prepared Spells (Envy)` etc.) with proper spell format.
**Files fixed**: M 4275

## Patterns Still Being Investigated

### Attack parsing
- `b9000` as attack bonus (not a number) - M 3682
- `null` as trait name - M 3778
- `blackfrost ice shard` attack with curse link in damage - N 4260

### Custom AoN tags
- `<actions>`, `<treasure>`, `<treasure.categories>`, `<tableshtml>` — non-standard HTML tags in creature pages
- Fix by removing from HTML

### 23. Sidebar `<img>` icons in building-block sections
**Pattern**: `<h3 class="title"><img alt="Sidebar - Additional Lore" ...> Section Name</h3>`
**Fix**: Remove the `<img>` tag — it's a decorative icon that's not needed for parsing.
**Files**: M 2604, 3937, 3811, 981 (4103 fixed in prior session)

### 24. Corrupted/garbled HTML tags in ability text
**Pattern**: `<h2 class="title">387%%&gt;emanation` — broken template tag embedded in ability text.
**Fix**: Remove the corrupted tag and its closing pair.
**Files**: M 4531 (Rusalka)

### 25. `<h2>` downgraded from `<h1>` in HTML5 update — building-block sections
**Pattern**: Building-block sections (creature variants, templates) that were `<h1>` in old XHTML but got changed to `<h2>` in the HTML5 update. Parser treats `<h1>` as top-level section separator; `<h2>` gets included in ability text.
**Fix**: Change `<h2 class="title">` back to `<h1 class="title">` for building-block section headers.
**Files**: M 414 (Will-o'-Wisp Variants), 3811 (Failed Prophet Abilities)

### 26. `<action.types>` broken template tags
**Pattern**: `<action.types>` appears where a single-action span should be. Usually 1 per Melee Strike line. Closing `</action.types>` tags accumulate at end of section.
**Fix**: Replace each `<action.types>` with `<span class="action" title="Single Action" role="img" aria-label="Single Action">[one-action]</span>`. Remove all `</action.types>` closing tags.
**Files**: M 3937 (Sinswarm — 7 instances, one per sinspawn variant)

### 27. `<div class="calledAction">` PC activity blocks
**Pattern**: `<div class="calledAction"><h3 class="title"><a href="...">Activity Name</a></h3><b>Source</b>...<hr>...</div>`
**Fix**: Replace the div structure with inline text. Remove `<div>`, inner `<h3>`, Source/`<hr>`, and closing `</div>`. Keep activity name as plain text (NOT bold, to avoid addon parsing). Works when calledAction is inside an `<h3>` creature ability section. Other creatures with calledAction in top-level description text already work fine.
**Files**: M 3377 (Ordulf Bladecaller). Compare with working M 987, 2371, 2358, 1730.

### 28. Duplicate stat block copy — legacy multi-source creatures
**Pattern**: Creature file contains two complete copies of the stat block (one per source variant). In old XHTML, parser handled this with different structural wrappers. In HTML5, the second copy follows a sidebar with no `<h1>` separator, causing its traits/stats to be included in the sidebar's text content.
**Fix**: Remove the entire second copy (duplicate stat block + sidebar) if it's the same source. Keep the first copy.
**Files**: M 981 (Viskithrel — 182 lines of duplicate removed)

### 29. Monster family listing table in building-block sections
**Pattern**: `<h2 class="title">All Monsters in "Family"</h2><table class="inner">...</table>` — family listing with table appears between description and stat block.
**Fix**: Remove the entire family listing block (`<h2>` through `</table>`). The family is already known from other parsing.
**Files**: M 3811 (Failed Prophet)

### 30. Building-block with tables in ability descriptions
**Pattern**: Creature template descriptions include `<table class="inner">` for data (e.g., "Value Stolen by Level"). These are legitimate content tables, not navigation.
**Fix**: Add creature to `CREATURE_TABLE_ALLOWED` in constants.py (adds table/tr/td to validset). Also add to `CREATURE_SPANS_ALLOWED` if action spans are present.
**Parser change**: Added `CREATURE_TABLE_ALLOWED` list and `markdown_valid_set` handler in creatures.py.
**Files**: M 3811 (Failed Prophet)

### 31. Missing `<b>` wrapper on interaction ability name after stats
**Pattern**: After the last stat (Cha) value and `<br>`, the interaction ability text begins as plain text without a `<b>` tag around the ability name. The parser expects `<b>AbilityName</b> description...` format — without `<b>`, the ability text gets concatenated onto the Cha stat value via `add_remnants()`, causing `process_attr` to fail with `ValueError: invalid literal for int()`.
**Fix**: Wrap the ability name in `<b>` tags. E.g., `Deep Breath The elasmosaurus...` → `<b>Deep Breath</b> The elasmosaurus...`
**Variant**: When the ability name is wrapped as `<a><b>Name</b></a>` (link outside bold), swap to `<b><a>Name</a></b>` so the parser sees `<b>` at the sibling level.
**Files**: M 3823 (Firefly's Remembrance), 3863 (Sloth), 3907 (Wind-Up — a/b swap), 3936 (Smoke Vision), 4377 (Deep Breath), 4436 (Coven)

### 32. Troop spell block missing `<span class="hanging-indent">` wrapper (pattern 16 continuation)
**Pattern**: Same as pattern 16 — spell lists appear as bare `<b>` tags after `Speed<br>` in troops, ending up in the offense tuple data. Previously fixed 12 files; this is a continuation.
**Fix**: Wrap spell block in `<span class="hanging-indent">...</span>` and add to `CREATURE_SPANS_ALLOWED`.
**Files**: M 3936 (Scamp Inferno)

### 33. Missing `)` after trait list before `<b>Trigger</b>` in defensive abilities
**Pattern**: Defensive ability with traits in parentheses has the closing `)` misplaced — it appears after the Trigger text instead of after the traits. E.g., `(divine, mental, unholy <b>Trigger</b> ...attack)` instead of `(divine, mental, unholy) <b>Trigger</b> ...attack;`.
**Fix**: Move `)` from after Trigger text to after last trait. Replace `)` at end of Trigger text with `;`.
**Files**: M 4101 (Diabolic Archdragon — Hell's Sting), 4397 (Water Wisp — Accord Essence)

### 34. Plain text trait name instead of `<a>` link in parenthesized trait list
**Pattern**: Trait name appears as plain text instead of `<a href="Traits.aspx?ID=NNN">` link inside a trait parenthetical. E.g., `(aura, divine)` where "divine" is plain text.
**Fix**: Wrap the plain text trait in `<a style="text-decoration:underline" href="Traits.aspx?ID=NNN">trait</a>`. Use sqlite DB at `~/.pfsrd2/pfsrd2.db` to look up trait IDs.
**Files**: M 4131-4134 (Young/Adult/Ancient/Archdragon Delight Dragon — Play Scape aura, "divine" → aonid 579)

### 35. Empty trait text in `<a><u></u></a>` link
**Pattern**: Trait link has correct `<a href="Traits.aspx?ID=NNN">` wrapper but the `<u>` inside is empty. Parser extracts empty string as trait name, `fetch_trait_by_name(curs, "")` returns None.
**Fix**: Add the correct trait name inside `<u>` tags. Find the correct name by checking other creatures with the same ability or looking up the trait in the DB. Note: AoN aonids may not match the parser DB (e.g., aonid 165 maps to "mindless" in DB but AoN uses it for "water").
**Files**: M 4168 (Ancient Sea Dragon — Hyponatremia, added "water"), M 4500 (Giant Opossum — jaws attack, added "deadly d10"), M 4595 (Trollhound — Bloodfire Fever, added "disease")

### 36. "cold iron" trait text (pre-remaster name)
**Pattern**: Attack trait text says "cold iron" which was the pre-remaster name. The remastered name is "naari". `fetch_trait_by_name(curs, "cold iron")` returns None because no such trait exists in the DB.
**Fix**: Change trait text from "cold iron" to "naari". Also fix aonid to 27 (naari) if it points elsewhere (e.g., aonid 555 = phantom).
**Files**: M 4328 (Ferrugon — 3 occurrences, aonid 555→27), M 4505 (Ozthoom — 2 occurrences, aonid 27 already correct)

### 37. Missing attack bonus and/or MAP in Melee/Ranged line
**Pattern**: Attack line missing the `+bonus` and/or `[+MAP1/+MAP2]` values. Variants include: bonus completely absent, bonus merged into trait text (e.g., `agile +12` instead of `+12 (agile)`), trait text as "null", or attack line truncated by premature `</span>`.
**Fix**: Add correct `+bonus` (check live AoN or reference creatures). Add MAP link if needed: `[<a style="text-decoration:underline" href="Rules.aspx?ID=322"><u>+MAP1/+MAP2</u></a>]`
**Files**: M 3682 (Rt5rrmn — added +22 to both attacks, added MAP to g7ujik), M 3778 (Grizzer — added +23 to claw, "null"→"agile"), M 4090 (Attic Whisperer — moved +12 out of trait text), M 4214 (Amelekana — added MAP and Effect to lob amoeba)

### 38. Missing weapon name before attack bonus
**Pattern**: Attack line has `+bonus [MAP] (traits)` but no weapon name before the bonus. Parser regex expects `name +bonus ...`.
**Fix**: Add weapon name from reference creatures (Young/Adult variants of same dragon, etc.).
**Files**: M 4140 (Ancient Executor Dragon — added jaws, claw, tail from Adult version)

### 39. Inline `<b>Melee</b>`/`<b>Damage</b>` in ability description text
**Pattern**: Ability description text contains `<b>Melee</b>` or `<b>Damage</b>` as inline references (e.g., describing a minion's attack). Parser interprets these as new attack sections.
**Fix**: Change `<b>` to `<strong>` for inline references (parser doesn't treat `<strong>` as section headers).
**Files**: M 4214 (Amelekana — Symbiotic Amoeba ability, `<b>Melee</b>` → `<strong>Melee</strong>`), M 3904 (Boggard Dreadknot — `<b>Effects</b>` → `<strong>Effects</strong>`), M 4247 (Oaksteward Enforcer — inline `<b>Melee</b>`+`<b>Damage</b>` in Effect text), M 4252 (Apothecary's Cabinet — `<b>1</b>`/`<b>2</b>`/`<b>3</b>`/`<b>4</b>` numbered items), M 4268 (Pyroclastic Mukradi — `<b>Smoke Maw</b>` inline), M 4509 (Suli Dune Dancer — `<b>Air</b>`/`<b>Earth</b>`/etc. element names)

### 40. Mythic Power section missing `<ul>` structure
**Pattern**: Mythic Power text is plain `"N Mythic Points."` in its own `<span>` with activations in separate `<span class="hanging-indent">` blocks. Parser expects `"N Mythic Points <ul><li>activation1</li>...</ul>"` inside a single section.
**Fix**: Restructure: move bullet activations into `<ul><li>` tags within the Mythic Power span. Keep non-mythic abilities (Pull Apart, Thrash, Trample) as separate spans.
**Files**: M 4268 (Pyroclastic Mukradi — Recharge and Remove a Condition moved into `<ul><li>` inside Mythic Power)

### 41. Speed line: semicolon instead of comma separating movement types
**Pattern**: Speed line uses `;` between movement types (e.g., `20 feet; ice climb 20 feet`). Parser treats text after `;` as modifiers, but "ice climb" is a movement type. Also: conditional speed text like `15 feet while waterlogged` after `;` instead of comma-separated `15 feet (while waterlogged)`.
**Fix**: Change `;` to `,`. For conditional speed text, wrap the condition in parentheses (e.g., `15 feet (while waterlogged)`).
**Files**: M 4216, 4217, 4434 (ice climb: `;` → `,`), M 4281 (Berberoka: `;` → `,` + parenthesized modifier)

### 42. Missing "feet" in speed movement type
**Pattern**: Speed value missing the word "feet" (e.g., `burrow 30` instead of `burrow 30 feet`). The `break_out_movement` regex expects `(\d+) feet$`.
**Fix**: Add " feet" after the number.
**Files**: M 3321 (Vibrant Pup Swarm — `burrow 30` → `burrow 30 feet`), M 4349 (Adult Coral Dragon — `swim 100` → `swim 100 feet`)

### 43. Speed data displaced into wrong section
**Pattern**: Speed text appears in a `<span class="hanging-indent">` before the `<hr>` (defense section) instead of after `<b>Speed</b>` in the offense section. The `<b>Speed</b>` line is empty.
**Fix**: Move speed text from the misplaced span to after `<b>Speed</b>`.
**Files**: M 3895 (Conductor — speed data in defense section, moved to offense)

### 44. Sense modifier text outside parentheses
**Pattern**: Special sense has modifier text after the closing paren instead of inside it: `tremorsense (imprecise) within their entire bound home`. Parser expects sense text to end with `)` when parentheses present.
**Fix**: Move the extra text inside the parentheses, separated by semicolon: `(imprecise; within their entire bound home)`.
**Files**: M 4441 (Domovoi — "bound home"), M 4442 (Dvorovoi — "bound yard"), M 4443 (Ovinnik — "bound granary or storeroom")

### 45. Aura ability missing range
**Pattern**: An ability with the `aura` trait has no range in its text. The `_test_aura()` function checks for "feet", "miles", "DC", or "damage" in the first sentence — if none found, it raises an assertion. The ability has a range on the live site but it was omitted in the HTML.
**Fix**: Add the range (e.g., `100 feet.`) after the closing `)` of the traits and before the descriptive text.
**Files**: M 4437 (Hellcat — Fiendish Telepathy missing `100 feet`)

### 46. Comma in aura range number
**Pattern**: Aura range written as `1,000 feet` — the comma causes `split_maintain_parens(test, ",")` to break the number into `1` and `000 feet`. The `1` fragment doesn't match any handler (no "feet", "DC", or "damage").
**Fix**: Remove comma from the number: `1000 feet`.
**Files**: M 4537 (Ximtal — Despoiler aura `1,000` → `1000`)

### 47. Affliction saving throw not bolded
**Pattern**: Affliction text has `Saving Throw DC XX Fortitude` as plain text instead of `<b>Saving Throw</b> DC XX Fortitude`. Parser expects `<b>` wrapper to identify it as an addon section header. Without it, the text ends up in the affliction's `text` field which then fails the "must end with `.` or `)`" assertion.
**Fix**: Wrap `Saving Throw` in `<b>` tags. Also change the preceding separator from `;` to `.` so the context text ends properly.
**Files**: M 4537 (Ximtal — Sensory Fever disease)

### 48. Sense modifier/range order swapped
**Pattern**: Special sense has the modifier between the number and "feet": `motion sense 60 (precise) feet`. The `_handle_special_sense_range` regex `r"(.*) (\d*) (.*)"` captures `(precise) feet` as the unit, which fails the `unit in ["feet", "miles"]` assertion.
**Fix**: Move the modifier before the number: `motion sense (precise) 60 feet`.
**Files**: M 4219 (Creeping Evil — `motion sense 60 (precise) feet` → `motion sense (precise) 60 feet`)

### 49. Spurious page reference in sense text
**Pattern**: Special sense has `(page 363)` appended after the range: `wavesense (imprecise) 60 feet (page 363)`. The regex captures the page number as a second range, and `")"` fails the unit assertion.
**Fix**: Remove the `(page NNN)` reference.
**Files**: M 4350 (Ancient Coral Dragon — removed `(page 363)` from wavesense)

### 50. Multiple legacy version links
**Pattern**: "There are Legacy versions here and here." contains two `<a>` links. `handle_alternate_link` asserts `len(links) == 1` — it only supports one alternate link.
**Fix**: Keep only the first link, change "versions" to "version" singular.
**Files**: M 3016 (Shadow Giant — kept aonid 681), M 3067 (Imp — kept aonid 109)

### 51. Semicolon inside parentheses breaks split
**Pattern**: Text inside parentheses contains `;` — `split_stat_block_line` splits on `;` first, separating the `(` from its matching `)`. Then `rebuilt_split_modifiers` tries to reunite them by popping from the parts list but runs out of elements.
**Fix (language)**: Change `;` to `,` inside parens: `(typically Common, can't speak any language)`.
**Fix (resistance)**: Add missing `)` to close the parenthetical before `;`: `(except force, ghost touch, spirit, or vitality); double resistance vs. non-magical`.
**Files**: M 3745 (Masque Mannequin — language `;` → `,`), M 4618 (War Wraith — added missing `)` in resistance)

### 52. Building-block sidebar variant abilities with `<b>` tags
**Pattern**: Sidebar sections (h3) describing variant/optional abilities contain `<b>VariantName</b>` for each sub-ability. Parser treats these as stat block addon headers. Same root cause as pattern 39.
**Fix**: Change `<b>` to `<strong>` for inline variant ability names in sidebar text.
**Files**: M 1729 (Kallas Devil — 7 variant abilities: Blameless, Infectious Water, Underwater Views, Cold Currents, Suffer the Children, Freezing Touch, Waterfall Torrent), M 1843 (Bone Croupier — 3 roll results: 7 or 11, 2/3/12, Any Other Roll), M 3914 (Dwarf Longshot Squad — Bullet Smog)

### 53. Aura missing range (flavor text first sentence)
**Pattern**: Aura ability text starts with flavor sentence before any range info. `_test_aura` checks the first sentence (split on `.`) for "feet"/"miles"/"DC"/"damage" — none found in flavor text.
**Fix**: Add range before flavor text (e.g., `500 feet.` extracted from the description).
**Files**: M 3809 (Beiran Frosthunt — Unseasonable Cold: added `500 feet` from severe cold zone range)

### 54. Spell block missing `<span class="hanging-indent">` wrapper
**Pattern**: Spell block (e.g., "Primal Innate Spells") appears as loose text after `<br>` instead of inside a `<span class="hanging-indent">`. Parser doesn't recognize it as a spell block, leaving it as unconsumed offense data.
**Fix**: Wrap the entire spell block in `<span class="hanging-indent">...</span>`.
**Files**: M 3809 (Beiran Frosthunt — Primal Innate Spells)

### 55. Unclosed building-block h3 sections nesting into stat block
**Pattern**: Building-block variant ability sections (`<h3>`) had no closing `</h3>` tags, causing lxml to nest them. The stat block `<h1>` ended up buried 3 levels deep inside nested h3 tags, making `parse_universal` unable to find the stat block.
**Fix**: Added `</h3>` closing tags after each building-block h3 section's content, and removed the extra closing `</h3>` tags that were at the end of the file.
**Related**: Pattern 25 (building-block h1→h2), but this is a different issue with unclosed tags.
**Files**: M 2794 (Noppera-Bo Impersonator)

### 56. Trailing comma in damage type text
**Pattern**: Damage text had `slashing, plus rt5rrmn yyumn` — the comma before "plus" caused the parser to extract `slashing,` as the damage type (with trailing comma), failing schema validation.
**Fix**: Removed the comma: `slashing plus rt5rrmn yyumn`.
**Files**: M 3682 (Rt5rrmn)

### 57. Affliction stages missing bold wrappers
**Pattern**: Only Stage 1 had `<b>Stage 1</b>` wrapper. Stages 2 and 3 were plain text `Stage 2` and `Stage 3` without `<b>` tags, causing `parse_affliction` to fail with "Stage should not be in the text of Affliction" assertion.
**Fix**: Wrapped with `<b>Stage 2</b>` and `<b>Stage 3</b>`.
**Related**: Pattern from ID_3925 (Leukodaemon Plague Stage 6) in prior session.
**Files**: M 3820 (Vorvorak)

### 58. Defense stat order — Hardness must come before Thresholds
**Pattern**: HTML had `HP; Thresholds; Hardness` order, but the parser's `process_stat_block` expects `HP; Hardness; Thresholds`. When the parser checked for Hardness first and found Thresholds instead, subsequent Immunities/Weaknesses checks also failed since Hardness was still in the queue.
**Fix**: Swapped to `HP; Hardness; Thresholds` order in the HTML.
**Files**: M 3899 (Animated Army)

### 59. Building-block variant spell lists as sidebar
**Pattern**: "Risen Runelord Spells" h3 section contained a description paragraph followed by 7 variant spell lists (one per sin: Envy, Gluttony, Greed, Lust, Pride, Sloth, Wrath). The parser's `get_attacks` treated this as a spell section (name ends with "Spells") and tried to split on `<br>` then extract level info from `<b>` tags. The description text had no `<b>` tags, and the sin names were not spell levels.
**Fix**: (a) Added sidebar img `<img alt="Sidebar - Advice and Rules" ...>` inside the h3 title to make `is_attack()` return False, treating it as a sidebar. (b) Changed `<b>Sin Spells</b>` to `<strong>Sin Spells</strong>` for all 7 sin types to prevent them from interfering with any bold-tag-based parsing.
**Files**: M 4271 (Risen Runelord)

### 60. Duplicated text outside closing `</a>` tag in senses
**Pattern**: Sense link text repeated as plain text after the `</a>`: `darkvision</a>\ndarkvision<br>`. Parser concatenates both into `"darkvisiondarkvision"`.
**Fix**: Remove the duplicate plain text, keeping only the text inside the `<a>` tag.
**Files**: M 2336 (Kellid Graveknight), M 2334 (Rezatha), M 3332 (Divine Warden of Haagenti), M 3331 (Statue of Alaznist)

### 61. Missing `<b>Languages</b>` wrapper and `<br>` separator after senses
**Pattern**: Languages line follows the last sense with no `<br>` break and no `<b>` wrapper: `low-light vision</a>\nLanguages Abyssal, Aklo, Common, Sylvan<br>`. Parser treats everything as senses — gets merged sense name and language names as senses.
**Fix**: Add `<br>\n<b>\nLanguages</b>\n` before the language list.
**Files**: M 2354 (Immense Mandragora), M 2352 (Kargstaad)

### 62. Trailing semicolon with no senses in Perception line
**Pattern**: Perception line ends with `; <br>` — semicolon followed by nothing. Parser splits on `;` and gets an empty sense entry.
**Fix**: Remove the trailing `; ` before `<br>`.
**Files**: N 2391 (Ekundayo Level 6)

### 63. Comma inside `<a>` tag for sense name
**Pattern**: Sense link has comma inside: `greater darkvision,</a>`. After text extraction, the comma is part of the sense name rather than being a list separator.
**Fix**: Move comma outside the `</a>` tag: `greater darkvision</a>,`.
**Files**: M 4310 (Vanyver)

### 64. Perception modifier with spurious "plus" prefix
**Pattern**: Perception line reads `+24; plus vigilance` — the "plus" prefix causes parser to create a sense named "plus vigilance" instead of modifier "vigilance".
**Fix**: Remove "plus " prefix: `+24; vigilance`.
**Files**: N 3634 (Elven Court Guard)

### 65. Missing comma between immunity names
**Pattern**: Immunity list has `disease paralyzed` with no comma separator. Parser treats it as a single immunity name `"disease paralyzed"`.
**Fix**: Add comma: `disease, paralyzed`.
**Files**: M 2344 (Elder Elemental Tsunami)

### 66. Ability text leaked into immunity line
**Pattern**: `disease</a> Impossible Stature (aura, divine, ...)` — ability name and traits follow directly after last immunity with no separator. Parser merges them into `"disease Impossible Stature"`.
**Fix**: Add `; <b>Impossible Stature</b>` to separate immunities from the ability.
**Files**: M 4581 (Elysian Titan)

### 67. Oxford comma in immunity list
**Pattern**: `precision, and unconscious` — English "and" before last item. Parser splits on `,` and gets `"and unconscious"`.
**Fix**: Remove oxford comma: `precision, unconscious`.
**Files**: M 2336 (Kellid Graveknight), M 2337 (Korog)

### 68. Italic `<i>` tags on immunity names instead of links
**Pattern**: `<i>acid</i>` and `<i>sleep</i>` used instead of `<a>` links or plain text. Parser converts to markdown `*acid*`.
**Fix**: Strip `<i>` tags, leaving plain text.
**Files**: M 1546 (Belmazog)

### 69. Missing `<b>` wrapper on Weaknesses header
**Pattern**: `; Weaknesses <a ...>fire</a>` — "Weaknesses" is plain text instead of `<b>Weaknesses</b>`. Parser doesn't recognize section boundary, treats `"Weaknesses fire"` as an immunity.
**Fix**: Add `<b>` wrapper: `; <b>\nWeaknesses</b>\n`.
**Files**: M 3734 (Phytohydra)

### 70. Trailing period on immunity name
**Pattern**: `unconscious.<br>` — period at end of immunity list. Parser includes it in name: `"unconscious."`.
**Fix**: Remove trailing period.
**Files**: M 3331 (Statue of Alaznist)

### 71. Typo in immunity name
**Pattern**: `unconcious` misspelled (missing 's').
**Fix**: Correct to `unconscious`.
**Files**: M 1641 (Gray Death)

### 72. Stray character after closing `</a>` tag in immunity
**Pattern**: `olfactory</a>e` — extra `e` after closing tag merges into name as `"olfactorye"`.
**Fix**: Remove stray character.
**Files**: M 2120 (War Sauropelta)

### 73. Trailing comma creating empty immunity
**Pattern**: `disease</a>,<br>` — comma before `<br>` with nothing after. Parser splits on `,` and creates an empty `""` immunity entry.
**Fix**: Remove trailing comma.
**Files**: M 1715 (Taon)
