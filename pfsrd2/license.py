import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from universal.universal import parse_universal, print_struct, entity_pass
from universal.universal import is_trait, extract_link
from universal.utils import split_maintain_parens
from universal.universal import source_pass, extract_source, get_links
from universal.universal import aon_pass, restructure_pass, html_pass
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.creatures import universal_handle_alignment
from universal.files import makedirs, char_replace
from universal.utils import get_text
from pfsrd2.schema import validate_against_schema
from pfsrd2.data import get_data
from pfsrd2.sql import get_db_path
from pfsrd2.constants import ORC_LICENSE

# TODO markdown the licenses


def parse_license(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(filename, max_title=4,
                              cssclass="main")
    ogl = ogl_pass(details)
    sec8 = parse_universal(filename, max_title=4,
                           cssclass="ctl00_RadDrawer1_Content_MainContent_FullSourcesLabel")
    ogl['sections'] = entity_pass(sec8)
    additional_sections_pass(ogl)
    remove_empty_sections_pass(ogl)
    basename.split("_")
    # if not options.skip_schema:
    # validate_against_schema(struct, "trait.schema.json")
    if not options.dryrun:
        output = options.output
        jsondir = makedirs(output, 'license')
        write_license(jsondir, ogl)
    elif options.stdout:
        print(json.dumps(ogl, indent=2))


def ogl_pass(details):
    license = details[1]['sections'][0]
    assert len(license['sections']) == 0
    bs = BeautifulSoup(license['text'].strip(), 'html.parser')
    span = bs.find(id="ctl00_RadDrawer1_Content_MainContent_FullSourcesLabel")
    span.decompose()
    bs.table.decompose()
    children = list(bs.children)
    last_p = children[-2]
    new_b = bs.new_tag("b")
    new_b.string = "Pathfinder Open Reference"
    last_p.append(new_b)
    last_p.append(
        ". © 2023 Masterwork Tools LLC, Authors: Devon Jones, Monica Jones.")
    license['text'] = str(bs).strip()
    return license


def additional_sections_pass(ogl):
    added_sections = get_data("additional_ogl.json")
    section_names = [s['name'] for s in ogl['sections']]
    for section in added_sections:
        assert section['name'] not in section_names, "Section 8 conflict: %s" % section['name']
        ogl['sections'].append(section)


def write_license(jsondir, struct):
    print("%s: %s" % ('license', struct['name']))
    filename = create_license_filename(jsondir, struct)
    fp = open(filename, 'w')
    json.dump(struct, fp, indent=4)
    fp.close()


def create_license_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct['name']) + ".json"
    return os.path.abspath(title)


def get_license(license, sec_8, sources):
    new_sec_8 = []
    for source in sources:
        found = False
        for sec in sec_8:
            if sec['name'] == source['name']:
                new_sec_8.append(sec)
                found = True
                break
        assert found, "Source not found in license: %s" % (source['name'])
    license["sections"] = new_sec_8
    return license


def get_orc_license(sources):
    def _get_sec_8():
        path = get_db_path("open_game_license_version_10a.json")
        with open(path) as f:
            license_data = json.load(f)
        return license_data["sections"]
    license = ORC_LICENSE
    return get_license(license, _get_sec_8(), sources)


def get_ogl_license(sources):
    path = get_db_path("open_game_license_version_10a.json")
    with open(path) as f:
        license_data = json.load(f)
    license = license_data
    license["subtype"] = "license"
    license["license"] = license["name"]
    sec_8 = license_data["sections"]
    return get_license(license, sec_8, sources)


def license_pass(struct):
    if "edition" in struct and struct["edition"] == "remastered":
        license = get_orc_license(struct['sources'])
    else:
        license = get_ogl_license(struct['sources'])
    struct["license"] = license


def license_consolidation_pass(struct):
    def _get_licenses(struct):
        retlist = []
        if 'license' in struct:
            retlist.append(struct['license'])
            del struct['license']
        for k, v in struct.items():
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
        section_names = [s['name'] for s in ogl['sections']]
        for section in sl['sections']:
            if section['name'] not in section_names:
                ogl['sections'].append(section)
    struct['license'] = ogl
