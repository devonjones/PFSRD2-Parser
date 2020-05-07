import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from pfsrd2.universal import parse_universal, print_struct
from pfsrd2.universal import is_trait, get_text, extract_link
from pfsrd2.files import makedirs, char_replace

def parse_creature(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, max_title=4)
	struct = restructure_creature_pass(details)
	creature_stat_block_pass(struct)
	source_pass(struct)
	sidebar_pass(struct)
	index_pass(struct)
	aon_pass(struct, basename)
	#validate_dict_pass(struct, struct, None, "")
	remove_empty_sections_pass(struct)
	basename.split("_")
	if not options.dryrun:
		output = options.output
		jsondir = makedirs(output, struct['game-obj'], struct['source']['name'])
		write_creature(jsondir, struct)
	elif options.stdout:
		print(json.dumps(struct, indent=2))

def restructure_creature_pass(details):
	sb = None
	rest = []
	for obj in details:
		if sb == None and 'subname' in obj and obj['subname'].startswith(
				"Creature"):
			assert not sb
			sb = obj
		else:
			rest.append(obj)
	top = {'name': sb['name'], 'type': 'creature', 'sections': [sb]}
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

def creature_stat_block_pass(struct):
	def add_to_data(key, value, data, link):
		if key:
			data.append((key, ''.join([str(v) for v in value]).strip(), link))
			key = None
			value = []
			link = None
		return key, value, data, link

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
			trait = parse_trait(obj)
			sb.setdefault('traits', []).append(trait)
		elif obj.name == "br":
			key, value, data, link = add_to_data(key, value, data, link)
		elif obj.name == 'hr':
			key, value, data, link = add_to_data(key, value, data, link)
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
	sections.append(data)
	assert len(sections) == 3
	process_stat_block(sb, sections)

def source_pass(struct):
	def _extract_source(section):
		if 'text' in section:
			bs = BeautifulSoup(section['text'], 'html.parser')
			children = list(bs.children)
			if children[0].name == "b" and get_text(children[0]) == "Source":
				children.pop(0)
				book = children.pop(0)
				source = extract_source(book)
				if children[0].name == "br":
					children.pop(0)
				section['text'] = ''.join([str(c) for c in children])
				return source
	
	def propagate_source(section, source):
		retval = _extract_source(section)
		if retval:
			source = retval
		if 'source' in section:
			source = section['source']
		else:
			section['source'] = source
		for s in section['sections']:
			propagate_source(s, source)

	if 'source' not in struct:
		sb = find_stat_block(struct)
		struct['source'] = sb['source']
	source = struct['source']
	for section in struct['sections']:
		propagate_source(section, source)

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
			image = c['src'].split("\\").pop()
			subtype = c['alt'].split("-").pop().strip()
			struct['type'] = "sidebar"
			struct['subtype'] = subtype.lower().replace(" ", "_")
			struct['sidebar_heading'] = subtype
			struct['image'] = image
			struct['text'] = ''.join([str(c) for c in children])

def index_pass(struct):
	for section in struct['sections']:
		index_pass(section)
	if struct['name'].startswith("All Monsters"):
		struct['type'] = "index"

def aon_pass(struct, basename):
	parts = basename.split("_")
	assert len(parts) == 2
	struct["aonid"] = int(parts[1])
	struct["game-obj"] = parts[0].split(".")[0]

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

def remove_empty_sections_pass(struct):
	for section in struct['sections']:
		remove_empty_sections_pass(section)
		if len(section['sections']) == 0:
			del section['sections']

def parse_trait(span):
	name = ''.join(span['alt']).replace(" Trait", "")
	trait_class = ''.join(span['class'])
	if trait_class != 'trait':
		trait_class = trait_class.replace('trait', '')
	text = ''.join(span['title'])
	trait = {
		'name': name,
		'class': trait_class,
		'text': text,
		'type': 'stat_block_element',
		'subtype': 'trait'}
	c = list(span.children)
	if len(c) == 1:
		if c[0].name == "a":
			_, link = extract_link(c[0])
			trait['link'] = link
	else:
		raise Exception("You should not be able to get here")
	return trait

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
	sb['offense']['speed'] = process_speed(offense.pop(0))
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
	def set_image(obj, name):
		link = obj['href']
		image = link.split("\\").pop()
		sb['image'] = {
			'type': 'image', 'name': name, 'game-obj': 'Monster',
			'image': image}

	assert section[0] == "Source"
	bs = BeautifulSoup(section[1], 'html.parser')
	c = list(bs.children)
	if len(c) == 1:
		sb['source'] = extract_source(c[0])
	elif len(c) == 2:
		set_image(c[0], sb['name'])
		sb['source'] = extract_source(c[1])
	else:
		raise Exception("Source should have only 1 or 2 pieces")

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
			perception['modifiers'] = build_objects(
				'stat_block_section', 'modifier', [modifier])
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
				sense['modifiers'] = build_objects(
					'stat_block_section', 'modifier', [modifier])
			special_senses.append(sense)
		perception['special_senses'] = special_senses
	return perception

