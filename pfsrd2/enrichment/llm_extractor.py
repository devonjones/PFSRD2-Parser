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

CRITIC = _CONFIG.get("critic", {})

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


_DICE = re.compile(r"\b\d+d\d+\s*(?:[+-]\s*\d+)?")


def _dice_in(text):
    """Every dice formula the source text actually prints, whitespace removed.

    The parallel of _dcs_in, and it exists for the same reason. Constrained
    decoding makes fabrication *easier*, not harder: the schema pattern
    "^[0-9]+d[0-9]+([+-][0-9]+)?$" guarantees whatever the model emits LOOKS
    like dice, so a bare number anywhere near the text gets completed into a
    plausible formula. Measured against the corpus, the model turned
    "30-foot cone" into 30d6, "60-foot line" into 60d6, "3 rounds in total"
    into 3d12 and a "+2 circumstance bonus" into 2d6+6.

    Two prompt revisions tried to instruct this away and both made extraction
    worse overall (see llm_config.toml damage). A formula the source never
    printed is decidable without asking the model anything, so decide it here.
    """
    return {
        m.group(0).replace(" ", "")
        for m in _DICE.finditer(text or "")
        if not _DURATION_AFTER.match(text or "", m.end())
    }


# A die immediately followed by a unit of time is a duration or a recharge
# timer, never damage: "stunned for 1d4 rounds", "recharges in 1d6 minutes".
_DURATION_AFTER = re.compile(
    r"\s*(?:more\s+)?(?:rounds?|minutes?|hours?|days?|turns?|weeks?)\b", re.I
)


def _dcs_in(text):
    """Every DC the source text actually prints."""
    found = set()
    for pattern in (r"\bDC\s+(\d+)", r"\bDC\b.{0,50}?\b(\d+)\b"):
        for m in re.finditer(pattern, text or "", re.I):
            found.add(int(m.group(1)))
    return found


_SAVE_WORDS = {
    "Fort": ("fortitude", "fort"),
    "Ref": ("reflex", "ref"),
    "Will": ("will",),
    "Flat Check": ("flat check", "flat"),
}


def _save_types_in(text):
    """Save types the source actually names."""
    low = (text or "").lower()
    return {
        code for code, words in _SAVE_WORDS.items()
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)
    }


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
    named = _save_types_in(text)

    seen, out = set(), []
    for entry in parsed.get("saves", []):
        dc = entry.get("dc")
        if dc is None or dc not in published:
            continue
        # A save type the text never names is invented, exactly like a DC it
        # never prints. The model reaches for one because a bare number looks
        # incomplete: "DC 22, 3d8 piercing, Escape DC 22" became DC 22 Ref, and
        # a skill check became all three saves at once. Dropping the type keeps
        # the DC, which is what the source actually said.
        save_type = entry.get("save_type")
        if save_type and save_type not in named:
            save_type = None
        key = (dc, save_type, bool(entry.get("basic")))
        if key in seen:
            continue
        seen.add(key)
        label = f"DC {dc}"
        if entry.get("basic"):
            label += " basic"
        if save_type:
            label += f" {save_type}"
        obj = {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "dc": dc,
            "text": label,
        }
        if save_type:
            obj["save_type"] = save_type
        if entry.get("basic"):
            obj["basic"] = True
        out.append(obj)
    return out or None


def _area_sizes_in(text):
    """Sizes the source writes as a measurement: "20-foot", "1-mile".

    Every one of the 284 area sizes already in the enrichment cache appears in
    its source text in this hyphenated form -- there were no exceptions -- so
    requiring it costs nothing and rejects the failure this exists for. A bare
    "within 30 feet" is a CONDITION on who is affected, not the area: "if more
    vrocks within 30 feet also Dance" became a 30-foot emanation alongside the
    real 20-foot one, and "120-foot line" produced a spurious 60-foot line.
    """
    return {
        int(m.group(1))
        for m in re.finditer(r"\b(\d+)\s*-\s*(?:foot|feet|mile|miles)\b", text or "", re.I)
    }


