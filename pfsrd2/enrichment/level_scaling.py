"""Read level-scaled damage from ability text.

Template and family abilities state damage that grows with the creature's
level ("increases to 2d6 if the cryptid is 9th level or higher", "1d6 per
level", "plus an additional 1d6 for every 6 levels"). The damage extractor
keeps only the base dice, so this reader marks how they scale.

Two shapes:
- steps: explicit thresholds, each printed: [{"min_level": 9, "formula": "2d6"}]
- increment: one printed rate. Damage at level L is
  (base if additive else nothing) + k * increment, where k counts the
  thresholds reached: start_level, start_level + per_levels, ...
  start_level is printed when the text gives one ("at 4th level and every 3
  levels thereafter"); a bare "for every 3 levels" starts at 3.
"""

import re

from pfsrd2.enrichment.change_extractor import name_filter

_ORD = r"(\d+)(?:st|nd|rd|th)"
_DICE = r"(\d+d\d+(?:\s*[+-]\s*\d+)?)"
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COUNT = r"(\d+|" + "|".join(_WORDS) + r")"

# "2d6 if the cryptid is 9th level or higher" / "is at least 8th level" /
# "2d4 at 5th level"
_STEP = re.compile(_DICE + r"\s+(?:if [^,;.]*?(?:at least\s+)?|at\s+)" + _ORD + r" level", re.I)
_STEP_INTRO = re.compile(r"increas\w*\s+to\s+" + _DICE + r"[^.]*", re.I)

# "1d6 at 3rd level and every odd level thereafter" /
# "1d6 at 4th level and every 3 levels thereafter"
_THEREAFTER = re.compile(
    r"increases by " + _DICE + r" at " + _ORD + r" level and every (odd|" + _COUNT[1:-1] + r") "
    r"levels? thereafter",
    re.I,
)
# "1d8 negative damage for every 3 levels" / "1d6 damage per level" /
# "plus an additional 1d6 for every 6 levels" / "+ 1d6 per 2 levels"
_RATE = re.compile(
    r"(plus (?:an )?(?:additional )?|increases by |\+ )?"
    + _DICE
    + r"(?:\s+[\w ]{0,25}?damage)?\s+(?:per (?:"
    + _COUNT
    + r" )?levels?(?! of the (?:\w+ )?(?:spell|ability|ritual)\b)|for every "
    + _COUNT
    + r" levels)",
    re.I,
)
# Shockwave: "(minimum 2d6 damage)"
_MINIMUM = re.compile(r"\(minimum " + _DICE + r"[\w ]*\)", re.I)
# Spitting Zombie: "1d12 acid damage per 3 levels of the zombie (or 1d6 acid
# damage below level 3)"
_BELOW = re.compile(r"\(or " + _DICE + r"[\w ]*? below level (\d+)\)", re.I)


def _norm(dice):
    return re.sub(r"\s+", "", dice)


def _num(word):
    if word is None:
        return 1
    return int(word) if word.isdigit() else _WORDS[word.lower()]


def _parse(formula):
    m = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", formula)
    assert m, f"not a dice formula: {formula!r}"
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _die(formula):
    return _parse(formula)[1]


def _section(**fields):
    return {"type": "stat_block_section", "subtype": "level_scaling", **fields}


def _steps(text, formula):
    intro = _STEP_INTRO.search(text)
    if not intro or _die(_norm(intro.group(1))) != _die(formula):
        return None
    steps = sorted(
        (
            {"min_level": int(m.group(2)), "formula": _norm(m.group(1))}
            for m in _STEP.finditer(text, intro.start(), intro.end())
            if _die(_norm(m.group(1))) == _die(formula)
        ),
        key=lambda step: step["min_level"],
    )
    # A level-keyed "increases to" sentence we cannot read is a phrasing to
    # teach the reader, not damage to keep at its base dice.
    assert steps or not re.search(
        r"\blevel", intro.group(0), re.I
    ), f"unread level scaling: {intro.group(0)!r}"
    return _section(steps=steps) if steps else None


def _increment(text, formula):
    m = _THEREAFTER.search(text)
    if m and _norm(m.group(1)) == formula:
        every = 2 if m.group(3).lower() == "odd" else _num(m.group(3))
        return _section(
            increment=formula, per_levels=every, start_level=int(m.group(2)), additive=True
        )
    for m in _RATE.finditer(text):
        # The rate must be this entry's own dice: Shockwave's "(minimum 2d6
        # damage)" also becomes a damage entry, and it does not scale.
        if _norm(m.group(2)) != formula:
            continue
        per = _num(m.group(3) or m.group(4))
        out = _section(
            increment=formula, per_levels=per, start_level=per, additive=m.group(1) is not None
        )
        minimum = _MINIMUM.search(text, m.end(), m.end() + 60)
        if minimum:
            out["minimum"] = _norm(minimum.group(1))
        below = _BELOW.search(text, m.end(), m.end() + 60)
        if below:
            assert (
                int(below.group(2)) == per
            ), f"below level {below.group(2)} is not the start {per}"
            out["below_start"] = _norm(below.group(1))
        return out
    return None


def extract_level_scaling(text, formula):
    """Scaling for the damage `formula` stated in `text`, or None."""
    if not text or not formula or not re.fullmatch(r"\d+d\d+([+-]\d+)?", formula):
        return None
    return _steps(text, formula) or _increment(text, formula)


