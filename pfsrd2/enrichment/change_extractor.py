"""Regex-based change enrichment extractor.

Applies categorization and effect building to raw change records
in the enrichment DB. This is the code that was formerly inline
in the monster_template parser pipeline.
"""

import json
import re

from universal.universal import build_object


ENRICHMENT_VERSION = 8

# HTML says "land Speed" but creature data uses "walk" for walking speed
_MOVEMENT_TYPE_NORMALIZE = {"land": "walk"}


def enrich_change(raw_json_str, source_name):
    """Enrich a single change record.

    Args:
        raw_json_str: JSON string of the raw change object
        source_name: The template/family name (for context)

    Returns:
        (enriched_json_str, extraction_method) or (None, None) if no enrichment possible
    """
    change = json.loads(raw_json_str)
    text = change.get("text", "")
    if not text.strip():
        return None, None

    # Adjustments table context (stored by population pass)
    adjustments = change.get("_adjustments")

    category = _categorize_change_text(text)
    if category == "unknown":
        return None, None

    enriched = {
        "change_category": category,
    }

    effects = _build_effects(text, category, source_name, adjustments)
    if effects:
        enriched["effects"] = effects

    return json.dumps(enriched, sort_keys=True, ensure_ascii=False), "regex"


def _categorize_change_text(text):
    """Auto-categorize a change based on its text content."""
    t = text.lower()
    if not t.strip():
        return "unknown"
    # Order matters — more specific patterns first
    if "following abilit" in t or "following optional abilit" in t:
        return "abilities"
    if any(w in t for w in ["darkvision", "low-light vision", "scent", "tremorsense"]):
        return "senses"
    if "trait" in t and (
        "add the" in t
        or "replace the" in t
        or "gains the" in t
        or "gain the" in t
        or "and plant trait" in t
        or "loses the" in t
        or "rarity" in t
    ):
        return "traits"
    if "immunit" in t:
        return "immunities"
    if "weakness" in t:
        return "weaknesses"
    if "resistance" in t:
        return "resistances"
    if "language" in t:
        return "languages"
    # Check combat_stats before hit_points since some changes mention both
    if (
        ("ac" in t or "attack" in t or "saving throw" in t)
        and ("increase" in t or "decrease" in t)
        and ("hp" in t or "hit point" in t)
    ):
        return "combat_stats"
    if "hit point" in t or " hp " in t or "\u2019s hp" in t or "'s hp" in t or t.endswith("hp"):
        return "hit_points"
    if "speed" in t and (
        "fly" in t
        or "swim" in t
        or "burrow" in t
        or "climb" in t
        or "change" in t
        or "highest" in t
        or "gains" in t
        or "increase" in t
        or "decrease" in t
        or "reduce" in t
    ):
        return "speed"
    if ("ac" in t and ("increase" in t or "decrease" in t)) or (
        "attack modifier" in t and ("increase" in t or "decrease" in t)
    ):
        return "combat_stats"
    if "damage" in t and (
        "strike" in t or "change" in t or "physical" in t or "increase" in t or "decrease" in t
    ):
        return "damage"
    if "size" in t and (
        "change" in t
        or "reduce" in t
        or "increase" in t
        or "becomes" in t
        or "one size" in t
        or "smaller" in t
    ):
        return "size"
    if (
        "creature's level" in t
        or "creature\u2019s level" in t
        or "spellcaster's level" in t
        or "spellcaster\u2019s level" in t
    ) and ("increase" in t or "decrease" in t):
        return "level"
    if (
        "perception" in t or "saving throw" in t or "fortitude" in t or "reflex" in t or "will" in t
    ) and ("increase" in t or "decrease" in t):
        return "combat_stats"
    if "skill" in t or "deception" in t or "stealth" in t or "athletics" in t:
        return "skills"
    if "spell" in t or "innate" in t or "cantrip" in t:
        return "spells"
    if (
        "strike" in t
        or "claw" in t
        or "fist" in t
        or "jaws" in t
        or "fangs" in t
        or "unarmed" in t
        or "versatile" in t
        or "reach" in t
    ):
        return "strikes"
    if "attack" in t and ("increase" in t or "decrease" in t or "modifier" in t):
        return "combat_stats"
    if "intelligence" in t or "wisdom" in t or "charisma" in t or "strength" in t:
        return "attributes"
    if "item" in t and ("remove" in t or "add" in t):
        return "gear"
    if "ability" in t and ("add" in t or "gains" in t or "paralysis" in t):
        return "abilities"
    return "unknown"