# Shapes the area schema accepts. "radius" is how the source usually writes a
# burst, so it maps rather than being dropped.
_AREA_SHAPES = "burst|cone|cylinder|emanation|line|wall|radius"

# "20-foot burst", "15-foot-radius", "30- foot cone" -- the hyphen may carry
# spaces and the shape may be joined to it, both of which appear in the corpus.
_AREA_PAT = re.compile(
    # The hyphen is load-bearing, not cosmetic. Making it optional lets the
    # pattern read a RANGE as an area: "within 60 feet in a 20-foot burst"
    # matched 60 and then missed the real 20-foot burst entirely.
    rf"\b(\d+)\s*-\s*(foot|feet|mile|miles)\b[^.;)]{{0,24}}?"
    rf"\b({_AREA_SHAPES})s?\b",
    re.I,
)


def extract_area_regex(name, text, model=None):
    """Areas, deterministically. No model involved.

    An area in this corpus is always written as a measurement followed closely
    by a shape word, which is regular enough that a regex beats the model on
    every axis measured. Against the 262 cached area values:

        258  reproduced exactly
          4  found an additional real area the model had missed
          0  missed anything the model found

    and over the 6068 abilities the pipeline records as having NO area, it
    fires on 43 -- all of them real areas the model failed to read, mostly odd
    hyphenation it choked on ("30- foot cone", "100- foot line",
    "15-foot-radius").

    It also recovers the troop-degradation second area the model consistently
    drops: "when the troop is reduced to 2 segments, this area decreases to a
    5-foot burst" is a real alternative area, and the model returns only the
    primary one.

    Signature matches the LLM extractors (model is accepted and ignored) so
    this drops into _EXTRACTOR_FNS without a special case.
    """
    seen, out = set(), []
    for m in _AREA_PAT.finditer(text or ""):
        # shape normalises (radius IS a burst) but the text field keeps the
        # word the source used -- the published data says "600-foot radius"
        # with shape "burst", and rewriting that to "600-foot burst" would
        # churn every radius area in the corpus.
        written = m.group(3).lower()
        shape = "burst" if written == "radius" else written
        # miles are rare but real: a pale sovereign's demesne is a 5-mile
        # radius, and forcing that to feet would be a factor-5280 error.
        unit = "miles" if m.group(2).lower().startswith("mile") else "feet"
        key = (m.group(1), shape, unit)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "type": "stat_block_section",
            "subtype": "area",
            "shape": shape,
            "size": int(m.group(1)),
            "unit": unit,
            # Normalised rather than the raw span: the source writes
            # "30- foot cone" and "15-foot-radius", the published form is
            # "30-foot cone". Reconstructing keeps the field canonical.
            "text": f"{m.group(1)}-{'mile' if unit == 'miles' else 'foot'} {written}",
        })
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
    published = _area_sizes_in(text)
    seen, out = set(), []
    for entry in parsed.get("areas", []):
        size, shape = entry.get("size"), entry.get("shape")
        if not size or not shape:
            continue
        # A size the source never states as a measurement is not this
        # ability's area, however plausible the shape beside it looks.
        try:
            if int(size) not in published:
                continue
        except (TypeError, ValueError):
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


