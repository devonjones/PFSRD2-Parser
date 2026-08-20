"""Degree-exemption verification: every named exemption must still name a
real, matching object, and the modelling deferral must still cover what it
claims.

Two tables in constants.py suppress or extend a degree by NAME:
DEGREE_EFFECT_NOT_THE_SUBJECTS (six degrees whose published dice are real but
not the subject's) and DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK (one degree
that owns the paragraph after it).

Each entry pins the phrase it was written against, and universal._is_exempt
raises at parse time if that phrase is rewritten. But that only fires when the
KEY matches. If AoN renames the ability, or the parser stops producing that
name, the key silently stops matching -- and a suppressed number quietly
republishes with nothing to say so. That is the same defect the rune verifier
exists for: a clause that matches nothing is worse than no clause.

This module also carries the check that makes the parse-time alarm safe. That
alarm is exact and unsilenceable -- it raises rather than asserts, so python -O
cannot strip it -- at the price of firing on a same-named
neighbour; ambiguous_entries() fails the run if any exemption key could ever
have one.

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
from pfsrd2.qa import data_dir, iter_json_dir
from universal.universal import (
    DEGREE_FIELDS,
    _unmodelled_degree_carriers,
    degree_carriers,
)

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
        _fold_degree_texts(doc, texts)
    return texts


def _fold_degree_texts(doc, texts):
    """Accumulate one document's degree texts into `texts`.

    Split out so the streaming pass in main() and the list-taking function
    above share one implementation -- two copies of a fold is how the three
    degree walkers drifted apart before they were merged.
    """
    for carrier, owner in degree_carriers(doc):
        for degree in DEGREE_FIELDS:
            # No emptiness re-check: degree_carriers already decided that.
            value = carrier.get(degree)
            if isinstance(value, str):
                texts.setdefault((owner, degree), []).append(value)


def keys_ambiguous_within_a_document(docs):
    """(name, degree) keys that match more than one carrier in the SAME doc.

    These are the keys an exemption cannot safely be written for, because
    _is_exempt would fire on whichever carrier never held the phrase. Counted
    per document on purpose -- the same key appearing once in each of fifty
    files is unambiguous everywhere it is used.
    """
    ambiguous = {}
    for doc in docs:
        _fold_ambiguous_keys(doc, ambiguous)
    return ambiguous


def _fold_ambiguous_keys(doc, ambiguous):
    """Accumulate one document's ambiguous keys into `ambiguous`.

    Per document by construction: the counts dict is local to this call, so a
    key appearing once in each of fifty files can never accumulate to two.
    """
    counts = {}
    for carrier, owner in degree_carriers(doc):
        for degree in DEGREE_FIELDS:
            value = carrier.get(degree)
            if isinstance(value, str):
                counts[(owner, degree)] = counts.get((owner, degree), 0) + 1
    for key, count in counts.items():
        if count > 1:
            ambiguous[key] = max(ambiguous.get(key, 0), count)


def ambiguous_entries(table, ambiguous_keys):
    """Entries whose key matches more than one carrier WITHIN one document.

    _is_exempt raises per degree, which is exact and cannot be silenced by a
    flag -- but an entry written for an ambiguous name would fire on the
    neighbour that never held the phrase. Ambiguity is a property of the
    corpus, not of any one parse, so it is checked here.

    Per DOCUMENT, not corpus-wide. A key matching one carrier each in fifty
    files is not ambiguous -- every parse sees exactly one -- and counting
    those made this flag 1790 of 6105 keys instead of the 8 that can actually
    collide. A verifier that false-alarms on a quarter of the corpus is a
    verifier that gets deleted.
    """
    return [
        (key, table[key][1], ambiguous_keys[key])
        for key in sorted(table, key=str)
        if key in ambiguous_keys
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

    Returns (stale directories, expired-pin messages).

    Uses _unmodelled_degree_carriers rather than catching the AssertionError
    from assert_every_degree_was_modelled: an exception is not control flow,
    and asking the walker directly says what this check means rather than
    inferring it from a failure. (The -O argument that first justified this is
    obsolete -- that guard raises now, so its error would survive -O and be
    catchable. The reason to walk directly is clarity, not survival.)
    """
    stale, expired_pins = [], []
    for name in content_dirs():
        if name in DEFERRED_DIRS:
            continue
        for doc in iter_json_dir(name):
            # _unmodelled_degree_carriers recomputes through degree_effects_for,
            # which routes through _is_exempt -- and _is_exempt RAISES on a
            # reworded pinned phrase. That raise is correct in a parse; here it
            # would abort the verifier with a traceback before a single line is
            # printed, hiding every dead and ambiguous entry behind whichever
            # reworded phrase happened to be reached first. Reported as a
            # problem instead, so the run still says everything it found.
            try:
                unmodelled = next(_unmodelled_degree_carriers(doc), None)
            except AssertionError as expired:
                # continue, not break: abandoning the directory here lets an
                # expired pin hide a stale_scope finding later in the same
                # directory -- and stale_scope DOES fail the run, so the
                # verdict flipped with glob enumeration order.
                expired_pins.append(str(expired))
                continue
            if unmodelled is not None:
                stale.append(name)
                # No break: an expired pin later in this directory is a
                # separate finding, and stopping here made whether it was
                # reported depend on enumeration order.
                continue
    return stale, expired_pins


