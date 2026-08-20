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

# Request options (temperature and friends), passed through to ollama verbatim.
OPTIONS = _CONFIG.get("options", {})

# The system prompt. Unset, whatever the model's packaged chat template
# supplies is in force -- nuextract-tiny's build injects "You are a helpful
# assistant." and it leaked into extracted output.
SYSTEM = _CONFIG.get("system", "")

PROMPTS = _CONFIG["prompts"]
SCHEMAS = _CONFIG.get("schemas", {})
STRUCTURED_PROMPTS = _CONFIG.get("structured_prompts", {})
FREQUENCY_PROMPT = PROMPTS["frequency"]
DAMAGE_PROMPT = PROMPTS["damage"]
AREA_PROMPT = PROMPTS["area"]
DC_PROMPT = PROMPTS["dc"]
CATEGORY_PROMPT = PROMPTS["category"]


def _options_key():
    """System prompt and options, rendered for the cache key.

    Both change the answer, so they belong in the key for the same reason the
    prompt and the schema do. Both empty renders to an empty string, so cache
    entries written before either existed still hit.
    """
    parts = []
    if SYSTEM:
        parts.append(SYSTEM)
    if OPTIONS:
        parts.append(json.dumps(OPTIONS, sort_keys=True))
    return ("\x00" + "\x00".join(parts)) if parts else ""


def _request(model, prompt, format=None):
    """The JSON body for an ollama /api/generate call."""
    body = {"model": model, "prompt": prompt, "stream": False}
    if SYSTEM:
        body["system"] = SYSTEM
    if OPTIONS:
        body["options"] = OPTIONS
    if format is not None:
        body["format"] = format
    return body


def _query_ollama(prompt, model=None):
    """Send a prompt to the Ollama instance and return the response.

    Results are cached in ~/.pfsrd2/llm_cache.db keyed on (prompt_hash, model).
    If the prompt template changes, the hash changes and the LLM is re-queried.
    """
    model = model or DEFAULT_MODEL
    prompt_hash = compute_prompt_hash(prompt + _options_key())

    # Check cache first
    cached = cache_get(prompt_hash, model)
    if cached is not None:
        return cached

    payload = json.dumps(_request(model, prompt))
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


