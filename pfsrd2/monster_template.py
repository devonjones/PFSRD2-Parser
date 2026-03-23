import json
import os
import sys

from bs4 import BeautifulSoup

from pfsrd2.change_enrichment import change_enrichment_pass
from pfsrd2.change_extraction import (
    extract_inline_abilities,
    parse_adjustments_table,
    parse_change,
)
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.universal import (
    aon_pass,
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
    change_enrichment_pass(struct, "monster_template")
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
            change = parse_change(li)
            changes.append(change)
        ul.decompose()
        source_section["text"] = str(bs).strip()
        mt["changes"] = changes
        found = True
    # Check for inline abilities — either when there's no <ul>, or in
    # remaining text after the <ul> was removed (ancestry templates put
    # abilities after the </ul>)
    abilities = extract_inline_abilities(bs)
    if abilities:
        source_section["text"] = str(bs).strip()
        mt.setdefault("abilities", []).extend(abilities)
        found = True
    return found


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