def count_deferred_carriers(docs):
    """Degree-carrying objects the modelling guard is currently skipping."""
    return sum(1 for doc in docs for _ in degree_carriers(doc))


def main():
    # Every content directory on disk, not a hand-typed list. A missing
    # directory here would make every exemption under it read as dead -- the
    # verifier would report a live entry as needing deletion, which is the one
    # wrong answer it must never give. Walking what is actually there means a
    # new content type is covered the day it lands.
    # ONE streaming pass, three folds. Holding the corpus resident to run the
    # folds separately peaked at 1453 MB and 16.1s; this is 34 MB and 3.5s for
    # identical answers. The verifier is meant to be cheap enough that nobody
    # thinks twice about running it.
    texts, ambiguous, seen_any = {}, {}, False
    for doc in iter_json_dir(*content_dirs()):
        seen_any = True
        _fold_degree_texts(doc, texts)
        _fold_ambiguous_keys(doc, ambiguous)
    if not seen_any:
        print(f"no data found under {data_dir()} — run the parsers first")
        return 1

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
        for key, why, count in ambiguous_entries(table, ambiguous):
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

    # The tested function, not a third inline copy of the same fold: it takes
    # any iterable, so a generator streams through it just as well as a list.
    deferred = count_deferred_carriers(iter_json_dir(*DEFERRED_DIRS))
    stale_scope, expired_pins = unmodelled_outside_the_deferral()

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

    if expired_pins:
        print(f"\nEXPIRED PINS: {len(expired_pins)}")
        for message in expired_pins:
            print(f"  - {message}")

    if problems:
        print(f"\nEXEMPTIONS NEEDING ATTENTION: {len(problems)}")
        for label, key, why, how in problems:
            print(f"  - {label}{key}: {how}.")
            print(f"      granted because {why}")
        print(
            "\nAn exemption that stops matching does not assert -- it just "
            "stops applying, and whatever it was suppressing republishes "
            "silently. Re-read the object and update or delete the entry."
        )
        return 1
    if stale_scope or expired_pins:
        # Reported above; returned here so EVERY problem prints. An early
        # return on the scope check hid any dead exemption behind it.
        #
        # expired_pins IS part of this condition, and an earlier version of
        # this file wrongly dropped it on the theory that dead_entries already
        # covers the same ground. It does not: dead_entries asks whether the
        # phrase survives in ANY carrier under the key, while _is_exempt asks
        # whether it survives in THIS one. With two same-named carriers and one
        # reworded, dead_entries is satisfied and _is_exempt raises -- so the
        # run printed EXPIRED PINS and the all-clear together and exited 0.
        #
        # That removal was justified by a surviving mutation. The mutation
        # survived because the test could not observe the condition, not
        # because the condition could not occur.
        return 1
    print(
        "\nevery degree exemption still names a real, published degree, still "
        "matches the sentence it was granted for, and is unambiguous"
    )
    return 0
