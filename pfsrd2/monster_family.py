import json
import os
import sys

from bs4 import BeautifulSoup, Tag

from pfsrd2.change_enrichment import change_enrichment_pass
from pfsrd2.change_extraction import parse_change
from universal.ability import parse_abilities_from_nodes
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


def parse_monster_family(filename, options):
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
    struct = restructure_monster_family_pass(details)
    if alternate_link:
        struct["alternate_link"] = alternate_link
    monster_family_struct_pass(struct)
    _strip_empty_text(struct)
    source_pass(struct, find_monster_family)
    _extract_creation_changes(struct)
    monster_family_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, "monster_family", find_monster_family)
    _extract_section_abilities(struct)
    _consolidate_creation_changes(struct)
    change_enrichment_pass(struct, "monster_family")
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    monster_family_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "", fxn_valid_tags=_valid_tags)
    remove_empty_fields(struct)
    _strip_image_links(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "monster_family.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, "monster_families", name)
            write_monster_family(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def _content_filter(soup):
    """Remove navigation elements and unwrap content spans.

    MonsterFamilies pages use the creature-style nav with multiple top-level
    <hr> tags and content wrapped in <span> elements.
    """
    main = soup.find(id="main")
    assert main, "No #main div found in HTML"
    # Strip nav before first top-level <hr>
    hr = main.find("hr", recursive=False)
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()
    # Remove remaining top-level <hr> tags (nav dividers)
    for hr in main.find_all("hr", recursive=False):
        hr.extract()
    # Unwrap content spans containing h1
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
            break
    # Remove empty spans
    for span in main.find_all("span", recursive=False):
        if not span.get_text(strip=True):
            span.decompose()
    # Remove empty anchors
    for a in main.find_all("a"):
        if not a.string and not a.contents:
            a.decompose()
    # Decompose sidebar images in headings (icons)
    for img in main.find_all("img"):
        img.decompose()
    # Keep action spans intact — the unified ability parser extracts them.
    # Unwrap siderbarlook divs (alternate link handled separately)
    for div in main.find_all("div", {"class": "siderbarlook"}):
        div.unwrap()
    # Split h3.title tags that contain body content (abilities, descriptions).
    # These are headings with inline content — the h3 wraps both the title AND
    # the body. Split: extract title as a clean h3, unwrap the rest so it becomes
    # sibling content. parse_universal's title_collapse_pass groups it correctly.
    for h3 in list(main.find_all("h3", {"class": "title"})):
        has_body_content = h3.find("br") or h3.find("ul") or h3.find("b")
        if not has_body_content:
            continue
        # Extract the title text — everything before the first body element
        title_parts = []
        for child in list(h3.children):
            if isinstance(child, Tag) and child.name in ("br", "b", "ul"):
                break
            title_parts.append(child.extract())
        title_text = "".join(str(p) for p in title_parts).strip()
        if title_text:
            new_h3 = BeautifulSoup(
                f'<h3 class="title">{title_text}</h3>', "html.parser"
            ).h3
            h3.insert_before(new_h3)
        h3.unwrap()
    # Remove the "Members" heading and its creature list.
    # <h3 class="framing">Members</h3> followed by creature links
    for h3 in main.find_all("h3", {"class": "framing"}):
        text = h3.get_text(strip=True)
        if text == "Members":
            node = h3.next_sibling
            while node:
                next_node = node.next_sibling
                if hasattr(node, "name") and node.name in ("h1", "h2", "h3"):
                    break
                node.extract()
                node = next_node
            h3.extract()


def restructure_monster_family_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    top = {"name": sb["name"], "type": "monster_family", "sections": [sb]}
    sb["type"] = "stat_block_section"
    sb["subtype"] = "monster_family"
    top["sections"].extend(rest)
    if len(sb["sections"]) > 0:
        top["sections"].extend(sb["sections"])
        sb["sections"] = []
    return top


def find_monster_family(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "monster_family":
            return section


def monster_family_struct_pass(struct):
    """Extract sources from section text fields, recursively."""

    def _extract_source(section):
        if "text" not in section:
            return None
        # Guard against empty text that would cause IndexError in source_pass
        text = section["text"].strip()
        if not text:
            return None
        bs = BeautifulSoup(text, "html.parser")
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


def _extract_creation_changes(struct):
    """Extract structured changes from 'Creating X' sections.

    These sections contain <ul><li> lists of stat modifications, similar to
    monster templates. Extract them into changes arrays with change_category
    and effects.
    """
    all_sections = struct.get("sections", [])

    def _is_creation_section(name):
        n = name.lower()
        if "creating" in n or "building" in n:
            return True
        if "abilities" in n:
            return True
        if "spellcasters" in n:
            return True
        if "adjustments" in n:
            return True
        return False

    def _process_section(section):
        name = section.get("name", "")
        if _is_creation_section(name) and "text" in section:
            _extract_changes_from_section(section, all_sections)
        for sub in section.get("sections", []):
            _process_section(sub)

    for section in all_sections:
        _process_section(section)


def _extract_changes_from_section(section, all_sections=None):
    """Extract <ul><li> changes from a creation section's text."""

    text = section.get("text", "")
    bs = BeautifulSoup(text, "html.parser")
    ul = bs.find("ul")
    if not ul:
        return
    changes = []
    for li in ul.find_all("li", recursive=False):
        if not get_text(li).strip():
            continue
        change = parse_change(li)
        changes.append(change)
    ul.decompose()
    section["text"] = str(bs).strip()
    if not changes:
        return
    section["changes"] = changes

    # Adjustments tables are handled by the enrichment pipeline


def _consolidate_creation_changes(struct):
    """Collect creation data into monster_family object.

    Pulls changes from creation sections into monster_family.changes, and
    collects ability sections (e.g., "Basic Vampire Abilities",
    "True Vampire Abilities") into monster_family.subtypes. Each subtype
    is itself a monster_family object with name, text, and abilities.
    """
    mf = struct.get("monster_family")
    assert mf is not None, f"No monster_family in struct: {struct.get('name')}"
    all_changes = []
    subtypes = []
    remaining = []

    def _collect_changes(sections):
        for section in sections:
            if "changes" in section:
                all_changes.extend(section["changes"])
                del section["changes"]
            _collect_changes(section.get("sections", []))

    _collect_changes(struct.get("sections", []))

    def _build_subtype(section):
        """Convert a section with abilities into a monster_family subtype.

        The abilities are wrapped in a change object with
        change_category="abilities" so they follow the same pattern as
        monster_template changes. The raw abilities list needs further
        processing (PFSRD2-Parser-alj) to separate true abilities from
        stat modifications like Immunities, Speed, etc.
        """
        subtype = {
            "name": section.get("name", ""),
            "type": "stat_block_section",
            "subtype": "monster_family",
        }
        if section.get("text"):
            subtype["text"] = section["text"]
        if section.get("abilities"):
            change = {
                "type": "stat_block_section",
                "subtype": "change",
                "text": section.get("name", ""),
                "change_category": "abilities",
                "abilities": section["abilities"],
                "effects": [
                    {
                        "target": "$.defense.automatic_abilities",
                        "operation": "add_items",
                        "source": "$.monster_family.subtypes[*].changes[*].abilities",
                    }
                ],
            }
            if section.get("links"):
                change["links"] = section["links"]
            subtype["changes"] = [change]
        # Recurse into subsections
        child_subtypes = []
        for sub in section.get("sections", []):
            if sub.get("abilities"):
                child_subtypes.append(_build_subtype(sub))
        if child_subtypes:
            subtype["subtypes"] = child_subtypes
        return subtype

    def _has_abilities_anywhere(section):
        """Check if section or any subsection has abilities."""
        if section.get("abilities"):
            return True
        return any(_has_abilities_anywhere(s) for s in section.get("sections", []))

    # Collect ability sections into subtypes — check both top level and subsections
    for section in struct.get("sections", []):
        if _has_abilities_anywhere(section):
            # Section has abilities directly or in subsections
            if section.get("abilities"):
                subtypes.append(_build_subtype(section))
            else:
                # Abilities are in subsections only (e.g., "Creating a Vampire"
                # has "Basic Vampire Abilities" as a child)
                kept_subs = []
                for sub in section.get("sections", []):
                    if _has_abilities_anywhere(sub):
                        subtypes.append(_build_subtype(sub))
                    else:
                        kept_subs.append(sub)
                section["sections"] = kept_subs
                remaining.append(section)
        else:
            remaining.append(section)

    struct["sections"] = remaining
    if all_changes:
        mf["changes"] = all_changes
    if subtypes:
        mf["subtypes"] = subtypes


def _strip_empty_text(struct):
    """Remove empty text fields that would cause IndexError in source_pass."""
    for section in struct.get("sections", []):
        if "text" in section and not section["text"].strip():
            del section["text"]
        _strip_empty_text(section)


def _strip_image_links(struct):
    """Remove image-only links that lack name/alt (from decomposed <img> in <a>)."""

    def _filter_links(obj):
        if isinstance(obj, dict):
            if "links" in obj:
                obj["links"] = [l for l in obj["links"] if "name" in l or "game-obj" in l]
                if not obj["links"]:
                    del obj["links"]
            for v in obj.values():
                _filter_links(v)
        elif isinstance(obj, list):
            for item in obj:
                _filter_links(item)

    _filter_links(struct)


def _valid_tags(struct, name, path, validset):
    """Allow additional tags in monster family creation sections.

    Some creation sections have embedded headings and malformed tags
    that can't be cleanly extracted without rewriting the HTML.
    """
    # h2/h3 from embedded headings in creation sections
    # t from malformed HTML in Lich family
    validset.update({"h2", "h3", "t"})


def _extract_section_abilities(struct):
    """Extract inline abilities from section text fields.

    Monster family "Creating X" sections contain abilities as <b>Name</b>
    followed by description text, separated by <br>. This extracts them
    into structured ability objects on the section using the unified parser.
    """

    def _process(section):
        if "text" in section:
            text = section["text"]
            # Only process if there are <b> tags (potential abilities)
            if "<b>" in text or "<b " in text:
                bs = BeautifulSoup(text, "html.parser")
                # Don't extract from text that's purely in tables
                if bs.find("b") and not (
                    bs.find("table") and not bs.find("b", recursive=False)
                ):
                    abilities = _extract_abilities_from_bs(bs)
                    if abilities:
                        section["text"] = str(bs).strip()
                        section.setdefault("abilities", []).extend(abilities)
        for sub in section.get("sections", []):
            _process(sub)

    for section in struct.get("sections", []):
        _process(section)


def _extract_abilities_from_bs(bs):
    """Extract abilities from a BS object using the unified parser.

    Finds the first <b> tag not inside a <table> and collects all nodes
    from there onward, then passes them to the unified ability parser.
    """
    first_b = None
    for b in bs.find_all("b"):
        if not b.find_parent("table"):
            first_b = b
            break
    if not first_b:
        return None
    # Collect all nodes from the first <b> onward (siblings only)
    ability_nodes = []
    node = first_b
    while node:
        next_node = node.next_sibling
        ability_nodes.append(node.extract())
        node = next_node
    return parse_abilities_from_nodes(ability_nodes)


def monster_family_link_pass(struct):
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


def monster_family_cleanup_pass(struct):
    """Promote fields from monster_family object to top level."""
    mf = struct.get("monster_family")
    assert mf is not None, f"No monster_family object found in struct: {struct.get('name')}"
    struct["name"] = mf["name"]
    struct["sources"] = mf["sources"]
    del mf["sources"]
    if "text" in mf:
        struct["text"] = mf["text"]
        del mf["text"]
    if "links" in mf:
        struct["links"] = mf["links"]
        del mf["links"]
    _clean_html_fields(struct)


def _clean_html_fields(struct):
    """Rename 'html' keys to 'text' in sections recursively."""
    for section in struct.get("sections", []):
        if "html" in section:
            section["text"] = section["html"]
            del section["html"]
        if "sections" in section:
            _clean_html_fields(section)


def write_monster_family(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_monster_family_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_monster_family_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
