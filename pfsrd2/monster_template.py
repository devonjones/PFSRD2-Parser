import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString, Tag

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.universal import (
    aon_pass,
    build_object,
    entity_pass,
    extract_link,
    extract_source_from_bs,
    game_id_pass,
    get_links,
    handle_alternate_link,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
)
from universal.utils import get_text, remove_empty_fields, strip_block_tags


def parse_monster_template(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=4,
        cssclass="main",
        pre_filters=[_content_filter],
    )
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    alternate_link = handle_alternate_link(details)
    struct = restructure_monster_template_pass(details)
    if alternate_link:
        struct["alternate_link"] = alternate_link
    monster_template_struct_pass(struct)
    source_pass(struct, find_monster_template)
    _extract_changes_pass(struct)
    _extract_adjustments_pass(struct)
    monster_template_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, "monster_template", find_monster_template)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    monster_template_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "")
    _categorize_changes_pass(struct)
    remove_empty_fields(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "monster_template.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, "monster_templates", name)
            write_monster_template(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def _content_filter(soup):
    """Remove navigation elements and unwrap content spans."""
    main = soup.find(id="main")
    if not main:
        return
    hr = main.find("hr", recursive=False)
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()
    for hr in main.find_all("hr", recursive=False):
        hr.extract()
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
            break
    for span in main.find_all("span", recursive=False):
        if not span.get_text(strip=True):
            span.decompose()
    for a in main.find_all("a"):
        if not a.string and not a.contents:
            a.decompose()
    for img in main.find_all("img"):
        img.decompose()
    for div in main.find_all("div", {"class": "siderbarlook"}):
        div.unwrap()


def restructure_monster_template_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    top = {"name": sb["name"], "type": "monster_template", "sections": [sb]}
    sb["type"] = "stat_block_section"
    sb["subtype"] = "monster_template"
    top["sections"].extend(rest)
    if len(sb["sections"]) > 0:
        top["sections"].extend(sb["sections"])
        sb["sections"] = []
    return top


def find_monster_template(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "monster_template":
            return section


def monster_template_struct_pass(struct):
    """Extract sources from section text fields, recursively."""

    def _extract_source(section):
        if "text" not in section:
            return None
        bs = BeautifulSoup(section["text"], "html.parser")
        source = extract_source_from_bs(bs)
        if not source:
            return None
        section["text"] = str(bs).strip()
        return [source]

    def _process_sections(sections, top_sources):
        for section in sections:
            sec_sources = _extract_source(section)
            if sec_sources:
                section["sources"] = sec_sources
                top_sources.extend(sec_sources)
            else:
                section["sources"] = []
            if section.get("sections"):
                _process_sections(section["sections"], top_sources)

    sources = []
    _process_sections(struct["sections"], sources)
    struct["sources"] = sources


_ACTION_TITLE_MAP = {
    "Single Action": "One Action",
    "Two Actions": "Two Actions",
    "Three Actions": "Three Actions",
    "Reaction": "Reaction",
    "Free Action": "Free Action",
}


def _extract_changes_pass(struct):
    """Extract the <ul> list and/or inline abilities from the stat block text or sections."""
    mt = find_monster_template(struct)
    if not mt:
        return

    def _search_sections(sections):
        for section in sections:
            if section is mt:
                continue
            if "text" in section:
                _try_extract_changes(section, mt)
            if section.get("sections"):
                _search_sections(section["sections"])

    # Try extracting from stat block text first
    if "text" in mt:
        _try_extract_changes(mt, mt)
    # Also check sections recursively — some templates have changes/abilities
    # in subsections (e.g., "Abilities" under "Adjustments")
    _search_sections(struct["sections"])


def _try_extract_changes(source_section, mt):
    """Try to extract changes and/or abilities from a section's text."""
    bs = BeautifulSoup(source_section["text"], "html.parser")
    found = False
    ul = bs.find("ul")
    if ul and "changes" not in mt:
        changes = []
        for li in ul.find_all("li", recursive=False):
            if not get_text(li).strip():
                continue
            change = _parse_change(li)
            changes.append(change)
        ul.decompose()
        source_section["text"] = str(bs).strip()
        mt["changes"] = changes
        found = True
    # Check for inline abilities — either when there's no <ul>, or in
    # remaining text after the <ul> was removed (ancestry templates put
    # abilities after the </ul>)
    abilities = _extract_inline_abilities(bs)
    if abilities:
        source_section["text"] = str(bs).strip()
        mt.setdefault("abilities", []).extend(abilities)
        found = True
    return found


def _parse_change(li):
    """Parse a single <li> into a change object, extracting abilities if present."""
    change = build_object("stat_block_section", "change", "")
    # Check if this li contains abilities (bold names after "Add the following abilities")
    text_content = get_text(li).strip()
    has_abilities = "following abilit" in text_content.lower()
    if has_abilities:
        abilities = _extract_abilities_from_li(li)
        if abilities:
            change["abilities"] = abilities
    # Extract links from li
    links = get_links(li, unwrap=True)
    if links:
        change["links"] = links
    # Unwrap action spans — keep text
    for span in li.find_all("span", {"class": "action"}):
        span.unwrap()
    text = str(li).strip()
    # Clean leading/trailing br
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    change["text"] = text.strip()
    # Remove empty name — text is the content
    del change["name"]
    return change


def _parse_ability_nodes(nodes):
    """Parse a sequence of nodes into ability objects.

    Abilities are delimited by <br> tags. Each starts with <b>Name</b>
    (optionally inside <a>), optionally followed by <span class="action">,
    then description text.
    """
    abilities = []
    current_ability = None
    for node in nodes:
        if isinstance(node, Tag) and node.name == "br":
            if current_ability:
                abilities.append(current_ability)
                current_ability = None
            continue
        if isinstance(node, Tag) and node.name == "a" and node.find("b"):
            b = node.find("b")
            name = get_text(b).strip()
            if current_ability:
                abilities.append(current_ability)
            current_ability = build_object("stat_block_section", "ability", name)
            link_name, link_obj = _extract_link_from_a(node)
            if link_obj:
                current_ability["link"] = link_obj
            continue
        if isinstance(node, Tag) and node.name == "b":
            name = get_text(node).strip()
            if current_ability:
                abilities.append(current_ability)
            current_ability = build_object("stat_block_section", "ability", name)
            continue
        if isinstance(node, Tag) and node.name == "span" and "action" in node.get("class", []):
            if current_ability:
                title = node.get("title", "")
                if title in _ACTION_TITLE_MAP:
                    current_ability["action_type"] = build_object(
                        "stat_block_section", "action_type", _ACTION_TITLE_MAP[title]
                    )
            continue
        if current_ability:
            text_bit = str(node).strip()
            if text_bit:
                existing = current_ability.get("text", "")
                current_ability["text"] = (existing + " " + text_bit).strip()

    if current_ability:
        abilities.append(current_ability)

    # Extract links from ability text fields
    for ability in abilities:
        if "text" in ability:
            ab_bs = BeautifulSoup(ability["text"], "html.parser")
            links = get_links(ab_bs, unwrap=True)
            if links:
                ability["links"] = links
            ability["text"] = str(ab_bs).strip()

    return abilities if abilities else None


def _extract_abilities_from_li(li):
    """Extract abilities from a <li> that says 'Add the following abilities.'"""
    found_abilities_text = False
    nodes = list(li.children)
    ability_nodes = []
    for node in nodes:
        if not found_abilities_text:
            if isinstance(node, NavigableString) and "following abilit" in str(node).lower():
                found_abilities_text = True
            continue
        ability_nodes.append(node)
    return _parse_ability_nodes(ability_nodes)


def _extract_inline_abilities(bs):
    """Extract abilities from text where they appear inline separated by <br>.

    For templates without a <ul> list — abilities appear directly in text after
    a sentence like 'The creature gains the following abilities.'
    """
    # Find the first <b> tag that's NOT inside a <table>
    first_b = None
    for b in bs.find_all("b"):
        if not b.find_parent("table"):
            first_b = b
            break
    if not first_b:
        return None
    # Collect all nodes from the first <b> onward (siblings only)
    ability_nodes = []
    node = first_b
    while node:
        next_node = node.next_sibling
        ability_nodes.append(node.extract())
        node = next_node
    return _parse_ability_nodes(ability_nodes)


def _extract_link_from_a(a_tag):
    """Extract name and link object from an <a> tag."""
    return extract_link(a_tag)


def _extract_adjustments_pass(struct):
    """Extract the adjustments table from the h2 section into the stat block."""
    mt = find_monster_template(struct)
    if not mt:
        return
    # Find the adjustments section (h2 with table, or unnamed section with table)
    remaining = []
    adjustments = None

    def _check_section(section):
        nonlocal adjustments
        if adjustments:
            return False
        name = section.get("name", "").lower()
        text = section.get("text", "")
        if ("adjustment" in name or not name.strip()) and ("|" in text or "<table" in text):
            adjustments = _parse_adjustments_table(text)
            return bool(adjustments)
        # Check subsections
        return any(_check_section(sub) for sub in section.get("sections", []))

    for section in struct["sections"]:
        if section is mt:
            remaining.append(section)
            continue
        if _check_section(section):
            pass  # consumed by adjustment extraction
        else:
            remaining.append(section)
    struct["sections"] = remaining
    if adjustments:
        mt["adjustments"] = adjustments


def _parse_adjustments_table(text):
    """Parse a markdown or HTML table into adjustment objects."""
    bs = BeautifulSoup(text, "html.parser")
    table = bs.find("table")
    if table:
        return _parse_html_table(table)
    # Try markdown table
    return _parse_markdown_table(text)


def _parse_html_table(table):
    """Parse an HTML table into adjustment objects."""
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None
    # First row is headers
    headers = []
    for td in rows[0].find_all(["td", "th"]):
        headers.append(get_text(td).strip().lower().replace(" ", "_"))
    adjustments = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        adj = build_object("stat_block_section", "adjustment", "")
        del adj["name"]
        for i, cell in enumerate(cells):
            if i < len(headers):
                adj[headers[i]] = get_text(cell).strip()
        adjustments.append(adj)
    return adjustments if adjustments else None


def _parse_markdown_table(text):
    """Parse a markdown table into adjustment objects."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 3:
        return None
    # First line is headers, second is separator
    headers = [
        h.strip().lower().replace(" ", "_").replace("*", "")
        for h in lines[0].split("|")
        if h.strip()
    ]
    adjustments = []
    for line in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.split("|") if c.strip()]
        adj = build_object("stat_block_section", "adjustment", "")
        del adj["name"]
        for i, cell in enumerate(cells):
            if i < len(headers):
                adj[headers[i]] = cell
        adjustments.append(adj)
    return adjustments if adjustments else None


def _categorize_changes_pass(struct):
    """Add change_category and effects to change objects.

    This is a hand-authored semantic mapping from the human-readable change text
    to machine-readable effect instructions. The downstream patch generator uses
    these to build RFC 6902 JSON Patches against creature JSON.

    Effects use jsonpath-style targets referencing the creature schema.
    Operation is always 'adjustment' with positive or negative value.
    For damage, 'add_modifier' appends a modifier object to the target.
    """
    mt = struct.get("monster_template")
    if not mt or "changes" not in mt:
        return
    name = mt.get("name", "")
    if name == "Elite":
        _categorize_elite(mt, 1, name.lower())
    elif name == "Weak":
        _categorize_elite(mt, -1, name.lower())
    else:
        # Auto-categorize based on text content
        for change in mt.get("changes", []):
            change["change_category"] = _categorize_change_text(change.get("text", ""))
        # Build effects for deterministic patterns
        _build_generic_effects(mt)


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


def _build_generic_effects(mt):
    """Build effects for non-Elite/Weak templates using text pattern matching."""
    for change in mt.get("changes", []):
        cat = change.get("change_category", "unknown")
        text = change.get("text", "")
        t = text.lower()

        if cat == "abilities":
            # Abilities are already extracted as structured objects on the change
            # or on the stat block — just add a pointer effect
            abilities = change.get("abilities", mt.get("abilities", []))
            if abilities:
                change["effects"] = [
                    {
                        "target": "$.defense.automatic_abilities",
                        "operation": "add_items",
                        "source": "$.monster_template.changes[*].abilities",
                    }
                ]
        elif cat == "immunities":
            change["effects"] = _build_immunity_effects(text)
        elif cat == "languages":
            change["effects"] = _build_language_effects(text)
        elif cat == "traits":
            change["effects"] = _build_trait_effects(text)
        elif cat == "size":
            change["effects"] = _build_size_effects(text)
        elif cat == "senses":
            change["effects"] = _build_sense_effects(text)
        elif cat == "attributes":
            change["effects"] = _build_attribute_effects(text)
        elif cat == "level":
            change["effects"] = _build_level_effects(text)
        elif cat == "combat_stats":
            change["effects"] = _build_combat_stat_effects(text)
        elif cat == "damage":
            change["effects"] = _build_damage_effects(text)
        elif cat == "hit_points":
            if "adjustments" in mt:
                # Use sign=1 for increase, -1 for decrease
                sign = -1 if "decrease" in t else 1
                change["effects"] = _hp_effects_from_adjustments(mt["adjustments"], sign)
        elif cat == "speed":
            change["effects"] = _build_speed_effects(text)
        elif cat == "skills":
            change["effects"] = _build_skill_effects(text)
        elif cat == "weaknesses":
            change["effects"] = _build_weakness_effects(text, mt)
        elif cat == "resistances":
            change["effects"] = _build_resistance_effects(text, mt)
        elif cat == "spells":
            change["effects"] = _build_spell_effects(text)
        elif cat == "strikes":
            change["effects"] = _build_strike_effects(text)
        elif cat == "traits":
            change["effects"] = _build_trait_effects(text)
        elif cat == "gear":
            change["effects"] = [
                {
                    "target": "$.statistics.gear",
                    "operation": "select",
                    "selection": {
                        "type": "remove_n",
                        "description": text,
                    },
                }
            ]


def _extract_names_from_text(text, after_marker):
    """Extract comma-separated names from text after a marker phrase.

    E.g., 'Add the following immunities: death effects, disease, poison.'
    -> ['death effects', 'disease', 'poison']
    """
    t = text.lower()
    idx = t.find(after_marker)
    if idx < 0:
        return []
    rest = text[idx + len(after_marker) :].strip()
    # Strip trailing period and sentence continuations
    if ". " in rest:
        rest = rest[: rest.index(". ")]
    rest = rest.rstrip(".")
    return [n.strip().strip("*") for n in rest.split(",") if n.strip()]


def _build_immunity_effects(text):
    names = _extract_names_from_text(text, "immunities:")
    if not names:
        # Single immunity: "Add immunity to fire."
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
    # Extract language name(s) — "Add the Necril language" or "add Sussuran"
    t = text.lower()
    effects = []
    # "Add the Fey and Gnomish languages"
    m = re.search(r"add (?:the )?(.+?)(?:\s+language)", t)
    if m:
        lang_text = m.group(1)
        # Split on " and " or ","
        langs = re.split(r"\s+and\s+|,\s*", lang_text)
        for lang in langs:
            lang = lang.strip().title()
            if lang:
                effects.append(
                    {
                        "target": "$.languages.languages",
                        "operation": "add_item",
                        "item": {"type": "stat_block_section", "subtype": "language", "name": lang},
                    }
                )
    if not effects:
        # "If it has any languages, add Sussuran."
        m = re.search(r"add (\w+)\.", t)
        if m:
            cond = None
            if "if it has any languages" in t:
                cond = "$.languages.languages != null"
            eff = {
                "target": "$.languages.languages",
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

    # "Replace the human trait with the dwarf trait"
    m = re.search(r"replace the (\w+) trait with the (\w+) trait", t)
    if m:
        effects.append(
            {
                "target": "$.creature_type.creature_types",
                "operation": "remove_item",
                "name": m.group(1).title(),
            }
        )
        effects.append(
            {
                "target": "$.creature_type.creature_types",
                "operation": "add_item",
                "name": m.group(2).title(),
            }
        )

    # "Add the ghost, spirit, and undead traits"
    m = re.search(r"add the (.+?) traits?[\.,]", t)
    if m:
        trait_text = m.group(1)
        traits = re.split(r",\s*(?:and\s+)?|\s+and\s+", trait_text)
        for trait in traits:
            trait = trait.strip()
            if trait and trait not in ("optionally the mindless",):
                effects.append(
                    {
                        "target": "$.creature_type.creature_types",
                        "operation": "add_item",
                        "name": trait.title(),
                    }
                )

    # "gains the undead and vampire traits" / "gain the construct trait"
    if not effects:
        m = re.search(r"gains? the (.+?) traits?[,.\s]", t)
        if m:
            trait_text = m.group(1)
            traits = re.split(r",\s*(?:and\s+)?|\s+and\s+", trait_text)
            for trait in traits:
                trait = trait.strip()
                if trait and "usually" not in trait:
                    effects.append(
                        {
                            "target": "$.creature_type.creature_types",
                            "operation": "add_item",
                            "name": trait.title(),
                        }
                    )

    # "Add the rare trait"
    if not effects:
        m = re.search(r"add the (\w+) trait", t)
        if m:
            effects.append(
                {
                    "target": "$.creature_type.creature_types",
                    "operation": "add_item",
                    "name": m.group(1).title(),
                }
            )

    # "If the creature has the aquatic trait, remove it"
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

    # "Increase the creature's rarity to uncommon if it was common or rare if uncommon"
    if "rarity" in t and not effects:
        effects.append(
            {
                "conditional": "$.creature_type.rarity == 'Common'",
                "target": "$.creature_type.rarity",
                "operation": "replace",
                "value": "Uncommon",
            }
        )
        effects.append(
            {
                "conditional": "$.creature_type.rarity == 'Uncommon'",
                "target": "$.creature_type.rarity",
                "operation": "replace",
                "value": "Rare",
            }
        )

    # "Replace the human and humanoid traits with the" (Leshy split li)
    m = re.search(r"replace the (.+?) traits? with the$", t)
    if m and not effects:
        for trait in re.split(r"\s+and\s+|,\s*", m.group(1)):
            effects.append(
                {
                    "target": "$.creature_type.creature_types",
                    "operation": "remove_item",
                    "name": trait.strip().title(),
                }
            )

    # "leshy and plant traits." (continuation of split li)
    m = re.match(r"^-?\s*([\w\s,]+(?:\s+and\s+[\w\s]+)+)\s+traits?\.", t)
    if m and "replace" not in t and "add" not in t and not effects:
        for trait in re.split(r"\s+and\s+|,\s*", m.group(1)):
            effects.append(
                {
                    "target": "$.creature_type.creature_types",
                    "operation": "add_item",
                    "name": trait.strip().title(),
                }
            )

    # "loses the animal trait and gains the beast trait"
    m = re.search(r"loses the (\w+) trait.+?gains the (\w+) trait", t)
    if m and not effects:
        effects.append(
            {
                "target": "$.creature_type.creature_types",
                "operation": "remove_item",
                "name": m.group(1).title(),
            }
        )
        effects.append(
            {
                "target": "$.creature_type.creature_types",
                "operation": "add_item",
                "name": m.group(2).title(),
            }
        )

    return effects


def _build_size_effects(text):
    t = text.lower()
    m = re.search(r"(?:change size to|reduce .+ size to|becomes?) (\w+)", t)
    if m:
        return [
            {
                "target": "$.creature_type.size",
                "operation": "replace",
                "value": m.group(1).title(),
            }
        ]
    # "Increase its size by one category"
    if "increase" in t and "size" in t and "one" in t:
        return [
            {
                "target": "$.creature_type.size",
                "operation": "size_increment",
                "value": 1,
            }
        ]
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
            {
                "target": "$.senses.special_senses",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "special_sense",
                    "name": "darkvision",
                },
            }
        )
    if "low-light vision" in t:
        effects.append(
            {
                "target": "$.senses.special_senses",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "special_sense",
                    "name": "low-light vision",
                },
            }
        )
    return effects


def _build_attribute_effects(text):
    t = text.lower()
    effects = []
    # "If the creature's Intelligence modifier is –4 or lower, increase it to –3."
    m = re.search(
        r"(\w+) modifier is [–-]?(\d+) or lower.+?(?:increase|set) it to [–-]?(\d+)",
        t,
    )
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
    # "has a Strength modifier of –5 and a Constitution modifier of +0"
    for m in re.finditer(r"(\w+) modifier of [+–-]?(\d+)", t):
        attr = m.group(1).lower()
        # Determine sign
        prefix = t[max(0, m.start() - 3) : m.start() + len(m.group(0))]
        val = int(m.group(2))
        if "–" in prefix or "-" in prefix[: prefix.find(m.group(2))]:
            val = -val
        effects.append(
            {
                "target": f"$.statistics.{attr[:3]}",
                "operation": "replace",
                "value": val,
            }
        )
    return effects


def _build_level_effects(text):
    t = text.lower()
    m = re.search(r"(increase|decrease) the (?:creature|spellcaster)['\u2019]s level by (\d+)", t)
    if m:
        direction = 1 if m.group(1) == "increase" else -1
        value = int(m.group(2)) * direction
        return [
            {
                "target": "$.creature_type.level",
                "operation": "adjustment",
                "value": value,
            }
        ]
    return []


def _build_combat_stat_effects(text):
    t = text.lower()
    effects = []

    # "Increase/Decrease the creature's AC, attack bonuses, DCs... by N"
    m = re.search(r"(increase|decrease).+?by (\d+)", t)
    if not m:
        return []

    direction = 1 if m.group(1) == "increase" else -1
    val = int(m.group(2)) * direction

    if "ac" in t:
        effects.append({"target": "$.defense.ac.value", "operation": "adjustment", "value": val})
    if "attack" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.bonus.bonuses",
                "operation": "adjustment",
                "value": val,
            }
        )
    if "dc" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].spells.saving_throw.dc",
                "operation": "adjustment",
                "value": val,
            }
        )
    if "saving throw" in t:
        for save in ("fort", "ref", "will"):
            effects.append(
                {
                    "target": f"$.defense.saves.{save}.value",
                    "operation": "adjustment",
                    "value": val,
                }
            )
    if "perception" in t:
        effects.append(
            {"target": "$.senses.perception.value", "operation": "adjustment", "value": val}
        )
    # Individual save names (e.g., "Decrease the creature's Will by 1")
    if not effects:
        for save_name in ("will", "fort", "ref"):
            if save_name in t:
                effects.append(
                    {
                        "target": f"$.defense.saves.{save_name}.value",
                        "operation": "adjustment",
                        "value": val,
                    }
                )
    if "skill" in t:
        effects.append({"target": "$.skills[*].value", "operation": "adjustment", "value": val})
    return effects


def _build_damage_effects(text):
    t = text.lower()
    effects = []

    # "Increase/Decrease the/its damage of Strikes... by N"
    m = re.search(r"(increase|decrease) (?:the|its) damage.+?by (\d+)", t)
    if m:
        direction = 1 if m.group(1) == "increase" else -1
        base_val = int(m.group(2)) * direction
        effects.append(
            {
                "conditional": "default",
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_modifier",
                "modifier": {
                    "type": "stat_block_section",
                    "subtype": "modifier",
                    "name": f"{base_val:+d} damage",
                },
            }
        )
        effects.append(
            {
                "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency == null",
                "target": "$.offense.offensive_actions[*].ability.damage",
                "operation": "add_modifier",
                "modifier": {
                    "type": "stat_block_section",
                    "subtype": "modifier",
                    "name": f"{base_val:+d} damage",
                },
            }
        )
        # Check for limited-use higher value
        m2 = re.search(r"(?:increase|decrease) the damage by (\d+) instead", t)
        if m2:
            limited_val = int(m2.group(1)) * direction
            effects.append(
                {
                    "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency != null",
                    "target": "$.offense.offensive_actions[*].ability.damage",
                    "operation": "add_modifier",
                    "modifier": {
                        "type": "stat_block_section",
                        "subtype": "modifier",
                        "name": f"{limited_val:+d} damage (limited use)",
                    },
                }
            )
        return effects

    # "Add drain life to any number of the creature's Strikes"
    if "any number" in t and "strikes" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack",
                "operation": "select",
                "selection": {
                    "type": "select_n",
                    "description": text,
                },
            }
        )
        return effects

    # "damage changes to negative damage"
    m = re.search(r"damage.+?changes? to (\w+) damage", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.damage[*].damage_type",
                "operation": "replace",
                "value": m.group(1),
            }
        )
        return effects

    # "gains a splinter ranged Strike" / "Add a jaws/fangs Strike"
    m = re.search(r"(?:add|gains?) a (\w[\w\s]*?) (?:ranged |melee )?strike", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "offensive_action",
                    "name": m.group(1).strip().title(),
                },
                "value_from": "$.offense.offensive_actions[*].attack.damage | min",
            }
        )
        return effects

    # "Reduce the damage of the creature's Strikes by N"
    m = re.search(r"reduce the damage.+?strikes? by (\d+)", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_modifier",
                "modifier": {
                    "type": "stat_block_section",
                    "subtype": "modifier",
                    "name": f"-{m.group(1)} damage",
                },
            }
        )
        return effects

    # "deal an additional 2d6 negative damage"
    m = re.search(r"deal an additional (\d+d\d+) (\w+) damage", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "attack_damage",
                    "formula": m.group(1),
                    "damage_type": m.group(2),
                },
            }
        )
        return effects

    # "change one die to fire damage" / "add 1 fire damage"
    m = re.search(r"change one die to (\w+) damage", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "replace_one_die",
                "value": m.group(1),
            }
        )
    m = re.search(r"add (\d+) (\w+) damage to its strikes", t)
    if m:
        effects.append(
            {
                "conditional": "$.offense.offensive_actions[*].attack.damage[0].formula | dice_count <= 1",
                "target": "$.offense.offensive_actions[*].attack.damage",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "attack_damage",
                    "formula": m.group(1),
                    "damage_type": m.group(2),
                },
            }
        )

    return effects


def _build_speed_effects(text):
    t = text.lower()
    effects = []

    # "Add a swim Speed of 25 feet"
    m = re.search(r"add a (\w+) speed (?:of |equal to )?(\d+) feet", t)
    if m:
        effects.append(
            {
                "target": "$.offense.speed.movement",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "speed",
                    "name": f"{m.group(1)} {m.group(2)} feet",
                    "movement_type": m.group(1),
                    "value": int(m.group(2)),
                },
            }
        )
        return effects

    # "Change Speed to 20 feet if higher"
    m = re.search(r"change speed to (\d+) feet", t)
    if m:
        cond = None
        if "if higher" in t:
            cond = f"$.offense.speed.movement[?(@.movement_type=='land')].value > {m.group(1)}"
        elif "if lower" in t:
            cond = f"$.offense.speed.movement[?(@.movement_type=='land')].value < {m.group(1)}"
        eff = {
            "target": "$.offense.speed.movement[?(@.movement_type=='land')].value",
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
            move_type = m2.group(1)
            # "equal to half its land Speed"
            if "half" in t:
                m3 = re.search(r"half its (\w+) speed", t)
                source_type = m3.group(1) if m3 else "land"
                eff = {
                    "target": "$.offense.speed.movement",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "speed",
                        "name": move_type,
                        "movement_type": move_type,
                    },
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
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "speed",
                        "name": move_type,
                        "movement_type": move_type,
                    },
                    "value_from": "$.offense.speed.movement[*].value | max",
                }
            else:
                eff = {
                    "target": "$.offense.speed.movement",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "speed",
                        "name": move_type,
                        "movement_type": move_type,
                    },
                }
            if "doesn't have" in t or "doesn\u2019t have" in t:
                eff["conditional"] = (
                    f"$.offense.speed.movement[?(@.movement_type=='{move_type}')] == null"
                )
            effects.append(eff)
            return effects

    # "change its highest Speed to a fly Speed"
    if "change" in t and "fly speed" in t:
        effects.append(
            {
                "target": "$.offense.speed.movement",
                "operation": "replace_highest_with",
                "movement_type": "fly",
            }
        )
        return effects

    # "Increase Speed by 10 feet or to 40 feet, whichever results in higher"
    m = re.search(r"increase speed by (\d+) feet or to (\d+) feet", t)
    if m:
        effects.append(
            {
                "target": "$.offense.speed.movement[?(@.movement_type=='land')].value",
                "operation": "adjustment",
                "value": int(m.group(1)),
                "minimum": int(m.group(2)),
            }
        )
        return effects

    # "Reduce the creature's Speed by N feet"
    m = re.search(r"reduce.+?speed by (\d+) feet", t)
    if m:
        effects.append(
            {
                "target": "$.offense.speed.movement[?(@.movement_type=='land')].value",
                "operation": "adjustment",
                "value": -int(m.group(1)),
            }
        )
        if "minimum" in t:
            m2 = re.search(r"minimum (?:of )?(\d+) feet", t)
            if m2:
                effects[-1]["minimum"] = int(m2.group(1))
        return effects

    # Level-conditional: "If the creature is 8th level or higher, give it a fly Speed of 25 feet"
    m = re.search(r"(\d+)\w* level or higher.+?(\w+) speed of (\d+) feet", t)
    if m:
        effects.append(
            {
                "conditional": f"$.creature_type.level >= {m.group(1)}",
                "target": "$.offense.speed.movement",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "speed",
                    "name": f"{m.group(2)} {m.group(3)} feet",
                    "movement_type": m.group(2),
                    "value": int(m.group(3)),
                },
            }
        )
        return effects

    return effects


def _build_skill_effects(text):
    t = text.lower()
    effects = []

    # "Add Stealth with a modifier equal to its highest skill modifier"
    m = re.search(r"add (\w[\w\s]*?) with a modifier equal to.+?highest skill", t)
    if m:
        skill_name = m.group(1).strip().title()
        effects.append(
            {
                "target": "$.skills",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "skill", "name": skill_name},
                "value_from": "$.skills[*].value | max",
            }
        )
        return effects

    # "Add Diplomacy and Labor Lore with a modifier..."
    m = re.search(r"add (.+?) with a modifier", t)
    if m:
        skill_text = m.group(1)
        skills = re.split(r",\s*(?:and\s+)?|\s+and\s+", skill_text)
        for skill in skills:
            effects.append(
                {
                    "target": "$.skills",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "skill",
                        "name": skill.strip().title(),
                    },
                    "value_from": "$.skills[*].value | max",
                }
            )
        return effects

    # "reduce its modifier by 2"
    m = re.search(r"reduce.+?(\w+).+?modifier by (\d+)", t)
    if m:
        effects.append(
            {
                "target": f"$.skills[?(@.name=='{m.group(1).title()}')].value",
                "operation": "adjustment",
                "value": -int(m.group(2)),
            }
        )

    # "Increase the creature's Thievery modifier to a high skill bonus"
    m = re.search(r"(?:increase|set) the creature.s (\w+) modifier to.+?high skill", t)
    if m and not effects:
        effects.append(
            {
                "target": f"$.skills[?(@.name=='{m.group(1).title()}')].value",
                "operation": "replace",
                "value_from": "$.skills | high_for_level",
            }
        )

    # "Give the creature a Stealth/Deception modifier equal to the high skill value"
    m = re.search(r"give the creature a ([\w\s]+?) modifier.+?equal to.+?high skill value", t)
    if m and not effects:
        skill_text = m.group(1).strip()
        skills = re.split(r"\s+and\s+", skill_text)
        for skill in skills:
            effects.append(
                {
                    "target": "$.skills",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "skill",
                        "name": skill.strip().title(),
                    },
                    "value_from": "$.skills | high_for_level",
                }
            )

    # "The creature gains the Deception skill"
    m = re.search(r"gains the (\w[\w\s]*?) skill", t)
    if m and not effects:
        effects.append(
            {
                "target": "$.skills",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "skill",
                    "name": m.group(1).strip().title(),
                },
            }
        )

    # "Choose a skill" — needs choice framework
    if "choose" in t and not effects:
        effects.append(
            {
                "target": "$.skills",
                "operation": "select",
                "selection": {
                    "type": "select_one",
                    "description": text,
                },
            }
        )

    # "gains a Lore skill relevant to" — needs choice framework
    if "lore skill relevant" in t and not effects:
        effects.append(
            {
                "target": "$.skills",
                "operation": "select",
                "selection": {
                    "type": "select_one",
                    "constraint": "lore",
                    "description": text,
                },
            }
        )

    return effects


def _build_spell_effects(text):
    t = text.lower()
    effects = []

    # "Add darkness as an innate divine spell usable once per day"
    m = re.search(r"add \*?(\w[\w\s]*?)\*? as an innate (\w+) spell", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "offensive_action",
                    "name": m.group(1).strip().title(),
                    "offensive_action_type": "spells",
                },
            }
        )
        return effects

    # "Swap out the domain spell" / "Swap the defiled religious symbol"
    if "swap" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].spells",
                "operation": "select",
                "selection": {
                    "type": "replace_n",
                    "description": text,
                },
            }
        )
        return effects

    # "you can replace spells with X spells" — choice framework
    m = re.search(r"replace spells with (\w+) spells", t)
    if m:
        element = m.group(1).strip()
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].spells.spell_list[*].spells",
                "operation": "select",
                "selection": {
                    "type": "replace_n",
                    "constraint": element,
                    "description": text,
                },
            }
        )
        return effects

    return effects


def _build_strike_effects(text):
    t = text.lower()
    effects = []

    # "Replace any fist attacks with claw attacks. They deal slashing damage"
    m = re.search(r"replace.+?(\w+) attacks? with (\w+) attacks?", t)
    if m:
        old_weapon = m.group(1)
        new_weapon = m.group(2)
        effects.append(
            {
                "target": f"$.offense.offensive_actions[?(@.attack.weapon=='{old_weapon}')].attack.weapon",
                "operation": "replace",
                "value": new_weapon,
            }
        )
        effects.append(
            {
                "target": f"$.offense.offensive_actions[?(@.attack.weapon=='{old_weapon}')].attack.name",
                "operation": "replace",
                "value": new_weapon.title(),
            }
        )
        m2 = re.search(r"deal (\w+) damage instead of (\w+)", t)
        if m2:
            effects.append(
                {
                    "target": f"$.offense.offensive_actions[?(@.attack.weapon=='{new_weapon}')].attack.damage[*].damage_type",
                    "operation": "replace",
                    "value": m2.group(1),
                }
            )
        return effects

    # "Reduce the reach of ... Strikes to 0 feet"
    m = re.search(r"reduce the reach.+?to (\d+) feet", t)
    if m:
        effects.append(
            {
                "target": "$.offense.offensive_actions[?(@.attack.attack_type=='melee')].attack.bonus",
                "operation": "set_reach",
                "value": int(m.group(1)),
            }
        )
        return effects

    # "Add the paralysis ability to the creature's jaws"
    if "paralysis" in t or "drain life" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack",
                "operation": "select",
                "selection": {
                    "type": "select_n",
                    "description": text,
                },
            }
        )
        return effects

    # "Add the Pounce ability" — already handled by abilities extraction
    if "ability" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "offensive_action"},
                "source": "$.monster_template.changes[*].abilities",
            }
        )
        return effects

    # "you can give its Strikes versatile P or versatile S" — choice
    if "versatile" in t:
        effects.append(
            {
                "target": "$.offense.offensive_actions[*].attack.traits",
                "operation": "select",
                "selection": {
                    "type": "select_one",
                    "options": ["versatile P", "versatile S"],
                    "description": text,
                },
            }
        )
        return effects

    return effects


def _build_weakness_effects(text, mt):
    t = text.lower()
    effects = []

    # "Add the following weaknesses... : force, ghost touch, positive"
    names = _extract_names_from_text(text, "weaknesses")
    if not names:
        m = re.search(r"weakness to (\w[\w\s]*?)[\.,]", t)
        if m:
            names = [m.group(1).strip()]

    # "gain weakness to X damage and more HP"
    m = re.search(r"weakness to (\w+) damage", t)
    if m and not names:
        names = [m.group(1).strip()]

    # Level-based values from adjustments table
    if "value based on" in t or "depending on" in t or "value dependent" in t:
        if "adjustments" in mt:
            for name in names:
                for adj in mt["adjustments"]:
                    level_text = adj.get("level", adj.get("starting_level", ""))
                    # Find the value column (not level)
                    val_key = [
                        k for k in adj if k not in ("type", "subtype", "level", "starting_level")
                    ]
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


def _build_resistance_effects(text, mt):
    t = text.lower()
    effects = []

    # "Add resistance to electricity depending on its level"
    m = re.search(r"resistance to ([\w\s]+?)(?:,|\.|depending|with)", t)
    if m:
        name = m.group(1).strip()
        if "depending on" in t or "based on" in t:
            if "adjustments" in mt:
                for adj in mt["adjustments"]:
                    level_text = adj.get("level", adj.get("starting_level", ""))
                    val_key = [
                        k for k in adj if k not in ("type", "subtype", "level", "starting_level")
                    ]
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

    # "Add the following resistances... : cold, electricity, fire"
    names = _extract_names_from_text(text, "resistances")
    if names and not effects:
        for res_name in names:
            effects.append(
                {
                    "target": "$.defense.hitpoints[*].resistances",
                    "operation": "add_item",
                    "item": {
                        "type": "stat_block_section",
                        "subtype": "resistance",
                        "name": res_name,
                    },
                }
            )

    # "gains resistance to physical damage (except X)"
    m = re.search(
        r"resistance to (?:all )?physical damage (?:\()?except (?:from )?(\w[\w\s]*?)[\),]", t
    )
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
                    "modifiers": [
                        {
                            "type": "stat_block_section",
                            "subtype": "modifier",
                            "name": f"except {bypass}",
                        }
                    ],
                },
            }
        )
    # "fast healing" in same text
    if "fast healing" in t and not effects:
        effects.append(
            {
                "target": "$.defense.hitpoints[*].automatic_abilities",
                "operation": "add_item",
                "item": {
                    "type": "stat_block_section",
                    "subtype": "ability",
                    "name": "Fast Healing",
                    "ability_type": "automatic",
                },
            }
        )

    # "Add resistance to physical damage... Choose one type of material"
    if "choose" in t and not effects:
        effects.append(
            {
                "target": "$.defense.hitpoints[*].resistances",
                "operation": "add_item",
                "item": {"type": "stat_block_section", "subtype": "resistance", "name": "physical"},
            }
        )
        effects.append(
            {
                "target": "$.defense.hitpoints[*].resistances[?(@.name=='physical')]",
                "operation": "select",
                "selection": {
                    "type": "select_one",
                    "constraint": "bypass_material",
                    "description": text,
                },
            }
        )

    return effects


def _categorize_elite(mt, sign, template_name):
    """Categorize Elite (sign=1) or Weak (sign=-1) changes.

    Both templates have the same structure with opposite signs.
    """
    for change in mt["changes"]:
        text = change.get("text", "").lower()
        if "level by" in text:
            change["change_category"] = "level"
            change["effects"] = [
                {
                    "conditional": (
                        "$.creature_type.level <= 0" if sign > 0 else "$.creature_type.level == 1"
                    ),
                    "target": "$.creature_type.level",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "conditional": "default",
                    "target": "$.creature_type.level",
                    "operation": "adjustment",
                    "value": sign * 1,
                },
            ]
        elif "ac" in text and "attack" in text and "saving throw" in text:
            change["change_category"] = "combat_stats"
            change["effects"] = [
                {
                    "target": "$.defense.ac.value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.offense.offensive_actions[*].attack.bonus.bonuses",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.offense.offensive_actions[*].spells.saving_throw.dc",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.defense.saves.fort.value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.defense.saves.ref.value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.defense.saves.will.value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.senses.perception.value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
                {
                    "target": "$.skills[*].value",
                    "operation": "adjustment",
                    "value": sign * 2,
                },
            ]
        elif "damage" in text and "strikes" in text.lower():
            change["change_category"] = "damage"
            change["effects"] = [
                {
                    "conditional": "default",
                    "target": "$.offense.offensive_actions[*].attack.damage",
                    "operation": "add_modifier",
                    "modifier": {
                        "type": "stat_block_section",
                        "subtype": "modifier",
                        "name": f"{sign * 2:+d} damage ({template_name})",
                    },
                },
                {
                    "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency == null",
                    "target": "$.offense.offensive_actions[*].ability.damage",
                    "operation": "add_modifier",
                    "modifier": {
                        "type": "stat_block_section",
                        "subtype": "modifier",
                        "name": f"{sign * 2:+d} damage ({template_name})",
                    },
                },
                {
                    "conditional": "$.offense.offensive_actions[*].ability.damage != null && $.offense.offensive_actions[*].ability.frequency != null",
                    "target": "$.offense.offensive_actions[*].ability.damage",
                    "operation": "add_modifier",
                    "modifier": {
                        "type": "stat_block_section",
                        "subtype": "modifier",
                        "name": f"{sign * 4:+d} damage ({template_name}, limited use)",
                    },
                },
            ]
        elif "hit points" in text or "\u2019s hp" in text or "'s hp" in text:
            change["change_category"] = "hit_points"
            # Effects come from the adjustments table
            if "adjustments" in mt:
                change["effects"] = _hp_effects_from_adjustments(mt["adjustments"], sign)
            else:
                change["effects"] = []
        else:
            change["change_category"] = "unknown"


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


def monster_template_link_pass(struct):
    """Extract links from text and name fields throughout the struct."""

    def _handle_text_field(section, field, keep=True):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs, unwrap=True)
        if len(links) > 0 and keep:
            linklist = section.setdefault("links", [])
            linklist.extend(links)
        section[field] = str(bs).strip()

    def _process_section(section):
        _handle_text_field(section, "name", keep=False)
        _handle_text_field(section, "text")
        for s in section.get("sections", []):
            _process_section(s)

    for section in struct["sections"]:
        _process_section(section)


def monster_template_cleanup_pass(struct):
    """Promote fields from monster_template object to top level."""
    mt = struct.get("monster_template")
    assert mt is not None, f"No monster_template object found in struct: {struct.get('name')}"
    struct["name"] = mt["name"]
    struct["sources"] = mt["sources"]
    del mt["sources"]
    if "text" in mt:
        struct["text"] = mt["text"]
        del mt["text"]
    if "links" in mt:
        struct["links"] = mt["links"]
        del mt["links"]
    if "sections" in mt:
        del mt["sections"]
    _clean_html_fields(struct)


def _clean_html_fields(struct):
    """Rename 'html' keys to 'text' in sections recursively."""
    for section in struct.get("sections", []):
        if "html" in section:
            section["text"] = section["html"]
            del section["html"]
        if "sections" in section:
            _clean_html_fields(section)


def write_monster_template(jsondir, struct, source):
    print(f"{struct['game-obj']} ({source}): {struct['name']}")
    filename = create_monster_template_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_monster_template_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
