import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString, Tag
from universal.markdown import markdown_pass
from universal.universal import parse_universal, entity_pass
from universal.universal import is_trait, extract_link, extract_links
from universal.universal import string_with_modifiers_from_string_list
from universal.utils import split_maintain_parens
from universal.universal import source_pass, extract_source
from universal.universal import aon_pass, restructure_pass
from universal.universal import remove_empty_sections_pass, get_links
from universal.universal import walk, test_key_is_value
from universal.universal import remove_empty_sections_pass, game_id_pass
from universal.universal import link_modifiers
from universal.universal import link_values, link_value
from universal.files import makedirs, char_replace
from universal.creatures import write_creature
from universal.creatures import universal_handle_special_senses
from universal.creatures import universal_handle_perception
from universal.creatures import universal_handle_senses
from universal.creatures import universal_handle_save_dc
from universal.creatures import universal_handle_range
from universal.utils import log_element, is_tag_named, get_text
from universal.utils import get_unique_tag_set
from universal.utils import get_text, bs_pop_spaces
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import trait_parse
from pfsrd2.trait import extract_span_traits
from pfsrd2.action import extract_action_type
from pfsrd2.license import license_pass, license_consolidation_pass
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name
import pfsrd2.constants as constants


def parse_skill(filename, options):
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)
    details = parse_universal(filename, subtitle_text=True, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)
    struct = restructure_skill_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)
    action_pass(struct)
    # addon_pass(struct)
    # trait_db_pass(struct)
    # game_id_pass(struct)
    license_pass(struct)
    license_consolidation_pass(struct)
    # markdown_pass(struct, struct["name"], '')
    # remove_empty_sections_pass(struct)
    # basename.split("_")
    # if not options.skip_schema:
    #    struct['schema_version'] = 1.1
    #    validate_against_schema(struct, "monster_ability.schema.json")
    # if not options.dryrun:
    #    output = options.output
    #    for source in struct['sources']:
    #        name = char_replace(source['name'])
    #        jsondir = makedirs(output, 'monster_abilities', name)
    #        write_creature(jsondir, struct, name)
    # elif options.stdout:
    #    print(json.dumps(struct, indent=2))

    pprint(struct)