def _fmt(n, die, mod):
    return f"{n}d{die}" + (f"{mod:+d}" if mod else "")


def formula_at_level(formula, scaling, level):
    """The damage formula at `level`, per its level_scaling."""
    if "steps" in scaling:
        best = formula
        for step in scaling["steps"]:
            if level >= step["min_level"]:
                best = step["formula"]
        return best
    start, per = scaling["start_level"], scaling["per_levels"]
    k = 0 if level < start else (level - start) // per + 1
    if k == 0:
        n, die, mod = _parse(scaling.get("below_start", formula))
    else:
        n, die, mod = _parse(scaling["increment"])
        n, mod = n * k, mod * k
        if scaling["additive"]:
            bn, bdie, bmod = _parse(formula)
            assert bdie == die, (formula, scaling)
            n, mod = n + bn, mod + bmod
    # the printed floor holds at every level, below the first step included
    if "minimum" in scaling:
        n = max(n, _parse(scaling["minimum"])[0])
    return _fmt(n, die, mod)


# Starting levels the bands cover; the first and last bands are open-ended.
_MIN_LEVEL, _MAX_LEVEL = -1, 25
# The engine wraps an ability placed here in an offensive_action, so the
# ability's fields sit under .ability.
_WRAPPED = {"$.offense.offensive_actions"}
_LEVEL = "$.creature_type.level"


def _placements(change):
    """Ability name -> (target, sink) for every add_items in the change.

    `sink` takes the ability's replace effects. A select option's ability
    exists only once the option is chosen, and the engine applies selections
    after every change (pfsrd2-api: applySelections runs after the change
    loop), so those replaces ride inside the option as an effects bundle.
    """
    out = {}

    def place(name, target, sink):
        assert name not in out, f"ability {name!r} is placed twice in one change"
        out[name] = (target, sink)

    for effect in change.get("effects", []):
        if effect["operation"] == "add_items":
            for name in effect.get("names", []):
                place(name, effect["target"], change["effects"].extend)
        elif effect["operation"] == "select":
            options = effect["selection"].get("options", [])
            for k, option in enumerate(options):
                if option.get("operation") == "add_items":
                    for name in option.get("names", []):
                        place(name, option["target"], _bundler(options, k))
    return out


def _bundler(options, k):
    def sink(replaces):
        if "effects" not in options[k]:
            options[k] = {"effects": [options[k]]}
        options[k]["effects"].extend(replaces)

    return sink


def _level_gained_after(changes, index):
    """Levels the creature gains from level changes that run after `index`.

    Scaling text means the creature's final level, but a conditional sees the
    level at the moment it runs: templates change the level before their
    abilities, families change it last.
    """
    gained = 0
    for change in changes[index + 1 :]:
        if change.get("change_category") != "level":
            continue
        for effect in change["effects"]:
            assert (
                effect["target"] == _LEVEL and effect["operation"] == "adjustment"
            ), f"level change effect this pass cannot count: {effect!r}"
            gained += effect["value"]
    return gained


def _bands(formula, scaling, delta):
    """[lo, hi, formula] runs of starting level, base-formula runs dropped."""
    bands = []
    for level in range(_MIN_LEVEL, _MAX_LEVEL + 1):
        at = formula_at_level(formula, scaling, level + delta)
        if bands and bands[-1][2] == at:
            bands[-1][1] = level
        else:
            bands.append([level, level, at])
    return [band for band in bands if band[2] != formula]


def _conditional(lo, hi):
    parts = []
    if lo > _MIN_LEVEL:
        parts.append(f"{_LEVEL} >= {lo}")
    if hi < _MAX_LEVEL:
        parts.append(f"{_LEVEL} <= {hi}")
    return " && ".join(parts)


def _replaces(target, name, formula, scaling, delta):
    path = target + name_filter(name) + (".ability" if target in _WRAPPED else "")
    path += ".damage" + name_filter(formula, "formula") + ".formula"
    return [
        {"operation": "replace", "target": path, "value": at, "conditional": _conditional(lo, hi)}
        for lo, hi, at in _bands(formula, scaling, delta)
    ]


def _scaled_damage(change):
    for ability in change.get("abilities", []):
        for dmg in ability.get("damage", []):
            if "level_scaling" in dmg:
                yield ability["name"], dmg


def level_scaling_effects(changes):
    """Add per-level-band replace effects for scaled ability damage.

    PFSRD2-Parser-9vah: an applied template must carry the damage for the
    creature's level, not the base dice. The engine resolves no numeric
    index, so each target filters on the ability name and base formula.
    """
    for index, change in enumerate(changes):
        placed = _placements(change)
        delta = _level_gained_after(changes, index)
        for name, dmg in _scaled_damage(change):
            assert name in placed, f"scaled ability {name!r} has no add_items placement"
            target, sink = placed[name]
            sink(_replaces(target, name, dmg["formula"], dmg["level_scaling"], delta))


def level_scaling_effects_pass(obj):
    """Run level_scaling_effects over a template/family and its subtypes."""
    level_scaling_effects(obj.get("changes", []))
    for subtype in obj.get("subtypes", []):
        level_scaling_effects_pass(subtype)
