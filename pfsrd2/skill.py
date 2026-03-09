import json
import os
import re
import sys

from bs4 import BeautifulSoup

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from pfsrd2.sql.traits import trait_db_pass
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.markdown import md
from universal.universal import (
    aon_pass,
    build_object,
    entity_pass,
    extract_link,
    extract_source,
    extract_source_from_bs,
    game_id_pass,
    get_links,
    handle_alternate_link,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
)
from universal.utils import content_filter, get_text, remove_empty_fields, strip_block_tags


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
    alternate_link = handle_alternate_link(details)
    struct = restructure_skill_pass(details)
    if alternate_link:
        struct["alternate_link"] = alternate_link
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
    trait_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "")
    remove_empty_fields(struct)
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
    content_filter(soup)


def _sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. siderbarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
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

KINGDOM_ATTRIBUTES = {
    "culture",
    "economy",
    "loyalty",
    "stability",
}


def _extract_key_ability(struct):
    """Extract key ability and skill_type from skill name like 'Acrobatics (Dex)'."""
    skill = find_skill(struct)
    assert skill is not None, f"No skill section found in {struct.get('name', 'unknown')}"
    name = skill["name"]
    bs = BeautifulSoup(name, "html.parser")
    text = get_text(bs).strip()
    if "(" not in text:
        skill["skill_type"] = "character_skill"
        return
    parts = text.rsplit("(", 1)
    attr = parts[1].replace(")", "").strip().lower()
    if attr in SKILL_ATTRIBUTES:
        skill["key_ability"] = attr
        skill["skill_type"] = "character_skill"
        # Rebuild name without the attribute
        # Preserve any HTML (links) but strip the "(Attr)" suffix
        skill["name"] = name[: name.rfind("(")].strip()
    else:
        assert (
            attr in KINGDOM_ATTRIBUTES
        ), f"Unknown parenthesized attribute '{attr}' in skill '{text}'"
        skill["key_kingdom_ability"] = attr
        skill["skill_type"] = "kingdom_skill"
        skill["name"] = name[: name.rfind("(")].strip()


def _remove_related_feats(struct):
    """Remove the 'Related Feats' section — it's just a link."""
    struct["sections"] = [s for s in struct["sections"] if s.get("name") != "Related Feats"]


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
    """Extract structured data from action subsections into skill object."""
    skill = find_skill(struct)
    assert skill is not None, f"No skill section found in {struct.get('name', 'unknown')}"
    actions = []
    remaining_sections = []
    for section in struct["sections"]:
        if not section.get("name", "").endswith("Actions"):
            remaining_sections.append(section)
            continue
        # Determine trained/untrained from parent section name
        parts = section["name"].split()
        trained = None
        for p in parts:
            if p.lower() in ("trained", "untrained"):
                trained = p.lower() == "trained"
                break
        last_action = None
        for action_section in section.get("sections", []):
            # Skip "Related Feats" — just a link, not an action
            if action_section.get("name", "").startswith("Related Feats"):
                continue
            _extract_action_type_from_name(action_section)
            if "text" in action_section:
                _extract_action_text(action_section)
            _extract_sample_tasks(action_section)
            # If it has an action_type span or a source extracted from its
            # text, it's a real action. Otherwise it's a descriptive section
            # that belongs under the preceding action (or top-level).
            if "action_type" in action_section or "source" in action_section:
                action_section["type"] = "stat_block_section"
                action_section["subtype"] = "skill_action"
                if trained is not None:
                    action_section["trained"] = trained
                actions.append(action_section)
                last_action = action_section
            else:
                # Not a real action — clean up any action-specific fields
                # that may have been extracted from its text
                _strip_action_fields(action_section)
                action_section["type"] = "section"
                action_section.pop("subtype", None)
                if last_action is not None:
                    # Attach as a subsection of the preceding action
                    last_action.setdefault("sections", []).append(action_section)
                else:
                    # No preceding action — keep as top-level section
                    remaining_sections.append(action_section)
    struct["sections"] = remaining_sections
    if actions:
        skill["actions"] = actions


_ACTION_ONLY_FIELDS = [
    "action_type",
    "traits",
    "source",
    "trained",
    "requirement",
    "trigger",
    "frequency",
    "cost",
    "effect",
    "duration",
    "critical_success",
    "success",
    "failure",
    "critical_failure",
    "sample_tasks",
]


def _strip_action_fields(section):
    """Remove action-specific fields from a section being reclassified."""
    for field in _ACTION_ONLY_FIELDS:
        section.pop(field, None)


