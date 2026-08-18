import re
import sys
from hashlib import md5
from pprint import pprint
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from pfsrd2.constants import (
    DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK,
    DEGREE_EFFECT_NOT_THE_SUBJECTS,
)
from pfsrd2.enrichment.regex_extractor import extract_all
from universal.utils import (
    clear_end_whitespace,
    clear_tags,
    filter_entities,
    get_text,
    has_name,
    nodes_after,
    split_comma_and_semicolon,
)

# FULLWIDTH COMMA = ，


class Heading:
    def __init__(self, level, name, subname=None):
        self.level = level
        self._handle_name(name)
        self.subname = subname
        self.details = []

    def _handle_name(self, name):
        try:
            bs = BeautifulSoup(str(name), "html.parser")
            children = list(bs.children)
            assert len(children) == 1, bs
            top = children[0]
            self.name = get_text(bs).strip()
            if hasattr(top, "contents"):
                self.name_html = "".join([str(i) for i in top])
                top.clear()
            else:
                self.name_html = str(top)
                top.extract()
            self.name_tag = str(bs)
        except Exception as e:
            print(name)
            raise e

    def __repr__(self):
        if self.subname:
            return f"<Heading {self.level}:{self.name} ({self.subname}) {self.details}>"
        else:
            return f"<Heading {self.level}:{self.name} {self.details}>"


def href_filter(soup):
    for href in soup.findAll("a"):
        if not href.has_attr("href"):
            href.decompose()
            continue
        if ".aspx?ID=" in href["href"]:
            o = urlparse(href["href"])
            for a in list(href.attrs):
                del href[a]
            href["game-obj"] = o.path.split(".")[0].lstrip("/")
            q = parse_qs(o.query)
            for k, vs in q.items():
                for v in vs:
                    href[k.lower() if k != "ID" else "aonid"] = v
        elif href["href"] == "javascript:void(0);":
            body = BeautifulSoup(href.renderContents(), "lxml")
            if len(body.contents) == 1:
                href.replaceWith(body.contents[0])
            else:
                href.replaceWith(body.renderContents())


def span_formatting_filter(soup):
    spans = soup.findAll("span")
    for span in spans:
        if span.has_attr("style") and len(list(span.children)) == 1:
            text = get_text(span)
            if len(text.strip()) == 0:
                span.decompose()


def noop_pass(details):
    retdetails = []
    for detail in details:
        # TODO: Get rid of the following line
        # if not str(detail).strip() == "":
        retdetails.append(detail)
    return retdetails


def entity_pass(details):
    for detail in details:
        if "sections" in detail:
            entity_pass(detail["sections"])
        if "text" in detail:
            detail["text"] = filter_entities(detail["text"])
        if "name" in detail:
            detail["name"] = filter_entities(detail["name"])
    return details


def handle_alternate_link(details, allow_multiple=False):
    """Extract alternate link(s) from the first detail element.

    Args:
        details: List of detail elements (first is checked for version text).
        allow_multiple: If True, return array for multiple links, single dict
            for one link, None for no match. If False (default), assert exactly
            one link exists.

    Returns:
        Single alternate_link dict, list of dicts (if allow_multiple and >1),
        or None if no version text found.
    """
    if not details:
        return None
    d = details[0]
    if not isinstance(d, str):
        return None
    if "Legacy version" not in d and "Remastered version" not in d:
        return None
    details.pop(0)
    text, links = extract_links(d)
    assert links, f"Version text found but no links extracted: {d}"
    if "Legacy version" in d:
        alternate_type = "legacy"
    else:
        alternate_type = "remastered"
    if not allow_multiple:
        assert len(links) == 1, links
    result = []
    for link in links:
        alt = {
            "type": "alternate_link",
            "game-obj": link["game-obj"],
            "aonid": link["aonid"],
            "alternate_type": alternate_type,
        }
        result.append(alt)
    if len(result) == 1:
        return result[0]
    return result


def nethys_search_pass(details):
    for detail in details:
        if "text" in detail:
            detail["text"] = clear_end_whitespace(clear_tags(detail["text"], ["nethys-search"]))
        if "sections" in detail:
            nethys_search_pass(detail["sections"])
    return details


def title_pass(details, max_title):
    retdetails = []
    for detail in details:
        if has_name(detail, "h1") and max_title >= 1:
            subname = None
            after = []
            spans = detail.findAll("span")
            assert len(spans) < 2, f"Unexpected number of subtitles {spans}"
            if len(spans) == 1:
                obj = spans[0]
                if is_action(obj) or is_trait(obj):
                    after.append(obj.extract())
                else:
                    subname = "".join(obj.extract().strings).strip()
            img = img_details(detail)
            h = Heading(1, detail, subname)
            if img:
                h.details.extend(img)
            retdetails.append(h)
            retdetails.extend(after)
        elif has_name(detail, "h2") and max_title >= 2:
            details = img_details(detail)
            h = Heading(2, detail)
            h.details = details
            retdetails.append(h)
        else:
            retdetails.append(detail)
    return retdetails


def title_collapse_pass(details, level, add_statblocks=True):
    retdetails = []
    curr = None
    for detail in details:
        if isinstance(detail, Heading) and detail.level <= level:
            curr = None
            retdetails.append(detail)
        else:
            if curr:
                curr.details.append(detail)
            else:
                retdetails.append(detail)
        if isinstance(detail, Heading) and detail.level == level:
            curr = detail
    return retdetails


def subtitle_pass(details, max_title):
    retdetails = []
    for detail in details:
        if hasattr(detail, "name"):
            if issubclass(detail.__class__, Heading):
                detail.details = subtitle_pass(detail.details, max_title)
                retdetails.append(detail)
            elif has_name(detail, "h3") and max_title >= 3:
                sub = img_details(detail)
                h = Heading(3, detail)
                h.details = sub
                retdetails.append(h)
            elif has_name(detail, "h4") and max_title >= 4:
                sub = img_details(detail)
                h = Heading(4, detail)
                h.details = sub
                retdetails.append(h)
            elif has_name(detail, "span") and not is_trait(detail) and not is_action(detail):
                # Skip empty spans (common in HTML5 update)
                if not get_text(detail).strip():
                    continue
                try:
                    retdetails.append(span_to_heading(detail, 3))
                except IndexError as e:
                    pprint(detail)
                    raise (e)
            else:
                retdetails.append(detail)
        else:
            retdetails.append(detail)
    return retdetails