def _build_effects(text, category, source_name, adjustments=None):
    """Build effects for a categorized change."""
    t = text.lower()

    if category == "abilities":
        return [
            {
                "target": "$.defense.automatic_abilities",
                "operation": "add_items",
                "source": "$.changes[*].abilities",
            }
        ]
    elif category == "immunities":
        return _build_immunity_effects(text)
    elif category == "languages":
        return _build_language_effects(text)
    elif category == "traits":
        return _build_trait_effects(text)
    elif category == "size":
        return _build_size_effects(text)
    elif category == "senses":
        return _build_sense_effects(text)
    elif category == "attributes":
        return _build_attribute_effects(text)
    elif category == "level":
        return _build_level_effects(text)
    elif category == "combat_stats":
        return _build_combat_stat_effects(text)
    elif category == "damage":
        return _build_damage_effects(text, source_name)
    elif category == "hit_points":
        return _build_hit_points_effects(text, adjustments)
    elif category == "speed":
        return _build_speed_effects(text)
    elif category == "skills":
        return _build_skill_effects(text)
    elif category == "spells":
        return _build_spell_effects(text)
    elif category == "strikes":
        return _build_strike_effects(text)
    elif category == "weaknesses":
        return _build_weakness_effects(text, adjustments)
    elif category == "resistances":
        return _build_resistance_effects(text, adjustments)
    elif category == "gear":
        return [
            {
                "target": "$.statistics.gear",
                "operation": "select",
                "selection": {"type": "remove_n", "description": text},
            }
        ]
    return []


def _extract_names_from_text(text, after_marker):
    """Extract comma-separated names from text after a marker phrase."""
    t = text.lower()
    idx = t.find(after_marker)
    if idx < 0:
        return []
    rest = text[idx + len(after_marker):].strip()
    if ". " in rest:
        rest = rest[:rest.index(". ")]
    rest = rest.rstrip(".")
    return [n.strip().strip("*") for n in rest.split(",") if n.strip()]


def _build_immunity_effects(text):
    names = _extract_names_from_text(text, "immunities:")
    if not names:
        m = re.search(r"immunity to (\w[\w\s]*?)[\.,]", text, re.IGNORECASE)
        if m:
            names = [m.group(1).strip()]
    effects = []
    for name in names:
        effects.append(
            {
                "target": "$.defense.hitpoints[*].immunities",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "immunity", "name": name},
            }
        )
    return effects


def _build_language_effects(text):
    t = text.lower()
    effects = []
    m = re.search(r"add (?:the )?(.+?)(?:\s+language)", t)
    if m:
        lang_text = m.group(1)
        langs = re.split(r"\s+and\s+|,\s*", lang_text)
        for lang in langs:
            lang = lang.strip().title()
            if lang:
                effects.append(
                    {
                        "target": "$.statistics.languages.languages",
                        "operation": "add_item",
                        "item": {"type": "stat_block_section", "subtype": "language", "name": lang},
                    }
                )
    if not effects:
        m = re.search(r"add (\w+)\.", t)
        if m:
            cond = None
            if "if it has any languages" in t:
                cond = "$.statistics.languages.languages != null"
            eff = {
                "target": "$.statistics.languages.languages",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "language",
                    "name": m.group(1).strip().title(),
                },
            }
            if cond:
                eff["conditional"] = cond
            effects.append(eff)
    return effects


