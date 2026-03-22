"""Regex-based extraction of structured mechanics from ability text.

Conservative patterns — better to miss an extraction than get it wrong.
Each extractor returns a structured object or None.
"""

import json
import re


# --- Damage type mapping ---

# Single-word damage types that appear in "XdY <type> damage" patterns
DAMAGE_TYPES = {
    "acid", "astral", "bleed", "bludgeoning", "cold", "electricity",
    "elemental", "energy", "evil", "fire", "force", "good", "holy",
    "lawful", "chaotic", "mental", "negative", "nonlethal", "physical",
    "piercing", "poison", "positive", "precision", "slashing", "sonic",
    "spirit", "split", "unholy", "vitality", "void",
}

# Multi-word damage types (check these before single-word)
MULTI_DAMAGE_TYPES = [
    "bludgeoning, piercing, or slashing",
    "acid, cold, electricity, fire, or sonic",
    "acid, cold, electricity, or fire",
    "acid, cold, or fire",
    "bludgeoning or positive",
    "piercing or slashing",
    "positive or negative",
    "void or vitality",
    "cold or fire",
]


# --- Save DC extraction ---

_SAVE_DC_PATTERNS = [
    # "DC 30 basic Reflex save" / "DC 30 basic Reflex"
    re.compile(
        r"DC\s+(\d+)\s+(basic\s+)?(Fortitude|Reflex|Will)(?:\s+save)?",
        re.IGNORECASE,
    ),
    # "Fortitude DC 30" / "a DC 28 Fortitude save"
    re.compile(
        r"(Fortitude|Reflex|Will)\s+DC\s+(\d+)",
        re.IGNORECASE,
    ),
    # "DC 5 flat check"
    re.compile(
        r"DC\s+(\d+)\s+flat\s+check",
        re.IGNORECASE,
    ),
    # Bare "DC 30" (no save type)
    re.compile(
        r"DC\s+(\d+)\b(?!\s*(?:Fortitude|Reflex|Will|basic|flat))",
        re.IGNORECASE,
    ),
]

_SAVE_TYPE_MAP = {
    "fortitude": "Fort",
    "reflex": "Ref",
    "will": "Will",
}

# Matches parenthetical modifier immediately after a DC/save pattern
_PAREN_MODIFIER = re.compile(r"\s*\(([^)]+)\)")


def _extract_trailing_modifier(text, match_end):
    """Check for a parenthetical modifier right after a regex match.

    Returns (modifier_list, full_text_including_modifier) or ([], match_text).
    """
    remaining = text[match_end:]
    m = _PAREN_MODIFIER.match(remaining)
    if m:
        mod_text = m.group(1).strip()
        modifier = {
            "type": "stat_block_section",
            "subtype": "modifier",
            "name": mod_text,
        }
        return [modifier], text[match_end - len(text):match_end] + m.group(0)
    return [], None


def _build_save_dc(match_text, dc_val, save_type=None, is_basic=False):
    """Build a save_dc object from extracted components."""
    result = {
        "type": "stat_block_section",
        "subtype": "save_dc",
        "text": match_text,
        "dc": dc_val,
    }
    if save_type:
        result["save_type"] = save_type
    if is_basic:
        result["basic"] = True
    return result