def subtitle_text_pass(details, max_title):
    retdetails = []
    prev = None
    for detail in details:
        try:
            if issubclass(detail.__class__, str):
                if not detail.strip():
                    continue
                bs = BeautifulSoup(detail, "html.parser")
                objs = list(bs.children)
                fo = ""
                while str(fo).strip() == "":
                    fo = objs.pop(0)
                if fo.name == "b" and get_text(fo) != "Source" and max_title > 2:
                    h = Heading(3, fo)
                    h.details = "".join([str(o) for o in objs])
                    retdetails.append(h)
                else:
                    retdetails.append(detail)
            else:
                retdetails.append(detail)
        except IndexError as e:
            pprint(prev)
            pprint(detail)
            raise (e)
        prev = detail
    return retdetails


def section_pass(struct):
    proclist = []
    if struct.__class__ == Heading:
        for d in struct.details:
            proclist.append(section_pass(d))
        oldstruct = struct
        struct = {
            # 'name': filter_name(oldstruct.name),
            "name": oldstruct.name_html,
            "type": "section",
            "sections": [],
        }
        if oldstruct.subname:
            struct["subname"] = oldstruct.subname
        if len(proclist) > 0:
            struct["sections"] = proclist
        struct = section_text_pass(struct)
    return struct


# Adds text to sections


def section_text_pass(struct):
    text = []
    newsections = []
    for item in struct.get("sections", []):
        if item.__class__ == Tag or item.__class__ == NavigableString:
            # Item is text, append it to the text list for attaching to an obj
            text.append(str(item))
        elif item.__class__ == str:
            text.append(item)
        else:
            newsections.append(item)
    if len(text) > 0:
        if "text" in struct:
            newsections.append(
                section_text_pass({"type": "section", "text": text.strip(), "sections": []})
            )
        else:
            struct["text"] = "".join(text)
    if len(newsections) > 0:
        struct["sections"] = newsections
    else:
        if "sections" in struct:
            struct["sections"] = []
    return struct


def text_pass(lines):
    newlines = []
    text = []
    for line in lines:
        if line.__class__ == Heading:
            if len(text) > 0:
                newlines.append("".join(text))
                text = []
            line.details = text_pass(line.details)
            newlines.append(line)
        elif line.__class__ == Tag or line.__class__ == NavigableString:
            text.append(str(line))
        else:
            raise AssertionError(line)
    if len(text) > 0:
        newlines.append("".join(text))
    return newlines


def parse_body(div, book=False, title=False, subtitle_text=False, max_title=5):
    lines = noop_pass(div.contents)
    lines = title_pass(lines, max_title)
    lines = subtitle_pass(lines, max_title)
    lines = text_pass(lines)
    if subtitle_text:
        lines = subtitle_text_pass(lines, max_title)
    if max_title >= 5:
        lines = title_collapse_pass(lines, 5, add_statblocks=False)
    if max_title >= 4:
        lines = title_collapse_pass(lines, 4, add_statblocks=False)
    if max_title >= 3:
        lines = title_collapse_pass(lines, 3, add_statblocks=False)
    if max_title >= 2:
        lines = title_collapse_pass(lines, 2)
    if max_title >= 1:
        lines = title_collapse_pass(lines, 1)
    newlines = []
    for line in lines:
        section = section_pass(line)
        newlines.append(section)
    return newlines


def parse_universal(
    filename,
    title=False,
    subtitle_text=False,
    max_title=5,
    cssclass="ctl00_MainContent_DetailedOutput",
    pre_filters=None,
):
    with open(filename) as fp:
        data = fp.read().replace("\n", "")
        soup = BeautifulSoup(data, "lxml")
        if pre_filters:
            for pre_filter in pre_filters:
                pre_filter(soup)
        href_filter(soup)
        span_formatting_filter(soup)
        content = soup.find(id=cssclass)
        if content:
            return parse_body(
                content, title=title, subtitle_text=subtitle_text, max_title=max_title
            )


def print_struct(top, level=0):
    if issubclass(top.__class__, list):
        print("[")
        for t in top:
            print_struct(t, level)
        print("]")
    if not top:
        return
    sys.stdout.write("".join(["-" for i in range(0, level)]))
    if top.__class__ == dict:
        if "name" in top:
            print("# " + top["name"])
        else:
            print("# <Anonymous>")
        if "sections" in top:
            for s in top["sections"]:
                print_struct(s, level + 2)
    elif issubclass(top.__class__, Heading):
        print("* " + top.name)
        for detail in top.details:
            print_struct(detail, level + 2)
    else:
        print("<text>")


def filter_name(name):
    name = name.strip()
    if name[-1] == ":":
        name = name[:-1]
    return name.strip()


def is_trait(span):
    if span.has_attr("class"):
        c = span["class"]
        if "".join(c).startswith("trait"):
            return True
    return False


def is_action(span):
    if span.has_attr("class"):
        c = span["class"]
        if "".join(c).startswith("action"):
            return True
    return False


def span_to_heading(span, level):
    def _handle_actions(span):
        subspans = span.findAll("span")
        if len(subspans) == 0:
            return
        for action in subspans:
            action = subspans[0]
            if not is_action(action):
                return
            if len(list(action.children)) == 0:
                return
            contents = " ".join([str(e) for e in action.contents]).strip()
            if contents == "" or (contents.startswith("[") and contents.endswith("]")):
                for c in action.contents:
                    c.extract()
            else:
                raise AssertionError(span)

    _handle_actions(span)
    details_text = "".join([str(i) for i in span.contents]).strip()
    details = list(BeautifulSoup(details_text, "html.parser").children)
    title = details.pop(0)
    h = Heading(level, title)
    h.details = details
    return h


