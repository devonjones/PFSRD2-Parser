import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup, Tag
from universal.markdown import markdown_pass
from universal.universal import parse_universal, entity_pass
from universal.universal import extract_link
from universal.universal import extract_source
from universal.universal import aon_pass
from universal.universal import remove_empty_sections_pass
from universal.universal import walk, test_key_is_value
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.files import makedirs, char_replace
from universal.creatures import write_creature
from universal.creatures import universal_handle_range
from universal.utils import is_tag_named, get_text
from universal.utils import get_text
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import extract_starting_traits
from pfsrd2.license import license_pass, license_consolidation_pass
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name


def parse_monster_ability(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(filename, subtitle_text=True, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)
    struct = restructure_monster_ability_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)
    addon_pass(struct)
    trait_db_pass(struct)
    game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    markdown_pass(struct, struct["name"], '')
    remove_empty_sections_pass(struct)
    basename.split("_")
    if not options.skip_schema:
        struct['schema_version'] = 1.2
        validate_against_schema(struct, "monster_ability.schema.json")
    if not options.dryrun:
        output = options.output
        for source in struct['sources']:
            name = char_replace(source['name'])
            jsondir = makedirs(output, 'monster_abilities', name)
            write_creature(jsondir, struct, name)
    elif options.stdout:
        print(json.dumps(struct, indent=2))


def restructure_monster_ability_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)
    assert len(rest) == 0, "More sections than expected (1)"
    assert len(sb['sections']) == 0, "More subsections than expected (1)"
    sb['type'] = 'ability'
    sb['ability_type'] = 'universal_monster_ability'
    return sb


def section_pass(struct):
    def _handle_front_spans(section):
        def _handle_action(section, tag):
            action = build_action(tag)
            assert action, tag
            section['action_type'] = action
            tag.decompose()

        def _tag_is_action(tag):
            assert 'class' in tag.attrs, tag
            tag_class = tag['class']
            if "action" in tag_class:
                return True
            return False

        if 'text' not in section:
            return
        bs = BeautifulSoup(section['text'].strip(), 'html.parser')
        children = list(bs.children)
        while children and is_tag_named(children[0], ['span']):
            tag = children.pop(0)
            if _tag_is_action(tag):
                _handle_action(section, tag)
            else:
                assert False, tag
        section['text'] = str(bs)

    def _fix_name(section):
        bs = BeautifulSoup(str(section['name']), 'html.parser')
        section['name'] = get_text(bs).strip()

    def _handle_traits(section):
        text, traits = extract_starting_traits(section['text'])
        section['text'] = text
        if traits:
            section['traits'] = traits

    def _clear_links(section):
        text = section.setdefault('text', "")
        links = section.setdefault('links', [])
        bs = BeautifulSoup(text, 'html.parser')
        while bs.a:
            _, link = extract_link(bs.a)
            links.append(link)
            bs.a.unwrap()
        section['text'] = str(bs)
        if len(links) == 0:
            del section['links']

    def _handle_source(section):
        def _extract_source_info(children):
            if not type(children[0]) == Tag:
                return None

            if get_text(children[0]).strip() == "Source":
                children.pop(0).decompose()
                a = children.pop(0)
                source = extract_source(a)
                a.decompose()
                if children and children[0].name == "sup":
                    sup = children.pop(0)
                    errata = extract_link(sup.find("a"))
                    source['errata'] = errata[1]
                    sup.decompose()
                return source

            return None

        if 'text' not in section:
            return

        bs = BeautifulSoup(section['text'].strip(), 'html.parser')
        children = list(bs.children)

        _clear_bad_tags(children)
        children = _clear_empty_tags(children)
        source = _extract_source_info(children)
        if source:
            section['sources'] = [source]
        _clear_bad_tags(children)
        section['text'] = str(bs)

    def _clear_empty_tags(children):
        return [c for c in children if str(c).strip() != '']

    def _clear_bad_tags(children, direction=0):
        while children and is_tag_named(children[direction], ['br', 'hr']):
            children.pop(0).decompose()

    def _clear_garbage(section):
        if 'text' not in section:
            return
        if section['text'] == '':
            del section['text']
            return
        bs = BeautifulSoup(section['text'].strip(), 'html.parser')
        children = list(bs.children)
        _clear_bad_tags(children)
        _clear_bad_tags(children, -1)
        section['text'] = str(bs)

    _fix_name(struct)
    _handle_front_spans(struct)
    _handle_source(struct)
    _handle_traits(struct)
    _clear_links(struct)
    _clear_garbage(struct)


