"""Affliction parser — curses and diseases.

Both publish the same stat block: a level badge in the title ("Curse 8",
"Disease 0"), trait spans, a Source line, prose, then a run of bold-labelled
fields ending in Stage 1..N. One parser, two runs, on the equipment pattern.

Built on the existing parsers rather than beside them:

  pipeline shape   pfsrd2/hazard.py — the same badge/traits/bold-fields shape
  traits           universal.universal.is_trait
  bold fields      universal.universal.extract_bold_fields
  save DC          universal.creatures.universal_handle_save_dc
  stages           the affliction_stage shape universal/ability.py already
                   produces for creature and hazard afflictions

ItemCurses is deliberately not parsed. All 15 of its distinct entries resolve
to Curses.aspx IDs the Curses run already covers, and the rendered bodies are
byte-identical, so parsing it would emit duplicates sharing an aonid and name.

Brittle by design: FIELD_LABELS is closed, and a bold label outside it fails
the parse rather than being dropped.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.traits import trait_db_pass
from universal.creatures import universal_handle_save_dc
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
    is_trait,
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
    normalize_pfs_to_object,
    remove_empty_fields,
    strip_block_tags,
)

# Structural stat-block labels. Anything bold outside this set, other than a
# Stage, fails the parse — that is the whole disambiguation, so it stays closed.
FIELD_LABELS = {
    "Saving Throw",
    "Onset",
    "Maximum Duration",
    "Effect",
    "Usage",
    "Special",
    "Tempted Curse",
}

_STAGE = re.compile(r"^Stage\s+(\d+)$", re.I)

# "Curse 5" as a bold label, on an affliction whose own badge is "Curse 4":
# the level the affliction becomes later in the adventure.
_ESCALATION = re.compile(r"^(?:Curse|Disease)\s+(\d+)$", re.I)

# "Curse 8", "Disease 0" — the badge parse_universal turns into `subname`.
_LEVEL_RE = re.compile(r"(?:Curse|Disease)\s+(-?\d+)", re.I)

# "Curse Level Varies" — published where the level depends on context.
_LEVEL_VARIES = re.compile(r"Level\s+Varies", re.I)

# "clumsy 1 (1 day)" — the trailing parenthetical is the stage's duration.
_STAGE_DURATION = re.compile(r"\(([^)]*)\)\s*$")

# "a high spell DC for a monster of its level" mentions DC without giving one.
_NUMERIC_DC = re.compile(r"\bDC\s*\d+")
_SAVE_NAME = re.compile(r"\b(Fortitude|Reflex|Will)\b", re.I)
_SAVE_NAMES = {"fortitude": "Fort", "reflex": "Ref", "will": "Will"}

AFFLICTION_TYPES = {"curse": "curses", "disease": "diseases"}

_TEXT_FIELDS = ("effect", "usage", "special", "tempted_curse", "onset", "maximum_duration")


def parse_affliction(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=4,
        cssclass="main",
        # content_filter bare, as hazards do: the badge IS the level, and
        # parse_universal turns it into `subname` for restructure to read.
        pre_filters=[content_filter, _sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    alternate_link = handle_alternate_link(details, allow_multiple=True)

    struct = restructure_affliction_pass(details, options.subtype)
    if alternate_link:
        struct["alternate_link"] = (
            alternate_link[0] if isinstance(alternate_link, list) else alternate_link
        )

    affliction = find_affliction(struct)
    bs = BeautifulSoup(affliction["text"], "html.parser")
    struct["pfs"] = extract_pfs_availability(bs)
    extract_pfs_note(bs, struct)
    affliction["text"] = str(bs)
    normalize_pfs_to_object(struct)

    affliction_extract_pass(struct)
    source_pass(struct, find_affliction)
    aon_pass(struct, basename)
    restructure_pass(struct, "affliction", find_affliction)
    struct["edition"] = edition_from_alternate_link(struct) or edition_pass(struct["sections"])
    struct["sections"] = [
        s for s in struct["sections"] if s.get("name") not in ("Legacy Content", "Traits")
    ]
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    trait_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct, extra_tags=["h2", "h3", "u"])
    universal_markdown_pass(struct, struct["name"], "")
    remove_empty_fields(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "affliction.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_affliction(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2, sort_keys=True))


def _sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. siderbarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


def find_affliction(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "affliction":
            return section
    raise AssertionError(f"No affliction stat block found in {struct.get('name')!r}")


def write_affliction(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = os.path.abspath(jsondir + "/" + char_replace(struct["name"]) + ".json")
    _assert_safe_overwrite(filename, struct)
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=2, sort_keys=True)


# Fields that differ between two AoN entries for the same affliction purely
# because they are two entries: the ID and everything derived from it.
_IDENTITY_FIELDS = ("aonid", "game-id", "alternate_link")


def _assert_safe_overwrite(filename, struct):
    """Refuse to silently overwrite a different affliction with the same name.

    AoN publishes 19 GM Core / Gatewalkers curses twice under two aonids, with
    identical bodies, so one overwriting the other loses nothing. That is only
    safe while the bodies match: without this check, the day two genuinely
    different afflictions share a name in one book, one of them disappears
    from the output and the run still reports success.
    """
    if not os.path.exists(filename):
        return
    with open(filename) as fp:
        existing = json.load(fp)
    if existing.get("aonid") == struct.get("aonid"):
        return  # our own output from a previous run
    body = lambda d: {k: v for k, v in d.items() if k not in _IDENTITY_FIELDS}  # noqa: E731
    assert body(existing) == body(struct), (
        f"{struct['name']!r} would overwrite a different affliction at "
        f"{filename} (aonid {existing.get('aonid')} vs {struct.get('aonid')})"
    )


def _take_text_section(sections):
    """Remove and return the first section carrying stat block text.

    Depth first, and removed from wherever it sits: a spoiler warning renders
    as an h2 that nests the stat block a level deeper, and leaving the section
    in place would carry the whole unparsed block into the output a second
    time.
    """
    for i, section in enumerate(sections):
        if section.get("text"):
            return sections.pop(i)
        found = _take_text_section(section.get("sections", []))
        if found:
            return found
    return None


def restructure_affliction_pass(details, subtype):
    """Build the affliction structure from parse_universal output.

    Same two layouts hazards have: legacy pages wrap the stat block in a
    "Legacy Content" section, remastered pages put the text on the entry.
    """
    assert details, "parse_universal returned nothing — the page has no parsable content"
    first = details[0]
    rest = details[1:]

    name = get_text(BeautifulSoup(first.get("name", ""), "html.parser")).strip()
    assert name, f"Could not extract affliction name from {first.get('name')!r}"

    # 'sections' must exist even when empty: the universal passes walk section
    # trees unconditionally (see CLAUDE.md, "The 'sections' Key Requirement").
    sb = build_object("stat_block_section", "affliction", name, {"sections": []})
    sb["affliction_type"] = subtype

    subname = (first.get("subname") or "").strip()
    assert subname, f"No level badge at all for {name!r}"
    match = _LEVEL_RE.search(subname)
    if match:
        sb["level"] = int(match.group(1))
    else:
        # "Curse Level Varies" — the level genuinely depends on the item or
        # the ritual that inflicted it. Record what was published rather than
        # inventing a number.
        assert _LEVEL_VARIES.search(
            subname
        ), f"Level badge {subname!r} for {name!r} is neither a number nor 'Varies'"
        sb["level_text"] = subname

    body_sections = list(first.get("sections", []))
    if first.get("text"):
        sb["text"] = first["text"]
        carrier = None
    else:
        # A spoiler warning renders as an h2, which nests the stat block one
        # level deeper, so the search has to descend rather than scan the top.
        carrier = _take_text_section(body_sections)
        assert carrier, f"No stat block text found for {name!r}"
        sb["text"] = carrier["text"]

    top = {"name": name, "type": "affliction", "sections": [sb]}
    top["sections"].extend(body_sections)
    for r in rest:
        assert isinstance(r, dict), f"Unstructured trailing detail on {name!r}: {r!r}"
        top["sections"].append(r)
    return top


def affliction_extract_pass(struct):
    """Pull traits, sources, bold fields and stages out of the stat block blob."""
    affliction = find_affliction(struct)
    bs = BeautifulSoup(affliction.pop("text"), "html.parser")

    # Separators carry no data, and leaving them in bleeds "---" into values
    # once markdown runs.
    for rule in list(bs.find_all("hr")):
        rule.decompose()

    _extract_traits(affliction, bs)
    _extract_sources(affliction, bs)
    # Stages first: their labels are Stage N rather than members of the closed
    # set, so extract_bold_fields would treat them as unknown.
    _extract_stages(affliction, bs)
    _extract_escalations(affliction, bs)
    extract_bold_fields(affliction, bs, FIELD_LABELS, decompose=True)
    _split_trailing_prose(affliction)
    _assert_no_unknown_labels(affliction, bs)
    _unwrap_field_links(affliction)
    links = get_links(bs, unwrap=True)
    if links:
        affliction.setdefault("links", []).extend(links)
    _structure_fields(affliction)

    # Residual prose is the affliction's description — it is published between
    # the Source line and the Saving Throw, with no label of its own.
    residual = str(bs).strip()
    recovered = affliction.pop("_trailing_prose", "")
    if recovered:
        residual = f"{recovered}<br/>{residual}" if residual else recovered
    leftover = re.sub(r"(<br/?>|\s|;|,)+", "", residual)
    if leftover:
        # Flatten here rather than in _unwrap_field_links: the description is
        # assembled after that runs, so its links would otherwise survive as
        # <a> tags and fail markdown validation.
        affliction["description"] = flatten_field_links(
            residual, affliction.setdefault("links", [])
        )


def _extract_traits(affliction, bs):
    """is_trait joins the class list, so it covers every rarity class AoN uses."""
    traits = []
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
        affliction["traits"] = traits


def _extract_sources(affliction, bs):
    """The shared extractor builds the structured dict and removes the nodes."""
    source = extract_source_from_bs(bs)
    assert source, f"No source found for affliction {affliction.get('name')!r}"
    affliction["sources"] = [source]


def _extract_stages(affliction, bs):
    """Stage 1..N, in published order, with the trailing duration split out.

    The same affliction_stage shape universal/ability.py produces for creature
    and hazard afflictions, so a consumer needs no new code to read them.
    """
    stages = []
    for bold in list(bs.find_all("b")):
        match = _STAGE.match(get_text(bold).strip())
        if not match:
            continue
        value = "".join(str(n) for n in _nodes_after(bold)).strip()
        stage = build_object("stat_block_section", "affliction_stage", f"Stage {match.group(1)}")
        stage["stage"] = int(match.group(1))
        # A trailing separator hides the duration from the anchored match.
        plain = _plain(value).strip(" ;,")
        duration = _STAGE_DURATION.search(plain)
        if duration:
            stage["duration"] = duration.group(1).strip()
            plain = plain[: duration.start()].strip(" ;,")
        assert plain, (
            f"Stage {match.group(1)} of {affliction.get('name')!r} has no effect text — "
            "the stage was published but not understood"
        )
        stage["effect"] = plain
        links = get_links(BeautifulSoup(value, "html.parser"), unwrap=True)
        if links:
            stage["links"] = links
        stages.append(stage)
        for node in _nodes_after(bold):
            node.extract()
        bold.decompose()
    if stages:
        expected = list(range(1, len(stages) + 1))
        assert [s["stage"] for s in stages] == expected, (
            f"{affliction.get('name')!r} publishes stages "
            f"{[s['stage'] for s in stages]}, which is not a run from 1"
        )
        affliction["stages"] = stages


def _extract_escalations(affliction, bs):
    """ "Curse 5", "Curse 6" — the affliction growing stronger as a story runs.

    Adventure-path afflictions publish later levels as their own bold labels,
    each describing what changes at that level. They are not stages: a stage is
    a step through one affliction, an escalation replaces the whole thing with
    a higher-level version.
    """
    escalations = []
    for bold in list(bs.find_all("b")):
        match = _ESCALATION.match(get_text(bold).strip())
        if not match:
            continue
        value = "".join(str(n) for n in _nodes_after(bold)).strip()
        effect = _plain(value).strip(" ;,")
        assert effect, (
            f"{match.group(0)!r} on {affliction.get('name')!r} has no text — the "
            "escalation was published but not understood"
        )
        entry = build_object("stat_block_section", "affliction_escalation", match.group(0))
        entry["level"] = int(match.group(1))
        entry["effect"] = effect
        links = get_links(BeautifulSoup(value, "html.parser"), unwrap=True)
        if links:
            entry["links"] = links
        escalations.append(entry)
        for node in _nodes_after(bold):
            node.extract()
        bold.decompose()
    if escalations:
        affliction["escalations"] = escalations


def _assert_no_unknown_labels(affliction, bs):
    """Every bold is either a known field or a stage; anything else is new."""
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if not label:
            continue
        raise AssertionError(
            f"Unknown bold label {label!r} on affliction {affliction.get('name')!r} — "
            "add it to FIELD_LABELS or handle it explicitly"
        )


def _split_trailing_prose(affliction):
    """Give back the prose a last-in-block field swallowed.

    A field's value never spans a <br/> in this source; the break separates the
    labelled run from the description that follows. extract_bold_fields takes
    everything up to the next bold, so the final field — Usage on a curse with
    no stages — otherwise absorbs the whole description.
    """
    prose = []
    for key in _TEXT_FIELDS:
        value = affliction.get(key)
        if not isinstance(value, str) or "<br" not in value:
            continue
        parts = re.split(r"<br\s*/?>", value, maxsplit=1)
        affliction[key] = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            prose.append(parts[1].strip())
    if prose:
        affliction["_trailing_prose"] = "<br/>".join(prose)


def _nodes_after(bold):
    """Sibling nodes up to the next bold label — a label's value run."""
    nodes = []
    node = bold.next_sibling
    while node is not None and getattr(node, "name", None) != "b":
        nodes.append(node)
        node = node.next_sibling
    return nodes


def _unwrap_field_links(affliction):
    """Flatten extracted field values to plain text, keeping their links."""
    for key in _TEXT_FIELDS:
        value = affliction.get(key)
        if not isinstance(value, str) or "<" not in value:
            continue
        affliction[key] = flatten_field_links(value, affliction.setdefault("links", []))


def _structure_fields(affliction):
    """Turn the extracted strings into the structures the schema expects."""
    raw = affliction.get("saving_throw")
    if raw:
        plain = _plain(raw).strip(" ;,")
        if _NUMERIC_DC.search(plain):
            affliction["saving_throw"] = universal_handle_save_dc(plain)
        else:
            # Some afflictions name the save without a DC ("Fortitude", "Will
            # save, with a high spell DC for a monster of its level"). Keep
            # what was published rather than inventing a number.
            save = {"type": "stat_block_section", "subtype": "save_dc", "text": plain}
            named = _SAVE_NAME.search(plain)
            if named:
                save["save_type"] = _SAVE_NAMES[named.group(1).lower()]
            affliction["saving_throw"] = save

    for key in _TEXT_FIELDS:
        if key in affliction:
            affliction[key] = affliction[key].strip(" ;,")


def _plain(value):
    return get_text(BeautifulSoup(value, "html.parser")).strip()