def img_details(detail):
    if len(detail.findAll("img")) > 0:
        return detail.findAll("img")
    return []


def extract_link(a):
    assert a.name == "a"
    name = get_text(a)
    link = {"type": "link", "name": name.strip(), "alt": name.strip()}
    if a.has_attr("game-obj"):
        link["game-obj"] = a["game-obj"]
    if a.has_attr("aonid"):
        link["aonid"] = int(a["aonid"])
    if a.has_attr("href"):
        link["href"] = a["href"]
    return name, link


def extract_links(text):
    bs = BeautifulSoup(text.strip(), "html.parser")
    all_a = bs.find_all("a")
    links = []
    for a in all_a:
        _, link = extract_link(a)
        links.append(link)
        a.unwrap()
    return str(bs), links


def source_pass(struct, find_object_fxn):
    def _extract_source(section):
        if "text" in section:
            bs = BeautifulSoup(section["text"], "html.parser")
            children = list(bs.children)
            if children[0].name == "b" and get_text(children[0]) == "Source":
                children = [c for c in children if str(c).strip() != ""]
                children.pop(0)
                book = ""
                while str(book).strip() == "" and children:
                    book = children.pop(0)
                source = extract_source(book)
                if children[0].name == "sup":
                    sup = children.pop(0)
                    errata = extract_link(sup.find("a"))
                    source["errata"] = errata[1]
                if children[0].name == "br":
                    children.pop(0)
                section["text"] = "".join([str(c) for c in children])
                return [source]

    def propagate_sources(section, sources):
        if "sources" in section and not section["sources"]:
            del section["sources"]
        retval = _extract_source(section)
        if retval:
            sources = retval
        if "sources" in section:
            sources = section["sources"]
        else:
            section["sources"] = sources
        for s in section["sections"]:
            propagate_sources(s, sources)

    if "sources" not in struct:
        sb = find_object_fxn(struct)
        struct["sources"] = sb["sources"]
    sources = struct["sources"]
    for section in struct["sections"]:
        propagate_sources(section, sources)


def extract_source(obj):
    text, link = extract_link(obj)
    parts = text.split(" pg. ")
    name = parts.pop(0)
    source = {"type": "source", "name": name, "link": link}
    if len(parts) == 1:
        page = int(parts.pop(0))
        source["page"] = page
    return source


def extract_source_from_bs(bs):
    """Extract source from a BeautifulSoup object, modifying it in place.

    Finds <b>Source</b> followed by a book link (and optional errata sup),
    removes those elements from the soup, and returns the source dict.
    Returns None if no source found. Handles trailing comma between
    multiple sources and trailing <br> tags.
    """

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


RESULT_LABELS = {
    "Critical Success": "critical_success",
    "Success": "success",
    "Failure": "failure",
    "Critical Failure": "critical_failure",
}

# Derived, not retyped. Every site that carries, strips or link-scans the degree
# fields by name is a place a NEW degree field would be silently dropped —
# which is exactly how skill.py and monster_ability.py both lost
# degree_effects. No count here on purpose: it moved twice while this PR was
# open. `grep -rn 'critical_failure' --include='*.py' pfsrd2/ universal/`
# should return only RESULT_LABELS, the exemption keys, and the label_map
# below.
#
# One retyped copy survives on purpose: equipment.py's label_map, which maps
# the DISPLAY labels ("Critical Failure") rather than the field names, and is
# the equipment half of the same table RESULT_LABELS is. Merging the two is
# PFSRD2-Parser-qj3v's job, not this constant's.
DEGREE_FIELDS = tuple(RESULT_LABELS.values())

# For lists that carry or strip a degree WITH its structure. Link passes want
# DEGREE_FIELDS instead: degree_effects is a modelled array, not HTML with <a>
# tags in it.
DEGREE_FIELDS_WITH_EFFECTS = DEGREE_FIELDS + ("degree_effects",)


def _stops_at_a_result_label(node):
    """Only another degree ends a degree's run. Closes over nothing."""
    return get_text(node).strip() in RESULT_LABELS


def _continues_past_a_break(section, degree, bold):
    """True when this last degree owns the paragraph that follows it.

    Asserts rather than silently skipping if the pinned phrase is gone: the
    exemption was granted for a specific sentence, so an AoN rewrite has to be
    re-judged by a person instead of inheriting the exception.
    """
    key = (section.get("name"), degree)
    if key not in DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK:
        return False
    phrase, why = DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK[key]
    following = "".join(str(n) for n in nodes_after(bold, stop=None))
    assert phrase in following, (
        f"{key[0]!r} {key[1]} is exempt from the paragraph boundary because "
        f"{why}, but the phrase {phrase!r} that justified it is no longer in "
        "the text after the degree. Re-read it and update or remove the entry "
        "in constants.DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK."
    )
    return True


