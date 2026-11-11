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
    + r" )?levels?(?! of the [\w ]*?(?:spell|ability|ritual))|for every "
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
    steps = [
        {"min_level": int(m.group(2)), "formula": _norm(m.group(1))}
        for m in _STEP.finditer(text, intro.start())
        if _die(_norm(m.group(1))) == _die(formula)
    ]
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
        if below and int(below.group(2)) == per:
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
        return scaling.get("below_start", formula)
    n, die, mod = _parse(scaling["increment"])
    n, mod = n * k, mod * k
    if scaling["additive"]:
        bn, bdie, bmod = _parse(formula)
        assert bdie == die, (formula, scaling)
        n, mod = n + bn, mod + bmod
    if "minimum" in scaling:
        n = max(n, _parse(scaling["minimum"])[0])
    return _fmt(n, die, mod)
