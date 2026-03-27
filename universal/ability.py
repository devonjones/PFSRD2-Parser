"""Unified ability parser for all content types.

Parses abilities from HTML into structured objects with action types,
traits, addon fields, result blocks, and affliction detection. Used by
creature, monster family, monster template, feat, and skill parsers.

Two entry points:
- parse_abilities_from_nodes(): for <br>-delimited node sequences
- parse_ability_from_html(): for single ability from HTML text
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from pfsrd2.action import extract_action_type
from pfsrd2.trait import extract_starting_traits
from universal.creatures import universal_handle_save_dc
from universal.universal import (
    build_object,
    extract_bold_fields,
    extract_link,
    extract_result_blocks,
    get_links,
)
from universal.utils import get_text


# Default set of bold-labeled fields recognized across all parsers.
# Parsers can pass a custom set to restrict or extend.
DEFAULT_ADDON_LABELS = {
    # Standard ability addons
    "Frequency",
    "Trigger",
    "Effect",
    "Duration",
    "Requirement",
    "Requirements",
    "Prerequisite",
    "Prerequisites",
    "Cost",
    # Feat-specific
    "Access",
    "Special",
    # Offensive ability fields
    "Range",
    "Damage",
    # Affliction fields
    "Saving Throw",
    "Onset",
    "Maximum Duration",
}

_STAGE_RE = re.compile(r"^Stage\s+\d+$", re.IGNORECASE)

# Addon fields that signal an affliction when combined with Stage N
_AFFLICTION_FIELDS = {"saving_throw", "onset", "maximum_duration"}

# Bold labels that should NOT be treated as ability names.
# These appear as <b> in sections but are structural labels, not abilities.
_NOT_ABILITY_NAMES = {
    "Related Groups",
    "Source",
}


# --------------------------------------------------------------------------- #
# Entry point A: Parse node sequence
# --------------------------------------------------------------------------- #


def parse_abilities_from_nodes(
    nodes,
    ability_type="ability",
    addon_labels=None,
    fxn_is_addon=None,
    fxn_post_process=None,
):
    """Parse a <br>-delimited sequence of BS4 nodes into ability objects.

    Abilities are delimited by <br> tags. Each starts with <b>Name</b>
    (optionally inside <a>), followed by action spans, traits, and
    addon fields.

    Args:
        nodes: list of BS4 nodes (Tag, NavigableString)
        ability_type: default ability_type for produced abilities
        addon_labels: custom set of addon labels (uses DEFAULT_ADDON_LABELS if None)
        fxn_is_addon: optional function(name) -> bool to override addon detection
        fxn_post_process: optional function(ability) for per-ability post-processing

    Returns: list of ability dicts, or None if no abilities found.
    """
    labels = addon_labels if addon_labels is not None else DEFAULT_ADDON_LABELS

    # Phase 1: Split into raw entries
    raw_entries = _split_nodes(nodes)
    if not raw_entries:
        return None

    # Phase 2: Merge addon fields into preceding ability
    merged = _merge_addons(raw_entries, labels, fxn_is_addon)

    # Phase 3: Build structured ability objects
    abilities = []
    for entry in merged:
        ability = _build_ability_from_entry(entry, ability_type, labels)
        if fxn_post_process:
            fxn_post_process(ability)
        abilities.append(ability)

    return abilities if abilities else None


# --------------------------------------------------------------------------- #
# Entry point B: Parse single ability from HTML
# --------------------------------------------------------------------------- #


def parse_ability_from_html(
    name,
    html_text,
    ability_type="ability",
    action_type=None,
    traits=None,
    link=None,
    addon_labels=None,
    break_results_on_any_bold=False,
    fxn_post_process=None,
):
    """Parse a single ability from its HTML text content.

    Extracts action type, traits, addon/bold fields, result blocks,
    and optionally detects affliction structure.

    Args:
        name: ability name (string)
        html_text: HTML description text (string)
        ability_type: classification (e.g., "interaction", "offensive")
        action_type: pre-extracted action_type object (optional)
        traits: pre-extracted traits list (optional)
        link: link on the ability name (optional)
        addon_labels: custom set of addon labels (uses DEFAULT_ADDON_LABELS if None)
        break_results_on_any_bold: feat-style result extraction
        fxn_post_process: optional function(ability) for post-processing

    Returns: ability dict.
    """
    labels = addon_labels if addon_labels is not None else DEFAULT_ADDON_LABELS

    ability = build_object("stat_block_section", "ability", name)
    ability["ability_type"] = ability_type
    if link:
        ability["link"] = link
    if action_type:
        ability["action_type"] = action_type
    if traits:
        ability["traits"] = traits

    bs = BeautifulSoup(html_text, "html.parser")

    # Extract action type if not pre-supplied
    if not action_type:
        remaining_html = str(bs)
        remaining_html, extracted_action = extract_action_type(remaining_html)
        if extracted_action:
            ability["action_type"] = extracted_action
            bs = BeautifulSoup(remaining_html, "html.parser")

    # Extract span traits
    _extract_span_traits(bs, ability)

    # Extract parenthesized traits if not pre-supplied
    if not traits:
        text = str(bs)
        text, extracted_traits = extract_starting_traits(text)
        if extracted_traits:
            ability.setdefault("traits", []).extend(extracted_traits)
            bs = BeautifulSoup(text, "html.parser")

    # Extract bold fields (addons)
    extract_bold_fields(ability, bs, labels, decompose=True)
    # Also extract Stage N fields
    _extract_stage_fields(ability, bs)

    # Convert saving_throw and damage from strings to structured arrays
    _normalize_structured_fields(ability)

    # Extract result blocks
    extract_result_blocks(ability, bs, break_on_any_bold=break_results_on_any_bold)

    # Extract links from remaining text
    links = get_links(bs, unwrap=True)
    if links:
        ability.setdefault("links", []).extend(links)

    # Set remaining text
    text = str(bs).strip()
    text = re.sub(r"^(<br/?>[\s]*)+", "", text)
    text = re.sub(r"(<br/?>[\s]*)+$", "", text)
    if text.strip():
        ability["text"] = text.strip()

    # Detect affliction
    _detect_affliction(ability)

    if fxn_post_process:
        fxn_post_process(ability)

    return ability


# --------------------------------------------------------------------------- #
# Internal: Node splitting
# --------------------------------------------------------------------------- #


def _split_nodes(nodes):
    """Split BS4 nodes into raw (name, link, text_nodes) tuples.

    Abilities are delimited by <br> tags. Each starts with <b>Name</b>
    or <a><b>Name</b></a>.
    """
    entries = []
    current = None  # (name, link, text_nodes)

    for node in nodes:
        if isinstance(node, Tag) and node.name == "br":
            if current:
                entries.append(current)
                current = None
            continue

        if isinstance(node, Tag) and node.name == "a" and node.find("b"):
            b = node.find("b")
            name = get_text(b).strip()
            if name in _NOT_ABILITY_NAMES:
                if current:
                    current[2].append(node)
                continue
            if current:
                entries.append(current)
            _name, link_obj = extract_link(node)
            current = (name, link_obj, [])
            continue

        if isinstance(node, Tag) and node.name == "b":
            name = get_text(node).strip()
            if name in _NOT_ABILITY_NAMES:
                if current:
                    current[2].append(node)
                continue
            if current:
                entries.append(current)
            current = (name, None, [])
            continue

        if current:
            current[2].append(node)

    if current:
        entries.append(current)
    return entries


def _merge_addons(entries, labels, fxn_is_addon=None):
    """Merge addon fields into preceding ability.

    Addon fields (Requirements, Effect, Trigger, etc.) and affliction
    fields (Saving Throw, Stage N, Onset) are attached to the preceding
    ability rather than treated as separate abilities.
    """
    merged = []
    for name, link, text_nodes in entries:
        lower_name = name.lower().strip()
        is_addon = False

        if fxn_is_addon and fxn_is_addon(name):
            is_addon = True
        elif name.strip() in labels:
            is_addon = True
        elif _STAGE_RE.match(name.strip()):
            is_addon = True

        if is_addon and merged:
            # Attach as addon to preceding ability
            merged[-1]["addon_entries"].append((name.strip(), text_nodes))
        else:
            merged.append(
                {
                    "name": name,
                    "link": link,
                    "text_nodes": text_nodes,
                    "addon_entries": [],
                }
            )
    return merged


# --------------------------------------------------------------------------- #
# Internal: Build ability from merged entry
# --------------------------------------------------------------------------- #


def _build_ability_from_entry(entry, ability_type, labels):
    """Build a structured ability object from a merged entry."""
    ability = build_object("stat_block_section", "ability", entry["name"])
    ability["ability_type"] = ability_type

    if entry["link"]:
        ability["link"] = entry["link"]

    # Reconstruct HTML from text nodes for processing
    raw_html = "".join(str(n) for n in entry["text_nodes"]).strip()

    if raw_html:
        # Extract traits first — they may appear before the action span
        # e.g., "(divine, void) [free-action]"
        remaining_html, traits = extract_starting_traits(raw_html.strip())
        if traits:
            ability["traits"] = traits

        # Extract action type from spans
        remaining_text, action = extract_action_type(remaining_html.strip())
        if action:
            ability["action_type"] = action

        # Extract links from remaining text
        if remaining_text.strip():
            ab_bs = BeautifulSoup(remaining_text, "html.parser")
            links = get_links(ab_bs, unwrap=True)
            if links:
                ability.setdefault("links", []).extend(links)
            final_text = str(ab_bs).strip()
            if final_text:
                ability["text"] = final_text

    # Process addon entries
    for addon_name, addon_nodes in entry["addon_entries"]:
        _apply_addon(ability, addon_name, addon_nodes)

    # Detect affliction
    _detect_affliction(ability)

    return ability


def _apply_addon(ability, addon_name, addon_nodes):
    """Apply an addon entry to an ability."""
    value_html = "".join(str(n) for n in addon_nodes).strip()
    if value_html.endswith(";"):
        value_html = value_html[:-1].strip()

    # Extract links from addon value
    ab_bs = BeautifulSoup(value_html, "html.parser")
    links = get_links(ab_bs, unwrap=True)
    if links:
        ability.setdefault("links", []).extend(links)
    value = str(ab_bs).strip()

    # Normalize key
    if _STAGE_RE.match(addon_name):
        # Stage N → add to stages array
        stage = {
            "type": "stat_block_section",
            "subtype": "affliction_stage",
            "name": addon_name,
        }
        if value:
            stage["text"] = value
        ability.setdefault("stages", []).append(stage)
    elif addon_name == "Saving Throw":
        ability["saving_throw"] = [_parse_save_dc(value)]
    elif addon_name == "Damage":
        ability["damage"] = _parse_damage(value)
    else:
        key = addon_name.lower().replace(" ", "_")
        # Standard normalizations
        if key == "requirements":
            key = "requirement"
        elif key == "prerequisites":
            key = "prerequisite"
        if value:
            ability[key] = value


def _normalize_structured_fields(ability):
    """Convert saving_throw and damage from strings to structured arrays.

    extract_bold_fields produces strings, but the schema requires arrays
    of save_dc / attack_damage objects.
    """
    if "saving_throw" in ability and isinstance(ability["saving_throw"], str):
        ability["saving_throw"] = [_parse_save_dc(ability["saving_throw"])]
    if "damage" in ability and isinstance(ability["damage"], str):
        ability["damage"] = _parse_damage(ability["damage"])


def _parse_save_dc(text):
    """Parse a saving throw string into a save_dc object.

    Tries structured parsing (DC + save type), falls back to minimal
    object with just the text for freeform descriptions.
    """
    if not text:
        return {"type": "stat_block_section", "subtype": "save_dc", "text": ""}
    if "DC" in text:
        try:
            return universal_handle_save_dc(text)
        except (AssertionError, ValueError):
            pass
    # Fallback: minimal object with text
    save_dc = {"type": "stat_block_section", "subtype": "save_dc", "text": text}
    # Try to extract save type from common patterns
    _SAVE_TYPES = {
        "Fortitude": "Fort",
        "Fort": "Fort",
        "Reflex": "Ref",
        "Ref": "Ref",
        "Will": "Will",
    }
    for name, abbrev in _SAVE_TYPES.items():
        if name in text:
            save_dc["save_type"] = abbrev
            break
    return save_dc


def _parse_damage(text):
    """Parse a damage string into an array of attack_damage objects.

    Tries structured parsing (dice formula + type), falls back to
    minimal object with the text as effect.
    """
    if not text:
        return []
    # Try to import and use the creature parser's damage parser
    try:
        from pfsrd2.creatures import parse_attack_damage

        return parse_attack_damage(text)
    except (ImportError, AssertionError, Exception):
        pass
    # Fallback: single object with text as effect
    return [
        {
            "type": "stat_block_section",
            "subtype": "attack_damage",
            "effect": text,
        }
    ]


# --------------------------------------------------------------------------- #
# Internal: Span trait extraction
# --------------------------------------------------------------------------- #


def _extract_span_traits(bs, ability):
    """Extract traits from <span class="trait*"> elements."""
    traits = []
    for span in list(bs.find_all("span")):
        classes = span.get("class", [])
        if any("trait" in c for c in classes):
            a = span.find("a")
            if a:
                name, trait_link = extract_link(a)
                trait = build_object(
                    "stat_block_section", "trait", name.strip()
                )
                if trait_link:
                    trait["link"] = trait_link
                traits.append(trait)
            span.decompose()
    # Also remove letter-spacing separator spans
    for span in list(bs.find_all("span", style=lambda s: s and "letter-spacing" in s)):
        span.decompose()
    if traits:
        ability.setdefault("traits", []).extend(traits)


# --------------------------------------------------------------------------- #
# Internal: Stage field extraction (for parse_ability_from_html path)
# --------------------------------------------------------------------------- #


def _extract_stage_fields(ability, bs):
    """Extract Stage N bold fields from BeautifulSoup.

    extract_bold_fields doesn't handle Stage N (regex pattern, not in label set).
    This function handles them separately.
    """
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if not _STAGE_RE.match(label):
            continue
        # Collect value nodes until next <b>
        parts = []
        nodes_to_remove = []
        node = bold.next_sibling
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

        stage = {
            "type": "stat_block_section",
            "subtype": "affliction_stage",
            "name": label,
        }
        if value:
            stage["text"] = value
        ability.setdefault("stages", []).append(stage)

        # Remove extracted nodes
        for n in nodes_to_remove:
            n.extract()
        bold.decompose()


# --------------------------------------------------------------------------- #
# Internal: Affliction detection
# --------------------------------------------------------------------------- #


def _detect_affliction(ability):
    """Detect if an ability is actually an affliction and set ability_type.

    An ability is an affliction if it has a saving_throw field AND
    at least one stage. When detected, ability_type is set to "affliction".
    """
    has_saving_throw = "saving_throw" in ability
    has_stages = bool(ability.get("stages"))

    if has_saving_throw and has_stages:
        ability["ability_type"] = "affliction"
    elif has_saving_throw or has_stages:
        # Partial affliction — still flag it
        ability["ability_type"] = "affliction"
