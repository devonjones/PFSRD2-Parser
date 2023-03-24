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
from universal.files import makedirs, char_replace
from universal.utils import get_text
from pfsrd2.schema import validate_against_schema

def parse_trait(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, max_title=4,
		cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
	details = entity_pass(details)
	struct = restructure_trait_pass(details)
	trait_struct_pass(struct)
	source_pass(struct, find_trait)
	trait_class_pass(struct, filename)
	trait_link_pass(struct)
	aon_pass(struct, basename)
	restructure_pass(struct, 'trait', find_trait)
	list_removal_pass(struct)
	remove_empty_sections_pass(struct)
	html_pass(struct)
	game_id_pass(struct)
	trait_cleanup_pass(struct)
	basename.split("_")
	if not options.skip_schema:
		validate_against_schema(struct, "trait.schema.json")
	if not options.dryrun:
		output = options.output
		for source in struct['sources']:
			name = char_replace(source['name'])
			jsondir = makedirs(output, struct['game-obj'], name)
			write_trait(jsondir, struct, name)
	elif options.stdout:
		print(json.dumps(struct, indent=2))

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
	def check_type_trait(trait_class, name):
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

	name = ''.join(span['alt']).replace(" Trait", "")
	trait_class = ''.join(span['class'])
	if trait_class != 'trait':
		trait_class = trait_class.replace('trait', '')
	if trait_class == 'trait':
		trait_class = check_type_trait(trait_class, name)
	text = ''.join(span['title'])
	trait = {
		'name': name,
		'classes': [trait_class],
		'text': text.strip(),
		'type': 'stat_block_section',
		'subtype': 'trait'}
	c = list(span.children)
	if len(c) == 1:
		if c[0].name == "a":
			_, link = extract_link(c[0])
			trait['link'] = link
	else:
		raise Exception("You should not be able to get here")
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
				book = children.pop(0)
				source = extract_source(book)
				if children[0].name == "sup":
					assert 'errata' not in source, "Should be no more than one errata."
					_, source['errata'] = extract_link(children.pop(0).find("a"))
				if children[0].name == "br":
					children.pop(0)
				assert children[0].name != "a", section
				section['text'] = ''.join([str(c) for c in children])
				return [source]
	
	for section in struct['sections']:
		sources = _extract_source(section)
		section['sources'] = sources

def trait_class_pass(struct, filename):
	parts = filename.split(".")
	parts = parts[:-2]
	fn = ".".join(parts)
	details = parse_universal(fn, max_title=4,
		cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
	top = details.pop(0)
	trait_classes = {}
	for section in details:
		assert section['name'].find("Traits") > -1, struct
		name = section['name'].replace("Traits", "").strip().lower().replace(" ", "_")
		soup = BeautifulSoup(section['text'], "html.parser")
		links = soup.find_all("a") 
		for link in links:
			trait = get_text(link)
			trait_classes.setdefault(trait.lower(), []).append(name)
	soup = BeautifulSoup(top, "html.parser")
	links = soup.find_all("a")
	for link in links:
		trait = get_text(link)
		assert trait not in trait_classes, "%s: %s" % (name, trait)
		trait_classes[trait.lower()] = None
	t = find_trait(struct)
	assert t['name'].lower() in trait_classes, t
	c = trait_classes[t['name'].lower()]
	if c:
		t['classes'] = c

def trait_link_pass(struct):
	trait = find_trait(struct)
	bs = BeautifulSoup(trait['text'], "html.parser")
	links = get_links(bs)
	trait['links'] = links
	while bs.a:
		bs.a.unwrap()
	trait['text'] = str(bs)

def list_removal_pass(struct):
	for section in struct['sections']:
		if 'sections' in section:
			list_removal_pass(section)
		text = "".join(section['text'].split(", "))
		soup = BeautifulSoup(text, "html.parser")
		r = True
		for c in list(soup.children):
			if c.name != "a":
				pprint(c.name)
				pprint(c)
				assert False, section['text']
				r = False
		if r:
			section['text'] = ''
	struct['sections']= [s for s in struct['sections'] if s['text'] != ""]

def trait_cleanup_pass(struct):
	assert 'sections' not in struct, struct # Right now no traits have other sections
	trait = struct['trait']
	if len(trait['sections']) == 0:
		del trait['sections']
	else:
		assert False, struct
	soup = BeautifulSoup(trait['text'], "html.parser")
	first = list(soup.children)[0]
	if first.name == "i":
		text = get_text(first)
		if text.find("Note from Nethys:") > -1:
			first.clear()
		first.unwrap()
	trait['text'] = str(soup).strip()
	if trait['text'] != "":
		assert 'text' not in struct, struct
		struct['text'] = html2markdown.convert(trait['text'])
	if len(trait.get('sections', [])) > 0:
		assert 'sections' not in struct, struct
		struct['sections'] = trait['sections']
	if trait.get('classes'):
		struct['classes'] = trait['classes']
	if trait.get('links'):
		assert 'links' not in struct, struct
		struct['links'] = trait['links']
	del struct['trait']


def write_trait(jsondir, struct, source):
	print("%s (%s): %s" %(struct['game-obj'], source, struct['name']))
	filename = create_trait_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_trait_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)