def extract_result_blocks(section, bs, break_on_any_bold=False):
    """Extract Critical Success/Success/Failure/Critical Failure from description.

    Also writes degree_effects onto `section` — see extract_degree_effects. A
    degree is a string, so what it says is modelled beside it.

    This function is ONE of the five degree-writers listed in
    extract_degree_effects, reached by feats, spells, and everything that goes
    via parse_ability_from_html.

    Args:
        section: dict to store result keys into (e.g. critical_success,
            failure) plus degree_effects when a degree's text carries damage
        bs: BeautifulSoup object to extract from (modified in place)
        break_on_any_bold: If True, stop collecting at ANY <b> tag (feat behavior).
            If False (default), only stop at <b> tags that are result labels
            (skill/spell behavior - allows non-result bolds within result text).
    """
    # Only the LAST degree needs a paragraph/block terminator. A middle degree
    # already has one -- the next degree's bold -- and everything between the
    # two is unambiguously its own content. Applying the boundary to a middle
    # degree CUT that content: tanglecurse's Failure says "roll 1d4 and consult
    # the results below" and the results sit between it and Critical Failure,
    # so the degree was left pointing at nothing.
    degree_bolds = [b for b in bs.find_all("b") if get_text(b).strip() in RESULT_LABELS]
    last_degree = degree_bolds[-1] if degree_bolds else None

    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if label not in RESULT_LABELS:
            continue
        key = RESULT_LABELS[label]
        is_last = bold is last_degree
        # One walk, used for both the value and the extraction. These were two
        # separate loops and they had ALREADY drifted: the value loop tested
        # `while node:` while the extraction loop had no such test, so the
        # stored value could describe less than what was removed from the soup.
        # The last degree also stops at ANY bold. After the last degree a new
        # bold introduces a new thing -- an affliction's stat block, a
        # **Special** note -- and there is not always a <br/><br/> in front of
        # it: curse_of_death runs "<b>Critical Failure</b> ...at stage 2.
        # <b>Curse of Death</b>" with no separator at all. A middle degree
        # keeps the narrower predicate, because a bold between two degrees can
        # legitimately be part of the first one. The last degrees that carry a
        # bold are a handful corpus-wide and every one of them should be cut
        # here; curse_of_death is the worked example above. A count sat here
        # through two rounds and was wrong both times, so it is gone rather
        # than re-measured a third time -- nothing checks a number in a
        # comment.
        # A handful of last degrees continue past their paragraph break instead
        # of returning to the parent object. The markup is identical, so they
        # are named in constants.py; see _continues_past_a_break.
        bounded = is_last and not _continues_past_a_break(section, key, bold)
        # A degree's text may legitimately contain a bold that is not another
        # degree, so a middle degree only stops at another degree's label. The
        # last degree, and any caller that asked for it, stops at every bold --
        # which is nodes_after's default, so it is None rather than a predicate
        # spelled out longhand.
        value_nodes = nodes_after(
            bold,
            stop=None if (is_last or break_on_any_bold) else _stops_at_a_result_label,
            stop_at_paragraph=bounded,
        )
        value = "".join(str(n) for n in value_nodes).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        section[key] = value
        for node in value_nodes:
            node.extract()
        bold.decompose()

    # The degrees are final here. This is the one place feats, spells and
    # every ability that goes through parse_ability_from_html write them, so
    # modelling them here is what keeps degree_effects from being a field that
    # exists for some parsers and silently not for others.
    extract_degree_effects(section)


def extract_degree_effects(ability, owner_name=None):
    """Model what a degree's text says, since the degree itself is a string.

    Before the degrees were folded into their parent, each one was (wrongly)
    parsed as its own ability — so the enrichment pipeline enriched it and its
    damage came back as structure. Folding removed the record that carried
    that, and nothing re-extracts from a plain string field. This puts it back
    as degree_effects[] on the parent, keyed by degree.

    The extractor is the enrichment regex pass, not _parse_damage: the latter
    parses a Damage FIELD value ("2d6 slashing"), while a degree is prose
    ("the target takes double damage and 2d6 persistent bleed damage"). Using
    the same extractor that produced the original objects reproduces them
    rather than inventing new ones. regex_extractor imports only json and re,
    so this pulls in no DB and no LLM.

    `damage` only, deliberately. Measured 2026-08-18 against the corpus AS
    BOUNDED BY THIS MODULE -- 160 DC occurrences in degree text, of which 64 are
    Escape DCs, 44 saving throws, 44 flat checks, 7 skill checks and 1 naming no
    check at all. Typing those as save_dc would claim something the source never
    said, so saving_throw and skill_check wait for PFSRD2-Parser-2cby.

    The date is load-bearing. This census counts degree TEXT, and the degree
    boundaries in this same module decide how much text there is, so it goes
    stale whenever they move. Re-derive from the corpus before quoting it; the
    published schema descriptions deliberately carry no tally at all.

    What comes back is damage the degree's text MENTIONS, which is not always
    damage the degree's subject takes: a small minority describe damage dealt
    to someone else ("the morlock injures themself, taking 2d6 damage"). A
    consumer that needs the subject must read the text. No count here on
    purpose — it moved from 7-of-439 to 7-of-697 while this PR was open, and a
    number that drifts every time coverage widens is worse than none.

    FIVE functions write a degree. Four call this once their degrees are
    final: extract_result_blocks (feats, spells, parse_ability_from_html),
    ability._build_ability_from_entry (whose degrees arrive through
    _apply_addon), creatures._apply_addons, hazard._extract_routine_results.
    The fifth, equipment._extract_save_outcomes, deliberately does not yet —
    see PFSRD2-Parser-qj3v, which covers its 212 degree-carrying objects.

    Do not read that list as closed. A writer without a call is SILENT: the
    field simply does not appear, which reads identically to "this degree had
    no damage". That is how the creature path shipped empty, and why the count
    here is a fact to re-check rather than a guarantee.

    `owner_name` names the enclosing object when `ability` has no name of its
    own -- a hazard's routine_results, a spell's defense. Only the exemption
    table in constants.py reads it, and without it that table cannot reach a
    third of the corpus. See _is_exempt.
    """
    effects = degree_effects_for(ability, owner_name)
    if effects:
        ability["degree_effects"] = effects


def _is_exempt(obj, degree, plain, owner_name=None):
    """A degree the extractor cannot judge, listed by name in constants.py.

    An entry matches when BOTH its (name, degree) key and its pinned phrase are
    present. The phrase is part of the match, not an assertion made after it.

    That ordering is load-bearing. `owner_name` is the nearest enclosing NAMED
    object, because 836 of the corpus's 2582 degree carriers have no name of
    their own -- every spell_defense, every equipment save_results, every hazard
    routine_results -- so keying on obj["name"] alone left a third of the corpus
    unreachable by any exemption, silently. But a name is not a unique handle on
    a degree: measured 2026-08-18, 28 (name, degree) keys already match TWO
    carriers in the same file. Asserting on the phrase after matching the key
    would make an exemption written for one sentence halt the parse on its
    same-named neighbour, which is a worse failure than the one the pin exists
    to prevent.

    Requiring the phrase makes the match exact, and makes the writer and the
    guard agree by construction: both ask the same question of the same degree
    text, whatever route they took to the object.

    The expiry the pin was for has not gone away, it has moved somewhere that
    can actually see it. If AoN rewords a degree, the phrase stops matching, the
    exemption stops applying, and the suppressed dice republish -- so the check
    has to be corpus-wide rather than per-degree. bin/pf2_verify_degree_exemptions
    reports any entry whose phrase is present nowhere. A per-parse assert could
    not do that job: it only ever sees one degree at a time, and it fires on the
    wrong one.
    """
    key = (obj.get("name") or owner_name, degree)
    if key not in DEGREE_EFFECT_NOT_THE_SUBJECTS:
        return False
    phrase, _why = DEGREE_EFFECT_NOT_THE_SUBJECTS[key]
    return phrase in plain


