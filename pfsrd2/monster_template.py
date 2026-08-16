import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString

from pfsrd2.ability_enrichment import template_ability_enrichment_pass
from pfsrd2.change_enrichment import change_enrichment_pass
from pfsrd2.change_extraction import (
    collect_ability_nodes,
    parse_adjustments_table,
    parse_change,
)
from pfsrd2.enrichment.change_extractor import choice_bounds
from pfsrd2.equivalents import equivalent_link_pass
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.prose_changes import prose_changes_from_text
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from universal.ability import ADDON_LABELS_WITH_RESULTS, parse_abilities_from_nodes
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.monster_ability import monster_ability_db_pass
from universal.universal import (
    aon_pass,
    build_object,
    entity_pass,
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

# Section intros that unconditionally grant their abilities (vs choose-from
# pools, which the engine must never auto-apply).
_GRANTS_ABILITIES = re.compile(
    # Unconditional grants only: modal wording ("may/can/might gain the
    # following abilities") is a choice, not a grant, and must stay pooled.
    r"(?<!\bmay )(?<!\bcan )(?<!\bmight )\bgains?\s+the\s+following\s+abilit",
    re.IGNORECASE,
)


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
    equivalent_link_pass(struct)
    monster_template_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    monster_ability_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "")
    change_enrichment_pass(struct, "monster_template")
    reorder_changes_pass(struct)
    template_ability_enrichment_pass(struct)
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
        print(json.dumps(struct, indent=2, sort_keys=True))


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
    if ul and not mt.get("_ul_changes_extracted"):
        changes = []
        for li in ul.find_all("li", recursive=False):
            if not get_text(li).strip():
                continue
            change = parse_change(li)
            changes.append(change)
        ul.decompose()
        source_section["text"] = str(bs).strip()
        # Intro prose in the ul-bearing creation section may carry stat
        # instructions that never made the list — Experimental Cryptid's
        # "Increase the creature's level by 1 and change its statistics as
        # follows." Document order: intro prose precedes the <li> changes.
        prose = prose_changes_from_text(source_section["text"])
        # granting ability sections may have appended changes already —
        # the <li> changes are the template's primary list and go first
        mt["changes"] = prose + changes + mt.get("changes", [])
        mt["_ul_changes_extracted"] = True
        found = True
    # Check for inline abilities — either when there's no <ul>, or in
    # remaining text after the <ul> was removed (ancestry templates put
    # abilities after the </ul>)
    abilities = _extract_abilities_from_bs(bs)
    if abilities:
        remaining = str(bs).strip()
        source_section["text"] = remaining
        # A section that GRANTS its abilities unconditionally ("All host
        # creatures gain the following abilities.") is a construction
        # instruction like any <li>: emit it as a change so enrichment
        # builds placement effects. Choose-from pools ("one of the
        # following") and plain ability sections stay at mt.abilities —
        # the engine only auto-applies those when the template has no
        # changes at all, which is exactly the ability-only case.
        section_text = get_text(bs)
        if source_section is not mt and (
            _GRANTS_ABILITIES.search(section_text) or choice_bounds(section_text) is not None
        ):
            # Mirror parse_change: links must be extracted before the text
            # is captured — raw <a> in change text fails markdown validation.
            links = get_links(bs, unwrap=True)
            remaining = str(bs).strip()
            source_section["text"] = remaining
            change = build_object("stat_block_section", "change", "")
            del change["name"]
            change["text"] = remaining
            if links:
                change["links"] = links
            change["abilities"] = abilities
            mt.setdefault("changes", []).append(change)
        else:
            mt.setdefault("abilities", []).extend(abilities)
        found = True
    return found


