import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, Tag

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
    ("\u00e2\u0080\u009c", "\u201c"),  # " (left double quote)
    ("\u00e2\u0080\u009d", "\u201d"),  # " (right double quote)
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


def filter_entities(text):
    for old, new in _ENTITY_REPLACEMENTS:
        text = text.replace(old, new)
    text = " ".join([part.strip() for part in text.split("\n")])
    return text


def recursive_filter_entities(obj):
    """Recursively apply entity replacements to all string values in a nested structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                for old, new in _ENTITY_REPLACEMENTS:
                    value = value.replace(old, new)
                obj[key] = value
            elif isinstance(value, dict | list):
                recursive_filter_entities(value)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                for old, new in _ENTITY_REPLACEMENTS:
                    item = item.replace(old, new)
                obj[i] = item
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
