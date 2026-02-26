import json
import os
import sys

from bs4 import BeautifulSoup

from pfsrd2.constants import ORC_LICENSE
from pfsrd2.data import get_data
from pfsrd2.sql import get_db_path
from universal.files import char_replace, makedirs
from universal.universal import entity_pass, parse_universal, remove_empty_sections_pass

# TODO markdown the licenses


def parse_license(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write(f"{basename}\n")
    details = parse_universal(filename, max_title=4, cssclass="main")
    ogl, sec8 = ogl_pass(details)
    ogl["sections"] = entity_pass(sec8)
    additional_sections_pass(ogl)
    remove_empty_sections_pass(ogl)
    basename.split("_")
    # if not options.skip_schema:
    # validate_against_schema(struct, "trait.schema.json")
    if not options.dryrun:
        output = options.output
        jsondir = makedirs(output, "license")
        write_license(jsondir, ogl)
    elif options.stdout:
        print(json.dumps(ogl, indent=2))


def ogl_pass(details):
    license = details[1]["sections"][0]
    # HTML5 update: Section 8 entries are now parsed as subsections (h3 tags)
    # instead of being in a separate ctl00_RadDrawer1_Content_MainContent_FullSourcesLabel span
    sec8 = license.pop("sections", [])
    bs = BeautifulSoup(license["text"].strip(), "html.parser")
    # Remove old ASP.NET elements if present (pre-HTML5 compatibility)
    span = bs.find(id="ctl00_RadDrawer1_Content_MainContent_FullSourcesLabel")
    if span:
        span.decompose()
    if bs.table:
        bs.table.decompose()
    # Find the last <p> tag (COPYRIGHT NOTICE) to append Masterwork Tools attribution
    last_p = bs.find_all("p")[-1]
    new_b = bs.new_tag("b")
    new_b.string = "Pathfinder Open Reference"
    last_p.append(new_b)
    last_p.append(". © 2023 Masterwork Tools LLC, Authors: Devon Jones, Monica Jones.")
    license["text"] = str(bs).strip()
    return license, sec8


def additional_sections_pass(ogl):
    added_sections = get_data("additional_ogl.json")
    section_names = [s["name"] for s in ogl["sections"]]
    for section in added_sections:
        assert section["name"] not in section_names, "Section 8 conflict: {}".format(
            section["name"]
        )
        ogl["sections"].append(section)


def write_license(jsondir, struct):
    print("{}: {}".format("license", struct["name"]))
    filename = create_license_filename(jsondir, struct)
    fp = open(filename, "w")
    json.dump(struct, fp, indent=4)
    fp.close()


def create_license_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct["name"]) + ".json"
    return os.path.abspath(title)


def get_license(license, attribution_section, sec_8, sources):
    new_sec_8 = []
    missing_sources = []
    for source in sources:
        found = False
        for sec in sec_8:
            if sec["name"] == source["name"]:
                new_sec_8.append(sec)
                found = True
                break
        if not found:
            missing_sources.append(source["name"])
    if missing_sources:
        for name in missing_sources:
            print(f"Warning: Source not found in license: {name}")
    attribution_section["sections"] = new_sec_8
    return license


def get_orc_license(sources):
    def _get_sec_8():
        path = get_db_path("open_game_license_version_10a.json")
        with open(path) as f:
            license_data = json.load(f)
        return license_data["sections"]

    license = ORC_LICENSE
    sec_8 = _get_sec_8()
    result = get_license(license, license["sections"][0], sec_8, sources)
    for source in sources:
        found = any(sec["name"] == source["name"] for sec in sec_8)
        if not found:
            print(f"Could not find source in license: {source['name']}")
    return result


def get_ogl_license(sources):
    path = get_db_path("open_game_license_version_10a.json")
    with open(path) as f:
        license_data = json.load(f)
    license = license_data
    license["subtype"] = "license"
    license["license"] = license["name"]
    sec_8 = license_data["sections"]
    result = get_license(license, license, sec_8, sources)
    for source in sources:
        found = any(sec["name"] == source["name"] for sec in sec_8)
        if not found:
            print(f"Could not find source in license: {source['name']}")
    return result


def license_pass(struct):
    if "edition" in struct and struct["edition"] == "remastered":
        license = get_orc_license(struct["sources"])
    else:
        license = get_ogl_license(struct["sources"])
    struct["license"] = license


def license_consolidation_pass(struct):
    def _get_licenses(struct):
        retlist = []
        if "license" in struct:
            retlist.append(struct["license"])
            del struct["license"]
        for _k, v in struct.items():
            if isinstance(v, dict):
                retlist.extend(_get_licenses(v))
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        retlist.extend(_get_licenses(item))
        return retlist

    licenses = _get_licenses(struct)
    ogl = licenses.pop(0)
    for sl in licenses:
        section_names = [s["name"] for s in ogl["sections"]]
        for section in sl["sections"]:
            if section["name"] not in section_names:
                ogl["sections"].append(section)
    struct["license"] = ogl