# The published vocabulary is small -- 35 distinct values across the corpus,
# dominated by "1d4 rounds", "once per round", "once per day". A new spelling of
# an existing concept is a value nobody can group by, so the phrasing is
# normalised HERE rather than asked for in the prompt. Asking did not work: the
# model kept "can't use again for 1d4 rounds" through explicit examples, the
# same way it wrote prose into the damage formula field until a regex stopped
# it. Constrain mechanically, not in prose.
_FREQ_STRIPS = (
    # Up to four words for the subject, not one: creature names are routinely
    # two or three words ("the crag linnorm can't use breath weapon again for
    # 1d4 rounds"), and the single-word pattern left the entire sentence
    # standing as the frequency value.
    re.compile(
        r"^\s*(?:the\s+)?(?:[\w'\u2019-]+\s+){0,4}?"
        r"can(?:'|\u2019)?t\s+use\b.*?\bagain\s+for\s+",
        re.I,
    ),
    re.compile(r"^\s*only\s+", re.I),
    re.compile(r"^\s*(?:it|they|the\s+\w+)\s+can\s+(?:be\s+)?used?\s+", re.I),
)
_NUMBER_WORD_START = re.compile(r"^(one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)


# The model's ways of saying "nothing here". Without this they arrive as
# frequency VALUES: a test that had been skipped while ollama was unreachable
# caught "no constraint" being published for an ability whose only "per round"
# is a rate ("1 gallon per round").
_FREQ_NOTHING = frozenset({
    "none", "no constraint", "no constraints", "no frequency",
    "no frequency constraint", "no frequency constraints", "n/a", "not applicable",
})


def _normalise_frequency(value):
    """Reduce a frequency phrase to the form the published data uses."""
    out = value.strip().rstrip(".;,")
    if out.lower() in _FREQ_NOTHING:
        return None
    for pattern in _FREQ_STRIPS:
        out = pattern.sub("", out).strip()
    if not out:
        return None
    # Lowercase, except a leading number word which the corpus title-cases only
    # when the source sentence began with it -- "three times per day" is the
    # dominant published spelling, so lowercase wins.
    return out[0].lower() + out[1:] if out else None


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
        value = _normalise_frequency(str(item))
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return "; ".join(out) or None


def _critique(field, name, text, proposed):
    """Second opinion on an extraction. Returns a corrected list, or None.

    Off unless llm_config.toml enables it, and pointless without the grounding
    guard downstream: measured over 40 records it recovered 3 real values, and
    invented 2. It is fabrication-neutral, not fabrication-free.

    The critic model must differ from the extractor. qwen2.5:7b reviewing its
    own output invented damage for an ability whose text contains no dice --
    handed an empty list it produced one rather than agree with nothing. A
    larger model left it empty and recovered a case nothing else did.
    """
    if not CRITIC.get("enabled") or field != "damage":
        return None
    schema, template = SCHEMAS.get(field), CRITIC.get("prompt")
    if not schema or not template:
        return None
    prompt = template.format(
        name=name, text=text, proposed=json.dumps(sorted(set(proposed)))
    )
    parsed = _query_ollama_structured(prompt, schema, CRITIC.get("model"))
    if not parsed:
        return None
    return [d.get("formula") for d in parsed.get("damage", []) if d.get("formula")]


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

    entries = parsed.get("damage", [])
    corrected = _critique("damage", name, text, [e.get("formula") for e in entries])
    if corrected is not None:
        # Keep the first pass's types where the critic kept the formula; it is
        # asked about dice, not about damage types, and rebuilding an entry from
        # a bare formula would throw those away.
        by_formula = {e.get("formula"): e for e in entries}
        entries = [by_formula.get(f, {"formula": f}) for f in corrected]

    # Only formulas the source actually prints. reject_if_ungrounded is
    # all-or-nothing per field, so without this one invented 30d6 discards the
    # real 9d6 alongside it and the ability ends up with no damage at all.
    published = _dice_in(text)

    seen, out = set(), []
    for entry in entries:
        formula = (entry.get("formula") or "").strip()
        if not formula or formula.replace(" ", "") not in published:
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
    # Filter obvious non-answers. The exact-match set is shared with the
    # structured path so the two cannot disagree about what "nothing" looks
    # like -- this list had "no constraints" and the model said "no
    # constraint", so the singular sailed through and was published as a
    # frequency value.
    if lower.strip() in _FREQ_NOTHING:
        return None
    if any(
        phrase in lower
        for phrase in [
            "no frequency",
            "no instances",
            "none found",
            "not found",
            "no constraint",
            "there are no",
        ]
    ):
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
