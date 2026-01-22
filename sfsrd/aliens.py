import os
import json
import sys
import re
import copy
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString, Tag
from universal.universal import parse_universal, entity_pass
from universal.universal import get_text, break_out_subtitles
from universal.universal import string_with_modifiers_from_string_list
from universal.universal import modifiers_from_string_list
from universal.universal import extract_source
from universal.universal import extract_link
from universal.universal import get_links
from universal.universal import html_pass
from universal.universal import remove_empty_sections_pass
from universal.files import makedirs, char_replace
from universal.utils import split_maintain_parens, split_comma_and_semicolon
from universal.utils import filter_end
from universal.utils import log_element
from universal.utils import is_tag_named
from universal.creatures import write_creature
from universal.creatures import universal_handle_alignment
from universal.creatures import universal_handle_aura
from universal.creatures import universal_handle_creature_type
from universal.creatures import universal_handle_dr
from universal.creatures import universal_handle_defensive_abilities
from universal.creatures import universal_handle_gear
from universal.creatures import universal_handle_immunities
from universal.creatures import universal_handle_languages
from universal.creatures import universal_handle_modifier_breakout
from universal.creatures import universal_handle_perception
from universal.creatures import universal_handle_range
from universal.creatures import universal_handle_resistances
from universal.creatures import universal_handle_save_dc
from universal.creatures import universal_handle_senses
from universal.creatures import universal_handle_size
from universal.creatures import universal_handle_special_senses
from universal.creatures import universal_handle_sr
from universal.creatures import universal_handle_weaknesses
from sfsrd.schema import validate_against_schema


