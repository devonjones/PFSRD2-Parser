import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from universal.universal import parse_universal, print_struct, entity_pass
from universal.universal import is_trait, get_text, extract_link
from universal.universal import split_maintain_parens
from universal.universal import source_pass, extract_source
from universal.universal import aon_pass, restructure_pass, html_pass
from universal.universal import remove_empty_sections_pass, get_links
from universal.universal import walk, test_key_is_value
from universal.universal import link_modifiers
from universal.files import makedirs, char_replace
from pfsrd2.schema import validate_against_schema
from pfsrd2.trait import trait_parse
from pfsrd2.sql import get_db_path, get_db_connection
from pfsrd2.sql.traits import fetch_trait_by_name

# TODO: range on perceptions
# pleroma, 11, lifesense 120 feet

def parse_creature(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, subtitle_text=True, max_title=4)
	details = entity_pass(details)
	struct = restructure_creature_pass(details, options.subtype)
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

def log_html_pass(struct, path):
	for k, v in struct.items():
		if k not in ["sections"]:
			if isinstance(v, dict):
				log_html_pass(v, "%s.%s" % (path, k))
			elif isinstance(v, list):
				for item in v:
					if isinstance(item, dict):
						log_html_pass(item, "%s.%s" % (path, k))
					elif isinstance(item, str):
						if item.find("<") > -1:
							log_element("html.log")("%s: %s" % (path, item))
			elif isinstance(v, str):
				if v.find("<") > -1:
					log_element("html.log")("%s: %s" % (path, v))

def db_pass(struct):
	db_path = get_db_path("traits.db")
	conn = get_db_connection(db_path)
	curs = conn.cursor()
	def _check_trait(trait, parent):
		_handle_value(trait)
		if "alignment" in trait.get('classes', []) and trait['name'] != "No Alignment":
			_handle_alignment_trait(trait, parent)
		else: 
			fetch_trait_by_name(curs, trait['name'])
			data = curs.fetchone()
			assert data, trait
			db_trait = json.loads(data['trait'])
			if "link" in trait:
				assert trait['link']['aonid'] == db_trait['aonid'], trait
			assert isinstance(parent, list), parent
			index = parent.index(trait)
			if 'value' in trait:
				db_trait['value'] = trait['value']
			if "aonid" in db_trait:
				del db_trait["aonid"]
			parent[index] = db_trait

	def _handle_value(trait):
		m = re.search(r"(.*) (\+?d?[0-9]+.*)", trait['name'])
		if trait['name'].startswith("range increment"):
			value = trait['name'].replace("range ", "")
			trait['name'] = "range"
			trait['value'] = value
		elif m:
			name, value = m.groups()
			trait['name'] = name
			trait['value'] = value
		elif trait['name'].startswith("versatile "):
			value = trait['name'].replace("versatile ", "")
			trait['name'] = "versatile"
			trait['value'] = value

	def _handle_alignment_trait(trait, parent):
		index = parent.index(trait)
		parent.remove(trait)
		parts = trait['name'].split(" ")
		for part in parts:
			fetch_trait_by_name(curs, part)
			data = curs.fetchone()
			db_trait = json.loads(data['trait'])
			if "aonid" in db_trait:
				del db_trait["aonid"]
			parent.insert(index, db_trait)
			index += 1

	walk(struct, test_key_is_value('subtype', 'trait'), _check_trait)

def restructure_creature_pass(details, subtype):
	sb = None
	rest = []
	for obj in details:
		if sb == None and 'subname' in obj and obj['subname'].startswith(
				"Creature"):
			assert not sb
			sb = obj
		else:
			rest.append(obj)
	top = {'name': sb['name'], 'type': subtype, 'sections': [sb]}
	level = int(sb['subname'].split(" ")[1])
	sb["level"] = level
	sb['type'] = 'stat_block'
	del sb["subname"]
	top['sections'].extend(rest)
	return top

def find_stat_block(struct):
	for s in struct['sections']:
		if s['type'] == 'stat_block':
			return s
	for s in struct['sections']:
		return creature_stat_block_pass(s)

def trait_pass(struct):
	sb = struct['stat_block']
	traits = sb['traits']
	for trait in traits:
		if "alignment" in trait['classes']:
			sb['alignment'] = trait['name']
	for trait in traits:
		if "creature_type" in trait['classes']:
			return
	assert False, "Has no creature type"

def creature_stat_block_pass(struct):
	def add_to_data(key, value, data, link):
		if key:
			data.append((key, ''.join([str(v) for v in value]).strip(), link))
			key = None
			value = []
			link = None
		return key, value, data, link

	def add_remnants(value, data):
		k,v,_ = data.pop()
		newvalue = [v]
		newvalue.extend(value)
		data.append((k, ''.join([str(v) for v in newvalue]).strip(), link))
		return [], data

	sb = find_stat_block(struct)
	bs = BeautifulSoup(sb["text"], 'html.parser')
	objs = list(bs.children)
	sections = []
	data = []
	key = None
	value = []
	link = None
	for obj in objs:
		if obj.name == 'span' and is_trait(obj):
			trait = trait_parse(obj)
			sb.setdefault('traits', []).append(trait)
		elif obj.name == "br":
			value.append(obj)
			key, value, data, link = add_to_data(key, value, data, link)
		elif obj.name == 'hr':
			key, value, data, link = add_to_data(key, value, data, link)
			if len(value) > 0:
				assert link == None
				value, data = add_remnants(value, data)
			data = strip_br(data)
			sections.append(data)
			data = []
		elif obj.name == "b":
			key, value, data, link = add_to_data(key, value, data, link)
			key = get_text(obj)
			if obj.a:
				_, link = extract_link(obj.a)
		else:
			value.append(obj)
	if key:
		key, value, data, link = add_to_data(key, value, data, link)
	data = strip_br(data)
	sections.append(data)
	assert len(sections) == 3, sections
	process_stat_block(sb, sections)

def strip_br(data):
	newdata = []
	for k,v,l in data:
		bs = BeautifulSoup(v, 'html.parser')
		children = list(bs.children)
		while len(children) > 0 and children[-1].name == "br":
			children.pop()
		newdata.append((k, ''.join([str(c) for c in children]).strip(), l))
	return newdata