def _build_trait_effects(text):
    effects = []
    t = text.lower()

    m = re.search(r"replace the (\w+) trait with the (\w+) trait", t)
    if m:
        effects.append(
            {"target": "$.creature_type.creature_types", "operation": "remove_item", "name": m.group(1).title()}
        )
        effects.append(
            {"target": "$.creature_type.creature_types", "operation": "add_item", "name": m.group(2).title()}
        )

    m = re.search(r"add the (.+?) traits?[\.,]", t)
    if m:
        trait_text = m.group(1)
        traits = re.split(r",\s*(?:and\s+)?|\s+and\s+", trait_text)
        for trait in traits:
            trait = trait.strip()
            if trait and trait not in ("optionally the mindless",):
                effects.append(
                    {"target": "$.creature_type.creature_types", "operation": "add_item", "name": trait.title()}
                )

    if not effects:
        m = re.search(r"gains? the (.+?) traits?[,.\s]", t)
        if m:
            trait_text = m.group(1)
            traits = re.split(r",\s*(?:and\s+)?|\s+and\s+", trait_text)
            for trait in traits:
                trait = trait.strip()
                if trait and "usually" not in trait:
                    effects.append(
                        {"target": "$.creature_type.creature_types", "operation": "add_item", "name": trait.title()}
                    )

    if not effects:
        m = re.search(r"add the (\w+) trait", t)
        if m:
            effects.append(
                {"target": "$.creature_type.creature_types", "operation": "add_item", "name": m.group(1).title()}
            )

    m = re.search(r"(?:if .+?has the|remove the) (\w+) trait,?\s*remove", t)
    if m:
        effects.append(
            {
                "target": "$.creature_type.creature_types",
                "operation": "remove_item",
                "name": m.group(1).title(),
                "conditional": f"$.creature_type.creature_types[?(@ == '{m.group(1).title()}')]",
            }
        )

    if "rarity" in t and not effects:
        effects.append({"conditional": "$.creature_type.rarity == 'Common'", "target": "$.creature_type.rarity", "operation": "replace", "value": "Uncommon"})
        effects.append({"conditional": "$.creature_type.rarity == 'Uncommon'", "target": "$.creature_type.rarity", "operation": "replace", "value": "Rare"})

    m = re.search(r"replace the (.+?) traits? with the$", t)
    if m and not effects:
        for trait in re.split(r"\s+and\s+|,\s*", m.group(1)):
            effects.append({"target": "$.creature_type.creature_types", "operation": "remove_item", "name": trait.strip().title()})

    m = re.match(r"^-?\s*([\w\s,]+(?:\s+and\s+[\w\s]+)+)\s+traits?\.", t)
    if m and "replace" not in t and "add" not in t and not effects:
        for trait in re.split(r"\s+and\s+|,\s*", m.group(1)):
            effects.append({"target": "$.creature_type.creature_types", "operation": "add_item", "name": trait.strip().title()})

    m = re.search(r"loses the (\w+) trait.+?gains the (\w+) trait", t)
    if m and not effects:
        effects.append({"target": "$.creature_type.creature_types", "operation": "remove_item", "name": m.group(1).title()})
        effects.append({"target": "$.creature_type.creature_types", "operation": "add_item", "name": m.group(2).title()})

    return effects


def _build_size_effects(text):
    t = text.lower()
    m = re.search(r"(?:change size to|reduce .+ size to|becomes?) (\w+)", t)
    if m:
        return [{"target": "$.creature_type.size", "operation": "replace", "value": m.group(1).title()}]
    if "increase" in t and "size" in t and "one" in t:
        return [{"target": "$.creature_type.size", "operation": "size_increment", "value": 1}]
    return []


def _build_sense_effects(text):
    effects = []
    t = text.lower()
    if "tremorsense" in t:
        m = re.search(r"tremorsense (\d+) feet", t)
        if m:
            effects.append(
                {
                    "target": "$.senses.special_senses",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "special_sense",
                        "name": "tremorsense",
                        "range": {
                            "type": "stat_block_section",
                            "subtype": "range",
                            "text": f"{m.group(1)} feet",
                            "range": int(m.group(1)),
                            "unit": "feet",
                        },
                    },
                }
            )
    if "darkvision" in t:
        effects.append(
            {"target": "$.senses.special_senses", "operation": "add_item", "item": {"type": "stat_block_section", "subtype": "special_sense", "name": "darkvision"}}
        )
    if "low-light vision" in t:
        effects.append(
            {"target": "$.senses.special_senses", "operation": "add_item", "item": {"type": "stat_block_section", "subtype": "special_sense", "name": "low-light vision"}}
        )
    return effects


