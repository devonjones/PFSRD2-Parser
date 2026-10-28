"""Seed git-stored enrichment overrides into the enrichment DB.

The overrides/ directory is the durable, reviewed record of hand-verified
enrichments — enrichment content that regex extraction cannot produce
(conditional chains, level-banded values, add_strike/select encodings).
The enrichment DB is disposable working state, so these are seeded (idempotently)
as extraction_method='manual', human_verified=1 during the cold-start cycle:

    parse (stages raw records) -> pf2_enrich_changes -> pf2_seed_change_overrides
    -> re-parse (merges enrichment into output JSON)

A change override that matches no record is reported as a miss: the source
text changed (AoN errata or an HTML fix), so the override is stale and must
be re-reviewed — never silently skipped.
"""

import json
import os
import sys

from pfsrd2.ability_placement import CATEGORY_TARGETS
from pfsrd2.change_identity import compute_change_hash
from pfsrd2.enrichment.change_extractor import (
    ENRICHMENT_VERSION,
    TraitLookupError,
    canonicalize_trait_effects,
)
from pfsrd2.enrichment.regex_extractor import ENRICHMENT_VERSION as ABILITY_ENRICHMENT_VERSION
from pfsrd2.sql.enrichment import (
    clear_change_needs_review,
    clear_needs_review,
    fetch_change_by_hash,
    mark_change_human_verified,
    mark_human_verified,
    update_ability_category,
    update_change_enriched_json,
    update_enriched_json,
)

OVERRIDES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "overrides")


def load_overrides(filename, overrides_dir=None, key="overrides"):
    path = os.path.join(overrides_dir or OVERRIDES_DIR, filename)
    if not os.path.exists(path):
        # Both override files are committed and loaded by hardcoded name — a
        # missing file means a broken checkout or a typo'd name, and silently
        # returning [] would no-op the entire hand-verified seeding step.
        raise FileNotFoundError(f"Overrides file missing: {path}")
    with open(path, encoding="utf-8") as fp:
        doc = json.load(fp)
    if key == "overrides":
        # mandatory: a file without it is malformed, not empty
        return doc["overrides"]
    # secondary keys ("quarantines") are optional — absent means none defined
    return doc.get(key, [])


def _traits_db_empty():
    """True when the main pfsrd2.db has no traits (CI / fresh checkout)."""
    try:
        from universal.universal import get_db_connection, get_db_path

        conn = get_db_connection(get_db_path("pfsrd2.db"))
        try:
            curs = conn.cursor()
            curs.execute("SELECT COUNT(*) AS n FROM traits")
            row = curs.fetchone()
            n = row["n"] if isinstance(row, dict) else row[0]
            return not n
        finally:
            conn.close()
    except Exception:
        return True


def seed_change_overrides(curs, overrides):
    """Seed change enrichment overrides. Returns (seeded_count, misses)."""
    seeded = 0
    misses = []
    for ov in overrides:
        identity_hash = compute_change_hash(ov["source_name"], ov["source_type"], ov["change_text"])
        record = fetch_change_by_hash(curs, identity_hash)
        if record is None:
            misses.append(ov)
            continue
        enriched = dict(ov["enriched"])
        if enriched.get("effects"):
            # unknown trait names become misses, not a mid-seed crash
            # same trait canonicalization as the regex extractor: type-list
            # adds mirror into the badge array with canonical trait objects,
            # name-only badge adds get upgraded (see canonicalize_trait_effects)
            try:
                enriched["effects"] = canonicalize_trait_effects(enriched["effects"])
            except TraitLookupError as exc:
                if _traits_db_empty():
                    # No traits DB in this environment (CI subprocess, fresh
                    # checkout): seed the override verbatim — real pipeline
                    # runs have the DB and canonicalize.
                    sys.stderr.write(
                        f"WARNING: traits DB empty — seeding override verbatim "
                        f"(no badge canonicalization): {ov['change_text'][:60]!r}\n"
                    )
                else:
                    ov = dict(ov, change_text=f"{ov['change_text']} [unknown trait: {exc}]")
                    misses.append(ov)
                    continue
        enriched_json = json.dumps(enriched, sort_keys=True, ensure_ascii=False)
        update_change_enriched_json(
            curs, record["change_id"], enriched_json, ENRICHMENT_VERSION, "manual"
        )
        mark_change_human_verified(curs, record["change_id"])
        clear_change_needs_review(curs, record["change_id"])
        seeded += 1
    return seeded, misses


