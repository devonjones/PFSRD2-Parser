import json
import os
import sys
from pprint import pprint

import html2markdown
from bs4 import BeautifulSoup, Tag

from pfsrd2.condition import extract_span_traits
from pfsrd2.license import license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.sources import fetch_source_by_name
from universal.files import char_replace, makedirs
from universal.markdown import md
from universal.universal import (
    aon_pass,
    build_object,
    entity_pass,
    extract_link,
    extract_source,
    game_id_pass,
    get_links,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
)
from universal.utils import bs_pop_spaces, get_text, get_unique_tag_set, log_element


def parse_skill(filename, options):
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
    struct = restructure_skill_pass(details)
    skill_struct_pass(struct)
    source_pass(struct, find_skill)
    _extract_key_ability(struct)
    _remove_related_feats(struct)
    _strip_details_tags(struct)
    skill_link_pass(struct)
    # General_true filenames have format Skills.aspx.General_true.ID_X.html
    # Normalize to Skills.aspx.ID_X.html for aon_pass
    aon_basename = basename.replace(".General_true", "")
    aon_pass(struct, aon_basename)
    restructure_pass(struct, "skill", find_skill)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    skill_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    license_pass(struct)
    # TODO: Enable these passes as extraction matures
    # markdown_pass(struct, struct["name"], "")
    # if not options.skip_schema:
    #     struct["schema_version"] = 1.0
    #     validate_against_schema(struct, "skill.schema.json")
    # if not options.dryrun:
    #     output = options.output
    #     for source in struct["sources"]:
    #         name = char_replace(source["name"])
    #         jsondir = makedirs(output, struct["game-obj"], name)
    #         write_skill(jsondir, struct, name)
    # elif options.stdout:
    #     print(json.dumps(struct, indent=2))

    from pprint import pprint
    pprint(struct)


def _content_filter(soup):
    """Remove navigation elements before <hr> and unwrap the content span."""
    main = soup.find(id="main")
    if not main:
        return
    hr = main.find("hr")
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
            break


def _sidebar_filter(soup):
    divs = soup.find_all("div", {"class": "siderbarlook"})
    for div in divs:
        div.decompose()
    divs = soup.find_all("div", {"class": "sidebar-nofloat"})
    for div in divs:
        div.unwrap()


def restructure_skill_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    top = {"name": sb["name"], "type": "skill", "sections": [sb]}
    sb["type"] = "stat_block_section"
    sb["subtype"] = "skill"
    top["sections"].extend(rest)
    if len(sb["sections"]) > 0:
        top["sections"].extend(sb["sections"])
        sb["sections"] = []
    return top


def find_skill(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "skill":
            return section


SKILL_ATTRIBUTES = {
    "str",
    "dex",
    "con",
    "int",
    "wis",
    "cha",
}


def _extract_key_ability(struct):
    """Extract key ability from skill name like 'Acrobatics (Dex)'."""
    skill = find_skill(struct)
    if not skill:
        return
    name = skill["name"]
    bs = BeautifulSoup(name, "html.parser")
    text = get_text(bs).strip()
    if "(" not in text:
        return
    parts = text.rsplit("(", 1)
    clean_name = parts[0].strip()
    attr = parts[1].replace(")", "").strip().lower()
    if attr in SKILL_ATTRIBUTES:
        skill["key_ability"] = attr
        # Rebuild name without the attribute
        # Preserve any HTML (links) but strip the "(Attr)" suffix
        if "(" in name:
            skill["name"] = name[: name.rfind("(")].strip()


def _remove_related_feats(struct):
    """Remove the 'Related Feats' section — it's just a link."""
    struct["sections"] = [
        s for s in struct["sections"] if s.get("name") != "Related Feats"
    ]


def _strip_details_tags(struct):
    """Strip <details> tags (item bonus widgets) from all text fields."""

    def _strip(section):
        if "text" in section:
            if "<details" in section["text"]:
                bs = BeautifulSoup(section["text"], "html.parser")
                while bs.details:
                    bs.details.decompose()
                section["text"] = str(bs).strip()
        for s in section.get("sections", []):
            _strip(s)

    for section in struct["sections"]:
        _strip(section)


def skill_struct_pass(struct):
    def _extract_source(section):
        if "text" not in section:
            return None
        bs = BeautifulSoup(section["text"], "html.parser")
        source_tag = bs.find("b", string=lambda s: s and s.strip() == "Source")
        if not source_tag:
            return None
        # Remove the <b>Source</b> tag and extract source info
        siblings = list(source_tag.next_siblings)
        source_tag.decompose()
        # Pop whitespace
        while siblings and isinstance(siblings[0], str) and not siblings[0].strip():
            siblings[0].extract()
            siblings.pop(0)
        if siblings and siblings[0].name in ("a", "i"):
            book = siblings.pop(0)
            source = extract_source(book)
            book.decompose()
        else:
            return None
        # Pop whitespace
        while siblings and isinstance(siblings[0], str) and not siblings[0].strip():
            siblings[0].extract()
            siblings.pop(0)
        if siblings and getattr(siblings[0], "name", None) == "sup":
            assert "errata" not in source, "Should be no more than one errata."
            sup = siblings.pop(0)
            _, source["errata"] = extract_link(sup.find("a"))
            sup.decompose()
        if siblings and getattr(siblings[0], "name", None) == "br":
            siblings[0].decompose()
            siblings.pop(0)
        section["text"] = str(bs).strip()
        return [source]

    sources = []
    for section in struct["sections"]:
        sec_sources = _extract_source(section)
        if sec_sources:
            section["sources"] = sec_sources
            sources.extend(sec_sources)
        else:
            section["sources"] = []
    struct["sources"] = sources

    def _handle_legacy_content(struct):
        sections = struct.get("sections", [])
        for i, section in enumerate(sections):
            if section.get("name") == "Legacy Content" and i > 0:
                prev_section = sections[i - 1]
                if "text" not in prev_section and "text" in section:
                    prev_section["text"] = section["text"]
                del sections[i]
                break

    _handle_legacy_content(struct)


def skill_link_pass(struct):
    def _handle_text_field(section, field, keep=True):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs)
        if len(links) > 0 and keep:
            linklist = section.setdefault("links", [])
            linklist.extend(links)
        while bs.a:
            bs.a.unwrap()
        # Strip action spans from names
        for span in bs.find_all("span", {"class": "action"}):
            span.decompose()
        # Strip letter-spacing spans (trait separators)
        for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
            span.decompose()
        section[field] = str(bs).strip()

    for section in struct["sections"]:
        _handle_text_field(section, "name", False)
        _handle_text_field(section, "text")
        if "sections" in section:
            skill_link_pass(section)