def sidebar_pass(struct):
	for section in struct['sections']:
		sidebar_pass(section)
	if 'text' in struct:
		bs = BeautifulSoup(struct['text'], 'html.parser')
		children = list(bs.children)
		if len(children) > 0:
			c = children[0]
		if c.name == 'img' and c['alt'].startswith("Sidebar"):
			children.pop(0)
			image = c['src'].split("\\").pop().split("%5C").pop()
			subtype = c['alt'].split("-").pop().strip()
			struct['type'] = "section"
			struct['subtype'] = "sidebar"
			struct['sidebar_type'] = subtype.lower().replace(" ", "_")
			struct['sidebar_heading'] = subtype
			struct['image'] = {'type': "image", "name": subtype, "image": image}
			struct['text'] = ''.join([str(c) for c in children])

def index_pass(struct):
	remove = []
	for section in struct['sections']:
		keep = index_pass(section)
		if not keep:
			remove.append(section)
	for s in remove:
		struct['sections'].remove(s)
	if struct['name'].startswith("All Monsters"):
		struct['type'] = "section"
		struct['subtype'] = "index"
		return False
	return True

def validate_dict_pass(top, struct, parent, field):
	try:
		if type(struct) is dict:
			for k, v in struct.items():
				validate_dict_pass(top, v, struct, k)
			if 'type' not in struct:
				raise Exception("%s missing type" % struct)
			if 'name' not in struct:
				raise Exception("%s missing name" % struct)
		elif type(struct) is list:
			for item in struct:
				if type(item) is dict:
					validate_dict_pass(top, item, struct, "")
				else:
					raise Exception("%s: lists should only have dicts" % struct)
		elif type(struct) is str:
			#if field == "name" and struct.startswith(top.get("name", "")):
			#	pass
			if type(parent) is dict and parent['type'] in ['section', 'sidebar']:
				pass
			elif type(parent) is dict and parent.get('subtype') in ['modifier']:
				pass
			elif type(parent) is dict and parent.get(
					'subtype') == 'ability' and field in [
					"frequency", "trigger", "effect", "duration", "requirement",
					"critical success", "success", "failure",
					"critical failure"]:
				pass
			elif struct.find("(") > -1:
				bs = BeautifulSoup(struct, 'html.parser')
				if not bs.table:
					raise Exception("%s: '(' should have been parsed out" % struct)
	except Exception as e:
		pprint(struct)
		raise e

def process_stat_block(sb, sections):
	# Stats
	stats = sections.pop(0)
	process_source(sb, stats.pop(0))
	sb['perception'] = process_perception(stats.pop(0))
	if(stats[0][0] == "Languages"):
		sb['languages'] = process_languages(stats.pop(0))
	if(stats[0][0] == "Skills"):
		sb['skills'] = process_skills(stats.pop(0))
	for _ in range(6):
		attr = stats.pop(0)
		sb[attr[0].lower()] = process_attr(attr)
	while len(stats) > 0:
		if stats[0][0] == "Items":
			sb['items'] = process_items(stats.pop(0))
		else:
			sb.setdefault('interaction_abilities', []).append(
				process_interaction_ability(stats.pop(0)))

	# Defense
	defense = sections.pop(0)
	sb['defense'] = {
		'type': 'stat_block_section', 'subtype': 'defense', 'name': "Defense"}
	sb['defense']['ac'] = process_ac(defense.pop(0))
	sb['defense']['saves'] = process_saves(
		defense.pop(0), defense.pop(0), defense.pop(0))
	sb['defense']['hp'] = process_hp(defense.pop(0), 'hitpoints')
	if len(defense) > 0 and defense[0][0] == "Hardness":
		sb['defense']['hardness'] = process_hp(defense.pop(0), 'hardness')
	if len(defense) > 0 and defense[0][0] == "Immunities":
		process_defense(sb, defense.pop(0))
	if len(defense) > 0 and defense[0][0] == "Resistances":
		process_defense(sb, defense.pop(0))
	if len(defense) > 0 and defense[0][0] == "Weaknesses":
		process_defense(sb, defense.pop(0))

	while len(defense) > 0:
		process_defensive_ability(defense.pop(0), defense, sb)

	# Offense
	offense = sections.pop(0)
	sb['offense'] = {
		'type': 'stat_block_section', 'subtype': 'offense', 'name': "Offense"}
	sb['offense']['speeds'] = process_speed(offense.pop(0))
	del sb['text']
	assert len(offense) == 0

	# Attacks
	attacks_src = get_attacks(sb)
	attacks = []
	for src in attacks_src:
		attacks.append(process_offensive_action(src))
	if len(attacks) > 0:
		sb['offense']['offensive_actions'] = attacks

def process_source(sb, section):
	# 5
	# <a target="_blank" href="Images\Monsters\Alghollthu_VeiledMaster.png"><img class="thumbnail" src="Images\Monsters\Alghollthu_VeiledMaster.png"></a>
	# <b>Source</b> <a href="https://paizo.com/products/btq01y0m?Pathfinder-Bestiary" target="_blank" class="external-link"><i>Bestiary pg. 14</i></a>
	# 447
	# <a target="_blank" href="Images\Monsters\Grippli.png"><img class="thumbnail" src="Images\Monsters\Grippli.png"></a>
	# <b>Source</b> <a href="https://paizo.com/products/btq01znt?Pathfinder-Adventure-Path-146-Cult-of-Cinders" target="_blank" class="external-link"><i>Pathfinder #146: Cult of Cinders pg. 86</i></a>, <a href="https://paizo.com/products/btq022yq" target="_blank"><i>Bestiary 2 pg. 139</i></a>; <strong><u><a href="Monsters.aspx?ID=693">There is a more recent version of this monster. Click here to view.</a></u></strong>
	# 861
	# <a target="_blank" href="Images\Monsters\Witchwyrd.png"><img class="thumbnail" src="Images\Monsters\Witchwyrd.png"></a>
	# <b>Source</b> <a href="https://paizo.com/products/btq022yq" target="_blank" class="external-link"><i>Bestiary 2 pg. 294</i></a>, <a href="https://paizo.com/products/btq02065" target="_blank"><i>Pathfinder #149: Against the Scarlet Triad pg. 90</i></a>
	def set_image(obj, name):
		link = obj['href']
		image = link.split("\\").pop().split("%5C").pop()
		sb['image'] = {
			'type': 'image', 'name': name, 'game-obj': 'Monster',
			'image': image}
	assert section[0] == "Source"
	bs = BeautifulSoup(section[1], 'html.parser')
	c = [c for c in list(bs.children)] # if c.name != "sup"]
	sources = []
	if c[0].find("img"):
		set_image(c.pop(0), sb['name'])
	note = None
	errata = None
	while len(c) > 0:
		if c[0].name == "a":
			sources.append(extract_source(c.pop(0)))
		elif c[0].name == "sup":
			assert not errata, "Should be no more than one errata."
			errata = extract_link(c.pop(0).find("a"))
		elif c[0].name == "strong":
			assert not note, "Should be no more than one note."
			note = extract_link(c.pop(0).find("a"))
		elif isinstance(c[0], str) and c[0].strip() in [",", ";"]:
			c.pop(0)
		elif c[0].name == "br":
			c.pop(0)
		else:
			raise Exception("Source has unexpected text: %s" % c[0])
	for source in sources:
		if note:
			source['note'] = note[1]
		if errata:
			source['errata'] = errata[1]
	sb['sources'] = sources