def _build_attribute_effects(text):
    t = text.lower()
    m = re.search(r"(\w+) modifier is [–-]?(\d+) or lower.+?(?:increase|set) it to [–-]?(\d+)", t)
    if m:
        attr = m.group(1).lower()
        threshold = -int(m.group(2))
        new_val = -int(m.group(3))
        return [
            {
                "conditional": f"$.creature_type.{attr}_modifier <= {threshold}",
                "target": f"$.creature_type.{attr}_modifier",
                "operation": "replace",
                "value": new_val,
            }
        ]
    effects = []
    for m in re.finditer(r"(\w+) modifier of [+–-]?(\d+)", t):
        attr = m.group(1).lower()
        prefix = t[max(0, m.start() - 3):m.start() + len(m.group(0))]
        val = int(m.group(2))
        if "–" in prefix or "-" in prefix[:prefix.find(m.group(2))]:
            val = -val
        effects.append({"target": f"$.statistics.{attr[:3]}", "operation": "replace", "value": val})
    return effects


def _build_level_effects(text):
    t = text.lower()
    m = re.search(r"(increase|decrease) the (?:creature|spellcaster)['\u2019]s level by (\d+)", t)
    if m:
        direction = 1 if m.group(1) == "increase" else -1
        value = int(m.group(2)) * direction
        return [{"target": "$.creature_type.level", "operation": "adjustment", "value": value}]
    return []


def _build_combat_stat_effects(text):
    t = text.lower()
    effects = []
    m = re.search(r"(increase|decrease).+?by (\d+)", t)
    if not m:
        return []
    direction = 1 if m.group(1) == "increase" else -1
    val = int(m.group(2)) * direction
    if "ac" in t:
        effects.append({"target": "$.defense.ac.value", "operation": "adjustment", "value": val})
    if "attack" in t:
        effects.append({"target": "$.offense.offensive_actions[*].attack.bonus.bonuses", "operation": "adjustment", "value": val})
    if "dc" in t:
        effects.append({"target": "$.offense.offensive_actions[*].spells.saving_throw.dc", "operation": "adjustment", "value": val})
        effects.append({"target": "$.defense.automatic_abilities[*].saving_throw[*].dc", "operation": "adjustment", "value": val})
        effects.append({"target": "$.defense.reactive_abilities[*].saving_throw[*].dc", "operation": "adjustment", "value": val})
        effects.append({"target": "$.offense.offensive_actions[*].ability.saving_throw[*].dc", "operation": "adjustment", "value": val})
    if "saving throw" in t:
        for save in ("fort", "ref", "will"):
            effects.append({"target": f"$.defense.saves.{save}.value", "operation": "adjustment", "value": val})
    if "perception" in t:
        effects.append({"target": "$.senses.perception.value", "operation": "adjustment", "value": val})
    if not effects:
        for save_name in ("will", "fort", "ref"):
            if save_name in t:
                effects.append({"target": f"$.defense.saves.{save_name}.value", "operation": "adjustment", "value": val})
    if "skill" in t:
        effects.append({"target": "$.statistics.skills[*].value", "operation": "adjustment", "value": val})
    return effects


def _build_damage_effects(text, source_name=""):
    t = text.lower()
    effects = []

    # "Increase/Decrease damage of Strikes by N"
    m = re.search(r"(increase|decrease) (?:the |its )?damage.+?by (\d+)", t)
    if m:
        direction = 1 if m.group(1) == "increase" else -1
        base_val = int(m.group(2)) * direction
        base_item = _damage_adjustment_item(base_val, notes=source_name or None)
        effects.append(
            {
                "conditional": "default",
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": base_item,
            }
        )
        effects.append(
            {
                "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency == null",
                "target": "$.offense.offensive_actions[*].ability.damage",
                "operation": "add_item",
                "item": base_item,
            }
        )
        m2 = re.search(r"(?:increase|decrease) the damage by (\d+) instead", t)
        if m2:
            limited_val = int(m2.group(1)) * direction
            limited_notes = f"{source_name}, limited use" if source_name else "limited use"
            limited_item = _damage_adjustment_item(limited_val, notes=limited_notes)
            effects.append(
                {
                    "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency != null",
                    "target": "$.offense.offensive_actions[*].ability.damage",
                    "operation": "add_item",
                    "item": limited_item,
                }
            )
        return effects

    if "any number" in t and "strikes" in t:
        return [{"target": "$.offense.offensive_actions[*].attack", "operation": "select", "selection": {"type": "select_n", "description": text}}]

    m = re.search(r"damage.+?changes? to (\w+) damage", t)
    if m:
        return [{"target": "$.offense.offensive_actions[*].attack.damage[*].damage_type", "operation": "replace", "value": m.group(1)}]

    m = re.search(r"(?:add|gains?) a (\w[\w\s]*?) (?:ranged |melee )?strike", t)
    if m:
        return [
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "offensive_action", "name": m.group(1).strip().title()},
                "value_from": "$.offense.offensive_actions[*].attack.damage | min",
            }
        ]

    # "Reduce the damage of Strikes by N"
    m = re.search(r"reduce the damage.+?strikes? by (\d+)", t)
    if m:
        return [
            {
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": _damage_adjustment_item(-int(m.group(1)), notes=source_name or None),
            }
        ]

    # "deal an additional 2d6 negative damage"
    m = re.search(r"deal an additional (\d+d\d+) (\w+) damage", t)
    if m:
        item = {"type": "stat_block_section", "subtype": "attack_damage", "formula": m.group(1), "damage_type": m.group(2)}
        if source_name:
            item["notes"] = source_name
        return [
            {
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": item,
            }
        ]

    # "change one die to fire damage"
    m = re.search(r"change one die to (\w+) damage", t)
    if m:
        effects.append({"target": "$.offense.offensive_actions[*].attack.damage", "operation": "replace_one_die", "value": m.group(1)})

    # "add 1 fire damage to its strikes"
    m = re.search(r"add (\d+) (\w+) damage to its strikes", t)
    if m:
        effects.append(
            {
                "conditional": "$.offense.offensive_actions[*].attack.damage[0].formula | dice_count <= 1",
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "attack_damage", "formula": m.group(1), "damage_type": m.group(2)},
            }
        )

    return effects


