import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString

from pfsrd2.license import license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql import get_db_connection, get_db_path
from pfsrd2.sql.sources import fetch_source_by_name
from pfsrd2.sql.traits import trait_db_pass
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
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
from universal.utils import get_text


def parse_spell(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        max_title=1,
        cssclass="main",
        pre_filters=[_content_filter, _sidebar_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    struct = restructure_spell_pass(details)
    spell_struct_pass(struct)
    # Promote sources to top level early (needed by game_id_pass)
    spell = find_spell(struct)
    struct["sources"] = spell.get("sources", [])
    source_pass(struct, find_spell)
    spell_structurize_pass(struct)
    spell_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, "spell", find_spell)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    spell_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    trait_db_pass(struct)
    license_pass(struct)
    _strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "", fxn_valid_tags=_spell_valid_tags)
    _remove_empty_fields(struct)
    if not options.skip_schema:
        struct["schema_version"] = 2.0
        validate_against_schema(struct, "spell.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_spell(jsondir, struct, name)
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
    for a in main.find_all("a"):
        if not a.string and not a.contents:
            a.decompose()
    # Move action spans and rank badge spans out of h1.title into the body.
    # Some spells have "Name [action] Spell 5" all inside the h1; parse_universal
    # chokes on multiple subtitle spans. Move them after the h1 so the title
    # is just the name and they end up in the text for later extraction.
    h1 = main.find("h1", class_="title")
    if h1:
        for span in list(h1.find_all("span")):
            cls = span.get("class", [])
            style = span.get("style", "")
            if "action" in cls or "margin-left:auto" in style:
                h1.insert_after(span)
        # Clean up text nodes left behind after moving spans out of h1.
        # Multi-action spells leave "or", "to", "or more" as orphaned text.
        for node in list(h1.children):
            if isinstance(node, NavigableString):
                cleaned = re.sub(r"\s+(or more|or|to)\s*$", "", str(node))
                if cleaned != str(node):
                    node.replace_with(NavigableString(cleaned))


def _sidebar_filter(soup):
    """Remove sidebar divs (remastered/legacy version links)."""
    for div in soup.find_all("div", {"class": "siderbarlook"}):
        div.decompose()
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


def restructure_spell_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    top = {"name": sb["name"], "type": "spell", "sections": [sb]}
    sb["type"] = "stat_block_section"
    sb["subtype"] = "spell"

    # The rank badge (e.g. "Spell 5", "Focus 1", "Cantrip 1") appears as a
    # subsection from parse_universal. Extract it into the stat block directly.
    remaining_sections = []
    for section in sb["sections"]:
        name = section.get("name", "")
        match = _RANK_BADGE_RE.match(name)
        if match and not section.get("text") and not section.get("sections"):
            sb["spell_type"] = match.group(1).lower()
            sb["rank"] = int(match.group(2))
        else:
            remaining_sections.append(section)
    sb["sections"] = []

    top["sections"].extend(rest)
    top["sections"].extend(remaining_sections)
    return top


_RANK_BADGE_RE = re.compile(r"^(Spell|Cantrip|Focus)\s+(\d+)$")


def find_spell(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "spell":
            return section


def _extract_source_from_bs(bs):
    """Extract source from a BeautifulSoup object, modifying it in place."""

    def _strip_whitespace(nodes):
        while nodes and isinstance(nodes[0], str) and not nodes[0].strip():
            nodes[0].extract()
            nodes.pop(0)

    source_tag = bs.find("b", string=lambda s: s and s.strip() == "Source")
    if not source_tag:
        return None
    siblings = list(source_tag.next_siblings)
    source_tag.decompose()
    _strip_whitespace(siblings)
    if not siblings or getattr(siblings[0], "name", None) not in ("a", "i"):
        return None
    book = siblings.pop(0)
    source = extract_source(book)
    book.decompose()
    _strip_whitespace(siblings)
    if siblings and getattr(siblings[0], "name", None) == "sup":
        assert "errata" not in source, "Should be no more than one errata."
        sup = siblings.pop(0)
        _, source["errata"] = extract_link(sup.find("a"))
        sup.decompose()
    if siblings and getattr(siblings[0], "name", None) == "br":
        siblings[0].decompose()
    return source


# Bold labels that appear in the spell stat block header area.
# These are extracted as structured fields.
_SPELL_STAT_LABELS = {
    "Traditions",
    "Spell List",
    "Bloodline",
    "Bloodlines",
    "Cast",
    "Range",
    "Targets",
    "Duration",
    "Area",
    "Saving Throw",
    "Defense",
    "Trigger",
    "Requirements",
    "Effect",
    "Access",
    "Catalysts",
    "Mystery",
    "Mysteries",
    "Domain",
    "Domains",
    "Patron Theme",
    "Lesson",
    "Deity",
    "Deities",
    "Amp",
    "PFS Note",
    "Cost",
}

_RESULT_LABELS = {
    "Critical Success": "critical_success",
    "Critical Failure": "critical_failure",
    "Success": "success",
    "Failure": "failure",
}

_HEIGHTENED_RE = re.compile(r"^Heightened\b")
_AMP_HEIGHTENED_RE = re.compile(r"^Amp Heightened\b")


def spell_struct_pass(struct):
    """Extract structured fields from the spell stat block text."""
    spell = find_spell(struct)
    assert spell is not None, f"No spell section found in {struct.get('name', 'unknown')}"
    if "text" not in spell:
        return
    bs = BeautifulSoup(spell["text"], "html.parser")

    # Extract spell name from the beginning of text
    # Text starts with "Abyssal Plague  [action-span]" before the h3/traits
    _extract_spell_name(bs, spell, struct)

    # Extract traits
    _extract_traits(bs, spell)

    # Extract Legacy Content marker
    _extract_legacy_marker(bs, struct)

    # Extract source
    source = _extract_source_from_bs(bs)
    if source:
        spell["sources"] = [source]
    else:
        spell["sources"] = []

    # Split on <hr> — pre-hr is stats, post-hr is description + heightened
    hr = bs.find("hr")
    if hr:
        pre_hr_parts = []
        for sibling in list(hr.previous_siblings):
            pre_hr_parts.insert(0, str(sibling))
            sibling.extract()
        hr.decompose()
        pre_hr_text = "".join(pre_hr_parts).strip()
        _extract_stat_fields(spell, pre_hr_text)

    # Extract heightened from after the second <hr> BEFORE result blocks,
    # so result block extraction doesn't consume heightened text.
    hr2 = bs.find("hr")
    if hr2:
        post_hr_parts = []
        for sibling in list(hr2.next_siblings):
            post_hr_parts.append(str(sibling))
            sibling.extract()
        hr2.decompose()
        heightened_text = "".join(post_hr_parts).strip()
        _extract_heightened(spell, heightened_text)

    # Extract result blocks from remaining body
    _extract_result_blocks(spell, bs)

    # Extract deity form entries from <ul><li><b><a href="Deities...">
    _extract_deity_forms(spell, bs)

    # Clean remaining text as description
    # Remove empty <ul> tags (AoN artifacts)
    for ul in bs.find_all("ul"):
        if not ul.get_text(strip=True):
            ul.decompose()
    text = str(bs).strip()
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    spell["text"] = text.strip()



def _clean_spell_name(name):
    """Strip trailing conjunctions and extra whitespace from spell names."""
    name = re.sub(r"\s+(or more|or|to)\s*$", "", name)
    # Collapse multiple spaces
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip()


def _extract_spell_name(bs, spell, struct):
    """Extract the spell name and optional action type from the start of text.

    Two cases:
    1. PFS-link spells: h1 has PFS link, name is leading text in body
    2. Direct-name spells: h1 has the spell name, text starts with action span
    """
    # Extract action type(s) from spans before removing them.
    # Some spells have "Two Actions or Three Actions" — extract all.
    action_spans = bs.find_all("span", {"class": "action"})
    if action_spans:
        title = action_spans[0].get("title", "")
        if title in _ACTION_TITLE_MAP:
            spell["action_type"] = build_object(
                "stat_block_section", "action_type", _ACTION_TITLE_MAP[title]
            )
        for span in action_spans:
            span.decompose()

    # Try to extract name from leading text nodes
    name_parts = []
    for node in list(bs.children):
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                name_parts.append(text)
                node.extract()
            else:
                node.extract()
        else:
            break
    name = " ".join(name_parts).strip()
    name = _clean_spell_name(name)
    if name:
        spell["name"] = name
        struct["name"] = name
    else:
        # Name already set from h1 title by parse_universal — use it as-is
        # Clean any HTML from the name
        name_bs = BeautifulSoup(spell["name"], "html.parser")
        clean_name = _clean_spell_name(get_text(name_bs).strip())
        if clean_name:
            spell["name"] = clean_name
            struct["name"] = clean_name


_ACTION_TITLE_MAP = {
    "Single Action": "One Action",
    "Two Actions": "Two Actions",
    "Three Actions": "Three Actions",
    "Reaction": "Reaction",
    "Free Action": "Free Action",
}


def _extract_traits(bs, spell):
    """Extract trait spans from the stat block."""
    traits = []
    for span in bs.find_all("span", class_=lambda c: c and "trait" in c):
        a = span.find("a")
        if a:
            name, trait_link = extract_link(a)
            traits.append(
                build_object("stat_block_section", "trait", name.strip(), {"link": trait_link})
            )
        span.decompose()
    # Also remove letter-spacing separator spans
    for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
        span.decompose()
    if traits:
        spell["traits"] = traits


def _extract_legacy_marker(bs, struct):
    """Extract Legacy Content h3 marker into a section for edition detection."""
    h3 = bs.find("h3", string=lambda s: s and "Legacy Content" in s)
    if h3:
        struct["sections"].append({
            "type": "section",
            "name": "Legacy Content",
            "sections": [],
        })
        h3.decompose()


def _extract_stat_fields(spell, text):
    """Extract bold-labeled fields from the pre-hr stat area."""
    bs = BeautifulSoup(text, "html.parser")
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if label == "Source":
            # Already handled
            continue
        if label not in _SPELL_STAT_LABELS:
            # Skip unknown labels (deity names etc. handled later)
            continue
        # Collect everything until next <b> or <br>
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                break
            if getattr(node, "name", None) == "br":
                node = node.next_sibling
                break
            parts.append(str(node))
            node = node.next_sibling
        value = "".join(parts).strip()
        if value.endswith(";"):
            value = value[:-1].strip()
        key = _label_to_key(label)
        spell[key] = value


def _label_to_key(label):
    """Convert a display label to a snake_case key."""
    mapping = {
        "Traditions": "traditions",
        "Spell List": "spell_list",
        "Bloodline": "bloodline",
        "Bloodlines": "bloodline",
        "Cast": "cast",
        "Range": "range",
        "Targets": "targets",
        "Duration": "duration",
        "Area": "area",
        "Saving Throw": "saving_throw",
        "Defense": "defense",
        "Trigger": "trigger",
        "Requirements": "requirement",
        "Effect": "effect",
        "Access": "access",
        "Catalysts": "catalysts",
        "Mystery": "mystery",
        "Mysteries": "mystery",
        "Domain": "domain",
        "Domains": "domain",
        "Patron Theme": "patron_theme",
        "Lesson": "lesson",
        "Deity": "deity",
        "Deities": "deity",
        "Amp": "amp",
        "PFS Note": "pfs_note",
        "Cost": "cost",
    }
    assert label in mapping, f"No key mapping for label: {label!r}"
    return mapping[label]


def _extract_result_blocks(spell, bs):
    """Extract Critical Success/Success/Failure/Critical Failure from description."""
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if label not in _RESULT_LABELS:
            continue
        key = _RESULT_LABELS[label]
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                next_label = get_text(node).strip()
                if next_label in _RESULT_LABELS:
                    break
            parts.append(str(node))
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        spell[key] = value
        # Remove from soup
        for node in list(bold.next_siblings):
            if getattr(node, "name", None) == "b" and get_text(node).strip() in _RESULT_LABELS:
                break
            node.extract()
        bold.decompose()


def _extract_deity_forms(spell, bs):
    """Extract deity-specific battle form entries from <ul><li> blocks.

    Avatar and similar spells list deity-specific forms as <li> items
    with a bold deity link: <li><b><a href="Deities.aspx?ID=...">Name</a></b> stats...</li>
    """
    forms = []
    for ul in list(bs.find_all("ul")):
        ul_forms = []
        for li in ul.find_all("li"):
            b = li.find("b", recursive=False)
            if not b:
                continue
            a = b.find("a", attrs={"game-obj": "Deities"})
            if not a:
                # Also check for pre-href_filter links
                a = b.find("a", href=lambda h: h and "Deities" in h)
            if not a:
                continue
            name, link = extract_link(a)
            name = name.strip()
            # Remove the bold deity tag from the li text
            b.decompose()
            text = str(li)
            # Strip li tags and leading/trailing whitespace
            text = re.sub(r"^<li>\s*", "", text)
            text = re.sub(r"\s*</li>$", "", text)
            text = text.strip()
            form = build_object(
                "stat_block_section", "deity_form", name,
                {"link": link, "text": text}
            )
            ul_forms.append(form)
        if ul_forms:
            forms.extend(ul_forms)
            ul.decompose()
    if forms:
        spell["deity_forms"] = forms


def _extract_heightened(spell, text):
    """Extract heightened entries into a structured array."""
    bs = BeautifulSoup(text, "html.parser")
    heightened = []
    for bold in bs.find_all("b"):
        label = get_text(bold).strip()
        if not (_HEIGHTENED_RE.match(label) or _AMP_HEIGHTENED_RE.match(label)):
            continue
        # Parse the level/increment from the label
        entry = _parse_heightened_label(label)
        # Collect text until next <b> that's a heightened label
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                next_label = get_text(node).strip()
                if _HEIGHTENED_RE.match(next_label) or _AMP_HEIGHTENED_RE.match(next_label):
                    break
            parts.append(str(node))
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"^(<br/?>[\s]*)+", "", value)
        value = re.sub(r"(<br/?>[\s]*)+$", "", value)
        entry["text"] = value
        heightened.append(entry)
    if heightened:
        spell["heightened"] = heightened


def _parse_heightened_label(label):
    """Parse 'Heightened (+1)', 'Heightened (4th)', 'Amp Heightened (+2)' etc."""
    entry = {
        "type": "stat_block_section",
        "subtype": "heightened",
    }
    if label.startswith("Amp"):
        entry["amp"] = True
    # Extract the parenthetical
    match = re.search(r"\(([^)]+)\)", label)
    assert match, f"Heightened label without parenthetical: {label!r}"
    inner = match.group(1).strip()
    if inner.startswith("+"):
        entry["increment"] = int(inner[1:])
    else:
        # "4th", "9th", "10th" -> extract number
        level_match = re.match(r"(\d+)", inner)
        assert level_match, f"Can't parse heightened level: {inner!r}"
        entry["level"] = int(level_match.group(1))
    return entry


_ACCESS_FIELDS = {
    "traditions": "tradition",
    "spell_list": "spell_list",
    "bloodline": "bloodline",
    "deity": "deity",
    "domain": "domain",
    "mystery": "mystery",
    "lesson": "lesson",
    "patron_theme": "patron_theme",
}


def spell_structurize_pass(struct):
    """Convert flat string fields into structured objects.

    Runs BEFORE spell_link_pass — fields still contain HTML with <a> tags.
    Builds: spell_access, spell_cast, spell_defense.
    """
    spell = find_spell(struct)
    assert spell is not None, f"No spell found in {struct.get('name')}"
    _build_spell_access(spell)
    _build_spell_cast(spell)
    _build_spell_defense(spell)


def _build_spell_access(spell):
    """Build spell_access array from access field HTML strings."""
    access = []
    for field, access_type in _ACCESS_FIELDS.items():
        if field not in spell:
            continue
        value = spell[field]
        if value == "N/A":
            del spell[field]
            continue
        bs = BeautifulSoup(value, "html.parser")
        # Extract linked entries
        for a in list(bs.find_all("a")):
            name = get_text(a).strip()
            if not name:
                continue
            _, link = extract_link(a)
            obj = build_object(
                "stat_block_section", "spell_access", name,
                {"access_type": access_type, "link": link},
            )
            access.append(obj)
            parent = a.parent
            if parent and parent.name == "u":
                parent.decompose()
            else:
                a.decompose()
        # Check for remaining unlinked entries
        remaining = get_text(bs).strip()
        if remaining:
            for part in remaining.split(","):
                name = part.strip()
                if name:
                    obj = build_object(
                        "stat_block_section", "spell_access", name,
                        {"access_type": access_type},
                    )
                    access.append(obj)
        del spell[field]
    if access:
        spell["spell_access"] = access


def _build_spell_cast(spell):
    """Build spell_cast object from cast HTML string + action_type."""
    cast_html = spell.pop("cast", None)
    action_type = spell.pop("action_type", None)

    if not cast_html and not action_type:
        return

    cast_obj = {
        "type": "stat_block_section",
        "subtype": "spell_cast",
    }

    if action_type:
        cast_obj["action_type"] = action_type

    if cast_html:
        bs = BeautifulSoup(cast_html, "html.parser")
        # Strip action spans (already extracted as action_type)
        for span in bs.find_all("span", {"class": "action"}):
            span.decompose()
        for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
            span.decompose()

        # Extract component objects from <a> tags
        components = []
        for a in list(bs.find_all("a")):
            comp_name = get_text(a).strip()
            if comp_name:
                _, comp_link = extract_link(a)
                comp = build_object(
                    "stat_block_section", "spell_cast_component", comp_name,
                    {"link": comp_link},
                )
                components.append(comp)
                parent = a.parent
                if parent and parent.name == "u":
                    parent.decompose()
                else:
                    a.decompose()

        # Get remaining text (time, artifacts, etc.)
        text = get_text(bs).strip()
        text = re.sub(r"^\s*(to|or|more)\s+", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        # Remove empty parenthetical left from extracted components
        text = re.sub(r"\s*\([,\s]*\)\s*", "", text).strip()
        text = text.strip(", ")

        if text:
            if re.match(r"\d", text):
                # Timed cast: "1 minute", "10 minutes", etc.
                cast_obj["time"] = text
            elif text.startswith("*"):
                # Nethys notes: "*(none printed)*", etc.
                cast_obj["note"] = text
            elif not components:
                # Plain text components (no links)
                for part in text.split(","):
                    name = part.strip()
                    if name:
                        comp = build_object(
                            "stat_block_section", "spell_cast_component", name,
                        )
                        components.append(comp)

        if components:
            cast_obj["components"] = components

    spell["cast"] = cast_obj


def _build_spell_defense(spell):
    """Build spell_defense object from saving_throw/defense + result blocks."""
    save_html = None
    if "defense" in spell:
        save_html = spell.pop("defense")
    elif "saving_throw" in spell:
        save_html = spell.pop("saving_throw")

    result_keys = ["critical_success", "success", "failure", "critical_failure"]
    has_results = any(k in spell for k in result_keys)

    if not save_html and not has_results:
        return

    defense = {
        "type": "stat_block_section",
        "subtype": "spell_defense",
    }

    if save_html:
        bs = BeautifulSoup(save_html, "html.parser")
        # Extract "basic" link if present
        for a in list(bs.find_all("a")):
            name = get_text(a).strip()
            if name.lower() == "basic":
                _, basic_link = extract_link(a)
                defense.setdefault("links", []).append(basic_link)
                parent = a.parent
                if parent and parent.name == "u":
                    parent.decompose()
                else:
                    a.decompose()
        clean_text = get_text(bs).strip()
        basic = clean_text.lower().startswith("basic") or "links" in defense
        if basic:
            defense["basic"] = True
            save_name = re.sub(r"^basic\s*", "", clean_text, flags=re.IGNORECASE).strip()
        else:
            save_name = clean_text

        _SAVE_TYPES = {
            "fortitude": "Fort",
            "reflex": "Ref",
            "will": "Will",
        }
        save_lower = save_name.lower()
        if save_lower in _SAVE_TYPES:
            defense["save_type"] = _SAVE_TYPES[save_lower]
        elif save_name:
            defense["text"] = save_name

    # Move result blocks into defense (still HTML, processed by link_pass later)
    for key in result_keys:
        if key in spell:
            defense[key] = spell.pop(key)

    spell["defense"] = defense


def spell_link_pass(struct):
    """Extract links from all text fields and unwrap <a> tags."""
    # Fields that still need link extraction. Access fields, cast, defense,
    # and result blocks are handled by spell_structurize_pass.
    _LINK_FIELDS = [
        "text",
        "requirement",
        "trigger",
        "effect",
        "catalysts",
        "access",
        "amp",
        "pfs_note",
        "range",
        "targets",
        "duration",
        "area",
        "cost",
    ]

    def _handle_text_field(section, field):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs, unwrap=True)
        if links:
            linklist = section.setdefault("links", [])
            linklist.extend(links)
        # Strip action spans
        for span in bs.find_all("span", {"class": "action"}):
            span.decompose()
        # Strip letter-spacing spans
        for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
            span.decompose()
        section[field] = str(bs).strip()

    def _process_section(section):
        _handle_text_field(section, "name")
        for field in _LINK_FIELDS:
            _handle_text_field(section, field)
        # Process defense result block fields
        defense = section.get("defense")
        if defense and isinstance(defense, dict):
            for field in ("critical_success", "success", "failure", "critical_failure"):
                _handle_text_field(defense, field)
        # Process heightened entries
        for h in section.get("heightened", []):
            _handle_text_field(h, "text")
        # Process deity form entries
        for df in section.get("deity_forms", []):
            _handle_text_field(df, "text")
        for s in section.get("sections", []):
            _process_section(s)

    for section in struct["sections"]:
        _process_section(section)


def spell_cleanup_pass(struct):
    """Clean up spell object after restructuring."""
    assert "spell" in struct, f"No spell object found in struct: {struct.get('name')}"
    spell = struct["spell"]

    # Promote name to top level
    struct["name"] = spell["name"]

    # Promote sources to top level (needed for file output and game_id)
    if "sources" in spell:
        struct["sources"] = spell["sources"]
        del spell["sources"]

    # Clean up empty sections
    if "sections" in spell:
        del spell["sections"]


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


def _strip_block_tags(struct):
    """Pre-strip <p>, <div>, <u>, <h2>, <h3>, <nethys-search> tags before markdown validation."""
    for k, v in struct.items():
        if isinstance(v, dict):
            _strip_block_tags(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _strip_block_tags(item)
        elif isinstance(v, str) and ("<" in v):
            bs = BeautifulSoup(v, "html.parser")
            changed = False
            for div in bs.find_all("div"):
                changed = True
                if not div.get_text(strip=True):
                    div.decompose()
                else:
                    div.unwrap()
            for p in bs.find_all("p"):
                changed = True
                p.unwrap()
            for u in bs.find_all("u"):
                changed = True
                u.unwrap()
            for h in bs.find_all(["h2", "h3"]):
                changed = True
                h.unwrap()
            for ns in bs.find_all("nethys-search"):
                changed = True
                ns.decompose()
            for span in bs.find_all("span", style=lambda s: s and "margin-left:auto" in s):
                changed = True
                span.decompose()
            # Strip corrupted HTML tags (e.g. <spells%6%%>, <action.types#2%%>)
            for tag in bs.find_all(True):
                if "%" in tag.name or "#" in tag.name:
                    changed = True
                    tag.unwrap()
            if changed:
                struct[k] = str(bs)


def _spell_valid_tags(struct, name, path, validset):
    """Add spell-specific tags to the markdown valid set.

    Battle form spells (Avatar, Aberrant Form, etc.) have inline stat blocks
    with <b> for labels, <i> for spell names, and <span> for action icons.
    """
    validset.update({"b", "i", "span"})


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    return isinstance(value, list | dict) and len(value) == 0


def _remove_empty_fields(obj):
    """Recursively remove fields with empty values ("", None, [], {})."""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            value = obj[key]
            _remove_empty_fields(value)
            if _is_empty(value):
                del obj[key]
    elif isinstance(obj, list):
        for item in obj:
            _remove_empty_fields(item)
        obj[:] = [item for item in obj if not _is_empty(item)]


def write_spell(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_spell_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_spell_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