_PROFICIENCY_LEVELS = ["untrained", "trained", "expert", "master", "legendary"]


def _extract_sample_tasks(section):
    """Extract Sample Tasks section into structured sample_tasks array."""
    remaining = []
    for sub in section.get("sections", []):
        if "Sample" not in sub.get("name", "") or "Tasks" not in sub.get("name", ""):
            remaining.append(sub)
            continue
        text = sub.get("text", "")
        bs = BeautifulSoup(text, "html.parser")
        sample_tasks = []
        current_level = None
        for node in bs.children:
            if getattr(node, "name", None) == "b":
                label = get_text(node).strip().lower()
                if label in _PROFICIENCY_LEVELS:
                    current_level = label
            elif getattr(node, "name", None) == "br":
                continue
            elif isinstance(node, str) and current_level:
                for task_name in node.split(","):
                    task_name = task_name.strip()
                    if task_name:
                        task = build_object("stat_block_section", "sample_task", task_name)
                        task["proficiency"] = current_level
                        sample_tasks.append(task)
        if sample_tasks:
            section["sample_tasks"] = sample_tasks
    section["sections"] = remaining


def _extract_action_type_from_name(section):
    """Extract action type span from section name before links are stripped."""
    name = section.get("name", "")
    bs = BeautifulSoup(name, "html.parser")
    action_span = bs.find("span", {"class": "action"})
    if action_span:
        title = action_span.get("title", "")
        assert title in _ACTION_TITLE_MAP, f"Unknown action title: {title}"
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
    source = extract_source_from_bs(bs)
    if source:
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
        if label not in ("Requirements", "Requirement", "Trigger", "Frequency", "Cost", "Duration"):
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
        if key == "requirements":
            key = "requirement"
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
        source = extract_source_from_bs(bs)
        if not source:
            return None
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
    "text",
    "requirement",
    "trigger",
    "frequency",
    "cost",
    "effect",
    "critical_success",
    "success",
    "failure",
    "critical_failure",
]


def skill_link_pass(struct):
    def _handle_text_field(section, field, keep=True):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs, unwrap=True)
        if len(links) > 0 and keep:
            linklist = section.setdefault("links", [])
            linklist.extend(links)
        # Strip action spans from names
        for span in bs.find_all("span", {"class": "action"}):
            span.decompose()
        # Strip letter-spacing spans (trait separators)
        for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
            span.decompose()
        section[field] = str(bs).strip()

    def _process_section(section):
        # Keep links from names for plain sections, discard for actions
        keep_name_links = section.get("type") == "section"
        _handle_text_field(section, "name", keep_name_links)
        for field in _LINK_FIELDS:
            _handle_text_field(section, field)
        for s in section.get("sections", []):
            _process_section(s)

    for section in struct["sections"]:
        _process_section(section)

    # Process skill actions
    skill = find_skill(struct)
    assert skill is not None, f"No skill section found in {struct.get('name', 'unknown')}"
    for action in skill.get("actions", []):
        _process_section(action)


def _convert_skill_text(skill):
    """Convert skill text HTML to markdown, keeping it in the skill object."""
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
    cleaned = str(soup).strip()
    if cleaned:
        skill["text"] = md(cleaned)
    else:
        del skill["text"]


def _promote_skill_fields(struct, skill):
    """Move only envelope fields from skill object to top-level struct."""
    struct["name"] = skill["name"]
    struct["sources"] = skill["sources"]
    del skill["sources"]

    if "sections" in skill:
        del skill["sections"]


def _clean_html_fields(struct):
    """Rename 'html' keys to 'text' in sections recursively."""
    for section in struct.get("sections", []):
        if "html" in section:
            section["text"] = section["html"]
            del section["html"]
        if "sections" in section:
            _clean_html_fields(section)


def skill_cleanup_pass(struct):
    assert "skill" in struct, f"No skill object found in struct: {struct.get('name')}"
    skill = struct["skill"]

    _convert_skill_text(skill)
    _promote_skill_fields(struct, skill)
    _clean_html_fields(struct)

    # Verify skill object is clean
    expected_keys = {
        "type",
        "subtype",
        "name",
        "actions",
        "skill_type",
        "key_ability",
        "key_kingdom_ability",
        "text",
        "links",
    }
    remaining = set(skill.keys()) - expected_keys
    assert not remaining, f"Unexpected keys in skill: {remaining}"


def write_skill(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_skill_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_skill_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
