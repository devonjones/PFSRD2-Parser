"""Prose stat-instruction extraction shared by family and template parsers.

Legacy families (Bestiary Lich) carry their "change its statistics" steps
as <br>-separated prose instead of a <ul>, and BOTH families and templates
bury level changes in intro sentences ("To create a lich, increase the
spellcaster's level by 1..." / Experimental Cryptid's "Increase the
creature's level by 1 and change its statistics as follows."). See the
predicates below for the imperative/gain-lose/lead-in/anaphora rules —
each exclusion class was added for a specific audited false positive.
"""

import re

from bs4 import BeautifulSoup

from universal.universal import build_object, get_links
from universal.utils import get_text

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
# also split after a sentence-ending punctuation followed by a closing
# paren/quote — "(These changes reflect a werecreature in its hybrid
# form.) Increase the creature's level by 1..." must split so the
# parenthetical exclusion can't swallow the instruction that follows
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[a-z][.!?])(?=[A-Z])|(?<=[.!?][)\"\u201d])\s+")
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


def prose_changes_from_text(html_text):
    """Prose stat-instruction changes from a text blob, <br>-line split.

    Used by the template parser on the intro prose that remains after a
    creation section's <ul> is extracted (Experimental Cryptid's level
    bump lives there). Same predicates and exclusions as the family path.
    """
    changes = []
    for line_html in re.split(r"<br\s*/?>", html_text or ""):
        changes.extend(_prose_changes_for_line(line_html))
    return changes
