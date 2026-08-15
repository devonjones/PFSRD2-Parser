"""Hazard parser.

Hazards are creature-shaped stat blocks: a level badge ("Hazard 3"), traits,
a run of bold-labelled fields, and abilities that carry an action type plus
Trigger/Effect. The whole stat block arrives from parse_universal as one flat
HTML blob of `<b>Label</b> value` runs separated by `<br/>` and `<hr/>`.

Built on the existing parsers rather than beside them:

  pipeline shape   pfsrd2/feat.py — the closest existing shape (level badge,
                   traits, bold fields, an action span in the title)
  traits           universal.universal.is_trait
  bold fields      universal.universal.extract_bold_fields
  abilities        universal.ability.parse_abilities_from_nodes
  defenses         universal.utils.parse_defense_line, shared with creatures

Brittle by design: FIELD_LABELS is closed. A bold label outside it is treated
as the start of an ability, and an ability that yields nothing fails the parse
rather than silently dropping a chunk of the stat block.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup

from pfsrd2.action import extract_action_type
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.traits import fetch_trait_by_name, trait_db_pass
from universal.ability import DEFAULT_ADDON_LABELS, parse_abilities_from_nodes
from universal.attack import parse_attack_action
from universal.creatures import universal_handle_save_dc
from universal.files import char_replace, disambiguated_filename, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.monster_ability import monster_ability_db_pass
from universal.universal import (
    RESULT_LABELS,
    aon_pass,
    build_object,
    drop_marker_sections,
    edition_from_alternate_link,
    edition_pass,
    entity_pass,
    extract_bold_fields,
    extract_source_from_bs,
    extract_span_traits,
    game_id_pass,
    get_links,
    handle_alternate_link,
    link_objects,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
    take_stat_block_text,
)
from universal.utils import (
    content_filter,
    extract_pfs_availability,
    extract_pfs_note,
    flatten_fields,
    get_text,
    handle_trait_value,
    nodes_after,
    normalize_pfs_to_object,
    parse_defense_line,
    plain_text,
    remove_empty_fields,
    sidebar_filter,
    strip_block_tags,
)

# Structural stat-block labels. Anything bold outside this set starts an
# ability — that is the whole disambiguation, so the set must stay closed.
FIELD_LABELS = {
    "Complexity",
    "Stealth",
    "Description",
    "Disable",
    "Reset",
    "Routine",
    "AC",
    "Fort",
    "Ref",
    "Will",
    "HP",
    "Hardness",
    "Immunities",
    "Weaknesses",
    "Resistances",
    "Speed",
    "Saving Throw",
    "Maximum Duration",
    "Bypass",
    "Special",
}

# "Trapdoor Hardness", "Scythe Blade HP", "HP (per mannequin)" — a hazard whose
# named parts have their own durability. The component keeps its own entry
# instead of overwriting the hazard's.
_COMPONENT_STATS = "Hardness|HP|BT|AC|Fort|Ref|Will|Immunities|Weaknesses|Resistances"
_COMPONENT_DURABILITY = re.compile(rf"^(?P<component>.+?)\s+(?P<stat>{_COMPONENT_STATS})$")

# Same names creature.schema.json uses, so a consumer sees one save shape
# across both content types.
_SAVE_LABELS = {"Fort": "Fort", "Ref": "Ref", "Will": "Will"}

# "<b>Spout</b> HP 32" — a component whose name and stat are separate bolds,
# so the name reads as an ability and the stat as its body.
_SPLIT_COMPONENT = re.compile(rf"^\s*(?:{_COMPONENT_STATS})\b", re.I)

_DEFENSE_SUBTYPES = {
    "Immunities": "immunity",
    "Weaknesses": "weakness",
    "Resistances": "resistance",
}

_LEVEL_RE = re.compile(r"Hazard\s+(-?\d+)", re.I)

# The break threshold is published inside the HP value ("90 (BT 45)"), never
# as its own bold label.
_BREAK_THRESHOLD = re.compile(r"BT\s+(-?\d+)")

# A hazard's degrees of success belong to the ability that rolled the save, not
# beside it. Without these, every bold "Success" starts a new ability, because
# an unrecognised bold is what starts one.
_HAZARD_ADDON_LABELS = DEFAULT_ADDON_LABELS | set(RESULT_LABELS)


def parse_hazard(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=4,
        cssclass="main",
        # content_filter is used bare, unlike feat.py which also moves the level
        # badge span out of the h1. A hazard's badge IS its level, and
        # parse_universal turns it into `subname`, which restructure reads.
        pre_filters=[content_filter, sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    alternate_link = handle_alternate_link(details, allow_multiple=True)

    struct = restructure_hazard_pass(details)
    if alternate_link:
        struct["alternate_link"] = (
            alternate_link[0] if isinstance(alternate_link, list) else alternate_link
        )

    hazard = find_hazard(struct)
    bs = BeautifulSoup(hazard["text"], "html.parser")
    struct["pfs"] = extract_pfs_availability(bs)
    extract_pfs_note(bs, struct)
    hazard["text"] = str(bs)
    normalize_pfs_to_object(struct)

    hazard_extract_pass(struct)
    source_pass(struct, find_hazard)
    aon_pass(struct, basename)
    restructure_pass(struct, "hazard", find_hazard)
    struct["edition"] = edition_from_alternate_link(struct) or edition_pass(struct["sections"])
    drop_marker_sections(struct)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    # A hazard ability can name a universal monster ability; the same DB pass
    # creatures use matches it by name and fills in the full record.
    monster_ability_db_pass(struct)
    trait_db_pass(struct, pre_process=_hazard_trait_pre_process)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct, extra_tags=["h2", "h3", "u"])
    universal_markdown_pass(struct, struct["name"], "")
    remove_empty_fields(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "hazard.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_hazard(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2, sort_keys=True))


def _hazard_trait_pre_process(trait, parent, curs):
    """Split a magnitude off a trait name before the DB lookup.

    A hazard's Strike can carry "thrown 10 feet"; the traits table knows
    "thrown". Same hook equipment uses for the same reason. The split is only
    kept if it actually resolves — otherwise an unknown two-word trait would
    be quietly reshaped into a plausible-looking name instead of failing.
    """
    if fetch_trait_by_name(curs, trait["name"]) or " " not in trait["name"]:
        return False
    original = dict(trait)
    handle_trait_value(trait)
    if not fetch_trait_by_name(curs, trait["name"]):
        trait.clear()
        trait.update(original)
    return False


def find_hazard(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "hazard":
            return section
    raise AssertionError(f"No hazard stat block found in {struct.get('name')!r}")


def write_hazard(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = disambiguated_filename(jsondir, struct, "hazard")
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=2, sort_keys=True)


def restructure_hazard_pass(details):
    """Build the hazard structure from parse_universal output.

    parse_universal yields the hazard as one entry whose `name` is the title
    link and `subname` is the level badge ("Hazard 3"). The stat block arrives
    as flat HTML in one of two places: legacy pages wrap it in a "Legacy
    Content" section, remastered pages put it on the entry itself.
    """
    assert details, "parse_universal returned nothing — the page has no parsable content"
    first = details[0]
    rest = details[1:]

    name = get_text(BeautifulSoup(first.get("name", ""), "html.parser")).strip()
    assert name, f"Could not extract hazard name from {first.get('name')!r}"

    # 'sections' must exist even when empty: the universal passes walk section
    # trees unconditionally (see CLAUDE.md, "The 'sections' Key Requirement").
    sb = build_object("stat_block_section", "hazard", name, {"sections": []})
    sb["type"] = "stat_block_section"
    sb["subtype"] = "hazard"

    subname = first.get("subname") or ""
    match = _LEVEL_RE.search(subname)
    assert match, f"No hazard level in subname {subname!r} for {name!r}"
    sb["level"] = int(match.group(1))

    # Two layouts: legacy pages wrap the stat block in a "Legacy Content"
    # section, remastered ones carry the text on the entry itself.
    body_sections = list(first.get("sections", []))
    # Carrier first, matching the original precedence: when a page carries
    # text in both places the wrapped stat block is the real one.
    text = take_stat_block_text(body_sections)
    if text is None:
        text = first.get("text")
    assert text, f"No stat block text found for {name!r}"
    sb["text"] = text

    top = {"name": name, "type": "hazard", "sections": [sb]}
    top["sections"].extend(body_sections)
    for r in rest:
        assert isinstance(r, dict), f"Unstructured trailing detail on {name!r}: {r!r}"
        top["sections"].append(r)
    return top


_INLINE_REF = re.compile(r"^[A-Z]?\d+[a-z]?$")


def _unwrap_inline_refs(bs):
    """Demote a bolded reference number mid-sentence to plain text.

    Adventure hazards bold the map square a trigger fires in ("area <b>C2</b>",
    also sub-lettered forms like <b>B4a</b>), the DC of a save, and the entries
    of a numbered effect list. Every other bold in a stat block is a field or
    ability label, so the ability parser reads these as labels — "C2" becomes
    an ability and its trailing "or" an action type. 59 hazard files bold a map
    square alone, so this belongs in code rather than in the HTML.
    """
    for tag in list(bs.find_all("b")):
        if not _INLINE_REF.match(tag.get_text().strip()):
            continue
        # Only mid-sentence, where the source actually writes these. A bold
        # "C2" that starts a run is a label this parser has not seen, and
        # unwrapping it on shape alone would hide that.
        lead = tag.previous_sibling
        if not isinstance(lead, str) or not lead.strip():
            continue
        tag.unwrap()


def hazard_extract_pass(struct):
    """Pull traits, bold fields and abilities out of the stat block blob."""
    hazard = find_hazard(struct)
    bs = BeautifulSoup(hazard.pop("text"), "html.parser")

    # Before the <hr> sweep: decomposing a rule re-parents the bold that
    # followed it onto the preceding text, which would let a bold starting a
    # run pass the mid-sentence guard below.
    _unwrap_inline_refs(bs)

    # Separators carry no data, and leaving them in bleeds "---" into field
    # values and ability effects once markdown runs.
    for rule in list(bs.find_all("hr")):
        rule.decompose()
    extract_span_traits(hazard, bs)
    _extract_sources(hazard, bs)
    # Fields first: the ability grab takes everything from the first non-field
    # bold onward, so a trailing Reset would be swallowed into the last ability.
    _extract_component_durability(hazard, bs)
    _assert_no_duplicate_labels(hazard, bs)
    extract_bold_fields(hazard, bs, FIELD_LABELS, decompose=True)
    _extract_abilities(hazard, bs)
    # Links are unwrapped per field AFTER abilities are parsed: universal.ability
    # reads an ability's trait links out of the live tags, so a global unwrap
    # beforehand strips the traits it needs.
    flatten_fields(hazard, _TEXT_FIELDS)
    links = get_links(bs, unwrap=True)
    if links:
        hazard.setdefault("links", []).extend(links)
    _structure_fields(hazard)

    # Residual prose the fields and abilities did not claim is real published
    # content, so it is kept — flattened the same way field values are, since
    # the markdown pass accepts no tags.
    for span in bs.find_all("span", {"class": "action"}):
        span.unwrap()
    leftover = re.sub(r"(<br/?>|<hr/?>|\s|;|,)+", "", str(bs).strip())
    if leftover:
        hazard["text"] = str(bs)


def _extract_sources(hazard, bs):
    """Sources come from the shared extractor, which builds the structured
    dict and removes the nodes; extract_bold_fields would only capture the
    raw HTML."""
    source = extract_source_from_bs(bs)
    assert source, f"No source found for hazard {hazard.get('name')!r}"
    hazard["sources"] = [source]


def _assert_no_duplicate_labels(hazard, bs):
    """A stat-block label may appear once.

    extract_bold_fields assigns rather than accumulates, so a repeated label
    means the second value silently replaced the first — and a hazard whose
    component publishes its own HP and saves ends up wearing them, which reads
    as plausible data rather than as a failure.
    """
    seen = set()
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if label not in FIELD_LABELS:
            continue
        assert label not in seen, (
            f"{label!r} appears twice in the stat block of {hazard.get('name')!r} — the "
            "second value would silently replace the first; if it belongs to a named "
            'part, the source should label it as one ("Reflection HP")'
        )
        seen.add(label)


_ATTACK_TYPES = {"Melee", "Ranged"}


def _looks_like_traits(inner):
    """Does a parenthetical hold traits rather than a note?

    Traits are short and comma-separated; a note is a sentence. The
    distinction matters because an unlinked trait has to be fixed in the
    source, while a note has to be kept.
    """
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    return bool(parts) and all(len(p.split()) <= 4 and " the " not in f" {p} " for p in parts)


def _starts_next_entry(node):
    """Does this node begin the entry after the attack line?

    The Damage and Effect labels belong to the attack, so the run continues
    through them. Anything else in bold ends it — including a bold nested in
    a link, which is how the source writes an ability whose name is a link
    ("<a href=MonsterAbilities...><b>Constrict</b></a>"). Checking only for a
    bold sibling misses those and swallows the ability.
    """
    if getattr(node, "name", None) is None:
        return False
    # Only inside a link. Descending into any tag stops the run at a <ul>
    # whose <li> headers are bold, which hands the Strike's own list to
    # whichever ability came before it.
    bold = node if node.name == "b" else (node.find("b") if node.name == "a" else None)
    if bold is None:
        return False
    return get_text(bold).strip() not in ("Damage", "Effect")


def _extract_attacks(hazard, bs):
    """Pull Melee/Ranged Strikes out before the ability parser sees them.

    A hazard publishes a Strike in the creature's grammar, minus the
    multiple-attack bracket no hazard prints — "<b>Melee</b> [one-action] jaws
    +17 (agile), <b>Damage</b> 2d6" — so the creature parser handles it
    unchanged. It has to run first: the ability parser unwraps every <a>, which
    would strip the trait markup the attack line carries, and splits
    <b>Damage</b> off into its own field.
    """
    attacks = []
    for bold in list(bs.find_all("b")):
        name = get_text(bold).strip()
        if name not in _ATTACK_TYPES:
            continue
        # The Damage/Effect label belongs to the attack line, so the run
        # continues through it and stops at the next unrelated bold.
        run = []
        node = bold.next_sibling
        while node is not None:
            if _starts_next_entry(node):
                break
            run.append(node)
            node = node.next_sibling
        section = {"name": name, "text": "".join(str(n) for n in run).strip()}
        text, action = extract_action_type(section["text"])
        if action:
            section["action_type"] = action
        section["text"] = text.strip()
        line = section["text"]
        assert line.count("(") == line.count(")"), (
            f"{name} of hazard {hazard.get('name')!r} has an unbalanced parenthesis in "
            f"{plain_text(line)!r} — the attack run stopped part way through the line"
        )
        parse_attack_action(section, name.lower())
        attack = section["attack"]
        assert attack.get(
            "weapon"
        ), f"{name} of hazard {hazard.get('name')!r} parsed no weapon from {line!r}"
        assert "(" not in attack["weapon"], (
            f"{name} of hazard {hazard.get('name')!r} parsed the weapon as "
            f"{attack['weapon']!r} — a parenthetical ended up inside the name"
        )
        # extract_starting_traits only objects to a parenthetical where SOME
        # traits are linked; one with none silently yields nothing. The fix for
        # an unlinked trait is to link it in the source, so say so. Only the
        # parenthetical before the Damage label holds traits — later ones are
        # notes on the damage.
        # A parenthetical the attack parser did not turn into traits is either
        # a source problem or a note, and which one is decidable rather than
        # guessable: if it carries trait links, they ARE traits and the line
        # shape defeated the parser; if it carries none, judge the plain text.
        head = re.split(r"(?:<b>\s*)?\b(?:Damage|Effect)\b", line)[0]
        paren = re.search(r"\(([^)]*)\)", head)
        if paren and paren.group(1).strip() and not attack.get("traits"):
            inner = paren.group(1)
            assert "Traits.aspx" not in inner and 'game-obj="Traits"' not in inner, (
                f"{name} of hazard {hazard.get('name')!r} publishes ({plain_text(inner)}) "
                "as linked traits but the attack parser did not read them — the line "
                "puts the parenthetical somewhere it does not expect, so fix the order "
                "in the source"
            )
            assert not _looks_like_traits(plain_text(inner)), (
                f"{name} of hazard {hazard.get('name')!r} publishes ({plain_text(inner)}) "
                "with no trait links, so the traits are lost — link them in the source"
            )
            # A note in the traits slot ("can target any creature in area A8")
            # is published content; parse_attack_action discards it with the
            # traits it could not find.
            attack["note"] = plain_text(inner)
        attacks.append(attack)
        for node in run:
            node.extract()
        bold.decompose()
    if attacks:
        hazard["attacks"] = attacks


def _extract_abilities(hazard, bs):
    """Everything from the first non-field bold label onward is an ability.

    Hazard actions are published exactly like creature abilities — a bold name,
    an action span, then Trigger/Effect — so universal.ability does the work.
    """
    _extract_attacks(hazard, bs)

    start = None
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if label in FIELD_LABELS:
            continue
        start = bold
        break
    if start is None:
        return

    nodes = []
    node = start
    while node:
        following = node.next_sibling
        nodes.append(node.extract())
        node = following

    consumed = set()
    abilities = parse_abilities_from_nodes(
        nodes, addon_labels=_HAZARD_ADDON_LABELS, consumed=consumed
    )
    assert abilities, (
        f"Bold label {get_text(start).strip()!r} on {hazard.get('name')!r} is not a known "
        "field and did not parse as an ability — add it to FIELD_LABELS or fix the split"
    )
    for ability in abilities:
        # Both halves of the split: "<b>Spout</b> HP 32" leaves the stat in the
        # body, "<b>HP (per mannequin)</b> 70" leaves it in the name.
        body = plain_text(ability.get("text") or ability.get("effect") or "")
        for part, where in ((ability["name"], "name"), (body, "body")):
            assert not _SPLIT_COMPONENT.match(part), (
                f"Ability {ability['name']!r} of hazard {hazard.get('name')!r} has a "
                f"component stat in its {where} ({part[:40]!r}) — the source should "
                'join the part and the stat in one bold ("Spout HP")'
            )
    hazard["abilities"] = abilities

    # Nodes the ability parser could not claim are real published content, so
    # they go back rather than being dropped.
    for leftover in nodes:
        if id(leftover) not in consumed:
            bs.append(leftover)


_TEXT_FIELDS = (
    "complexity",
    "stealth",
    "description",
    "disable",
    "reset",
    "routine",
    "speed",
    "saving_throw",
    "maximum_duration",
    "bypass",
    "special",
    "immunities",
    "weaknesses",
    "resistances",
    "ac",
    "hardness",
    "hp",
    "bt",
    "fort",
    "ref",
    "will",
)


def _component_label(label):
    """(component, stat) for a durability label naming a part, else None."""
    match = _COMPONENT_DURABILITY.match(label)
    if match:
        return match.group("component").strip(), match.group("stat")
    return None


def _extract_component_durability(hazard, bs):
    """Hardness/HP/BT belonging to a named part of the hazard.

    A trapdoor, a scythe blade or a canvas has its own durability, published as
    "<component> Hardness". Those must not overwrite the hazard's own values.
    """
    components = {}
    seen = set()
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        parsed = _component_label(label)
        if not parsed:
            continue
        component, stat = parsed
        # Same reason the hazard's own labels are guarded: a repeated stat is
        # either lost (durability, which assigns) or doubled (a save, which
        # appends), and neither is something to discover in the output.
        assert (component, stat) not in seen, (
            f"{stat} of component {component!r} appears twice on hazard "
            f"{hazard.get('name')!r} — a durability stat would be replaced and a save "
            "duplicated, and neither is something to find in the output"
        )
        seen.add((component, stat))
        entry = components.setdefault(
            component,
            build_object("stat_block_section", "hazard_component", component),
        )
        raw = _value_after(bold)
        if stat in _DEFENSE_SUBTYPES:
            entry[stat.lower()] = _parse_defenses(plain_text(raw), _DEFENSE_SUBTYPES[stat])
            for node in nodes_after(bold):
                node.extract()
            bold.decompose()
            continue
        value, bt, note = _stat_value(raw)
        assert value is not None, (
            f"{label!r} of hazard {hazard.get('name')!r} is {plain_text(raw)!r}, which has "
            "no number in it — the component stat was published but not understood"
        )
        if note:
            entry[stat.lower() + "_note"] = note
        if stat in _SAVE_LABELS:
            save = build_object("stat_block_section", "save", _SAVE_LABELS[stat])
            save["value"] = value
            entry.setdefault("saves", []).append(save)
        else:
            entry[stat.lower()] = value
        if bt is not None:
            entry["bt"] = bt
        for node in nodes_after(bold):
            node.extract()
        bold.decompose()
    if components:
        hazard["components"] = list(components.values())


def _value_after(bold):
    return "".join(str(n) for n in nodes_after(bold))


def _first_int(text):
    match = re.search(r"-?\d+", get_text(BeautifulSoup(text, "html.parser")))
    return int(match.group(0)) if match else None


def _stat_value(raw):
    """Split a raw stat value into its number, break threshold and qualifier.

    "88 (BT 44) per spider" -> (88, 44, "per spider"). What the number is
    qualified by is published content, so taking only the integer drops it —
    at component level as much as at hazard level.
    """
    plain = plain_text(raw)
    value = _first_int(plain)
    bt = _BREAK_THRESHOLD.search(plain)
    note = _BREAK_THRESHOLD.sub("", plain, count=1)
    # The sign belongs to the number, not to the qualifier ("+11").
    note = re.sub(r"^\s*[+-]?\d+", "", note, count=1)
    note = note.replace("()", "").strip(" ,;")
    return value, int(bt.group(1)) if bt else None, note


_PROFICIENCIES = ("untrained", "trained", "expert", "master", "legendary")

# "DC 37 (expert)" for a simple hazard, "+17 (trained)" for a complex one.
_STEALTH = re.compile(
    r"^(?:(?P<dc>DC\s*(?P<dcval>\d+))|(?P<mod>[+-]\d+))"
    r"(?:\s*\((?P<prof>[^)]*)\))?(?P<rest>.*)$",
    re.I,
)


def _structure_stealth(hazard):
    """Stealth is a DC for a simple hazard and a modifier for a complex one.

    GM Core 100: the entry "lists the Stealth modifier for a complex hazard's
    initiative or the Stealth DC to detect a simple hazard, followed by the
    minimum proficiency rank to detect the hazard (if any)". Both are kept as
    published rather than converted into one another.
    """
    raw = hazard.get("stealth")
    if not raw:
        return
    match = _STEALTH.match(raw.strip())
    # A bare number says neither which it is nor which the hazard needs, and
    # guessing from the complexity would be wrong 25 times over — the corpus
    # has Complex hazards publishing a DC and Simple ones a modifier.
    assert match, (
        f"Stealth of hazard {hazard.get('name')!r} is {raw!r} — a Stealth entry is a "
        'DC ("DC 37") for a simple hazard or a signed modifier ("+17") for a complex '
        "one, and this is neither"
    )
    stealth = build_object("stat_block_section", "stealth", "Stealth")
    if match.group("dc"):
        stealth["dc"] = int(match.group("dcval"))
    else:
        stealth["value"] = int(match.group("mod"))
    # The parenthetical is usually the proficiency rank, but a few hazards put
    # prose there instead ("the tar lake is blatantly obvious").
    notes = []
    paren = (match.group("prof") or "").strip()
    rank, _, trailing = paren.partition(";")
    if rank.strip().lower() in _PROFICIENCIES:
        stealth["proficiency"] = rank.strip().lower()
        if trailing.strip():
            notes.append(trailing.strip())
    elif paren:
        notes.append(paren)
    rest = (match.group("rest") or "").strip(" ;,")
    if rest:
        notes.append(rest)
    if notes:
        stealth["note"] = " ".join(notes)
    hazard["stealth"] = stealth


def _structure_saving_throw(hazard):
    """The save a hazard's effect calls for, via the shared save-DC parser."""
    raw = hazard.get("saving_throw")
    if raw:
        hazard["saving_throw"] = universal_handle_save_dc(raw.strip())


