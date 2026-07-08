"""Curated cross-type edition equivalence links.

AoN alternate links connect same-type pages across editions. When a
transformation's rules CARRIER changed type across editions (Book of the
Dead undead templates -> Monster Core creation-rules families), the pair
is hand-curated in overrides/equivalents.json and emitted into both
documents as an equivalent_link — same role as alternate_link, distinct
field, because it is editorial data with no AoN backing.
"""

import json
import os

_EQUIVALENTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "overrides",
    "equivalents.json",
)

_BY_GAME_ID = None


def _load():
    global _BY_GAME_ID
    if _BY_GAME_ID is None:
        with open(_EQUIVALENTS_PATH, encoding="utf-8") as fp:
            pairs = json.load(fp)["equivalents"]
        _BY_GAME_ID = {}
        for pair in pairs:
            a, b = pair["a"], pair["b"]
            _BY_GAME_ID[a["game_id"]] = b
            _BY_GAME_ID[b["game_id"]] = a
    return _BY_GAME_ID


def equivalent_link_pass(struct):
    """Attach equivalent_link when this document's game-id is paired.

    Runs after game_id_pass. No-op for unpaired documents.
    """
    other = _load().get(struct.get("game-id"))
    if not other:
        return
    struct["equivalent_link"] = {
        "type": "equivalent_link",
        "game_id": other["game_id"],
        "entry_type": other["entry_type"],
        "name": other["name"],
        "edition": other["edition"],
    }