def process_perception(section):
	assert section[0] == "Perception"
	assert section[2] == None
	parts = split_stat_block_line(section[1])
	value = parts.pop(0)
	value = int(value.replace("+", ""))
	perception = {
		'type': 'stat_block_section', 'subtype': 'perception',
		'name': 'perception', 'value': value}
	if len(parts) > 0:
		if parts[0].startswith("("):
			modifier = parts.pop(0)
			modifier = modifier.replace("(", "").replace(")", "")
			#TODO: fix []
			perception['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', [modifier]))
	if len(parts) > 0:
		special_senses = []
		for part in parts:
			part, modifier = extract_modifier(part)
			bs = BeautifulSoup(part, 'html.parser')
			children = list(bs.children)
			sense = None
			if children[0].name == "a":
				name, link = extract_link(children[0])
				sense = build_object(
					'stat_block_section', 'special_sense', name, {'link': link})
			else:
				sense = build_object(
					'stat_block_section', 'special_sense', part)
			if modifier:
				#TODO: fix []
				sense['modifiers'] = link_modifiers(
					build_objects(
						'stat_block_section', 'modifier', [modifier]))
			special_senses.append(sense)
		perception['special_senses'] = special_senses
	return perception

def process_languages(section):
	# 1, Unseen Servant
	#  <b>Languages</b> - (understands its creator)
	# 2, Alghollthu Master
	#  <b>Languages</b> <a href="Languages.aspx?ID=13"><u>Aklo</a></u>, <a href="Languages.aspx?ID=24"><u>Alghollthu</a></u>, <a href="Languages.aspx?ID=14"><u>Aquan</a></u>, <a href="Languages.aspx?ID=1"><u>Common</a></u>, <a href="Languages.aspx?ID=11"><u>Undercommon</a></u>
	# 204
	#  <b>Languages</b> pidgin of <a style="text-decoration:underline" href="Languages.aspx?ID=6">Goblin</a>, <a style="text-decoration:underline" href="Languages.aspx?ID=8">Jotun</a>, and <a style="text-decoration:underline" href="Languages.aspx?ID=9">Orcish</a>
	# 211
	#  <b>Languages</b> <a href="Languages.aspx?ID=1"><u>Common</a></u>; one elemental language (Aquan, Auran, Ignan, or Terran), one planar language (Abyssal, Celestial, or Infernal); telepathy 100 feet
	# 343, Quelaunt
	#  <b>Languages</b> <a href="Languages.aspx?ID=13"><u>Aklo</a></u>; (can't speak any language); telepathy 100 feet
	# 639, Drainberry Bush
	#  <b>Languages</b> <a href="Languages.aspx?ID=13"><u>Aklo</a></u>, <a href="Languages.aspx?ID=1"><u>Common</a></u>, <a href="Languages.aspx?ID=10"><u>Sylvan</a></u>; <a style="text-decoration:underline" href="Spells.aspx?ID=340"><i>tongues</i></a>
	# 98, Succubus
	#  <b>Languages</b> <a href="Languages.aspx?ID=12"><u>Abyssal</a></u>, <a href="Languages.aspx?ID=16"><u>Celestial</a></u>, <a href="Languages.aspx?ID=1"><u>Common</a></u>, <a href="Languages.aspx?ID=2"><u>Draconic</a></u>; three additional mortal languages; telepathy 100 feet, <a style="text-decoration:underline" href="Spells.aspx?ID=340"><i>tongues</i></a>

	assert section[0] == "Languages"
	assert section[2] == None
	text = section[1]
	languages = build_object(
		'stat_block_section', 'languages', 'Languages', {'languages': []})
	if text.find(";") > -1:
		parts = text.split(";")
		text = parts.pop(0)
		assert len(parts) in [1,2], parts
		parts = rebuilt_split_modifiers(split_stat_block_line(";".join(parts)))
		abilities = []
		for part in parts:
			newtext, modifier = extract_modifier(part.strip())
			if newtext.strip() == "":
				languages['modifiers'] = link_modifiers(
					build_objects(
						'stat_block_section', 'modifier',
						[m.strip() for m in modifier.split(",")]))
			else:
				bs = BeautifulSoup(newtext, 'html.parser')
				link = None
				if bs.a:
					newtext, link = extract_link(bs.a)
				ability = build_object(
				'stat_block_section', 'ability', newtext, {
					'ability_type': 'communication'})
				if link:
					#TODO: fix []
					ability['links'] = [link]
				if(modifier):
					#TODO: fix []
					ability['modifiers'] = link_modifiers(
						build_objects(
							'stat_block_section', 'modifier', [
								modifier.strip()]))
				abilities.append(ability)
		if len(abilities) > 0:
			languages['communication_abilities'] = abilities
	parts = rebuilt_split_modifiers(split_stat_block_line(text))
	for text in parts:
		text, modifier = extract_modifier(text)
		bs = BeautifulSoup(text, 'html.parser')
		c = list(bs.children)

		if len(c) > 1:
			text = []
			for child in c:
				if child.name == "a":
					name, link = extract_link(child)
					text.append(name)
				elif isinstance(child, str):
					text.append(child)
			language = {
				'name': ''.join(text),
				'type': 'stat_block_section',
				'subtype': 'language',
				'link': link}
		else:
			assert len(c) == 1
			if c[0].name == 'a':
				name, link = extract_link(c[0])
				language = {
					'name': get_text(bs),
					'type': 'stat_block_section',
					'subtype': 'language',
					'link': link}
			else:
				language = {
					'name': get_text(bs),
					'type': 'stat_block_section',
					'subtype': 'language'}
		if modifier:
			#TODO: fix []
			language['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', [modifier]))
		languages['languages'].append(language)
	return languages