def degree_effects_for(obj, owner_name=None):
    """The degree_effects an object's degrees imply. Pure; obj is not touched.

    Split out from the mutator so assert_every_degree_was_modelled can ask the
    same question of finished output without writing to it.
    """
    effects = []
    for degree in DEGREE_FIELDS:
        text = obj.get(degree)
        if not isinstance(text, str) or not text.strip():
            continue
        # extract_all reads "text" and "effect" for content, and treats
        # saving_throw/area/range/DAMAGE as already-done when the key is
        # present — handing it a real ability dict would make it extract
        # nothing. Hence a dict carrying only the degree's text, which is why
        # this is not the parent ability. _missed reports keywords it saw but
        # could not structure; that is a corpus-coverage signal for the
        # enrichment pass, not a per-degree one — PFSRD2-Parser-165k measures
        # it.
        plain = get_text(BeautifulSoup(text, "html.parser"))
        if _is_exempt(obj, degree, plain, owner_name):
            continue
        enriched, _missed = extract_all({"text": plain})
        damage = _damage_the_degree_itself_deals((enriched or {}).get("damage"), plain)
        if not damage:
            continue
        effects.append(
            {
                "type": "stat_block_section",
                "subtype": "degree_effect",
                "degree": degree,
                "damage": damage,
            }
        )
    return effects


# A degree IS the outcome of a save. So a die roll inside it that carries its
# OWN save, or that is a per-unit rate rather than an amount, is not what this
# degree deals — it belongs to a second check the prose introduces. Modelling it
# says the creature takes damage it does not take (wind_surge, the_putrid_rise)
# or takes a fraction of what it does (test_of_endurance). PFSRD2-Parser-bsw3:
# these stay prose.
# An ALTERNATIVE to the damage already stated, not damage on top of it:
# "2d6 ... or 6d6 if you have legendary proficiency", "3d4 mental damage
# instead if", "either is deafened (if sonic) or takes 1d6 persistent fire".
# Emitting both makes a consumer read 8d6 where the source offers a choice of
# 2d6. Keeping the base case is the same call PFSRD2-Parser-bsw3 makes for
# scaling.
# The marker must join TWO damage expressions inside one sentence. Requiring a
# preceding NdM is what separates "2d6 damage ... or 6d6 damage" from the
# ordinary English "or" that is everywhere: "a Medium or smaller creature takes
# 2d6+5", "if the creature is undead or a nindoru fiend, it takes 2d6", "an
# activity that requires three or more actions". All three of those are real
# damage and an unanchored marker suppressed them.
_AN_ALTERNATIVE_BEFORE = re.compile(
    r"\d+d\d+[^.]{0,90}\b(?:or|either|alternately)\b[^.]{0,30}$", re.I
)
# "3d4 mental damage instead if" is an alternative. "6d6 fire damage instead OF
# 12d6" is the value itself, replacing another -- keep it.
_AN_ALTERNATIVE_AFTER = re.compile(r"^[^.]{0,40}\binstead\b(?!\s+of\b)", re.I)

# Hit Points restored, not damage dealt. "The target regains 8d6 Hit Points"
# is the opposite of what an attack_damage object means.
_HEALING_BEFORE = re.compile(r"\b(?:regains?|heals?|restores?|recovers?)\b[^.]{0,40}$", re.I)

# The parenthetical must actually NAME a save. The corpus writes escape DCs as
# "Escapes (DC 24)" and "escape (DC 37)" -- bare parenthesised DCs that gate a
# way OUT of a condition, not the damage. Matching those dropped the degree's
# own damage and kept the recurring damage instead, in second_kiss_engine and
# ephialtes. A fixture written "(Escape DC 25)" hid it: real pages put the verb
# outside the parens.
_ITS_OWN_SAVE = re.compile(r"\(\s*DC\s*\d+[^)]*\bsaves?\b", re.I)

# ...unless the sentence names the degree's OWN subject taking it. A basic save
# printed right after the dice is the standard way of writing the degree's own
# damage, so the parenthetical alone cannot tell a second check from the first.
# Without this, gorlak's Fling Foe lost all three degrees -- "The creature takes
# 2d10+9 piercing damage (DC 25 basic Fortitude save)" -- while ran-to's
# Whirlwind Toss, the same ability shape, kept its damage only because the
# source happened to put the parenthetical past the window. That is the rule
# reading layout rather than attribution.
_THE_DEGREES_OWN_SUBJECT = re.compile(
    r"\b(?:the (?:creature|target)|you)\s+takes?\b[^.]{0,40}$", re.I
)
_A_RATE_NOT_AN_AMOUNT = re.compile(r"\bfor (?:each|every)\b", re.I)

# How far past the dice to look. Long enough to clear "6d6 bludgeoning damage to
# creatures in the water or within 15 feet of the waterline (DC 29 ...)", short
# enough not to reach an unrelated later sentence.
_QUALIFIER_WINDOW = 110