def skill_cleanup_pass(struct):
    def _clean_text():
        struct["name"] = skill["name"]
        del skill["name"]
        if "text" not in skill:
            return
        soup = BeautifulSoup(skill["text"], "html.parser")
        # Remove Nethys notes
        first = list(soup.children)[0] if list(soup.children) else None
        if first and first.name == "i":
            text = get_text(first)
            if text.find("Note from Nethys:") > -1:
                first.clear()
            first.unwrap()
        # Strip <details> (item bonuses widget)
        while soup.details:
            soup.details.decompose()
        skill["text"] = str(soup).strip()
        if skill["text"] != "":
            assert "text" not in struct, struct
            struct["text"] = html2markdown.convert(skill["text"])
        del skill["text"]

    def _clean_sections():
        def _clean_html(section):
            if "html" in section:
                section["text"] = section["html"]
                del section["html"]
            if "sections" in section:
                for s in section["sections"]:
                    _clean_html(s)

        if len(skill["sections"]) != 0:
            struct["sections"] = skill["sections"]
        del skill["sections"]
        if "sections" in struct:
            for section in struct["sections"]:
                _clean_html(section)

    def _clean_links():
        if skill.get("links"):
            assert "links" not in struct, struct
            struct["links"] = skill["links"]
            del skill["links"]

    def _clean_misc():
        struct["sources"] = skill["sources"]
        del skill["sources"]
        if "key_ability" in skill:
            struct["key_ability"] = skill["key_ability"]
            del skill["key_ability"]
        del skill["type"]
        del skill["subtype"]

    skill = struct["skill"]
    _clean_text()
    _clean_sections()
    _clean_links()
    _clean_misc()
    assert len(skill) == 0, skill
    del struct["skill"]


def write_skill(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_skill_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_skill_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)


def markdown_pass(struct, name, path):
    def _validate_acceptable_tags(text):
        validset = {
            "i",
            "b",
            "u",
            "strong",
            "ol",
            "ul",
            "li",
            "br",
            "table",
            "tr",
            "td",
            "hr",
        }
        tags = get_unique_tag_set(text)
        assert tags.issubset(validset), f"{name} : {text} - {tags}"

    for k, v in struct.items():
        if isinstance(v, dict):
            markdown_pass(v, name, f"{path}/{k}")
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    markdown_pass(item, name, f"{path}/{k}")
                elif isinstance(item, str) and item.find("<") > -1:
                    raise AssertionError()
        elif isinstance(v, str) and v.find("<") > -1:
            if "<div" in v or "<p" in v:
                bs = BeautifulSoup(v, "html.parser")
                for div in bs.find_all("div"):
                    if not div.get_text(strip=True):
                        div.decompose()
                    else:
                        div.unwrap()
                for p in bs.find_all("p"):
                    p.unwrap()
                v = str(bs)
                struct[k] = v
            _validate_acceptable_tags(v)
            struct[k] = md(v).strip()
            log_element("markdown.log")("{} : {}".format(f"{path}/{k}", name))


def set_edition_from_db_pass(struct):
    db_path = get_db_path("pfsrd2.db")
    conn = get_db_connection(db_path)
    curs = conn.cursor()
    for source in struct.get("sources", []):
        fetch_source_by_name(curs, source["name"])
        row = curs.fetchone()
        if row and row.get("edition"):
            struct["edition"] = row["edition"]
    conn.close()