def _assert_only_separators_were_unclaimed(nodes, consumed):
    """Every node the ability parser did not claim must be a separator.

    Shape, not emptiness: plain_text() measures an <img> or an attribute-only
    <a> as empty, so testing for empty text would let a text-free node drop as
    silently as before. What the corpus actually shows is that unclaimed nodes
    are <br/> separators and pretty-printer whitespace — so assert that, which
    is both the measured invariant and the stricter one.

    Five paths in universal.ability._split_nodes can leave a node unclaimed,
    and they split two ways. Two of them produce everything this guard ALLOWS:
    the <br> branch, whose _consume sits inside `if current:`, and the loop's
    final `if current:` fall-through. Between them they account for every
    unclaimed node in the corpus — the 24 <br/>s and the pretty-printer
    newlines.

    The other three are the levers if this fires: the _LEAD_IN_RE branch,
    which skips a lead-in on the grounds that it "already lives in the
    sections text" — a premise this file breaks by overwriting that text; the
    _NOT_ABILITY_NAMES branch, which drops a label and its value line
    together; and a continuation the glue rules refuse.
    """
    for node in nodes:
        if id(node) in consumed:
            continue
        if isinstance(node, NavigableString):
            assert not node.strip(), (
                f"The ability parser did not claim the text {str(node).strip()!r}, and "
                "it is about to be dropped: collect_ability_nodes removed it from the "
                "tree and this section's text is overwritten from what remains. See "
                "universal.ability._split_nodes (_LEAD_IN_RE, or the continuation glue)"
            )
        else:
            assert node.name == "br", (
                f"The ability parser did not claim a <{node.name}>, and it is about to "
                "be dropped: collect_ability_nodes removed it from the tree and this "
                "section's text is overwritten from what remains. Only <br/> separators "
                "are expected to go unclaimed"
            )


def _extract_abilities_from_bs(bs):
    """Extract abilities from a BS object using the unified parser.

    collect_ability_nodes EXTRACTS its nodes from the tree, and when this
    returns abilities the caller overwrites the section text with str(bs) — so
    any node the ability parser did not claim is gone from the output with
    nothing said. Across all 55 templates the only unclaimed nodes are the
    <br/> separators between abilities, which is why nothing has been lost yet.

    Rather than putting the separators back — they would render as stray hard
    breaks — assert that only separators went unclaimed. That turns the one
    genuinely silent drop in this file into a loud failure without changing any
    output.

    The assert runs only when there ARE abilities, because that is exactly when
    the caller overwrites the section text with what survived extraction. The
    <ul> branch also writes, but it does so BEFORE collect_ability_nodes
    mutates the tree, so it snapshots the pre-extraction string. Ordering, not the
    absence of a write, is what makes the gate safe, and
    TestTemplateCallerWriteBackOrdering pins it. Ungated, this would fail a
    build over content that still ships.

    monster_family.py deliberately does NOT need this: it parses a COPY and
    never reassigns section["text"]. See PFSRD2-Parser-4bcm, and
    PFSRD2-Parser-9oge for the separate question of attaching continuation
    prose to its ability.
    """
    nodes = collect_ability_nodes(bs)
    if not nodes:
        return None
    consumed = set()
    abilities = parse_abilities_from_nodes(
        nodes, addon_labels=ADDON_LABELS_WITH_RESULTS, consumed=consumed
    )
    if abilities:
        _assert_only_separators_were_unclaimed(nodes, consumed)
    return abilities


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
            adjustments = parse_adjustments_table(text)
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


# Categorization and effect-building code has moved to
# pfsrd2/enrichment/change_extractor.py (offline enrichment pipeline).
# Raw extraction code has moved to pfsrd2/change_extraction.py (shared).


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
    mt.pop("_ul_changes_extracted", None)
    _clean_html_fields(struct)


def reorder_changes_pass(struct):
    """Move hit_points changes ahead of the level change in changes[].

    Change effects apply sequentially, and hit_points band conditionals
    ("2-4 -> +15" etc.) reference $.creature_type.level, so they must
    evaluate against the creature's starting level — before a level change
    mutates it. Templates without a level change keep their source order.
    Requires change_category, so this runs after change_enrichment_pass.
    """
    mt = struct.get("monster_template")
    if not mt:
        return
    changes = mt.get("changes")
    if not changes:
        return
    cats = [c.get("change_category") for c in changes]
    if "level" not in cats or "hit_points" not in cats:
        return
    hp_changes = [c for c in changes if c.get("change_category") == "hit_points"]
    rest = [c for c in changes if c.get("change_category") != "hit_points"]
    # Reinsert all hit_points changes immediately before the first level
    # change, preserving relative order within both groups.
    insert_at = next(i for i, c in enumerate(rest) if c.get("change_category") == "level")
    mt["changes"] = rest[:insert_at] + hp_changes + rest[insert_at:]


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
    json.dump(struct, fp, indent=2, sort_keys=True)
    fp.close()


def create_monster_template_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
