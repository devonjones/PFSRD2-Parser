"""Hazard parser.

Hazards are creature-shaped stat blocks: a level badge ("Hazard 3"), traits,
a run of bold-labelled fields, and abilities that carry an action type plus
Trigger/Effect. The whole stat block arrives from parse_universal as one flat
HTML blob of `<b>Label</b> value` runs separated by `<br/>` and `<hr/>`.

Built on the existing parsers rather than beside them:

  pipeline shape   pfsrd2/feat.py — the closest existing shape (level badge,
                   traits, bold fields, an action span in the title)
  bold fields      universal.universal.extract_bold_fields
  abilities        universal.ability.parse_abilities_from_nodes
  defenses         universal.creatures.universal_handle_* for immunities,
                   weaknesses, resistances and save DCs

Brittle by design: FIELD_LABELS is closed. A bold label outside it is treated
as the start of an ability, and an ability that yields nothing fails the parse
rather than silently dropping a chunk of the stat block.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.traits import fetch_trait_by_name, trait_db_pass
from universal.ability import parse_abilities_from_nodes
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.universal import (
    aon_pass,
    build_object,
    edition_from_alternate_link,
    edition_pass,
    entity_pass,
    extract_bold_fields,
    extract_source_from_bs,
    game_id_pass,
    get_links,
    handle_alternate_link,
    link_objects,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
)
from universal.utils import (
    content_filter,
    extract_pfs_availability,
    extract_pfs_note,
    get_text,
    handle_trait_value,
    normalize_pfs_to_object,
    parse_section_modifiers,
    parse_section_value,
    rebuilt_split_modifiers,
    remove_empty_fields,
    split_stat_block_line,
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
    "BT",
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
_COMPONENT_DURABILITY = re.compile(r"^(?P<component>.+?)\s+(?P<stat>Hardness|HP|BT)$")
_QUALIFIED_DURABILITY = re.compile(r"^(?P<stat>Hardness|HP|BT)\s*\((?P<component>[^)]+)\)$")

_SAVE_LABELS = {"Fort": "fortitude", "Ref": "reflex", "Will": "will"}

_LEVEL_RE = re.compile(r"Hazard\s+(-?\d+)", re.I)


def parse_hazard(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=4,
        cssclass="main",
        pre_filters=[_content_filter, _sidebar_filter],
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
    if "text" in hazard:
        bs = BeautifulSoup(hazard["text"], "html.parser")
        struct["pfs"] = extract_pfs_availability(bs)
        extract_pfs_note(bs, struct)
        hazard["text"] = str(bs)
    else:
        struct["pfs"] = "Standard"
    normalize_pfs_to_object(struct)

    hazard_extract_pass(struct)
    source_pass(struct, find_hazard)
    aon_pass(struct, basename)
    restructure_pass(struct, "hazard", find_hazard)
    struct["edition"] = edition_from_alternate_link(struct) or edition_pass(struct["sections"])
    struct["sections"] = [
        s for s in struct["sections"] if s.get("name") not in ("Legacy Content", "Traits")
    ]
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
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


def _content_filter(soup):
    """Base content filter only.

    Deliberately does NOT move the level badge span out of the h1 the way
    feat.py does. Feats move it because they also carry an action span there;
    a hazard's badge IS its level, and parse_universal turns it into `subname`,
    which restructure_hazard_pass reads.
    """
    content_filter(soup)


def _sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. siderbarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


def _hazard_trait_pre_process(trait, parent, curs):
    """Split a magnitude off a trait name before the DB lookup.

    A hazard's Strike can carry "thrown 10 feet"; the traits table knows
    "thrown". Same hook equipment uses for the same reason.
    """
    data = fetch_trait_by_name(curs, trait["name"])
    if not data and " " in trait["name"]:
        handle_trait_value(trait)
    return False


def find_hazard(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "hazard":
            return section
    raise AssertionError(f"No hazard stat block found in {struct.get('name')!r}")


def write_hazard(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = os.path.abspath(jsondir + "/" + char_replace(struct["name"]) + ".json")
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=2, sort_keys=True)


def restructure_hazard_pass(details):
    """Build the hazard structure from parse_universal output.

    parse_universal yields the hazard as one entry whose `name` is the title
    link, `subname` is the level badge ("Hazard 3"), and whose single section
    carries the entire stat block as flat HTML.
    """
    assert details, "No details from parse_universal"
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
    carrier = None
    for section in body_sections:
        if section.get("text"):
            carrier = section
            break
    if carrier:
        sb["text"] = carrier["text"]
    else:
        assert first.get("text"), f"No stat block text found for {name!r}"
        sb["text"] = first["text"]

    top = {"name": name, "type": "hazard", "sections": [sb]}
    top["sections"].extend(s for s in body_sections if s is not carrier)
    top["sections"].extend(r for r in rest if isinstance(r, dict))
    return top


_MAP_AREA_REF = re.compile(r"^[A-Z]\d+$")


def _unwrap_map_area_refs(bs):
    """Demote bolded map-area references ("area <b>C2</b>") to plain text.

    Adventure hazards cite the map square a trigger fires in, and the source
    bolds it mid-sentence. Every other bold in a stat block is a field or
    ability label, so the ability parser reads "C2" as a label and its trailing
    "or" as an action type. 59 hazard files do this, so it belongs in code.
    """
    for tag in list(bs.find_all("b")):
        if _MAP_AREA_REF.match(tag.get_text().strip()):
            tag.unwrap()


def hazard_extract_pass(struct):
    """Pull traits, bold fields and abilities out of the stat block blob."""
    hazard = find_hazard(struct)
    bs = BeautifulSoup(hazard.pop("text", ""), "html.parser")

    # Separators carry no data, and leaving them in bleeds "---" into field
    # values and ability effects once markdown runs.
    for rule in list(bs.find_all("hr")):
        rule.decompose()

    _unwrap_map_area_refs(bs)
    _extract_traits(hazard, bs)
    _extract_sources(hazard, bs)
    # Fields first: the ability grab takes everything from the first non-field
    # bold onward, so a trailing Reset would be swallowed into the last ability.
    _extract_component_durability(hazard, bs)
    extract_bold_fields(hazard, bs, FIELD_LABELS, decompose=True)
    _extract_abilities(hazard, bs)
    # Links are unwrapped per field AFTER abilities are parsed: universal.ability
    # reads an ability's trait links out of the live tags, so a global unwrap
    # beforehand strips the traits it needs.
    _unwrap_field_links(hazard)
    links = get_links(bs, unwrap=True)
    if links:
        hazard.setdefault("links", []).extend(links)
    _structure_fields(hazard)

    # Residual prose the fields and abilities did not claim is real published
    # content, so it is kept — flattened the same way field values are, since
    # the markdown pass accepts no tags.
    residue_links = get_links(bs, unwrap=True)
    if residue_links:
        hazard.setdefault("links", []).extend(residue_links)
    for span in bs.find_all("span", {"class": "action"}):
        span.unwrap()
    leftover = re.sub(r"(<br/?>|<hr/?>|\s|;|,)+", "", str(bs).strip())
    if leftover:
        hazard["text"] = str(bs)


def _extract_traits(hazard, bs):
    traits = []

    # AoN marks rarity with its own classes: trait, traituncommon, traitrare,
    # traitunique. Matching only "trait" drops every rare hazard's rarity.
    def _is_trait_span(tag):
        return tag.name == "span" and any(c.startswith("trait") for c in (tag.get("class") or []))

    for span in list(bs.find_all(_is_trait_span)):
        trait = build_object("stat_block_section", "trait", get_text(span).strip())
        links = get_links(span, unwrap=True)
        if links:
            trait["links"] = links
        traits.append(trait)
        span.decompose()
    if traits:
        hazard["traits"] = traits


def _extract_sources(hazard, bs):
    """Sources come from the shared extractor, which builds the structured
    dict and removes the nodes; extract_bold_fields would only capture the
    raw HTML."""
    sources = []
    while True:
        source = extract_source_from_bs(bs)
        if not source:
            break
        sources.append(source)
    assert sources, f"No sources found for hazard {hazard.get('name')!r}"
    hazard["sources"] = sources


def _extract_abilities(hazard, bs):
    """Everything from the first non-field bold label onward is an ability.

    Hazard actions are published exactly like creature abilities — a bold name,
    an action span, then Trigger/Effect — so universal.ability does the work.
    """
    start = None
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if label in FIELD_LABELS or _component_label(label):
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
    abilities = parse_abilities_from_nodes(nodes, consumed=consumed)
    assert abilities, (
        f"Bold label {get_text(start).strip()!r} on {hazard.get('name')!r} is not a known "
        "field and did not parse as an ability — add it to FIELD_LABELS or fix the split"
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


def _unwrap_field_links(hazard):
    """Flatten extracted field values to plain text.

    Links become structured references; action spans are unwrapped to their
    bracket text the way change_extraction.py does, since a Routine or Disable
    entry can name an action inline and the markdown pass accepts no tags.
    """
    for key in _TEXT_FIELDS:
        value = hazard.get(key)
        if not isinstance(value, str) or "<" not in value:
            continue
        bs = BeautifulSoup(value, "html.parser")
        links = get_links(bs, unwrap=True)
        if links:
            hazard.setdefault("links", []).extend(links)
        for span in bs.find_all("span", {"class": "action"}):
            span.unwrap()
        hazard[key] = str(bs)


def _component_label(label):
    """(component, stat) for a durability label naming a part, else None."""
    for pattern in (_QUALIFIED_DURABILITY, _COMPONENT_DURABILITY):
        match = pattern.match(label)
        if match:
            return match.group("component").strip(), match.group("stat")
    return None


def _extract_component_durability(hazard, bs):
    """Hardness/HP/BT belonging to a named part of the hazard.

    A trapdoor, a scythe blade or a canvas has its own durability, published as
    "<component> Hardness". Those must not overwrite the hazard's own values.
    """
    components = {}
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        parsed = _component_label(label)
        if not parsed:
            continue
        component, stat = parsed
        entry = components.setdefault(
            component,
            build_object("stat_block_section", "hazard_component", component),
        )
        raw = _value_after(bold)
        entry[stat.lower()] = _first_int(raw)
        # HP is published as "12 (BT 6)" — the break threshold rides along.
        bt = re.search(r"BT\s+(-?\d+)", _plain(raw))
        if bt:
            entry["bt"] = int(bt.group(1))
        for node in _nodes_after(bold):
            node.extract()
        bold.decompose()
    if components:
        hazard["components"] = list(components.values())


def _nodes_after(bold):
    """Sibling nodes up to the next bold label — a label's value run."""
    nodes = []
    node = bold.next_sibling
    while node is not None and getattr(node, "name", None) != "b":
        nodes.append(node)
        node = node.next_sibling
    return nodes


