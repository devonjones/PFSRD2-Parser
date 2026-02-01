import json
import os
import re
import sys
from pprint import pprint

from bs4 import BeautifulSoup, NavigableString

from pfsrd.schema import validate_against_schema
from universal.creatures import (
    universal_handle_alignment,
    universal_handle_aura,
    universal_handle_creature_type,
    universal_handle_defensive_abilities,
    universal_handle_dr,
    universal_handle_gear,
    universal_handle_immunities,
    universal_handle_languages,
    universal_handle_range,
    universal_handle_resistances,
    universal_handle_save_dc,
    universal_handle_size,
    universal_handle_sr,
    universal_handle_weaknesses,
    write_creature,
)
from universal.files import char_replace, makedirs
from universal.universal import (
    break_out_subtitles,
    entity_pass,
    extract_link,
    extract_source,
    get_text,
    html_pass,
    link_modifiers,
    modifiers_from_string_list,
    number_with_modifiers,
    parse_number,
    parse_universal,
    remove_empty_sections_pass,
    string_values_from_string_list,
    string_with_modifiers,
    string_with_modifiers_from_string_list,
)
from universal.utils import (
    clear_tags,
    filter_end,
    find_list,
    split_comma_and_semicolon,
    split_maintain_parens,
)


def parse_creature(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(filename, subtitle_text=False, max_title=3, cssclass=options.cssclass)
    details = entity_pass(details)
    struct = restructure_creature_pass(details, options.subtype, basename)
    top_matter_pass(struct)
    fix_description_pass(details, struct)
    child_monster_pass(struct)
    defense_pass(struct)
    offense_pass(struct)
    tactics_pass(struct)
    statistics_pass(struct)
    ecology_pass(struct)
    special_ability_pass(struct)
    html_pass(struct)
    # log_html_pass(struct, basename)
    remove_empty_sections_pass(struct)
    if not options.skip_schema:
        validate_against_schema(struct, "creature.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def child_monster_pass(struct):
    def _validate_description(section):
        if not find_section(struct, "Description"):
            for s in section["sections"]:
                if s["name"] == "Description":
                    struct["sections"].append(s)
                    section["sections"].remove(s)
                    return

    def _handle_child_monster(section):
        section["stat_block"] = {
            "name": section["name"],
            "type": "stat_block",
        }
        section["type"] = "monster"
        section["game-obj"] = "Monsters"
        section["sources"] = struct["sources"]
        top_matter_pass(section)
        fix_description_pass([], section)
        defense_pass(section)
        offense_pass(section)
        tactics_pass(section)
        statistics_pass(section)
        ecology_pass(section)
        special_ability_pass(section)
        html_pass(section)
        _validate_description(section)
        remove_empty_sections_pass(section)
        struct["stat_block"]["sub_creature"] = section

    for section in struct["sections"]:
        titles = ["Defense", "Offense", "Statistics"]
        nope = False
        for title in titles:
            if title not in [s["name"] for s in section["sections"]]:
                nope = True
        if not nope:
            _handle_child_monster(section)
            struct["sections"].remove(section)


def fix_description_pass(details, struct):
    def _split_out_description(last_section):
        newparts = []
        newdescription = []
        parts = last_section["text"].split("<br/><br/>")
        found = False
        for part in parts:
            if "<b>" not in part:
                found = True
            if found:
                newdescription.append(part)
            else:
                newparts.append(part)
        newd = "<br/><br/>".join(newdescription)
        last_section["text"] = "<br/><br/>".join(newparts)
        if len(newd) > 0:
            newsection = {
                "name": "Description",
                "sections": [],
                "type": "section",
                "text": "<br/><br/>".join(newdescription),
            }
            struct["sections"].append(newsection)
            return

    desc_section = find_section(struct, "Description")
    if desc_section:
        if "text" in desc_section:
            return
        else:
            struct["sections"].remove(desc_section)
    last_section = struct["sections"][-1]
    _split_out_description(last_section)
    if details:
        struct["sections"].extend(details)
    return


def handle_default_list_of_strings(field):
    def _handle_default_list_impl(_, elem, text):
        text = filter_end(text, ["<br/>", ","])
        parts = split_comma_and_semicolon(text)
        elem[field.lower().strip()] = parts

    return _handle_default_list_impl


def handle_special_attacks(_, elem, text):
    # TODO pull out dice
    text = filter_end(text, ["<br/>", ","])
    retlist = []
    parts = split_comma_and_semicolon(text)
    for text in parts:
        element = {"type": "stat_block_section", "subtype": "special_attack"}
        if text.find("(") > -1:
            parts = text.split("(")
            text = parts.pop(0).strip()
            modtext = ",".join([p.replace(")", "").strip() for p in parts])
            modparts = split_comma_and_semicolon(modtext, parenleft="[", parenright="]")
            element["modifiers"] = modifiers_from_string_list(modparts)
        element["name"] = text
        retlist.append(element)
    elem["special_attacks"] = retlist


def handle_default(field):
    def _handle_default_impl(_, elem, text):
        text = filter_end(text, ["<br/>", ","])
        elem[field.lower().strip()] = text.strip()

    return _handle_default_impl


def handle_noop(name):
    def _handle_noop_impl(_, elem, text):
        pprint(f"{name}: {text}")
        # assert False

    return _handle_noop_impl


def restructure_creature_pass(details, subtype, basename):
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
            if detail["name"].endswith("Category"):
                name = detail["name"]
                parts = name.split('"')
                assert len(parts) == 3, parts
                name = parts[1]
                details.remove(detail)
                return name

    def _handle_aon(struct, basename):
        parts = basename.split("Display")
        assert len(parts) == 2
        struct["game-obj"] = f"{parts[0]}s"

    struct, path = _find_stat_block(details)
    short_desc = path.pop()
    assert path == [], path
    details.remove(short_desc)
    if "text" in short_desc:
        struct["html"] = short_desc["text"]
    struct["sections"].extend(short_desc["sections"])
    assert len(path) == 0, path
    parts = [p.strip() for p in struct["name"].split("CR")]
    name = parts.pop(0)
    cr = parts.pop(0)
    assert len(parts) == 0, parts
    struct["name"] = name
    struct["type"] = subtype
    # struct['game-obj'] = "Monsters"
    _handle_aon(struct, basename)
    struct["stat_block"] = {"name": name, "type": "stat_block"}
    struct["stat_block"]["cr"] = cr
    family = _handle_family(details)
    if family:
        struct["stat_block"]["family"] = family
    return struct


def top_matter_pass(struct):
    def _handle_sources(struct, _, text):
        bs = BeautifulSoup(text, "html.parser")
        links = bs.findAll("a")
        retarr = []
        for link in links:
            retarr.append(extract_source(link))
            link.extract()
        assert str(bs).replace(", ", "") == "", str(bs)
        struct["sources"] = retarr

    def _handle_xp(_, sb, text):
        if text == "—":
            sb["xp"] = None
        else:
            sb["xp"] = int(text.replace(",", "").strip())

    def _handle_cr(_, sb, text):
        sb["cr"] = text

    def _handle_initiative(_, sb, text):
        if text.endswith(";"):
            text = text[:-1]
        text = text.replace("–", "-")
        modifiers = []
        if text.find("(") > -1:
            parts = [p.strip() for p in text.split("(")]
            assert len(parts) == 2, text
            text = parts.pop(0)
            mods = parts.pop()
            assert mods[-1] == ")", mods
            mparts = [m.strip() for m in mods[0:-1].split(",")]
            modifiers = modifiers_from_string_list(mparts)

        init = {"type": "stat_block_section", "subtype": "initiative", "value": int(text)}
        if len(modifiers) > 0:
            init["modifiers"] = modifiers
        sb["initiative"] = init

    def _handle_senses(_, sb, text):
        text = text.replace("–", "-")
        parts = split_comma_and_semicolon(text)
        perclist = []
        newparts = []
        for part in parts:
            name = part.split(" ").pop(0)
            if name in ["Perception", "Listen", "Spot"]:
                perclist.append(part)
            else:
                newparts.append(part)
        if len(perclist) > 0:
            sb["perception"] = _handle_perception(perclist)
        if len(parts) > 0:
            sb["senses"] = modifiers_from_string_list(newparts, "sense")

    def _handle_perception(percskills):
        retarr = []
        for perkskill in percskills:
            parts = perkskill.split(" ")
            skillname = parts.pop(0).strip()
            perkskill = " ".join(parts)
            modifiers = []
            if perkskill.find("(") > -1:
                parts = perkskill.split("(")
                perkskill = parts.pop(0).strip()
                mtext = "(".join(parts).replace(")", "")
                modifiers = modifiers_from_string_list([m.strip() for m in mtext.split(",")])
                modifiers = link_modifiers(modifiers)
            perception = {
                "type": "stat_block_section",
                "subtype": skillname.lower(),
                "value": int(perkskill),
            }
            if len(modifiers) > 0:
                perception["modifiers"] = modifiers
            retarr.append(perception)
        return retarr

    def _handle_aura(_, sb, text):
        sb["auras"] = universal_handle_aura(text)

    def _handle_creature_basics(text, sb):
        subtypes = []
        if text.endswith(")"):
            type_parts = text.split("(")
            assert len(type_parts) == 2, text
            text = type_parts.pop(0)
            subtypes = [s.strip() for s in type_parts.pop().replace(")", "").split(",")]
        basics = text.strip().split(" ")
        creature_type = _handle_creature_type(basics, subtypes)
        sb["creature_type"] = creature_type
        creature_type["size"] = universal_handle_size(basics.pop().capitalize())
        _handle_alignment(creature_type, basics)
        if "family" in sb:
            creature_type["family"] = sb["family"]
            del sb["family"]
        if "cr" in sb:
            creature_type["cr"] = sb["cr"]
            del sb["cr"]
        if "xp" in sb:
            creature_type["xp"] = sb["xp"]
            del sb["xp"]
        if "grafts" in sb:
            creature_type["grafts"] = sb["grafts"]
            del sb["grafts"]

    def _handle_alignment(creature_type, basics):
        abbrev = basics[0]
        alignment = universal_handle_alignment(abbrev)
        if alignment:
            creature_type["alignment"] = alignment
        creature_type["alignment_text"] = " ".join(basics)

    def _handle_creature_type(basics, subtype):
        testtype = basics.pop().capitalize()
        if testtype == "Beast" or testtype == "Humanoid" and basics[-1] == "monstrous":
            testtype = basics.pop().capitalize() + " " + testtype
        subtype = ", ".join(subtype)
        return universal_handle_creature_type(testtype, subtype)

    def _handle_grafts(text):
        if text.find("(<i>Pathfinder") > -1:
            p = text.split("(<i>Pathfinder")
            assert len(p) == 2
            text = p.pop(0).strip()

        parts = split_maintain_parens(text, " ")
        newarr = []
        for part in parts:
            try:
                _ = int(part)
                newarr[-1] = newarr[-1] + " " + part
            except:
                if part.startswith("("):
                    newarr[-1] = newarr[-1] + " " + part
                else:
                    newarr.append(part)

        grafts = string_values_from_string_list(newarr, "graft", False)
        sb["grafts"] = grafts

    sb = struct["stat_block"]
    parts = struct.pop("text").split("<br/>")
    freetext = []
    for part in parts:
        bs = BeautifulSoup(part, "html.parser")
        output = break_out_subtitles(bs, "b")
        while len(output) > 0:
            title, text = output.pop(0)
            if title:
                dispatch = {
                    "Source": _handle_sources,
                    "XP": _handle_xp,
                    "CR": _handle_cr,
                    "Init": _handle_initiative,
                    "Senses": _handle_senses,
                    "Aura": _handle_aura,
                }
                dispatch[title](struct, sb, text)
            else:
                freetext.append(text)

    assert len(freetext) in [1, 2], freetext
    if len(freetext) == 2:
        _handle_grafts(freetext.pop(0))
    _handle_creature_basics(freetext.pop(0), sb)


def defense_pass(struct):
    def _handle_ac(_, defense, text):
        parts = text.replace("–", "-").split("(")
        text = parts.pop(0).strip()
        modtext = ",".join([p.replace(")", "").strip() for p in parts])

        parts = split_comma_and_semicolon(text)
        ac = {"name": "AC", "type": "stat_block_section", "subtype": "armor_class"}
        while len(parts) > 0:
            acparts = parts.pop(0).split(" ")
            assert len(acparts) in [1, 2], parts
            if len(acparts) == 1:
                ac["ac"] = int(acparts[0])
            else:
                ac[acparts[0].lower()] = int(acparts[1])
        ac["modifiers"] = modifiers_from_string_list([m.strip() for m in modtext.split(",")])
        defense["ac"] = ac

    def _handle_hp(_, defense, text):
        hp = {"name": "HP", "type": "stat_block_section", "subtype": "hitpoints"}
        parts = split_comma_and_semicolon(text)
        base = parts.pop(0)
        hptext, hdtext = base.split("(")
        if hptext.strip().endswith(" each"):
            hptext = hptext.replace(" each", "")
        hp["value"] = int(hptext.strip())
        hp["hit_dice"] = hdtext.replace(")", "").strip()
        hp["healing_abilities"] = modifiers_from_string_list(parts, "healing_ability")

    def _handle_save(name):
        def _handle_save_impl(_, defense, text):
            text = text.replace("–", "-")
            saves = defense.setdefault("saves", {"type": "stat_block_section", "subtype": "saves"})
            if text.endswith(",") or text.endswith("."):
                text = text[:-1]
            if text.find("(") > -1:
                tmplist = text.split("(")
                text = ", ".join([t.replace(")", "").strip() for t in tmplist])
            parts = split_comma_and_semicolon(text)
            value = parts.pop(0)
            save = {
                "name": name,
                "type": "stat_block_section",
                "subtype": "save",
                "value": int(value),
            }
            if len(parts) > 0:
                save["modifiers"] = modifiers_from_string_list(parts)

            saves[name.lower()] = save

        return _handle_save_impl

    def _handle_dr(_, defense, text):
        dr = universal_handle_dr(text)
        defense["dr"] = dr

    def _handle_sr(_, defense, text):
        sr = universal_handle_sr(text)
        defense["sr"] = sr

    def _handle_immunities(_, defense, text):
        immunities = universal_handle_immunities(text)
        defense["immunities"] = immunities

    def _handle_resistances(_, defense, text):
        resistances = universal_handle_resistances(text)
        defense["resistances"] = resistances

    def _handle_weaknesses(_, defense, text):
        weaknesses = universal_handle_weaknesses(text)
        defense["weaknesses"] = weaknesses

    def _handle_defensive_abilities(_, defense, text):
        bs = BeautifulSoup(text, "html.parser")
        sups = bs.find_all("sup")
        for sup in sups:
            sup.replace_with("")
        text = str(bs)

        das = universal_handle_defensive_abilities(text)
        defense["defensive_abilities"] = das

    sb = struct["stat_block"]
    defense_section = find_section(struct, "Defense")
    defense_text = defense_section["text"]
    struct["sections"].remove(defense_section)
    parts = list(filter(lambda d: d != "", [d.strip() for d in defense_text.split("<br/>")]))
    defense = {"name": "Defense", "type": "stat_block_section", "subtype": "defense"}
    for part in parts:
        bs = BeautifulSoup(part, "html.parser")
        output = break_out_subtitles(bs, "b")
        while len(output) > 0:
            title, text = output.pop(0)
            if title:
                dispatch = {
                    "AC": _handle_ac,
                    "hp": _handle_hp,
                    "Fort": _handle_save("Fort"),
                    "Ref": _handle_save("Ref"),
                    "Will": _handle_save("Will"),
                    "DR": _handle_dr,
                    "SR": _handle_sr,
                    "Immune": _handle_immunities,
                    "Weaknesses": _handle_weaknesses,
                    "Resist": _handle_resistances,
                    "Defensive Abilities": _handle_defensive_abilities,
                }
                dispatch[title](struct, defense, text)
            else:
                raise AssertionError(output)
    sb["defense"] = defense


def offense_pass(struct):
    def _handle_spell(offense, title, text):
        def _handle_spell_deets(deets):
            if deets == "":
                return
            parts = split_comma_and_semicolon(deets)
            cl = parts.pop(0)
            cl = cl.replace("caster level", "CL")
            assert cl.upper().startswith("CL "), cl
            clparts = cl.split(" ")
            assert len(clparts) == 2, cl
            try:
                spells["caster_level"] = int(clparts[1])
            except:
                spells["caster_level"] = int(clparts[1][:-2])
            for part in parts:
                if part.find("+") > -1:
                    elements = part.split(" ")
                    assert len(elements) in [2, 3], part
                    v = elements.pop()
                    n = " ".join(elements)
                    assert n in ["melee", "ranged", "concentration", "touch", "ranged touch"], n
                    n = n.replace(" ", "_")
                    spells[n] = int(v)
                else:
                    spells.setdefault("notes", []).append(part)

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
                        raise AssertionError(deets)
                    spell_list["count_text"] = deetparts[1].replace(")", "").strip()
                else:
                    raise AssertionError(deets)
                count_text = spell_list["count_text"]
                if count_text.find("PE") > -1:
                    pe, _ = count_text.split(" ")
                    spell_list["psychic_energy"] = int(pe)
                elif count_text.find("/") > -1 and count_text.find("(") == -1:
                    c, f = count_text.split("/")
                    if c.find(" ") > -1:
                        c, time = c.split(" ")
                        f = f"{time}/{f}"
                    spell_list["count"] = int(c)
                    spell_list["frequency"] = f
                else:
                    spell_list["frequency"] = count_text

            def _handle_spell(spell_list, text):
                spell = {"type": "stat_block_section", "subtype": "spell"}
                text = clear_tags(text, ["a"])
                bs = BeautifulSoup(text, "html.parser")
                bslist = list(bs.children)
                first = str(bslist[0]).strip()
                metamagic = [
                    "empowered",
                    "extended",
                    "heightened",
                    "maximized",
                    "merciful",
                    "reach",
                    "quickened",
                    "scarring",
                    "widened",
                    "quickened empowered",
                ]
                prefix = ""
                if first.endswith(":"):
                    note = str(bslist.pop(0)).strip()[:-1]
                    spell_list.setdefault("notes", []).append(note)
                elif first == "mass":
                    prefix = first + " "
                    bslist.pop(0)
                elif first in metamagic:
                    if "metamagic" in spell:
                        spell["metamagic"] = "{}, {}".format(spell["metamagic"], first)
                    else:
                        spell["metamagic"] = first
                    bslist.pop(0)
                spell["name"] = prefix + clear_tags(str(bslist.pop(0)), ["i"]).strip()
                if find_list(spell["name"], metamagic):
                    name = spell["name"]
                    mm = find_list(name, metamagic)
                    assert "metamagic" not in spell, text
                    name = name.replace(mm, "").replace("  ", " ").strip()
                    spell["name"] = name
                    spell["metamagic"] = mm
                if len(bslist) > 0:
                    exttext = "".join([str(b) for b in bslist]).strip()
                    if spell["name"] == "summon":
                        exttext = get_text(BeautifulSoup(exttext, "html.parser"))
                    if exttext.find("<sup>") > -1:
                        bs = BeautifulSoup(exttext, "html.parser")
                        notation = bs.sup.extract().get_text()
                        assert spell.get("notation") is None
                        spell["notation"] = notation
                        exttext = str(bs).strip()
                    if exttext.find("*") > -1:
                        assert spell.get("notation") is None, text
                        spell["notation"] = "*"
                        exttext = exttext.replace("*", "").strip()
                    if len(exttext.strip()) > 0:
                        if exttext.find(");") > -1:
                            exttext, note = exttext.split(");")
                            exttext = exttext + ")"
                            note = note.strip()
                            spell_list.setdefault("notes", []).append(note)
                        m = re.match(r"^([IVX]*) (.*)", exttext)
                        if m:
                            spell_version, exttext = m.groups()
                            spell["name"] = "{} {}".format(spell["name"], spell_version)
                        assert exttext.startswith("(") and exttext.endswith(")"), exttext
                        exttext = exttext[1:-1]
                        extparts = split_comma_and_semicolon(exttext, ";")
                        modlist = []
                        for extpart in extparts:
                            if extpart.endswith("level"):
                                level, _ = extpart.split(" ")
                                spell["level"] = int(level[:-2])
                            elif extpart.startswith("range "):
                                parts = extpart.split(" ")
                                parts.pop(0)
                                spell["range"] = universal_handle_range(" ".join(parts))
                            elif extpart.startswith("DC"):
                                spell["saving_throw"] = universal_handle_save_dc(extpart)
                            elif extpart.endswith("PE"):
                                pe, _ = extpart.split(" ")
                                spell["psychic_energy"] = int(pe)
                            else:
                                modlist.append(extpart)
                        if len(modlist) > 0:
                            spell["modifiers"] = modifiers_from_string_list(modlist)
                return spell

            spell_list = {"type": "stat_block_section", "subtype": "spell_list", "spells": []}
            text = text.replace("–", "—")
            text = text.replace("-", "—")

            tmplist = split_maintain_parens(text, "—")
            deets = tmplist.pop(0)
            listtext = "—".join(tmplist)
            _handle_spell_list_deets(deets)
            spelltexts = split_maintain_parens(listtext, ",")
            for spelltext in spelltexts:
                spell_list["spells"].append(_handle_spell(spell_list, spelltext))
            spells["spell_list"].append(spell_list)

        offense.setdefault(
            "magic", {"name": "Magic", "type": "stat_block_section", "subtype": "magic"}
        )
        spells = {
            "name": title,
            "type": "stat_block_section",
            "subtype": "spells",
            "spell_list": [],
        }
        parts = list(filter(lambda d: d != "", [d.strip() for d in text.split("<br/>")]))
        deets = parts.pop(0)
        assert deets.startswith("(") and deets.endswith(")"), deets
        _handle_spell_deets(deets[1:-1])
        for part in parts:
            _handle_spell_list(part)
        offense["magic"].setdefault("spells", []).append(spells)

    def _handle_speeds(_, offense, text):
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

            text = filter_end(text, ["<br/>", ";"])
            speed["name"] = text
            if text.find(" ft.") > -1:
                segments = text.replace(" ft.", "").split(" ")
                distance = int(segments.pop())
                if len(segments) == 0:
                    speed["movement_type"] = "walk"
                    speed["value"] = int(distance)
                else:
                    speed["movement_type"] = " ".join(segments)
                    speed["value"] = int(distance)
            return speed

        speeds = {
            "name": "Speed",
            "type": "stat_block_section",
            "subtype": "speeds",
            "movement": [],
        }
        parts = split_comma_and_semicolon(text)
        for part in parts:
            speeds["movement"].append(_handle_speed(part))
        offense["speed"] = speeds

    def _handle_attack(attack_type):
        def _handle_attack_impl(_, offense, text):
            def _handle_attack_start(start):
                if start in ["swarm attack", "troop attack", "swarm", "troop"]:
                    attack["name"] = start
                    return
                parts = start.split(" ")
                if "attack" in parts:
                    parts.remove("attack")
                if parts[-1] == "touch":
                    attack["touch"] = True
                    parts.pop()
                if parts[-1] == "incorporeal":
                    attack["incorporeal"] = True
                    parts.pop()
                if "melee" in parts:
                    parts.remove("melee")
                if "ranged" in parts:
                    parts.remove("ranged")
                if "swarm" in parts:
                    attack["swarm"] = True
                    parts.remove("swarm")
                if len(parts) > 0:
                    plus = parts.pop().replace("–", "-")
                    try:
                        attack["count"] = int(parts[0])
                        parts.pop(0)
                    except:
                        # No count at front
                        pass
                    bs = BeautifulSoup(" ".join(parts), "html.parser")
                    attack["name"] = get_text(bs)
                    attack["bonus"] = [int(p) for p in plus.split("/")]

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
                            _handle_effects(damage_type)
                            # assert False, damage_type
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
                damageparts = split_comma_and_semicolon(damagetext, parenleft="[", parenright="]")
                for damagepart in damageparts:
                    attack_damage = {
                        "type": "stat_block_section",
                        "subtype": "attack_damage",
                    }
                    if damagepart.find("[") > -1:
                        damagepart, modtext = damagepart.split("[")
                        damagepart = damagepart.strip()

                        modtext = modtext.replace("]", "").strip()
                        modparts = split_comma_and_semicolon(modtext)
                        for modpart in modparts:
                            if modpart.find("DC") > -1:
                                attack_damage["saving_throw"] = universal_handle_save_dc(modpart)
                            elif modpart.endswith("ft."):
                                attack_damage["range"] = universal_handle_range(modpart)
                            else:
                                damagepart = damagepart + ";" + modpart

                    if damagepart.find("nonlethal") > -1:
                        attack_damage["nonlethal"] = True
                        damagepart = damagepart.replace("nonlethal", "").strip()
                        damagepart = damagepart.replace("  ", " ").strip()
                    if re.match(r"^\d+d\d+", damagepart):
                        ps = damagepart.split(" ")
                        attack_damage["formula"] = ps.pop(0)
                        damage_type = " ".join(ps)
                        _handle_damage_type(damage_type)
                    elif re.match(r".* \d*d?\d+$", damagepart):
                        ps = damagepart.split(" ")
                        attack_damage["formula"] = ps.pop()
                        damagepart = " ".join(ps)
                        _handle_effects(damagepart)
                    else:
                        _handle_effects(damagepart)
                    if "formula" in attack_damage and attack_damage["formula"].find("/") > -1:
                        tmplist = attack_damage["formula"].split("/")
                        ad = tmplist.pop(0)
                        ac = "/".join(tmplist)
                        attack_damage["formula"] = ad
                        assert "critical_range" not in attack, attacktext
                        attack["critical_range"] = ac
                    damage.append(attack_damage)
                attack["damage"] = damage

            text = clear_tags(text, ["i"]).replace("<br/>", "")
            textparts = split_maintain_parens(text, ",")
            text = " or ".join(textparts)
            textparts = split_maintain_parens(text, " and ")
            text = " or ".join(textparts)
            melee = []
            attacks = split_maintain_parens(text, " or ")
            attacks = [a.replace("  ", " ") for a in attacks]
            for attacktext in attacks:
                attack = {
                    "type": "stat_block_section",
                    "subtype": "attack",
                    "attack_type": attack_type,
                }
                attackparts = attacktext.split("(")
                start = attackparts.pop(0).strip()
                attackdata = "; ".join(attackparts).replace(")", "").strip()
                _handle_attack_start(start)
                if len(attackparts) > 0:
                    _handle_attack_damage(attackdata)
                melee.append(attack)
            offense[attack_type] = melee

        return _handle_attack_impl

    def _handle_reach(_, offense, text):
        reach = {"type": "stat_block_section", "subtype": "reach"}
        text = filter_end(text, ["<br/>", ","])
        if text.find("(") > -1:
            text, modtext = text.split("(")
            text = text.strip()
            modtext = modtext.replace(")", "").strip()
            parts = [p.strip() for p in modtext.split(",")]
            reach["modifiers"] = modifiers_from_string_list(parts)
        reach["value"] = text
        offense["reach"] = reach

    def _handle_notation(name):
        def _handle_notation_impl(_, offense, text):
            magic = offense["magic"]
            notations = magic.setdefault("notations", [])
            text = text.replace("<br/>", " ").strip()
            text = filter_end(text, [";"]).strip()
            notation = {
                "name": name,
                "type": "stat_block_section",
                "subtype": "notation",
                "value": text.strip(),
            }
            notations.append(notation)

        return _handle_notation_impl

    def _handle_class_selection(name):
        def _clear_sup(text):
            bs = BeautifulSoup(text, "html.parser")
            sups = bs.find_all("sup")
            for sup in sups:
                sup.replace_with("")
            return str(bs)

        def _handle_notation_impl(_, offense, text):
            magic = offense["magic"]
            notations = magic.setdefault("class_selections", [])
            text = text.replace("<br/>", " ").strip()
            text = _clear_sup(text)
            values = split_comma_and_semicolon(text)
            notation = {
                "name": name,
                "type": "stat_block_section",
                "subtype": "class_selection",
                "values": values,
            }
            notations.append(notation)

        return _handle_notation_impl

    sb = struct["stat_block"]
    offense_section = find_section(struct, "Offense")
    offense_text = offense_section["text"]
    struct["sections"].remove(offense_section)
    offense = {"name": "Offense", "type": "stat_block_section", "subtype": "offense"}
    bs = BeautifulSoup(offense_text, "html.parser")
    output = break_out_subtitles(bs, "b")
    while len(output) > 0:
        title, text = output.pop(0)
        if title:
            if find_list(title, ["Spell", "Magic", "Extract", "Talent"]):
                _handle_spell(offense, title, text)
            else:
                dispatch = {
                    "Speed": _handle_speeds,
                    "Space": handle_default("space"),
                    "Reach": _handle_reach,
                    "Melee": _handle_attack("melee"),
                    "Ranged": _handle_attack("ranged"),
                    "Special Attacks": handle_special_attacks,
                    "D": _handle_notation("D"),
                    "S": _handle_notation("S"),
                    "M": _handle_notation("M"),
                    "*": _handle_notation("*"),
                    "Domains": _handle_class_selection("Domains"),
                    "Mystery": _handle_class_selection("Mystery"),
                    "Bloodline": _handle_class_selection("Bloodline"),
                    "Patron": _handle_class_selection("Patron"),
                    "Domain": _handle_class_selection("Domains"),
                    "Spirit": _handle_class_selection("Spirit"),
                    "Implements": _handle_class_selection("Implements"),
                    "Opposition Schools": _handle_class_selection("Opposition Schools"),
                    "Evocation": _handle_class_selection("Evocation"),
                    "Illusion": _handle_class_selection("Illusion"),
                    "Psychic Discipline": _handle_class_selection("psychic discipline"),
                    "Prohibited Schools": _handle_class_selection("Prohibited Schools"),
                    "Inquisition": _handle_class_selection("Inquisition"),
                }
                dispatch[title](struct, offense, text)
        else:
            raise AssertionError(output)
    sb["offense"] = offense


def tactics_pass(struct):
    def _handle_tactic(sb, title, text):
        tactics = sb.setdefault("tactics", [])
        tactics.append(
            {"type": "stat_block_section", "subtype": "tactic", "name": title, "text": text}
        )

    def _break_out_subtitles(bs):
        text = str(bs)
        first = True
        title = None
        for child in bs.children:
            if first:
                assert child.name == "b", f"malformed tactics: {str(bs)}"
                first = False
                title = child.extract().get_text().strip()
            else:
                break
        assert title, f"malformed tactics: {text}"
        return title, str(bs)

    sb = struct["stat_block"]
    tactics_section = find_section(struct, "Tactics")
    if tactics_section:
        tactics_text = tactics_section["text"]
        struct["sections"].remove(tactics_section)
        parts = list(filter(lambda d: d != "", [d.strip() for d in tactics_text.split("<br/>")]))
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            title, text = _break_out_subtitles(bs)
            titles = ["During Combat", "Before Combat", "Base Statistics", "Morale"]
            assert title in titles, f"Don't recognize tactic title: {title}"
            _handle_tactic(sb, title, text)


def statistics_pass(struct):
    def _handle_attribute(name):
        def _handle_attribute_impl(_, stats, text):
            text = filter_end(text, [",", "<br/>"]).strip()
            if text in ["-", "—"]:
                stats[name] = None
            else:
                stats[name] = int(text)

        return _handle_attribute_impl

    def _handle_bab(name):
        def _handle_bab_impl(struct, _, text):
            offense = struct["stat_block"]["offense"]
            if text.endswith(";"):
                text = text[:-1]
            elif text.endswith("<br/>"):
                text = text[:-5]
            elif text.endswith("<br/>"):
                raise AssertionError(f"Unrecognized string structure: {text}")
            offense[name.lower()] = number_with_modifiers(text.strip(), name.lower())

        return _handle_bab_impl

    def _handle_feats(_, statistics, text):
        assert text.find(";") == -1, text
        parts = split_maintain_parens(text.strip(), ",")
        feats = []
        for part in parts:
            bs = BeautifulSoup(part, "html.parser")
            notation = None
            sups = bs.find_all("sup")
            for sup in sups:
                sup.replace_with("")
                ntext = sup.extract().get_text()
                assert notation is None
                notation = ntext
            link = None
            if bs.a and bs.a["href"].startswith("FeatDisplay"):
                _, link = extract_link(bs.a)
                bs.a.replace_with(bs.a.get_text())
            part = str(bs)
            part = clear_tags(part, ["br"])
            feat = string_with_modifiers(part, "feat")
            if "modifiers" in feat:
                feat["modifiers"] = link_modifiers(feat["modifiers"])
            if link:
                feat["link"] = link
            if notation:
                feat["notation"] = notation
            feats.append(feat)
        statistics["feats"] = feats

    def _handle_tricks(_, statistics, text):
        text = clear_tags(text, ["br"])
        parts = split_maintain_parens(text, ",")
        tricks = string_with_modifiers_from_string_list(parts, "trick")
        statistics["tricks"] = tricks

    def _handle_skills(_, statistics, text):
        text = clear_tags(text, ["br"])
        if text.endswith(";"):
            text = text[:-1]
        assert ";" not in text, text
        skills = {"type": "stat_block_section", "subtype": "skills", "skills": []}
        assert "<a" not in text, text
        parts = split_maintain_parens(text, ",")
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
                skill["value"] = parse_number(parts[1])
                modtext = parts[2]
                skill["modifiers"] = modifiers_from_string_list(
                    [m.strip() for m in modtext.split(",")]
                )
            else:
                m = re.search(r"(.*) +([-–—+]?[0-9]+)", part)
                if m:
                    parts = m.groups()
                    assert len(parts) == 2, parts
                    skill["name"] = parts[0]
                    skill["value"] = parse_number(parts[1])
                else:
                    raise AssertionError(f"{part}: {text}")
            skills["skills"].append(skill)
        statistics["skills"] = skills

    def _handle_racial_modifiers(_, statistics, text):
        text = clear_tags(text, ["br"])
        rmods = modifiers_from_string_list(
            split_maintain_parens(text, ","), subtype="racial_modifier"
        )
        modifiers = statistics["skills"].setdefault("modifiers", [])
        modifiers.extend(rmods)

    def _handle_languages(_, statistics, text):
        text = clear_tags(text, ["br"])
        languages = universal_handle_languages(text)
        statistics["languages"] = languages

    def _handle_sq(_, statistics, text):
        text = clear_tags(text, ["br"])
        bs = BeautifulSoup(text, "html.parser")
        sups = bs.find_all("sup")
        for sup in sups:
            sup.replace_with("")
        text = str(bs)

        sqs = string_with_modifiers_from_string_list(
            split_maintain_parens(text, ","), "special_quality"
        )
        for sq in sqs:
            assert sq["name"].lower() != "tricks", f"Tricks should be broken out {sq}"
            assert (
                ";" not in sq["name"]
            ), f"Don't presently handle the SQ list having modifiers: {text}"
        statistics["special_qualities"] = sqs

    def _handle_gear(field):
        def _handle_gear_impl(struct, _, bs):
            text = str(bs)
            if text.endswith(";"):
                text = text[:-1]
            gear = universal_handle_gear(text)
            struct["stat_block"][field] = gear

        return _handle_gear_impl

    def _handle_boon(struct, _, bs):
        text = str(bs)
        if text.endswith(";"):
            text = text[:-1]
        struct["stat_block"]["boon"] = text

    sb = struct["stat_block"]
    stats_section = find_section(struct, "Statistics")
    stats_text = stats_section["text"]
    struct["sections"].remove(stats_section)
    statistics = {"type": "stat_block_section", "subtype": "statistics"}
    bs = BeautifulSoup(stats_text, "html.parser")
    output = break_out_subtitles(bs, "b")
    while len(output) > 0:
        title, text = output.pop(0)
        if title:
            dispatch = {
                "Str": _handle_attribute("str"),
                "Dex": _handle_attribute("dex"),
                "Con": _handle_attribute("con"),
                "Int": _handle_attribute("int"),
                "Wis": _handle_attribute("wis"),
                "Cha": _handle_attribute("cha"),
                "Base Atk": _handle_bab("bab"),
                "CMB": _handle_bab("cmb"),
                "CMD": _handle_bab("cmd"),
                "Feats": _handle_feats,
                "Tricks": _handle_tricks,
                "Skills": _handle_skills,
                "Racial Modifiers": _handle_racial_modifiers,
                "Racial Modifier": _handle_racial_modifiers,
                "Languages": _handle_languages,
                "SQ": _handle_sq,
                "Grapple": _handle_bab("grapple"),
                "Gear": _handle_gear("gear"),
                "Combat Gear": _handle_gear("combat_gear"),
                "Other Gear": _handle_gear("other_gear"),
                "Boon": _handle_boon,
            }
            dispatch[title](struct, statistics, text)
        else:
            raise AssertionError(output)
    sb["statistics"] = statistics
    struct["stat_block"]["statistics"] = statistics


def ecology_pass(struct):
    def _handle_ecology(ecology_section, dupe=False):
        stats_text = ecology_section["text"]
        parts = list(filter(lambda d: d != "", [d.strip() for d in stats_text.split("<br/>")]))
        ecology = {"name": "Ecology", "type": "stat_block_section", "subtype": "ecology"}
        for part in parts:
            dispatch = {
                "Environment": _handle_environment,
                "Organization": _handle_organization,
                "Treasure": _handle_treasure,
                "Advancement": _handle_advancement,
                "Level Adjustment": _handle_level_adjustment,
            }
            bs = BeautifulSoup(part, "html.parser")
            namebs = list(bs.children).pop(0)
            if type(namebs) is NavigableString:
                if namebs.split(" ").pop(0) in dispatch:
                    raise AssertionError(f"Ecology key missing <i> tag: {namebs}")
                else:
                    return
            name = namebs.get_text().strip()
            namebs.extract()
            dispatch[name](ecology, bs)
        if dupe:
            for key in ecology:
                if key in struct["stat_block"]["ecology"]:
                    assert ecology[key] == struct["stat_block"]["ecology"][key], "{} : {}".format(
                        ecology,
                        struct["stat_block"]["ecology"],
                    )
                else:
                    struct["stat_block"]["ecology"][key] = ecology[key]
        remove_section(struct, ecology_section, deep=True)
        struct["stat_block"]["ecology"] = ecology

    def _handle_environment(ecology, bs):
        ecology["environment"] = str(bs).strip()

    def _handle_organization(ecology, bs):
        # TODO: Handle links
        ecology["organization"] = str(bs).strip()

    def _handle_treasure(ecology, bs):
        # TODO: Parse treasure
        ecology["treasure"] = str(bs).strip()

    def _handle_advancement(ecology, bs):
        # TODO: Parse advancement
        ecology["advancement"] = str(bs).strip()

    def _handle_level_adjustment(ecology, bs):
        # TODO: Parse level_adjustment
        ecology["level_adjustment"] = str(bs).strip()

    found = False
    ecology_section = find_section(struct, "Ecology")
    if ecology_section:
        _handle_ecology(ecology_section)
        found = True
    ecology_section = find_section(struct, "Ecology", deep=True)
    if ecology_section:
        _handle_ecology(ecology_section, found)


def special_ability_pass(struct):
    def _handle_special_abilities(sa_section):
        sa_text = sa_section["text"]
        remove_section(struct, sa_section, deep=True)
        bs = BeautifulSoup(sa_text, "html.parser")
        parts = break_out_subtitles(bs, "b")
        special_abilities = struct["stat_block"].setdefault("special_abilities", [])
        other_abilities = struct["stat_block"].setdefault("other_abilities", [])
        for title, text in parts:
            sa = {
                "type": "stat_block_section",
                "subtype": "special_ability",
            }
            is_sa = _handle_special_ability_title(sa, title)
            _handle_special_ability_text(sa, text)
            if is_sa:
                _handle_affliction(sa)
                special_abilities.append(sa)
            else:
                sa["subtype"] = "other_ability"
                other_abilities.append(sa)
        if len(special_abilities) == 0:
            del struct["stat_block"]["special_abilities"]
        if len(other_abilities) == 0:
            del struct["stat_block"]["other_abilities"]

    def _handle_affliction(sa):
        affliction = {"type": "stat_block_section", "subtype": "affliction", "name": sa["name"]}
        sec_text = sa["text"]
        bs = BeautifulSoup(sec_text, "html.parser")
        parts = break_out_subtitles(bs, "i")
        if len(parts) == 0:
            return
        only_none = True
        for part in parts:
            affliction_sections = ["save", "frequency", "effect", "cure", "onset", None]
            if part[0] not in affliction_sections:
                return
            if part[0] is not None:
                only_none = False
        if only_none:
            return
        for part in parts:
            title, text = part
            if text.endswith(";"):
                text = text[:-1]
            if title == "save":
                affliction["saving_throw"] = universal_handle_save_dc(text)
            elif title is None:
                if ":" in text:
                    name, text = text.split(":")
                    affliction["name"] = name
                affliction["affliction_type"] = "{}; {}".format(sa["name"].strip(), text.strip())
            else:
                affliction[title] = text
        sa["affliction"] = affliction

    def _handle_special_ability_title(sa, title):
        if "(" not in title:
            sa["name"] = title
            return False
        name_parts = title.split("(")
        sa["name"] = name_parts.pop(0).strip()
        assert len(name_parts) == 1, title
        sa_type = name_parts[0].replace(")", "").strip()
        ability_types = {
            "Ex": "Extraordinary",
            "Sp": "Spell-Like",
            "Su": "Supernatural",
            "Sp, Su": "Spell-Like, Supernatural",
            "Ex, Sp": "Extraordinary, Spell-Like",
            "Ex, Su": "Extraordinary, Supernatural",
            "Ex, Sp, Su": "Extraordinary, Spell-Like, Supernatural",
        }
        if sa_type in ability_types:
            sa["ability_type"] = ability_types[sa_type]
            sa["ability_type_abbrev"] = sa_type
            return True
        return False

    def _handle_special_ability_text(sa, text):
        # TODO: Handle links
        while text.endswith("<br/>"):
            text = text[:-5]
        sa["text"] = text
        return sa

    sa_section = find_section(struct, "Special Abilities")
    if sa_section:
        _handle_special_abilities(sa_section)
    sa_section = find_section(struct, "Special Abilities", deep=True)
    if sa_section:
        _handle_special_abilities(sa_section)


def find_section(struct, name, deep=False):
    for s in struct["sections"]:
        if s["name"] == name:
            return s
        if deep and "sections" in s:
            result = find_section(s, name, deep)
            if result:
                return result


def remove_section(struct, section, deep=False):
    if "sections" in struct:
        if section in struct["sections"]:
            struct["sections"].remove(section)
        elif deep:
            for s in struct["sections"]:
                remove_section(s, section, deep)