def _damage_adjustment_item(value, damage_type=None, notes=None):
    """Build an attack_damage item for a flat damage adjustment."""
    item = {
        "type": "stat_block_section",
        "subtype": "attack_damage",
        "formula": f"{value:+d}" if value != 0 else "0",
    }
    if damage_type:
        item["damage_type"] = damage_type
    if notes:
        item["notes"] = notes
    return item


def _normalize_movement_type(mt):
    """Normalize movement type from HTML text to data model value."""
    return _MOVEMENT_TYPE_NORMALIZE.get(mt, mt)


def _build_speed_effects(text):
    t = text.lower()
    effects = []

    # "Add a swim Speed of 25 feet"
    # "Add a swim Speed of 25 feet"
    m = re.search(r"add a (\w+) speed (?:of |equal to )?(\d+) feet", t)
    if m:
        move_type = _normalize_movement_type(m.group(1))
        return [
            {
                "target": "$.offense.speed.movement",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "speed",
                    "name": f"{move_type} {m.group(2)} feet",
                    "movement_type": move_type,
                    "value": int(m.group(2)),
                },
            }
        ]

    # "Change Speed to 20 feet if higher"
    m = re.search(r"change speed to (\d+) feet", t)
    if m:
        cond = None
        if "if higher" in t:
            cond = f"$.offense.speed.movement[?(@.movement_type=='walk')].value > {m.group(1)}"
        elif "if lower" in t:
            cond = f"$.offense.speed.movement[?(@.movement_type=='walk')].value < {m.group(1)}"
        eff = {
            "target": "$.offense.speed.movement[?(@.movement_type=='walk')].value",
            "operation": "replace",
            "value": int(m.group(1)),
        }
        if cond:
            eff["conditional"] = cond
        effects.append(eff)
        return effects

    # "Add a fly Speed equal to its highest Speed"
    if re.search(r"speed equ\s*al to", t):
        m2 = re.search(r"(\w+) speed equ?\s*a?\s*l to", t)
        if m2:
            move_type = _normalize_movement_type(m2.group(1))
            if "half" in t:
                m3 = re.search(r"half its (\w+) speed", t)
                source_type = _normalize_movement_type(m3.group(1)) if m3 else "walk"
                eff = {
                    "target": "$.offense.speed.movement",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "speed", "name": move_type, "movement_type": move_type},
                    "value_from": f"$.offense.speed.movement[?(@.movement_type=='{source_type}')].value / 2",
                }
                if "minimum" in t:
                    m4 = re.search(r"minimum (\d+) feet", t)
                    if m4:
                        eff["minimum"] = int(m4.group(1))
            elif "highest" in t or "fastest" in t:
                eff = {
                    "target": "$.offense.speed.movement",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "speed", "name": move_type, "movement_type": move_type},
                    "value_from": "$.offense.speed.movement[*].value | max",
                }
            else:
                eff = {
                    "target": "$.offense.speed.movement",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "speed", "name": move_type, "movement_type": move_type},
                }
            if "doesn't have" in t or "doesn\u2019t have" in t:
                eff["conditional"] = f"$.offense.speed.movement[?(@.movement_type=='{move_type}')] == null"
            effects.append(eff)
            return effects

    # "change its highest Speed to a fly Speed"
    if "change" in t and "fly speed" in t:
        return [{"target": "$.offense.speed.movement", "operation": "replace_highest_with", "movement_type": "fly"}]

    # "Increase Speed by 10 feet or to 40 feet"
    m = re.search(r"increase speed by (\d+) feet or to (\d+) feet", t)
    if m:
        return [
            {
                "target": "$.offense.speed.movement[?(@.movement_type=='walk')].value",
                "operation": "adjustment",
                "value": int(m.group(1)),
                "minimum": int(m.group(2)),
            }
        ]

    # "Reduce the creature's Speed by N feet"
    m = re.search(r"reduce.+?speed by (\d+) feet", t)
    if m:
        eff = {
            "target": "$.offense.speed.movement[?(@.movement_type=='walk')].value",
            "operation": "adjustment",
            "value": -int(m.group(1)),
        }
        if "minimum" in t:
            m2 = re.search(r"minimum (?:of )?(\d+) feet", t)
            if m2:
                eff["minimum"] = int(m2.group(1))
        return [eff]

    # Level-conditional speed
    m = re.search(r"(\d+)\w* level or higher.+?(\w+) speed of (\d+) feet", t)
    if m:
        move_type = _normalize_movement_type(m.group(2))
        return [
            {
                "conditional": f"$.creature_type.level >= {m.group(1)}",
                "target": "$.offense.speed.movement",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "speed",
                    "name": f"{move_type} {m.group(3)} feet",
                    "movement_type": move_type,
                    "value": int(m.group(3)),
                },
            }
        ]

    return effects