def _value_after(bold):
    return "".join(str(n) for n in _nodes_after(bold))


def _first_int(text):
    match = re.search(r"-?\d+", get_text(BeautifulSoup(text, "html.parser")))
    return int(match.group(0)) if match else None


def _structure_fields(hazard):
    """Turn the extracted strings into the structures the schema expects."""
    saves = {}
    for label, key in _SAVE_LABELS.items():
        raw = hazard.pop(label.lower(), None)
        if raw is None:
            continue
        value = _first_int(raw)
        if value is None:
            continue
        save = build_object("stat_block_section", "save", key)
        save["value"] = value
        saves[key] = save
    if saves:
        hazard["saves"] = [saves[k] for k in ("fortitude", "reflex", "will") if k in saves]

    for key in ("ac", "hardness", "hp", "bt"):
        if key in hazard:
            value = _first_int(hazard[key])
            if value is not None:
                hazard[key] = value
            else:
                del hazard[key]

    for key, subtype in (
        ("immunities", "immunity"),
        ("weaknesses", "weakness"),
        ("resistances", "resistance"),
    ):
        if hazard.get(key):
            hazard[key] = _parse_defenses(_plain(hazard[key]), subtype)

    for key in ("complexity", "stealth", "description", "disable", "reset", "routine"):
        if key in hazard:
            hazard[key] = hazard[key].strip()


def _parse_defenses(text, subtype):
    """Immunities / weaknesses / resistances, in the creature shape.

    Uses the same helper chain pfsrd2/creatures.py uses for the identical
    stat-block line, so "cold 5" yields {name: "cold", value: 5} and a
    consumer sees one shape across both content types.
    """
    if text.endswith(";"):
        text = text[:-1].strip()
    entries = []
    for part in rebuilt_split_modifiers(split_stat_block_line(text)):
        # A trailing separator yields an empty part. Left in, its name is ""
        # and remove_empty_fields later strips the key entirely, producing a
        # nameless entry that fails schema validation.
        if not part or not part.strip():
            continue
        entry = {"type": "stat_block_section", "subtype": subtype, "name": part.strip()}
        parse_section_modifiers(entry, "name")
        parse_section_value(entry, "name")
        entries.append(entry)
    link_objects(entries)
    return entries


def _plain(value):
    return get_text(BeautifulSoup(value, "html.parser")).strip()


def _iter_strings(node):
    if isinstance(node, NavigableString):
        yield str(node)
