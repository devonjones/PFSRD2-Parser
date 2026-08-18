"""Ability enrichment pass for the creature parser pipeline.

Populates the enrichment DB with ability records and creature links.
When enriched data exists, merges it into the ability objects.
"""

import json
import re
import sys

from pfsrd2.ability_identity import ability_to_raw_json, compute_identity_hash
from pfsrd2.ability_placement import deterministic_ability_category
from pfsrd2.enrichment.regex_extractor import ENRICHMENT_VERSION, extract_all
from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.enrichment import (
    add_review_reason,
    fetch_ability_by_hash,
    get_enrichment_db_connection,
    insert_ability_record,
    insert_creature_link,
    mark_stale,
    refresh_raw_json,
    update_enriched_json,
)
from pfsrd2.sql.monster_abilities import fetch_monster_abilities_by_name
from universal.universal import DEGREE_FIELDS

# Fields that enrichment can add to an ability object.
# These are the structured mechanics extracted from text.
ENRICHMENT_FIELDS = ("saving_throw", "damage", "area", "range", "frequency")

# Module-level flag: when False, skip inline regex enrichment.
# Set via --no-enrich CLI flag, passed through to parsers.
_inline_enrich = True


def set_inline_enrich(enabled):
    """Enable/disable inline regex enrichment during parser runs."""
    global _inline_enrich
    _inline_enrich = enabled


def _try_inline_enrich(curs, ability_id, raw_json):
    """Run regex + LLM extraction on a new/unenriched record and store the result.

    Called inline during parser enrichment passes so that enrichment
    is available on the same run, avoiding the parser→enrich→parser cycle.
    Returns the enriched_json string if enrichment was produced, else None.
    """
    if not _inline_enrich:
        return None

    # Phase 1: Regex extraction
    result, missed = extract_all(raw_json)

    # Phase 2: LLM extraction for missed keywords (cached, so fast after first run)
    if missed:
        from pfsrd2.enrichment.llm_extractor import (
            extract_area_llm,
            extract_damage_llm,
            extract_dc_llm,
            extract_frequency_llm,
        )

        ability = json.loads(raw_json)
        name = ability.get("name", "")
        text = ability.get("text", "")
        effect = ability.get("effect", "")
        combined = f"{text} {effect}".strip()

        if result is None:
            result = dict(ability)

        _LLM_EXTRACTORS = {
            "frequency": (extract_frequency_llm, "frequency"),
            "dc": (extract_dc_llm, "saving_throw"),
            "area": (extract_area_llm, "area"),
            "damage": (extract_damage_llm, "damage"),
        }

        for keyword in missed:
            if keyword in _LLM_EXTRACTORS and combined:
                extractor_fn, field_name = _LLM_EXTRACTORS[keyword]
                if not result.get(field_name):
                    llm_result = extractor_fn(name, combined)
                    rejected = reject_if_ungrounded(
                        llm_result, combined, field_name, name, curs, ability_id
                    )
                    if not rejected and llm_result:
                        result[field_name] = llm_result

    if result is None:
        return None
    enriched_json = json.dumps(result, sort_keys=True, ensure_ascii=False)
    update_enriched_json(curs, ability_id, enriched_json, ENRICHMENT_VERSION, "inline")
    return enriched_json


# Dice first, so "4d6+2" is one token. Splitting it into 4, 6 and 2 and then
# looking for a bare 4 fails: in "4d6" the digit is followed by a word character,
# so there is no word boundary to match on, and every dice formula reads as
# ungrounded.
_A_NUMBER = re.compile(r"\d+d\d+(?:[+-]\d+)?|\d+")


# bin/pf2_enrich_abilities re-queues a flagged record by substring-matching its
# review_reason against the --llm-type. One of the four types is not spelled
# the way its FIELD is -- dc/saving_throw -- so a reason naming only the field
# is a reason nothing can re-queue: nine saving_throw rejections were parked
# permanently because "dc" does not occur in "saving_throw".
_LLM_TYPE_OF_FIELD = {
    "damage": "damage",
    "saving_throw": "dc",
    "area": "area",
    "frequency": "frequency",
}


def rejection_reason(field_name, ungrounded):
    """Why a record was flagged, worded so run_llm can find it again."""
    llm_type = _LLM_TYPE_OF_FIELD.get(field_name, field_name)
    return (
        f"PFSRD2-Parser-l59s: LLM returned {ungrounded!r} for {field_name} "
        f"(--llm-type {llm_type}), absent from the ability text"
    )