def _build_hit_points_effects(text, adjustments=None):
    """Build HP effects using the adjustments table."""
    t = text.lower()
    if not adjustments:
        return []
    sign = -1 if "decrease" in t or "reduce" in t else 1
    return _hp_effects_from_adjustments(adjustments, sign)


def _hp_effects_from_adjustments(adjustments, sign):
    """Convert adjustments table rows into HP effects with conditionals."""
    effects = []
    for adj in adjustments:
        level_text = adj.get("starting_level", adj.get("level", ""))
        skip_keys = {"type", "subtype", "starting_level", "level"}
        # Prefer HP-specific columns over others (e.g., resistances)
        hp_keys = [k for k in adj if k not in skip_keys and "hp" in k.lower()]
        value_key = hp_keys if hp_keys else [k for k in adj if k not in skip_keys]
        if not value_key:
            continue
        raw_value = adj[value_key[0]].replace("\u2013", "-").replace("\u2014", "-")
        try:
            value = int(raw_value)
        except ValueError:
            continue
        # Ensure sign matches template direction
        if sign < 0 and value > 0:
            value = -value
        elif sign > 0 and value < 0:
            value = abs(value)
        conditional = _level_text_to_conditional(level_text)
        effects.append(
            {
                "conditional": conditional,
                "target": "$.defense.hitpoints[*].hp",
                "operation": "adjustment",
                "value": value,
            }
        )
    return effects


def _level_text_to_conditional(text):
    """Convert table level text like '2-4' or '20+' to a jsonpath conditional."""
    text = text.strip()
    if "or lower" in text or "or less" in text:
        num = re.search(r"(\d+)", text)
        if num:
            return f"$.creature_type.level <= {num.group(1)}"
    if text.endswith("+"):
        num = text.rstrip("+").strip()
        return f"$.creature_type.level >= {num}"
    if "-" in text and not text.startswith("-"):
        parts = text.split("-")
        return f"$.creature_type.level >= {parts[0].strip()} && $.creature_type.level <= {parts[1].strip()}"
    # Single number
    num = re.search(r"(\d+)", text)
    if num:
        return f"$.creature_type.level == {num.group(1)}"
    return text


