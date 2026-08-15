"""Affliction parser — curses and diseases.

Both publish the same stat block: a level badge in the title ("Curse 8",
"Disease 0"), trait spans, a Source line, prose, then a run of bold-labelled
fields ending in Stage 1..N. One parser, two runs, on the equipment pattern.

Built on the existing parsers rather than beside them:

  pipeline shape   pfsrd2/hazard.py — the same badge/traits/bold-fields shape
  traits           universal.universal.extract_span_traits
  bold fields      universal.universal.extract_bold_fields
  save DC          universal.creatures.parse_save_dc
  filenames        universal.files.disambiguated_filename — the same
                   aonid-suffix collision policy hazards use

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
from universal.creatures import parse_save_dc
from universal.files import char_replace, disambiguated_filename, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.universal import (
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
    flatten_field_links,
    flatten_fields,
    get_text,
    nodes_after,
    normalize_pfs_to_object,
    plain_text,
    remove_empty_fields,
    sidebar_filter,
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

# The badge and the escalation labels name the affliction's own type, so the
# patterns are built per type: a "Curse 5" bold on a disease page is not an
# escalation, it is a page the parser has misunderstood.
_BADGE_WORD = {"curse": "Curse", "disease": "Disease"}


def _escalation_re(subtype):
    """ "Curse 5" as a bold label on an affliction whose badge is "Curse 4":
    the level the affliction becomes later in the adventure."""
    return re.compile(rf"^{_BADGE_WORD[subtype]}\s+(\d+)$", re.I)


def _level_re(subtype):
    """ "Curse 8", "Disease 0" — the badge parse_universal turns into subname."""
    return re.compile(rf"{_BADGE_WORD[subtype]}\s+(-?\d+)", re.I)


def _level_varies_re(subtype):
    """ "Curse Level Varies" — published where the level depends on context."""
    return re.compile(rf"^{_BADGE_WORD[subtype]}\s+Level\s+Varies$", re.I)


# "clumsy 1 (1 day)" — the trailing parenthetical is the stage's duration.
_STAGE_DURATION = re.compile(r"\(([^)]*)\)\s*$")

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
        pre_filters=[content_filter, sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    # No allow_multiple: the universal assert that a version line carries
    # exactly one link is the only thing that would notice a second one, and
    # keeping [0] of a list silently drops the rest.
    alternate_link = handle_alternate_link(details)

    struct = restructure_affliction_pass(details, options.subtype)
    if alternate_link:
        struct["alternate_link"] = alternate_link

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
    drop_marker_sections(struct)
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


def find_affliction(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "affliction":
            return section
    raise AssertionError(f"No affliction stat block found in {struct.get('name')!r}")


def write_affliction(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = disambiguated_filename(jsondir, struct, "affliction")
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=2, sort_keys=True)


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

    # The badge names the type, so it also confirms it: affliction_type comes
    # from the command line and is the one field the HTML cannot contradict
    # unless it is checked here.
    subname = (first.get("subname") or "").strip()
    assert subname, f"No level badge at all for {name!r}"
    match = _level_re(subtype).search(subname)
    if match:
        sb["level"] = int(match.group(1))
    else:
        # "Curse Level Varies" — the level genuinely depends on the item or
        # the ritual that inflicted it. Record what was published rather than
        # inventing a number.
        assert _level_varies_re(subtype).search(subname), (
            f"Level badge {subname!r} for {name!r} is neither a "
            f"{_BADGE_WORD[subtype]} level nor '{_BADGE_WORD[subtype]} Level Varies' — "
            "wrong affliction type for this page?"
        )
        sb["level_text"] = subname

    body_sections = list(first.get("sections", []))
    # Carrier first, matching the original precedence: when a page carries
    # text in both places the wrapped stat block is the real one.
    text = take_stat_block_text(body_sections)
    if text is None:
        text = first.get("text")
    assert text, f"No stat block text found for {name!r}"
    sb["text"] = text

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

    # Snapshot every published label before anything consumes one. Checking
    # the residue instead would make a label invisible to the check the moment
    # an earlier extractor removed it — which is exactly the markup change the
    # check exists to catch.
    published = [get_text(b).strip() for b in bs.find_all("b")]

    extract_span_traits(affliction, bs)
    _extract_sources(affliction, bs)
    # Stages and escalations need their own extractors because their labels
    # are patterns rather than members of the closed set, and they must run
    # FIRST. extract_bold_fields stops a value run at the next sibling bold,
    # but a Stage bold nested inside an inline tag is not a sibling — the
    # whole tag is swallowed into the preceding field and the stage is gone.
    # No page publishes that shape today; the order is what keeps it that way.
    _extract_stages(affliction, bs)
    _extract_escalations(affliction, bs, affliction["affliction_type"])
    extract_bold_fields(affliction, bs, FIELD_LABELS, decompose=True)
    prose = _split_trailing_prose(affliction)
    _assert_no_unknown_labels(affliction, published, affliction["affliction_type"])
    flatten_fields(affliction, _TEXT_FIELDS)
    links = get_links(bs, unwrap=True)
    if links:
        affliction.setdefault("links", []).extend(links)
    _structure_fields(affliction)
    _extract_description(affliction, bs, prose)


def _extract_description(affliction, bs, prose):
    """Whatever prose is left once every label has taken its own.

    The description is published between the Source line and the first field
    with no label of its own, and a last-in-block field can swallow a second
    run of it, which _split_trailing_prose hands back here. Published order is
    residual-then-recovered: the recovered half came from further down the
    block.
    """
    residual = str(bs).strip()
    if prose:
        residual = f"{residual}<br/>{prose}" if residual else prose
    # Without this the punctuation left behind by the field run would ship as
    # a description of "<br/>;".
    leftover = re.sub(r"(<br/?>|\s|;|,)+", "", residual)
    if not leftover:
        return
    # Flatten here rather than in flatten_fields: the description is assembled
    # after that runs, so its links would otherwise survive as <a> tags and
    # fail markdown validation.
    affliction["description"] = flatten_field_links(residual, affliction.setdefault("links", []))


def _extract_sources(affliction, bs):
    """The shared extractor builds the structured dict and removes the nodes."""
    source = extract_source_from_bs(bs)
    assert source, f"No source found for affliction {affliction.get('name')!r}"
    affliction["sources"] = [source]


def _labelled_blocks(bs, pattern):
    """Yield (match, value_html) for each bold matching pattern, consuming both.

    Stages and escalations are the same walk over the same markup — only what
    they build from the value differs.
    """
    for bold in list(bs.find_all("b")):
        match = pattern.match(get_text(bold).strip())
        if not match:
            continue
        # find_all is snapshotted, so a bold nested inside an earlier value
        # run has already been extracted with it. Walking its siblings now
        # would silently merge two entries; the label is real, so it is a
        # markup shape the parser has not understood.
        assert bold.find_parent() is not None, (
            f"{match.group(0)!r} was consumed by an earlier value run — "
            "it is nested rather than a sibling, which this parser cannot read"
        )
        nodes = nodes_after(bold)
        value = "".join(str(n) for n in nodes).strip()
        for node in nodes:
            node.extract()
        bold.decompose()
        yield match, value


def _block_links(value):
    return get_links(BeautifulSoup(value, "html.parser"), unwrap=True)


def _extract_stages(affliction, bs):
    """Stage 1..N, in published order, with the trailing duration split out."""
    stages = []
    for match, value in _labelled_blocks(bs, _STAGE):
        stage = build_object("stat_block_section", "affliction_stage", f"Stage {match.group(1)}")
        stage["stage"] = int(match.group(1))
        # A trailing separator hides the duration from the anchored match.
        plain = plain_text(value).strip(" ;,")
        duration = _STAGE_DURATION.search(plain)
        if duration:
            stage["duration"] = duration.group(1).strip()
            plain = plain[: duration.start()].strip(" ;,")
        assert plain, (
            f"Stage {match.group(1)} of {affliction.get('name')!r} has no effect text — "
            "the stage was published but not understood"
        )
        stage["effect"] = plain
        links = _block_links(value)
        if links:
            stage["links"] = links
        stages.append(stage)
    if stages:
        expected = list(range(1, len(stages) + 1))
        assert [st["stage"] for st in stages] == expected, (
            f"{affliction.get('name')!r} publishes stages "
            f"{[st['stage'] for st in stages]}, which is not a run from 1"
        )
        affliction["stages"] = stages


def _extract_escalations(affliction, bs, subtype):
    """ "Curse 5", "Curse 6" — the affliction growing stronger as a story runs.

    Adventure-path afflictions publish later levels as their own bold labels,
    each describing what changes at that level. They are not stages: a stage is
    a step through one affliction, an escalation replaces the whole thing with
    a higher-level version.
    """
    escalations = []
    for match, value in _labelled_blocks(bs, _escalation_re(subtype)):
        effect = plain_text(value).strip(" ;,")
        assert effect, (
            f"{match.group(0)!r} on {affliction.get('name')!r} has no text — the "
            "escalation was published but not understood"
        )
        entry = build_object("stat_block_section", "affliction_escalation", match.group(0))
        entry["level"] = int(match.group(1))
        entry["effect"] = effect
        links = _block_links(value)
        if links:
            entry["links"] = links
        escalations.append(entry)
    if escalations:
        levels = [e["level"] for e in escalations]
        assert levels == sorted(set(levels)), (
            f"{affliction.get('name')!r} publishes escalations {levels}, "
            "which are not in ascending order or repeat a level"
        )
        affliction["escalations"] = escalations


# Labels owned by a dedicated extractor rather than by FIELD_LABELS.
_OWNED_LABELS = {"Source", "Sources"}


def _assert_no_unknown_labels(affliction, published, subtype):
    """Every published bold is a known field, a stage, or an escalation.

    Escalations are matched against this affliction's own type: a "Curse 7"
    bold on a disease page is not an escalation the parser understood, it is a
    page it has misread.
    """
    escalation = _escalation_re(subtype)
    for label in published:
        if not label:
            continue
        if label in FIELD_LABELS or label in _OWNED_LABELS:
            continue
        if _STAGE.match(label) or escalation.match(label):
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
        if value is None:
            continue
        assert isinstance(value, str), f"Field {key!r} is {type(value).__name__}, not text"
        if "<br" not in value:
            continue
        parts = re.split(r"<br\s*/?>", value, maxsplit=1)
        affliction[key] = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            prose.append(parts[1].strip())
    return "<br/>".join(prose)


def _structure_fields(affliction):
    """Turn the extracted strings into the structures the schema expects."""
    raw = affliction.get("saving_throw")
    if raw:
        # Harvest before flattening: the save line links its save type and any
        # condition it inflicts, and plain text alone would drop them.
        links = _block_links(raw)
        if links:
            affliction.setdefault("links", []).extend(links)
        plain = plain_text(raw).strip(" ;,")
        # strict: every DC an affliction prints is a number, so a DC that will
        # not parse is a bug to surface rather than prose to fall back on.
        save = parse_save_dc(plain, strict=True)
        assert save.get("dc") or save.get("save_type"), (
            f"Saving throw {plain!r} on {affliction.get('name')!r} carries neither "
            "a DC nor a Fortitude/Reflex/Will save name"
        )
        affliction["saving_throw"] = save

    for key in _TEXT_FIELDS:
        if key in affliction:
            affliction[key] = affliction[key].strip(" ;,")
