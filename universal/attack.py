"""Attack lines shared by every stat block that has them.

A Strike is published the same way wherever it appears — "tentacle +16
[+12/+8] (agile, magical), Damage 2d8+10 bludgeoning" for a creature, the same
shape without the multiple-attack bracket for a hazard — so it is parsed in one
place. Lifted verbatim from pfsrd2/creatures.py.

Reached directly by creatures and hazards, and indirectly by everything that
builds abilities, since universal/ability.py parses ability damage with it.
"""

import re

from bs4 import BeautifulSoup

from pfsrd2.trait import extract_starting_traits
from universal.universal import extract_link, get_links
from universal.utils import get_text, split_list


def parse_attack_damage(text):
    def _parse_attack_effect(parts):
        effect = {"type": "stat_block_section", "subtype": "attack_damage"}
        bs = BeautifulSoup(" ".join(parts), "html.parser")
        allA = bs.find_all("a")
        links = []
        for a in allA:
            _, link = extract_link(a)
            links.append(link)
        if links:
            effect["links"] = links
        effect["effect"] = get_text(bs).strip()
        return effect

    # A comma before a dice formula separates two damage instances
    # ("1d6 acid, 2d6 fire"). Commas inside a type ("bludgeoning, piercing, or
    # slashing") are not followed by dice, so they survive.
    text = re.sub(r",\s*(?=\d+d?\d*[\s+])", " and ", text.strip())
    ds = split_list(text, [" plus ", " and "])
    damages = []
    for d in ds:
        damage = {"type": "stat_block_section", "subtype": "attack_damage"}
        parts = d.split(" ")
        dice = parts.pop(0).strip()
        m = re.match(r"^\d*d\d*.?[0-9]*?$", dice)
        if not m:
            m = re.match(r"^\d*$", dice)
        if m:  # damage
            damage["formula"] = dice.replace("–", "-")
            damage_type = " ".join(parts)
            # A trailing clause after ";" is a note on the strike, not part of
            # the damage type — hazards publish "slashing; no multiple attack
            # penalty" this way.
            notes = []
            # Only a ";" outside the parentheses separates a trailing clause;
            # one inside belongs to the parenthetical note.
            depth, cut = 0, -1
            for i, ch in enumerate(damage_type):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == ";" and depth == 0:
                    cut = i
                    break
            if cut > -1:
                damage_type, trailing = damage_type[:cut], damage_type[cut + 1 :]
                damage_type = damage_type.strip()
                note_bs = BeautifulSoup(trailing.strip(), "html.parser")
                note_links = get_links(note_bs, unwrap=True)
                if note_links:
                    damage.setdefault("links", []).extend(note_links)
                notes.append(str(note_bs))
            if damage_type.find("(") > -1:
                parts = damage_type.split("(")
                damage_type = parts.pop(0).strip()
                paren_note = parts.pop(0).replace(")", "").strip()
                assert len(parts) == 0, f"Failed to parse damage: {text}"
                bs = BeautifulSoup(paren_note, "html.parser")
                links = get_links(bs, unwrap=True)
                if len(links) > 0:
                    damage.setdefault("links", []).extend(links)
                # A strike can carry both kinds of note; the parenthetical one
                # comes first in the source, so it leads.
                notes.insert(0, str(bs))
            if notes:
                damage["notes"] = "; ".join(n for n in notes if n)
            # A trailing separator is never part of a damage type.
            damage_type = damage_type.strip().rstrip(",;").strip()
            if damage_type.find("damage") > -1:
                # energy touch +36 [<a aonid="322" game-obj="Rules"><u>+32/+28</u></a>] (<a aonid="170" game-obj="Traits"><u>agile</u></a>, <a aonid="99" game-obj="Traits"><u>lawful</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>), <b>Damage</b> 5d8+18 positive or negative damage plus 1d6 lawful
                damage_type = damage_type.replace(" damage", "")
            if damage_type == "damage":
                # "2d10+13 damage (fire damage from the burning city, ...)" —
                # the type is spelled out in the note, not the type slot.
                damage_type = "varies"
            bs = BeautifulSoup(damage_type, "html.parser")
            allA = bs.find_all("a")
            links = []
            for a in allA:
                _, link = extract_link(a)
                links.append(link)
            if links:
                damage["links"] = links
            damage_type = get_text(bs).strip()
            if damage_type.startswith("persistent"):
                damage_type = damage_type.replace("persistent ", "")
                damage["persistent"] = True
            if damage_type.find("splash") > -1:
                damage_type = damage_type.replace("splash", "").strip()
                damage["splash"] = True
            damage["damage_type"] = damage_type
        else:  # effect
            parts.insert(0, dice)
            damage = _parse_attack_effect(parts)
        damages.append(damage)
    return damages


def remove_html_weapon(text, section):
    bs = BeautifulSoup(text, "html.parser")
    if list(bs.children)[0].name == "i":
        bs.i.unwrap()
    while bs.a:
        _, link = extract_link(bs.a)
        section.setdefault("links", []).append(link)
        bs.a.unwrap()
    return str(bs)