def process_languages(section):
	assert section[0] == "Languages"
	assert section[2] == None
	text = section[1]
	languages = build_object(
		'stat_block_element', 'languages', 'Languages', {'languages': []})
	if text.find(";") > -1:
		parts = text.split(";")
		text = parts.pop(0)
		assert len(parts) == 1
		parts = rebuilt_split_modifiers(split_stat_block_line(parts.pop()))
		abilities = []
		for part in parts:
			newtext, modifier = extract_modifier(part.strip())
			if newtext.strip() == "":
				languages['modifiers'] = build_objects(
						'stat_block_section', 'modifier',
						[m.strip() for m in modifier.split(",")])
			else:
				bs = BeautifulSoup(newtext, 'html.parser')
				link = None
				if bs.a:
					newtext, link = extract_link(bs.a)

				ability = build_object(
				'stat_block_section', 'ability', newtext, {
					'ability_type': 'communication'})
				if link:
					ability['link'] = link
				if(modifier):
					ability['modifiers'] = build_objects(
						'stat_block_section', 'modifier',
						[m.strip() for m in modifier.split(",")])
				abilities.append(ability)
		if len(abilities) > 0:
			languages['communication_abilities'] = abilities
	parts = rebuilt_split_modifiers(split_stat_block_line(text))
	for text in parts:
		text, modifier = extract_modifier(text)
		bs = BeautifulSoup(text, 'html.parser')
		c = list(bs.children)

		if len(c) > 1:
			assert c[0].name == 'a'
			assert len(c) == 2
			name, link = extract_link(c[0])
			language = {
				'name': name,
				'type': 'stat_block_element',
				'subtype': 'language',
				'link': link}
		else:
			assert len(c) == 1
			if c[0].name == 'a':
				link = extract_link(c[0])
				language = {
					'name': get_text(bs),
					'type': 'stat_block_element',
					'subtype': 'language',
					'link': link}
			else:
				language = {
					'name': get_text(bs),
					'type': 'stat_block_element',
					'subtype': 'language'}
		if modifier:
			language['modifiers'] = build_objects(
				'stat_block_section', 'modifier', [modifier])
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
			'type': 'stat_block_element',
			'subtype': 'skill',
			'name': name,
			'link': link,
			'value': value}
		if modifier:
			skill['modifiers'] = build_objects(
				'stat_block_section', 'modifier', [modifier])
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
		html = str(bs)
		name = get_text(bs)
		children = list(bs.children)
		item = {
			'type': 'stat_block_element',
			'subtype': 'item',
			'name': name.strip(),
			'html': html.strip()}
		if modifier:
			modifiers = modifier.split(",")
			item['modifiers'] = build_objects(
				'stat_block_section', 'modifier', modifiers)
		references = []
		for a in bs.findAll("a"):
			_, link = extract_link(a)
			references.append(link)
		if len(references) > 0:
			item['references'] = references
		items.append(item)
	return items

def process_interaction_ability(section):
	ability_name = section[0]
	description = section[1]
	link = section[2]
	ability = {
		'name': ability_name,
		'type': 'stat_block_element',
		'subtype': 'interaction_ability'}
	description, traits = extract_all_traits(description)
	if len(traits) > 0:
		ability['traits'] = traits
	ability['text'] = description
	if link:
		ability['link'] = link
	return ability

def process_ac(section):
	assert section[0] == "AC"
	assert section[1].endswith(",")
	assert section[2] == None
	text = section[1][:-1]
	modifiers = []
	value, modifier = extract_modifier(text)
	if modifier:
		modifiers = [m.strip() for m in modifier.split(";")]
	if value.find(";") > -1:
		parts = value.split(";")
		value = parts.pop(0)
		modifiers.extend([m.strip() for m in parts])
	ac = {
		'type': 'stat_block_element',
		'subtype': 'armor_class',
		'name': "AC",
		'value': int(value.strip())
	}
	if len(modifiers) > 0:
		ac['modifiers'] = build_objects(
			'stat_block_section', 'modifier', modifiers)
	return ac

def process_saves(fort, ref, will):
	saves = {
		'type': 'stat_block_element',
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
			saves['modifiers'] = build_objects(
				'stat_block_section', 'modifier', bonuses)
		value, modifier = extract_modifier(value)
		save = {
			'type': "stat_block_section",
			'subtype': "save",
			'name': section[0],
			'value': int(value.strip().replace("+", ""))}
		if modifier:
			modifiers = [m.strip() for m in modifier.split(",")]
			save['modifiers'] = build_objects(
				'stat_block_section', 'modifier', modifiers)
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
	value, text = re.search("^(\d*)(.*)", text).groups()
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
		'type': 'stat_block_element',
		'subtype': subtype,
		'name': name,
		'value': value}
	if len(specials) > 0:
		special_sections = build_objects(
			'stat_block_section', 'ability', specials, {
				'ability_type': 'automatic'})
		for section in special_sections:
			parse_section_modifiers(section, 'name')
			parse_section_value(section, 'name')
		hp['automatic_abilities'] = special_sections


	return hp