def process_skills(section):
	assert section[0] == "Skills"
	assert section[2] == None
	parts = split_stat_block_line(section[1])
	parts = rebuilt_split_modifiers(parts)
	skills = []
	for part in parts:
		children = list(BeautifulSoup(part, 'html.parser').children)
		a = children.pop(0)
		name, link = extract_link(a)
		value, modifier = extract_modifier(''.join([str(c) for c in children]))
		value = int(value.replace("+", ""))
		skill = {
			'type': 'stat_block_section',
			'subtype': 'skill',
			'name': name,
			'link': link,
			'value': value}
		if modifier:
			#TODO: fix []
			skill['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', [modifier]))
		skills.append(skill)
	return skills

def process_attr(section):
	assert section[0] in ['Str', 'Dex', 'Con', 'Int', 'Wis', 'Cha']
	assert section[2] == None
	value = int(section[1].replace(",", "").replace("+", ""))
	return value

def unwrap_formatting(bs):
	while bs.i:
		bs.i.unwrap()
	while bs.u:
		bs.u.unwrap()
	for a in bs.find_all("a"):
		for child in a.children:
			if isinstance(child, NavigableString):
				child.replace_with(child.strip())
	return bs

def process_items(section):
	assert section[0] == "Items"
	assert section[2] == None
	parts = rebuilt_split_modifiers(split_stat_block_line(section[1]))
	items = []
	for part in parts:
		text, modifier = extract_modifier(part)
		bs = unwrap_formatting(BeautifulSoup(text, 'html.parser'))
		name = get_text(bs)
		item = {
			'type': 'stat_block_section',
			'subtype': 'item',
			'name': name.strip()}
		if modifier:
			item['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', modifier.split(",")))
		links = []
		while bs.a:
		#for a in bs.findAll("a"):
			_, link = extract_link(bs.a)
			links.append(link)
			bs.a.unwrap()
		if len(links) > 0:
			item['links'] = links
		items.append(item)
	return items

def process_interaction_ability(section):
	ability_name = section[0]
	description = section[1]
	link = section[2]
	ability = {
		'name': ability_name,
		'type': 'stat_block_section',
		'subtype': 'ability',
		'ability_type': 'interaction'}
	description, traits = extract_all_traits(description)
	if len(traits) > 0:
		ability['traits'] = traits
	ability['text'] = description
	if link:
		#TODO: fix []
		ability['links'] = [link]
	return ability

def process_ac(section):
	def extract_ac_modifier(text):
		#22 <b>AC</b> 26 (22 when broken); construct armor;
		#303 <b>AC</b> 37 all-around vision; 
		#333 <b>AC</b> 23 (25 with shield raised); 
		text, modifier = extract_modifier(text)
		if modifier:
			modifiers = [modifier]
		else:
			modifiers = []
		if text.find(";") > -1:
			parts = [p.strip() for p in text.split(";", 1)]
			text = parts.pop(0)
			modifiers.extend(parts)
		if text.find(",") > -1:
			parts = [p.strip() for p in text.split(",", 1)]
			text = parts.pop(0)
			modifiers.extend(parts)
		if text.find(" ") > -1:
			parts = text.split(" ", 1)
			base = [parts.pop(0)]
			newparts = parts.pop(0).split(")", 1)
			modifier = newparts.pop(0).strip()
			base.extend(newparts)
			modifiers.append(modifier)
			return ' '.join([b.strip() for b in base]).strip(), modifiers
		else:
			return text, modifiers
	
	assert section[0] == "AC"
	assert section[1].endswith(";")
	assert section[2] == None
	text = section[1][:-1]
	modifiers = []
	value, modifiers = extract_ac_modifier(text)
	modifier = ';'.join(modifiers)
	if modifier:
		modifiers = [m.strip() for m in modifier.split(";")]
	if value.find(";") > -1:
		parts = value.split(";")
		value = parts.pop(0)
		modifiers.extend([m.strip() for m in parts])

	ac = {
		'type': 'stat_block_section',
		'subtype': 'armor_class',
		'name': "AC",
		'value': int(value.strip())
	}
	if len(modifiers) > 0:
		ac['modifiers'] = link_modifiers(
			build_objects(
				'stat_block_section', 'modifier', modifiers))
	return ac

def process_saves(fort, ref, will):
	saves = {
		'type': 'stat_block_section',
		'subtype': 'saves',
		'name': "Saves"
	}
	def process_save(section):
		assert section[0] in ["Fort", "Ref", "Will"]
		assert section[2] == None
		name = section[0].lower()
		value = section[1] 
		if value.endswith(","):
			value = value[:-1]
		if(value.find(";")> -1):
			value, bonus = value.split(";")
			if bonus.find(", +") > -1:
				bonuses = [b.strip() for b in bonus.split(", ")]
			else:
				bonuses = [bonus.strip()]
			saves['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', bonuses))
		value, modifier = extract_modifier(value)
		save = {
			'type': "stat_block_section",
			'subtype': "save",
			'name': section[0],
			'value': int(value.strip().replace("+", ""))}
		if modifier:
			modifiers = [m.strip() for m in modifier.split(",")]
			save['modifiers'] = link_modifiers(
				build_objects(
					'stat_block_section', 'modifier', modifiers))
		saves[name] = save

	process_save(fort)
	process_save(ref)
	process_save(will)
	return saves

def process_hp(section, subtype):
	assert section[0] in ["HP", "Hardness"]
	assert section[2] == None
	text = section[1].strip()
	name = section[0]
	value, text = re.search(r"^(\d*)(.*)", text).groups()
	text = text.strip()
	value = int(value)
	if(text.startswith(",")):
		text = text[1:]
	if(text.endswith(";")):
		text = text[:-1]
	text = text.strip()
	specials = []
	if text.startswith("(") and text.endswith(")"):
		specials.extend([t.strip() for t in text[1:-1].split(",")])
	elif len(text.strip()) > 0:
		specials.extend([t.strip() for t in text.split(",")])
	hp = {
		'type': 'stat_block_section',
		'subtype': subtype,
		'name': name,
		'value': value}
	if len(specials) > 0:
		special_sections = build_objects(
			'stat_block_section', 'ability', specials, {
				'ability_type': 'automatic'})
		for s in special_sections:
			parse_section_modifiers(s, 'name')
		special_sections = link_abilities(special_sections)
		for s in special_sections:
			parse_section_value(s, 'name')
			assert s['name'] != "", section
		hp['automatic_abilities'] = special_sections
	return hp

