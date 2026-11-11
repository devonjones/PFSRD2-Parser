"""Read level-scaled damage from ability text.

Template and family abilities state damage that grows with the creature's
level ("increases to 2d6 if the cryptid is 9th level or higher", "1d6 per
level", "plus an additional 1d6 for every 6 levels"). The damage extractor
keeps only the base dice, so this reader marks how they scale.

Two shapes, both grounded in the text (nothing is inferred):
- steps: explicit thresholds, each printed: [{"min_level": 9, "formula": "2d6"}]
- increment: one printed rate. Damage at level L is
  (base if additive else nothing) + k * increment, where k counts the
  thresholds reached: start_level, start_level + per_levels, ...
"""

import re

_ORD = r"(\d+)(?:st|nd|rd|th)"
_DICE = r"(\d+d\d+(?:\+\d+)?)"
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COUNT = r"(\d+|" + "|".join(_WORDS) + r")"

# "2d6 if the cryptid is 9th level or higher" / "is at least 8th level" /
# "2d4 at 5th level"
_STEP = re.compile(_DICE + r"\s+(?:if [^,;.]*?(?:at least\s+)?|at\s+)" + _ORD + r" level", re.I)
_STEP_INTRO = re.compile(r"increas\w*\s+to\s+\d+d\d+", re.I)

# "1d6 at 3rd level and every odd level thereafter" /
# "1d6 at 4th level and every 3 levels thereafter"
_THEREAFTER = re.compile(
    r"increases by "
    + _DICE
    + r" at "
    + _ORD
    + r" level and every (odd|\d+|"
    + "|".join(_WORDS)
    + r") levels? thereafter",
    re.I,
)
# "1d8 negative damage for every 3 levels" / "1d6 damage per level" /
# "plus an additional 1d6 for every 6 levels" / "+ 1d6 per 2 levels"
_RATE = re.compile(
    r"(plus (?:an )?(?:additional )?|increases by |\+ )?"
    + _DICE
    + r"(?:\s+[\w ]{0,25}?damage)?\s+(?:per (?:"
    + _COUNT
    + r" )?levels?|for every "
    + _COUNT
    + r" levels)",
    re.I,
)
_MINIMUM = re.compile(r"\(minimum " + _DICE + r"\)", re.I)
# Spitting Zombie: "1d12 acid damage per 3 levels of the zombie (or 1d6 acid
# damage below level 3)"
_BELOW = re.compile(r"\(or " + _DICE + r"[\w ]*? below level (\d+)\)", re.I)


def _num(word):
    if word is None:
        return 1
    return int(word) if word.isdigit() else _WORDS[word.lower()]


def _die(formula):
    return formula.split("d", 1)[1].split("+", 1)[0]


def _section(**fields):
    return {"type": "stat_block_section", "subtype": "level_scaling", **fields}


def _steps(text, formula):
    intro = _STEP_INTRO.search(text)
    if not intro:
        return None
    steps = [
        {"min_level": int(m.group(2)), "formula": m.group(1)}
        for m in _STEP.finditer(text, intro.start())
        if _die(m.group(1)) == _die(formula)
    ]
    return _section(steps=steps) if steps else None


def _increment(text, formula):
    m = _THEREAFTER.search(text)
    if m and _die(m.group(1)) == _die(formula):
        every = 2 if m.group(3).lower() == "odd" else _num(m.group(3))
        return _section(
            increment=m.group(1), per_levels=every, start_level=int(m.group(2)), additive=True
        )
    for m in _RATE.finditer(text):
        inc = m.group(2)
        if _die(inc) != _die(formula):
            continue
        per = _num(m.group(3) or m.group(4))
        additive = m.group(1) is not None
        out = _section(increment=inc, per_levels=per, start_level=per, additive=additive)
        minimum = _MINIMUM.search(text, m.end(), m.end() + 60)
        if minimum:
            out["minimum"] = minimum.group(1)
        below = _BELOW.search(text, m.end(), m.end() + 60)
        if below and int(below.group(2)) == out["start_level"]:
            out["below_start"] = below.group(1)
        return out
    return None


def extract_level_scaling(text, formula):
    """Scaling for the damage `formula` stated in `text`, or None."""
    if not text or not formula or "d" not in formula:
        return None
    return _steps(text, formula) or _increment(text, formula)


def _parse(formula):
    count, rest = formula.split("d", 1)
    die, _, mod = rest.partition("+")
    return int(count), int(die), int(mod or 0)


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
        mn = _parse(scaling["minimum"])[0]
        n = max(n, mn)
    return f"{n}d{die}" + (f"+{mod}" if mod else "")