def reject_if_ungrounded(llm_result, source, field_name, name, curs, ability_id, mark=True):
    """True when the extractor invented a number, and the record is flagged.

    Shared by both LLM paths on purpose. The guard first existed only on the
    inline path, which covered 6 of the 63 poisoned records in
    PFSRD2-Parser-l59s -- the other 57 came through bin/pf2_enrich_abilities
    run_llm, an identical extractor loop with no check at all. A second
    hand-written copy of the check is how that happened, so there is one copy.

    Rejected rather than asserted: an assert halts a 4500-file creature run on
    a model hiccup, and the correct output is simply "no value".

    stderr alone is not enough, which is why this also marks the record. The
    result is cached, so the warning prints exactly once ever and every later
    run is silent. needs_review is durable and queryable.

    `mark` is False for a dry run, where nothing should be written.
    """
    ungrounded = a_number_the_source_never_published(llm_result, source)
    if not ungrounded:
        return False
    sys.stderr.write(
        f"REJECTED ungrounded {field_name} for {name!r}: {ungrounded!r} does "
        f"not occur in the ability text. {llm_result!r}\n"
    )
    if mark:
        add_review_reason(curs, ability_id, rejection_reason(field_name, ungrounded))
    return True


def a_number_the_source_never_published(llm_result, source):
    """The first number in an LLM answer that is absent from its own input.

    PFSRD2-Parser-l59s: extract_dc_llm returned "DC 30 basic Reflex" -- character
    for character its own few-shot example in DC_PROMPT -- for Repelling Blast,
    whose text says only "a basic Reflex save of the same DC". "DC 30" occurs
    nowhere on that source page. The value looked like ordinary game data and
    took a corpus sweep to find.

    The prompt already instructs the model not to extract a DC that references
    another creature's, so this is not a prompting problem and better wording
    will not close it. A model cannot invent a number that is already in the
    text it was handed, so requiring every number to appear there is a cheap,
    deterministic floor that needs no judgement.

    Deliberately checks digits only. Damage TYPES and save names are words the
    model may legitimately normalise ("negative" -> "void"); numbers are not.
    Returns the offending number, or None when everything is grounded.
    """
    if not llm_result:
        return None
    # ensure_ascii=False, or an en-dash escapes to "\u2013" and its digits are
    # read as a number: "a -2 circumstance penalty" produced the phantom "20132".
    # "4d6 + 2" in the source grounds "4d6+2" in the answer; a model normalising
    # spacing is not fabricating.
    source = re.sub(r"\s*([+-])\s*", r"\1", source)
    for number in _A_NUMBER.findall(json.dumps(llm_result, ensure_ascii=False)):
        # BOTH branches need the boundary. The dice branch used to be a bare
        # substring, so "1d6" was satisfied by a source containing only "11d6"
        # and bare "20" by "1d20" -- the guard accepted a fabricated number
        # because a longer one happened to contain it. The comment claimed dice
        # were "matched whole"; they were not.
        #
        # The class is [\dd], not \d: a bare "20" is otherwise grounded by
        # "1d20", where the preceding character is a letter.
        pattern = rf"(?<![\dd]){re.escape(number)}(?!\d)"
        if not re.search(pattern, source):
            return number
    return None


def _get_creature_metadata(struct):
    """Extract creature-level metadata for the link table."""
    sb = struct.get("stat_block", {})
    ct = sb.get("creature_type", {})
    trait_names = [t["name"] for t in ct.get("traits", []) if isinstance(t, dict) and "name" in t]
    sources = struct.get("sources", [])
    source_name = sources[0]["name"] if sources else None
    return {
        "creature_game_id": str(struct.get("aonid", "")),
        "creature_name": struct.get("name", ""),
        "creature_level": ct.get("level"),
        "creature_traits": trait_names,
        "source_name": source_name,
    }


