import os
import json
import sys
import re
from pprint import pprint
from bs4 import BeautifulSoup
from pfsrd2.universal import parse_universal, print_struct
from pfsrd2.universal import is_trait, get_text, extract_link
from pfsrd2.files import makedirs, char_replace

def parse_creature(filename, output):
	basename = os.path.basename(filename)
	#sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, output, max_title=4)
	struct = restructure_creature_pass(details)
	creature_stat_block_pass(struct)
	source_pass(struct)
	sidebar_pass(struct)
	index_pass(struct)
	aon_pass(struct, basename)
	basename.split("_")
	jsondir = makedirs(output, struct['game-obj'], struct['source']['name'])
	write_creature(jsondir, struct)
	#print(json.dumps(struct, indent=2, sort_keys=True))
	#if struct['type'] == 'section':
	#	if not struct.has_key('name'):
	#		struct['name'] = struct['sections'][0]['name']
	#		struct['name'] = struct['name'].split(",")[0]
	#	write_creature(output, book, struct)
	#elif struct['type'] == 'creature':
	#	write_creature(output, book, struct)
	#else:
	#	raise Exception("Uh Oh")

def restructure_creature_pass(details):
	sb = None
	rest = []
	for obj in details:
		if sb == None and 'subname' in obj and obj['subname'].startswith("Creature"):
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
		sb['language'] = process_languages(stats.pop(0))
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
	sb['defense'] = {}
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
	sb['offense'] = {}
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
	def set_image(obj):
		link = obj['href']
		sb['image'] = {'link': {'href': link.split("\\").pop()}}

	assert section[0] == "Source"
	bs = BeautifulSoup(section[1], 'html.parser')
	c = list(bs.children)
	if len(c) == 1:
		sb['source'] = extract_source(c[0])
	elif len(c) == 2:
		set_image(c[0])
		sb['source'] = extract_source(c[1])
	else:
		raise Exception("Source should have only 1 or 2 pieces")

def process_perception(section):
	assert section[0] == "Perception"
	assert section[2] == None
	parts = split_stat_block_line(section[1])
	value = parts.pop(0)
	value = int(value.replace("+", ""))
	perception = {'value': value}
	if len(parts) > 0:
		if parts[0].startswith("("):
			modifier = parts.pop(0)
			modifier = modifier.replace("(", "").replace(")", "")
			perception['modifier'] = modifier
	if len(parts) > 0:
		special_senses = []
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			children = list(bs.children)
			if children[0].name == "a":
				name, link = extract_link(children[0])
				special_senses.append({
					'name': name,
					'type': 'stat_block_element',
					'subtype': 'special_sense',
					'link': link})
			else:
				special_senses.append({'name': part})
		perception['special_senses'] = special_senses
	return perception

def process_languages(section):
	assert section[0] == "Languages"
	assert section[2] == None
	parts = split_stat_block_line(section[1])
	languages = []
	for language in parts:
		bs = BeautifulSoup(language, 'html.parser')
		c = list(bs.children)
		if len(c) > 1:
			assert c[0].name == 'a'
			assert len(c) == 2
			name, link = extract_link(c[0])
			languages.append({
				'name': name,
				'type': 'stat_block_element',
				'subtype': 'language',
				'link': link})
		else:
			assert len(c) == 1
			if c[0].name == 'a':
				languages.append({
					'name': get_text(bs),
					'type': 'stat_block_element',
					'subtype': 'language',
					'link': {'game-obj': c[0]['game-obj'], 'aonid': c[0]['aonid']}})
			else:
				languages.append({
					'name': get_text(bs),
					'type': 'stat_block_element',
					'subtype': 'language'})
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
			skill['modifier'] = modifier
		skills.append(skill)
	return skills

def process_attr(section):
	assert section[0] in ['Str', 'Dex', 'Con', 'Int', 'Wis', 'Cha']
	assert section[2] == None
	value = int(section[1].replace(",", "").replace("+", ""))
	return value

def process_items(section):
	assert section[0] == "Items"
	assert section[2] == None
	parts = rebuilt_split_modifiers(split_stat_block_line(section[1]))
	items = []
	for part in parts:
		bs = BeautifulSoup(part, 'html.parser')
		children = list(bs.children)
		if children[0].name == 'a':
			_, link = extract_link(children[0])
			text = get_text(bs)
			name, modifier = extract_modifier(text)
			item = {
				'type': 'stat_block_element',
				'subtype': 'item',
				'item': name,
				'link': link}
			if modifier:
				modifiers = modifier.split(",")
				item['modifiers'] = modifiers
			items.append(item)
		else:
			items.append({
				'type': 'stat_block_element',
				'subtype': 'item',
				'item': part})
	return items

def process_interaction_ability(section):
	ability_name = section[0]
	description = section[1]
	link = section[2]
	ability = {
		'name': ability_name,
		'type': 'stat_block_element',
		'subtype': 'interaction_ability'}
	description, traits = extract_traits(description)
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
	value, modifier = extract_modifier(text)
	ac = {
		'type': 'stat_block_element',
		'subtype': 'armor_class',
		'value': int(value.strip())
	}
	if modifier:
		modifiers = [m.strip() for m in modifier.split(";")]
		ac['modifiers'] = modifiers
	return ac