# The fields enrichment writes onto an ability (ability_enrichment.ENRICHMENT_FIELDS,
# not imported: that module imports the parser stack).
_ABILITY_FIELDS = {"saving_throw", "damage", "area", "range", "frequency"}


def seed_ability_field_overrides(curs, overrides):
    """Seed hand-verified enrichment FIELDS onto ability records.

    For one-offs the extractors cannot get right (PFSRD2-Parser-4pw0: Bola
    Hurl's "nonlethal bludgeoning", Ekriathe's Breath's chosen save). Keyed on
    name AND exact ability text, as change overrides key on their text: an AoN
    errata makes the entry a miss to re-review, never a silent apply to text
    nobody checked. Only the listed fields are replaced.
    Returns (seeded_count, misses).
    """
    seeded = 0
    misses = []
    for ov in overrides:
        fields = ov["enriched"]
        assert set(fields) <= _ABILITY_FIELDS, (
            f"Override {ov['name']!r} sets {sorted(set(fields) - _ABILITY_FIELDS)}, "
            f"which enrichment never writes. Allowed: {sorted(_ABILITY_FIELDS)}"
        )
        curs.execute(
            "SELECT ability_id, raw_json, enriched_json FROM ability_records"
            " WHERE LOWER(name) = LOWER(?) AND json_extract(raw_json, '$.text') = ?",
            (ov["name"], ov["text"]),
        )
        rows = curs.fetchall()
        if not rows:
            misses.append(ov)
            continue
        for row in rows:
            enriched = json.loads(row["enriched_json"] or row["raw_json"])
            enriched.update(fields)
            update_enriched_json(
                curs,
                row["ability_id"],
                json.dumps(enriched, sort_keys=True, ensure_ascii=False),
                ABILITY_ENRICHMENT_VERSION,
                "manual",
            )
            mark_human_verified(curs, row["ability_id"])
            clear_needs_review(curs, row["ability_id"])
        seeded += 1
    return seeded, misses


def seed_change_quarantines(curs, quarantines):
    """Seed documented quarantines: rules text that is deliberately NOT
    machine-encoded (GM-judgment removals, spell-list encodings pending).

    Sets needs_review=1 with the override's distinct reason so the review
    queue shows an audited disposition instead of a raw unknown_category.
    Returns (seeded_count, misses).
    """
    seeded = 0
    misses = []
    for qv in quarantines:
        identity_hash = compute_change_hash(qv["source_name"], qv["source_type"], qv["change_text"])
        record = fetch_change_by_hash(curs, identity_hash)
        if record is None:
            misses.append(qv)
            continue
        curs.execute(
            "UPDATE change_records SET needs_review = 1, review_reason = ?" " WHERE change_id = ?",
            (f"quarantine: {qv['reason']}", record["change_id"]),
        )
        seeded += 1
    return seeded, misses


def seed_ability_overrides(curs, overrides):
    """Seed ability_category overrides, name-keyed (case-insensitive).

    Updates every record variant sharing the name — legacy/remastered
    editions of the same ability get the same category.
    Returns (seeded_count, misses).
    """
    seeded = 0
    misses = []
    for ov in overrides:
        category = ov["ability_category"]
        assert category in CATEGORY_TARGETS, (
            f"Invalid ability category {category!r} for override {ov['name']!r}. "
            f"Must be one of: {sorted(CATEGORY_TARGETS)}"
        )
        curs.execute(
            "SELECT ability_id FROM ability_records WHERE LOWER(name) = LOWER(?)",
            (ov["name"],),
        )
        rows = curs.fetchall()
        if not rows:
            misses.append(ov)
            continue
        for row in rows:
            update_ability_category(curs, row["ability_id"], category)
            mark_human_verified(curs, row["ability_id"])
        seeded += 1
    return seeded, misses
