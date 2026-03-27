"""Shared change extraction utilities for template/family parsers.

Extracts raw change data from HTML — the <li> elements, inline abilities,
and adjustment tables. Does NOT categorize or build effects; that's the
enrichment pipeline's job.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from universal.ability import parse_abilities_from_nodes
from universal.universal import build_object, extract_link, get_links
from universal.utils import get_text

_ACTION_TITLE_MAP = {
    "Single Action": "One Action",
    "Two Actions": "Two Actions",
    "Three Actions": "Three Actions",
    "Reaction": "Reaction",
    "Free Action": "Free Action",
}


def parse_change(li):
    """Parse a single <li> into a change object, extracting abilities if present."""
    change = build_object("stat_block_section", "change", "")
    # Check if this li contains abilities (bold names after "Add the following abilities")
    text_content = get_text(li).strip()
    has_abilities = "following abilit" in text_content.lower()
    if has_abilities:
        abilities = _extract_abilities_from_li(li)
        if abilities:
            change["abilities"] = abilities
    # Extract links from li
    links = get_links(li, unwrap=True)
    if links:
        change["links"] = links
    # Unwrap action spans — keep text
    for span in li.find_all("span", {"class": "action"}):
        span.unwrap()
    text = str(li).strip()
    # Clean leading/trailing br
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    change["text"] = text.strip()
    # Remove empty name — text is the content
    del change["name"]
    return change


def parse_ability_nodes(nodes):
    """Parse a sequence of nodes into ability objects.

    Abilities are delimited by <br> tags. Each starts with <b>Name</b>
    (optionally inside <a>), optionally followed by <span class="action">,
    then description text.
    """
    abilities = []
    current_ability = None
    for node in nodes:
        if isinstance(node, Tag) and node.name == "br":
            if current_ability:
                abilities.append(current_ability)
                current_ability = None
            continue
        if isinstance(node, Tag) and node.name == "a" and node.find("b"):
            b = node.find("b")
            name = get_text(b).strip()
            if current_ability:
                abilities.append(current_ability)
            current_ability = build_object("stat_block_section", "ability", name)
            link_name, link_obj = extract_link(node)
            if link_obj:
                current_ability["link"] = link_obj
            continue
        if isinstance(node, Tag) and node.name == "b":
            name = get_text(node).strip()
            if current_ability:
                abilities.append(current_ability)
            current_ability = build_object("stat_block_section", "ability", name)
            continue
        if isinstance(node, Tag) and node.name == "span" and "action" in node.get("class", []):
            if current_ability:
                title = node.get("title", "")
                if title in _ACTION_TITLE_MAP:
                    current_ability["action_type"] = build_object(
                        "stat_block_section", "action_type", _ACTION_TITLE_MAP[title]
                    )
            continue
        if current_ability:
            text_bit = str(node).strip()
            if text_bit:
                existing = current_ability.get("text", "")
                current_ability["text"] = (existing + " " + text_bit).strip()

    if current_ability:
        abilities.append(current_ability)

    # Extract links from ability text fields
    for ability in abilities:
        if "text" in ability:
            ab_bs = BeautifulSoup(ability["text"], "html.parser")
            links = get_links(ab_bs, unwrap=True)
            if links:
                ability["links"] = links
            ability["text"] = str(ab_bs).strip()

    return abilities if abilities else None


def _extract_abilities_from_li(li):
    """Extract abilities from a <li> that says 'Add the following abilities.'"""
    found_abilities_text = False
    nodes = list(li.children)
    ability_nodes = []
    for node in nodes:
        if not found_abilities_text:
            if isinstance(node, NavigableString) and "following abilit" in str(node).lower():
                found_abilities_text = True
            continue
        ability_nodes.append(node)
    return parse_abilities_from_nodes(ability_nodes)


def extract_inline_abilities(bs):
    """Extract abilities from text where they appear inline separated by <br>.

    For templates without a <ul> list — abilities appear directly in text after
    a sentence like 'The creature gains the following abilities.'
    """
    # Find the first <b> tag that's NOT inside a <table>
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
    return parse_ability_nodes(ability_nodes)


def parse_adjustments_table(text):
    """Parse a markdown or HTML table into adjustment objects."""
    bs = BeautifulSoup(text, "html.parser")
    table = bs.find("table")
    if table:
        return _parse_html_table(table)
    # Try markdown table
    return _parse_markdown_table(text)


def _parse_html_table(table):
    """Parse an HTML table into adjustment objects."""
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None
    # First row is headers
    headers = []
    for td in rows[0].find_all(["td", "th"]):
        headers.append(get_text(td).strip().lower().replace(" ", "_"))
    adjustments = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        adj = build_object("stat_block_section", "adjustment", "")
        del adj["name"]
        for i, cell in enumerate(cells):
            if i < len(headers):
                adj[headers[i]] = get_text(cell).strip()
        adjustments.append(adj)
    return adjustments if adjustments else None


def _parse_markdown_table(text):
    """Parse a markdown table into adjustment objects."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 3:
        return None
    # First line is headers, second is separator
    headers = [
        h.strip().lower().replace(" ", "_").replace("*", "")
        for h in lines[0].split("|")
        if h.strip()
    ]
    adjustments = []
    for line in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.split("|") if c.strip()]
        adj = build_object("stat_block_section", "adjustment", "")
        del adj["name"]
        for i, cell in enumerate(cells):
            if i < len(headers):
                adj[headers[i]] = cell
        adjustments.append(adj)
    return adjustments if adjustments else None