def _walk_abilities(struct):
    """Yield (category, ability) tuples from a creature's stat block.

    Categories match the location in the creature schema:
    - "automatic": defense.automatic_abilities
    - "reactive": defense.reactive_abilities
    - "hp_automatic": defense.hitpoints[*].automatic_abilities
    - "interaction": stat_block.interaction_abilities
    - "communication": statistics.languages.communication_abilities
    - "offensive": offense.offensive_actions[*].ability
    - "special_sense": senses.special_senses
    """
    sb = struct.get("stat_block", {})
    defense = sb.get("defense", {})

    # defense.automatic_abilities
    for ability in defense.get("automatic_abilities", []):
        if ability.get("subtype") == "ability":
            yield "automatic", ability

    # defense.reactive_abilities
    for ability in defense.get("reactive_abilities", []):
        if ability.get("subtype") == "ability":
            yield "reactive", ability

    # defense.hitpoints[*].automatic_abilities
    for hp in defense.get("hitpoints", []):
        for ability in hp.get("automatic_abilities", []):
            if ability.get("subtype") == "ability":
                yield "hp_automatic", ability

    # stat_block.interaction_abilities
    for ability in sb.get("interaction_abilities", []):
        if ability.get("subtype") == "ability":
            yield "interaction", ability

    # statistics.languages.communication_abilities
    languages = sb.get("statistics", {}).get("languages", {})
    for ability in languages.get("communication_abilities", []):
        if ability.get("subtype") == "ability":
            yield "communication", ability

    # offense.offensive_actions[*].ability
    for oa in sb.get("offense", {}).get("offensive_actions", []):
        if oa.get("offensive_action_type") == "ability":
            ability = oa.get("ability")
            if ability:
                yield "offensive", ability

    # senses.special_senses
    for sense in sb.get("senses", {}).get("special_senses", []):
        if sense.get("subtype") == "ability":
            yield "special_sense", sense


def _dc_key(save_dc):
    """Identity key for deduplicating save DCs."""
    return (save_dc.get("dc"), save_dc.get("save_type"))


def _normalize_to_list(value):
    """Normalize a value to a list."""
    if isinstance(value, list):
        return value
    return [value] if value else []


def _area_key(area):
    """Identity key for deduplicating areas."""
    return (area.get("size"), area.get("shape"), area.get("unit"))


def _damage_key(damage):
    """Identity key for deduplicating damage."""
    return (damage.get("formula"), damage.get("damage_type"), damage.get("persistent", False))


def _merge_list_field(ability, enriched, field, key_fn):
    """Merge a list field, deduplicating by key function.

    Handles both single object and array formats.
    Produces an array.
    """
    new = enriched.get(field)
    if not new:
        return

    existing = _normalize_to_list(ability.get(field))
    new = _normalize_to_list(new)

    existing_keys = {key_fn(item) for item in existing}
    for item in new:
        if key_fn(item) not in existing_keys:
            existing.append(item)
            existing_keys.add(key_fn(item))

    if existing:
        ability[field] = existing


def _raws_equivalent(raw_a, raw_b):
    """True when two raw serializations differ only in links or whitespace.

    The identity hash covers the enrichment-extraction inputs (name/text/
    effect/frequency/...) with whitespace normalization, but the raw also
    carries fields the hash excludes: links (edition-specific targets) AND
    parser-written mechanics (saving_throw, damage, stages, ...). Errata to
    a hash-excluded mechanics field must still stale the record — otherwise
    _merge_list_field appends the outdated enriched copy alongside the new
    parsed value forever. Only links/whitespace drift is merge-safe.
    """

    def canon(v):
        if isinstance(v, dict):
            # "links" (ability-level) and "link" (inside trait/action
            # objects) both carry edition-specific aonid targets.
            return {k: canon(x) for k, x in v.items() if k not in ("links", "link")}
        if isinstance(v, list):
            return [canon(x) for x in v]
        if isinstance(v, str):
            return " ".join(v.split())
        return v

    return canon(json.loads(raw_a)) == canon(json.loads(raw_b))


def _merge_enrichment(ability, enriched_json):
    """Merge enriched fields into the ability object in-place.

    For list-capable fields (saving_throw, area, damage), merges and
    deduplicates. For scalar fields, only adds if not already present.
    """
    enriched = json.loads(enriched_json)

    # List-capable fields get merge logic
    _merge_list_field(ability, enriched, "saving_throw", _dc_key)
    _merge_list_field(ability, enriched, "area", _area_key)
    _merge_list_field(ability, enriched, "damage", _damage_key)

    # Scalar fields: simple add-if-missing
    for field in ENRICHMENT_FIELDS:
        if field in ("saving_throw", "area", "damage"):
            continue
        if field in enriched and field not in ability:
            ability[field] = enriched[field]


def _apply_uma_from_db(ability, main_curs, edition=None):
    """Wire up universal_monster_ability from the monster abilities DB.

    If the ability is flagged as a UMA in the enrichment DB but doesn't
    already have the universal_monster_ability object, look it up and attach it.
    """
    if "universal_monster_ability" in ability:
        return  # Already wired (e.g., from HTML link detection)

    results = fetch_monster_abilities_by_name(main_curs, ability["name"])
    if not results:
        return

    # Pick best match by edition
    data = results[0]
    if len(results) > 1 and edition:
        for r in results:
            ability_json = json.loads(r["monster_ability"])
            if ability_json.get("edition") == edition:
                data = r
                break

    db_ability = json.loads(data["monster_ability"])
    # Strip metadata that doesn't belong on a nested object
    for key in ("schema_version", "license"):
        db_ability.pop(key, None)
    # Strip trait templates
    if "traits" in db_ability:
        db_ability["traits"] = [
            t for t in db_ability["traits"] if t.get("type") != "trait_template"
        ]
        for trait in db_ability["traits"]:
            for key in ("schema_version",):
                trait.pop(key, None)

    ability["universal_monster_ability"] = db_ability