def process_defense(sb, section):
	def create_defense(defense):
		d = {
			'type': 'stat_block_section',
			'subtype': subtype[section[0]],
			'name': part}
		d = parse_section_modifiers(d, 'name')
		d = parse_section_value(d, 'name')
		return d

	assert section[0] in ["Immunities", "Resistances", "Weaknesses"]
	assert section[2] == None
	text = section[1].strip()
	subtype = {
		"Immunities": "immunity",
		"Resistances": "resistance",
		"Weaknesses": "weakness"}
	if(text.endswith(";")):
		text = text[:-1].strip()
	parts = rebuilt_split_modifiers(split_stat_block_line(text))
	defense = build_object(
						'stat_block_section', section[0].lower(), section[0],
						{section[0].lower(): []})
	for part in parts:
		defense[section[0].lower()].append(create_defense(part))
	link_objects(defense[section[0].lower()])
	sb['defense'][section[0].lower()] = defense

def process_defensive_ability(section, sections, sb):
	#TODO: parse error on 71, Catfolk Pouncer
	assert section[0] not in ["Immunities", "Resistances", "Weaknesses"], section[0]
	description = section[1]
	link = section[2]
	sb_key = 'automatic_abilities'
	ability = {
		'type': 'stat_block_section',
		'subtype': 'ability',
		'ability_type': 'automatic',
		'name': section[0]
	}
	if link:
		# TODO: fix []
		ability['links'] = [link]
	addons = ["Frequency", "Trigger", "Effect", "Duration", "Requirement",
			"Critical Success", "Success", "Failure", "Critical Failure"]
	while len(sections) > 0 and sections[0][0] in addons:
		addon = sections.pop(0)
		assert addon[2] == None
		addon_name = addon[0].lower().replace(" ", "_")
		value = addon[1].strip()
		if value.endswith(";"):
			value = value[:-1]
		ability[addon_name] = value

	description, action = extract_action(description.strip())
	if action:
		ability['action'] = action
		ability['subtype'] = 'ability'
		ability['ability_type'] = 'reactive'
		sb_key = 'reactive_abilities'

	description, traits = extract_starting_traits(description.strip())
	if len(traits) > 0:
		ability['traits'] = traits

	if(len(description) > 0):
		ability['text'] = description.strip()
	sb['defense'].setdefault(sb_key, []).append(ability)

def process_speed(section):
	# 538
	#  <b>Speed</b> 25 feet; <a style="text-decoration:underline" href="Spells.aspx?ID=6"><i>air walk</i></a>

	def build_movement(text):
		movements = build_objects('stat_block_section', 'speed',
			[t.strip() for t in text.split(",")])
		for movement in movements:
			break_out_movement(movement)
			name, modifier = extract_modifier(movement['name'])
			if modifier:
				movement['name'] = name
				#TODO: fix []
				movement['modifiers'] = link_modifiers(
					build_objects(
						'stat_block_section', 'modifier',
						[modifier]))
		return movements
	
	def break_out_movement(movement):
		data = movement['name']
		m = re.match(r"^([a-zA-Z0-9 ]*) \((.*)\)$", data)
		if m:
			# climb 30 feet (<a aonid="299" game-obj="Spells"><i>spider climb</i></a>)
			# burrow 20 feet (snow only)
			data = m.groups()[0]
			content = m.groups()[1]
			content = content.replace("from ", "")
			bs = BeautifulSoup(content, 'html.parser')
			links = get_links(bs)
			if links:
				assert len(links) == 1, movement
				movement['from'] = links[0]
			else:
				#TODO: fix []
				movement['modifiers'] = link_modifiers(
					build_objects(
						'stat_block_section', 'modifier', [content]))
		movement['name'] = data
		if data == "can't move":
			# can't move
			movement['movement_type'] = data
			return
		m = re.match(r"^(\d*) feet$", data)
		if m:
			# 30 feet
			speed = int(m.groups()[0])
			movement['movement_type'] = 'walk'
			movement['value'] = speed
			return
		m = re.match(r"^([a-zA-Z ]*) (\d*) feet$", data)
		if m:
			# fly 30 feet
			mtype = m.groups()[0]
			speed = int(m.groups()[1])
			movement['movement_type'] = mtype
			movement['value'] = speed
			return
		bs = BeautifulSoup(data, 'html.parser')
		if bs.i:
			bs.i.unwrap()
		c = list(bs.children)
		if len(c) == 1 and c[0].name == "a":
			links = get_links(bs)
			movement['name'] = get_text(bs)
			assert len(links) == 1, movement
			movement['from'] = links[0]
			return
		log_element("speed.log")(data)
		assert False, data

	assert section[0] == "Speed", section
	assert section[2] == None, section
	text = section[1].strip()
	parts = [t.strip() for t in text.split(";")]
	text = parts.pop(0)
	modifiers = None
	if len(parts) > 0:
		modifiers = [p.strip() for p in parts.pop().split(",")]
	assert len(parts) == 0, section
	movement = build_movement(text)
	speed = build_object(
		'stat_block_section', 'speeds', 'Speed', {'movement': movement})
	if modifiers:
		speed['modifiers'] = link_modifiers(
			build_objects('stat_block_section', 'modifier', modifiers))
		for m in speed['modifiers']:
			assert m['name'].find("feet") == -1, modifiers
	return speed