def extract_save_dc(text):
    """Extract all save DCs from ability text. Returns a list of save_dc objects."""
    if not text or "DC" not in text:
        return []

    results = []
    seen_dcs = set()  # track (dc, save_type) to avoid duplicates

    # Pass 1: DC <num> [basic] <save_type> — most specific
    for m in _SAVE_DC_PATTERNS[0].finditer(text):
        dc_val = int(m.group(1))
        is_basic = m.group(2) is not None
        save_type = _SAVE_TYPE_MAP[m.group(3).lower()]
        key = (dc_val, save_type)
        if key not in seen_dcs:
            seen_dcs.add(key)
            result = _build_save_dc(m.group(0), dc_val, save_type, is_basic)
            modifiers, _ = _extract_trailing_modifier(text, m.end())
            if modifiers:
                result["modifiers"] = modifiers
            results.append(result)

    # Pass 2: <save_type> DC <num>
    for m in _SAVE_DC_PATTERNS[1].finditer(text):
        save_type = _SAVE_TYPE_MAP[m.group(1).lower()]
        dc_val = int(m.group(2))
        key = (dc_val, save_type)
        if key not in seen_dcs:
            seen_dcs.add(key)
            result = _build_save_dc(m.group(0), dc_val, save_type)
            modifiers, _ = _extract_trailing_modifier(text, m.end())
            if modifiers:
                result["modifiers"] = modifiers
            results.append(result)

    # Pass 3: DC <num> flat check
    for m in _SAVE_DC_PATTERNS[2].finditer(text):
        dc_val = int(m.group(1))
        key = (dc_val, "Flat Check")
        if key not in seen_dcs:
            seen_dcs.add(key)
            result = _build_save_dc(m.group(0), dc_val, "Flat Check")
            modifiers, _ = _extract_trailing_modifier(text, m.end())
            if modifiers:
                result["modifiers"] = modifiers
            results.append(result)

    # Pass 4: bare DC <num> — only if this DC wasn't already captured
    for m in _SAVE_DC_PATTERNS[3].finditer(text):
        dc_val = int(m.group(1))
        if not any(dc_val == dc for dc, _ in seen_dcs):
            seen_dcs.add((dc_val, None))
            result = _build_save_dc(m.group(0), dc_val)
            modifiers, _ = _extract_trailing_modifier(text, m.end())
            if modifiers:
                result["modifiers"] = modifiers
            results.append(result)

    return results


# --- Area extraction ---

_AREA_PATTERN = re.compile(
    r"(\d+)[- ](?:foot|mile)\s+(line|cone|burst|emanation|wall|cylinder|radius)",
    re.IGNORECASE,
)

_SHAPE_MAP = {
    "line": "line",
    "cone": "cone",
    "burst": "burst",
    "emanation": "emanation",
    "wall": "wall",
    "cylinder": "cylinder",
    "radius": "burst",  # PF2e "radius" is mechanically a burst
}


def extract_area(text):
    """Extract all areas from ability text. Returns a list of area objects."""
    if not text:
        return []
    results = []
    seen = set()
    for m in _AREA_PATTERN.finditer(text):
        size = int(m.group(1))
        shape = _SHAPE_MAP[m.group(2).lower()]
        unit = "miles" if "mile" in m.group(0).lower() else "feet"
        key = (size, shape, unit)
        if key not in seen:
            seen.add(key)
            results.append({
                "type": "stat_block_section",
                "subtype": "area",
                "text": m.group(0),
                "shape": shape,
                "size": size,
                "unit": unit,
            })
    return results


# --- Range extraction ---

_RANGE_PATTERN = re.compile(
    r"(?:within|range of)\s+(\d+)\s+(?:(feet|foot|miles?|mile))",
    re.IGNORECASE,
)


def extract_range(text):
    """Extract a range from ability text. Returns a range object or None."""
    if not text:
        return None
    m = _RANGE_PATTERN.search(text)
    if m:
        size = int(m.group(1))
        raw_unit = m.group(2).lower()
        unit = "miles" if raw_unit.startswith("mile") else "feet"
        return {
            "type": "stat_block_section",
            "subtype": "range",
            "text": m.group(0),
            "range": size,
            "unit": unit,
        }
    return None


# --- Damage extraction ---

_DICE = r"(\d+d\d+(?:\s*[+\-]\s*\d+)?)"
_TYPE = r"(\w+)"

