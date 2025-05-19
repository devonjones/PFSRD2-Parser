import os
import sys
import json
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from universal.universal import parse_universal, entity_pass
from universal.universal import restructure_pass, html_pass, aon_pass
from universal.universal import source_pass, game_id_pass, get_links
from pfsrd2.schema import validate_against_schema
from dateutil import parser as dateparser
from universal.files import makedirs, char_replace
from hashlib import md5
from pfsrd2.license import get_ogl_license, get_orc_license

def parse_source(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    struct = {"name": basename, "type": "source"}
    details = parse_universal(filename, subtitle_text=True, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)
    struct = restructure_source_pass(details)
    drop_contents_pass(struct)
    source_struct_pass(struct)
    source_pass(struct, find_source)
    aon_pass(struct, basename)
    game_id_pass_source(struct)
    restructure_pass(struct, 'source', find_source)
    link_pass(struct)
    convert_entities_pass(struct)
    extract_product_page_fields_pass(struct)
    normalize_release_date_pass(struct)
    set_edition_by_date_pass(struct)
    license_pass_source(struct)
    remove_empty_sections_pass(struct)
    drop_sources_fields_pass(struct)
    if not options.skip_schema:
        struct["schema_version"] = 1.0
        validate_against_schema(struct, "source.schema.json")
    if not options.dryrun:
        output = options.output
        jsondir = makedirs(output, struct['game-obj'])
        write_source(jsondir, struct)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def source_struct_pass(struct):
    def _extract_source(section):
        if 'text' in section:
            bs = BeautifulSoup(section['text'], 'html.parser')
            children = list(bs.children)
            if children[0].name == "b" and get_text(children[0]) == "Source":
                children.pop(0)
                bs_pop_spaces(children)
                book = children.pop(0)
                source = extract_source(book)
                bs_pop_spaces(children)
                if children[0].name == "sup":
                    assert 'errata' not in source, "Should be no more than one errata."
                    _, source['errata'] = extract_link(
                        children.pop(0).find("a"))
                if children[0].name == "br":
                    children.pop(0)
                assert children[0].name != "a", section
                section['text'] = ''.join([str(c) for c in children])
                return [source]

    def _handle_legacy(struct):
        struct['edition'] = 'remastered'
        if len(struct['sections']) == 1:
            return
        if struct['sections'][1]['name'] == 'Legacy Content':
            lc = struct['sections'].pop(1)
            struct['edition'] = 'legacy'
            del lc['name']
            del lc['type']
            sec = struct['sections'][0]
            sec['text'] = lc['text']
            del lc['text']
            sec['sources'] = lc['sources']
            del lc['sources']
            sec['sections'].extend(lc['sections'])
            del lc['sections']
            assert len(lc) == 0, lc

    for section in struct['sections']:
        sources = _extract_source(section)
        section['sources'] = sources

    _handle_legacy(struct)

def restructure_source_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)
    top = {'name': sb['name'], 'type': 'source', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []
    return top

def drop_contents_pass(struct):
    struct['sections'] = struct['sections'][:2]

def find_source(struct):
    for section in struct['sections']:
        if section['type'] == 'stat_block_section':
            return section
    return None

def link_pass(struct):
    def _handle_text_field(field, keep=True):
        bs = BeautifulSoup(struct[field], "html.parser")
        links = get_links(bs)
        if len(links) > 0 and keep:
            linklist = struct.setdefault('links', [])
            linklist.extend(links)
        while bs.a:
            bs.a.unwrap()
        struct[field] = str(bs)

    _handle_text_field("name", False)

def extract_product_page_fields_pass(struct):
    # Only run if there is at least one section
    if not struct.get('sections') or not struct['sections']:
        return
    section = struct['sections'][0]
    text = section.get('text', '')
    if not text:
        return
    bs = BeautifulSoup(text, 'html.parser')
    # Extract fields from the HTML
    for tag in bs.find_all(['b', 'u', 'i', 'a', 'br']):
        if tag.name == 'b':
            label = tag.get_text(strip=True)
            next_sib = tag.next_sibling
            if label == 'Latest Errata' and next_sib:
                # Find the next <a> for errata version
                a = tag.find_next('a')
                if a:
                    version_text = a.get_text(strip=True)
                    try:
                        version = float(version_text)
                    except Exception:
                        version = None
                    # Try to extract the date after the dash
                    errata_date = None
                    if a.next_sibling:
                        after = a.next_sibling
                        if isinstance(after, str) and '-' in after:
                            date_part = after.split('-', 1)[-1].strip()
                            try:
                                date_obj = dateparser.parse(date_part, fuzzy=True)
                                errata_date = date_obj.date().isoformat()
                            except Exception:
                                errata_date = date_part
                    struct['errata'] = {"version": version, "errata_date": errata_date}
            elif label == 'Release Date' and next_sib:
                # The release date is after the <b>Release Date</b>
                date = next_sib.strip() if isinstance(next_sib, str) else ''
                struct['release_date'] = date
            elif label == 'Product Line' and next_sib:
                line = next_sib.strip() if isinstance(next_sib, str) else ''
                struct['product_line'] = line
    # Optionally extract other fields (e.g., notes in <i>)
    i_tag = bs.find('i')
    if i_tag:
        struct['note'] = i_tag.get_text(strip=True)
    # Remove the section after extracting fields
    struct['sections'] = struct['sections'][1:]

def normalize_release_date_pass(struct):
    date_str = struct.get('release_date')
    if not date_str:
        return
    try:
        dt = dateparser.parse(date_str, fuzzy=True)
        struct['release_date'] = dt.date().isoformat()
    except Exception:
        pass

def set_edition_by_date_pass(struct):
    date_str = struct.get('release_date')
    if not date_str:
        return
    try:
        dt = dateparser.parse(date_str)
        cutoff = dateparser.parse('2023-08-01')
        if dt < cutoff:
            struct['edition'] = 'legacy'
    except Exception:
        pass

def game_id_pass_source(struct):
    # Use only the source name and aonid for the game-id
    name = struct['name']
    aonid = struct.get('aonid', '')
    pre_id = f"{name}:{aonid}"
    struct['game-id'] = md5(pre_id.encode()).hexdigest()

def remove_empty_sections_pass(struct):
    if 'sections' in struct:
        # Remove empty sections from children first
        struct['sections'] = [s for s in struct['sections'] if s and (s.get('sections') or s.get('text') or s.get('name'))]
        for section in struct['sections']:
            remove_empty_sections_pass(section)
        # Remove the sections key if now empty
        if not struct['sections']:
            del struct['sections']

def drop_sources_fields_pass(struct):
    if 'sources' in struct:
        del struct['sources']
    if 'source' in struct:
        del struct['source']

def write_source(jsondir, struct):
    print("%s: %s" % (struct['game-obj'], struct['name']))
    filename = create_source_filename(jsondir, struct)
    fp = open(filename, 'w')
    json.dump(struct, fp, indent=4)
    fp.close()

def create_source_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct['name']) + ".json"
    return os.path.abspath(title)

def license_pass_source(struct):
    try:
        # Add a license object to the struct, using OGL for legacy and ORC for remastered
        if struct.get('edition') == 'legacy':
            # Use get_ogl_license to build the license, passing the current struct as the only source
            struct['license'] = get_ogl_license([struct])
            struct['license']['sections'].append(
                {
                    "name": "Pathfinder Open Reference",
                    "type": "section",
                    "text": "<bPathfinder Open Reference</b> © 2023 Masterwork Tools LLC, Authors: Devon Jones, Monica Jones."
                }
            )
        else:
            struct['license'] = get_orc_license([struct])
    except Exception as e:
        print(f"Error in license_pass_source: {e}")
        print(f"Struct: {struct}")

def convert_entities_pass(struct):
    # Convert HTML entities in the name to their character equivalent
    if 'name' in struct and struct['name']:
        bs = BeautifulSoup(struct['name'], 'html.parser')
        struct['name'] = bs.get_text()
