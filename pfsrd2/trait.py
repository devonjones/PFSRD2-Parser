import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from universal.universal import parse_universal, print_struct, entity_pass
from universal.universal import extract_link, nethys_search_pass
from universal.universal import source_pass, extract_source, get_links
from universal.universal import aon_pass, restructure_pass, html_pass
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.universal import build_object, extract_links
from universal.creatures import universal_handle_alignment
from universal.markdown import md
from universal.files import makedirs, char_replace
from universal.utils import get_text, bs_pop_spaces
from universal.utils import log_element, get_unique_tag_set
from pfsrd2.schema import validate_against_schema
from pfsrd2.license import license_pass


def parse_trait(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(filename, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)
    alternate_link = handle_alternate_link(details)
    details = nethys_search_pass(details)
    struct = restructure_trait_pass(details)
    if alternate_link:
        struct["alternate_link"] = alternate_link
    trait_struct_pass(struct)
    source_pass(struct, find_trait)
    trait_link_pass(struct)
    aon_pass(struct, basename)
    restructure_pass(struct, 'trait', find_trait)
    classlist = list_removal_pass(struct, [])
    trait_class_pass(struct, classlist)
    remove_empty_sections_pass(struct)
    html_pass(struct)
    game_id_pass(struct)
    trait_cleanup_pass(struct)
    license_pass(struct)
    markdown_pass(struct, struct["name"], '')
    basename.split("_")
    if not options.skip_schema:
        struct["schema_version"] = 1.1
        validate_against_schema(struct, "trait.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, struct['game-obj'], name)
            write_trait(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def handle_alternate_link(details):
    d = details[0]
    if "Legacy version" in d or "Remastered version" in d:
        details.pop(0)
        text, links = extract_links(d)
        bs = BeautifulSoup(text.strip(), 'html.parser')
        assert len(list(bs.children)) == 1, bs
        div = list(bs.children)[0]
        assert div.name == "div", div
        assert list(div.children)[0].__class__ == NavigableString, bs
        text = get_text(div)
        assert len(links) == 1, links
        link = links[0]
        del link['alt']
        del link['name']
        link['type'] = 'alternate_link'
        if "Legacy version" in d:
            link['alternate_type'] = 'legacy'
        else:
            link['alternate_type'] = 'remastered'
        return link


def restructure_trait_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)
    top = {'name': sb['name'], 'type': 'trait', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    sb['subtype'] = 'trait'
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []
    return top


def trait_parse(span):
    def _check_type_trait(trait_class, name):
        types = [
            "Aberration", "Animal", "Astral", "Beast", "Celestial", "Construct",
            "Dragon", "Dream", "Elemental", "Ethereal", "Fey", "Fiend",
            "Fungus", "Giant", "Humanoid", "Monitor", "Ooze", "Petitioner",
            "Plant", "Undead"
        ]
        if name in types:
            return "creature_type"
        else:
            return trait_class

    def _alingment_trait(trait):
        align = universal_handle_alignment(trait['name'])
        if align == 'Any Alignment':
            align = 'Any'
        trait['name'] = align
        trait['link']['alt'] = align

    name = ''.join(get_text(span)).replace(" Trait", "")
    trait_class = ''.join(span['class'])
    if trait_class != 'trait':
        trait_class = trait_class.replace('trait', '')
    if trait_class == 'trait':
        trait_class = _check_type_trait(trait_class, name)
    trait = {
        'name': name,
        'classes': [trait_class],
        'type': 'stat_block_section',
        'subtype': 'trait'}
    c = list(span.children)
    if len(c) == 1:
        if c[0].name == "a":
            _, link = extract_link(c[0])
            trait['link'] = link
    else:
        raise Exception("You should not be able to get here")
    if trait_class == "alignment":
        _alingment_trait(trait)
    return trait


def find_trait(struct):
    for section in struct['sections']:
        if section['subtype'] == 'trait':
            return section


def trait_struct_pass(struct):
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
        if len(struct['sections']) == 1:
            struct['edition'] = 'remastered'
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


def trait_class_pass(struct, classlist):
    classlist = list(set(classlist))
    classlist = [c.lower() for c in classlist]
    classlist = [c.replace(' ', '_') for c in classlist]
    trait = struct['trait']
    if len(classlist):
        trait['classes'] = classlist


def trait_link_pass(struct):
    def _handle_text_field(field, keep=True):
        bs = BeautifulSoup(trait[field], "html.parser")
        links = get_links(bs)
        if len(links) > 0 and keep:
            linklist = trait.setdefault('links', [])
            linklist.extend(links)
        while bs.a:
            bs.a.unwrap()
        trait[field] = str(bs)

    trait = find_trait(struct)
    _handle_text_field("name", False)
    _handle_text_field("text")


def list_removal_pass(struct, classlist):
    for section in struct['sections']:
        if 'sections' in section:
            list_removal_pass(section, classlist)
        text = "".join(section['text'].split(", "))
        soup = BeautifulSoup(text, "html.parser")
        r = True
        for c in list(soup.children):
            if c.name != "a":
                assert False, section['text']
                r = False
        if r:
            section['text'] = ''
    classlist.extend([s['name']
                     for s in struct['sections'] if s['text'] == ""])
    struct['sections'] = [s for s in struct['sections'] if s['text'] != ""]
    return classlist


def trait_cleanup_pass(struct):
    def _clean_text():
        soup = BeautifulSoup(trait['text'], "html.parser")
        first = list(soup.children)[0]
        if first.name == "i":
            text = get_text(first)
            if text.find("Note from Nethys:") > -1:
                first.clear()
            first.unwrap()
        struct['name'] = trait['name']
        trait['text'] = str(soup).strip()
        if trait['text'] != "":
            assert 'text' not in struct, struct
            struct['text'] = html2markdown.convert(trait['text'])
        del trait['text']

    def _clean_sections():
        if len(trait['sections']) == 0:
            del trait['sections']
        else:
            assert False, struct
        assert 'sections' not in struct, struct

    def _clean_classes():
        if trait.get('classes'):
            struct['classes'] = trait['classes']
            struct['classes'].sort()
            del trait['classes']

    def _clean_links():
        if trait.get('links'):
            assert 'links' not in struct, struct
            struct['links'] = trait['links']
            del trait['links']

    def _clean_basics():
        del trait['name']
        del trait['type']
        del trait['subtype']
        del trait['sources']

    trait = struct['trait']
    _clean_text()
    _clean_sections()
    _clean_classes()
    _clean_links()
    _clean_basics()
    assert len(trait) == 0, trait
    del struct['trait']


def write_trait(jsondir, struct, source):
    print("%s (%s): %s" % (struct['game-obj'], source, struct['name']))
    filename = create_trait_filename(jsondir, struct)
    fp = open(filename, 'w')
    json.dump(struct, fp, indent=4)
    fp.close()


def create_trait_filename(jsondir, struct):
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
