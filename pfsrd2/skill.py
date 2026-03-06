import json
import os
import sys
from pprint import pprint

import html2markdown
from bs4 import BeautifulSoup, Tag

import re

from pfsrd2.action import build_action_type
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
    action_extract_pass(struct)
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
    markdown_pass(struct, struct["name"], "")
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "skill.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_skill(jsondir, struct, name)
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


_ACTION_TITLE_MAP = {
    "Single Action": "One Action",
    "Two Actions": "Two Actions",
    "Three Actions": "Three Actions",
    "Reaction": "Reaction",
    "Free Action": "Free Action",
}

_RESULT_FIELDS = [
    "Critical Success",
    "Critical Failure",
    "Success",
    "Failure",
]


def action_extract_pass(struct):
    """Extract structured data from action subsections."""
    for section in struct["sections"]:
        if not section.get("name", "").endswith("Actions"):
            continue
        # Determine trained/untrained from parent section name
        parts = section["name"].split()
        # e.g. "Acrobatics Untrained Actions" or "Athletics Trained Actions"
        trained = None
        for p in parts:
            if p.lower() in ("trained", "untrained"):
                trained = p.lower() == "trained"
                break
        for action_section in section.get("sections", []):
            _extract_action_type_from_name(action_section)
            if trained is not None:
                action_section["trained"] = trained
            if "text" in action_section:
                _extract_action_text(action_section)


def _extract_action_type_from_name(section):
    """Extract action type span from section name before links are stripped."""
    name = section.get("name", "")
    bs = BeautifulSoup(name, "html.parser")
    action_span = bs.find("span", {"class": "action"})
    if action_span:
        title = action_span.get("title", "")
        if title in _ACTION_TITLE_MAP:
            section["action_type"] = build_object(
                "stat_block_section", "action_type", _ACTION_TITLE_MAP[title]
            )


def _extract_action_text(section):
    """Extract traits, source, requirements, and result blocks from action text."""
    bs = BeautifulSoup(section["text"], "html.parser")

    # 1. Extract trait spans
    traits = []
    for span in bs.find_all("span", {"class": "trait"}):
        a = span.find("a")
        if a:
            name, trait_link = extract_link(a)
            traits.append(
                build_object("stat_block_section", "trait", name.strip(), {"link": trait_link})
            )
        span.decompose()
    if traits:
        section["traits"] = traits

    # 2. Strip letter-spacing spans (trait separators)
    for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
        span.decompose()

    # 3. Extract source
    source_tag = bs.find("b", string=lambda s: s and s.strip() == "Source")
    if source_tag:
        siblings = list(source_tag.next_siblings)
        source_tag.decompose()
        while siblings and isinstance(siblings[0], str) and not siblings[0].strip():
            siblings[0].extract()
            siblings.pop(0)
        if siblings and getattr(siblings[0], "name", None) in ("a", "i"):
            book = siblings.pop(0)
            source = extract_source(book)
            book.decompose()
            while siblings and isinstance(siblings[0], str) and not siblings[0].strip():
                siblings[0].extract()
                siblings.pop(0)
            if siblings and getattr(siblings[0], "name", None) == "sup":
                sup = siblings.pop(0)
                _, source["errata"] = extract_link(sup.find("a"))
                sup.decompose()
            if siblings and getattr(siblings[0], "name", None) == "br":
                siblings[0].decompose()
            section["source"] = source

    # 4. Split on <hr> — pre-hr is stats (requirements etc), post-hr is description
    hr = bs.find("hr")
    if hr:
        # Everything before <hr> is the stats area
        pre_hr_parts = []
        for sibling in list(hr.previous_siblings):
            pre_hr_parts.insert(0, str(sibling))
            sibling.extract()
        hr.decompose()
        pre_hr_text = "".join(pre_hr_parts).strip()

        # Extract bold fields from pre-hr area
        _extract_bold_fields(section, pre_hr_text)

    # 5. Extract result blocks from remaining text (post-hr / description area)
    _extract_result_blocks(section, bs)

    # 6. Clean remaining text
    text = str(bs).strip()
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    section["text"] = text.strip()


def _extract_bold_fields(section, text):
    """Extract Requirements, Trigger, Frequency, Cost from pre-hr text."""
    bs = BeautifulSoup(text, "html.parser")
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if label not in ("Requirements", "Requirement", "Trigger",
                          "Frequency", "Cost", "Duration"):
            continue
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                break
            parts.append(str(node))
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        if value.endswith(";"):
            value = value[:-1].strip()
        key = label.lower().replace(" ", "_")
        if key == "requirement":
            key = "requirements"
        section[key] = value


def _extract_result_blocks(section, bs):
    """Extract Critical Success/Success/Failure/Critical Failure from description."""
    result_labels = {
        "Critical Success": "critical_success",
        "Success": "success",
        "Failure": "failure",
        "Critical Failure": "critical_failure",
    }
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if label not in result_labels:
            continue
        key = result_labels[label]
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                # Check if next bold is also a result label
                next_label = get_text(node).strip()
                if next_label in result_labels:
                    break
            parts.append(str(node))
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        section[key] = value
        # Remove the bold tag and its text from the soup
        for node in list(bold.next_siblings):
            if getattr(node, "name", None) == "b" and get_text(node).strip() in result_labels:
                break
            node.extract()
        bold.decompose()


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


_LINK_FIELDS = [
    "text", "requirements", "trigger", "frequency", "cost", "effect", "duration",
    "critical_success", "success", "failure", "critical_failure",
]


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
        for field in _LINK_FIELDS:
            _handle_text_field(section, field)
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