def _damage_the_degree_itself_deals(damage, plain):
    """Drop dice the degree mentions but does not itself deal.

    Positional, because the qualifier follows the dice: find each formula in the
    degree's own text and read the words after it. A formula that appears
    nowhere in the text is kept — that means the extractor built it some other
    way and this cannot judge it.
    """
    if not damage:
        return damage
    kept = []
    for entry in damage:
        formula = entry.get("formula")
        at = plain.find(formula) if formula else -1
        if at == -1:
            kept.append(entry)
            continue
        window = plain[at : at + _QUALIFIER_WINDOW]
        before = plain[max(0, at - _QUALIFIER_WINDOW) : at]
        if _ITS_OWN_SAVE.search(window) and not _THE_DEGREES_OWN_SUBJECT.search(before):
            continue
        if _A_RATE_NOT_AN_AMOUNT.search(window):
            continue
        # Look BEHIND as well: "or"/"regains" introduce the dice, they do not
        # follow them.
        if _AN_ALTERNATIVE_BEFORE.search(before) or _HEALING_BEFORE.search(before):
            continue
        if _AN_ALTERNATIVE_AFTER.search(plain[at + len(formula) :]):
            continue
        kept.append(entry)
    return kept


# The equipment parser writes degrees through its own _extract_save_outcomes and
# models none of them: 36 objects, 35 under equipment/ and 1 under weapons/, all
# on equipment.schema.json (all six equipment types share that schema, so the
# deferral cannot be dodged by running a different one). That is PFSRD2-Parser-qj3v, deferred deliberately.
# This constant IS the scope of that deferral, written down where the guard can
# see it, and it goes away when qj3v lands. Do not add to it to quiet a failure
# — a new entry here means a degree-writer shipped unmodelled, which is the
# exact defect the guard exists to catch.
_DEGREE_MODELLING_DEFERRED = frozenset({"equipment.schema.json"})


def assert_every_degree_was_modelled(struct, schema_name):
    """A writer that never calls extract_degree_effects fails HERE.

    Every other failure mode in this feature is loud. This one is not: a new
    place that writes a degree, or a fixed key-list that copies the degrees
    without their structure, produces output that is *valid* and simply
    missing a field — indistinguishable from "this degree had no damage". Two
    review rounds found four such holes (creatures, feats, spells, hazard
    routines) and two more in copy-lists (skill, monster_ability), and not one
    of them tripped anything.

    So the invariant is checked against finished output instead of trusted:
    recompute what each object's degrees imply and compare. Over the published
    corpus this agrees everywhere the deferral does not cover.

    How much the deferral covers is a measurement, not a constant, so it is
    not written here -- bin/pf2_verify_degree_exemptions prints it, and also
    fails if DEFERRED_DIRS stops matching _DEGREE_MODELLING_DEFERRED.

    Recomputing from published text is safe because the extractor is fed
    get_text() at write time, and no published degree string carries markup.
    """
    if schema_name in _DEGREE_MODELLING_DEFERRED:
        return
    first = next(_unmodelled_degree_carriers(struct), None)
    if first is not None:
        obj, expected, owner_name = first
        actual = obj.get("degree_effects") or []
        # Say which of the three disagreements this is. The comparison went
        # from degree names to full structure, so "missing" is no longer the
        # only way to fail -- and the message used to print "no degree_effects
        # for []" when the object had EXTRA entries, which describes the
        # opposite of what happened.
        missing = [
            e["degree"] for e in expected if e["degree"] not in {a["degree"] for a in actual}
        ]
        extra = [a["degree"] for a in actual if a["degree"] not in {e["degree"] for e in expected}]
        if missing:
            what = f"no degree_effects for {missing}"
        elif extra:
            what = f"degree_effects for {extra}, which its text does not carry"
        else:
            what = (
                "degree_effects on the right degrees but with different damage: "
                f"expected {expected}, published {actual}"
            )
        assert False, (
            f"{obj.get('name') or owner_name!r} ({obj.get('subtype')}) publishes "
            f"a degree whose text disagrees with its structure — {what}. "
            "Either whatever wrote this object's degrees never called "
            "extract_degree_effects, or it called it before the degrees were "
            "final — see that function for the list of writers. Fix it where "
            "the degrees become final; do not add or edit the field by hand."
        )


def _unmodelled_degree_carriers(struct, owner_name=None):
    """Walks output, carrying down the nearest enclosing name.

    The name matters because degree_effects_for consults the exemption table
    with it. Recomputing WITHOUT it would make this guard disagree with the
    writer on every exempt degree that hangs off an unnamed carrier, and the
    guard would report the writer as broken.
    """
    if isinstance(struct, dict):
        owner_name = struct.get("name") or owner_name
        if any(isinstance(struct.get(d), str) for d in DEGREE_FIELDS):
            expected = degree_effects_for(struct, owner_name)
            actual = struct.get("degree_effects") or []
            # Full structural equality, not just the degree NAMES. Comparing
            # names only would pass an object whose degree_effects listed the
            # right degrees with the wrong dice on them -- which is the shape
            # of every bug this feature has actually shipped. Re-measured over
            # the corpus: exact equality costs nothing, it finds the same zero
            # disagreements.
            if expected != actual:
                yield struct, expected, owner_name
        for value in struct.values():
            yield from _unmodelled_degree_carriers(value, owner_name)
    elif isinstance(struct, list):
        for value in struct:
            yield from _unmodelled_degree_carriers(value, owner_name)


_KEY_OVERRIDES = {
    "requirements": "requirement",
    "prerequisites": "prerequisite",
}