def _build_skill_effects(text):
    t = text.lower()
    effects = []

    m = re.search(r"add (\w[\w\s]*?) with a modifier equal to.+?highest skill", t)
    if m:
        return [
            {
                "target": "$.statistics.skills",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "skill", "name": m.group(1).strip().title()},
                "value_from": "$.statistics.skills[*].value | max",
            }
        ]

    m = re.search(r"add (.+?) with a modifier", t)
    if m:
        skill_text = m.group(1)
        skills = re.split(r",\s*(?:and\s+)?|\s+and\s+", skill_text)
        for skill in skills:
            effects.append(
                {
                    "target": "$.statistics.skills",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "skill", "name": skill.strip().title()},
                    "value_from": "$.statistics.skills[*].value | max",
                }
            )
        return effects

    m = re.search(r"reduce.+?(\w+).+?modifier by (\d+)", t)
    if m:
        effects.append({"target": f"$.statistics.skills[?(@.name=='{m.group(1).title()}')].value", "operation": "adjustment", "value": -int(m.group(2))})

    m = re.search(r"(?:increase|set) the creature.s (\w+) modifier to.+?high skill", t)
    if m and not effects:
        effects.append({"target": f"$.statistics.skills[?(@.name=='{m.group(1).title()}')].value", "operation": "replace", "value_from": "$.statistics.skills | high_for_level"})

    m = re.search(r"give the creature a ([\w\s]+?) modifier.+?equal to.+?high skill value", t)
    if m and not effects:
        skill_text = m.group(1).strip()
        skills = re.split(r"\s+and\s+", skill_text)
        for skill in skills:
            effects.append(
                {
                    "target": "$.statistics.skills",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "skill", "name": skill.strip().title()},
                    "value_from": "$.statistics.skills | high_for_level",
                }
            )

    m = re.search(r"gains the (\w[\w\s]*?) skill", t)
    if m and not effects:
        effects.append(
            {"target": "$.statistics.skills", "operation": "add_item", "item": {"type": "stat_block_section", "subtype": "skill", "name": m.group(1).strip().title()}}
        )

    if "choose" in t and not effects:
        effects.append({"target": "$.statistics.skills", "operation": "select", "selection": {"type": "select_one", "description": text}})

    if "lore skill relevant" in t and not effects:
        effects.append({"target": "$.statistics.skills", "operation": "select", "selection": {"type": "select_one", "constraint": "lore", "description": text}})

    return effects


def _build_spell_effects(text):
    t = text.lower()
    m = re.search(r"add \*?(\w[\w\s]*?)\*? as an innate (\w+) spell", t)
    if m:
        return [
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "offensive_action", "name": m.group(1).strip().title(), "offensive_action_type": "spells"},
            }
        ]
    if "swap" in t:
        return [{"target": "$.offense.offensive_actions[*].spells", "operation": "select", "selection": {"type": "replace_n", "description": text}}]
    m = re.search(r"replace spells with (\w+) spells", t)
    if m:
        return [
            {
                "target": "$.offense.offensive_actions[*].spells.spell_list[*].spells",
                "operation": "select",
                "selection": {"type": "replace_n", "constraint": m.group(1).strip(), "description": text},
            }
        ]
    return []


def _build_strike_effects(text):
    t = text.lower()

    m = re.search(r"replace.+?(\w+) attacks? with (\w+) attacks?", t)
    if m:
        old_weapon = m.group(1)
        new_weapon = m.group(2)
        effects = [
            {"target": f"$.offense.offensive_actions[?(@.attack.weapon=='{old_weapon}')].attack.weapon", "operation": "replace", "value": new_weapon},
            {"target": f"$.offense.offensive_actions[?(@.attack.weapon=='{old_weapon}')].attack.name", "operation": "replace", "value": new_weapon.title()},
        ]
        m2 = re.search(r"deal (\w+) damage instead of (\w+)", t)
        if m2:
            effects.append(
                {"target": f"$.offense.offensive_actions[?(@.attack.weapon=='{new_weapon}')].attack.damage[*].damage_type", "operation": "replace", "value": m2.group(1)}
            )
        return effects

    m = re.search(r"reduce the reach.+?to (\d+) feet", t)
    if m:
        return [{"target": "$.offense.offensive_actions[?(@.attack.attack_type=='melee')].attack.bonus", "operation": "set_reach", "value": int(m.group(1))}]

    if "paralysis" in t or "drain life" in t:
        return [{"target": "$.offense.offensive_actions[*].attack", "operation": "select", "selection": {"type": "select_n", "description": text}}]

    if "ability" in t:
        return [
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "offensive_action"},
                "source": "$.changes[*].abilities",
            }
        ]

    if "versatile" in t:
        return [
            {
                "target": "$.offense.offensive_actions[*].attack.traits",
                "operation": "select",
                "selection": {"type": "select_one", "options": ["versatile P", "versatile S"], "description": text},
            }
        ]

    return []