def _structure_fields(hazard):
    """Turn the extracted strings into the structures the schema expects."""
    saves = {}
    for label, key in _SAVE_LABELS.items():
        raw = hazard.pop(label.lower(), None)
        if raw is None:
            continue
        value = _first_int(raw)
        assert value is not None, (
            f"{label} save of hazard {hazard.get('name')!r} is {raw!r}, which has no "
            "number in it — the save was published but not understood"
        )
        save = build_object("stat_block_section", "save", key)
        save["value"] = value
        saves[key] = save
    if saves:
        hazard["saves"] = [saves[k] for k in ("Fort", "Ref", "Will") if k in saves]

    # The break threshold rides along inside HP ("90 (BT 45)") — it is never
    # published as its own bold label, so reading only the first integer drops
    # it. _extract_component_durability already does this for named parts.
    break_threshold = None

    for key in ("ac", "hardness", "hp"):
        if key not in hazard:
            continue
        value, bt, note = _stat_value(hazard[key])
        if key == "hp":
            break_threshold = bt
        assert value is not None, (
            f"{key.upper()} of hazard {hazard.get('name')!r} is {hazard[key]!r}, "
            "which has no number in it — the field was published but not understood"
        )
        hazard[key] = value
        if note:
            hazard[key + "_note"] = note

    if break_threshold is not None:
        hazard["bt"] = break_threshold

    for key, subtype in (
        ("immunities", "immunity"),
        ("weaknesses", "weakness"),
        ("resistances", "resistance"),
    ):
        if hazard.get(key):
            hazard[key] = _parse_defenses(plain_text(hazard[key]), subtype)

    for key in ("complexity", "stealth", "description", "disable", "reset", "routine"):
        if key in hazard:
            hazard[key] = hazard[key].strip()

    _structure_stealth(hazard)
    _structure_saving_throw(hazard)


def _parse_defenses(text, subtype):
    """Immunities / weaknesses / resistances, in the creature shape."""
    entries = parse_defense_line(text, subtype)
    link_objects(entries)
    return entries