def process_saves(fort, ref, will):
	saves = {
		'type': 'stat_block_element',
		'subtype': 'saves',
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
			saves['bonuses'] = bonuses
		value, modifier = extract_modifier(value)
		save = {
			'name': section[0],
			'value': int(value.strip().replace("+", ""))}
		if modifier:
			modifiers = [m.strip() for m in modifier.split(",")]
			save['modifiers'] = modifiers
		saves[name] = save

	process_save(fort)
	process_save(ref)
	process_save(will)
	return saves

def process_hp(section, name):
	assert section[0] in ["HP", "Hardness"]
	assert section[2] == None
	text = section[1].strip()
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
		'subtype': name,
		'value': value}
	if len(specials) > 0:
		hp['special'] = specials
	return hp

def process_defense(sb, section):
	assert section[0] in ["Immunities", "Resistances", "Weaknesses"]
	assert section[2] == None
	text = section[1].strip()
	if(text.endswith(";")):
		text = text[:-1].strip()
	parts = rebuilt_split_modifiers(split_stat_block_line(text))
	sb[section[0].lower()] = parts

def process_defensive_ability(section, sections, sb):
	assert section[0] not in ["Immunities", "Resistances", "Weaknesses"]
	description = section[1]
	link = section[2]
	sb_key = 'automatic_abilities'
	ability = {
		'type': 'stat_block_element',
		'subtype': 'automatic_ability',
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
	description, traits = extract_traits(description)
	description = description.strip()

	if len(traits) > 0:
		ability['traits'] = traits
	
	description, action = extract_action(description)
	if action:
		ability['action'] = action
		ability['subtype'] = 'reactive_ability'
		sb_key = 'reactive_abilities'

	if(len(description) > 0):
		ability['text'] = description
	sb.setdefault(sb_key, []).append(ability)

def process_speed(section):
	assert section[0] == "Speed"
	assert section[2] == None
	text = section[1].strip()
	parts = [t.strip() for t in text.split(";")]
	text = parts.pop(0)
	modifiers = None
	if len(parts) > 0:
		modifiers = parts.pop()
	assert len(parts) == 0
	speeds = [t.strip() for t in text.split(",")]
	speed = {
		'type': 'stat_block_element',
		'subtype': 'speed',
		'movements': speeds
	}
	if modifiers:
		speed['modifiers'] = [modifiers]
	return speed

def process_offensive_action(section):
	if len(section['sections']) == 0:
		del section['sections']
	section['type'] = 'offensive_action'
	text = section['text']
	text, action = extract_action(text)
	if action:
		section['action'] = action
	text, traits = extract_traits(text)
	if len(traits) > 0:
		section['traits'] = traits
	section['text'] = text
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
	return {'name': name, 'link': link, 'page': page}

def extract_traits(description):
	traits = []
	if(description.startswith('(')):
		text, description = description.split(")", 1)
		parts = [p.strip() for p in text.replace("(", "").split(",")]
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			children = list(bs.children)
			assert len(children) == 1
			name, trait_link = extract_link(children[0])
			traits.append({
				'type': 'stat_block_element',
				'subtype': 'trait',
				'name': name,
				'link': trait_link})
	return description.strip(), traits

def extract_modifier(text):
	if text.find("(") > -1:
		parts = text.split("(")
		assert len(parts) == 2
		base = parts.pop(0).strip()
		modifier = parts.pop(0).replace(")", "").strip()
		return base, modifier
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
				action = {'action': action_name, 'image': image}
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

#def monster_race_pass(struct):
#	for child in struct.get('sections', []):
#		if child.get('name', '').strip().endswith('Characters'):
#			child['name'] = child['name'].replace('Characters', '').strip()
#			child['type'] = 'race'
#			child['subtype'] = 'monster_race'
#		else:
#			monster_race_pass(child)
#	return struct

#def collapse_pass(struct):
#	if struct['type'] == 'section' and len(struct.get('sections', [])) == 1 and struct['sections'][0]['type'] == 'creature':
#		soup = BeautifulSoup(struct['text'])
#		mon = struct['sections'][0]
#		mon['description'] = ''.join(soup.findAll(text=True))
#		mon['name'] = struct['name']
#		return mon
#	newchildren = []
#	for child in struct.get('sections', []):
#		newchildren.append(collapse_pass(child))
#	if len(newchildren) > 0:
#		struct['sections'] = newchildren
#	return struct

#def animal_companion_pass(struct):
#	newsections = []
#	for section in struct.get('sections', []):
#		if section.get('name', '').endswith('Companion') or section.get('name', '').endswith('Companions'):
#			name = section['name'].replace(' Animal Companion', '')
#			name = name.replace(' Companions', '')
#			nsec = section['sections'].pop(0)
#			nsec['name'] = name
#			nsec['sections'] = section['sections']
#			animalsec = newsections[-1].setdefault('sections', [])
#			animalsec.append(nsec)
#		else:
#			newsections.append(animal_companion_pass(section))
#	struct['sections'] = newsections
#	return struct

#def familiar_pass(rules, basename):
#	if basename in ['familiar.html', 'newFamiliars.html']:
#		creatures = find_all_sections(rules, section_type='creature')
#		for creature in creatures:
#			creature['subtype'] = 'familiar'
#	return rules

#def rule_pass(struct):
#	newsections = []
#	last_creature = None
#	for section in struct['sections']:
#		if section['type'] == 'creature':
#			newsections.append(section)
#			last_creature = section
#		else:
#			if not last_creature:
#				newsections.append(section)
#			else:
#				csec = last_creature.setdefault('sections', [])
#				csec.append(section)
#	struct['sections'] = newsections
#	return struct


def write_creature(jsondir, struct):
	print("%s: %s" %(struct['game-obj'], struct['name']))
	filename = create_creature_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_creature_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)