def build_action(child, action=None):
    assert not action, "Multiple actions detected: %s" % child
    action_name = child['title']
    action = build_object(
        'stat_block_section',
        'action_type',
        action_name)
    if action_name == 'Single Action':
        action["name"] = "One Action"
    return action


def build_object(dtype, subtype, name, keys=None):
    assert type(name) is str
    obj = {
        'type': dtype,
        'subtype': subtype,
        'name': name.strip()
    }
    if keys:
        obj.update(keys)
    return obj


def addon_pass(struct):
    def _oa_html_reduction(data):
        bs = BeautifulSoup(''.join(data).strip(), 'html.parser')
        if (list(bs.children)[-1].name == 'br'):
            list(bs.children)[-1].unwrap()
        return str(bs)

    def _handle_ranges(addons):
        for k, v in addons.items():
            if k == 'range':
                assert len(v) == 1, "Malformed range: %s" % v
                struct['range'] = universal_handle_range(v[0])
            else:
                struct[k] = _oa_html_reduction(v)

    def _get_prospective_name(child):
        current = get_text(child).strip()
        if current == "Requirements":
            current = "Requirement"
        return current

    def _create_addon(current, child):
        addon_names = ["Frequency", "Trigger", "Effect", "Duration",
                       "Requirement", "Requirements", "Prerequisite", "Critical Success",
                       "Success", "Failure", "Critical Failure", "Range", "Cost"]
        assert current in addon_names, "%s, %s" % (current, text)
        addon_text = str(child)
        if addon_text.strip().endswith(";"):
            addon_text = addon_text.rstrip()[:-1]
        addons.setdefault(
            current.lower().replace(" ", "_"), []).append(addon_text)

    def _set_struct_text(struct, parts):
        if len(parts) > 0:
            struct['text'] = _oa_html_reduction(parts)
        else:
            del struct['text']

    text = struct['text']
    bs = BeautifulSoup(text, 'html.parser')
    children = list(bs)
    addons = {}
    current = None
    parts = []
    while len(children) > 0:
        child = children.pop(0)
        if child.name == 'b':
            current = _get_prospective_name(child)
        elif current:
            _create_addon(current, child)
        else:
            parts.append(str(child))
    _handle_ranges(addons)
    _set_struct_text(struct, parts)


def trait_db_pass(struct):
    # TODO: Copied from creature.py
    def _merge_classes(trait, db_trait):
        trait_classes = set(trait.get('classes', []))
        db_trait_classes = set(db_trait.get('classes', []))
        db_trait['classes'] = list(trait_classes | db_trait_classes)

    def _check_trait(trait, parent):
        fetch_trait_by_name(curs, trait['name'])
        data = curs.fetchone()
        assert data, "%s | %s" % (data, trait)
        db_trait = json.loads(data['trait'])
        _merge_classes(trait, db_trait)
        if "link" in trait and trait['link']['game-obj'] == 'Trait':
            assert trait['link']['aonid'] == db_trait['aonid'], "%s : %s" % (
                trait, db_trait)
        assert isinstance(parent, list), parent
        index = parent.index(trait)
        if 'value' in trait:
            db_trait['value'] = trait['value']
        if "aonid" in db_trait:
            del db_trait["aonid"]
        _sort_classes(db_trait)
        parent[index] = db_trait

    def _sort_classes(trait):
        trait['classes'].sort()

    db_path = get_db_path("pfsrd2.db")
    conn = get_db_connection(db_path)
    curs = conn.cursor()
    walk(struct, test_key_is_value('subtype', 'trait'), _check_trait)