def _build_weakness_effects(text, adjustments=None):
    t = text.lower()
    names = _extract_names_from_text(text, "weaknesses")
    if not names:
        m = re.search(r"weakness to (\w[\w\s]*?)[\.,]", t)
        if m:
            names = [m.group(1).strip()]
    m = re.search(r"weakness to (\w+) damage", t)
    if m and not names:
        names = [m.group(1).strip()]

    effects = []
    # Level-based values from adjustments table
    if ("value based on" in t or "depending on" in t or "value dependent" in t) and adjustments:
        for name in names:
            for adj in adjustments:
                level_text = adj.get("level", adj.get("starting_level", ""))
                val_key = [k for k in adj if k not in ("type", "subtype", "level", "starting_level")]
                if val_key:
                    try:
                        val = int(adj[val_key[0]])
                    except ValueError:
                        continue
                    effects.append(
                        {
                            "conditional": _level_text_to_conditional(level_text),
                            "target": "$.defense.hitpoints[*].weaknesses",
                            "operation": "add_item",
                            "item": {
                                "type": "stat_block_section",
                                "subtype": "weakness",
                                "name": name,
                                "value": val,
                            },
                        }
                    )
    else:
        for name in names:
            effects.append(
                {
                    "target": "$.defense.hitpoints[*].weaknesses",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "weakness", "name": name},
                }
            )
    return effects


def _build_resistance_effects(text, adjustments=None):
    t = text.lower()
    effects = []

    m = re.search(r"resistance to ([\w\s]+?)(?:,|\.|depending|with)", t)
    if m:
        name = m.group(1).strip()
        if ("depending on" in t or "based on" in t) and adjustments:
            for adj in adjustments:
                level_text = adj.get("level", adj.get("starting_level", ""))
                val_key = [k for k in adj if k not in ("type", "subtype", "level", "starting_level")]
                if val_key:
                    try:
                        val = int(adj[val_key[0]])
                    except ValueError:
                        continue
                    effects.append(
                        {
                            "conditional": _level_text_to_conditional(level_text),
                            "target": "$.defense.hitpoints[*].resistances",
                            "operation": "add_item",
                            "item": {
                                "type": "stat_block_section",
                                "subtype": "resistance",
                                "name": name,
                                "value": val,
                            },
                        }
                    )
        else:
            effects.append(
                {
                    "target": "$.defense.hitpoints[*].resistances",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "resistance", "name": name},
                }
            )

    names = _extract_names_from_text(text, "resistances")
    if names and not effects:
        for res_name in names:
            effects.append(
                {
                    "target": "$.defense.hitpoints[*].resistances",
                    "operation": "add_item",
                    "item": {"type": "stat_block_section", "subtype": "resistance", "name": res_name},
                }
            )

    m = re.search(r"resistance to (?:all )?physical damage (?:\()?except (?:from )?(\w[\w\s]*?)[\),]", t)
    if m and not effects:
        bypass = m.group(1).strip()
        effects.append(
            {
                "target": "$.defense.hitpoints[*].resistances",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "resistance",
                    "name": "physical",
                    "modifiers": [{"type": "stat_block_section", "subtype": "modifier", "name": f"except {bypass}"}],
                },
            }
        )

    if "fast healing" in t and not effects:
        effects.append(
            {
                "target": "$.defense.hitpoints[*].automatic_abilities",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "ability", "name": "Fast Healing", "ability_type": "automatic"},
            }
        )

    if "choose" in t and not effects:
        effects.append({"target": "$.defense.hitpoints[*].resistances", "operation": "add_item", "item": {"type": "stat_block_section", "subtype": "resistance", "name": "physical"}})
        effects.append(
            {
                "target": "$.defense.hitpoints[*].resistances[?(@.name=='physical')]",
                "operation": "select",
                "selection": {"type": "select_one", "constraint": "bypass_material", "description": text},
            }
        )

    return effects
