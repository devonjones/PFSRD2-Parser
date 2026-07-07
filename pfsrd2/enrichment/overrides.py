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

from pfsrd2.change_identity import compute_change_hash
from pfsrd2.enrichment.change_extractor import ENRICHMENT_VERSION
from pfsrd2.sql.enrichment import (
    clear_change_needs_review,
    fetch_change_by_hash,
    mark_change_human_verified,
    update_change_enriched_json,
)

OVERRIDES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "overrides")


def load_overrides(filename, overrides_dir=None):
    path = os.path.join(overrides_dir or OVERRIDES_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path) as fp:
        return json.load(fp)["overrides"]


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
        enriched_json = json.dumps(ov["enriched"], sort_keys=True)
        update_change_enriched_json(
            curs, record["change_id"], enriched_json, ENRICHMENT_VERSION, "manual"
        )
        mark_change_human_verified(curs, record["change_id"])
        clear_change_needs_review(curs, record["change_id"])
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
        curs.execute(
            "SELECT ability_id FROM ability_records WHERE LOWER(name) = LOWER(?)",
            (ov["name"],),
        )
        rows = curs.fetchall()
        if not rows:
            misses.append(ov)
            continue
        for row in rows:
            curs.execute(
                "UPDATE ability_records"
                " SET ability_category = ?, human_verified = 1"
                " WHERE ability_id = ?",
                (ov["ability_category"], row["ability_id"]),
            )
        seeded += 1
    return seeded, misses
