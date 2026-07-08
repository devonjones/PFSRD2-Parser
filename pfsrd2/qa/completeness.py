"""Parser completeness: every substantive line of a template/family page's
rules region must appear somewhere in the parsed JSON (change text, ability,
section text, adjustments). Reports lines the JSON does not cover.

Found the <br>-continuation truncation (PR #133): 26 abilities across 24
files silently lost their follow-on paragraphs. Run after any parser
change that touches ability/section extraction:

    bin/pf2_check_completeness            # exit 1 on non-exempt gaps

Known-benign exceptions are documented in EXEMPT below — each entry says
WHY the HTML line legitimately doesn't appear verbatim in the JSON.
"""

import glob
import html as htmllib
import json
import os
import re

WEB = "/home/devon/MasterworkTools/pfsrd2/pfsrd2-web/2e.aonprd.com"
DATA = "/home/devon/MasterworkTools/pfsrd2/pfsrd2-data"


def norm(t):
    t = htmllib.unescape(t)
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return " ".join(t.split())


def json_corpus(doc):
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("text", "name", "effect", "frequency", "trigger") and isinstance(v, str):
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return norm(" ".join(out))


def page_lines(path):
    h = open(path).read()
    m = re.search(r"<h1.*?(?=Site Owner|<footer|id=\"push\")", h, re.S)
    region = m.group(0) if m else h
    region = re.sub(r"<script.*?</script>", " ", region, flags=re.S)
    # the parser strips the Members creature-link list by design
    region = re.sub(
        r"<h3[^>]*class=\"framing\"[^>]*>\s*Members\s*</h3>.*?(?=<h[12]|$)", " ", region, flags=re.S
    )
    # break on structural boundaries
    region = re.sub(r"<(?:br|/h\d|/li|/ul|/b)[^>]*>", "\n", region)
    lines = []
    for ln in re.sub(r"<[^>]+>", " ", region).split("\n"):
        ln = " ".join(htmllib.unescape(ln).split())
        if len(ln) >= 25:  # substantive lines only
            lines.append(ln)
    return lines


# map aonid -> json doc
docs = {}
for kind, tdir, key in (
    ("monster_templates", "MonsterTemplates", "monster_template"),
    ("monster_families", "MonsterFamilies", "monster_family"),
):
    for f in glob.glob(f"{DATA}/{kind}/**/*.json", recursive=True):
        d = json.load(open(f))
        if d.get("aonid") is not None:
            docs.setdefault((tdir, d["aonid"]), []).append((f, d))

missing_report = []
for kind, aspx in (
    ("MonsterTemplates", "MonsterTemplates.aspx"),
    ("MonsterFamilies", "MonsterFamilies.aspx"),
):
    for f in sorted(os.listdir(f"{WEB}/{kind}")):
        m = re.match(rf"{aspx}\.ID_(\d+)\.html$", f)
        if not m:
            continue
        aonid = int(m.group(1))
        entries = docs.get((kind, aonid))
        if not entries:
            missing_report.append((f, None, ["NO JSON DOC FOR PAGE"]))
            continue
        corpus = " ".join(json_corpus(d) for _, d in entries)
        gaps = []
        BOILER = (
            "there is a remastered version",
            "there is a legacy version",
            "click here for the full rules",
            "recall knowledge -",
            "source ",
        )
        for ln in page_lines(f"{WEB}/{kind}/{f}"):
            low = ln.lower()
            if any(low.startswith(b) or b in low[:60] for b in BOILER):
                continue
            n = norm(ln)
            if n and n not in corpus:
                # tolerate partial: check 60%-length prefix
                if n[: max(20, int(len(n) * 0.6))] not in corpus:
                    gaps.append(ln[:120])
        if gaps:
            missing_report.append((f, entries[0][0].split(DATA + "/")[1], gaps))

# Verified-benign exceptions: (page substring, gap prefix) -> reason
EXEMPT = {
    (
        "ID_14.html",
        "Primeval Cryptid Abilities",
    ): "section heading; abilities + guidance text are captured",
    (
        "ID_15.html",
        "Rumored Cryptid Abilities",
    ): "section heading; abilities + guidance text are captured",
    (
        "ID_21.html",
        "Weakness to Fire and Axes",
    ): "adjustments table column survives as weakness_to_fire_and_axes",
    (
        "ID_36.html",
        "The retired creature is in a combat encounter",
    ): "reaction trigger captured in the structured trigger field",
}


def is_exempt(page, gap):
    return any(pk in page and gap.startswith(gk) for (pk, gk), _ in EXEMPT.items())


def main():
    failures = 0
    for page, doc, gaps in missing_report:
        real = [g for g in gaps if not is_exempt(page, g)]
        if not real:
            continue
        failures += 1
        print("==", page, "->", doc)
        for g in real[:6]:
            print("   MISSING:", g)
    print(f"\npages with non-exempt gaps: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