_DAMAGE_PATTERNS = [
    # Pattern 1: "XdY[+/-Z] [persistent] <type> damage"
    re.compile(
        _DICE + r"\s+"
        r"(persistent\s+)?"
        r"(\w+(?:\s*,?\s*(?:or|and)\s+\w+)*)"
        r"\s+damage",
        re.IGNORECASE,
    ),
    # Pattern 2: "XdY <type> and/plus XdY <type> damage"
    # Captures the first part that would otherwise be missed
    re.compile(
        _DICE + r"\s+" + _TYPE
        + r"\s+(?:and|plus)\s+"
        + _DICE + r"\s+\w+\s+damage",
        re.IGNORECASE,
    ),
    # Pattern 3: "XdY damage" (untyped — no type word)
    re.compile(
        _DICE + r"\s+damage\b",
        re.IGNORECASE,
    ),
    # Pattern 4: "Damage XdY[+/-Z] <type>" (stat block format)
    re.compile(
        r"\bDamage\s+" + _DICE + r"\s+" + _TYPE,
        re.IGNORECASE,
    ),
    # Pattern 5: "extra/additional XdY <type> damage"
    re.compile(
        r"(?:extra|additional)\s+"
        + _DICE + r"\s+"
        r"(persistent\s+)?"
        + _TYPE
        + r"\s+damage",
        re.IGNORECASE,
    ),
    # Pattern 6: "XdY extra/additional <type> damage"
    re.compile(
        _DICE
        + r"\s+(?:extra|additional)\s+"
        r"(persistent\s+)?"
        + _TYPE
        + r"\s+damage",
        re.IGNORECASE,
    ),
]


def _resolve_damage_type(raw_type):
    """Resolve a raw damage type string to a canonical type, or None."""
    raw = raw_type.strip().lower()
    for multi in MULTI_DAMAGE_TYPES:
        if raw == multi:
            return multi
    if raw in DAMAGE_TYPES:
        return raw
    return None


def extract_damage(text):
    """Extract damage expressions from ability text.

    Returns a list of attack_damage objects, or empty list.
    """
    if not text or "damage" not in text.lower():
        return []

    damages = []
    seen = set()  # (formula, type, persistent) to dedup

    def _add(formula, damage_type=None, is_persistent=False):
        key = (formula, damage_type, is_persistent)
        if key in seen:
            return
        # Skip if this formula already captured with a type
        if damage_type is None and any(formula == k[0] for k in seen):
            return
        seen.add(key)
        dmg = {
            "type": "stat_block_section",
            "subtype": "attack_damage",
            "formula": formula,
        }
        if damage_type:
            dmg["damage_type"] = damage_type
        if is_persistent:
            dmg["persistent"] = True
        damages.append(dmg)

    # Pattern 1: "XdY [persistent] <type> damage"
    for m in _DAMAGE_PATTERNS[0].finditer(text):
        formula = m.group(1).replace(" ", "")
        is_persistent = m.group(2) is not None
        damage_type = _resolve_damage_type(m.group(3))
        if damage_type:
            _add(formula, damage_type, is_persistent)

    # Pattern 2: "XdY <type> and/plus XdY <type> damage"
    # Captures the FIRST part before "and/plus"
    for m in _DAMAGE_PATTERNS[1].finditer(text):
        formula = m.group(1).replace(" ", "")
        damage_type = _resolve_damage_type(m.group(2))
        if damage_type:
            _add(formula, damage_type)

    # Pattern 3: "XdY damage" (untyped)
    for m in _DAMAGE_PATTERNS[2].finditer(text):
        formula = m.group(1).replace(" ", "")
        _add(formula)

    # Pattern 4: "Damage XdY <type>" (stat block format)
    for m in _DAMAGE_PATTERNS[3].finditer(text):
        formula = m.group(1).replace(" ", "")
        damage_type = _resolve_damage_type(m.group(2))
        if damage_type:
            _add(formula, damage_type)

    # Pattern 5: "extra/additional XdY [persistent] <type> damage"
    for m in _DAMAGE_PATTERNS[4].finditer(text):
        formula = m.group(1).replace(" ", "")
        is_persistent = m.group(2) is not None
        damage_type = _resolve_damage_type(m.group(3))
        if damage_type:
            _add(formula, damage_type, is_persistent)

    # Pattern 6: "XdY extra/additional [persistent] <type> damage"
    for m in _DAMAGE_PATTERNS[5].finditer(text):
        formula = m.group(1).replace(" ", "")
        is_persistent = m.group(2) is not None
        damage_type = _resolve_damage_type(m.group(3))
        if damage_type:
            _add(formula, damage_type, is_persistent)

    return damages


