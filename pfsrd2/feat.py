import glob
import json
import os
import re
import sys

from bs4 import BeautifulSoup

from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.traits import trait_db_pass
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.markdown import md
from universal.universal import (
    aon_pass,
    build_object,
    edition_from_alternate_link,
    edition_pass,
    entity_pass,
    extract_link,
    extract_source,
    game_id_pass,
    get_links,
    handle_alternate_link,
    parse_universal,
    remove_empty_sections_pass,
    restructure_pass,
    source_pass,
)
from universal.utils import content_filter, get_text, remove_empty_fields, strip_block_tags


def parse_feat(filename, options):
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
    alternate_link = handle_alternate_link(details, allow_multiple=True)
    struct = restructure_feat_pass(details)
    if alternate_link:
        if isinstance(alternate_link, list):
            struct["alternate_link"] = alternate_link[0]
            if len(alternate_link) > 1:
                struct["alternate_links"] = alternate_link
        else:
            struct["alternate_link"] = alternate_link
    feat_extract_pass(struct)
    _detect_archetype_level(struct, filename)
    _extract_called_actions(struct)
    source_pass(struct, find_feat)
    feat_link_pass(struct)
    # Normalize ArchLevel variants: Feats.aspx.ID_4803.ArchLevel_8 -> Feats.aspx.ID_4803
    aon_basename = re.sub(r"\.ArchLevel_\d+", "", basename)
    aon_pass(struct, aon_basename)
    restructure_pass(struct, "feat", find_feat)
    struct["edition"] = edition_from_alternate_link(struct) or edition_pass(struct["sections"])
    struct["sections"] = [
        s for s in struct["sections"]
        if s.get("name") not in ("Legacy Content", "Traits")
    ]
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    feat_cleanup_pass(struct)
    trait_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "")
    remove_empty_fields(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "feat.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, struct["game-obj"], name)
            write_feat(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def _content_filter(soup):
    content_filter(soup)
    # Move action and level spans out of h1 titles
    # Some feats have both [action] and "Feat N" spans inside h1
    main = soup.find(id="main")
    if not main:
        return
    for h1 in main.find_all("h1", class_="title"):
        spans_to_move = []
        for span in h1.find_all("span"):
            if "action" in span.get("class", []):
                spans_to_move.append(span)
            elif "margin-left" in (span.get("style") or ""):
                spans_to_move.append(span)
        for span in spans_to_move:
            span.extract()
            h1.insert_after(span)


def _sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. siderbarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


def restructure_feat_pass(details):
    """Build feat structure from parse_universal output.

    parse_universal produces:
      detail[0]:
        name: PFS link (garbage)
        text: '<a game-obj="Feats">Feat Name</a> [action span]'
        sections: varied structure depending on legacy/remastered/spoiler presence
    """
    assert len(details) > 0, "No details from parse_universal"
    first = details[0]
    rest = details[1:]

    # Extract feat name and action span
    # The feat name link can be in first.text (standard) or first.name (wrapped-span)
    feat_name = ""
    action_text = ""
    for field in ("text", "name"):
        field_val = first.get(field, "") or ""
        bs = BeautifulSoup(field_val, "html.parser")
        name_link = bs.find("a", attrs={"game-obj": "Feats"})
        if name_link:
            feat_name = get_text(name_link).strip()
            action_text = str(bs)
            break
    assert feat_name, f"Could not extract feat name from sections: {[s.get('name') for s in first.get('sections', [])]}"

    # Scan all sections recursively to find feat level and content
    feat_level = None
    content_text = None
    is_legacy = False
    extra_sections = []

    feat_section_text = None  # Non-content text from "Feat N" section (e.g., action span)

    def _scan_sections(sections):
        """Scan sections to find feat level, content text, and legacy marker.

        Returns True if content was found within these sections (so the caller
        knows not to add the parent section to extras).
        """
        nonlocal feat_level, content_text, is_legacy, feat_section_text
        found_content = False
        for section in sections:
            name = section.get("name", "")
            match = re.match(r"Feat\s+(\d+)", name)
            if match:
                feat_level = int(match.group(1))
                if "text" in section and content_text is None:
                    # Only treat as content if it has Source tag (real content)
                    if "Source" in section["text"]:
                        content_text = section["text"]
                        found_content = True
                    else:
                        # Store non-content text (action span etc.) for later
                        feat_section_text = section["text"]
                if _scan_sections(section.get("sections", [])):
                    found_content = True
            elif name == "Legacy Content":
                is_legacy = True
                if "text" in section and content_text is None:
                    content_text = section["text"]
                    found_content = True
                if _scan_sections(section.get("sections", [])):
                    found_content = True
            else:
                # Scan subsections first (content may be nested under spoiler etc.)
                child_found = _scan_sections(section.get("sections", []))
                if child_found:
                    found_content = True
                elif content_text is None and "Source" in section.get("text", ""):
                    # This section IS the content
                    content_text = section["text"]
                    found_content = True
                else:
                    extra_sections.append(section)
        return found_content

    _scan_sections(first.get("sections", []))

    # Fallback: if no content found in sections, the content is in first's text
    # This happens when parse_universal wraps everything in a single section
    # (e.g., when the h1 span wraps all content)
    if content_text is None and "Source" in first.get("text", ""):
        content_text = first["text"]
        # Name is directly in the name field, not in text
        name_bs = BeautifulSoup(first.get("name", ""), "html.parser")
        name_link2 = name_bs.find("a", attrs={"game-obj": "Feats"})
        if name_link2:
            feat_name = get_text(name_link2).strip()
        action_text = first.get("name", "")
        # Level may be in subname
        subname = first.get("subname", "")
        level_match = re.match(r"Feat\s+(\d+)", subname)
        if level_match and feat_level is None:
            feat_level = int(level_match.group(1))

    # Build the stat block
    sb = {
        "name": feat_name,
        "type": "stat_block_section",
        "subtype": "feat",
        "sections": [],
    }
    if content_text:
        sb["text"] = content_text
    if feat_level is not None:
        sb["level"] = feat_level
    # Combine all sources of action span HTML for extraction
    # action_text comes from first.text, feat_section_text from "Feat N" section
    sb["_name_html"] = action_text + (" " + feat_section_text if feat_section_text else "")

    top = {"name": feat_name, "type": "feat", "sections": [sb]}
    if is_legacy:
        top["sections"].append(
            {"name": "Legacy Content", "type": "section", "sections": []}
        )
    top["sections"].extend(extra_sections)
    top["sections"].extend(rest)

    return top


def find_feat(struct):
    for section in struct["sections"]:
        if section.get("subtype") == "feat":
            return section


_ACTION_TITLE_MAP = {
    "Single Action": "One Action",
    "Two Actions": "Two Actions",
    "Three Actions": "Three Actions",
    "Reaction": "Reaction",
    "Free Action": "Free Action",
}


def feat_extract_pass(struct):
    """Extract structured fields from the feat stat block text."""
    feat = find_feat(struct)
    assert feat is not None, f"No feat section found in {struct.get('name', 'unknown')}"

    # Extract action type from the name HTML
    _extract_action_type(feat)

    if "text" not in feat:
        return

    bs = BeautifulSoup(feat["text"], "html.parser")

    # 1. Extract trait spans (includes traituncommon, traitrare, traitunique, traitalignment)
    traits = []
    for span in bs.find_all("span", class_=lambda c: c and c.startswith("trait")):
        a = span.find("a")
        if a:
            name, trait_link = extract_link(a)
            trait_obj = build_object("stat_block_section", "trait", name.strip(), {"link": trait_link})
            # Split valued traits like "Additive 1" into name="Additive" + value="1"
            value_match = re.match(r"^(.+?)\s+(\d+)$", trait_obj["name"])
            if value_match:
                trait_obj["name"] = value_match.group(1)
                trait_obj["value"] = value_match.group(2)
            traits.append(trait_obj)
        span.decompose()
    if traits:
        feat["traits"] = traits

    # 2. Strip letter-spacing spans (trait separators)
    for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
        span.decompose()

    # 3. Extract source(s)
    sources = []
    while True:
        source = _extract_source_from_bs(bs)
        if source:
            sources.append(source)
        else:
            break
    assert sources, f"No sources found for feat {feat.get('name', 'unknown')}"
    feat["sources"] = sources

    # 4. Split on <hr> — pre-hr is stats, post-hr is description
    hr = bs.find("hr")
    if hr:
        pre_hr_parts = []
        for sibling in list(hr.previous_siblings):
            pre_hr_parts.insert(0, str(sibling))
            sibling.extract()
        hr.decompose()
        pre_hr_text = "".join(pre_hr_parts).strip()
        _extract_bold_fields(feat, pre_hr_text)

    # 5. Extract calledAction divs from post-hr text before bold field extraction
    # (prevents calledAction content from being absorbed into bold fields)
    for div in list(bs.find_all("div", {"class": "calledAction"})):
        action = _parse_called_action(div)
        div.extract()
        feat.setdefault("abilities", []).append(action)

    # 6. Extract trailing h2 sections ("Leads To...", "Traits") and trait-entry
    # divs that are sometimes trapped in the feat text instead of being split
    # into separate sections by parse_universal
    _extract_trailing_sections(struct, bs)

    # 7. Extract result blocks from remaining text
    _extract_result_blocks(feat, bs)

    # 8. Extract bold fields from post-hr text (Special, Trigger, Requirement
    # can appear in the description after the <hr> divider)
    _extract_bold_fields_from_bs(feat, bs)

    # 9. Clean remaining text
    text = str(bs).strip()
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    feat["text"] = text.strip()


def _detect_archetype_level(struct, filename):
    """If an ArchLevel variant file exists, set archetype_level on the feat."""
    pattern = filename + ".ArchLevel_*"
    matches = glob.glob(pattern)
    if not matches:
        return
    # Extract the level number from the first match
    m = re.search(r"\.ArchLevel_(\d+)$", matches[0])
    if m:
        feat = find_feat(struct)
        feat["archetype_level"] = int(m.group(1))


def _extract_action_type(feat):
    """Extract action type from the stored name HTML."""
    name_html = feat.pop("_name_html", "")
    if not name_html:
        return
    bs = BeautifulSoup(name_html, "html.parser")
    action_span = bs.find("span", {"class": "action"})
    if action_span:
        title = action_span.get("title", "")
        assert title in _ACTION_TITLE_MAP, f"Unknown action title: {title}"
        feat["action_type"] = build_object(
            "stat_block_section", "action_type", _ACTION_TITLE_MAP[title]
        )


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
    _strip_whitespace(siblings)
    if not siblings or getattr(siblings[0], "name", None) not in ("a", "i"):
        return None
    source_tag.decompose()
    book = siblings.pop(0)
    source = extract_source(book)
    book.decompose()
    _strip_whitespace(siblings)
    if siblings and getattr(siblings[0], "name", None) == "sup":
        assert "errata" not in source, "Should be no more than one errata."
        sup = siblings.pop(0)
        _, source["errata"] = extract_link(sup.find("a"))
        sup.decompose()
    # Strip trailing comma or whitespace between multiple sources
    _strip_whitespace(siblings)
    if siblings and isinstance(siblings[0], str) and siblings[0].strip() == ",":
        siblings[0].extract()
        siblings.pop(0)
    if siblings and getattr(siblings[0], "name", None) == "br":
        siblings[0].decompose()
    return source


def _extract_bold_fields(section, text):
    """Extract Prerequisites, Archetype, Requirements, Trigger, etc. from text string."""
    bs = BeautifulSoup(text, "html.parser")
    _extract_bold_fields_from_bs(section, bs)
    _attach_archetype_note(section)


def _extract_archetypes(section, bs):
    """Extract Archetype/Archetypes bold field into structured array.

    Parses archetype links, detects '*' footnote markers on individual archetypes,
    and extracts the '* This archetype/version...' note text.
    """
    bold = None
    for b in list(bs.find_all("b")):
        label = get_text(b).strip()
        if label in ("Archetype", "Archetypes"):
            bold = b
            break
    if not bold:
        return

    # Collect sibling nodes until next <b> tag
    nodes_to_remove = []
    node = bold.next_sibling
    value_nodes = []
    note_nodes = []
    in_note = False
    while node:
        if getattr(node, "name", None) == "b":
            break
        # Detect "* This archetype/version..." note (not a bare "*" star marker)
        if (
            not in_note
            and isinstance(node, str)
            and re.match(r"^\*\s+\w", node.lstrip())
        ):
            in_note = True
        if in_note:
            note_nodes.append(node)
        else:
            value_nodes.append(node)
        nodes_to_remove.append(node)
        node = node.next_sibling

    # Parse archetype links from value nodes
    value_html = "".join(str(n) for n in value_nodes).strip()
    value_html = re.sub(r"<br/?>[\s]*$", "", value_html)
    value_bs = BeautifulSoup(value_html, "html.parser")

    archetypes = []
    for a in value_bs.find_all("a"):
        name, link_obj = extract_link(a)
        arch_obj = {"name": name.strip(), "type": "feat_archetype"}
        if link_obj:
            arch_obj["link"] = link_obj
        # Check for '*' immediately after this link's parent <u> or the <a> itself
        parent = a.parent
        target = parent if parent and parent.name == "u" else a
        next_sib = target.next_sibling
        if isinstance(next_sib, str) and next_sib.startswith("*"):
            arch_obj["star"] = True
        archetypes.append(arch_obj)

    if not archetypes:
        return

    # Extract note text if present
    if note_nodes:
        note_text = "".join(str(n) for n in note_nodes).strip()
        note_text = re.sub(r"<br/?>[\s]*$", "", note_text)
        # Strip leading "* " from note
        note_text = re.sub(r"^\*\s*", "", note_text)
        if note_text:
            for arch in archetypes:
                if arch.get("star"):
                    arch["note"] = note_text
                    del arch["star"]

    section["archetype"] = archetypes

    # Remove extracted nodes from BS
    for n in nodes_to_remove:
        n.extract()
    bold.decompose()


def _attach_archetype_note(section):
    """Find '* This archetype/version...' note in field values and move to archetypes.

    The note often ends up appended to the last pre-hr bold field value (e.g. requirement)
    because it appears after all bold fields in the HTML. Strip it from the field and
    attach it to starred archetype objects.
    """
    archetypes = section.get("archetype")
    if not archetypes or not isinstance(archetypes, list):
        return
    # Already have notes from inline detection
    starred = [a for a in archetypes if a.get("star")]
    if starred and any("note" in a for a in starred):
        return

    # Only scan bold-extracted fields, not description text or name
    _note_scan_fields = {
        "requirement", "prerequisite", "trigger", "frequency", "cost",
        "duration", "access", "special", "effect",
    }
    note_re = re.compile(r"\s*\*\s+(This (?:archetype|version)\b.+)")
    for key in _note_scan_fields:
        val = section.get(key)
        if not isinstance(val, str):
            continue
        m = note_re.search(val)
        if m:
            note_text = m.group(1).strip()
            # Strip trailing <br> from note
            note_text = re.sub(r"<br/?>[\s]*$", "", note_text).strip()
            # Remove note from field value
            section[key] = val[: m.start()].rstrip()
            # Strip trailing <br> from cleaned value
            section[key] = re.sub(r"<br/?>[\s]*$", "", section[key]).strip()
            # Attach note to starred archetypes, or all if none are starred
            targets = starred if starred else archetypes
            for arch in targets:
                arch["note"] = note_text
                arch.pop("star", None)
            return


def _extract_bold_fields_from_bs(section, bs):
    """Extract bold-labeled fields from a BS object, removing them in place."""
    known_labels = {
        "Prerequisites",
        "Prerequisite",
        "Requirements",
        "Requirement",
        "Trigger",
        "Frequency",
        "Cost",
        "Duration",
        "Access",
        "Special",
        "Effect",
    }

    # Handle Archetype/Archetypes separately with structured extraction
    _extract_archetypes(section, bs)

    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if label not in known_labels:
            continue
        # Collect value nodes between this bold and the next bold
        nodes_to_remove = []
        node = bold.next_sibling
        parts = []
        while node:
            if getattr(node, "name", None) == "b":
                break
            parts.append(str(node))
            nodes_to_remove.append(node)
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        if value.endswith(";"):
            value = value[:-1].strip()
        key = label.lower().replace(" ", "_")
        if key == "requirements":
            key = "requirement"
        if key == "prerequisites":
            key = "prerequisite"
        section[key] = value
        # Remove extracted nodes from BS
        for n in nodes_to_remove:
            n.extract()
        bold.decompose()


def _extract_trailing_sections(struct, bs):
    """Extract h2 sections and trait-entry divs trapped in feat text.

    Some feats (mostly legacy dedication feats) have "X Leads To..." and
    "Traits" h2 sections inside the feat text instead of as separate sections.
    This happens when parse_universal can't split them due to DOM structure.
    """
    for h2 in list(bs.find_all("h2", class_="title")):
        name = get_text(h2).strip()
        # Collect all content after the h2 until the next h2
        parts = []
        nodes_to_remove = []
        node = h2.next_sibling
        while node:
            if getattr(node, "name", None) == "h2":
                break
            parts.append(str(node))
            nodes_to_remove.append(node)
            node = node.next_sibling
        text = "".join(parts).strip()
        for n in nodes_to_remove:
            n.extract()
        h2.decompose()
        # Drop "Traits" sections — redundant with enriched trait objects
        if name == "Traits":
            continue
        if name or text:
            section = {"name": name, "type": "section", "sections": []}
            if text:
                section["text"] = text
            struct["sections"].append(section)

    # Remove any remaining trait-entry divs
    for div in list(bs.find_all("div", {"class": "trait-entry"})):
        div.extract()


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
        nodes_to_remove = []
        parts = []
        node = bold.next_sibling
        while node:
            if getattr(node, "name", None) == "b":
                break
            parts.append(str(node))
            nodes_to_remove.append(node)
            node = node.next_sibling
        value = "".join(parts).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        section[key] = value
        for n in nodes_to_remove:
            n.extract()
        bold.decompose()


def _extract_called_actions(struct):
    """Extract calledAction divs from section text into structured ability objects.

    Some feats (e.g., Beastmaster Dedication, Additional Follower) have embedded
    action definitions in extra sections. These contain h3 titles, traits, sources,
    and description text that would fail markdown validation if left in raw text.
    """
    for section in struct.get("sections", []):
        _extract_called_actions_from_section(section)


def _extract_called_actions_from_section(section):
    """Process a single section, extracting any calledAction divs."""
    # Recurse into subsections first
    for sub in section.get("sections", []):
        _extract_called_actions_from_section(sub)

    if "text" not in section:
        return

    bs = BeautifulSoup(section["text"], "html.parser")
    called_divs = bs.find_all("div", {"class": "calledAction"})
    if not called_divs:
        return

    for div in called_divs:
        action = _parse_called_action(div)
        div.extract()
        section.setdefault("abilities", []).append(action)

    section["text"] = str(bs).strip()


def _parse_called_action(div):
    """Parse a calledAction div into a structured ability object."""
    ability = {
        "type": "stat_block_section",
        "subtype": "ability",
        "ability_type": "called",
        "sections": [],
    }

    # Extract name from h3 title
    h3 = div.find("h3")
    if h3:
        a = h3.find("a")
        if a:
            name, link = extract_link(a)
            ability["name"] = name.strip()
            ability["link"] = link
        else:
            ability["name"] = get_text(h3).strip()
        h3.decompose()

    # Extract traits
    traits = []
    for span in div.find_all("span", class_=lambda c: c and c.startswith("trait")):
        a = span.find("a")
        if a:
            name, trait_link = extract_link(a)
            traits.append(
                build_object("stat_block_section", "trait", name.strip(), {"link": trait_link})
            )
        span.decompose()
    if traits:
        ability["traits"] = traits

    # Remove letter-spacing separators
    for span in div.find_all("span", style=lambda s: s and "letter-spacing" in s):
        span.decompose()

    # Extract source
    source = _extract_source_from_bs(div)
    if source:
        ability["sources"] = [source]

    # Extract bold fields (Trigger, Requirements, Frequency, etc.) from pre-hr
    # content, then use post-hr as description text
    hr = div.find("hr")
    if hr:
        pre_hr_parts = []
        for sibling in list(hr.previous_siblings):
            pre_hr_parts.insert(0, str(sibling))
            sibling.extract()
        hr.decompose()
        pre_hr_text = "".join(pre_hr_parts).strip()
        _extract_bold_fields(ability, pre_hr_text)

    # Remove leading br tags from remaining content
    for child in list(div.children):
        if getattr(child, "name", None) == "br":
            child.decompose()
        elif isinstance(child, str) and not child.strip():
            child.extract()
        else:
            break

    # Extract result blocks from post-hr content
    _extract_result_blocks(ability, div)

    # Extract trailing h2 sections (e.g. "Spellstrike Specifics")
    for h2 in list(div.find_all("h2", class_="title")):
        name = get_text(h2).strip()
        parts = []
        nodes_to_remove = []
        node = h2.next_sibling
        while node:
            if getattr(node, "name", None) == "h2":
                break
            parts.append(str(node))
            nodes_to_remove.append(node)
            node = node.next_sibling
        text = "".join(parts).strip()
        for n in nodes_to_remove:
            n.extract()
        h2.decompose()
        if name or text:
            section = {"name": name, "type": "section", "sections": []}
            if text:
                section["text"] = text
            ability["sections"].append(section)

    # Remaining inner HTML is the description (preserve tags for link extraction)
    text = "".join(str(c) for c in div.children).strip()
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    if text.strip():
        ability["text"] = text.strip()

    return ability


_LINK_FIELDS = [
    "text",
    "prerequisite",
    "requirement",
    "trigger",
    "frequency",
    "cost",
    "effect",
    "access",
    "special",
    "critical_success",
    "success",
    "failure",
    "critical_failure",
]


def feat_link_pass(struct):
    """Extract links from text fields and unwrap anchor tags."""

    def _handle_text_field(section, field, keep=True):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs, unwrap=True)
        if len(links) > 0 and keep:
            linklist = section.setdefault("links", [])
            linklist.extend(links)
        for span in bs.find_all("span", {"class": "action"}):
            span.decompose()
        for span in bs.find_all("span", style=lambda s: s and "letter-spacing" in s):
            span.decompose()
        section[field] = str(bs).strip()

    def _process_section(section):
        keep_name_links = section.get("type") == "section"
        _handle_text_field(section, "name", keep_name_links)
        for field in _LINK_FIELDS:
            _handle_text_field(section, field)
        for arch in section.get("archetype", []):
            if isinstance(arch, dict) and "note" in arch:
                _handle_text_field(arch, "note")
        for s in section.get("sections", []):
            _process_section(s)
        for ability in section.get("abilities", []):
            _process_section(ability)

    for section in struct["sections"]:
        _process_section(section)

    feat = find_feat(struct)
    assert feat is not None, f"No feat section found in {struct.get('name', 'unknown')}"
    _process_section(feat)


def feat_cleanup_pass(struct):
    """Clean up and promote fields from feat to top level."""
    assert "feat" in struct, f"No feat object found in struct: {struct.get('name')}"
    feat = struct["feat"]

    _convert_feat_text(feat)
    _promote_feat_fields(struct, feat)
    _clean_html_fields(struct)


def _convert_feat_text(feat):
    """Convert feat text HTML to markdown."""
    if "text" not in feat:
        return
    soup = BeautifulSoup(feat["text"], "html.parser")
    # Remove Nethys notes
    first = list(soup.children)[0] if list(soup.children) else None
    if first and first.name == "i":
        text = get_text(first)
        if "Note from Nethys:" in text:
            first.clear()
        first.unwrap()
    cleaned = str(soup).strip()
    if cleaned:
        feat["text"] = md(cleaned)
    else:
        del feat["text"]


def _promote_feat_fields(struct, feat):
    """Move envelope fields from feat object to top-level struct."""
    struct["name"] = feat["name"]
    if "sources" in feat:
        struct["sources"] = feat["sources"]
        del feat["sources"]
    elif "sources" not in struct:
        struct["sources"] = []

    if "sections" in feat:
        del feat["sections"]


def _clean_html_fields(struct):
    """Rename 'html' keys to 'text' in sections recursively."""
    for section in struct.get("sections", []):
        if "html" in section:
            section["text"] = section["html"]
            del section["html"]
        if "sections" in section:
            _clean_html_fields(section)


def write_feat(jsondir, struct, source):
    print("{} ({}): {}".format(struct["game-obj"], source, struct["name"]))
    filename = create_feat_filename(jsondir, struct)
    with open(filename, "w") as fp:
        json.dump(struct, fp, indent=4)


def create_feat_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
