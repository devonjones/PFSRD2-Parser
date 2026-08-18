import re
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, NavigableString, Tag

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def split_maintain_parens(text, split, parenleft="(", parenright=")"):
    parts = text.split(split)
    newparts = []
    while len(parts) > 0:
        part = parts.pop(0)
        if part.find(parenleft) > -1 and part.rfind(parenright) < part.rfind(parenleft):
            newpart = part
            while newpart.find(parenleft) > -1 and newpart.rfind(parenright) < newpart.rfind(
                parenleft
            ):
                newpart = newpart + split + parts.pop(0)
            newparts.append(newpart)
        else:
            newparts.append(part)
    return [p.strip() for p in newparts]


def split_comma_and_semicolon(text, parenleft="(", parenright=")"):
    parts = [
        split_maintain_parens(t, ",", parenleft, parenright)
        for t in split_maintain_parens(text, ";", parenleft, parenright)
    ]
    return list(filter(lambda e: e != "", [item for sublist in parts for item in sublist]))


def filter_end(text, tokens):
    while True:
        text = text.strip()
        testtext = text
        for token in tokens:
            if text.endswith(token):
                flen = len(token) * -1
                text = text[:flen]
        if testtext == text:
            return text


# Single source of truth for mojibake / entity replacements.
# Each tuple is (broken_sequence, correct_character).
_ENTITY_REPLACEMENTS = [
    ("\u00c2\u00ba", "\u00ba"),  # º (degree/ordinal)
    ("\u00c3\u0097", "\u00d7"),  # × (multiplication sign)
    ("\u00e2\u0080\u0091", "\u2011"),  # ‑ (non-breaking hyphen)
    ("\u00e2\u0080\u0093", "\u2013"),  # – (en-dash)
    ("\u00e2\u0080\u0094", "\u2014"),  # — (em-dash)
    ("\u00e2\u0080\u0098", "\u2018"),  # ' (left single quote)
    ("\u00e2\u0080\u0099", "\u2019"),  # ' (right single quote)
    # Note: left/right double quotes use \u201c/\u201d escape sequences rather than
    # literal curly quotes to avoid a triple-quote parsing bug (see PR #34).
    ("\u00e2\u0080\u009c", "\u201c"),  # \u201c (left double quote)
    ("\u00e2\u0080\u009d", "\u201d"),  # \u201d (right double quote)
    ("\u00e2\u0080\u00a6", "\u2026"),  # … (ellipsis)
    ("%5C", "\\"),
    ("&amp;", "&"),
    ("\u00ca\u00bc", "\u2019"),  # ' (was u02BC)
    ("\u00c2\u00a0", " "),
    ("\u00a0", " "),
    # HTML entity encoded variants (BeautifulSoup decodes &acirc;&#128;&#148; etc.)
    ("\u00e2\u20ac\u201d", "\u2014"),  # — (em-dash from HTML entities)
    ("\u00e2\u20ac\u201c", "\u2013"),  # – (en-dash from HTML entities)
    ("\u00e2\u20ac\u2122", "\u2019"),  # ' (right single quote from HTML entities)
    ("\u00e2\u20ac\u0153", "\u201c"),  # " (left double quote from HTML entities)
    ("\u00e2\u20ac\u009d", "\u201d"),  # " (right double quote from HTML entities)
]


def _apply_replacements(text):
    """Apply entity replacements to a string without newline normalization."""
    for old, new in _ENTITY_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def filter_entities(text):
    text = _apply_replacements(text)
    text = " ".join([part.strip() for part in text.split("\n")])
    return text


