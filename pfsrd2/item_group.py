import os
import json
import sys
from pprint import pprint
from bs4 import BeautifulSoup, Tag
from universal.markdown import markdown_pass
from universal.universal import parse_universal, entity_pass
from universal.universal import extract_link, extract_links, extract_source
from universal.universal import aon_pass, remove_empty_sections_pass, game_id_pass
from universal.utils import is_tag_named, get_text
from universal.files import makedirs, char_replace
from universal.creatures import write_creature
from pfsrd2.schema import validate_against_schema
from pfsrd2.license import license_pass, license_consolidation_pass


def parse_item_group(filename, options):
    """Main parsing function - entry point for the armor/weapon group parser"""
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Determine subtype (armor_group or weapon_group)
    subtype = getattr(options, "subtype", "armor_group")

    # Parse HTML into initial structure
    details = parse_universal(
        filename,
        subtitle_text=True,
        max_title=4,
        cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput",
    )
    details = entity_pass(details)

    # Restructure and process
    struct = restructure_armor_group_pass(details, subtype)
    aon_pass(struct, basename)
    section_pass(struct)
    handle_edition(struct)
    game_id_pass(struct)

    # License information (always include)
    license_pass(struct)
    license_consolidation_pass(struct)

    # Markdown and cleanup
    markdown_pass(struct, struct["name"], "")
    remove_empty_sections_pass(struct)

    # Schema validation and file output
    # Both armor_group and weapon_group use the same schema
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "armor_group.schema.json")
    if not options.dryrun:
        output = options.output
        # Output directory is based on subtype (armor_groups or weapon_groups)
        output_dir = subtype + "s" if not subtype.endswith("s") else subtype
        jsondir = makedirs(output, output_dir)
        write_creature(jsondir, struct, char_replace(struct["name"]))
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def restructure_armor_group_pass(details, subtype="armor_group"):
    """Create the basic structure for armor/weapon group content type"""
    sb = None
    rest = []
    for obj in details:
        if sb is None:
            sb = obj
        else:
            rest.append(obj)

    # Top-level structure - flatten text to top level
    top = {"name": sb["name"], "type": subtype, "text": sb.get("text", ""), "sections": []}

    # Add any additional sections from rest
    top["sections"].extend(rest)

    # Add subsections from main section if they exist
    if len(sb.get("sections", [])) > 0:
        top["sections"].extend(sb["sections"])

    return top


def section_pass(struct):
    """Extract structured data from sections"""

    def _clean_name(section):
        """Clean HTML from name field"""
        if "name" in section:
            bs = BeautifulSoup(str(section["name"]), "html.parser")
            section["name"] = get_text(bs).strip()

        # Also clean names in subsections
        for subsection in section.get("sections", []):
            if "name" in subsection:
                bs = BeautifulSoup(str(subsection["name"]), "html.parser")
                subsection["name"] = get_text(bs).strip()

    def _handle_source(section):
        """Extract source book information"""
        if "text" not in section:
            return

        bs = BeautifulSoup(section["text"].strip(), "html.parser")
        children = list(bs.children)

        # Clear empty tags
        children = [c for c in children if str(c).strip() != ""]

        if not children or not isinstance(children[0], Tag):
            return

        # Look for "Source" tag
        if get_text(children[0]).strip() == "Source":
            children.pop(0).decompose()
            a = children.pop(0)
            source = extract_source(a)
            a.decompose()

            # Check for errata
            if children and children[0].name == "sup":
                sup = children.pop(0)
                errata = extract_link(sup.find("a"))
                source["errata"] = errata[1]
                sup.decompose()

            section["sources"] = [source]

        section["text"] = str(bs)

    def _clear_garbage(section):
        """Remove unwanted HTML elements"""
        if "text" not in section:
            return
        if section["text"] == "":
            del section["text"]
            return

        bs = BeautifulSoup(section["text"].strip(), "html.parser")

        # Remove details tags
        while bs.details:
            bs.details.decompose()

        children = list(bs.children)
        if children and children[0].name == "br":
            children.pop(0).decompose()

        section["text"] = str(bs)

        # Recursively clean subsections
        for s in section.get("sections", []):
            _clear_garbage(s)

    def _remove_backlinks(section):
        """Remove Weapons/Armor backlink lists from text"""
        if "text" not in section:
            return

        bs = BeautifulSoup(section["text"].strip(), "html.parser")

        # Find and remove "Weapons" or "Armor" sections (backlinks)
        for bold in bs.find_all("b"):
            bold_text = get_text(bold).strip()
            if bold_text in ["Weapons", "Armor"]:
                # Remove everything from this bold tag onwards
                # Get all following siblings and remove them
                following = list(bold.next_siblings)
                for sibling in following:
                    if hasattr(sibling, "decompose"):
                        sibling.decompose()
                    elif isinstance(sibling, str):
                        sibling.replace_with("")
                bold.decompose()
                break

        section["text"] = str(bs)

    def _clear_links(section):
        """Extract links into structured format"""
        text = section.setdefault("text", "")
        links = section.setdefault("links", [])
        text, links = extract_links(text)
        section["text"] = text
        section["links"] = links
        if len(links) == 0:
            del section["links"]

    _clean_name(struct)
    _handle_source(struct)
    _clear_garbage(struct)
    _remove_backlinks(struct)
    _clear_links(struct)


def handle_edition(struct):
    """Determine if armor group is legacy or remastered based on sections"""
    struct["edition"] = "remastered"
    # Check if there's a Legacy Content section
    for section in struct["sections"]:
        if section.get("name") == "Legacy Content":
            struct["edition"] = "legacy"
            break
