import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from pfsrd2.universal import parse_universal, print_struct, entity_pass
from pfsrd2.universal import is_trait, get_text, extract_link
from pfsrd2.universal import split_maintain_parens
from pfsrd2.universal import source_pass, extract_source
from pfsrd2.universal import aon_pass, restructure_pass, html_pass
from pfsrd2.universal import remove_empty_sections_pass, get_links
from pfsrd2.universal import walk, test_key_is_value
from pfsrd2.files import makedirs, char_replace
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import trait_parse
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name

from pfsrd2.creatures import restructure_creature_pass
from pfsrd2.creatures import creature_stat_block_pass
from pfsrd2.creatures import sidebar_pass
from pfsrd2.creatures import index_pass
from pfsrd2.creatures import trait_pass
from pfsrd2.creatures import db_pass
from pfsrd2.creatures import log_html_pass
from pfsrd2.creatures import write_creature

# TODO: range on perceptions
# pleroma, 11, lifesense 120 feet

def parse_alien(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, subtitle_text=False, max_title=3,
		cssclass="ctl00_MainContent_DataListTalentsAll_ctl00_LabelName")
	details = entity_pass(details)
	struct = restructure_alien_pass(details, options.subtype)
	sys.exit(0)
	creature_stat_block_pass(struct)
	source_pass(struct, find_stat_block)
	sidebar_pass(struct)
	index_pass(struct)
	aon_pass(struct, basename)
	restructure_pass(struct, 'stat_block', find_stat_block)
	trait_pass(struct)
	db_pass(struct)
	html_pass(struct)
	log_html_pass(struct, basename)
	remove_empty_sections_pass(struct)
	basename.split("_")
	if not options.skip_schema:
		validate_against_schema(struct, "creature.schema.json")
	if not options.dryrun:
		output = options.output
		for source in struct['sources']:
			name = char_replace(source['name'])
			jsondir = makedirs(output, struct['game-obj'], name)
			write_creature(jsondir, struct, name)
	elif options.stdout:
		print(json.dumps(struct, indent=2))

def restructure_alien_pass(details, subtype):
	def _find_stat_block(details):
		path = []
		for detail in details:
			if detail['name'].find('CR') > -1:
				details.remove(detail)
				return detail, []
			else:
				result = _find_stat_block(detail['sections'])
				if result:
					r, path = result
					path.append(detail)
					return r, path
		return None

	def _handle_family(details):
		for detail in details:
			if detail['name'].endswith("Family"):
				name = detail['name']
				parts = name.split('"')
				assert len(parts) == 3, parts
				name = parts[1]
				details.remove(detail)
				return name

	def _handle_role(top):
		bs = BeautifulSoup(top['text'], 'html.parser')
		imgs = bs.findAll('img')
		assert len(imgs) == 1, imgs
		img = imgs.pop()
		role = img['src'].split(".")[0].split("_").pop()
		img.extract()
		top['text'] = str(bs)
		return role

	def _handle_sources(top):
		bs = BeautifulSoup(top['text'], 'html.parser')
		links = bs.findAll('a')
		retarr = []
		for link in links:
			retarr.append(extract_source(link))
			link.extract()
		assert str(bs).replace("<b>Source</b>", "").replace(", ", "") == "", str(bs)
		del top['text']
		return retarr

	rest = []
	struct, path = _find_stat_block(details)
	top = path.pop()
	assert path == [], path
	details.remove(top)
	assert len(path) == 0, path
	parts = [p.strip() for p in struct['name'].split('CR')]
	name = parts.pop(0)
	cr = parts.pop(0)
	assert len(parts) == 0, parts
	struct['name'] = name
	struct['cr'] = cr
	struct['alien_family'] = _handle_family(details)
	struct['role'] = _handle_role(top)
	struct['sources'] = _handle_sources(top)
	assert len(top) == 3, str(top)
	struct['sections'].extend(top['sections'])
	return struct
