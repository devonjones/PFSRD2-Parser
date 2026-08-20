"""LLM-based extraction of structured mechanics from ability text.

Uses an Ollama instance with per-type prompts. Each extraction type has its own
prompt template optimized through iteration against known test cases.

Model, host and every prompt live in llm_config.toml beside this file. Prompts
are tuning rather than logic -- iterating on wording should not be a code
change -- and a diff of that file reads as "what we asked the model".

Ollama is NOT on localhost: it was moved off the parser box because running it
alongside a full corpus parse crashed the machine. Override the host with
PFSRD2_OLLAMA_URL.
"""

import json
import os
import re
import subprocess
import tomllib

from pfsrd2.enrichment.llm_cache import cache_get, cache_put, compute_prompt_hash
from pfsrd2.enrichment.regex_extractor import _SHAPE_MAP, _resolve_damage_type

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_config.toml")

with open(_CONFIG_PATH, "rb") as _fh:
    _CONFIG = tomllib.load(_fh)

# The host may move -- ollama was taken off the parser box because running it
# alongside a full corpus parse crashed the machine -- so it is overridable.
OLLAMA_URL = os.environ.get("PFSRD2_OLLAMA_URL", _CONFIG["url"])

# The model is NOT overridable by environment on purpose. Every enriched record
# stores "llm:<model>" as its extraction_method; changing it from a shell
# variable would split the corpus across two models with nothing in the data
# saying which produced what. Change it in llm_config.toml, deliberately, and
# expect to re-enrich.
DEFAULT_MODEL = _CONFIG["model"]

PROMPTS = _CONFIG["prompts"]
FREQUENCY_PROMPT = PROMPTS["frequency"]
DAMAGE_PROMPT = PROMPTS["damage"]
AREA_PROMPT = PROMPTS["area"]
DC_PROMPT = PROMPTS["dc"]
CATEGORY_PROMPT = PROMPTS["category"]


def _query_ollama(prompt, model=None):
    """Send a prompt to the Ollama instance and return the response.

    Results are cached in ~/.pfsrd2/llm_cache.db keyed on (prompt_hash, model).
    If the prompt template changes, the hash changes and the LLM is re-queried.
    """
    model = model or DEFAULT_MODEL
    prompt_hash = compute_prompt_hash(prompt)

    # Check cache first
    cached = cache_get(prompt_hash, model)
    if cached is not None:
        return cached

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
    )
    try:
        result = subprocess.run(
            ["curl", "-s", OLLAMA_URL, "-d", payload],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        response = json.loads(result.stdout)
        response_text = response.get("response", "").strip()
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None

    # Cache the result (even empty responses, to avoid re-querying)
    cache_put(prompt_hash, model, response_text)
    return response_text


# --- Per-type prompt templates ---







# --- Extraction functions ---


def _clean_llm_response(response):
    """Clean up LLM response, filtering noise and normalizing format."""
    if not response:
        return None
    lower = response.lower()
    # Filter obvious non-answers
    if any(
        phrase in lower
        for phrase in [
            "no frequency",
            "no instances",
            "none found",
            "not found",
            "no constraints",
            "there are no",
        ]
    ):
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




def _parse_area_response(parts):
    """Parse area response parts into structured area objects."""
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
            areas.append(
                {
                    "type": "stat_block_section",
                    "subtype": "area",
                    "text": part.strip(),
                    "shape": shape,
                    "size": size,
                    "unit": unit,
                }
            )
    return areas if areas else None


def _parse_dc_response(parts, original_text=""):
    """Parse DC response parts into structured save_dc objects.

    Validates extracted DCs against the original text to prevent
    hallucinations (e.g., model extracting "60" from "60-foot").
    """
    saves = []
    seen = set()
    save_type_map = {
        "fortitude": "Fort",
        "fort": "Fort",
        "reflex": "Ref",
        "ref": "Ref",
        "will": "Will",
        "flat check": "Flat Check",
        "flat": "Flat Check",
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
        remaining = part[m.end() :].strip().lower()
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


# --- Ability category classification ---

# Valid categories matching creature stat block sections
VALID_CATEGORIES = {
    "offensive",
    "automatic",
    "reactive",
    "interaction",
    "special_sense",
    "hp_automatic",
    "communication",
}



def classify_ability_category_llm(name, text, action="", traits="", model=None):
    """Classify an ability into a creature stat block category using LLM.

    Returns one of the VALID_CATEGORIES strings, or None if classification fails.
    """
    prompt = CATEGORY_PROMPT.format(
        name=name,
        text=text[:500],  # Truncate long text
        action=action or "none",
        traits=traits or "none",
    )
    response = _query_ollama(prompt, model)
    if not response:
        return None

    # Clean and validate
    category = response.strip().lower().replace(" ", "_")
    # Handle common LLM variations
    if category in ("sense", "senses", "perception"):
        category = "special_sense"
    if category in ("defense", "defensive", "passive"):
        category = "automatic"
    if category in ("offense", "attack", "proactive"):
        category = "offensive"
    if category in ("reaction",):
        category = "reactive"
    if category in ("hp", "hitpoints", "hit_points", "healing"):
        category = "hp_automatic"

    if category in VALID_CATEGORIES:
        return category
    return None