# --- Frequency extraction ---

_TIME_UNITS = r"(?:rounds?|minutes?|hours?|days?|turns?|months?|weeks?|years?)"

_FREQUENCY_PATTERNS = [
    # "can't/cannot <verb> <anything> again for X rounds/minutes"
    # Handles: "can't use X again for", "can't Surge again for",
    # "can't be used again for", "can't make a X again for"
    # Also handles "1d4+1 rounds" dice expressions with modifiers
    re.compile(
        r"(?:can[\u2019']t|cannot) (?:be )?\w+ .{0,60}?again for (\d+d?\d*(?:\s*[+\-]\s*\d+)?\s+" + _TIME_UNITS + r")",
        re.IGNORECASE,
    ),
    # "can't be reactivated for X" — different verb pattern
    re.compile(
        r"(?:can[\u2019']t|cannot) be \w+ for (\d+d?\d*(?:\s*[+\-]\s*\d+)?\s+" + _TIME_UNITS + r")",
        re.IGNORECASE,
    ),
    # "once per day" / "once per round" / "once per month" / etc.
    re.compile(
        r"(once per " + _TIME_UNITS + r")",
        re.IGNORECASE,
    ),
    # "X times per day/round" (numeric or spelled out)
    re.compile(
        r"(\d+ times per " + _TIME_UNITS + r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"((?:two|three|four|five|six|seven|eight|nine|ten)"
        r" times per " + _TIME_UNITS + r")",
        re.IGNORECASE,
    ),
]


def extract_frequency(text):
    """Extract a frequency/cooldown from ability text. Returns a string or None."""
    if not text:
        return None
    for pattern in _FREQUENCY_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


# --- Keyword detection ---

_KEYWORD_DETECTORS = {
    "dc": re.compile(r"\bDC\b"),
    "damage": re.compile(r"\bdamage\b", re.IGNORECASE),
    "area": re.compile(r"\d+[- ]?(?:foot|mile)\b", re.IGNORECASE),
    "frequency": re.compile(
        r"\b(?:again for|once per|per day|per round|per minute|per hour)\b",
        re.IGNORECASE,
    ),
}


def detect_keywords(text):
    """Detect which mechanical keywords are present in text.

    Returns a dict of {keyword: count} for keywords found,
    after subtracting known false alarm matches.
    """
    if not text:
        return {}
    found = {}
    for name, pattern in _KEYWORD_DETECTORS.items():
        raw_count = len(pattern.findall(text))
        if raw_count > 0:
            false_alarm_count = _count_false_alarms(name, text)
            effective = raw_count - false_alarm_count
            if effective > 0:
                found[name] = effective
    return found


# --- False alarm filtering ---

