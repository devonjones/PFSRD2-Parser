import json
import os
import re
import sys

from bs4 import BeautifulSoup, Tag

from pfsrd2.ability_enrichment import template_ability_enrichment_pass
from pfsrd2.change_enrichment import change_enrichment_pass
from pfsrd2.change_extraction import collect_ability_nodes, parse_change
from pfsrd2.equivalents import equivalent_link_pass
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from universal.ability import parse_abilities_from_nodes
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass as universal_markdown_pass
from universal.monster_ability import monster_ability_db_pass
from universal.spells import is_spell_name, parse_spell_block
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
    image = _extract_image(details)
    struct = restructure_monster_family_pass(details)
    if alternate_link:
        struct["alternate_link"] = alternate_link
    if image:
        struct["image"] = image
    monster_family_struct_pass(struct)
    _strip_empty_text(struct)
    source_pass(struct, find_monster_family)
    _extract_creation_changes(struct)
    _extract_section_abilities(struct)
    monster_family_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, "monster_family", find_monster_family)
    _consolidate_creation_changes(struct)
    change_enrichment_pass(struct, "monster_family")
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    equivalent_link_pass(struct)
    monster_family_cleanup_pass(struct)
    set_edition_from_db_pass(struct)
    monster_ability_db_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    strip_block_tags(struct)
    universal_markdown_pass(struct, struct["name"], "", fxn_valid_tags=_valid_tags)
    template_ability_enrichment_pass(struct)
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
        print(json.dumps(struct, indent=2, sort_keys=True))


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
    # Decompose sidebar images in headings (icons).
    # Thumbnail artwork (<img class="thumbnail">) is inside an <a> wrapper;
    # decomposing the <img> leaves the <a href="Images\Monsters\X.png"> in the
    # tree, which _extract_image picks up later from the details text.
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
            new_h3 = BeautifulSoup(f'<h3 class="title">{title_text}</h3>', "html.parser").h3
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
        return "adjustments" in n

    def _process_section(section):
        name = section.get("name", "")
        if _is_creation_section(name) and "text" in section:
            _extract_changes_from_section(section, all_sections)
        for sub in section.get("sections", []):
            _process_section(sub)

    for section in all_sections:
        _process_section(section)


# Prose lines in creation sections that are stat instructions, not flavor.
# Legacy families (pre-remaster) often carry their "change its statistics"
# steps as <br>-separated prose instead of a <ul> (e.g. Bestiary Lich).
_PROSE_IMPERATIVE = re.compile(r"^\s*(?:increase|decrease|change)\b", re.I)
# "A lich gains the undead trait and becomes evil." / "Liches lose all
# abilities that come from being a living creature." — requires a mechanics
# noun so flavor sentences ("ghouls gain sustenance...") don't match.
_PROSE_GAIN_LOSE = re.compile(
    r"^\s*(?:it|they|a|an|the|[a-z][\w']*s?)\b[\w' ]{0,30}?" r"\b(?:also\s+)?(?:gains?|loses?)\b",
    re.I,
)
_PROSE_MECHANICS_NOUN = re.compile(r"\b(?:trait|abilit|statistic)", re.I)
# Level-change instruction buried mid-sentence in intro prose:
# "To create a lich, increase the spellcaster's level by 1 and ..."
_LEVEL_SENTENCE = re.compile(
    r"[^.]*\b(?:increase|decrease)[^.]*?\blevel by (?:\d+|one|two)\b[^.]*\.",
    re.I,
)
# Sentence-level extraction, for lines where a stat instruction shares a
# line with a grant marker (Swarm Strider: "A swarm strider gains the
# aberration and swarm traits. ... typically have the following abilities.")
# or uses transform phrasing (Phantom: "by trading their usual traits for
# the ethereal, incorporeal, and spirit traits").
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[a-z][.!?])(?=[A-Z])")
_SENT_VERB = re.compile(r"\b(?:gains?|loses?|trades?|trading)\b", re.I)
_SENT_NOUN = re.compile(r"\b(?:trait|abilit|statistic|immunit|resistance|weakness)", re.I)
# "has/have" is too weak a verb for the broad noun set — only trait adds
# ("all blackfrost dead have the rare trait").
_SENT_HAVE_TRAIT = re.compile(r"\bha(?:s|ve)\b[^.]*\btraits?\b", re.I)
# Non-universal quantifiers mark guidance, not rules ("Many phantoms gain
# occult innate spells...").
_SENT_NONUNIVERSAL = re.compile(r"^\s*(?:many|some|most|often|several|a few|certain)\b", re.I)