def parse_attack_action(parent_section, attack_type):
    def _handle_requirements(text):
        if "Requirements" in text:
            if "Effect" in text:
                parts = text.split("Effect")
                assert len(parts) == 2, text
                text = parts.pop()
                requirements = parts.pop()
                assert text.startswith("</b>"), text
                requirements += "</b>"
                text = text[4:].strip()
            else:
                parts = text.split("<b>Requirements</b>")
                assert len(parts) == 2, text
                requirements = "<b>Requirements</b>" + parts.pop()
                text = parts.pop()
            bs = BeautifulSoup(requirements, "html.parser")
            b_tags = bs.findAll("b")
            assert len(b_tags) in [1, 2], bs
            for b in b_tags:
                b.extract()
            requirements = get_text(bs).strip()
            if requirements.endswith(";"):
                requirements = requirements[:-1]
            section["requirement"] = requirements
        return text

    # tentacle +16 [<a aonid="322" game-obj="Rules"><u>+12/+8</u></a>] (<a aonid="170" game-obj="Traits"><u>agile</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>, <a aonid="192" game-obj="Traits"><u>reach 15 feet</u></a>), <b>Damage</b> 2d8+10 bludgeoning plus slime
    # trident +10 [<a aonid="322" game-obj="Rules"><u>+5/+0</u></a>], <b>Damage</b> 1d8+4 piercing
    # trident +7 [<a aonid="322" game-obj="Rules"><u>+2/-3</u></a>] (<a aonid="195" game-obj="Traits"><u>thrown 20 feet</u></a>), <b>Damage</b> 1d8+3 piercing
    # Sphere of Oblivion +37 [<a aonid="322" game-obj="Rules"><u>+32/+27</u></a>] (<a aonid="103" game-obj="Traits"><u>magical</u></a>), <b>Effect</b> see Sphere of Oblivion
    # piercing hymn +17 [<a aonid="322" game-obj="Rules"><u>+12/+7</u></a>] (<a aonid="83" game-obj="Traits"><u>good</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>, <a aonid="248" game-obj="Traits"><u>range 90 feet</u></a>, <a aonid="147" game-obj="Traits"><u>sonic</u></a>), <b>Damage</b> 4d6 sonic damage plus 1d6 good and deafening aria
    # crossbow +14 [<a aonid="322" game-obj="Rules"><u>+9/+4</u></a>] (<a aonid="248" game-obj="Traits"><u>range increment 120 feet</u></a>, <a aonid=\"254\" game-obj="Traits"><u>reload 1</u></a>), <b>Damage</b> 1d8+2 piercing plus crossbow precision
    text = parent_section["text"]
    del parent_section["text"]
    section = {
        "type": "stat_block_section",
        "subtype": "attack",
        "attack_type": attack_type,
        "name": parent_section["name"],
    }
    if "action_type" in parent_section:
        section["action_type"] = parent_section["action_type"]
        del parent_section["action_type"]
    if "traits" in parent_section:
        section["traits"] = parent_section["traits"]
        del parent_section["traits"]
    text = _handle_requirements(text)
    # Normalize: HTML5 may have space between sign and digits (e.g. "+ 14")
    text = re.sub(r"([+-])\s+(\d)", r"\1\2", text)

    # Old format: name +bonus [MAP link] (traits), Damage ...
    m = re.search(r"^(.*) ([+-]\d*) \[(.*)\] \((.*)\), (.*)$", text)
    has_map = True
    if not m:
        m = re.search(r"^(.*) ([+-]\d*) \[(.*)\], (.*)$", text)
    if not m:
        # HTML5 format: no MAP brackets
        has_map = False
        m = re.search(r"^(.*) ([+-]\d*) \((.*)\), (.*)$", text)
        if not m:
            m = re.search(r"^(.*) ([+-]\d*), (.*)$", text)
    assert m, f"Failed to parse: {text}"
    attack_data = list(m.groups())
    section["weapon"] = remove_html_weapon(attack_data.pop(0), section)
    attacks = [attack_data.pop(0)]

    if has_map:
        bs = BeautifulSoup(attack_data.pop(0), "html.parser")
        children = list(bs.children)
        assert len(children) == 1, f"Failed to parse: {text}"
        data, link = extract_link(children[0])
        attacks.extend(data.split("/"))
        attacks = [int(a) for a in attacks]
        section["bonus"] = {
            "type": "stat_block_section",
            "subtype": "attack_bonus",
            "link": link,
            "bonuses": attacks,
        }
    else:
        attacks = [int(a) for a in attacks]
        section["bonus"] = {
            "type": "stat_block_section",
            "subtype": "attack_bonus",
            "bonuses": attacks,
        }

    damage = attack_data.pop().split(" ")
    _ = damage.pop(0)
    section["damage"] = parse_attack_damage(" ".join(damage).strip())

    if len(attack_data) > 0:
        _, traits = extract_starting_traits(f"({attack_data.pop()})")
        assert "traits" not in section
        section["traits"] = traits
    assert len(attack_data) == 0, f"Failed to parse: {text}"
    parent_section["attack"] = section
