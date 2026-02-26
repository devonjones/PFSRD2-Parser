import json
import os
import sys

import html2markdown
from bs4 import BeautifulSoup

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


def parse_condition(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=4,
        cssclass="main",
        pre_filters=[_content_filter, sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    struct = restructure_condition_pass(details)
    condition_struct_pass(struct)
    source_pass(struct, find_condition)
    subtype_pass(struct)
    condition_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, "condition", find_condition)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    condition_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    license_pass(struct)
    markdown_pass(struct, struct["name"], "")
    basename.split("_")
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "condition.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_condition(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


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


def sidebar_filter(soup):
    divs = soup.find_all("div", {"class": "sidebar-nofloat"})
    for div in divs:
        div.unwrap()


def restructure_condition_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    top = {"name": sb["name"], "type": "condition", "sections": [sb]}
    sb["type"] = "stat_block_section"
    sb["subtype"] = "condition"
    top["sections"].extend(rest)
    if len(sb["sections"]) > 0:
        top["sections"].extend(sb["sections"])
        sb["sections"] = []
    return top


def find_condition(struct):
    for section in struct["sections"]:
        if section["subtype"] == "condition":
            return section


def condition_struct_pass(struct):
    def _extract_source(section):
        if "text" in section:
            bs = BeautifulSoup(section["text"], "html.parser")
            children = list(bs.children)
            if children and children[0].name == "b" and get_text(children[0]) == "Source":
                children.pop(0)
                bs_pop_spaces(children)
                book = children.pop(0)
                source = extract_source(book)
                bs_pop_spaces(children)
                if children and children[0].name == "sup":
                    assert "errata" not in source, "Should be no more than one errata."
                    _, source["errata"] = extract_link(children.pop(0).find("a"))
                if children and children[0].name == "br":
                    children.pop(0)
                assert not (children and children[0].name == "a"), section
                section["text"] = "".join([str(c) for c in children])
                return [source]

    # Remove debug print
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
                # Remove the Legacy Content section
                del sections[i]
                break

    _handle_legacy_content(struct)


def subtype_pass(struct):
    struct["subtype"] = "standard"
    for source in struct["sources"]:
        if source["name"] == "Kingmaker Adventure Path":
            struct["subtype"] = "kingdom"
            return


def condition_link_pass(struct):
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
        section[field] = str(bs)

    for section in struct["sections"]:
        _handle_text_field(section, "name", False)
        _handle_text_field(section, "text")
        if "sections" in section:
            condition_link_pass(section)


def condition_cleanup_pass(struct):
    def _clean_text():
        soup = BeautifulSoup(condition["text"], "html.parser")
        first = list(soup.children)[0]
        if first.name == "i":
            text = get_text(first)
            if text.find("Note from Nethys:") > -1:
                first.clear()
            first.unwrap()
        struct["name"] = condition["name"]
        del condition["name"]
        condition["text"] = str(soup).strip()
        if condition["text"] != "":
            assert "text" not in struct, struct
            struct["text"] = html2markdown.convert(condition["text"])
        del condition["text"]

    def _clean_sections():
        def _clean_html(section):
            if "html" in section:
                section["text"] = section["html"]
                del section["html"]
            if "sections" in section:
                for s in section["sections"]:
                    _clean_html(s)

        if len(condition["sections"]) != 0:
            struct["sections"] = condition["sections"]
        del condition["sections"]
        if "sections" in struct:
            for section in struct["sections"]:
                _clean_html(section)

    def _clean_links():
        if condition.get("links"):
            assert "links" not in struct, struct
            struct["links"] = condition["links"]
            del condition["links"]

    def _clean_misc():
        struct["sources"] = condition["sources"]
        del condition["sources"]
        del condition["type"]
        del condition["subtype"]

    condition = struct["condition"]
    _clean_text()
    _clean_sections()
    _clean_links()
    _clean_misc()
    assert len(condition) == 0, condition
    del struct["condition"]


def write_condition(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_condition_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_condition_filename(jsondir, struct):
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
                    raise AssertionError()  # For now, I'm unaware of any tags in lists of strings
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


def extract_starting_traits(description):
    if description.strip().startswith("("):
        return _extract_trait(description)
    return description, []


def extract_span_traits(text):
    bs = BeautifulSoup(text, "html.parser")
    children = list(bs.children)
    newchildren = []
    traits = []
    while len(children) > 0:
        child = children.pop(0)
        if child.name == "span":  # and child["class"] == "trait":
            content = child.contents
            assert len(content) == 1, content
            a = content[0]
            name, trait_link = extract_link(a)
            traits.append(
                build_object("stat_block_section", "trait", name.strip(), {"link": trait_link})
            )
        else:
            newchildren.append(child)
            newchildren.extend(children)
            break
    text = "".join([str(c) for c in newchildren]).strip()
    return text, traits


def extract_all_traits(description):
    traits = []
    while description.find("(") > -1:
        description, ts = _extract_trait(description)
        traits.extend(ts)
    return description, traits


def _extract_trait(description):
    def _handle_trait_template(text):
        text = text.strip()
        if not text.startswith("["):
            return
        assert text.endswith("]")
        text = text[1:-1]
        template = build_object("trait_template", "", text)
        del template["subtype"]
        return template

    traits = []
    newdescription = []
    if description.find("(") > -1:
        front, middle = description.split("(", 1)
        newdescription.append(front)
        s = middle.split(")", 1)
        assert len(s) == 2, s
        text, back = s
        bs = BeautifulSoup(text, "html.parser")
        if bs.a and bs.a.has_attr("game-obj") and bs.a["game-obj"] == "Traits":
            if text.find(" or ") > -1:
                return description, []
            parts = [p.strip() for p in text.replace("(", "").split(",")]
            for part in parts:
                bs = BeautifulSoup(part, "html.parser")
                # Remove empty <a> tags (HTML5 artifacts)
                for a in bs.find_all("a"):
                    if not a.string and not a.contents:
                        a.decompose()
                children = list(bs.children)
                assert len(children) == 1, part
                child = children[0]
                template = _handle_trait_template(str(child))
                if template:
                    traits.append(template)
                else:
                    name, trait_link = extract_link(child)
                    traits.append(
                        build_object(
                            "stat_block_section", "trait", name.strip(), {"link": trait_link}
                        )
                    )
        else:
            newdescription.append(text)
            newdescription.append(")")
        description = back
    newdescription.append(description)
    return "".join(newdescription).strip(), traits


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