def recursive_filter_entities(obj):
    """Recursively apply entity replacements to all string values in a nested structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                obj[key] = _apply_replacements(value)
            elif isinstance(value, dict | list):
                recursive_filter_entities(value)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                obj[i] = _apply_replacements(item)
            elif isinstance(item, dict | list):
                recursive_filter_entities(item)


def log_element(fn):
    fp = open(fn, "a+")

    def log_e(element):
        fp.write(element)
        fp.write("\n")

    return log_e


def clear_tags(text, taglist):
    bs = BeautifulSoup(text, "html.parser")
    for tag in taglist:
        for t in bs.find_all(tag):
            t.replace_with(t.get_text())
    return filter_entities(str(bs))


def clear_end_whitespace(text):
    bs = BeautifulSoup(text, "html.parser")
    children = list(bs.children)
    while len(children) > 0 and children[-1].name == "br":
        children.pop()
    text = "".join([str(c) for c in children]).strip()
    return text


def find_list(text, elements):
    for element in elements:
        if text.find(element) > -1:
            return element
    return False


def is_tag_named(element, taglist):
    if type(element) != Tag:
        return False
    elif element.name in taglist:
        return True
    return False


def has_name(tag, name):
    return bool(hasattr(tag, "name") and tag.name == name)


def get_text(detail):
    return "".join(detail.findAll(text=True))


def bs_pop_spaces(children):
    clean = False
    while not clean:
        testval = children[0]
        if type(testval) == Tag or testval.strip() != "":
            clean = True
        else:
            children.pop(0)


def get_unique_tag_set(text):
    bs = BeautifulSoup(text, "html.parser")
    return {tag.name for tag in bs.find_all()}


def split_on_tag(text, tag):
    bs = BeautifulSoup(text, "html.parser")
    parts = bs.findAll(tag)
    for part in parts:
        part.insert_after("|")
        part.unwrap()
    return str(bs).split("|")


def clear_garbage(text):
    if type(text) == list:
        text = "".join(text).strip()
    bs = BeautifulSoup(text, "html.parser")
    children = list(bs.children)
    while children and is_tag_named(children[0], ["br", "hr"]):
        children.pop(0).decompose()
    while children and is_tag_named(children[-1], ["br", "hr"]):
        children.pop().decompose()
    return str(bs)


def content_filter(soup, hr_recursive=True):
    """Remove navigation elements before <hr> and unwrap the content span.

    Standard pre-filter for HTML5 AoN pages. Strips nav before first <hr>,
    then unwraps the content span that contains the h1 title.

    Args:
        soup: BeautifulSoup object to filter
        hr_recursive: If True (default), find any <hr> in main. If False,
            only find direct-child <hr> tags (needed for equipment HTML
            where nav spans contain nested <hr> tags).
    """
    main = soup.find(id="main")
    if not main:
        return
    hr = main.find("hr", recursive=hr_recursive)
    if hr:
        for sibling in list(hr.previous_siblings):
            sibling.extract()
        hr.extract()
    for span in main.find_all("span", recursive=False):
        if span.find("h1"):
            span.unwrap()
            break


def is_empty(value):
    """Check if a value is empty (None, blank string, empty list/dict).

    Returns False for 0 and False (non-empty values).
    """
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return isinstance(value, list | dict) and len(value) == 0


def remove_empty_fields(obj):
    """Recursively remove fields with empty values ("", None, [], {})."""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            value = obj[key]
            remove_empty_fields(value)
            if is_empty(value):
                del obj[key]
    elif isinstance(obj, list):
        for item in obj:
            remove_empty_fields(item)
        obj[:] = [item for item in obj if not is_empty(item)]


def strip_block_tags(struct, extra_tags=None):
    """Pre-strip block-level HTML tags before markdown validation.

    Always strips: div, p, nethys-search, margin-left spans, corrupted tags (% or #).
    Pass extra_tags (e.g. ["u", "h2", "h3"]) for parser-specific additional tags.
    """
    for k, v in struct.items():
        if isinstance(v, dict):
            strip_block_tags(v, extra_tags)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    strip_block_tags(item, extra_tags)
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
            if extra_tags:
                for tag_name in extra_tags:
                    for tag in bs.find_all(tag_name):
                        changed = True
                        tag.unwrap()
            if changed:
                struct[k] = str(bs)


def extract_modifier(text):
    """Extract parenthesized modifier from text.

    Returns (text_without_parens, modifier_string) or (text, None) if no modifier.
    """
    if text.find("(") > -1:
        parts = text.split("(", 1)
        assert len(parts) == 2
        base = [parts.pop(0)]
        newparts = parts.pop(0).split(")", 1)
        modifier = newparts.pop(0).strip()
        base.extend(newparts)
        return " ".join([b.strip() for b in base]).strip(), modifier
    else:
        return text, None


def split_stat_block_line(line):
    """Split a stat block line by semicolons and commas, respecting parentheses."""
    line = line.strip()
    parts = split_maintain_parens(line, ";")
    newparts = []
    for part in parts:
        newparts.extend(split_maintain_parens(part, ","))
    return [p.strip() for p in newparts]


def rebuilt_split_modifiers(parts):
    """Rejoin comma-split parts that were inside parentheses."""
    newparts = []
    while len(parts) > 0:
        part = parts.pop(0)
        if part.find("(") > 0:
            newpart = part
            while newpart.find(")") == -1:
                newpart = newpart + ", " + parts.pop(0)
            newparts.append(newpart)
        else:
            newparts.append(part)
    return newparts


def handle_trait_value(trait, prefix_traits=()):
    """Split a value off a trait name: "thrown 10 feet" -> name "thrown", value "10 feet".

    Traits that carry a magnitude are written as one string in the source, and
    the traits table only knows the bare name. Shared because every stat block
    with valued traits needs it — equipment, creatures and hazards all do.

    prefix_traits names traits that must split on the prefix rather than on
    whatever the numeric regex would find ("versatile B", and "range", whose
    creature form keeps the word "increment" in the value). They are matched
    first, and passing any switches off the blind split-on-first-space
    fallback.
    """
    original_name = trait["name"]
    for prefix in prefix_traits:
        if original_name.startswith(prefix + " "):
            trait["value"] = original_name[len(prefix) + 1 :]
            trait["name"] = prefix
            return

    # Only the word "range" comes off: the traits table knows "range", and
    # "increment" belongs to the value ("range increment 400 feet" -> value
    # "increment 400 feet"). Both equipment and creatures publish it this way.
    if original_name.lower().startswith("range increment"):
        trait["name"] = "range"
        trait["value"] = original_name[len("range ") :].strip()
        return

    m = re.search(r"(.*) (\+?d?[0-9]+.*)", trait["name"])
    if m:
        name, value = m.groups()
        trait["name"] = name.strip()
        trait["value"] = value.strip()
        return
    if prefix_traits:
        # Callers that name their prefixes want only those splits; a blind
        # split on the first space would invent traits.
        return
    if " " in trait["name"]:
        parts = trait["name"].split(" ", 1)
        trait["name"] = parts[0].strip()
        trait["value"] = parts[1].strip()


def flatten_field_links(value, links_out):
    """Strip a field value down to plain text, collecting its links.

    Links become structured references and action spans are reduced to their
    bracket text, because the markdown pass accepts no tags.

    Returns the flattened string; discovered links are appended to links_out.
    """
    from universal.universal import get_links  # circular import at module level

    bs = BeautifulSoup(value, "html.parser")
    links = get_links(bs, unwrap=True)
    if links:
        links_out.extend(links)
    for span in bs.find_all("span", {"class": "action"}):
        span.unwrap()
    return str(bs).strip()


def split_list(text, splits):
    """Split text on each separator in turn ("a plus b and c" -> three parts)."""
    elements = text.split(splits[0])
    newelements = []
    if len(splits) > 1:
        for element in elements:
            newelements.extend(split_list(element, splits[1:]))
    else:
        newelements.extend(elements)
    return newelements


def parse_defense_line(text, subtype):
    """Split an Immunities/Weaknesses/Resistances line into protection objects.

    "cold 5, fire 10" -> [{name: "cold", value: 5}, {name: "fire", value: 10}].
    Shared because every stat block that has these publishes them identically —
    creatures and hazards both parse the same line.
    """
    # One trailing separator is routine in the source; two in a row means the
    # line is malformed, so leave the second for the empty-entry assert.
    text = text.strip()
    if text[-1:] in ",;":
        text = text[:-1].strip()
    entries = []
    for part in rebuilt_split_modifiers(split_stat_block_line(text)):
        assert part and part.strip(), (
            f"Empty entry in {subtype} line {text!r} — two separators with nothing "
            "between them, which means the line is malformed"
        )
        entry = {"type": "stat_block_section", "subtype": subtype, "name": part.strip()}
        parse_section_modifiers(entry, "name")
        parse_section_value(entry, "name")
        entries.append(entry)
    return entries


def parse_section_value(section, key):
    """Split a trailing number off a name: "cold 5" -> name "cold", value 5.

    Lives here rather than in a content-type module because every stat block
    with typed defences needs it — creatures and hazards both.
    """
    text = section[key]
    m = re.search(r"(.*) (\d*)$", text)
    value = None
    if m:
        text, value = m.groups()
    if value:
        section["value"] = int(value)
    section[key] = text
    return section


def parse_section_modifiers(section, key):
    """Extract parenthesized modifier from a section field and build modifier objects."""
    # Deferred import to avoid circular dependency: universal.universal imports from utils
    from universal.universal import build_objects, link_modifiers

    text = section[key]
    text, modifier = extract_modifier(text)
    if modifier:
        # TODO: fix []
        section["modifiers"] = link_modifiers(
            build_objects("stat_block_section", "modifier", [modifier])
        )
    section[key] = text
    return section


def extract_pfs_availability(bs):
    """Extract PFS availability from an img tag in the content.

    PFS availability appears as: <img alt="PFS Standard" ...>
    Valid values: Standard, Limited, Restricted.

    Removes the img (and its parent PFS link/span if empty after removal)
    from the soup.

    Returns the availability string, or "Standard" if no PFS img found.
    """
    pfs_img = bs.find("img", alt=lambda s: s and s.startswith("PFS"))
    if not pfs_img:
        return "Standard"

    pfs_alt = pfs_img.get("alt", "")
    match = re.match(r"PFS\s+(\w+)", pfs_alt, re.IGNORECASE)
    assert match, f"PFS img found but alt text doesn't match expected format: '{pfs_alt}'"
    availability = match.group(1).capitalize()
    assert availability in (
        "Standard",
        "Limited",
        "Restricted",
    ), f"Unknown PFS availability: '{availability}' (from alt text: '{pfs_alt}')"

    # Remove the img and clean up empty parent wrappers
    parent = pfs_img.parent
    pfs_img.decompose()
    # If parent is now empty (span or a wrapping just the icon), remove it too
    while parent and parent.name in ("span", "a") and not parent.get_text(strip=True):
        next_parent = parent.parent
        parent.decompose()
        parent = next_parent

    return availability


def normalize_pfs_to_object(struct):
    """Ensure struct['pfs'] is a structured object, not a string.

    Converts string pfs values to the standard object form.
    No-op if already an object. Asserts if pfs key is missing.
    """
    pfs = struct.get("pfs")
    assert pfs is not None, "struct['pfs'] must be set before calling normalize_pfs_to_object"
    if isinstance(pfs, str):
        struct["pfs"] = {
            "type": "stat_block_section",
            "subtype": "pfs",
            "availability": pfs,
        }


def _collect_pfs_note_text(u_tag):
    """Traverse siblings after a PFS Note <u> wrapper to collect note text.

    Stops at <br><br>, <hr>, or next <b> tag.

    Returns:
        Tuple of (note_text, elements_to_remove) where note_text is the
        cleaned text string and elements_to_remove includes the u_tag
        and all consumed sibling nodes.
    """
    note_parts = []
    elements_to_remove = [u_tag]
    current = u_tag.next_sibling
    while current:
        if isinstance(current, Tag) and current.name == "b":
            break
        if isinstance(current, Tag) and current.name == "hr":
            break
        if isinstance(current, Tag) and current.name == "br":
            next_sib = current.next_sibling
            if isinstance(next_sib, Tag) and next_sib.name in ("br", "hr"):
                elements_to_remove.append(current)
                if next_sib.name == "br":
                    elements_to_remove.append(next_sib)
                break
            elements_to_remove.append(current)
            current = current.next_sibling
            continue
        note_parts.append(str(current))
        elements_to_remove.append(current)
        current = current.next_sibling

    note_html = "".join(note_parts).strip()
    if note_html:
        note_soup = BeautifulSoup(note_html, "html.parser")
        note_text = filter_entities(note_soup.get_text())
        # Strip leading colons (HTML artifact in some files)
        note_text = note_text.lstrip(":").strip()
    else:
        note_text = None

    return note_text, elements_to_remove


def extract_pfs_note(bs, struct):
    """Extract PFS Note from HTML and convert pfs field to structured object.

    PFS Notes appear as: <u><a href="PFS.aspx"><b><i>PFS Note</i></b></a></u> note text<br>

    Converts struct["pfs"] from a string to:
        {"type": "stat_block_section", "subtype": "pfs", "availability": "Standard", "note": "..."}

    If no PFS Note is found, leaves struct["pfs"] unchanged.
    Removes extracted elements from the soup.
    """
    pfs_note_bold = None
    for b in bs.find_all("b"):
        if "PFS Note" in b.get_text():
            pfs_note_bold = b
            break

    if not pfs_note_bold:
        return

    u_tag = pfs_note_bold.find_parent("u")
    assert u_tag, (
        "PFS Note <b> tag found without expected <u> wrapper. "
        "Expected structure: <u><a><b><i>PFS Note</i></b></a></u>"
    )

    note_text, elements_to_remove = _collect_pfs_note_text(u_tag)

    for elem in elements_to_remove:
        if isinstance(elem, Tag):
            elem.decompose()
        elif isinstance(elem, NavigableString):
            elem.extract()

    assert note_text, "PFS Note tag found and removed from HTML but yielded no text"

    pfs_availability = struct["pfs"]
    assert isinstance(
        pfs_availability, str
    ), f"Expected pfs to be a string at this point, got {type(pfs_availability)}"
    struct["pfs"] = {
        "type": "stat_block_section",
        "subtype": "pfs",
        "availability": pfs_availability,
        "note": note_text,
    }


def sidebar_filter(soup):
    """Unwrap sidebar-nofloat divs. sidebarlook is handled by handle_alternate_link."""
    for div in soup.find_all("div", {"class": "sidebar-nofloat"}):
        div.unwrap()


def plain_text(value):
    """Markup in, visible text out."""
    return get_text(BeautifulSoup(value, "html.parser")).strip()


# Elements a degree of success cannot be part of. Deliberately a small,
# explicit list rather than "not in _INLINE_TAGS": a tag nobody anticipated
# should be absorbed and show up in review, not silently truncate a degree.
_BLOCK_TAGS = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "dl", "hr", "div"}
)


def _starts_a_blank_line(br):
    """True when this <br/> is the first of a consecutive pair.

    Whitespace between them is the source pretty-printing, not content.
    """
    node = br.next_sibling
    while node is not None and isinstance(node, NavigableString) and not node.strip():
        node = node.next_sibling
    return getattr(node, "name", None) == "br"


def nodes_after(bold, stop=None, stop_at_br=False, stop_at_blank_line=False, stop_at_block=False):
    """Sibling nodes up to the next bold label — a label's value run.

    `stop` overrides which bold ends the run. It receives each <b> node and
    returns True to stop. The default stops at every bold, which is what a
    stat-block field wants; extract_result_blocks passes a predicate because a
    degree's text may legitimately contain a bold that is not another degree.

    A bold the predicate does NOT stop on is returned like any other node, so
    a caller that extracts the returned list removes that bold from the tree
    as well. The callers that extract rely on that: the value they store and
    the nodes they remove have to be the same set. (Seven call sites now, not
    the two this said when it was written.)

    `stop_at_br` adds <br/> as a terminator. The bold terminator stays live:
    the run ends at whichever comes first. It is a separate argument rather
    than something `stop` could express, because `stop` is only consulted for
    <b> nodes and a <br/> never reaches it, and widening it would change the
    contract for every caller.

    Afflictions want it: a field's value never spans a break in that source, so
    without it the last field in a block absorbs the description that follows.
    Hazards do NOT — their routines deliberately keep prose published after the
    last degree (see pfsrd2/hazard.py::_extract_routine_results), so breaking
    there would truncate them.

    `stop_at_blank_line` ends the run at a PARAGRAPH break -- a <br/> whose
    next non-whitespace sibling is another <br/>. A single <br/> separates the
    fields inside a block and must not end anything; two in a row is the source
    saying this block is over.

    Degrees want it. A degree of success is one sentence about one save
    outcome, and it never spans a paragraph. Without this the LAST degree has
    no terminator at all -- there is no bold after it -- so it swallowed
    whatever the page printed next: an affliction's whole stat block into
    purple_worm_sting's critical failure, a separate Depart ability into
    summon_stampede's. Both were shipped that way and degree_effects then read
    the buried dice as the degree's own damage.

    `stop_at_block` ends the run at a block-level element. A degree is one
    sentence about one save outcome; it cannot contain a heading, a table or a
    list. unfathomable_song says "Roll 1d4+1 on the table below." and then
    prints an <h2> and the table itself, all of which landed inside
    critical_failure. A paragraph break would not have caught it, because there
    is none -- the block element IS the separator.

    The loop tests `is not None`, not `while node:` — an empty NavigableString
    is falsy, so the inlined copies this replaces ended the run early on one
    and truncated the value silently. Neither html.parser nor lxml emits one —
    parse_universal uses lxml — so this is hardening rather than a fix for
    observed data.
    """
    nodes = []
    node = bold.next_sibling
    while node is not None:
        name = getattr(node, "name", None)
        if name == "b":
            if stop is None or stop(node):
                break
        elif name == "br":
            if stop_at_br or (stop_at_blank_line and _starts_a_blank_line(node)):
                break
        elif stop_at_block and name in _BLOCK_TAGS:
            break
        nodes.append(node)
        node = node.next_sibling
    return nodes


def flatten_fields(section, keys):
    """Flatten extracted field values to plain text, keeping their links.

    Links become structured references and action spans are unwrapped to their
    bracket text, since the markdown pass accepts no tags in a field value.
    """
    for key in keys:
        value = section.get(key)
        if not isinstance(value, str) or "<" not in value:
            continue
        section[key] = flatten_field_links(value, section.setdefault("links", []))