def extract_bold_fields(section, bs, labels, decompose=False, stop_at_br=False):
    """Extract bold-labeled fields from a BeautifulSoup object.

    Finds <b>Label</b> followed by value text, extracts each recognized
    label into section[key] = value. Keys are derived from labels via
    lowercase + underscore conversion, with standard plural normalization.

    Args:
        section: dict to store extracted key/value pairs into
        bs: BeautifulSoup object to search
        labels: set of recognized bold label strings
        decompose: If True, remove extracted nodes from the BS tree.
            Use when operating on a live BS object that will be processed
            further (e.g. feat's _extract_bold_fields_from_bs).
        stop_at_br: If True, add <br/> as a terminator for each value run —
            the next bold still ends it too, whichever comes first. Use where
            a field's value never spans a break, so the last field in a block
            stops absorbing the prose that follows it and that prose falls out
            as residual description.
    """
    for bold in list(bs.find_all("b")):
        label = get_text(bold).strip()
        if label not in labels:
            continue
        # The third and last inlined copy of the walk. It was byte-for-byte
        # the loop _extract_stage_fields lost, including the `while node:`
        # falsy test — leaving it here would have fixed that in two copies and
        # not in the one ~8 parsers reach. PFSRD2-Parser-nlf1 changes WHERE
        # this run terminates, which is orthogonal to whose walk it is.
        nodes_to_remove = nodes_after(bold, stop_at_br=stop_at_br)
        value = "".join(str(n) for n in nodes_to_remove).strip()
        value = re.sub(r"<br/?>[\s]*$", "", value)
        if value.endswith(";"):
            value = value[:-1].strip()
        key = label.lower().replace(" ", "_")
        key = _KEY_OVERRIDES.get(key, key)
        section[key] = value
        if decompose:
            for n in nodes_to_remove:
                n.extract()
            bold.decompose()


def aon_pass(struct, basename):
    parts = basename.split("_")
    assert len(parts) == 2
    id_text = parts[1].replace(".html", "")
    struct["aonid"] = int(id_text)
    struct["game-obj"] = parts[0].split(".")[0]


def restructure_pass(struct, obj_name, find_object_fxn):
    sb = find_object_fxn(struct)
    struct[obj_name] = sb
    struct["sections"].remove(sb)


def html_pass(section):
    if "sections" in section:
        for s in section["sections"]:
            html_pass(s)
    if "stat_block" in section:
        html_pass(section["stat_block"])
    if "text" in section:
        section["html"] = section["text"].strip()
        del section["text"]


def remove_empty_sections_pass(struct):
    if "sections" in struct:
        for section in struct["sections"]:
            remove_empty_sections_pass(section)
            if len(struct.get("sections", [])) == 0:
                del section["sections"]
    if "stat_block" in struct:
        remove_empty_sections_pass(struct["stat_block"])
    if "sections" in struct and len(struct.get("sections", [])) == 0:
        del struct["sections"]


def walk(struct, test, function, parent=None):
    if test(struct):
        function(struct, parent)
    if isinstance(struct, dict):
        for _k, v in struct.items():
            walk(v, test, function, struct)
    elif isinstance(struct, list):
        for i in struct:
            walk(i, test, function, struct)


def test_key_is_value(k, v):
    def test(struct):
        return bool(isinstance(struct, dict) and "type" in struct and struct.get(k) == v)

    return test


def game_id_pass(struct):
    source = struct["sources"][0]
    name = struct["name"]
    pre_id = "{}: {}: {}".format(source["name"], source.get("page"), name)
    struct["game-id"] = md5(str.encode(pre_id)).hexdigest()


def get_links(bs, unwrap=False):
    all_a = bs.find_all("a")
    links = []
    for a in all_a:
        # Skip PFS icon/note links (decorative navigation, not game content)
        href = a.get("href", "")
        if "PFS.aspx" in href:
            if unwrap:
                a.unwrap()
            continue
        _, link = extract_link(a)
        links.append(link)
        if unwrap:
            a.unwrap()
    return links


def link_modifiers(modifiers):
    for m in modifiers:
        bs = BeautifulSoup(m["name"], "html.parser")
        links = get_links(bs, True)
        if links:
            m["name"] = clear_tags(str(bs), ["i"])
            m["links"] = links
    return modifiers


def link_value(value, field="name", singleton=False):
    if field in value:
        bs = BeautifulSoup(value[field], "html.parser")
        links = get_links(bs, True)
        if links:
            if singleton:
                assert len(links) == 1, f"Multiple links found where one expected: {value[field]}"
                value[field] = str(bs)
                value["link"] = links[0]
            else:
                value[field] = str(bs)
                value["links"] = links
    return value


def link_values(values, field="name", singleton=False):
    for v in values:
        v = link_value(v, field, singleton)
    return values


def extract_modifiers(text):
    if text.find("(") > -1:
        assert text.endswith(")"), f"Modifiers should be at the end only: {text}"
        parts = [p.strip() for p in text.split("(")]
        assert len(parts) == 2, text
        text = parts.pop(0)
        mods = parts.pop()
        mtext = split_comma_and_semicolon(mods[0:-1], parenleft="[", parenright="]")
        modifiers = modifiers_from_string_list(mtext)
        return text, link_modifiers(modifiers)
    return text, []


def string_values_from_string_list(strlist, subtype, check_modifiers=True):
    svs = []
    for part in strlist:
        sv = {"type": "stat_block_section", "subtype": subtype}
        if check_modifiers:
            part, modifiers = extract_modifiers(part)
            if modifiers:
                raise AssertionError(f"String Values have no modifiers: {part}")
        sv["name"] = part
        svs.append(sv)
    return svs


def string_with_modifiers_from_string_list(strlist, subtype):
    swms = []
    for mpart in strlist:
        swms.append(string_with_modifiers(mpart, subtype))
    return swms


def string_with_modifiers(mpart, subtype):
    swm = {"type": "stat_block_section", "subtype": subtype}
    mpart, modifiers = extract_modifiers(mpart)
    if modifiers:
        swm["modifiers"] = modifiers
    swm["name"] = clear_tags(mpart, ["i"])
    return swm


def parse_number(text):
    negative = False
    if text.startswith("–") or text.startswith("-"):
        negative = True
        text = text[1:]
    if text == "—":
        return None
    value = int(text)
    if negative:
        value = value * -1
    return value


def number_with_modifiers(mpart, subtype):
    nwm = {"type": "stat_block_section", "subtype": subtype}
    mpart, modifiers = extract_modifiers(mpart)
    if modifiers:
        nwm["modifiers"] = modifiers
    nwm["value"] = parse_number(mpart)
    return nwm


def modifiers_from_string_list(modlist, subtype="modifier"):
    modifiers = []
    for mpart in modlist:
        mpart = clear_tags(mpart, "i")
        modifiers.append({"type": "stat_block_section", "subtype": subtype, "name": mpart})
    return modifiers


