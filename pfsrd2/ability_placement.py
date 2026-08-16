"""Look up ability placement category from the enrichment DB.

When a template adds abilities, this module determines where each ability
belongs in the creature schema by checking what category the same ability
appears in across existing creatures.
"""

from pfsrd2.sql.enrichment import get_enrichment_db_connection
from pfsrd2.sql.enrichment.queries import fetch_majority_category_for_name

# Mapping from enrichment DB category to the JSONPath target in the creature schema
CATEGORY_TARGETS = {
    "automatic": "$.defense.automatic_abilities",
    "reactive": "$.defense.reactive_abilities",
    "hp_automatic": "$.defense.hitpoints[*].automatic_abilities",
    "interaction": "$.interaction_abilities",
    "communication": "$.statistics.languages.communication_abilities",
    "offensive": "$.offense.offensive_actions",
    "special_sense": "$.senses.special_senses",
}

# Default target when ability is not found in the DB
DEFAULT_TARGET = "$.defense.automatic_abilities"


def deterministic_ability_category(ability):
    """Infer an ability's category from its action_type alone.

    Reactions are always reactive. 1/2/3-action abilities are always
    offensive. Free actions with a trigger are reactive. Returns the
    category string, or None if it can't be determined from action_type.
    """
    action_type = ability.get("action_type")
    if not isinstance(action_type, dict):
        return None
    action_name = action_type.get("name", "")
    if action_name == "Reaction":
        return "reactive"
    if action_name in ("One Action", "Two Actions", "Three Actions"):
        return "offensive"
    if action_name == "Free Action" and ability.get("trigger"):
        return "reactive"
    return None


def _target_for(category, name):
    """Map a category to its schema target, refusing to guess.

    The fallback this replaces could only fire when someone added a category
    without adding its mapping — it existed solely to hide that, and it hid it
    by routing a whole category into DEFAULT_TARGET where it reads as a real
    placement decision. Every category the enrichment DB actually holds is a
    key here (verified: 7 for 7).
    """
    assert category in CATEGORY_TARGETS, (
        f"Ability {name!r} is filed under category {category!r}, which has no "
        f"CATEGORY_TARGETS entry — it would be routed to {DEFAULT_TARGET} and "
        "look like a real placement decision"
    )
    return CATEGORY_TARGETS[category]


def ability_target(ability):
    """Pick the schema target for an ability using action_type, then DB history.

    A nameless ability is a parser bug — assert rather than silently return a
    default. The assert comes first: the only production caller already
    guarantees a name, so accepting a nameless ability on the action_type path
    was a gap rather than a feature.
    """
    name = ability.get("name")
    assert name, f"Ability missing required 'name' field: {ability!r}"
    category = deterministic_ability_category(ability)
    if category:
        return _target_for(category, name)
    _, target = lookup_ability_category(name)
    return target


def lookup_ability_category(ability_name, conn=None):
    """Look up the most common category for an ability by name.

    Returns (category, target), or (None, DEFAULT_TARGET) when no creature has
    this ability yet — a template may legitimately name one, so that is normal
    input rather than a data error.

    The query lives in queries.fetch_majority_category_for_name. This module
    used to carry its own copy, and the batch form below carried a third, so
    the three could drift apart silently.
    """
    close_conn = False
    if conn is None:
        conn = get_enrichment_db_connection()
        close_conn = True
    try:
        row = fetch_majority_category_for_name(conn.cursor(), ability_name)
        if row is None:
            return None, DEFAULT_TARGET
        return row[0], _target_for(row[0], ability_name)
    finally:
        if close_conn:
            conn.close()


def lookup_ability_categories(ability_names, conn=None):
    """Batch lookup. Returns {name: (category, target)} for every name asked."""
    close_conn = False
    if conn is None:
        conn = get_enrichment_db_connection()
        close_conn = True
    try:
        curs = conn.cursor()
        result = {}
        for name in ability_names:
            row = fetch_majority_category_for_name(curs, name)
            result[name] = (
                (None, DEFAULT_TARGET) if row is None else (row[0], _target_for(row[0], name))
            )
        return result
    finally:
        if close_conn:
            conn.close()
