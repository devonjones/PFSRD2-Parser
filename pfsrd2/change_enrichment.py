"""Change enrichment pass for template/family parser pipelines.

Populates the enrichment DB with raw change records from template/family
construction instructions. When enriched data exists (from the offline
enrichment pipeline), merges it back into the change objects.

The base parser is only responsible for:
1. Identifying sections with construction instructions
2. Extracting raw change text from <li> elements
3. Calling this pass to populate/merge enrichment data

All rule extraction (categorization, effect building) happens in the
offline enrichment pipeline, not in the parser.
"""

import json

from pfsrd2.change_identity import change_to_raw_json, compute_change_hash
from pfsrd2.sql.enrichment import (
    fetch_change_by_hash,
    get_enrichment_db_connection,
    insert_change_record,
    mark_change_stale,
)

# Fields that enrichment adds to a change object
ENRICHMENT_FIELDS = ("change_category", "effects")


def change_enrichment_pass(struct, source_type):
    """Populate enrichment DB and merge enriched data for change objects.

    Args:
        struct: The top-level parsed structure (monster_template or monster_family)
        source_type: "monster_template" or "monster_family"
    """
    obj_key = source_type  # "monster_template" or "monster_family"
    obj = struct.get(obj_key)
    if not obj:
        return
    # Use the object's name (clean, after link extraction) not struct["name"]
    # which may still have HTML link tags at this point in the pipeline
    source_name = obj.get("name", struct.get("name", ""))

    adjustments = obj.get("adjustments")

    conn = get_enrichment_db_connection()
    curs = conn.cursor()
    try:
        # Process top-level changes
        _process_changes(curs, obj.get("changes", []), source_name, source_type, adjustments)

        # Process subtype changes (monster_family subtypes)
        for subtype in obj.get("subtypes", []):
            subtype_name = f"{source_name} :: {subtype.get('name', '')}"
            _process_changes(curs, subtype.get("changes", []), subtype_name, source_type, adjustments)
            for child in subtype.get("subtypes", []):
                child_name = f"{source_name} :: {child.get('name', '')}"
                _process_changes(curs, child.get("changes", []), child_name, source_type, adjustments)

        conn.commit()
    finally:
        curs.close()
        conn.close()


def _process_changes(curs, changes, source_name, source_type, adjustments=None):
    """Process a list of change objects: populate DB and merge enrichments."""
    for change in changes:
        text = change.get("text", "")
        if not text.strip():
            continue

        identity_hash = compute_change_hash(source_name, source_type, text)
        # Include adjustments context in raw_json so enrichment can use them
        store_obj = dict(change)
        if adjustments:
            store_obj["_adjustments"] = adjustments
        raw_json = change_to_raw_json(store_obj)

        existing = fetch_change_by_hash(curs, identity_hash)
        if existing:
            # Check if source text changed (shouldn't happen with same hash, but
            # handle raw_json changes from link extraction etc.)
            if existing["stale"]:
                pass  # Already marked stale, skip
            # If enriched and not stale, merge enrichment back
            if existing["enriched_json"] and not existing["stale"]:
                _merge_enrichment(change, existing["enriched_json"])
        else:
            # New change — insert raw record
            insert_change_record(curs, source_name, source_type, identity_hash, raw_json)


def _merge_enrichment(change, enriched_json_str):
    """Merge enriched fields into a change object.

    Enrichment adds change_category and effects. Text is never modified.
    """
    enriched = json.loads(enriched_json_str)
    for field in ENRICHMENT_FIELDS:
        if field in enriched and field not in change:
            change[field] = enriched[field]
