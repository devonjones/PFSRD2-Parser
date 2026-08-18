"""Degree-exemption verification: every named exemption must still name a
real, matching object, and the modelling deferral must still cover what it
claims.

Two tables in constants.py suppress or extend a degree by NAME:
DEGREE_EFFECT_NOT_THE_SUBJECTS (six degrees whose published dice are real but
not the subject's) and DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK (one degree
that owns the paragraph after it).

Each entry pins the phrase it was written against, and the parser asserts if
that phrase is rewritten. But the pin only fires when the KEY matches. If AoN
renames the ability, or the parser stops producing that name, the key silently
stops matching -- and a suppressed number quietly republishes with nothing to
say so. That is the same defect the rune verifier exists for: a clause that
matches nothing is worse than no clause.

    bin/pf2_verify_degree_exemptions     # exit 1 on dead entries

Run after any change to the exemption tables, to the degree boundary rules, or
after a web re-download.

The deferral count is checked here too, for the same reason it cannot be a
comment: _DEGREE_MODELLING_DEFERRED turns the modelling guard OFF for a whole
schema, and how much data that covers is a measurement that drifts.
"""

from pfsrd2.constants import (
    DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK,
    DEGREE_EFFECT_NOT_THE_SUBJECTS,
)
from pfsrd2.qa import data_dir, load_json_dir
from universal.universal import DEGREE_FIELDS

# The data directories equipment.schema.json covers -- the scope of the
# modelling deferral. Six parsers write this schema, which is why the deferral
# is much wider than "equipment".
DEFERRED_DIRS = (
    "equipment",
    "weapons",
    "armor",
    "shields",
    "siege_weapons",
    "vehicles",
)


def published_degree_texts(docs):
    """Every (owning name, degree) a document publishes -> the texts under it.

    The name is the nearest enclosing named object, matching how _is_exempt
    resolves a key -- a third of degree carriers (spell_defense,
    save_results, routine_results) have no name of their own.

    A key maps to a LIST because a name is not a unique handle: 28 keys in the
    corpus match two carriers in the same file. Checking the pinned phrase
    needs all of them, which is the reason this check lives here and not in
    _is_exempt -- a parse only ever sees one degree at a time.
    """
    texts = {}

    def walk(node, owner):
        if isinstance(node, dict):
            owner = node.get("name") or owner
            for degree in DEGREE_FIELDS:
                if isinstance(node.get(degree), str) and node[degree].strip():
                    texts.setdefault((owner, degree), []).append(node[degree])
            for value in node.values():
                walk(value, owner)
        elif isinstance(node, list):
            for value in node:
                walk(value, owner)

    for doc in docs:
        walk(doc, None)
    return texts


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


def count_deferred_carriers(docs):
    """Degree-carrying objects the modelling guard is currently skipping."""
    total = 0

    def walk(node):
        nonlocal total
        if isinstance(node, dict):
            if any(isinstance(node.get(d), str) for d in DEGREE_FIELDS):
                total += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for doc in docs:
        walk(doc)
    return total


def main():
    docs = load_json_dir(
        "monsters",
        "npcs",
        "spells",
        "feats",
        "skills",
        "hazards",
        "weatherhazards",
        "monster_abilities",
        "monster_families",
        "monster_templates",
        "afflictions",
    )
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

    deferred = count_deferred_carriers(load_json_dir(*DEFERRED_DIRS))

    print(f"degree-carrying objects loaded: {len(texts)} distinct (name, degree) keys")
    print(
        f"exemption entries: {len(DEGREE_EFFECT_NOT_THE_SUBJECTS)} suppressing, "
        f"{len(DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK)} extending"
    )
    print(
        f"deferred by _DEGREE_MODELLING_DEFERRED: {deferred} degree carriers "
        f"across {', '.join(DEFERRED_DIRS)}"
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
    print("\nevery degree exemption still names a real, published degree")
    return 0
