"""Look up ability placement category from the enrichment DB.

When a template adds abilities, this module determines where each ability
belongs in the creature schema by checking what category the same ability
appears in across existing creatures.
"""

from pfsrd2.sql.enrichment import get_enrichment_db_connection

# Mapping from enrichment DB category to the JSONPath target in the creature schema
CATEGORY_TARGETS = {
    "automatic": "$.defense.automatic_abilities",
    "reactive": "$.defense.reactive_abilities",
    "hp_automatic": "$.defense.hitpoints[*].automatic_abilities",
    "interaction": "$.stat_block.interaction_abilities",
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


def ability_target(ability):
    """Pick the schema target for an ability using action_type, then DB history.

    Returns a JSONPath string from CATEGORY_TARGETS, or DEFAULT_TARGET if the
    ability's category can't be determined.
    """
    category = deterministic_ability_category(ability)
    if category:
        return CATEGORY_TARGETS.get(category, DEFAULT_TARGET)
    name = ability.get("name")
    if not name:
        return DEFAULT_TARGET
    _, target = lookup_ability_category(name)
    return target


def lookup_ability_category(ability_name, conn=None):
    """Look up the most common category for an ability by name.

    Returns (category, target) where category is the enrichment DB category
    and target is the JSONPath in the creature schema. Returns (None, DEFAULT_TARGET)
    if the ability is not found.

    Case-insensitive lookup. When an ability appears in multiple categories,
    returns the most common one.
    """
    close_conn = False
    if conn is None:
        conn = get_enrichment_db_connection()
        close_conn = True
    try:
        curs = conn.cursor()
        curs.execute(
            "SELECT acl.ability_category, COUNT(*) as cnt "
            "FROM ability_records ar "
            "JOIN ability_creature_links acl ON ar.ability_id = acl.ability_id "
            "WHERE LOWER(ar.name) = LOWER(?) "
            "GROUP BY acl.ability_category "
            "ORDER BY cnt DESC",
            (ability_name,),
        )
        rows = curs.fetchall()
        if rows:
            category = rows[0]["ability_category"]
            target = CATEGORY_TARGETS.get(category, DEFAULT_TARGET)
            return category, target
        return None, DEFAULT_TARGET
    finally:
        if close_conn:
            conn.close()


def lookup_ability_categories(ability_names, conn=None):
    """Batch lookup for multiple ability names.

    Returns a dict of {name: (category, target)} for each name.
    More efficient than calling lookup_ability_category repeatedly.
    """
    close_conn = False
    if conn is None:
        conn = get_enrichment_db_connection()
        close_conn = True
    try:
        result = {}
        curs = conn.cursor()
        for name in ability_names:
            curs.execute(
                "SELECT acl.ability_category, COUNT(*) as cnt "
                "FROM ability_records ar "
                "JOIN ability_creature_links acl ON ar.ability_id = acl.ability_id "
                "WHERE LOWER(ar.name) = LOWER(?) "
                "GROUP BY acl.ability_category "
                "ORDER BY cnt DESC",
                (name,),
            )
            rows = curs.fetchall()
            if rows:
                category = rows[0]["ability_category"]
                target = CATEGORY_TARGETS.get(category, DEFAULT_TARGET)
                result[name] = (category, target)
            else:
                result[name] = (None, DEFAULT_TARGET)
        return result
    finally:
        if close_conn:
            conn.close()
