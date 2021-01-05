import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from pfsrd2.creatures import remove_empty_sections_pass, source_pass
from pfsrd2.creatures import sidebar_pass, index_pass, aon_pass, trait_pass
from pfsrd2.creatures import creature_stat_block_pass, sb_restructure_pass
from pfsrd2.universal import parse_universal, print_struct
from pfsrd2.universal import is_trait, get_text, extract_link
from pfsrd2.files import makedirs, char_replace
from pfsrd2.schema import validate_against_schema

def parse_npc(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, max_title=4)
	struct = restructure_npc_pass(details)
	creature_stat_block_pass(struct)
	source_pass(struct)
	sidebar_pass(struct)
	index_pass(struct)
	aon_pass(struct, basename)
	sb_restructure_pass(struct)
	#validate_dict_pass(struct, struct, None, "")
	remove_empty_sections_pass(struct)
	trait_pass(struct)
	basename.split("_")
	if not options.skip_schema:
		validate_against_schema(struct, "creature.schema.json")
	if not options.dryrun:
		output = options.output
		for source in struct['sources']:
			jsondir = makedirs(output, struct['game-obj'], source['name'])
			write_npc(jsondir, struct, source['name'])
	elif options.stdout:
		print(json.dumps(struct, indent=2))

def restructure_npc_pass(details):
	sb = None
	rest = []
	for obj in details:
		if sb == None and 'subname' in obj and obj['subname'].startswith(
				"Creature"):
			assert not sb
			sb = obj
		else:
			rest.append(obj)
	top = {'name': sb['name'], 'type': 'npc', 'sections': [sb]}
	level = int(sb['subname'].split(" ")[1])
	sb["level"] = level
	sb['type'] = 'stat_block'
	del sb["subname"]
	top['sections'].extend(rest)
	return top

def write_npc(jsondir, struct, source):
	print("%s (%s): %s" %(struct['game-obj'], source, struct['name']))
	filename = create_npc_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_npc_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)