def process_offensive_action(section):
	def remove_html_weapon(text, section):
		bs = BeautifulSoup(text, 'html.parser')
		if list(bs.children)[0].name == "i":
			bs.i.unwrap()
		while bs.a:
			_, link = extract_link(bs.a)
			section.setdefault("links", []).append(link)
			bs.a.unwrap()
		return str(bs)
	
	def parse_attack_action(parent_section, attack_type):
		# tentacle +16 [<a aonid="322" game-obj="Rules"><u>+12/+8</u></a>] (<a aonid="170" game-obj="Traits"><u>agile</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>, <a aonid="192" game-obj="Traits"><u>reach 15 feet</u></a>), <b>Damage</b> 2d8+10 bludgeoning plus slime
		# trident +10 [<a aonid="322" game-obj="Rules"><u>+5/+0</u></a>], <b>Damage</b> 1d8+4 piercing
		# trident +7 [<a aonid="322" game-obj="Rules"><u>+2/-3</u></a>] (<a aonid="195" game-obj="Traits"><u>thrown 20 feet</u></a>), <b>Damage</b> 1d8+3 piercing
		# Sphere of Oblivion +37 [<a aonid="322" game-obj="Rules"><u>+32/+27</u></a>] (<a aonid="103" game-obj="Traits"><u>magical</u></a>), <b>Effect</b> see Sphere of Oblivion
		# piercing hymn +17 [<a aonid="322" game-obj="Rules"><u>+12/+7</u></a>] (<a aonid="83" game-obj="Traits"><u>good</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>, <a aonid="248" game-obj="Traits"><u>range 90 feet</u></a>, <a aonid="147" game-obj="Traits"><u>sonic</u></a>), <b>Damage</b> 4d6 sonic damage plus 1d6 good and deafening aria
		# crossbow +14 [<a aonid="322" game-obj="Rules"><u>+9/+4</u></a>] (<a aonid="248" game-obj="Traits"><u>range increment 120 feet</u></a>, <a aonid=\"254\" game-obj="Traits"><u>reload 1</u></a>), <b>Damage</b> 1d8+2 piercing plus crossbow precision
		text = parent_section['text']
		del parent_section['text']
		section = {
			'type': "stat_block_section", "subtype": "attack",
			'attack_type': attack_type, 'name': parent_section['name']
		}
		if 'action' in parent_section:
			section['action'] = parent_section['action']
			del parent_section['action']
		if 'traits' in parent_section:
			section['traits'] = parent_section['traits']
			del parent_section['traits']

		m = re.search(r"^(.*) ([+-]\d*) \[(.*)\] \((.*)\), (.*)$", text)
		if not m:
			m = re.search(r"^(.*) ([+-]\d*) \[(.*)\], (.*)$", text)
		assert m, "Failed to parse: %s" % (text)
		attack_data = list(m.groups())
		section['weapon'] = remove_html_weapon(attack_data.pop(0), section)
		attacks = [attack_data.pop(0)]
		bs = BeautifulSoup(attack_data.pop(0), 'html.parser')
		children = list(bs.children)
		assert len(children) == 1, "Failed to parse: %s" % (text)
		data, link = extract_link(children[0])
		attacks.extend(data.split("/"))
		attacks = [int(a) for a in attacks]
		section['bonus'] = {
			"type": "stat_block_section", "subtype": "attack_bonus",
			"link": link, "bonuses": attacks
		}
		
		damage = attack_data.pop().split(" ")
		_ = damage.pop(0)
		section['damage'] = parse_attack_damage(" ".join(damage).strip())

		if len(attack_data) > 0:
			_, traits = extract_starting_traits("(%s)" %(attack_data.pop()))
			assert 'traits' not in section
			section['traits'] = traits
		assert len(attack_data) == 0, "Failed to parse: %s" % (text)
		parent_section['attack'] = section

	def parse_attack_damage(text):
		ds = split_list(text.strip(), [" plus ", " and "])
		damages = []
		for d in ds:
			damage = {
				"type": "stat_block_section", "subtype": "attack_damage"
			}
			parts = d.split(" ")
			dice = parts.pop(0).strip()
			m = re.match(r"^\d*d\d*.?[0-9]*?$", dice)
			if not m:
				m = re.match(r"^\d*$", dice)
			if m: #damage
				damage["formula"] = dice.replace('–', '-')
				damage_type = ' '.join(parts)
				if damage_type.find("(") > -1:
					parts = damage_type.split("(")
					damage_type = parts.pop(0).strip()
					notes = parts.pop(0).replace(")", "").strip()
					assert len(parts) == 0, "Failed to parse damage: %s" % (text)
					damage["notes"] = notes
				if damage_type.find("damage") > -1:
					# energy touch +36 [<a aonid="322" game-obj="Rules"><u>+32/+28</u></a>] (<a aonid="170" game-obj="Traits"><u>agile</u></a>, <a aonid="99" game-obj="Traits"><u>lawful</u></a>, <a aonid="103" game-obj="Traits"><u>magical</u></a>), <b>Damage</b> 5d8+18 positive or negative damage plus 1d6 lawful
					damage_type = damage_type.replace(" damage", "")
				bs = BeautifulSoup(damage_type, 'html.parser')
				allA = bs.find_all("a")
				links = []
				for a in allA:
					_, link = extract_link(a)
					links.append(link)
				if links:
					damage["links"] = links
				damage_type = get_text(bs).strip()
				if damage_type.startswith("persistent"):
					damage_type = damage_type.replace("persistent ", "")
					damage["persistent"] = True
				if damage_type.find("splash") > -1:
					damage_type = damage_type.replace("splash", "").strip()
					damage["splash"] = True
				damage["damage_type"] = damage_type
			else: #effect
				parts.insert(0, dice)
				damage = parse_attack_effect(parts)
			damages.append(damage)
		return damages

	def parse_attack_effect(parts):
		effect = {
			"type": "stat_block_section", "subtype": "attack_damage"
		}
		bs = BeautifulSoup(' '.join(parts), 'html.parser')
		allA = bs.find_all("a")
		links = []
		for a in allA:
			_, link = extract_link(a)
			links.append(link)
		if links:
			effect["links"] = links
		effect["effect"] = get_text(bs).strip()
		return effect

	def parse_spells(parent_section):
		text = parent_section['text']
		del parent_section['text']
		section = {
			'type': "stat_block_section", "subtype": "spells",
			'name': parent_section['name']
		}
		if 'action' in parent_section:
			section['action'] = parent_section['action']
			del parent_section['action']
		if 'traits' in parent_section:
			section['traits'] = parent_section['traits']
			del parent_section['traits']

		name_parts = section['name'].split(" ")
		if name_parts[-1] != "Formulas":
			section["spell_tradition"] = name_parts.pop(0)
		section["spell_type"] = " ".join(name_parts)
		parts = split_maintain_parens(text, ";")
		tt_parts = split_maintain_parens(parts.pop(0), ",")
		remains = []
		for tt in tt_parts:
			if tt == '':
				continue
			chunks = tt.split(" ")
			if tt.startswith("DC"):
				section["spell_dc"] = int(chunks.pop())
			elif tt.startswith("attack") or tt.startswith("spell attack"):
				section["spell_attack"] = int(chunks.pop())
			elif tt.endswith("Focus Points"):
				section["focus_points"] = int(tt.replace(" Focus Points", "").strip())
			elif tt.endswith("Focus Point"):
				section["focus_points"] = int(tt.replace(" Focus Point", "").strip())
			else:
				remains.append(tt)
		if len(remains) > 0 and remains != tt_parts:
			section['notes'] = remains
			remains = []
		if len(remains) > 0:
			parts.insert(0, ', '.join(remains))
		spell_lists = []
		assert len(parts) > 0, section
		for p in parts:
			spell_lists.append(parse_spell_list(p))
		section['spell_list'] = spell_lists
		parent_section['spells'] = section	

	def parse_spell_list(part):
		spell_list = {"type": "stat_block_section", "subtype": "spell_list"}
		bs = BeautifulSoup(part, 'html.parser')
		level_text = get_text(bs.b.extract())
		if level_text == "Constant":
			spell_list["constant"] = True
			level_text = get_text(bs.b.extract())
		if level_text == "Cantrips":
			spell_list["cantrips"] = True
			level_text = get_text(bs.b.extract())
		m = re.match(r"^\(?(\d*)[snrt][tdh]\)?$", level_text)
		assert m, "Failed to parse spells: %s" % (part)
		spell_list["level"] = int(m.groups()[0])
		spell_list["level_text"] = level_text
		spells_html = split_maintain_parens(str(bs), ",")
		spells = []
		for html in spells_html:
			spells.append(parse_spell(html))
		spell_list["spells"] = spells
		return spell_list

	def parse_spell(html):
		spell = {"type": "stat_block_section", "subtype": "spell"}
		bsh = BeautifulSoup(html, 'html.parser')
		hrefs = bsh.find_all("a")
		links = []
		for a in hrefs:
			_, link = extract_link(a)
			links.append(link)
		spell['links'] = links
		text = get_text(bsh)
		if text.find("(") > -1:
			parts = [t.strip() for t in text.split("(")]
			assert len(parts) == 2, "Failed to parse spell: %s" % (html)
			spell['name'] = parts.pop(0)
			count_text = parts.pop().replace(")", "")
			spell["count_text"] = count_text
			count = None
			for split in [";", ","]:
				remainder = []
				for part in count_text.split(split):
					m = re.match(r"^x\d*$", part.strip())
					if m:
						assert count == None, "Failed to parse spell: %s" % (html)
						count = int(part.strip()[1:])
					else:
						remainder.append(part)
					count_text = split.join(remainder)
			if count:
				spell["count"] = count
		else:
			spell['name'] = text
			spell['count'] = 1
		return spell

	def parse_affliction(parent_section):
		text = parent_section['text']
		del parent_section['text']
		section = {
			'type': "stat_block_section", "subtype": "affliction",
			'name': parent_section['name']
		}
		if 'action' in parent_section:
			section['action'] = parent_section['action']
			del parent_section['action']
		if 'traits' in parent_section:
			section['traits'] = parent_section['traits']
			del parent_section['traits']
		bs = BeautifulSoup(text, 'html.parser')
		section['links'] = get_links(bs)
		while bs.a:
			bs.a.unwrap()
		text = str(bs)
		parts = [p.strip() for p in text.split(";")]
		for p in parts:
			bs = BeautifulSoup(p, 'html.parser')
			if(bs.b):
				title = get_text(bs.b.extract()).strip()
				newtext = get_text(bs).strip()
				if title == 'Saving Throw':
					assert 'saving_throw' not in section, text
					section['saving_throw'] = newtext
				elif title == 'Onset':
					assert 'onset' not in section, text
					section['onset'] = newtext
				elif title == 'Maximum Duration':
					assert 'maximum_duration' not in section, text
					section['maximum_duration'] = newtext
				elif title.startswith('Stage'):
					section.setdefault("stages", []).append(newtext)
				else:
					assert False, text
			else:
				section.setdefault('text', []).append(get_text(bs))
		if 'text' in section:
			section['text'] = '; '.join(section['text'])
		parent_section['affliction'] = section

	def parse_offensive_ability(parent_section):
		def _oa_html_reduction(data):
			bs = BeautifulSoup(''.join(data).strip(), 'html.parser')
			if(list(bs.children)[-1].name == 'br'):
				list(bs.children)[-1].unwrap()
			return str(bs)

		text = parent_section['text']
		del parent_section['text']
		section = {
			'type': "stat_block_section", "subtype": "ability",
			'name': parent_section['name'], "ability_type": "offensive"
		}
		if 'action' in parent_section:
			section['action'] = parent_section['action']
			del parent_section['action']
		if 'traits' in parent_section:
			section['traits'] = parent_section['traits']
			del parent_section['traits']
		bs = BeautifulSoup(text, 'html.parser')
		links = get_links(bs)
		if len(links) > 0:
			section['links'] = links
		while bs.a:
			bs.a.unwrap()
		
		children = list(bs)
		addons = {}
		current = None
		parts = []
		addon_names = ["Frequency", "Trigger", "Effect", "Duration",
			"Requirement", "Requirements", "Prerequisite", "Critical Success",
			"Success", "Failure", "Critical Failure", "Range"]		
		if section['name'] == "Planar Incarnation":
			parts = [str(c) for c in children]
		else: 
			while len(children) > 0:
				child = children.pop(0)
				if child.name == 'b':
					current = get_text(child).strip()
					if current == "Requirements":
						current = "Requirement"
					if current == "Prerequisites":
						current = "Prerequisite"
				elif current:
					assert current in addon_names, "%s, %s" % (current, text)
					addon_text = str(child)
					if addon_text.strip().endswith(";"):
						addon_text = addon_text.strip()[:-1]
					addons.setdefault(current.lower().replace(" ", "_"), [])\
						.append(addon_text)
				else:
					parts.append(str(child))
		for k, v in addons.items():
			section[k] = _oa_html_reduction(v)
		if len(parts) > 0:
			section['text'] = _oa_html_reduction(parts)
		parent_section['ability'] = section
	
	if len(section['sections']) == 0:
		del section['sections']
	section['type'] = 'stat_block_section'
	section['subtype'] = 'offensive_action'
	text = section['text'].strip()
	text, action = extract_action(text)
	if action:
		section['action'] = action
	text, traits = extract_starting_traits(text)
	if len(traits) > 0:
		section['traits'] = traits
	section['text'] = text.strip()
	if section['name'] in ["Melee", "Ranged"]:
		section['offensive_action_type'] = "attack"
		parse_attack_action(section, section['name'].lower())
	elif section['name'].find("Spells") > -1 \
			or section['name'].endswith("Rituals") \
			or section['name'].endswith("Formulas"):
		section['offensive_action_type'] = "spells"
		parse_spells(section)
	else:
		bs = BeautifulSoup(section['text'], 'html.parser')
		if bs.b:
			title = get_text(bs.b)
			if title.strip() in ['Saving Throw']:
				section['offensive_action_type'] = "affliction"
				parse_affliction(section)
			else:
				section['offensive_action_type'] = "ability"
				parse_offensive_ability(section)
		else:
			section['offensive_action_type'] = "ability"
			parse_offensive_ability(section)
	return section