# Names that are result blocks or affliction stages, not standalone abilities.
# These should not receive ability_category even if they appear in the
# abilities array (parser bug — they should be nested in their parent).
_NOT_CATEGORIZABLE = {
    "Critical Success",
    "Success",
    "Failure",
    "Critical Failure",
}


def _is_stage_name(name):
    """Check if a name looks like an affliction stage (Stage 1, Stage 2, etc.)."""
    return bool(re.match(r"^Stage \d+$", name))


def _enrich_abilities(abilities, conn, edition=None):
    """Core enrichment loop: insert/update records and merge enriched data.

    Works for any list of ability dicts regardless of source (creature,
    monster family, monster template).

    Merges:
    - enriched_json fields (saving_throw, damage, area, range, frequency)
    - ability_category from classification
    - universal_monster_ability from monster abilities DB (for UMAs)
    """
    curs = conn.cursor()

    # Lazily open main DB only if UMA lookup is needed
    main_conn = None
    main_curs = None

    try:
        for ability in abilities:
            if ability.get("subtype") != "ability":
                continue

            # Deterministic category from action type — no DB/LLM needed
            det_cat = deterministic_ability_category(ability)
            if det_cat:
                ability["ability_category"] = det_cat

            identity_hash = compute_identity_hash(ability)
            raw_json = ability_to_raw_json(ability)

            existing = fetch_ability_by_hash(curs, identity_hash)

            if existing is None:
                ability_id = insert_ability_record(curs, ability["name"], identity_hash, raw_json)
                # Inline enrich new records so enrichment is
                # available on this same parser run
                enriched = _try_inline_enrich(curs, ability_id, raw_json)
                if enriched:
                    _merge_enrichment(ability, enriched)
            else:
                ability_id = existing["ability_id"]
                now_stale = existing["stale"]
                if existing["raw_json"] != raw_json:
                    if _raws_equivalent(existing["raw_json"], raw_json):
                        # Links/whitespace-only drift: identity AND mechanics
                        # unchanged, enrichment stays valid. Refresh without
                        # staling — two sources sharing a record (legacy +
                        # remastered family files with different link
                        # targets) otherwise re-stale it on every parse,
                        # permanently disabling the merge for both
                        # (ghost/skeleton/nosferatu lost frequency/range).
                        refresh_raw_json(curs, ability_id, raw_json)
                    else:
                        # Hash-excluded mechanics drifted (e.g. errata to an
                        # addon-line saving throw DC): the enriched copy is
                        # genuinely outdated — stale it for re-enrichment.
                        mark_stale(curs, ability_id, raw_json)
                        now_stale = True

                # Apply enrichment
                if existing["enriched_json"] and not now_stale:
                    _merge_enrichment(ability, existing["enriched_json"])
                elif now_stale or not existing["enriched_json"]:
                    # Stale or unenriched — re-enrich inline
                    enriched = _try_inline_enrich(curs, ability_id, raw_json)
                    if enriched:
                        _merge_enrichment(ability, enriched)

                # Apply ability_category from DB (skip result blocks/stages,
                # and skip if already set deterministically above)
                name = ability.get("name", "")
                is_real_ability = name not in _NOT_CATEGORIZABLE and not _is_stage_name(name)
                if is_real_ability and "ability_category" not in ability:
                    if existing.get("ability_category"):
                        ability["ability_category"] = existing["ability_category"]

                # Wire up UMA from monster abilities DB
                if is_real_ability and existing.get("is_uma"):
                    if main_conn is None:
                        db_path = get_db_path("pfsrd2.db")
                        main_conn = get_db_connection(db_path)
                        main_curs = main_conn.cursor()
                    _apply_uma_from_db(ability, main_curs, edition=edition)
    finally:
        if main_conn is not None:
            main_conn.close()


