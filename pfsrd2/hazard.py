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

import glob
import json
import os
import re
import sys

from bs4 import BeautifulSoup

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.traits import fetch_trait_by_name, trait_db_pass
from universal.ability import DEFAULT_ADDON_LABELS, parse_abilities_from_nodes
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.monster_ability import monster_ability_db_pass
from universal.universal import (
    RESULT_LABELS,
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
    is_trait,
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
    flatten_field_links,
    get_text,
    handle_trait_value,
    normalize_pfs_to_object,
    parse_defense_line,
    remove_empty_fields,
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
        pre_filters=[content_filter, _sidebar_filter],
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
    struct["sections"] = [
        s for s in struct["sections"] if s.get("name") not in ("Legacy Content", "Traits")
    ]
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


def _sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. siderbarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


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
    filename = _hazard_filename(jsondir, struct)
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=2, sort_keys=True)


def _hazard_filename(jsondir, struct):
    """Path for a hazard, disambiguated by aonid when two share a name.

    A book can publish two different hazards under one name — Pathfinder #184
    has two "Glyph of Warding" (levels 13 and 14). Writing both to the same
    path silently loses one, so once a name collides EVERY hazard sharing it
    takes its aonid, however many there are and in whatever order they are
    parsed.
    """
    stem = os.path.abspath(jsondir + "/" + char_replace(struct["name"]))
    base = stem + ".json"
    suffixed = f"{stem}_{struct['aonid']}.json"
    if not os.path.exists(base):
        # A sibling already claimed a suffix, so this name is known to collide.
        return suffixed if glob.glob(f"{stem}_*.json") else base

    with open(base) as fp:
        try:
            existing = json.load(fp)
        except json.JSONDecodeError as e:
            raise ValueError(f"Existing hazard file {base} is not readable JSON") from e
    assert "aonid" in existing, f"Existing hazard file {base} has no aonid"
    if existing["aonid"] == struct["aonid"]:
        return base
    # Move the squatter aside under its own aonid, then take a suffix too.
    os.rename(base, f"{stem}_{existing['aonid']}.json")
    return suffixed


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
    _extract_traits(hazard, bs)
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
    _unwrap_field_links(hazard)
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


def _extract_traits(hazard, bs):
    traits = []

    # is_trait joins the class list before matching, so it covers every rarity
    # class AoN uses — trait, traituncommon, traitrare, traitunique.
    for span in list(bs.find_all("span")):
        if not is_trait(span):
            continue
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


def _extract_abilities(hazard, bs):
    """Everything from the first non-field bold label onward is an ability.

    Hazard actions are published exactly like creature abilities — a bold name,
    an action span, then Trigger/Effect — so universal.ability does the work.
    """
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
        body = _plain(ability.get("text") or ability.get("effect") or "")
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
        hazard[key] = flatten_field_links(value, hazard.setdefault("links", []))


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
        if stat in _DEFENSE_SUBTYPES:
            entry[stat.lower()] = _parse_defenses(_plain(raw), _DEFENSE_SUBTYPES[stat])
            for node in _nodes_after(bold):
                node.extract()
            bold.decompose()
            continue
        value, bt, note = _stat_value(raw)
        assert value is not None, (
            f"{label!r} of hazard {hazard.get('name')!r} is {_plain(raw)!r}, which has "
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


def _stat_value(raw):
    """Split a raw stat value into its number, break threshold and qualifier.

    "88 (BT 44) per spider" -> (88, 44, "per spider"). What the number is
    qualified by is published content, so taking only the integer drops it —
    at component level as much as at hazard level.
    """
    plain = _plain(raw)
    value = _first_int(plain)
    bt = _BREAK_THRESHOLD.search(plain)
    note = _BREAK_THRESHOLD.sub("", plain, count=1)
    # The sign belongs to the number, not to the qualifier ("+11").
    note = re.sub(r"^\s*[+-]?\d+", "", note, count=1)
    note = note.replace("()", "").strip(" ,;")
    return value, int(bt.group(1)) if bt else None, note


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
            hazard[key] = _parse_defenses(_plain(hazard[key]), subtype)

    for key in ("complexity", "stealth", "description", "disable", "reset", "routine"):
        if key in hazard:
            hazard[key] = hazard[key].strip()


def _parse_defenses(text, subtype):
    """Immunities / weaknesses / resistances, in the creature shape."""
    entries = parse_defense_line(text, subtype)
    link_objects(entries)
    return entries


def _plain(value):
    return get_text(BeautifulSoup(value, "html.parser")).strip()