def split_stat_block_line(line):
	line = line.strip()
	parts = line.split(";")
	newparts = []
	for part in parts:
		newparts.extend(part.split(","))
	parts = [p.strip() for p in newparts]
	return parts

def get_attacks(sb):
	def is_attack(section):
		text = section['text']
		children = list(BeautifulSoup(text.strip(), 'html.parser').children)
		test = children.pop(0)
		if test.name == "img":
			if test['alt'].startswith("Sidebar"):
				return False
		if section['name'].startswith("All Monsters"):
			return False
		elif section['name'].startswith("Variant"):
			return False
		return True
	
	sections = sb['sections']
	newsections = []
	attacks = []
	for section in sections:
		if is_attack(section):
			if section['name'].endswith("Spells") or section['name'].endswith("Rituals"):
				text = section['text']
				bs = BeautifulSoup(text.strip(), 'html.parser')
				if bs.br:
					parts = re.split(r" *?\<br ?\/\> *?", text)
					section['text'] = parts.pop(0)
					attacks.append(section)
					for part in parts:
						if part.strip() != "":
							newsection = section.copy()
							for k, v in section.items():
								newsection[k] = v
							bs = BeautifulSoup(part, 'html.parser')
							name = get_text(bs.b.extract())
							newsection["sections"] = []
							newsection["name"] = name
							newsection["text"] = str(bs)
							attacks.append(newsection)
				pass
			else:
				attacks.append(section)
		else:
			newsections.append(section)
	sb['sections'] = newsections
	return attacks

