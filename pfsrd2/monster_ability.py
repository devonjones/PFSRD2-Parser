import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString, Tag
from universal.markdown import markdown_pass
from universal.universal import parse_universal, entity_pass
from universal.universal import is_trait, extract_link
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
	pprint(struct)
	game_id_pass(struct)
	#license_pass(struct)
	markdown_pass(struct, struct["name"], '')
	remove_empty_sections_pass(struct)
	basename.split("_")
	if not options.skip_schema:
		struct['schema_version'] = 1.1
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
			section['action'] = action
			tag.decompose()
		def _handle_trait(section, tag):
			trait = trait_parse(tag)
			assert trait, tag
			section.setdefault('traits', []).append(trait)
			tag.decompose()
		def _tag_is_action(tag):
			assert 'class' in tag.attrs, tag
			tag_class = tag['class']
			if "action" in tag_class:
				return True
			return False
		def _tag_is_trait(tag):
			assert 'class' in tag.attrs, tag
			tag_class = tag['class']
			if 'trait' in tag_class:
				return True
			if 'traitrare' in tag_class:
				return True
			return False
		
		if 'text' in section:
			bs = BeautifulSoup(section['text'].strip(), 'html.parser')
			children = list(bs.children)
			while children and is_tag_named(children[0], ['span']):
				tag = children.pop(0)
				if _tag_is_action(tag):
					_handle_action(section, tag)
				elif _tag_is_trait(tag):
					_handle_trait(section, tag)
				else:
					assert False, tag
			section['text'] = str(bs)

	def _fix_name(section):
		bs = BeautifulSoup(str(section['name']), 'html.parser')
		section['name'] = get_text(bs).strip()

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
		if 'text' in section:
			bs = BeautifulSoup(section['text'].strip(), 'html.parser')
			children = list(bs.children)
			while children and is_tag_named(children[0], ['br', 'hr']):
				children.pop(0).decompose()
			if children:
				children = [c for c in children if str(c).strip() != '']
				if not type(children[0]) == Tag:
					return
				if get_text(children[0]).strip() == "Source":
					children.pop(0).decompose()
					a = children.pop(0)
					source = extract_source(a)
					a.decompose()
					if children[0].name == "sup":
						sup = children.pop(0)
						errata = extract_link(sup.find("a"))
						source['errata'] = errata[1]
						sup.decompose()
					section['sources'] = [source]
			while children and is_tag_named(children[0], ['br', 'hr']):
				children.pop(0).decompose()
				
			section['text'] = str(bs)

	def _clear_garbage(section):
		if 'text' in section:
			if section['text'] == '':
				del section['text']
				return
			bs = BeautifulSoup(section['text'].strip(), 'html.parser')
			children = list(bs.children)
			while children and is_tag_named(children[0], ['br', 'hr']):
				children.pop(0).decompose()
			while children and is_tag_named(children[-1], ['br', 'hr']):
				children.pop().decompose()
			section['text'] = str(bs)

	_fix_name(struct)
	_handle_front_spans(struct)
	_handle_source(struct)
	_clear_links(struct)
	_clear_garbage(struct)

def build_action(child, action=None):
	action_name = child['title']
	if not action:
		action = build_object(
			'stat_block_section',
			'action',
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
		if(list(bs.children)[-1].name == 'br'):
			list(bs.children)[-1].unwrap()
		return str(bs)

	text = struct['text']
	bs = BeautifulSoup(text, 'html.parser')
	children = list(bs)
	addons = {}
	current = None
	parts = []
	addon_names = ["Frequency", "Trigger", "Effect", "Duration",
		"Requirement", "Requirements", "Prerequisite", "Critical Success",
		"Success", "Failure", "Critical Failure", "Range", "Cost"]
	while len(children) > 0:
		child = children.pop(0)
		if child.name == 'b':
			current = get_text(child).strip()
			if current == "Requirements":
				current = "Requirement"
		elif current:
			assert current in addon_names, "%s, %s" % (current, text)
			addon_text = str(child)
			if addon_text.strip().endswith(";"):
				addon_text = addon_text.rstrip()[:-1]
			addons.setdefault(current.lower().replace(" ", "_"), [])\
				.append(addon_text)
		else:
			parts.append(str(child))
	for k, v in addons.items():
		if k == 'range':
			assert len(v) == 1, "Malformed range: %s" % v
			struct['range'] = universal_handle_range(v[0])
		else:
			struct[k] = _oa_html_reduction(v)
	if len(parts) > 0:
		struct['text'] = _oa_html_reduction(parts)
	else:
		del struct['text']
