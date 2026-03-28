"""Universal monster ability database pass.

Walks a struct looking for abilities that link to MonsterAbilities.aspx
and enriches them with the full DB record (game-id, traits, etc.).

Used by: creature, monster family, and monster template parsers.
"""

import json
import sys

from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.monster_abilities import fetch_monster_abilities_by_name
from universal.universal import test_key_is_value, walk

EXPECTED_MONSTER_ABILITY_SCHEMA_VERSION = 1.2


def monster_ability_db_pass(struct, edition=None, fxn_handle_trait_template=None):
    """Enrich abilities with universal monster ability data from the DB.

    Walks all abilities in the struct. For each ability whose link points
    to MonsterAbilities, looks it up in the DB and sets the
    universal_monster_ability field with the full record.

    Args:
        struct: The parsed structure to walk
        edition: Target edition ("legacy" or "remastered") for picking
                 the best match. If None, uses struct.get("edition").
        fxn_handle_trait_template: Optional callback(curs, ability, db_ability)
            for substituting trait templates. If None, trait templates are
            simply stripped. Creatures pass a function that replaces
            [Magical Tradition] with the creature's actual tradition trait.
    """
    target_edition = edition or struct.get("edition")

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()

        def _check_ability(ability, parent):
            name = ability.get("name", "")
            if not name:
                return

            # Always look up by name — creature abilities may not have
            # MonsterAbilities links in HTML but are still UMAs
            abilities = fetch_monster_abilities_by_name(curs, name)
            data = _pick_best_ability(abilities, target_edition)
            if data:
                db_ability = json.loads(data["monster_ability"])
                # Assert expected schema version before stripping
                sv = db_ability.pop("schema_version", None)
                assert sv is None or sv <= EXPECTED_MONSTER_ABILITY_SCHEMA_VERSION, (
                    f"Monster ability schema version {sv} > expected "
                    f"{EXPECTED_MONSTER_ABILITY_SCHEMA_VERSION} for {name}"
                )
                # Keep "license" — license_consolidation_pass needs it.
                # Handle trait templates — either substitute or strip
                if "traits" in db_ability:
                    if fxn_handle_trait_template:
                        fxn_handle_trait_template(curs, ability, db_ability)
                    else:
                        # Strip trait templates with warning for unknown types
                        templates = [
                            t for t in db_ability["traits"] if t.get("type") == "trait_template"
                        ]
                        for t in templates:
                            sys.stderr.write(
                                f"WARNING: stripping trait_template "
                                f"'{t.get('name', '?')}' from UMA "
                                f"'{name}' (no handler provided)\n"
                            )
                        db_ability["traits"] = [
                            t for t in db_ability["traits"] if t.get("type") != "trait_template"
                        ]
                    # Strip metadata from nested traits
                    for trait in db_ability["traits"]:
                        trait.pop("schema_version", None)
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

    # No exact match — warn and return first one
    names = [json.loads(a["monster_ability"]).get("name", "?") for a in abilities]
    sys.stderr.write(
        f"WARNING: _pick_best_ability: no edition match for {names[0]} "
        f"(target={target_edition}), using first of {len(abilities)}\n"
    )
    return abilities[0]
