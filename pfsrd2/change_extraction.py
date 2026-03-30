"""Shared change extraction utilities for template/family parsers.

Extracts raw change data from HTML — the <li> elements, inline abilities,
and adjustment tables. Does NOT categorize or build effects; that's the
enrichment pipeline's job.
"""

import re

from bs4 import BeautifulSoup, NavigableString

from universal.ability import parse_abilities_from_nodes
from universal.universal import build_object, get_links
from universal.utils import get_text


def collect_ability_nodes(bs):
    """Collect ability nodes from a BS object.

    Finds the first <b> tag not inside a <table> and collects all sibling
    nodes from there onward (extracting them from the tree).

    Returns: list of extracted nodes, or None if no <b> tag found.
    """
    first_b = None
    for b in bs.find_all("b"):
        if not b.find_parent("table"):
            first_b = b
            break
    if not first_b:
        return None
    # If the <b> is inside an <a>, start from the <a> instead
    start_node = first_b
    if first_b.parent and first_b.parent.name == "a":
        start_node = first_b.parent
    # Collect all nodes from the start onward (siblings only)
    nodes = []
    node = start_node
    while node:
        next_node = node.next_sibling
        nodes.append(node.extract())
        node = next_node
    return nodes


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
