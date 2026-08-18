"""Degree-exemption verification: every named exemption must still name a
real, matching object, and the modelling deferral must still cover what it
claims.

Two tables in constants.py suppress or extend a degree by NAME:
DEGREE_EFFECT_NOT_THE_SUBJECTS (six degrees whose published dice are real but
not the subject's) and DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK (one degree
that owns the paragraph after it).

Each entry pins the phrase it was written against, and
universal.assert_exemptions_still_apply asserts at DOCUMENT scope if that
phrase is rewritten. But that only fires when the KEY matches. If AoN renames
the ability, or the parser stops producing that name, the key silently stops
matching -- and a suppressed number quietly republishes with nothing to say so.
That is the same defect the rune verifier exists for: a clause that matches
nothing is worse than no clause.

    bin/pf2_verify_degree_exemptions     # exit 1 on dead entries

Run after any change to the exemption tables, to the degree boundary rules, or
after a web re-download.

The deferral count is checked here too, for the same reason it cannot be a
comment: _DEGREE_MODELLING_DEFERRED turns the modelling guard OFF for a whole
schema, and how much data that covers is a measurement that drifts.
"""

import os

from pfsrd2.constants import (
    DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK,
    DEGREE_EFFECT_NOT_THE_SUBJECTS,
)
from pfsrd2.qa import data_dir, load_json_dir
from universal.universal import DEGREE_FIELDS, degree_carriers

# The data directories equipment.schema.json covers -- the scope of the
# modelling deferral. One parser writes this schema under six type configs
# (equipment, weapon, armor, shield, siege_weapon, vehicle), which is why the
# deferral reaches further than the word "equipment" suggests. Hand-typed, so
# unmodelled_outside_the_deferral() cross-checks it against the walker rather
# than trusting it: this list and _DEGREE_MODELLING_DEFERRED are two spellings
# of one fact and nothing else keeps them in step.
DEFERRED_DIRS = (
    "equipment",
    "weapons",
    "armor",
    "shields",
    "siege_weapons",
    "vehicles",
)


def content_dirs():
    """Top-level data directories, excluding git and the bug-report folder."""
    root = data_dir()
    return sorted(
        name
        for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
        and not name.startswith(".")
        and name != "known_errors"
    )


def published_degree_texts(docs):
    """Every (owning name, degree) a document publishes -> the texts under it.

    Walks with universal.degree_carriers, the same walker the parser's own
    guard uses, so this cannot disagree with it about what counts as a carrier.

    A key maps to a LIST because a name is not a unique handle: 8 keys match
    more than one carrier within a single file. Checking the pinned phrase
    needs all of them.
    """
    texts = {}
    for doc in docs:
        for carrier, owner in degree_carriers(doc):
            for degree in DEGREE_FIELDS:
                # No emptiness re-check: degree_carriers already decided that,
                # and repeating the predicate here is how the three walkers
                # drifted apart in the first place.
                # No emptiness re-check: degree_carriers already decided that.
                value = carrier.get(degree)
                if isinstance(value, str):
                    texts.setdefault((owner, degree), []).append(value)
    return texts


def ambiguous_entries(table, texts):
    """Entries whose key matches more than one carrier in some document.

    _is_exempt asserts per degree, which is exact and cannot be silenced by a
    flag -- but it means an entry written for an ambiguous name would fire on
    the neighbour that never had the phrase. Ambiguity is a property of the
    corpus, not of any one parse, so it is checked here.

    8 (name, degree) keys corpus-wide match more than one carrier in a single
    file. None of them is an exemption today; this is what fails if one ever
    becomes one.
    """
    return [
        (key, table[key][1], len(texts[key]))
        for key in sorted(table, key=str)
        if len(texts.get(key, ())) > 1
    ]


def dead_entries(table, texts):
    """Entries that can no longer apply to anything, and why they were added.

    Two ways to die, and the second is the one a parse cannot see:

    * the KEY matches nothing -- the object was renamed or is gone;
    * the key matches but the PINNED PHRASE appears in none of the degrees it
      matches -- AoN reworded the sentence the exemption was granted for.

    Either way the exemption silently stops applying and whatever it was
    suppressing republishes, which is exactly what the pin exists to prevent.
    """
    dead = []
    for key in sorted(table, key=str):
        phrase, why = table[key]
        found = texts.get(key)
        if not found:
            dead.append((key, why, "nothing publishes this degree any more"))
        elif not any(phrase in text for text in found):
            dead.append(
                (
                    key,
                    why,
                    f"the pinned phrase {phrase!r} is in none of the "
                    f"{len(found)} degree(s) this key matches",
                )
            )
    return dead


