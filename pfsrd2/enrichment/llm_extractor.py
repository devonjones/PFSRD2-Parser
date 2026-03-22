"""LLM-based extraction of structured mechanics from ability text.

Uses a local Ollama instance with per-type prompts. Each extraction type
has its own prompt template optimized through iteration against known
test cases.
"""

import json
import subprocess

DEFAULT_MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/api/generate"


def _query_ollama(prompt, model=None):
    """Send a prompt to the local Ollama instance and return the response."""
    model = model or DEFAULT_MODEL
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
    })
    try:
        result = subprocess.run(
            ["curl", "-s", OLLAMA_URL, "-d", payload],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return None
        response = json.loads(result.stdout)
        return response.get("response", "").strip()
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None


# --- Per-type prompt templates ---

FREQUENCY_PROMPT = """You are extracting frequency constraints from Pathfinder 2E ability text. A frequency constraint is any phrase that limits how often something can be done.

Scan the ENTIRE text carefully. Look for ALL instances of:
- "once per X"
- "X times per Y"
- "can't ... again for X"
- "only once per X"
- "Frequency: once per X"

Return every frequency constraint found as a semicolon-separated list.

Ability: {name}
Text: {text}

Frequency constraints found:"""


DAMAGE_PROMPT = """You are extracting damage dice from Pathfinder 2E ability text.

Extract ALL dice formulas (like 2d6, 4d8+10, 1d4) that represent damage.

Patterns to look for:
- "XdY type damage" (e.g., "2d6 fire damage")
- "XdY damage" with no type (e.g., "1d4 extra damage")
- "XdY persistent type damage" (e.g., "1d6 persistent bleed damage")
- "Damage XdY type" (e.g., "Damage 1d6+2 slashing")
- "deals/takes XdY type" even without the word "damage"
- "XdY type, DC" format (e.g., "6d6 spirit, DC 30")

Do NOT extract:
- Text about damage without dice ("combine their damage", "deals damage equal to")
- Damage reduction ("takes half damage", "resistance to damage")
- Healing references ("regains HP equal to damage")
- Non-damage dice ("1d4 rounds" is a duration, not damage)

For each found: XdY[+/-Z] type [persistent]
If no type, just: XdY
Semicolon-separated list, or "none".

Examples:
Text: "deals 12d6 acid damage in a 60-foot line"
Result: 12d6 acid

Text: "deals 1d4 extra damage to prone creatures"
Result: 1d4

Text: "takes 4d6 damage (DC 33 basic Fortitude save)"
Result: 4d6

Text: "6d6 spirit, DC 30"
Result: 6d6 spirit

Text: "combine their damage for the purpose of resistances"
Result: none

Text: "takes 2d6 fire damage and 1d6 persistent bleed damage"
Result: 2d6 fire; 1d6 persistent bleed

Ability: {name}
Text: {text}

Damage:"""


AREA_PROMPT = """You are extracting area-of-effect information from Pathfinder 2E ability text.

Look for ALL instances of these area patterns anywhere in the text:
- "X-foot line"
- "X-foot cone"
- "X-foot burst"
- "X-foot emanation"
- "X-foot wall"
- "X-foot cylinder"
- "X-foot radius" (treat as burst)

The text may contain HTML tags — look inside them too.
Return each UNIQUE area once as: size-foot shape

Do NOT include distances that are reach, range, tether length, movement, or object size.

Return as a semicolon-separated list, or "none" if no areas found.

Ability: {name}
Text: {text}

Areas:"""


# --- Extraction functions ---

def _clean_llm_response(response):
    """Clean up LLM response, filtering noise and normalizing format."""
    if not response:
        return None
    lower = response.lower()
    # Filter obvious non-answers
    if any(phrase in lower for phrase in [
        "no frequency", "no instances", "none found", "not found",
        "no constraints", "there are no",
    ]):
        return None
    if lower.strip() == "none":
        return None

    parts = [p.strip() for p in response.split(";") if p.strip()]
    cleaned = []
    for part in parts:
        p = part.lower().strip()
        if p == "none":
            continue
        if p.startswith("frequency constraints"):
            continue
        cleaned.append(part.strip())

    return cleaned if cleaned else None


def extract_frequency_llm(name, text, model=None):
    """Extract frequency constraints using LLM.

    Returns a semicolon-separated string of frequencies, or None.
    """
    prompt = FREQUENCY_PROMPT.format(name=name, text=text)
    response = _query_ollama(prompt, model)
    parts = _clean_llm_response(response)
    if not parts:
        return None
    return "; ".join(parts)


DC_PROMPT = """You are extracting DCs (Difficulty Classes) from Pathfinder 2E ability text. A DC is a specific number a creature must meet or beat.

Extract ALL static numeric DCs. These include:
- "DC 30 Fortitude save" or "DC 30 basic Reflex"
- "Escape DC 18" or "DC to Escape is 18"
- "DC to Balance is 18" or "DC to stop the bleeding is 35"
- "a DC of 30"
- "DC 5 flat check"

Do NOT extract:
- References to another creature's DC ("creature's Fortitude DC", "Athletics DC")
- "the DC is X rather than Y" (conditional text)

Examples:
Text: "DC 30 basic Reflex save. It can't use Breath Weapon again for 1d4 rounds."
Result: DC 30 basic Reflex

Text: "The DC to Escape the net is 16."
Result: DC 16

Text: "Athletics check with a DC of 30 or the pilot's Sailing Lore DC"
Result: DC 30

Text: "They can Cast the Spell using the original caster's DC."
Result: none

Text: "all adjacent creatures are exposed to the same disease, at the same DC."
Result: none

Return ONLY the semicolon-separated list or "none". No explanations.

Now extract from:
Ability: {name}
Text: {text}

DCs found:"""


_SHAPE_MAP = {
    "line": "line",
    "cone": "cone",
    "burst": "burst",
    "emanation": "emanation",
    "wall": "wall",
    "cylinder": "cylinder",
    "radius": "burst",
}


def _parse_area_response(parts):
    """Parse area response parts into structured area objects."""
    import re
    areas = []
    seen = set()
    pattern = re.compile(r"(\d+)[- ](?:foot|mile)\s+(\w+)", re.I)
    for part in parts:
        m = pattern.search(part)
        if m:
            size = int(m.group(1))
            raw_shape = m.group(2).lower()
            shape = _SHAPE_MAP.get(raw_shape)
            if not shape:
                continue
            unit = "miles" if "mile" in part.lower() else "feet"
            key = (size, shape, unit)
            if key in seen:
                continue
            seen.add(key)
            areas.append({
                "type": "stat_block_section",
                "subtype": "area",
                "text": part.strip(),
                "shape": shape,
                "size": size,
                "unit": unit,
            })
    return areas if areas else None


def _parse_dc_response(parts, original_text=""):
    """Parse DC response parts into structured save_dc objects.

    Validates extracted DCs against the original text to prevent
    hallucinations (e.g., model extracting "60" from "60-foot").
    """
    import re
    saves = []
    seen = set()
    save_type_map = {
        "fortitude": "Fort", "fort": "Fort",
        "reflex": "Ref", "ref": "Ref",
        "will": "Will",
        "flat check": "Flat Check", "flat": "Flat Check",
    }

    # Build set of DCs actually present in original text
    valid_dcs = set()
    if original_text:
        for m in re.finditer(r"\bDC\s+(\d+)", original_text, re.I):
            valid_dcs.add(int(m.group(1)))
        # Also "DC to X is Y" and "DC of Y"
        for m in re.finditer(r"\bDC\b.{0,50}?\b(\d+)\b", original_text, re.I):
            valid_dcs.add(int(m.group(1)))

    for part in parts:
        m = re.search(r"DC\s+(\d+)", part, re.I)
        if not m:
            continue
        dc_val = int(m.group(1))

        # Validate against original text if available
        if valid_dcs and dc_val not in valid_dcs:
            continue

        lower = part.lower()
        is_basic = "basic" in lower
        save_type = None
        for name_str, mapped in save_type_map.items():
            if name_str in lower:
                save_type = mapped
                break
        key = (dc_val, save_type)
        if key in seen:
            continue
        seen.add(key)
        result = {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "text": part.strip(),
            "dc": dc_val,
        }
        if save_type:
            result["save_type"] = save_type
        if is_basic:
            result["basic"] = True
        saves.append(result)
    return saves if saves else None


def _parse_damage_response(parts):
    """Parse damage response parts into structured attack_damage objects."""
    import re
    from pfsrd2.enrichment.regex_extractor import _resolve_damage_type
    damages = []
    seen = set()
    for part in parts:
        m = re.search(r"(\d+d\d+(?:\s*[+\-]\s*\d+)?)", part)
        if not m:
            continue
        formula = m.group(1).replace(" ", "")
        lower = part.lower()
        is_persistent = "persistent" in lower
        # Try to find damage type after the formula
        remaining = part[m.end():].strip().lower()
        # Remove "persistent" to find the type
        remaining = remaining.replace("persistent", "").strip()
        damage_type = None
        for word in remaining.split():
            dt = _resolve_damage_type(word)
            if dt:
                damage_type = dt
                break
        key = (formula, damage_type, is_persistent)
        if key in seen:
            continue
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
    return damages if damages else None


def extract_damage_llm(name, text, model=None):
    """Extract damage dice using LLM.

    Returns a list of attack_damage objects, or None.
    """
    prompt = DAMAGE_PROMPT.format(name=name, text=text)
    response = _query_ollama(prompt, model)
    parts = _clean_llm_response(response)
    if not parts:
        return None
    return _parse_damage_response(parts)


def extract_dc_llm(name, text, model=None):
    """Extract save DCs using LLM.

    Returns a list of save_dc objects, or None.
    """
    prompt = DC_PROMPT.format(name=name, text=text)
    response = _query_ollama(prompt, model)
    parts = _clean_llm_response(response)
    if not parts:
        return None
    return _parse_dc_response(parts, original_text=text)


def extract_area_llm(name, text, model=None):
    """Extract areas of effect using LLM.

    Returns a list of area objects, or None.
    """
    prompt = AREA_PROMPT.format(name=name, text=text)
    response = _query_ollama(prompt, model)
    parts = _clean_llm_response(response)
    if not parts:
        return None
    return _parse_area_response(parts)