def extract_starting_traits(description):
	if description.strip().startswith("("):
		return _extract_trait(description)
	return description, []

def extract_all_traits(description):
	traits = []
	while description.find("(") > -1:
		description, ts = _extract_trait(description)
		traits.extend(ts)
	return description, traits

def _extract_trait(description):
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
				# TODO - need to solve or cases on traits, Monster ID 518
				return description, []
			parts = [p.strip() for p in text.replace("(", "").split(",")]
			for part in parts:
				bs = BeautifulSoup(part, 'html.parser')
				children = list(bs.children)
				assert len(children) == 1, part
				name, trait_link = extract_link(children[0])
				traits.append(build_object(
					'stat_block_section', 'trait', name.strip(), {'link': trait_link}))
		else:
			newdescription.append(text)
			newdescription.append(")")
		description = back
	newdescription.append(description)
	return ''.join(newdescription).strip(), traits

def parse_section_modifiers(section, key):
	text = section[key]
	text, modifier = extract_modifier(text)
	if modifier:
		#TODO: fix []
		section['modifiers'] = link_modifiers(
			build_objects(
				'stat_block_section', 'modifier', [modifier]))
	section[key] = text
	return section

def parse_section_value(section, key):
	text = section[key]
	m = re.search(r"(.*) (\d*)$", text)
	value = None
	if m:
		text, value = m.groups()
	if value:
		section['value'] = int(value)
	section[key] = text
	return section

def extract_modifier(text):
	if text.find("(") > -1:
		parts = text.split("(", 1)
		assert len(parts) == 2
		base = [parts.pop(0)]
		newparts = parts.pop(0).split(")", 1)
		modifier = newparts.pop(0).strip()
		base.extend(newparts)
		return ' '.join([b.strip() for b in base]).strip(), modifier
	else:
		return text, None

def extract_action(text):
	def build_action(child, action):
		action_name = child['alt']
		image = child['src'].split("\\").pop().split("%5C").pop()
		image_name = image.split(".")[0]
		if not action:
			action = build_object(
				'stat_block_section',
				'action',
				action_name,
				{'image': {
					"type": "image", "name": image_name, "image": image}})
		return action

	children = list(BeautifulSoup(text.strip(), 'html.parser').children)
	action = None
	newchildren = []
	action_names = [
		"Reaction", "Free Action", "Single Action",
		 "Two Actions", "Three Actions"]
	while len(children) > 0:
		child = children.pop(0)
		if child.name == "img" and child['alt'] in action_names:
			action = build_action(child, action)
		else:
			newchildren.append(child)
			newchildren.extend(children)
			break
	text = ''.join([str(c) for c in newchildren]).strip()
	return text, action

def rebuilt_split_modifiers(parts):
	newparts = []
	while len(parts) > 0:
		part = parts.pop(0)
		if part.find("(") > 0:
			newpart = part
			while newpart.find(")") == -1:
				newpart = newpart + ", " + parts.pop(0)
			newparts.append(newpart)
		else:
			newparts.append(part)
	return newparts

def build_objects(dtype, subtype, names, keys=None):
	objects = []
	for name in names:
		objects.append(build_object(dtype, subtype, name, keys))
	return objects

def build_object(dtype, subtype, name, keys=None):
	assert type(name) is str
	obj = {
		'type': dtype,
		'subtype': subtype,
		'name': name
	}
	if keys:
		obj.update(keys)
	return obj

def write_creature(jsondir, struct, source):
	print("%s (%s): %s" %(struct['game-obj'], source, struct['name']))
	filename = create_creature_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_creature_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)

def log_element(fn):
	fp = open(fn, "a+")
	def log_e(element):
		fp.write(element)
		fp.write("\n")
	return log_e

def link_objects(objects):
	for o in objects:
		bs = BeautifulSoup(o['name'], 'html.parser')
		links = get_links(bs)
		if len(links) > 0:
			o['name'] = get_text(bs)
			o['link'] = links[0]
			if len(links) > 1:
				# TODO: fix []
				assert False, objects
	return objects

def link_abilities(abilities):
	for a in abilities:
		bs = BeautifulSoup(a['name'], 'html.parser')
		links = get_links(bs)
		if len(links) > 0:
			a['name'] = get_text(bs)
			a['links'] = links
	return abilities

def split_list(text, splits):
	elements = text.split(splits[0])
	newelements = []
	if len(splits) > 1:
		for element in elements:
			newelements.extend(split_list(element, splits[1:]))
	else:
		newelements.extend(elements)
	return newelements