def ability_enrichment_pass(struct, conn=None):
    """Populate the enrichment DB and apply enrichments to abilities.

    First run: inserts raw records + creature links (no output changes).
    Subsequent runs: if enriched data exists and isn't stale, merges
    structured fields into the ability objects.

    If conn is provided, uses it (caller manages lifecycle).
    Otherwise opens and closes its own connection.
    """
    meta = _get_creature_metadata(struct)
    owns_conn = conn is None
    if owns_conn:
        conn = get_enrichment_db_connection()
    edition = struct.get("edition")

    # Lazily open main DB only if UMA lookup is needed
    main_conn = None
    main_curs = None

    try:
        curs = conn.cursor()
        for category, ability in _walk_abilities(struct):
            identity_hash = compute_identity_hash(ability)
            raw_json = ability_to_raw_json(ability)

            existing = fetch_ability_by_hash(curs, identity_hash)

            if existing is None:
                ability_id = insert_ability_record(curs, ability["name"], identity_hash, raw_json)
                # Inline enrich new records
                enriched = _try_inline_enrich(curs, ability_id, raw_json)
                if enriched:
                    _merge_enrichment(ability, enriched)
            else:
                ability_id = existing["ability_id"]
                now_stale = existing["stale"]
                if existing["raw_json"] != raw_json:
                    if _raws_equivalent(existing["raw_json"], raw_json):
                        # Links/whitespace-only drift: identity AND mechanics
                        # unchanged, enrichment stays valid. Refresh without
                        # staling — two sources sharing a record (legacy +
                        # remastered family files with different link
                        # targets) otherwise re-stale it on every parse,
                        # permanently disabling the merge for both
                        # (ghost/skeleton/nosferatu lost frequency/range).
                        refresh_raw_json(curs, ability_id, raw_json)
                    else:
                        # Hash-excluded mechanics drifted (e.g. errata to an
                        # addon-line saving throw DC): the enriched copy is
                        # genuinely outdated — stale it for re-enrichment.
                        mark_stale(curs, ability_id, raw_json)
                        now_stale = True

                # Apply enrichment
                if existing["enriched_json"] and not now_stale:
                    _merge_enrichment(ability, existing["enriched_json"])
                elif now_stale or not existing["enriched_json"]:
                    # Stale or unenriched — re-enrich inline (regex + LLM)
                    enriched = _try_inline_enrich(curs, ability_id, raw_json)
                    if enriched:
                        _merge_enrichment(ability, enriched)

                # Wire up UMA from monster abilities DB
                if existing.get("is_uma"):
                    if main_conn is None:
                        db_path = get_db_path("pfsrd2.db")
                        main_conn = get_db_connection(db_path)
                        main_curs = main_conn.cursor()
                    _apply_uma_from_db(ability, main_curs, edition=edition)

            insert_creature_link(
                curs,
                ability_id,
                meta["creature_game_id"],
                meta["creature_name"],
                meta["creature_level"],
                meta["creature_traits"],
                meta["source_name"],
                category,
            )

        conn.commit()
    finally:
        if main_conn is not None:
            main_conn.close()
        if owns_conn:
            conn.close()


def _walk_all_abilities(struct):
    """Walk all abilities in any struct type (family, template, creature).

    Yields ability dicts from changes[].abilities[] arrays found
    anywhere in the structure. Does NOT recurse into ability objects
    themselves — nested children like result blocks (Critical Success,
    Failure) and affliction stages are not standalone abilities.
    """
    if isinstance(struct, dict):
        # Direct abilities array on this object
        for ability in struct.get("abilities", []):
            if isinstance(ability, dict) and ability.get("subtype") == "ability":
                yield ability
                # Don't recurse into the ability — its children aren't
                # standalone abilities
        # Recurse into all dict/list values EXCEPT abilities (handled above)
        # and fields that are nested inside abilities
        for key, value in struct.items():
            if key in (
                "abilities",
                "stages",
                "universal_monster_ability",
                *DEGREE_FIELDS,
            ):
                continue
            yield from _walk_all_abilities(value)
    elif isinstance(struct, list):
        for item in struct:
            yield from _walk_all_abilities(item)


def template_ability_enrichment_pass(struct, conn=None):
    """Enrichment pass for monster family and monster template abilities.

    Same as ability_enrichment_pass but walks the template/family
    structure instead of creature stat blocks. No creature links are
    created — these abilities describe what to add to a creature, not
    a creature's own abilities.

    Merges ability_category, UMA data, and enriched fields.
    """
    edition = struct.get("edition")
    owns_conn = conn is None
    if owns_conn:
        conn = get_enrichment_db_connection()
    try:
        abilities = list(_walk_all_abilities(struct))
        _enrich_abilities(abilities, conn, edition=edition)
        conn.commit()
    finally:
        if owns_conn:
            conn.close()