def parse_alien(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(
        filename,
        subtitle_text=False,
        max_title=3,
        cssclass="ctl00_MainContent_DataListTalentsAll_ctl00_LabelName",
    )
    details = entity_pass(details)
    struct = restructure_alien_pass(details, options.subtype)
    top_matter_pass(struct)
    defense_pass(struct)
    offense_pass(struct)
    statistics_pass(struct)
    ecology_pass(struct)
    special_ability_pass(struct)
    section_pass(struct)
    fix_description_pass(details, struct)
    html_pass(struct)
    # log_html_pass(struct, basename)
    remove_empty_sections_pass(struct)
    basename.split("_")
    if not options.skip_schema:
        validate_against_schema(struct, "alien.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def restructure_alien_pass(details, subtype):
    def _find_stat_block(details):
        path = []
        for detail in details:
            if detail["name"].find("CR") > -1:
                details.remove(detail)
                return detail, []
            else:
                result = _find_stat_block(detail["sections"])
                if result:
                    r, path = result
                    path.append(detail)
                    return r, path
        return None

    def _handle_family(details):
        for detail in details:
            if detail["name"].endswith("Family"):
                name = detail["name"]
                parts = name.split('"')
                assert len(parts) == 3, parts
                name = parts[1]
                details.remove(detail)
                return name

    def _handle_role(top):
        bs = BeautifulSoup(top["text"], "html.parser")
        imgs = bs.findAll("img")
        assert len(imgs) == 1, imgs
        img = imgs.pop()
        role = img["src"].split(".")[0].split("_").pop()
        img.extract()
        top["text"] = str(bs)
        return role

    def _handle_sources(top):
        bs = BeautifulSoup(top["text"], "html.parser")
        links = bs.findAll("a")
        retarr = []
        for link in links:
            retarr.append(extract_source(link))
            link.extract()
        assert str(bs).replace("<b>Source</b>", "").replace(",", "").strip() == "", str(bs)
        del top["text"]
        return retarr

    rest = []
    struct, path = _find_stat_block(details)
    top = path.pop()
    assert path == [], path
    details.remove(top)
    assert len(path) == 0, path
    parts = [p.strip() for p in struct["name"].split("CR")]
    name = parts.pop(0)
    cr = parts.pop(0)
    assert len(parts) == 0, parts
    struct["name"] = name
    struct["type"] = "alien"
    struct["game-obj"] = "Aliens"
    struct["stat_block"] = {"name": name, "type": "stat_block"}
    struct["stat_block"]["cr"] = cr
    family = _handle_family(details)
    if family:
        struct["stat_block"]["family"] = family
    struct["stat_block"]["role"] = _handle_role(top)
    struct["sources"] = _handle_sources(top)
    assert len(top) == 3, str(top)
    struct["sections"].extend(top["sections"])
    return struct


def top_matter_pass(struct):
    def _handle_sb_image(sb, bs):
        first = list(bs.children).pop(0)
        if first.name == "a" and first.find("img"):
            img = first.find("img")
            link = img["src"]
            image = link.split("\\").pop().split("%5C").pop()
            sb["image"] = {
                "type": "image",
                "name": sb["name"],
                "game-obj": "Monster",
                "image": image,
            }
            first.decompose()

    def _handle_xp(bs):
        xp = bs.find_all("b").pop(0)
        text = get_text(xp)
        assert text.startswith("XP "), xp
        xp.extract()
        return int(text.replace("XP ", "").replace(",", ""))

    def _handle_initiative(bs):
        # TODO: Check for parsables in modifiers
        text = list(bs.children)[-1]
        text.extract()
        modifiers = []
        if text.find("(") > -1:
            parts = [p.strip() for p in text.split("(")]
            assert len(parts) == 2, text
            text = parts.pop(0)
            mods = parts.pop()
            assert mods[-1] == ")", mods
            mparts = [m.strip() for m in mods[0:-1].split(",")]
            modifiers = modifiers_from_string_list(mparts)
        text = text.strip().replace("+", "")
        title = list(bs.children)[-1]
        assert str(title) == "<b>Init</b>", title
        title.extract()
        init = {"type": "stat_block_section", "subtype": "initiative", "value": int(text)}
        if len(modifiers) > 0:
            init["modifiers"] = modifiers
        return init

    def _handle_alignment(abbrev):
        alignment = universal_handle_alignment(abbrev)
        assert alignment, "Unrecognized alignment: %s" % abbrev
        return alignment

    def _handle_creature_basics(bs, sb):
        parts = list(filter(lambda e: len(e) > 0, str(bs).split("<br/>")))
        assert len(parts) in [1, 2], bs
        type = parts.pop()
        type_parts = type.split("(")
        assert len(type_parts) in [1, 2], str(type)
        basics = type_parts.pop(0).strip().split(" ")
        assert len(basics) in [3, 4], basics
        alignment = _handle_alignment(basics.pop(0))
        size = universal_handle_size(basics.pop(0).capitalize())
        sb["creature_type"] = _handle_creature_type(
            " ".join([b.capitalize() for b in basics]), type_parts
        )
        sb["creature_type"]["alignment"] = alignment
        sb["creature_type"]["size"] = size
        if "family" in sb:
            sb["creature_type"]["family"] = sb["family"]
            del sb["family"]
        if "cr" in sb:
            sb["creature_type"]["cr"] = sb["cr"]
            del sb["cr"]
        if "role" in sb:
            sb["creature_type"]["role"] = sb["role"]
            del sb["role"]
        assert len(type_parts) == 0, type_parts

        if len(parts) == 1:
            grafts = parts.pop()
            grafts = string_with_modifiers_from_string_list(
                split_maintain_parens(grafts, " "), "graft"
            )
            sb["creature_type"]["grafts"] = grafts

    def _handle_creature_type(ct, type_parts):
        subtype = None
        if len(type_parts) > 0:
            subtype = type_parts.pop()
            assert subtype[-1] == ")", "Malformed subtypes: %s" % subtype
            subtype = subtype.replace(")", "")
        return universal_handle_creature_type(ct, subtype)

    def _handle_perception(title, value):
        assert str(title) == "<b>Perception</b>", title
        text = str(value).strip()
        return universal_handle_perception(text)

    def _handle_special_senses(text):
        # TODO: Check for parsables in modifiers
        text = text.replace("<b>Senses</b>", "")
        parts = split_maintain_parens(text, ",")
        senses = []
        special_senses = universal_handle_special_senses(parts)
        return special_senses

    def _handle_aura(title, value):
        assert str(title) == "<b>Aura</b>", title
        return universal_handle_aura(value)

    text = list(filter(lambda e: e != "", struct.pop("text").split(";")))
    assert len(text) in [2, 3], text

    # Part 1
    bs = BeautifulSoup(text.pop(0), "html.parser")
    assert len(list(bs.children)) in [6, 7, 8, 9], str(list(bs.children))
    sb = struct["stat_block"]
    _handle_sb_image(sb, bs)
    xp = _handle_xp(bs)
    sb["initiative"] = _handle_initiative(bs)
    _handle_creature_basics(bs, sb)
    sb["creature_type"]["xp"] = xp

    # Part 2
    bs = BeautifulSoup(text.pop().strip(), "html.parser")
    [b.extract() for b in bs.find_all("br")]
    parts = list(bs.children)
    assert len(parts) in [2, 4], bs
    senses = universal_handle_senses()
    sb["senses"] = senses
    senses["perception"] = _handle_perception(parts.pop(0), parts.pop(0))
    if len(parts) > 0:
        sb["auras"] = _handle_aura(parts.pop(0), parts.pop(0))

    # Part 3
    if len(text) > 0:
        senses["special_senses"] = _handle_special_senses(text.pop(0))

    assert len(text) == 0, text


def fix_description_pass(details, struct):
    def _handle_detail(detail):
        _handle_sources(detail)
        _handle_name_links(detail)
        for section in detail["sections"]:
            _handle_detail(section)

    def _clear_br(children):
        while is_tag_named(children[0], "br"):
            children.pop(0)

    def _handle_sources(section):
        if "text" in section:
            bs = BeautifulSoup(section["text"], "html.parser")
            children = list(bs.children)
            if children[0].name == "b" and get_text(children[0]) == "Source":
                children = [c for c in children if str(c).strip() != ""]
                children.pop(0)
                book = ""
                _clear_br(children)
                while str(book).strip() == "" and children:
                    book = children.pop(0)
                source = extract_source(book)
                if children[0].name == "sup":
                    sup = children.pop(0)
                    errata = extract_link(sup.find("a"))
                    source["errata"] = errata[1]
                _clear_br(children)
                section["text"] = "".join([str(c) for c in children])
                sources = section.setdefault("sources", [])
                sources.append(source)

    def _handle_name_links(section):
        bs = BeautifulSoup(section["name"], "html.parser")
        links = get_links(bs, unwrap=True)
        section["name"] = str(bs)
        if links:
            assert len(links) == 1, links
            section["link"] = links.pop(0)

    if details:
        for detail in details:
            _handle_detail(detail)
        struct["sections"].extend(details)
    return


def defense_pass(struct):
    def _handle_hp(defense, text):
        parts = [t.strip() for t in text.split(";")]
        hp = {"type": "stat_block_section", "subtype": "hitpoints"}
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            bsparts = list(bs.children)
            assert len(bsparts) == 2, str(bs)
            name = bsparts.pop(0).get_text()
            value = int(bsparts.pop().strip())
            if name == "HP":
                hp["hp"] = value
            elif name == "RP":
                hp["rp"] = value
            else:
                assert False, bs
        defense["hp"] = hp

    def _handle_ac(defense, text):
        parts = [t.strip() for t in text.split(";")]
        ac = {"type": "stat_block_section", "subtype": "armor_class"}
        if len(parts) > 2:
            ac["modifiers"] = modifiers_from_string_list(parts[2:])
            parts = parts[0:2]
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            bsparts = list(bs.children)
            assert len(bsparts) == 2, str(bs)
            name = bsparts.pop(0).get_text()
            value = int(bsparts.pop().strip())
            assert name in ["EAC", "KAC"], name
            ac[name.lower()] = value
        defense["ac"] = ac

    def _handle_saves(defense, text):
        parts = [t.strip() for t in text.split(";")]
        saves = {"type": "stat_block_section", "subtype": "saves"}
        if len(parts) > 3:
            saves["modifiers"] = modifiers_from_string_list(parts[3:])
            parts = parts[0:3]
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            bsparts = list(bs.children)
            assert len(bsparts) == 2, str(bs)
            name = bsparts.pop(0).get_text()
            assert name in ["Fort", "Ref", "Will"], name
            save = {"name": name, "type": "stat_block_section", "subtype": "save"}
            valuetext = bsparts.pop().strip()
            if valuetext.find("(") > -1:
                vparts = [v.strip() for v in valuetext.split("(")]
                assert len(vparts) == 2, vparts
                valuetext = vparts.pop(0)
                modifiertext = vparts.pop(0).replace(")", "").strip()
                save["modifiers"] = modifiers_from_string_list(
                    [m.strip() for m in modifiertext.split(",")]
                )
            save["value"] = int(valuetext)

            saves[name.lower()] = save
        defense["saves"] = saves

    def _handle_defensive_abilities(defense, daparts):
        def _check_broken_text(names, value):
            tests = copy.copy(names)
            # Some mispellings found in the html
            tests.append("Immune")
            tests.append("Immunity")
            tests.append("Weakness")
            tests.append("Resistance")
            for t in tests:
                if t in value:
                    assert False, "Malformed %s: %s" % (name, value)

        for dapart in daparts:
            bs = BeautifulSoup(dapart, "html.parser")
            bsparts = list(bs.children)
            assert len(bsparts) == 2, str(bs)
            name = bsparts.pop(0).get_text()
            names = ["Defensive Abilities", "Immunities", "Resistances", "DR", "SR", "Weaknesses"]
            assert name in names, name
            value = bsparts.pop().strip()
            _check_broken_text(names, value)
            if name == "SR":
                defense["sr"] = universal_handle_sr(value)
            elif name == "DR":
                defense["dr"] = universal_handle_dr(value)
            elif name == "Weaknesses":
                defense["weaknesses"] = universal_handle_weaknesses(value)
            elif name == "Resistances":
                defense["resistances"] = universal_handle_resistances(value)
            elif name == "Immunities":
                defense["immunities"] = universal_handle_immunities(value)
            elif name == "Defensive Abilities":
                defense["defensive_abilities"] = universal_handle_defensive_abilities(value)
            else:
                name = name.lower().replace(" ", "_")
                values = split_maintain_parens(str(value), ",")
                defense[name] = values
                for value in values:
                    log_element("%s.log" % name.lower())("%s" % (value))
                assert False, "Unexpected section in Defensive Abilities: %s: %s" % (name, value)

    defense_section = find_section(struct, "Defense")
    defense_text = defense_section["text"]
    struct["sections"].remove(defense_section)
    parts = list(filter(lambda d: d != "", [d.strip() for d in defense_text.split("<br/>")]))
    defense = {"type": "stat_block_section", "subtype": "defense"}
    _handle_hp(defense, parts.pop(0))
    _handle_ac(defense, parts.pop(0))
    _handle_saves(defense, parts.pop(0))
    abilities = list(
        filter(lambda p: p != "", [part.strip() for part in ";".join(parts).split(";")])
    )
    if len(abilities) > 0:
        _handle_defensive_abilities(defense, abilities)
    struct["stat_block"]["defense"] = defense


def offense_pass(struct):
    def _handle_spell(offense, name, text):
        def _handle_spell_deets(deets):
            parts = split_comma_and_semicolon(deets)
            cl = parts.pop(0)
            assert cl.startswith("CL "), cl
            clparts = cl.split(" ")
            assert len(clparts) == 2, cl
            spells["caster_level"] = int(clparts[1][:-2])
            for part in parts:
                elements = part.split(" ")
                assert len(elements) == 2, part
                n, v = elements
                assert n in ["melee", "ranged"]
                spells[n] = int(v)

        def _handle_spell_list(text):
            def _handle_spell_list_deets(deets):
                deetparts = deets.split("(")
                if deetparts[0].startswith("At will"):
                    deetparts = [deets]
                if len(deetparts) == 1:
                    spell_list["count_text"] = deetparts[0].strip()
                elif len(deetparts) == 2:
                    spell_level_text = deetparts[0].strip()
                    spell_list["level_text"] = spell_level_text
                    if len(spell_level_text) == 1:
                        spell_list["level"] = int(spell_level_text)
                    elif len(spell_level_text) == 3:
                        spell_list["level"] = int(spell_level_text[:-2])
                    else:
                        assert False, deets
                    spell_list["count_text"] = deetparts[1].replace(")", "").strip()
                else:
                    assert False, deets
                count_text = spell_list["count_text"]
                if count_text.find("/") > -1 and count_text.find("(") == -1:
                    c, f = count_text.split("/")
                    spell_list["count"] = int(c)
                    spell_list["frequency"] = f
                else:
                    spell_list["frequency"] = count_text

            def _handle_spell(text):
                spell = {"type": "stat_block_section", "subtype": "spell"}
                bs = BeautifulSoup(text, "html.parser")
                bslist = list(bs.children)
                spell["name"] = bslist.pop(0).get_text().strip()
                if len(bslist) > 0:
                    exttext = "".join([str(b) for b in bslist]).strip()
                    assert exttext.startswith("(") and exttext.endswith(")"), exttext
                    exttext = exttext[1:-1]
                    extparts = split_maintain_parens(exttext, ";")
                    modlist = []
                    for extpart in extparts:
                        if extpart.endswith("level"):
                            level, _ = extpart.split(" ")
                            spell["level"] = int(level[:-2])
                        elif extpart.startswith("range"):
                            parts = extpart.split(" ")
                            parts.pop(0)
                            spell["range"] = universal_handle_range(" ".join(parts))
                        elif extpart.startswith("DC"):
                            spell["saving_throw"] = universal_handle_save_dc(extpart)
                        else:
                            modlist.append(extpart)
                    if len(modlist) > 0:
                        spell["modifiers"] = modifiers_from_string_list(modlist)
                return spell

            spell_list = {"type": "stat_block_section", "subtype": "spell_list", "spells": []}

            text = text.replace("–", "—")
            deets, listtext = text.split("—")
            _handle_spell_list_deets(deets)
            spelltexts = split_maintain_parens(listtext, ",")
            for spelltext in spelltexts:
                spell_list["spells"].append(_handle_spell(spelltext))
            spells["spell_list"].append(spell_list)

        spells = {"name": name, "type": "stat_block_section", "subtype": "spells", "spell_list": []}
        parts = list(filter(lambda d: d != "", [d.strip() for d in text.split("<br/>")]))
        deets = parts.pop(0)
        assert deets.startswith("(") and deets.endswith(")"), deets
        _handle_spell_deets(deets[1:-1])
        for part in parts:
            _handle_spell_list(part)
        offense.setdefault("spells", []).append(spells)

    def _handle_speeds(offense, _, text):
        def _handle_speed(text):
            speed = {"type": "stat_block_section", "subtype": "speed"}
            if text.find("(") > -1:
                move, modtext = text.split("(")
                text = move.strip()
                modtext = modtext.replace(")", "").strip()
                parts = split_comma_and_semicolon(modtext)
                if parts[0] in ["Ex", "Sp", "Su"]:
                    abbrev = parts.pop(0)
                    ability_types = {
                        "Ex": "Extraordinary",
                        "Sp": "Spell-Like",
                        "Su": "Supernatural",
                    }
                    speed["ability_type"] = ability_types[abbrev]
                    speed["ability_type_abbrev"] = abbrev
                    speed["maneuverability"] = parts.pop(0)
                if len(parts) > 0:
                    speed["modifiers"] = modifiers_from_string_list(parts)

            speed["name"] = text
            if text.find(" ft.") > -1:
                segments = text.replace(" ft.", "").split(" ")
                assert len(segments) in [1, 2], text
                if len(segments) == 1:
                    speed["movement_type"] = "walk"
                    speed["value"] = int(segments[0])
                else:
                    speed["movement_type"] = segments[0]
                    speed["value"] = int(segments[1])
            return speed

        speeds = {"type": "stat_block_section", "subtype": "speeds", "movement": []}
        parts = split_comma_and_semicolon(text)
        for part in parts:
            speeds["movement"].append(_handle_speed(part))
        offense["speed"] = speeds

    def _handle_attack(attack_type):
        def _handle_attack_impl(offense, _, text):
            def _handle_attack_start(start):
                if start in ["swarm attack", "troop attack", "distraction"]:
                    attack["name"] = start
                    return
                parts = start.split(" ")
                plus = parts.pop().replace("–", "-")
                try:
                    attack["count"] = int(parts[0])
                    parts.pop(0)
                except:
                    # No count at front
                    pass
                bs = BeautifulSoup(" ".join(parts), "html.parser")
                attack["name"] = get_text(bs)
                attack["bonus"] = int(plus)

            def _handle_attack_damage(damagetext):
                def _handle_damage_type(damage_type):
                    if len(damage_type) == 0:
                        return
                    parts = filter(lambda p: p != "", [p.strip() for p in damage_type.split(" ")])
                    values = []
                    for part in parts:
                        part = part.strip()
                        damage_types = {
                            "A": "Acid",
                            "B": "Bludgeoning",
                            "C": "Cold",
                            "E": "Electricity",
                            "F": "Fire",
                            "EF": "Electricity & Fire",
                            "force": "Force",
                            "P": "Piercing",
                            "S": "Slashing",
                            "So": "Sonic",
                            "random": "Random type",
                        }
                        comma = False
                        if part.find(",") > -1:
                            comma = True
                            part = part.replace(",", "").strip()
                        if part in damage_types:
                            values.append(damage_types[part])
                        elif part in ["&", "or"]:
                            values.append(part)
                        else:
                            assert False, damage_type
                        if comma:
                            values[-1] = values[-1] + ","
                    attack_damage["damage_type"] = " ".join(values)
                    attack_damage["damage_type_text"] = damage_type

                def _handle_effects(effecttext):
                    if effecttext.find("critical") > -1:
                        attack_damage["critical"] = True
                        effecttext = effecttext.replace("critical", "").replace("  ", " ").strip()
                    attack_damage["effect"] = effecttext

                damage = []
                damagetext = damagetext.replace(" plus ", "; ")
                damagetext = damagetext.replace(" and ", "; ")
                if damagetext.find("[") > -1:
                    damagetext, modtext = damagetext.split("[")
                    damagetext = damagetext.strip()
                    modtext = modtext.replace("]", "").strip()
                    modparts = split_comma_and_semicolon(modtext)
                    for modpart in modparts:
                        if modpart.find("DC") > -1:
                            attack["saving_throw"] = universal_handle_save_dc(modpart)
                        elif modpart.endswith("ft."):
                            parts = modpart.split(" ")
                            assert len(parts) == 2, "bad range: %s" % modpart
                            value = int(parts[0])
                            range = {
                                "type": "stat_block_section",
                                "subtype": "range",
                                "text": modpart,
                                "range": value,
                                "unit": "feet",
                            }
                            attack["range"] = range
                        else:
                            damagetext = damagetext + ";" + modpart

                if len(damagetext.strip()) > 0:
                    damageparts = [d.strip() for d in damagetext.split(";")]
                    for damagepart in damageparts:
                        attack_damage = {
                            "type": "stat_block_section",
                            "subtype": "attack_damage",
                        }
                        if damagepart.find("nonlethal") > -1:
                            attack_damage["nonlethal"] = True
                            damagepart = damagepart.replace("nonlethal", "").strip()
                            damagepart = damagepart.replace("  ", " ").strip()
                        if re.match("^\d+d\d+", damagepart):
                            ps = damagepart.split(" ")
                            attack_damage["formula"] = ps.pop(0)
                            damage_type = " ".join(ps)
                            _handle_damage_type(damage_type)
                        elif re.match(".* \d*d?\d+$", damagepart):
                            ps = damagepart.split(" ")
                            attack_damage["formula"] = ps.pop()
                            damagepart = " ".join(ps).strip()
                            _handle_effects(damagepart)
                        else:
                            _handle_effects(damagepart)
                        damage.append(attack_damage)
                    attack["damage"] = damage

            def _handle_space_reach(attacktext, attack):
                if not "Space" in attacktext:
                    return attacktext
                parts = [p.strip() for p in attacktext.split("Space")]
                assert len(parts) == 2, attacktext
                attacktext = parts.pop(0)
                space_reach = parts.pop(0)
                space, reach = split_maintain_parens(space_reach, ";")
                assert "ft." in space, space
                attack["space"] = space.strip()
                assert reach.startswith("Reach")
                reach = reach.replace("Reach", "").strip()
                attack["reach"] = _handle_reach_impl(reach)
                return attacktext

            melee = []
            attacks = split_maintain_parens(text, " or ")
            attacks = [a.replace("  ", " ") for a in attacks]
            for attacktext in attacks:
                attack = {
                    "type": "stat_block_section",
                    "subtype": "attack",
                    "attack_type": attack_type,
                }
                attacktext = _handle_space_reach(attacktext, attack)
                attackparts = attacktext.split("(")
                assert len(attackparts) in [1, 2], attacktext
                start = attackparts.pop(0).strip()
                _handle_attack_start(start)
                if len(attackparts) == 1:
                    _handle_attack_damage(attackparts.pop().replace(")", "").strip())
                melee.append(attack)
            offense[attack_type] = melee

        return _handle_attack_impl

    def _handle_multiattack(offense, name, text):
        textparts = split_maintain_parens(text, ",")
        text = " or ".join(textparts)
        _handle_attack("multiattack")(offense, name, text)

    def _handle_reach_impl(text):
        reach = {"type": "stat_block_section", "subtype": "reach"}
        if text.find("(") > -1:
            text, modtext = text.split("(")
            text = text.strip()
            modtext = modtext.replace(")", "").strip()
            parts = [p.strip() for p in modtext.split(",")]
            reach["modifiers"] = modifiers_from_string_list(parts)
        reach["value"] = text
        return reach

    def _handle_reach(offense, _, text):
        reach = _handle_reach_impl(text)
        offense["reach"] = reach

    def _handle_default(offense, name, text):
        offense[name.lower().strip()] = text

    def _handle_offensive_ability(offense, _, text):
        retlist = []
        parts = split_maintain_parens(text, ",")
        for text in parts:
            element = {"type": "stat_block_section", "subtype": "offensive_ability"}
            if text.find("(") > -1:
                text, modtext = text.split("(")
                text = text.strip()
                modtext = modtext.replace(")", "").strip()
                modparts = split_comma_and_semicolon(modtext, parenleft="[", parenright="]")
                element["modifiers"] = modifiers_from_string_list(modparts)

            element["name"] = text
            universal_handle_modifier_breakout(element)
            retlist.append(element)
        offense["offensive_abilities"] = retlist

    def _handle_default_list(sbsubtype, sbfield):
        # TODO pull out dice
        def __handle_default_list(offense, _, text):
            retlist = []
            parts = split_maintain_parens(text, ",")
            for text in parts:
                element = {"type": "stat_block_section", "subtype": sbsubtype}
                if text.find("(") > -1:
                    text, modtext = text.split("(")
                    text = text.strip()
                    modtext = modtext.replace(")", "").strip()
                    modparts = split_comma_and_semicolon(modtext, parenleft="[", parenright="]")
                    element["modifiers"] = modifiers_from_string_list(modparts)
                element["name"] = text
                retlist.append(element)
            offense[sbfield] = retlist

        return __handle_default_list

    offense_section = find_section(struct, "Offense")
    offense_text = offense_section["text"]
    struct["sections"].remove(offense_section)
    bs = BeautifulSoup(offense_text, "html.parser")
    output = break_out_subtitles(bs, "b")
    offense = {"type": "stat_block_section", "subtype": "offense"}
    for o in output:
        name, text = o
        text = filter_end(text, ["<br/>", ";"])
        if name.find("Spell") > -1:
            _handle_spell(offense, name, text)
        else:
            dispatch = {
                "Speed": _handle_speeds,
                "Melee": _handle_attack("melee"),
                "Ranged": _handle_attack("ranged"),
                "Multiattack": _handle_multiattack,
                "Space": _handle_default,
                "Reach": _handle_reach,
                "Offensive Abilities": _handle_offensive_ability,
                "Special Attacks": _handle_default_list("special_attack", "special_attacks"),
                "Connection": _handle_default,
            }
            dispatch[name](offense, name, text)
    struct["stat_block"]["offense"] = offense


def statistics_pass(struct):
    def _handle_stats(statistics, text):
        parts = [t.strip() for t in text.split(";")]
        assert len(parts) == 6, parts
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            bsparts = list(bs.children)
            assert len(bsparts) == 2, str(bs)
            name = bsparts.pop(0).get_text().lower()
            assert name in ["str", "dex", "con", "int", "wis", "cha"], name
            value = bsparts.pop().strip()
            if value in ["-", "—"]:
                statistics[name] = None
            else:
                statistics[name] = int(value)

    def _handle_feats(statistics, _, bs):
        assert str(bs).find(";") == -1, bs
        feats = string_with_modifiers_from_string_list(split_maintain_parens(str(bs), ","), "feat")
        statistics["feats"] = feats

    def _handle_skills(statistics, _, bs):
        parts = str(bs).split(";")
        assert len(parts) in [1, 2], bs
        skills = {"type": "stat_block_section", "subtype": "skills", "skills": []}
        if len(parts) > 1:
            modtext = parts.pop()
            skills["modifiers"] = modifiers_from_string_list(
                [m.strip() for m in modtext.split(",")]
            )
        parts = split_maintain_parens(parts.pop(), ",")
        for part in parts:
            skill = {
                "type": "stat_block_section",
                "subtype": "skill",
            }
            m = re.search(r"(.*) +([-—+]?[0-9]+) +\((.*)\)", part)
            if m:
                parts = m.groups()
                assert len(parts) == 3, parts
                skill["name"] = parts[0]
                skill["value"] = int(parts[1])
                modtext = parts[2]
                skill["modifiers"] = modifiers_from_string_list(
                    [m.strip() for m in modtext.split(",")]
                )
            else:
                m = re.search(r"(.*) +([-—+]?[0-9]+)", part)
                if m:
                    parts = m.groups()
                    assert len(parts) == 2, parts
                    skill["name"] = parts[0]
                    skill["value"] = int(parts[1])
                else:
                    assert False, "%s: %s" % (part, str(bs))
            skills["skills"].append(skill)
        statistics["skills"] = skills

    def _handle_languages(statistics, _, bs):
        text = str(bs)
        languages = universal_handle_languages(text)
        statistics["languages"] = languages

    def _handle_other_abilities(statistics, _, bs):
        abilities = string_with_modifiers_from_string_list(
            split_maintain_parens(str(bs), ","), "other_ability"
        )
        for ability in abilities:
            universal_handle_modifier_breakout(ability)
        statistics["other_abilities"] = abilities

    def _handle_gear(_, sb, bs):
        gear = universal_handle_gear(str(bs))
        sb["gear"] = gear

    def _handle_augmentations(_, sb, bs):
        parts = split_maintain_parens(str(bs), ",")
        augmentations = modifiers_from_string_list(parts, "augmentation")
        sb["augmentations"] = augmentations

    stats_section = find_section(struct, "Statistics")
    stats_text = stats_section["text"]
    struct["sections"].remove(stats_section)
    parts = list(filter(lambda d: d != "", [d.strip() for d in stats_text.split("<br/>")]))
    statistics = {"type": "stat_block_section", "subtype": "statistics"}
    _handle_stats(statistics, parts.pop(0))
    for part in parts:
        bs = BeautifulSoup(part, "html.parser")
        namebs = list(bs.children).pop(0)
        name = namebs.get_text()
        namebs.extract()
        dispatch = {
            "Feats": _handle_feats,
            "Skills": _handle_skills,
            "Languages": _handle_languages,
            "Other Abilities": _handle_other_abilities,
            "Gear": _handle_gear,
            "Augmentations": _handle_augmentations,
        }
        dispatch[name](statistics, struct["stat_block"], bs)

    struct["stat_block"]["statistics"] = statistics


def ecology_pass(struct):
    def _handle_environment(ecology, bs):
        assert str(bs).find(";") == -1, bs
        ecology["environment"] = str(bs).strip()

    def _handle_organization(ecology, bs):
        ecology["organization"] = str(bs).strip()

    stats_section = find_section(struct, "Ecology")
    if len(stats_section["sections"]) == 0 and "text" not in stats_section:
        struct["sections"].remove(stats_section)
        return
    stats_text = stats_section["text"]
    struct["sections"].remove(stats_section)
    parts = list(filter(lambda d: d != "", [d.strip() for d in stats_text.split("<br/>")]))
    ecology = {"type": "stat_block_section", "subtype": "ecology"}
    for part in parts:
        bs = BeautifulSoup(part, "html.parser")
        namebs = list(bs.children).pop(0)
        name = namebs.get_text()
        namebs.extract()
        dispatch = {"Environment": _handle_environment, "Organization": _handle_organization}
        dispatch[name](ecology, bs)
    struct["stat_block"]["ecology"] = ecology


def special_ability_pass(struct):
    def _handle_special_ability(data):
        # TODO: Handle links
        sa = {
            "type": "stat_block_section",
            "subtype": "special_ability",
        }
        name, text = data
        while text.endswith("<br/>"):
            text = text[:-5]
        sa["text"] = text
        name_parts = name.split("(")
        sa["name"] = name_parts.pop(0).strip()
        assert len(name_parts) == 1, bs
        sa_type = name_parts[0].replace(")", "").strip()
        ability_types = {"Ex": "Extraordinary", "Sp": "Spell-Like", "Su": "Supernatural"}
        assert sa_type in ability_types.keys()
        sa["ability_type"] = ability_types[sa_type]
        sa["ability_type_abbrev"] = sa_type
        return sa

    sa_section = find_section(struct, "Special Abilities")
    if sa_section:
        sa_text = sa_section["text"]
        struct["sections"].remove(sa_section)
        bs = BeautifulSoup(sa_text, "html.parser")
        output = break_out_subtitles(bs, "b")
        special_abilities = []
        for o in output:
            special_abilities.append(_handle_special_ability(o))
        struct["stat_block"]["special_abilities"] = special_abilities


def section_pass(struct):
    def _handle_affliction(section, remove):
        def _handle_save_dc(affliction):
            if "save" not in affliction:
                return affliction
            save = affliction["save"]
            affliction["saving_throw"] = universal_handle_save_dc(save)
            del affliction["save"]
            return affliction

        sec_text = section["text"]
        del section["text"]
        del section["sections"]
        remove.append(section)
        bs = BeautifulSoup(sec_text, "html.parser")
        output = break_out_subtitles(bs, "b")
        for element in output:
            name, text = element
            name = name.lower().strip()
            text = filter_end(text, ["<br/>", ";"])
            if name == "type":
                name = "affliction_type"
            section[name] = text
        section["type"] = "stat_block_section"
        section["subtype"] = "affliction"
        return _handle_save_dc(section)

    afflictions = []
    remove = []
    for section in struct["sections"]:
        bs = BeautifulSoup(section["text"].strip(), "html.parser")
        children = list(bs.children)
        if len(children) == 1:
            # Table, leave it in sections
            pass
        elif section["name"] not in ["Description"]:
            afflictions.append(_handle_affliction(section, remove))
    for s in remove:
        struct["sections"].remove(s)
    if len(afflictions) > 0:
        struct["stat_block"]["afflictions"] = afflictions


def find_section(struct, name):
    for s in struct["sections"]:
        if s["name"] == name:
            return s