def _query_ollama_structured(prompt, schema, model=None):
    """Query with constrained decoding: the model can only emit `schema`.

    Ollama takes a JSON Schema as "format" and constrains generation to it, so
    malformed output stops being a failure mode. That is worth more here than
    any model swap -- see PFSRD2-Parser-4k8b for the bench.

    Returns the parsed object, or None. A None means the request failed or the
    response did not parse; it does NOT mean "no values found", which comes
    back as an empty list inside a valid object.

    The schema is folded into the cache key. It is part of the request, so a
    changed schema has to re-query for the same reason a changed prompt does --
    otherwise an old answer, shaped by the old schema, is served for a question
    nobody asked.
    """
    model = model or DEFAULT_MODEL
    schema_json = json.dumps(schema, sort_keys=True)
    prompt_hash = compute_prompt_hash(prompt + "\x00" + schema_json + _options_key())

    cached = cache_get(prompt_hash, model)
    if cached is not None:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            return None

    payload = json.dumps(_request(model, prompt, format=schema))
    try:
        result = subprocess.run(
            ["curl", "-s", OLLAMA_URL, "-d", payload],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None
        response_text = json.loads(result.stdout).get("response", "").strip()
        parsed = json.loads(response_text)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None

    cache_put(prompt_hash, model, response_text)
    return parsed


def _structured(field, name, text, model):
    """Shared plumbing: render the prompt, query under the schema, return raw."""
    schema = SCHEMAS.get(field)
    template = STRUCTURED_PROMPTS.get(field)
    if not schema or not template:
        return None
    return _query_ollama_structured(template.format(name=name, text=text), schema, model)


def _dcs_in(text):
    """Every DC the source text actually prints."""
    found = set()
    for pattern in (r"\bDC\s+(\d+)", r"\bDC\b.{0,50}?\b(\d+)\b"):
        for m in re.finditer(pattern, text or "", re.I):
            found.add(int(m.group(1)))
    return found


def extract_dc_structured(name, text, model=None):
    """Save DCs via constrained decoding. Returns save_dc objects, or None.

    The schema does two things the free-text path could not. save_type is an
    enum, so the model picks from the four values that exist rather than
    writing "Fortitude" or "basic Reflex" into a lookup that silently dropped
    what it did not recognise. And dc is an integer, which removes the
    "DC 30" / "30" / "DC of 30" parsing spread.

    The grounding check stays: PFSRD2-Parser-l59s was a schema-valid DC that
    the source never published, and a constrained decoder emits those just as
    happily as a free-text one.
    """
    parsed = _structured("dc", name, text, model)
    if not parsed:
        return None

    # Only DCs the source actually prints. This is the check _parse_dc_response
    # does on the free-text path, and dropping it here reintroduced
    # PFSRD2-Parser-l59s immediately: given "a basic Reflex save of the same
    # DC", the free-text path correctly returns nothing while the constrained
    # one invented DC 13. A schema that REQUIRES an integer pushes the model to
    # produce one, so constrained decoding makes this failure more likely, not
    # less.
    published = _dcs_in(text)

    seen, out = set(), []
    for entry in parsed.get("saves", []):
        dc = entry.get("dc")
        save_type = entry.get("save_type")
        if dc is None or not save_type:
            continue
        if dc not in published:
            continue
        key = (dc, save_type, bool(entry.get("basic")))
        if key in seen:
            continue
        seen.add(key)
        obj = {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "dc": dc,
            "save_type": save_type,
            "text": f"DC {dc}{' basic' if entry.get('basic') else ''} {save_type}",
        }
        if entry.get("basic"):
            obj["basic"] = True
        out.append(obj)
    return out or None


def extract_area_structured(name, text, model=None):
    """Areas via constrained decoding. Returns area objects, or None.

    shape is an enum matching _SHAPE_MAP's values. "radius" is excluded from it
    deliberately: the source writes it, but it means burst, so the model has to
    map it rather than emit a shape nothing downstream accepts.
    """
    parsed = _structured("area", name, text, model)
    if not parsed:
        return None
    seen, out = set(), []
    for entry in parsed.get("areas", []):
        size, shape = entry.get("size"), entry.get("shape")
        if not size or not shape:
            continue
        unit = entry.get("unit") or "feet"
        key = (size, shape, unit)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "type": "stat_block_section",
            "subtype": "area",
            "shape": shape,
            "size": size,
            "unit": unit,
            "text": f"{size}-{'mile' if unit == 'miles' else 'foot'} {shape}",
        })
    return out or None


def extract_frequency_structured(name, text, model=None):
    """Frequency via constrained decoding. Returns a joined string, or None.

    The weakest of the four: frequency is stored as prose, so the schema only
    guarantees a list of strings. It removes the semicolon-splitting, not any
    ambiguity about what the model should say.
    """
    parsed = _structured("frequency", name, text, model)
    if not parsed:
        return None
    seen, out = set(), []
    for item in parsed.get("frequencies", []):
        value = str(item).strip()
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return "; ".join(out) or None


def extract_damage_structured(name, text, model=None):
    """Damage via constrained decoding. Returns attack_damage objects, or None.

    Deliberately parallel to extract_damage_llm rather than replacing it: the
    other four extractors still use the free-text path, and the bench that
    justifies this covers damage only. Measure before switching anything else.

    De-duplicates. The model emitted the same formula four times for one
    ability, which is harmless in itself and must not reach the data.
    """
    parsed = _structured("damage", name, text, model)
    if not parsed:
        return None

    seen, out = set(), []
    for entry in parsed.get("damage", []):
        formula = (entry.get("formula") or "").strip()
        if not formula:
            continue
        damage_type = (entry.get("damage_type") or "").strip().lower() or None
        persistent = bool(entry.get("persistent"))
        # The model reliably writes "persistent bleed" into damage_type rather
        # than setting the boolean beside it. Both spellings mean the same
        # thing and only one of them matches what the rest of the pipeline
        # emits, so normalise rather than teach the prompt.
        if damage_type and damage_type.startswith("persistent "):
            damage_type = damage_type[len("persistent "):].strip() or None
            persistent = True
        key = (formula, damage_type, persistent)
        if key in seen:
            continue
        seen.add(key)
        obj = {
            "type": "stat_block_section",
            "subtype": "attack_damage",
            "formula": formula,
        }
        if damage_type:
            obj["damage_type"] = damage_type
        if persistent:
            obj["persistent"] = True
        out.append(obj)
    return out or None


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
