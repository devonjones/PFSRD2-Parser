import json
import os
import sys

from bs4 import BeautifulSoup, Tag

from pfsrd2.action import extract_action_type
from pfsrd2.license import license_consolidation_pass, license_pass
from pfsrd2.schema import validate_against_schema
from pfsrd2.sql.sources import set_edition_from_db_pass
from pfsrd2.sql.traits import trait_db_pass as universal_trait_db_pass
from universal.ability import parse_ability_from_html
from universal.creatures import write_creature
from universal.files import char_replace, makedirs
from universal.markdown import markdown_pass
from universal.universal import (
    aon_pass,
    entity_pass,
    extract_link,
    extract_source,
    game_id_pass,
    parse_universal,
    remove_empty_sections_pass,
)
from universal.utils import content_filter, get_text, is_tag_named


def _content_filter(soup):
    """Delegate to shared content_filter."""
    content_filter(soup)


def parse_monster_ability(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(
        filename,
        subtitle_text=True,
        max_title=4,
        cssclass="main",
        pre_filters=[_content_filter],
    )
    details = entity_pass(details)
    details = [d for d in details if not (isinstance(d, str) and not d.strip())]
    struct = restructure_monster_ability_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)
    set_edition_from_db_pass(struct)
    universal_trait_db_pass(struct)
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], "")
    remove_empty_sections_pass(struct)
    basename.split("_")
    if not options.skip_schema:
        struct["schema_version"] = 1.2
        validate_against_schema(struct, "monster_ability.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct["sources"]:
            name = char_replace(source["name"])
            jsondir = makedirs(output, "monster_abilities", name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2, sort_keys=True))


def restructure_monster_ability_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)
    assert len(rest) == 0, "More sections than expected (1)"
    assert len(sb["sections"]) == 0, "More subsections than expected (1)"
    sb["type"] = "ability"
    sb["ability_type"] = "universal_monster_ability"
    return sb


_MA_ADDON_LABELS = {
    "Frequency",
    "Trigger",
    "Effect",
    "Duration",
    "Requirement",
    "Requirements",
    "Prerequisite",
    "Cost",
    "Range",
}


def section_pass(struct):
    """Extract structured fields from the monster ability text.

    Keeps source extraction (custom child-walking logic) in-house,
    delegates everything else to the unified ability parser.
    """

    def _fix_name(section):
        bs = BeautifulSoup(str(section["name"]), "html.parser")
        section["name"] = get_text(bs).strip()

    def _handle_source(section):
        def _extract_source_info(children):
            if type(children[0]) != Tag:
                return None
            if get_text(children[0]).strip() == "Source":
                children.pop(0).decompose()
                a = children.pop(0)
                source = extract_source(a)
                a.decompose()
                if children and children[0].name == "sup":
                    sup = children.pop(0)
                    errata = extract_link(sup.find("a"))
                    source["errata"] = errata[1]
                    sup.decompose()
                return source
            return None

        if "text" not in section:
            return
        bs = BeautifulSoup(section["text"].strip(), "html.parser")
        children = list(bs.children)
        # Strip leading br/hr
        while children and is_tag_named(children[0], ["br", "hr"]):
            children.pop(0).decompose()
        children = [c for c in children if str(c).strip() != ""]
        source = _extract_source_info(children)
        if source:
            section["sources"] = [source]
        # Strip leading br/hr again after source removal
        while children and is_tag_named(children[0], ["br", "hr"]):
            children.pop(0).decompose()
        section["text"] = str(bs)

    def _extract_action_and_strip(section):
        """Extract action type from leading spans, remove them from text.

        Must run before _handle_source so the <b>Source</b> tag is the
        first child. Returns extracted action_type or None.
        """
        if "text" not in section:
            return None
        text, action_type = extract_action_type(section["text"])
        section["text"] = text
        return action_type

    _fix_name(struct)
    extracted_action = _extract_action_and_strip(struct)
    _handle_source(struct)

    text = struct.get("text", "")
    if not text:
        return

    # Delegate to unified ability parser
    ability = parse_ability_from_html(
        struct["name"],
        text,
        ability_type="universal_monster_ability",
        action_type=extracted_action,
        addon_labels=_MA_ADDON_LABELS,
    )

    # Merge extracted fields into top-level struct
    _MERGE_FIELDS = (
        "action_type",
        "traits",
        "requirement",
        "prerequisite",
        "trigger",
        "effect",
        "frequency",
        "duration",
        "cost",
        "range",
        "text",
        "links",
        "critical_success",
        "success",
        "failure",
        "critical_failure",
    )
    for key in _MERGE_FIELDS:
        if key in ability:
            struct[key] = ability[key]
    if "text" not in ability:
        struct.pop("text", None)