def break_out_subtitles(bs, tagname):
    parts = []
    part = []
    title = None
    for tag in bs.children:
        if tag.name == tagname:
            if len(part) > 0:
                if title:
                    title = title.get_text().strip()
                parts.append((title, "".join([str(p) for p in part]).strip()))
                part = []
                title = None
            title = tag
        else:
            part.append(tag)
    if len(part) > 0:
        if title:
            title = title.get_text().strip()
        parts.append((title, "".join([str(p) for p in part]).strip()))
    return parts


def build_objects(dtype, subtype, names, keys=None):
    objects = []
    for name in names:
        objects.append(build_object(dtype, subtype, name, keys))
    return objects


def build_object(dtype, subtype, name, keys=None):
    assert type(name) is str
    obj = {"type": dtype, "subtype": subtype, "name": name.strip()}
    if keys:
        obj.update(keys)
    return obj


def build_value_objects(dtype, subtype, names, keys=None):
    objects = []
    for name in names:
        objects.append(build_object(dtype, subtype, name, keys))
    return objects


def build_value_object(dtype, subtype, value, keys=None):
    assert type(value) is str
    obj = {"type": dtype, "subtype": subtype, "value": value}
    if keys:
        obj.update(keys)
    return obj


def link_objects(objects):
    for o in objects:
        bs = BeautifulSoup(o["name"], "html.parser")
        links = get_links(bs)
        if len(links) > 0:
            o["name"] = get_text(bs)
            o["link"] = links[0]
            if len(links) > 1:
                # TODO: fix []
                raise AssertionError(objects)
    return objects


def edition_pass(details):
    for detail in details:
        if detail["name"] == "Legacy Content":
            return "legacy"
        result = edition_pass(detail["sections"])
        if result == "legacy":
            return result
    return "remastered"


def edition_from_alternate_link(struct):
    """Infer edition from the alternate_link sidebar if present.

    If alternate_type is "remastered", this item IS legacy (it links to its remastered version).
    If alternate_type is "legacy", this item IS remastered (it links to its legacy version).
    Returns None if no alternate_link is present.
    """
    alt = struct.get("alternate_link")
    if not alt:
        return None
    if isinstance(alt, list):
        # Assert all entries agree on alternate_type (items split into multiple
        # remastered versions should all have the same type)
        alt_types = {a.get("alternate_type") for a in alt}
        assert len(alt_types) == 1, f"Conflicting alternate_type values in list: {alt_types}"
        alt = alt[0]
    alt_type = alt.get("alternate_type")
    if alt_type == "remastered":
        return "legacy"
    elif alt_type == "legacy":
        return "remastered"
    return None


# Sources where AoN shares one page for legacy + remastered editions.
# The source name in item HTML is always the base name (e.g. "Treasure Vault"),
# so remastered items must be renamed programmatically.
_SOURCE_EDITION_OVERRIDES = {
    "Treasure Vault": {
        "remastered": "Treasure Vault (Remastered)",
    }
}


def source_edition_override_pass(struct):
    """Rename source names for split sources based on detected edition.

    Must be called AFTER edition and sources are set, BEFORE game_id_pass.
    """
    edition = struct.get("edition")
    if not edition:
        return
    for source in struct.get("sources", []):
        overrides = _SOURCE_EDITION_OVERRIDES.get(source["name"])
        if overrides and edition in overrides:
            source["name"] = overrides[edition]
            if "link" in source:
                source["link"]["name"] = overrides[edition]
                source["link"]["alt"] = overrides[edition]


def extract_span_traits(section, bs):
    """Trait spans out of a stat block, into section["traits"].

    is_trait joins the class list before matching, so it covers every rarity
    class AoN uses — trait, traituncommon, traitrare, traitunique. The spans
    are decomposed so they do not survive into the residual description.
    """
    traits = []
    for span in list(bs.find_all("span")):
        if not is_trait(span):
            continue
        trait = build_object("stat_block_section", "trait", get_text(span).strip())
        links = get_links(span, unwrap=True)
        if links:
            trait["links"] = links
        traits.append(trait)
        span.decompose()
    if traits:
        section["traits"] = traits


def take_stat_block_text(sections):
    """Take the stat block text out of whichever section carries it.

    Depth first: a spoiler warning renders as an h2 that nests the stat block
    a level deeper than the usual layout.

    The carrier section is left in place with only its text removed. On a
    legacy page that section is named "Legacy Content", and edition_pass
    decides the edition by looking for exactly that name — so removing the
    section outright silently turns every legacy page remastered.
    remove_empty_sections_pass drops the emptied husk later.
    """
    for section in sections:
        if section.get("text"):
            return section.pop("text")
        found = take_stat_block_text(section.get("sections", []))
        if found:
            return found
    return None


# Sections that exist to be read and then discarded: "Legacy Content" is the
# carrier edition_pass reads the edition off, "Traits" is consumed by the
# trait extractor. No page in the current corpus produces a "Traits" section —
# it is kept because it costs a word and the alternative is one leaking into
# output the day a page does.
MARKER_SECTIONS = ("Legacy Content", "Traits")


def drop_marker_sections(struct, names=MARKER_SECTIONS):
    """Remove the marker sections, once they are known to be empty.

    Dropping one by name while it still carries text would be silent data
    loss, so this asserts rather than trusting that an earlier pass emptied
    it. Must run after edition_pass, which needs the Legacy Content name.

    Recurses, because a spoiler warning nests the carrier a level deeper and
    remove_empty_sections_pass only clears empty `sections` keys — it never
    removes an element from a parent list, so a nested husk would otherwise
    ship with the document.
    """
    kept = []
    for section in struct.get("sections", []):
        drop_marker_sections(section, names)
        if section.get("name") in names:
            assert not section.get("text"), (
                f"{section['name']!r} section on {struct.get('name')!r} still carries text; "
                "dropping it here would lose data"
            )
            continue
        kept.append(section)
    struct["sections"] = kept