# Anaphoric lead-ins depend on prior context ("Either way, increase its
# cantrip level by 1.") and cannot stand alone as changes; parentheticals
# are asides; "When ..." sentences are conditional mechanics, not creation
# instructions; "listed below" is a grant marker like "following".
_SENT_ANAPHORA = re.compile(
    r"^\s*(?:\(|(?:either way|then|instead|otherwise|in either case|when)\b)", re.I
)


def _sentence_excluded(sent):
    low = sent.lower()
    return (
        not sent.strip()
        or "following" in low
        or "as detailed below" in low
        or "listed below" in low
        or "if you " in low
        or _SENT_NONUNIVERSAL.match(sent)
        or _SENT_ANAPHORA.match(sent)
    )


def _sentence_changes(plain):
    """Extract per-sentence stat instructions from a prose line."""
    out = []
    for sent in _SENT_SPLIT.split(plain):
        if _sentence_excluded(sent):
            continue
        matched = (
            _PROSE_IMPERATIVE.match(sent)
            or (_SENT_VERB.search(sent) and _SENT_NOUN.search(sent))
            or _SENT_HAVE_TRAIT.search(sent)
            or _LEVEL_SENTENCE.search(sent)
        )
        if not matched:
            continue
        change = build_object("stat_block_section", "change", "")
        change["text"] = sent.strip()
        del change["name"]
        out.append(change)
    return out


def _prose_change_from_html(line_html):
    """Build a change object from a prose line's HTML fragment."""
    wrapper = BeautifulSoup(f"<div>{line_html}</div>", "html.parser").div
    change = build_object("stat_block_section", "change", "")
    links = get_links(wrapper, unwrap=True)
    if links:
        change["links"] = links
    for span in wrapper.find_all("span", {"class": "action"}):
        span.unwrap()
    change["text"] = wrapper.decode_contents().strip()
    del change["name"]
    return change


def _prose_changes_for_line(line_html):
    """Return changes for a prose line's stat instructions.

    Whole-line match first (preserves links); otherwise per-sentence scan,
    so instructions sharing a line with a grant marker still extract.
    Grant/choice markers ("...the following abilities") are handled by the
    ability parsing path, never here.
    """
    # Bold-led lines are ability/name-entry definitions ("<b>Change Shape</b>
    # ..."), owned by the ability parsing path — never prose changes, even
    # when the ability name starts with an imperative verb ("Change ...").
    if re.match(r"\s*<b>", line_html, re.I):
        return []
    plain = get_text(BeautifulSoup(line_html, "html.parser")).strip()
    if not plain:
        return []
    mixed_polarity = re.search(r"\b(?:gains?|trades?|trading)\b", plain, re.I) and re.search(
        r"\bloses?\b", plain, re.I
    )
    if not _sentence_excluded(plain) and not mixed_polarity:
        if _PROSE_IMPERATIVE.match(plain):
            return [_prose_change_from_html(line_html)]
        if _PROSE_GAIN_LOSE.match(plain) and _PROSE_MECHANICS_NOUN.search(plain):
            return [_prose_change_from_html(line_html)]
        m = _LEVEL_SENTENCE.search(plain)
        if m:
            change = build_object("stat_block_section", "change", "")
            change["text"] = m.group(0).strip()
            del change["name"]
            return [change]
    return _sentence_changes(plain)