def process_defense(sb, section):
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
		d = {
			'type': 'stat_block_section',
			'subtype': subtype[section[0]],
			'name': part}
		d = parse_section_modifiers(d, 'name')
		d = parse_section_value(d, 'name')
		defense[section[0].lower()].append(d)
	sb[section[0].lower()] = defense

def process_defensive_ability(section, sections, sb):
	assert section[0] not in ["Immunities", "Resistances", "Weaknesses"]
	description = section[1]
	link = section[2]
	sb_key = 'automatic_abilities'
	ability = {
		'type': 'stat_block_element',
		'subtype': 'ability',
		'ability_type': 'automatic',
		'name': section[0]
	}
	if link:
		ability['link'] = link
	addons = ["Frequency", "Trigger", "Effect", "Duration", "Requirement",
			"Critical Success", "Success", "Failure", "Critical Failure"]
	while len(sections) > 0 and sections[0][0] in addons:
		addon = sections.pop(0)
		assert addon[2] == None
		ability[addon[0].lower()] = addon[1]
	description, traits = extract_starting_traits(description)
	description = description.strip()

	if len(traits) > 0:
		ability['traits'] = traits
	
	description, action = extract_action(description)
	if action:
		ability['action'] = action
		ability['subtype'] = 'ability'
		ability['ability_type'] = 'reactive'
		sb_key = 'reactive_abilities'

	if(len(description) > 0):
		ability['text'] = description
	sb.setdefault(sb_key, []).append(ability)

def process_speed(section):
	def build_movement(text):
		movements = build_objects('stat_block_section', 'speed',
			[t.strip() for t in text.split(",")])
		for movement in movements:
			name, modifier = extract_modifier(movement['name'])
			if modifier:
				movement['name'] = name
				bs = BeautifulSoup(modifier, 'html.parser')
				if bs.a:
					_, link = extract_link(bs.a)
					modifier = get_text(bs)
					movement['modifiers'] = build_objects(
						'stat_block_section', 'modifier',
						[modifier], {'link': link})
				else:
					movement['modifiers'] = build_objects(
						'stat_block_section', 'modifier', [modifier])
		return movements
	
	assert section[0] == "Speed"
	assert section[2] == None
	text = section[1].strip()
	parts = [t.strip() for t in text.split(";")]
	text = parts.pop(0)
	modifier = None
	if len(parts) > 0:
		modifier = parts.pop()
	assert len(parts) == 0
	movement = build_movement(text)
	speed = build_object(
		'stat_block_element', 'speed', 'Speed', {'movement': movement})
	if modifier:
		speed['modifiers'] = build_objects(
				'stat_block_section', 'modifier', [modifier])
	return speed

def process_offensive_action(section):
	if len(section['sections']) == 0:
		del section['sections']
	section['type'] = 'offensive_action'
	text = section['text'].strip()
	text, action = extract_action(text)
	if action:
		section['action'] = action
	text, traits = extract_starting_traits(text)
	if len(traits) > 0:
		section['traits'] = traits
	section['text'] = text.strip()
	if section['name'] == "Melee":
		section['subtype'] = "melee"
	elif section['name'] == "Ranged":
		section['subtype'] = "ranged"
	elif section['name'].endswith("Spells"):
		section['subtype'] = "spells"
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
			attacks.append(section)
		else:
			newsections.append(section)
	sb['sections'] = newsections
	return attacks

def extract_source(obj):
	text, link = extract_link(obj)
	parts = text.split(" pg. ")
	assert len(parts) == 2
	name = parts.pop(0)
	page = int(parts.pop(0))
	return {'type': 'source', 'name': name, 'link': link, 'page': page}

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
		text, back = middle.split(")", 1)
		bs = BeautifulSoup(text, 'html.parser')
		if bs.a and bs.a.has_attr('game-obj') and bs.a['game-obj'] == 'Traits':
			if text.find(" or ") > -1:
				# TODO - need to solve or cases on traits, Monster ID 518
				return description, []
			parts = [p.strip() for p in text.replace("(", "").split(",")]
			for part in parts:
				bs = BeautifulSoup(part, 'html.parser')
				children = list(bs.children)
				assert len(children) == 1
				name, trait_link = extract_link(children[0])
				traits.append(build_object(
					'stat_block_element', 'trait', name, {'link': trait_link}))
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
		modifiers = modifier.split(",")		
		section['modifiers'] = build_objects(
				'stat_block_section', 'modifier', [modifier])
	section[key] = text
	return section

def parse_section_value(section, key):
	text = section[key]
	m = re.search("(.*) (\d*)$", text)
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
	children = list(BeautifulSoup(text.strip(), 'html.parser').children)
	action = None
	newchildren = []
	action_names = [
		"Reaction", "Free Action", "Single Action",
		 "Two Actions", "Three Actions"]
	while len(children) > 0:
		child = children.pop(0)
		if child.name == "img" and child['alt'] in action_names:
			action_name = child['alt']
			image = child['src'].split("\\").pop()
			if not action:
				action = build_object(
					'stat_block_section',
					'action',
					action_name,
					{'image': image})
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

def write_creature(jsondir, struct):
	print("%s: %s" %(struct['game-obj'], struct['name']))
	filename = create_creature_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_creature_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)