def unmodelled_outside_the_deferral():
    """Content directories that carry unmodelled degrees but are not deferred.

    DEFERRED_DIRS is a hand-typed spelling of _DEGREE_MODELLING_DEFERRED. If it
    goes stale -- another parser starts writing equipment.schema.json, or a
    deferred directory is renamed -- the deferral silently covers data this
    list does not mention, and the printed scope understates it. Rather than
    asserting the list is right, this asks the walker.

    Uses _unmodelled_degree_carriers rather than catching the AssertionError
    from assert_every_degree_was_modelled: an assert is not control flow, and
    under `python -O` there would be nothing to catch, so this check would
    silently pass for every directory.
    """
    from universal.universal import _unmodelled_degree_carriers

    stale = []
    for name in content_dirs():
        if name in DEFERRED_DIRS:
            continue
        for doc in load_json_dir(name):
            if next(_unmodelled_degree_carriers(doc), None) is not None:
                stale.append(name)
                break
    return stale


def count_deferred_carriers(docs):
    """Degree-carrying objects the modelling guard is currently skipping."""
    return sum(1 for doc in docs for _ in degree_carriers(doc))


def main():
    # Every content directory on disk, not a hand-typed list. A missing
    # directory here would make every exemption under it read as dead -- the
    # verifier would report a live entry as needing deletion, which is the one
    # wrong answer it must never give. Walking what is actually there means a
    # new content type is covered the day it lands.
    docs = load_json_dir(*content_dirs())
    if not docs:
        print(f"no data found under {data_dir()} — run the parsers first")
        return 1

    texts = published_degree_texts(docs)
    problems = []
    for label, table in (
        ("DEGREE_EFFECT_NOT_THE_SUBJECTS", DEGREE_EFFECT_NOT_THE_SUBJECTS),
        (
            "DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK",
            DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK,
        ),
    ):
        for key, why, how in dead_entries(table, texts):
            problems.append((label, key, why, how))
        for key, why, count in ambiguous_entries(table, texts):
            problems.append(
                (
                    label,
                    key,
                    why,
                    f"its key matches {count} carriers in one document, so the "
                    "per-degree assert in _is_exempt would fire on whichever of "
                    "them never held the phrase. Make the entry unambiguous",
                )
            )

    deferred = count_deferred_carriers(load_json_dir(*DEFERRED_DIRS))
    stale_scope = unmodelled_outside_the_deferral()

    print(f"distinct (name, degree) keys published: {len(texts)}")
    print(
        f"exemption entries: {len(DEGREE_EFFECT_NOT_THE_SUBJECTS)} suppressing, "
        f"{len(DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK)} extending"
    )
    print(
        f"deferred by _DEGREE_MODELLING_DEFERRED: {deferred} degree carriers "
        f"across {', '.join(DEFERRED_DIRS)}"
    )

    if stale_scope:
        print(
            f"\nDEFERRAL SCOPE IS STALE: {', '.join(stale_scope)} carry unmodelled "
            "degrees but are not in DEFERRED_DIRS. Either a writer is missing its "
            "extract_degree_effects call, or DEFERRED_DIRS no longer matches "
            "_DEGREE_MODELLING_DEFERRED."
        )

    if problems:
        print(f"\nDEAD EXEMPTIONS: {len(problems)}")
        for label, key, why, how in problems:
            print(f"  - {label}{key}: {how}.")
            print(f"      granted because {why}")
        print(
            "\nAn exemption that stops matching does not assert -- it just "
            "stops applying, and whatever it was suppressing republishes "
            "silently. Re-read the object and update or delete the entry."
        )
        return 1
    if stale_scope:
        # Reported above; returned here so BOTH problems always print. An early
        # return on the scope check hid any dead exemption behind it.
        return 1
    print("\nevery degree exemption still names a real, published degree")
    return 0
