import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from universal.universal import parse_universal, entity_pass
from universal.universal import extract_link
from universal.universal import source_pass, extract_source, get_links
from universal.universal import aon_pass, restructure_pass
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.universal import build_object
from universal.markdown import md
from universal.files import makedirs, char_replace
from universal.utils import get_text, bs_pop_spaces
from universal.utils import log_element, get_unique_tag_set
from pfsrd2.schema import validate_against_schema
from pfsrd2.license import license_pass


def parse_condition(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(
        filename, max_title=4,
        cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput",
        pre_filters=[sidebar_filter])
    details = entity_pass(details)
    struct = restructure_condition_pass(details)
    condition_struct_pass(struct)
    source_pass(struct, find_condition)
    subtype_pass(struct)
    condition_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, 'condition', find_condition)
    remove_empty_sections_pass(struct)
    game_id_pass(struct)
    condition_cleanup_pass(struct)
    license_pass(struct)
    markdown_pass(struct, struct["name"], '')
    basename.split("_")
    if not options.skip_schema:
        validate_against_schema(struct, "condition.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, struct['game-obj'], name)
            write_condition(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def sidebar_filter(soup):
    divs = soup.find_all("div", {"class": "sidebar-nofloat"})
    for div in divs:
        div.unwrap()


def restructure_condition_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)
    top = {'name': sb['name'], 'type': 'condition', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    sb['subtype'] = 'condition'
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []
    return top


def find_condition(struct):
    for section in struct['sections']:
        if section['subtype'] == 'condition':
            return section


def condition_struct_pass(struct):
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

    for section in struct['sections']:
        sources = _extract_source(section)
        section['sources'] = sources


def subtype_pass(struct):
    struct['subtype'] = 'standard'
    for source in struct['sources']:
        if source['name'] == "Kingmaker Adventure Path":
            struct['subtype'] = 'kingdom'
            return


def condition_link_pass(struct):
    def _handle_text_field(section, field, keep=True):
        if field not in section:
            return
        bs = BeautifulSoup(section[field], "html.parser")
        links = get_links(bs)
        if len(links) > 0 and keep:
            linklist = section.setdefault('links', [])
            linklist.extend(links)
        while bs.a:
            bs.a.unwrap()
        section[field] = str(bs)

    for section in struct['sections']:
        _handle_text_field(section, "name", False)
        _handle_text_field(section, "text")
        if 'sections' in section:
            condition_link_pass(section)


def condition_cleanup_pass(struct):
    def _clean_text():
        soup = BeautifulSoup(condition['text'], "html.parser")
        first = list(soup.children)[0]
        if first.name == "i":
            text = get_text(first)
            if text.find("Note from Nethys:") > -1:
                first.clear()
            first.unwrap()
        struct['name'] = condition['name']
        del condition['name']
        condition['text'] = str(soup).strip()
        if condition['text'] != "":
            assert 'text' not in struct, struct
            struct['text'] = html2markdown.convert(condition['text'])
        del condition['text']

    def _clean_sections():
        def _clean_html(section):
            if 'html' in section:
                section['text'] = section['html']
                del section['html']
            if 'sections' in section:
                for s in section['sections']:
                    _clean_html(s)

        if len(condition['sections']) != 0:
            struct['sections'] = condition['sections']
        del condition['sections']
        if 'sections' in struct:
            for section in struct['sections']:
                _clean_html(section)

    def _clean_links():
        if condition.get('links'):
            assert 'links' not in struct, struct
            struct['links'] = condition['links']
            del condition['links']

    def _clean_misc():
        struct['sources'] = condition['sources']
        del condition['sources']
        del condition['type']
        del condition['subtype']

    condition = struct['condition']
    _clean_text()
    _clean_sections()
    _clean_links()
    _clean_misc()
    assert len(condition) == 0, condition
    del struct['condition']


def write_condition(jsondir, struct, source):
    print("%s (%s): %s" % (struct['game-obj'], source, struct['name']))
    filename = create_condition_filename(jsondir, struct)
    fp = open(filename, 'w')
    json.dump(struct, fp, indent=4)
    fp.close()


def create_condition_filename(jsondir, struct):
    title = jsondir + "/" + char_replace(struct['name']) + ".json"
    return os.path.abspath(title)


def markdown_pass(struct, name, path):
    def _validate_acceptable_tags(text):
        validset = set(['i', 'b', 'u', 'strong', 'ol', 'ul', 'li', 'br',
                        'table', 'tr', 'td', 'hr'])
        if "license" in struct:
            validset.add('p')
        tags = get_unique_tag_set(text)
        assert tags.issubset(validset), "%s : %s - %s" % (name, text, tags)

    for k, v in struct.items():
        if isinstance(v, dict):
            markdown_pass(v, name, "%s/%s" % (path, k))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    markdown_pass(item, name, "%s/%s" % (path, k))
                elif isinstance(item, str):
                    if item.find("<") > -1:
                        assert False  # For now, I'm unaware of any tags in lists of strings
        elif isinstance(v, str):
            if v.find("<") > -1:
                _validate_acceptable_tags(v)
                struct[k] = md(v).strip()
                log_element("markdown.log")("%s : %s" %
                                            ("%s/%s" % (path, k), name))


def extract_starting_traits(description):
    if description.strip().startswith("("):
        return _extract_trait(description)
    return description, []


def extract_span_traits(text):
    bs = BeautifulSoup(text, 'html.parser')
    children = list(bs.children)
    newchildren = []
    traits = []
    while len(children) > 0:
        child = children.pop(0)
        if child.name == "span":  # and child["class"] == "trait":
            content = child.contents
            assert len(content) == 1, content
            a = content[0]
            name, trait_link = extract_link(a)
            traits.append(build_object(
                'stat_block_section',
                'trait',
                name.strip(),
                {'link': trait_link}))
        else:
            newchildren.append(child)
            newchildren.extend(children)
            break
    text = "".join([str(c) for c in newchildren]).strip()
    return text, traits


def extract_all_traits(description):
    traits = []
    while description.find("(") > -1:
        description, ts = _extract_trait(description)
        traits.extend(ts)
    return description, traits


def _extract_trait(description):
    def _handle_trait_template(text):
        text = text.strip()
        if not text.startswith("["):
            return
        assert text.endswith("]")
        text = text[1:-1]
        template = build_object('trait_template', "", text)
        del template['subtype']
        return template

    traits = []
    newdescription = []
    if description.find("(") > -1:
        front, middle = description.split("(", 1)
        newdescription.append(front)
        s = middle.split(")", 1)
        assert len(s) == 2, s
        text, back = s
        bs = BeautifulSoup(text, 'html.parser')
        if bs.a and bs.a.has_attr('game-obj') and bs.a['game-obj'] == 'Traits':
            if text.find(" or ") > -1:
                return description, []
            parts = [p.strip() for p in text.replace("(", "").split(",")]
            for part in parts:
                bs = BeautifulSoup(part, 'html.parser')
                children = list(bs.children)
                assert len(children) == 1, part
                child = children[0]
                template = _handle_trait_template(str(child))
                if template:
                    traits.append(template)
                else:
                    name, trait_link = extract_link(child)
                    traits.append(build_object(
                        'stat_block_section',
                        'trait',
                        name.strip(),
                        {'link': trait_link}))
        else:
            newdescription.append(text)
            newdescription.append(")")
        description = back
    newdescription.append(description)
    return ''.join(newdescription).strip(), traits
