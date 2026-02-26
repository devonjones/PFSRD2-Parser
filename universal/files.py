import os
import re
import unicodedata


def char_replace(instr):
    for char in {
        "(",
        ")",
        "[",
        "]",
        ",",
        "/",
        "'",
        "\u2018",
        "\u2019",
        ":",
        ";",
        "&",
        ".",
        "#",
        "!",
        "?",
    }:
        instr = instr.replace(char, "")
    instr = instr.strip()
    instr = instr.replace(" ", "_")
    instr = instr.lower()
    instr = "".join(
        c for c in unicodedata.normalize("NFD", instr) if unicodedata.category(c) != "Mn"
    )
    instr = re.sub(r"[^a-z0-9_\-]", "", instr)
    return instr


def makedirs(output, game_obj, source=None):
    if not source:
        game_obj_dir = os.path.abspath(output + "/" + char_replace(game_obj))
    else:
        game_obj_dir = os.path.abspath(
            output + "/" + char_replace(game_obj) + "/" + char_replace(source)
        )
    if not os.path.exists(game_obj_dir):
        os.makedirs(game_obj_dir)
    return game_obj_dir