# Patterns that contain keywords but aren't extractable mechanics.
# Each entry is (keyword, compiled_regex). If the regex matches, the
# keyword is considered a false alarm and suppressed from flagging.
_FALSE_ALARM_PATTERNS = {
    "damage": [
        # Modifiers to damage, not actual damage dice
        re.compile(r"(?:bonus|penalty) to (?:attack and )?damage", re.I),
        re.compile(r"attack and damage (?:bonus|penalt|modifier|roll)", re.I),
        re.compile(r"damage (?:bonus|penalt|modifier|roll)", re.I),
        # Resistance/immunity to damage
        re.compile(r"resistance \d+ to .{0,30}damage", re.I),
        re.compile(r"resistance to .{0,20}damage", re.I),
        re.compile(r"immune to .{0,20}damage", re.I),
        # Hardness reducing damage
        re.compile(r"reduces any damage it takes", re.I),
        re.compile(r"hardness reduces .{0,20}damage", re.I),
        # Conditional/trigger references
        re.compile(r"(?:deals?|takes?) damage from", re.I),
        re.compile(r"if .{0,30}deals? damage", re.I),
        re.compile(r"damage type .{0,20}strikes? deal", re.I),
        re.compile(r"change .{0,20}damage type", re.I),
        re.compile(r"doesn.t change .{0,40}damage", re.I),
        re.compile(r"(?:being )?damaged by", re.I),
        # Negation
        re.compile(r"deals? no damage", re.I),
        re.compile(r"don.t deal .{0,20}damage", re.I),
        # "damage is increased to" — modifier on existing damage, not new dice
        re.compile(r"damage is increased to", re.I),
        # "damage equal to" — computed, not dice
        re.compile(r"damage equal to", re.I),
        # "when ... deals damage" — trigger condition
        re.compile(r"when .{0,40}deals? damage", re.I),
        # "harmed by X (XdY..." — elemental weakness format
        re.compile(r"harmed by .{0,30}\(", re.I),
        # "healed by X (area XdY..." — elemental healing format
        re.compile(r"healed by .{0,30}\(", re.I),
        # "combine their damage" — multi-strike combine instructions
        re.compile(r"combine .{0,20}damage", re.I),
        # "takes damage from the fall" / "takes damage from" — trigger
        re.compile(r"takes? damage from", re.I),
        # "takes half damage" / "halves damage" / "half damage"
        re.compile(r"(?:takes? half|halves?|half) damage", re.I),
        # "fast healing" / "regains HP equal to ... damage"
        re.compile(r"fast healing", re.I),
        re.compile(r"regains? .{0,30}equal to .{0,30}damage", re.I),
        # "damage avoidance" — familiar ability
        re.compile(r"damage avoidance", re.I),
        # "no damage" negation
        re.compile(r"\bno damage\b", re.I),
        # "same amount of ... damage" — pass-through
        re.compile(r"same (?:amount|type) of .{0,20}damage", re.I),
        # "counts as ... damage" — type override
        re.compile(r"counts as .{0,20}damage", re.I),
        # "instead of ... damage" — replacement
        re.compile(r"instead of .{0,20}damage", re.I),
        # "for the purpose of ... damage" — resistances instruction
        re.compile(r"for the purpose of .{0,30}damage", re.I),
    ],
    "dc": [
        # Referencing another creature's DC, not a static number
        re.compile(r"(?:against|versus) .{0,30}(?:Fortitude|Reflex|Will) DC\b", re.I),
        re.compile(r"creature.s (?:Fortitude|Reflex|Will) DC", re.I),
        re.compile(r"target.s (?:Fortitude|Reflex|Will) DC", re.I),
        re.compile(r"victim.s (?:Fortitude|Reflex|Will) DC", re.I),
        re.compile(r"enemy.s (?:Fortitude|Reflex|Will) DC", re.I),
        # Skill DCs — creature's own skill used as DC
        re.compile(r"(?:Athletics|Intimidation|Deception|Stealth|Perception|Performance) DC\b", re.I),
        re.compile(r"(?:Sailing|Piloting|Legal) Lore DC\b", re.I),
        # "flat check to target" — not a save DC
        re.compile(r"flat check to target", re.I),
        # "reduce the DC of the flat check" — modifying a check, not a save
        re.compile(r"reduce the DC of the flat check", re.I),
        re.compile(r"DC of the flat check", re.I),
        # "DC of X" referencing a difficulty class of something else
        re.compile(r"DC of \d+.*reduced by", re.I),
        # "DC cumulatively decreases" — describing the first DC, not a second one
        re.compile(r"DC cumulatively decreases", re.I),
        # "counteract DC" — not a save DC
        re.compile(r"counteract DC", re.I),
        # Variable/referenced DCs
        re.compile(r"spell DC\b(?!\s+\d)", re.I),
        re.compile(r"(?:Will|Reflex|Fortitude) DC\b(?!\s+\d)", re.I),
        # "against the DC of the effect" — references another effect
        re.compile(r"against the DC of", re.I),
        # "at the same DC" — referencing another effect's DC
        re.compile(r"at the same DC", re.I),
        # "penalty/bonus to DC" — creature's own DC
        re.compile(r"penalty to .{0,20}DC\b", re.I),
        re.compile(r"bonus to .{0,20}DC\b", re.I),
        # "the DC is X rather than Y" — conditional override, not a save
        re.compile(r"the DC is \d+.{0,15}rather than", re.I),
        # "DC increases/decreases by" — modification, not a static DC
        re.compile(r"DC (?:increases|decreases|is increased|is reduced) by", re.I),
        # "standard DC for" — variable
        re.compile(r"standard DC for", re.I),
        # "Dominate DC" / "class DC" — creature's own DC reference
        re.compile(r"(?:Dominate|class) DC", re.I),
        # "Society DC" / "Performance DC" etc. — skill used as DC
        re.compile(r"(?:Society|Performance|Religion|Nature|Arcana|Occultism) DC", re.I),
    ],
    "area": [
        # Speed bonuses, not areas
        re.compile(r"[+-]\d+[- ]foot .{0,20}(?:bonus|penalty|circumstance|status) .{0,10}(?:to |Speed)", re.I),
        re.compile(r"(?:bonus|penalty|circumstance|status) .{0,10}(?:to |Speed).{0,10}\d+[- ]foot", re.I),
        re.compile(r"\d+[- ]foot[- ]circumstance", re.I),
        re.compile(r"\d+[- ]foot[- ]status", re.I),
        # Troop movement ("20-foot-by-20-foot area") — consumes 2 keyword matches
        # Handles hyphens, em-dashes, spaces, missing separators
        (re.compile(r"\d+[- ]foot[- \u2013]by[\u2013 –-]?\s*\d*[- ]?foot", re.I), 2),
        (re.compile(r"\d+[- ]by[- ]?\d+[- ]foot", re.I), 2),
        # Troop variant with space before second "foot": "20-foot-by–20- foot"
        re.compile(r"\d+[- ]foot[- ].{0,5}by", re.I),
        # Specific distance references, not areas
        re.compile(r"(?:pushed|pulled|moved) .{0,10}\d+[- ](?:foot|feet)", re.I),
        re.compile(r"\d+[- ]foot[- ]deep", re.I),
        # "up to X mile" — travel distance, not area
        re.compile(r"up to \d+ miles? away", re.I),
        # Speed values
        re.compile(r"(?:Speed|Speeds) (?:of )?\d+[- ](?:foot|feet)", re.I),
        re.compile(r"\d+[- ]foot (?:fly|swim|climb|burrow|land) Speed", re.I),
        # Reach, not area
        re.compile(r"\d+[- ]foot reach", re.I),
        # Auras — different mechanic from areas
        re.compile(r"\d+[- ]foot aura", re.I),
        # Dimensions, not area shapes
        re.compile(r"\d+[- ]foot[- ](?:tall|high|wide|long)\b", re.I),
        # Squares (specific location, not area shape)
        re.compile(r"\d+[- ]foot square", re.I),
        # "X-foot penalty" (speed penalty)
        re.compile(r"\d+[- ]foot penalty", re.I),
        # Range increment / tether length, not area
        re.compile(r"\d+[- ]foot range increment", re.I),
        re.compile(r"\d+[- ]foot length", re.I),
        # Diameter of non-area things (demiplanes, tunnels)
        re.compile(r"\d+[- ]foot[- ]diameter", re.I),
        # Specific spaces, not area shapes
        re.compile(r"\d+[- ]foot[- ]?(?:cube|space|square)\b", re.I),
        # "X-foot area" without a shape — ambiguous
        re.compile(r"\d+[- ]foot area\b", re.I),
        # Troop format variants (em-dash, "by" without "foot")
        re.compile(r"\d+[- ]by[- ]\d+[- ]foot", re.I),
    ],
    "frequency": [
        # "per round" in non-frequency contexts
        re.compile(r"(?:extra|additional) reactions? per round", re.I),
        re.compile(r"feet per round", re.I),
        re.compile(r"minutes? per day", re.I),
        re.compile(r"hit points? per (?:round|day|hour)", re.I),
        # Rates of production/consumption/destruction
        re.compile(r"gallons? (?:of water )?per (?:round|minute|hour|day)", re.I),
        re.compile(r"(?:cube|cubes) per (?:round|minute|hour|day)", re.I),
        re.compile(r"lemures per day", re.I),
        re.compile(r"damage per round", re.I),
        # "once per" non-time-unit contexts
        re.compile(r"once per (?:character|creature|target|use|Stride)", re.I),
        # Recovery rates
        re.compile(r"decreases by \d+ per (?:week|day|hour|round)", re.I),
        # "first time per round" — trigger limit, not ability frequency
        re.compile(r"first time per round", re.I),
        # "affected only once per" — target limit
        re.compile(r"(?:affected|benefit).{0,10}only once per", re.I),
        # "X per round" for action economy
        re.compile(r"reactions? per round", re.I),
        # Scaling: "for every X levels"
        re.compile(r"for every \d+", re.I),
    ],
}