def restructure_skill_pass(details):
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)
    top = {'name': sb['name'], 'type': 'skill', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    sb['subtype'] = 'skill'
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []
    return top


def section_pass(struct):
    def _fix_name(section):
        bs = BeautifulSoup(str(section['name']), 'html.parser')
        name = get_text(bs).strip()
        if "(" not in name:
            assert False, "Name has no associated Attribute: %s" % name

        parts = [n.strip() for n in name.split("(")]
        assert len(parts) == 2, "Too many parens in name: %s" % name
        section['name'] = parts.pop(0)
        attribute = parts.pop(0).replace(")", "").lower()
        if attribute in constants.CREATURE_ATTRIBUTES:
            pass
        elif attribute in constants.KINGDOM_ATTRIBUTES:
            section['type'] = 'kingdom_skill'
        else:
            assert False, "Unknown attribute: %s" % attribute

    def _clear_links(section):
        text = section.setdefault('text', "")
        links = section.setdefault('links', [])
        text, links = extract_links(text)

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

        child = section["sections"].pop(0)
        if 'text' not in child:
            return

        bs = BeautifulSoup(child['text'].strip(), 'html.parser')
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
        while children and is_tag_named(children[direction], ['details']):
            children.pop(0).decompose()

    def _clear_garbage(section):
        if 'text' not in section:
            return
        if section['text'] == '':
            del section['text']
            return
        bs = BeautifulSoup(section['text'].strip(), 'html.parser')
        while bs.details:
            bs.details.decompose()
        children = list(bs.children)
        if children[0].name == "br":
            children.pop(0).decompose()
        section['text'] = str(bs)
        for s in section['sections']:
            _clear_garbage(s)

    def _clear_related_feats(section):
        delsection = None
        for s in section['sections']:
            if s['name'] == "Related Feats":
                delsection = s
            if s["sections"]:
                _clear_related_feats(s)
        if not delsection:
            return

        section["sections"].remove(delsection)

    _fix_name(struct)
    _handle_source(struct)
    _clear_garbage(struct)
    _clear_links(struct)
    _clear_related_feats(struct)


def action_pass(struct):
    def _handle_action_list(struct, section, trained):
        pass

    def _handle_action_section(struct, section, trained):
        name, action_type = extract_action_type(section["name"], True)
        if action_type:
            section["action_type"] = action_type
        name, links = extract_links(name)
        assert len(links) == 1, links
        section["name"] = name
        section["links"] = links
        section["type"] = "action"
        if trained == "trained":
            section["trained"] = True
        else:
            section["trained"] = False
        _handle_action_text(section)

    def _clear_empty_tags(children):
        return [c for c in children if str(c).strip() != '']

    def _extract_source_info(text):
        bs = BeautifulSoup(text.strip(), 'html.parser')
        children = list(bs.children)
        children = _clear_empty_tags(children)
        if children[0].name == "br":
            children.pop(0).decompose()
        if not type(children[0]) == Tag:
            return text, None

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
            return str(bs), source

        return text, None

    def _oa_html_reduction(data):
        bs = BeautifulSoup(''.join(data).strip(), 'html.parser')
        while (list(bs.children)[-1].name == 'br'):
            list(bs.children)[-1].unwrap()
        return str(bs).strip()

    def _handle_addons(text):
        def _get_prospective_name(child):
            current = get_text(child).strip()
            if current == "Requirements":
                current = "Requirement"
            return current

        def _create_addon(current, child):
            addon_names = ["Frequency", "Trigger", "Effect", "Duration",
                           "Requirement", "Requirements", "Prerequisite", "Critical Success",
                           "Success", "Failure", "Critical Failure", "Cost"]
            assert current in addon_names, "%s, %s" % (current, text)
            addon_text = str(child)
            if addon_text.strip().endswith(";"):
                addon_text = addon_text.rstrip()[:-1]
            addons.setdefault(
                current.lower().replace(" ", "_"), []).append(addon_text)

        def _reorder_children(children):
            top = []
            while len(children) > 0:
                child = children.pop(0)
                if child.name == 'hr':
                    break
                top.append(child)
            children.extend(top)

        bs = BeautifulSoup(text, 'html.parser')
        children = list(bs)
        _reorder_children(children)
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
        for k, v in addons.items():
            addons[k] = _oa_html_reduction(v)
        text = _oa_html_reduction(parts)
        return text, addons

    def _handle_samples(section):
        sections = section["sections"]
        samples = {}
        if len(sections) == 0:
            return samples
        sample = sections[0]
        if not sample["name"].startswith("Sample") and not sample["name"].endswith("Tasks"):
            return samples
        sections.pop(0)
        assert len(sections) == 1, sections
        sample = sections.pop(0)
        text = "<b>%s</b> %s" % (sample["name"], sample["text"])
        bs = BeautifulSoup(text.strip(), 'html.parser')
        children = list(bs.children)
        name = None
        for child in children:
            if child.name == "b":
                name = get_text(child).lower().strip()
            elif child.name == "br":
                continue
            elif name:
                samples.setdefault(name, []).append(str(child))
        for k, v in samples.items():
            samples[k] = _oa_html_reduction(v)
        return samples

    def _handle_action_text(section):
        text, traits = extract_span_traits(section['text'])
        if traits:
            section['traits'] = traits
        text, source = _extract_source_info(text)
        if source:
            section['source'] = source
        text, addons = _handle_addons(text)
        if addons:
            section.update(addons)
        section['text'] = text
        samples = _handle_samples(section)
        if len(samples) > 0:
            section['samples'] = samples

    def _handle_actions(struct, section):
        parts = section["name"].split(" ")
        assert len(parts) == 3, section["name"]
        assert parts.pop(0) == struct["name"]
        assert parts.pop() == "Actions"
        trained = parts.pop().lower()
        assert trained in ["trained", "untrained"], section["name"]
        if "sections" not in section:
            _handle_action_list(struct, section)
        else:
            for s in section["sections"]:
                _handle_action_section(struct, s, trained)

    for section in struct["sections"]:
        if section["name"].endswith("Actions"):
            _handle_actions(struct, section)