def _extract_changes_from_section(section, all_sections=None):
    """Extract changes from a creation section's text.

    <ul><li> lists are the primary form (each li is a change, destructively
    removed from the display text). Prose stat instructions — legacy families
    that predate the <ul> convention, or level changes buried in intro
    sentences — are additionally extracted in document order, but stay in
    the display text (sections remain the source of truth for reading).
    """

    text = section.get("text", "")
    bs = BeautifulSoup(text, "html.parser")
    changes = []
    # Walk top-level nodes in document order, splitting prose into lines on
    # <br>, so intro-prose changes land before the <ul> changes they precede.
    line_nodes = []

    def _flush_line():
        if not line_nodes:
            return
        line_html = "".join(str(n) for n in line_nodes)
        line_nodes.clear()
        changes.extend(_prose_changes_for_line(line_html))

    ul_found = False
    for node in list(bs.children):
        if isinstance(node, Tag) and node.name == "ul" and not ul_found:
            ul_found = True
            _flush_line()
            for li in node.find_all("li", recursive=False):
                if not get_text(li).strip():
                    continue
                changes.append(parse_change(li))
            node.decompose()
        elif isinstance(node, Tag) and node.name == "br":
            _flush_line()
        elif isinstance(node, Tag) and node.name == "ul":
            # A second <ul> stays in display text (main's behavior) rather
            # than being swallowed into a prose line's change text.
            _flush_line()
        else:
            line_nodes.append(node)
    _flush_line()

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
    references abilities via JSONPath back to the sections tree rather
    than copying them — sections remain the source of truth for display.
    """
    mf = struct.get("monster_family")
    assert mf is not None, f"No monster_family in struct: {struct.get('name')}"
    all_changes = []
    subtypes = []

    def _collect_changes(sections):
        for section in sections:
            if "changes" in section:
                all_changes.extend(section["changes"])
                del section["changes"]
            _collect_changes(section.get("sections", []))

    _collect_changes(struct.get("sections", []))

    def _section_path_filter(name):
        """Build a JSONPath name filter for a section."""
        assert name, "Section name must not be empty for JSONPath filter"
        escaped = name.replace("'", "\\'")
        return f"[?(@.name=='{escaped}')]"

    def _build_subtype(section, section_path):
        """Build a monster_family subtype that references section abilities.

        Instead of copying abilities into the subtype, the effects use
        JSONPath source references back to the sections tree. This keeps
        sections as the single source of truth for display while giving
        the template engine the structured change objects it needs.
        """
        subtype = {
            "name": section.get("name", ""),
            "type": "stat_block_section",
            "subtype": "monster_family",
        }
        # Text stays in sections (source of truth for display), not duplicated here.
        if section.get("abilities") or section.get("spells"):
            change = {
                "type": "stat_block_section",
                "subtype": "change",
                "text": section.get("name", ""),
                "change_category": "abilities",
            }
            if section.get("abilities"):
                change["effects"] = [
                    {
                        "target": "$.defense.automatic_abilities",
                        "operation": "add_items",
                        "source": f"{section_path}.abilities",
                    }
                ]
            if section.get("spells"):
                if "effects" not in change:
                    change["effects"] = []
                change["effects"].append(
                    {
                        "target": "$.offense.offensive_actions",
                        "operation": "add_items",
                        "source": f"{section_path}.spells",
                    }
                )
            if section.get("links"):
                change["links"] = section["links"]
            subtype["changes"] = [change]
        # Recurse into subsections
        child_subtypes = []
        for sub in section.get("sections", []):
            if _has_abilities_anywhere(sub):
                sub_path = f"{section_path}.sections{_section_path_filter(sub.get('name', ''))}"
                child_subtypes.append(_build_subtype(sub, sub_path))
        if child_subtypes:
            subtype["subtypes"] = child_subtypes
        return subtype

    def _has_abilities_anywhere(section):
        """Check if section or any subsection has abilities or spells."""
        if section.get("abilities") or section.get("spells"):
            return True
        return any(_has_abilities_anywhere(s) for s in section.get("sections", []))

    # Collect ability/spell sections into subtypes — sections stay in the tree
    for section in struct.get("sections", []):
        if _has_abilities_anywhere(section):
            sec_filter = _section_path_filter(section.get("name", ""))
            sec_path = f"$.sections{sec_filter}"
            if section.get("abilities") or section.get("spells"):
                subtypes.append(_build_subtype(section, sec_path))
            else:
                # Abilities are in subsections only
                for sub in section.get("sections", []):
                    if _has_abilities_anywhere(sub):
                        sub_path = f"{sec_path}.sections{_section_path_filter(sub.get('name', ''))}"
                        subtypes.append(_build_subtype(sub, sub_path))

    # Sections are NOT removed — they stay intact for display
    if all_changes:
        mf["changes"] = all_changes
    if subtypes:
        mf["subtypes"] = subtypes


def _extract_image(details):
    """Extract thumbnail image from first detail's text.

    The content filter decomposes <img> tags but leaves the <a> wrapper
    with href pointing to the image file. Extract and remove it.

    Returns an image dict or None.
    """
    if not details:
        return None
    assert isinstance(details[0], dict), f"Expected dict, got {type(details[0])}"
    name_html = details[0].get("name", "")
    family_name = get_text(BeautifulSoup(name_html, "html.parser")).strip()
    text = details[0].get("text", "")
    bs = BeautifulSoup(text, "html.parser")
    for a in bs.find_all("a"):
        href = a.get("href", "")
        if "Images" in href and "Monsters" in href and href.endswith(".png"):
            image_file = href.replace("\\", "/").split("/")[-1]
            a.decompose()
            details[0]["text"] = str(bs).strip()
            return {
                "type": "image",
                "name": family_name,
                "game-obj": "MonsterFamilies",
                "image": image_file,
            }
    return None


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
    # Sections with extracted abilities preserve the original HTML text
    # which includes action <span> tags (e.g., [one-action]). The <b> and
    # <br> tags are already in the default validset.
    if struct.get("abilities") or struct.get("spells"):
        validset.add("span")


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
                # Parse a COPY — collect_ability_nodes mutates the tree via
                # extract(), but we want section text to stay intact for display.
                bs = BeautifulSoup(text, "html.parser")
                # Don't extract from text that's purely in tables
                if bs.find("b") and not (bs.find("table") and not bs.find("b", recursive=False)):
                    abilities, spells = _extract_abilities_from_bs(bs)
                    if abilities:
                        section.setdefault("abilities", []).extend(abilities)
                    if spells:
                        section.setdefault("spells", []).extend(spells)
        for sub in section.get("sections", []):
            _process(sub)

    for section in struct.get("sections", []):
        _process(section)


def _extract_abilities_from_bs(bs):
    """Extract abilities and spells from a BS object.

    Uses shared collect_ability_nodes to find and extract nodes, then
    splits into spell blocks and ability nodes.

    Returns: (abilities_list_or_None, spells_list_or_None)
    """
    all_nodes = collect_ability_nodes(bs)
    if not all_nodes:
        return None, None

    # Split into spell blocks and ability nodes
    spells, ability_nodes = _split_spell_nodes(all_nodes)

    abilities = parse_abilities_from_nodes(ability_nodes) if ability_nodes else None
    return abilities, spells if spells else None


def _split_spell_nodes(nodes):
    """Split nodes into spell blocks and remaining ability nodes.

    Walks through nodes looking for <b> tags whose text matches
    is_spell_name(). When found, collects that <b> and all following
    nodes (spell levels like <b>3rd</b>, <b>Cantrips</b>) until a <br>
    before a non-spell <b> or end of nodes. The collected nodes become
    the HTML text for parse_spell_block.
    """
    spells = []
    ability_nodes = []
    i = 0

    while i < len(nodes):
        node = nodes[i]

        # Check if this node is a <b> with a spell name
        if isinstance(node, Tag) and node.name == "b":
            name = get_text(node).strip()
            if is_spell_name(name):
                # Collect this spell block — name <b> + all following text/levels
                spell_html_parts = []
                i += 1  # skip the name <b>
                while i < len(nodes):
                    n = nodes[i]
                    # Stop at <br> if next significant node is a non-spell <b>
                    if isinstance(n, Tag) and n.name == "br":
                        # Peek ahead for next <b>
                        next_b = _find_next_b(nodes, i + 1)
                        if next_b is None or not _is_spell_level(get_text(next_b).strip()):
                            break
                    spell_html_parts.append(str(n))
                    i += 1

                # Parse the spell block — but only if it has spell level
                # indicators (<b>1st</b>, <b>Cantrips</b>, etc.). Narrative
                # spell descriptions without levels stay as abilities.
                spell_text = "".join(spell_html_parts).strip()
                has_levels = any(
                    f"<b>{lvl}</b>" in spell_text or f"<b>\n{lvl}</b>" in spell_text
                    for lvl in [
                        "1st",
                        "2nd",
                        "3rd",
                        "4th",
                        "5th",
                        "6th",
                        "7th",
                        "8th",
                        "9th",
                        "10th",
                        "Cantrips",
                        "Constant",
                        "Rituals",
                    ]
                ) or re.search(r"<b>\s*Cantrips\s*\(", spell_text)
                if spell_text and has_levels:
                    spell = parse_spell_block(name, spell_text)
                    spells.append(spell)
                else:
                    # No spell levels — keep as ability
                    ability_nodes.append(node)
                    for part_html in spell_html_parts:
                        bs_part = BeautifulSoup(part_html, "html.parser")
                        for child in bs_part.children:
                            ability_nodes.append(child)
                continue

        ability_nodes.append(node)
        i += 1

    return spells, ability_nodes


def _find_next_b(nodes, start):
    """Find the next <b> tag in nodes starting from index start."""
    for i in range(start, len(nodes)):
        n = nodes[i]
        if isinstance(n, Tag) and n.name == "b":
            return n
        if isinstance(n, Tag) and n.name == "a" and n.find("b"):
            return n.find("b")
    return None


_SPELL_LEVEL_NAMES = {
    "1st",
    "2nd",
    "3rd",
    "4th",
    "5th",
    "6th",
    "7th",
    "8th",
    "9th",
    "10th",
    "Constant",
}


def _is_spell_level(text):
    """Check if text looks like a spell level name."""
    if text in _SPELL_LEVEL_NAMES:
        return True
    return bool(text.startswith("Cantrips") or text == "Rituals")


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
    json.dump(struct, fp, indent=2, sort_keys=True)
    fp.close()


def create_monster_family_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)