def _count_false_alarms(keyword, text):
    """Count how many keyword matches are consumed by false alarm patterns.

    Each false alarm entry is either a regex (counts as 1 per match)
    or a (regex, weight) tuple where weight is the number of keyword
    matches each false alarm match accounts for.
    """
    entries = _FALSE_ALARM_PATTERNS.get(keyword, [])
    count = 0
    for entry in entries:
        if isinstance(entry, tuple):
            pattern, weight = entry
        else:
            pattern, weight = entry, 1
        count += len(pattern.findall(text)) * weight
    return count


# --- Top-level extraction ---

def extract_all(ability_json):
    """Run all extractors on an ability object.

    Returns (enriched_ability_or_None, missed_dict).

    enriched_ability is a new ability object with structured fields added,
    or None if no extractions were made.

    missed_dict maps keyword -> (detected_count, extracted_count) for
    keywords where detected > extracted. Empty dict means fully covered.
    """
    if isinstance(ability_json, str):
        ability_json = json.loads(ability_json)

    # Combine text fields to search
    text = ability_json.get("text", "")
    effect = ability_json.get("effect", "")
    combined = f"{text} {effect}".strip()

    if not combined:
        return None, {}

    detected = detect_keywords(combined)
    extracted_counts = {}

    # Only extract fields that don't already exist on the ability
    enriched = dict(ability_json)
    changed = False

    if "saving_throw" not in ability_json:
        saves = extract_save_dc(combined)
        if saves:
            enriched["saving_throw"] = saves
            changed = True
            extracted_counts["dc"] = len(saves)
    else:
        # Already has saving_throw — count existing as extracted
        st = ability_json["saving_throw"]
        extracted_counts["dc"] = len(st) if isinstance(st, list) else 1

    if "area" not in ability_json:
        areas = extract_area(combined)
        if areas:
            enriched["area"] = areas
            changed = True
            extracted_counts["area"] = extracted_counts.get("area", 0) + len(areas)
    else:
        existing_area = ability_json["area"]
        extracted_counts["area"] = len(existing_area) if isinstance(existing_area, list) else 1

    if "range" not in ability_json:
        rng = extract_range(combined)
        if rng:
            enriched["range"] = rng
            changed = True
            extracted_counts["area"] = extracted_counts.get("area", 0) + 1
    else:
        extracted_counts["area"] = extracted_counts.get("area", 0) + 1

    if "damage" not in ability_json:
        damages = extract_damage(combined)
        if damages:
            enriched["damage"] = damages
            changed = True
            extracted_counts["damage"] = len(damages)
    else:
        extracted_counts["damage"] = len(ability_json["damage"]) if isinstance(ability_json["damage"], list) else 1

    if not ability_json.get("frequency"):
        freq = extract_frequency(combined)
        if freq:
            enriched["frequency"] = freq
            changed = True
            extracted_counts["frequency"] = 1
    else:
        extracted_counts["frequency"] = 1

    # Compare detected counts vs extracted counts
    missed = {}
    for keyword, det_count in detected.items():
        ext_count = extracted_counts.get(keyword, 0)
        if ext_count < det_count:
            missed[keyword] = (det_count, ext_count)

    result = enriched if changed else None
    return result, missed
