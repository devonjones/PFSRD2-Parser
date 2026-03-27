"""Universal monster ability database pass.

Walks a struct looking for abilities that link to MonsterAbilities.aspx
and enriches them with the full DB record (game-id, traits, etc.).

Used by: creature, monster family, and monster template parsers.
"""

import json
import sys

from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.monster_abilities import fetch_monster_abilities_by_name
from universal.universal import walk, test_key_is_value


def monster_ability_db_pass(struct, edition=None):
    """Enrich abilities with universal monster ability data from the DB.

    Walks all abilities in the struct. For each ability whose link points
    to MonsterAbilities, looks it up in the DB and sets the
    universal_monster_ability field with the full record.

    Args:
        struct: The parsed structure to walk
        edition: Target edition ("legacy" or "remastered") for picking
                 the best match. If None, uses struct.get("edition").
    """
    target_edition = edition or struct.get("edition")

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()

        def _check_ability(ability, parent):
            # Check if this ability should be a UMA:
            # 1. Has a link to MonsterAbilities (from HTML)
            # 2. Has a universal_monster_ability skeleton (from parser detection)
            # 3. Has a link on it at all with game-obj MonsterAbilities
            should_check = False
            link = ability.get("link")
            if link and link.get("game-obj") == "MonsterAbilities":
                should_check = True
            uma = ability.get("universal_monster_ability")
            if uma:
                should_check = True
            # Also check links array (link may have been moved there)
            for lnk in ability.get("links", []):
                if lnk.get("game-obj") == "MonsterAbilities":
                    should_check = True
                    break

            if not should_check:
                return

            name = ability.get("name", "")
            if not name:
                return

            abilities = fetch_monster_abilities_by_name(curs, name)
            data = _pick_best_ability(abilities, target_edition)
            if data:
                db_ability = json.loads(data["monster_ability"])
                # Strip metadata that doesn't belong on a nested object
                for key in ("schema_version", "license"):
                    db_ability.pop(key, None)
                # Strip metadata from nested traits and remove trait templates
                if "traits" in db_ability:
                    db_ability["traits"] = [
                        t for t in db_ability["traits"] if t.get("type") != "trait_template"
                    ]
                    for trait in db_ability["traits"]:
                        for key in ("schema_version",):
                            trait.pop(key, None)
                ability["universal_monster_ability"] = db_ability
            elif ability.get("universal_monster_ability"):
                # DB didn't find it — remove the incomplete skeleton
                del ability["universal_monster_ability"]

        walk(struct, test_key_is_value("subtype", "ability"), _check_ability)


def _pick_best_ability(abilities, target_edition):
    """Pick the ability that best matches the target edition."""
    if not abilities:
        return None
    if len(abilities) == 1:
        return abilities[0]

    # Parse all abilities and find edition matches
    for ability_row in abilities:
        ability_json = json.loads(ability_row["monster_ability"])
        if ability_json.get("edition") == target_edition:
            return ability_row

    # No exact match — return first one
    return abilities[0]
