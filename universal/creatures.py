import os
import json
import re
from pprint import pprint
from universal.universal import modifiers_from_string_list, extract_modifiers
from universal.universal import link_values, get_links, get_text
from universal.universal import split_maintain_parens
from universal.universal import string_values_from_string_list
from universal.universal import string_with_modifiers_from_string_list
from universal.universal import string_with_modifiers
from universal.universal import split_comma_and_semicolon
from universal.files import char_replace
from universal.utils import log_element, clear_tags
from bs4 import BeautifulSoup


def write_creature(jsondir, struct, source):
	print("%s (%s): %s" %(struct['game-obj'], source, struct['name']))
	filename = create_creature_filename(jsondir, struct)
	fp = open(filename, 'w')
	json.dump(struct, fp, indent=4)
	fp.close()

def create_creature_filename(jsondir, struct):
	title = jsondir + "/" + char_replace(struct['name']) + ".json"
	return os.path.abspath(title)

def universal_handle_senses():
	senses = {
		"type": "stat_block_section",
		"subtype": "senses",
	}
	return senses

def universal_handle_modifier_breakout(section):
	def _handle_modifier_range(section, modifier):
		if "[" in modifier["name"]:
			return modifier
		range = universal_handle_range(modifier["name"])
		if range:
			section['range'] = range
			return None
		return modifier
	def _handle_modifier_dc(section, modifier):
		if modifier:
			if "[" in modifier["name"]:
				return modifier
			text = modifier["name"]
			if "DC" in text:
				section["saving_throw"] = universal_handle_save_dc(text)
				return None
		return modifier
	def _handle_modifier_damage(section, modifier):
		def _handle_dam(m):
			groups = m.groups()
			assert len(groups) == 2, groups
			if "damage" in section:
				damage = section["damage"]
			else:
				damage = {
					"type": "stat_block_section",
					"subtype": "attack_damage"
				}
			damage["formula"] = groups[0]
			damage_types = {
				"A": "Acid",
				"B": "Bludgeoning",
				"C": "Cold",
				"E": "Electricity",
				"F": "Fire",
				"force": "Force",
				"P": "Piercing",
				"S": "Slashing",
				"So": "Sonic",
				"E & F": "Electricity & Fire",
				"B & F": "Bludgeoning & Fire",
				"B & S": "Bludgeoning & Slashing",
				"P & F": "Piercing & Fire",
				"random": "Random type"
			}
			damage_type = groups[1]
			if 'plus' in damage_type:
				damage_type, effect = damage_type.split("plus")
				damage_type = damage_type.strip()
				assert "effect" not in damage, "Damage already has effect: %s, %s" % (damage, effect)
				damage["effect"] = effect.strip()
			if damage_type not in damage_types:
				return modifier
			damage["damage_type"] = damage_types[damage_type]
			damage["damage_type_text"] = damage_type
			section["damage"] = damage
			return None

		if modifier:
			if "[" in modifier["name"]:
				return modifier
			m = re.search(r'^(\d*d\d*) (.*)$', modifier["name"])
			if m:
				return _handle_dam(m)
			m = re.search(r'^(\d*d\d*\+\d*) (.*)$', modifier["name"])
			if m:
				return _handle_dam(m)
		return modifier
	def _handle_modifier_effect(section, modifier):
		if modifier:
			if "[" in modifier["name"]:
				return modifier
			m = re.search(r'^([a-zA-Z]*) (\d*)d?(\d?) ([a-zA-Z]*)$', modifier["name"])
			if m:
				groups = m.groups()
				assert len(groups) == 4, groups
				if "damage" in section:
					damage = section["damage"]
				else:
					damage = {
						"type": "stat_block_section",
						"subtype": "attack_damage"
					}
				assert "effect" not in damage, "Damage already has effect: %s, %s" % (damage, damage["effect"])
				damage["effect"] = modifier["name"]
				section["damage"] = damage
				return None
		return modifier
	def _handle_modifier_hp(section, modifier):
		if modifier:
			if "[" in modifier["name"]:
				return modifier
			m = re.search(r'^(\d*) hp$', modifier["name"].lower())
			if m:
				groups = m.groups()
				assert len(groups) == 1, groups
				section["hp"] = int(groups[0])
				return None
		return modifier
	def _handle_modifier_kac(section, modifier):
		if modifier:
			if "[" in modifier["name"]:
				return modifier
			m = re.search(r'^kac (\d*)$', modifier["name"].lower())
			if m:
				groups = m.groups()
				assert len(groups) == 1, groups
				section["kac"] = int(groups[0])
				return None
		return modifier
	def _handle_modifier_eac(section, modifier):
		if modifier:
			if "[" in modifier["name"]:
				return modifier
			m = re.search(r'^eac (\d*)$', modifier["name"].lower())
			if m:
				groups = m.groups()
				assert len(groups) == 1, groups
				section["eac"] = int(groups[0])
				return None
		return modifier

	newmods = []
	if "modifiers" in section:
		for modifier in section['modifiers']:
			modifier = _handle_modifier_range(section, modifier)
			modifier = _handle_modifier_dc(section, modifier)
			modifier = _handle_modifier_damage(section, modifier)
			modifier = _handle_modifier_effect(section, modifier)
			modifier = _handle_modifier_hp(section, modifier)
			modifier = _handle_modifier_kac(section, modifier)
			modifier = _handle_modifier_eac(section, modifier)
			if modifier:
				newmods.append(modifier)
		section["modifiers"] = newmods
		if len(newmods) == 0:
			del section["modifiers"]
	return section

def universal_handle_aura(value):
	auras = string_with_modifiers_from_string_list(
		split_maintain_parens(str(value).strip(), ","),
		"aura")
	auras = link_values(auras)
	for aura in auras:
		universal_handle_modifier_breakout(aura)
	return auras

def universal_handle_range(text):
	m = re.search(r'^(\d*) (.*)$', text)
	if m:
		groups = m.groups()
		assert len(groups) == 2, groups
		unit = groups[1]
		unit, modifiers = extract_modifiers(unit)
		if unit.endswith('.'):
			unit = unit[:-1]
		if unit in ["ft", "feet", "mile", "miles"]:
			if unit == "ft":
				unit = "feet"
			if unit == "mile":
				unit = "miles"

			range = {
				"type": "stat_block_section",
				"subtype": "range",
				"text": text,
				"range": int(groups[0]),
				"unit": unit
			}
			if modifiers:
				range["modifiers"] = modifiers
			return range
	return None

def universal_handle_save_dc(text):
	# Fortitude DC 22
	# DC 22
	# DC 22 Fortitude
	# DC 22 half

	assert "DC" in text, "Saves must have DCs: %s" % text
	if text.endswith(","):
		text = text[:-1]
	save_dc = {
		"type": "stat_block_section",
		"subtype": "save_dc",
		"text": text
	}
	text, modifiers = extract_modifiers(text)
	if modifiers:
		save_dc["modifiers"] = modifiers
	parts = text.split(" ")
	types = {
		"Fortitude": "Fort",
		"Fort": "Fort",
		"Reflex": "Ref",
		"Ref": "Ref",
		"Will": "Will",
		"Strength": "Str"
	}
	newparts = []
	for part in parts:
		if part == "DC":
			continue
		elif part.isnumeric():
			save_dc["dc"] = int(part)
		elif part in types:
			save_dc["save_type"] = types[part]
		else:
			newparts.append(part)
	if newparts:
		result = " ".join(newparts)
		if "half" in result:
			save_dc['result'] = result
		elif "negates" in result:
			save_dc['result'] = result
		elif "basic" in result:
			save_dc['result'] = result
		else:
			assert False, "Broken DC: %s" % text
	return save_dc

def universal_handle_perception(value):
	# +10
	# +13 (+15 with vision)
	# +6 (–2 to hear things)
	# +18 (+20 to detect lies and illusions)
	# +22 (+30 in space)
	# +8 (or +13)
	# +28 (32 to detect illusions)

	perception = {
		"type": "stat_block_section",
		"subtype": "perception"
	}
	text = str(value).strip()
	if text.startswith('+'):
		text = text[1:].strip()
	text, modifiers = extract_modifiers(text)
	if modifiers:
		perception['modifiers'] = modifiers
	perception["value"] = int(text)
	return perception

def universal_handle_special_senses(parts):
	# Array of:
	# <a aonid="65" game-obj="Spells"><i>detect alignment</i></a> (chaotic only)
	# darkvision 60 ft.
	# blindsense (thought) 30 ft.
	# blindsense (scent, vibration) 60 ft.
	# sense through (vision [life-forms only]) 60 ft.
	# sense through (vision [crystal only])

	def _get_link(part):
		bs = BeautifulSoup(part, 'html.parser')
		links = get_links(bs)
		assert len(links) <= 1, "Multiple links found where one expected: %s" % part
		if len(links) == 1:
			sense['link'] = links[0]
		return get_text(bs)

	def _handle_special_sense_range(text, sense):
		m = re.search(r'(.*) (\d*) (.*)', text)
		if m:
			range = {
				"type": "stat_block_section",
				"subtype": "range",
			}

			groups = m.groups()
			assert len(groups) == 3, groups
			range["range"] = int(groups[1])
			range["text"] = "%s %s" % (groups[1], groups[2])
			unit = groups[2]
			if unit == "ft.":
				unit = "feet"
			if unit == "mile":
				unit = "miles"
			assert unit in ["feet", "miles"], "Bad special sense range: %s" % text
			range["unit"] = unit
			sense["range"] = range
			text = groups[0].strip()
		return text
	
	special_senses = []
	for part in parts:
		sense = {
			"type": "stat_block_section",
			"subtype": "special_sense",
		}
		part = _handle_special_sense_range(part, sense)
		if part.find("(") > -1:
			assert part.endswith(")"), part
			parts = [p.strip() for p in part.split("(")]
			assert len(parts) == 2, part
			part = parts.pop(0)
			mods = parts.pop()
			mparts = [m.strip() for m in mods[0:-1].split(",")]
			modifiers = modifiers_from_string_list(mparts)
			sense["modifiers"] = link_values(modifiers)
		part = _get_link(part)
		
		sense["name"] = part
		special_senses.append(sense)
	special_senses = link_values(special_senses, singleton=True)
	return special_senses

def universal_handle_size(s):
	sizes = [
		"Fine", "Diminutive", "Tiny", "Small", "Medium", "Large", "Huge",
		"Gargantuan", "Colossal"]
	if s in sizes:
		return s
	assert s in sizes, s

def universal_handle_alignment(abbrev):
	alignments = {
		'LG': "Lawful Good",
		'LN': "Lawful Neutral",
		'LE': "Lawful Evil",
		'NG': "Neutral Good",
		'N': "Neutral",
		'NE': "Neutral Evil",
		'CG': "Chaotic Good",
		'CN': "Chaotic Neutral",
		'CE': "Chaotic Evil",
		'Any': "Any alignment",
	}
	if abbrev in alignments:
		return alignments[abbrev]

def universal_handle_creature_type(ct, subtype):
	def _handle_creature_subtypes(subtype):
		subtype = subtype.replace(")", "")
		assert subtype.find(")") == -1, "Malformed subtypes: %s" % subtype
		subtypes = string_values_from_string_list(
			split_maintain_parens(subtype, ","),
			"creature_subtype")
		return subtypes

	types = [
		"Aberration", "Animal", "Construct", "Dragon", "Fey", "Humanoid",
		"Magical Beast", "Monstrous Humanoid", "Ooze", "Outsider", "Plant",
		"Undead", "Vermin"]
	if ct in types:
		creature_type = {
			"type": "stat_block_section",
			"subtype": "creature_type",
			"creature_type": ct
		}
		if subtype and len(subtype) > 0:
			creature_type['creature_subtypes'] = _handle_creature_subtypes(subtype)
		return creature_type
	assert ct in types, ct

def universal_handle_languages(text):
	def _handle_communication_abilities(parts):
		comtext = clear_tags(", ".join(parts), ["i"])
		parts = split_maintain_parens(comtext, ",")
		coms = []
		for part in parts:
			text, crange = _handle_communication_ability_range(part)
			com = string_with_modifiers(text, "communication_ability")
			if crange:
				com["range"] = crange
			if 'modifiers' in com:
				newmods = []
				for modifier in com['modifiers']:
					crange = universal_handle_range(modifier['name'])
					if crange:
						assert 'range' not in com, "broken communication ability: %s" % comtext
						com['range'] = crange
					else:
						newmods.append(modifier)
				if len(newmods) > 0:
					com['modifiers'] = newmods
				else:
					del com['modifiers']
			coms.append(com)
		return coms
	def _handle_communication_ability_range(text):
		m = re.search(r'^(.*) (\d*) (.*)$', text)
		if m:
			groups = m.groups()
			assert len(groups) == 3, groups
			text = groups[0]
			rangetext = "%s %s" % (groups[1], groups[2])
			crange = universal_handle_range(rangetext)
			assert crange, "communication ability range broken: %s" % text
			return text, crange
		return text, None

	parts = text.split(";")
	languages = {
		"type": "stat_block_section",
		"subtype": "languages",
		"languages": []
	}
	langs = parts.pop(0)
	lparts = split_maintain_parens(langs, ",")

	for lpart in lparts:
		if "telepathy" in lpart:
			parts.append(lpart)
		elif "ft." in lpart:
			parts.append(lpart)
		else:
			language = {
				"type": "stat_block_section",
				"subtype": "language",
			}
			ltext, modifiers = extract_modifiers(lpart)
			bs = BeautifulSoup(ltext, 'html.parser')
			links = get_links(bs)
			if len(links) > 0:
				assert len(links) == 1, "Malformed language: %s" % ltext
				language['link'] = links[0]
				ltext = get_text(bs)
			language["name"] = ltext

			if len(modifiers) > 0:
				language['modifiers'] = modifiers
			languages['languages'].append(language)
	if len(languages['languages']) == 0:
		del languages['languages']
	if len(parts) > 0:
		languages['communication_abilities'] = _handle_communication_abilities(parts)
	return languages

def universal_handle_sr(value):
	sr = {
		'type': 'stat_block_section',
		'subtype': 'sr',
	}
	parts = value.split(" ")
	sr['value'] = int(parts.pop(0))
	if len(parts) > 0:
		modifier_text = " ".join(parts)
		if modifier_text.startswith("(") and modifier_text.endswith(")"):
			modifier_text = modifier_text[1:-1]
		assert modifier_text.find(",") < 0, "SR modifiers apparently do need to be split: %s" % modifier_text
		assert modifier_text.find(";") < 0, "SR modifiers apparently do need to be split: %s" % modifier_text
		sr['modifiers'] = modifiers_from_string_list(
			[m.strip() for m in modifier_text.split(",")])
	return sr

def universal_handle_dr(value):
	# TODO: Check for parsables in modifiers
	def _break_out_damage_types(dr, text):
		FULLWIDTH_COMMA = "，"
		parts = text.split(FULLWIDTH_COMMA)
		newparts = []
		conj_and = False
		conj_or = False
		for part in parts:
			if " and " in part:
				conj_and = True
				newparts.extend(part.split(" and "))
			elif " or " in part:
				conj_or = True
				newparts.extend(part.split(" or "))
			else:
				newparts.append(part)
		assert not (conj_and and conj_or), "broken dr: %s" % text
		if conj_and:
			dr["conjunction"] = "and"
		elif conj_or:
			dr["conjunction"] = "or"
		dr["damage_types"] = newparts

			
	if value.endswith(";"):
		value = value [:-1]
	value = clear_tags(value, ["i"])
	values = split_maintain_parens(value, ",")
	drs = []
	for value in values:
		parts = value.split("/")
		assert len(parts) == 2, "Bad DR: %s" % value
		num = int(parts[0])
		dr = {
			"type": "stat_block_section",
			"subtype": "dr",
			"value": num,
			"text": value
		}
		text = parts[1].strip()
		if text.find("(") > -1:
			text, modtext = text.split("(")
			modtext = modtext.replace(")", "").strip()
			dr['modifiers'] = modifiers_from_string_list(
				[m.strip() for m in modtext.split(",")])
		_break_out_damage_types(dr, text.strip())
		drs.append(dr)
	return drs

def universal_handle_weaknesses(value):
	if value.endswith(";"):
		value = value [:-1]
	weaknesses = string_with_modifiers_from_string_list(
		split_maintain_parens(str(value), ","),
		"weakness")
	weaknesses = link_values(weaknesses)
	for weakness in weaknesses:
		if re.search("\d", weakness["name"]):
			assert False, "Bad Weakness: %s" % (weakness["name"])
	return weaknesses

def universal_handle_resistances(value):
	if value.endswith(";"):
		value = value [:-1]
	values = split_maintain_parens(str(value), ",")
	resistances = []
	for value in values:
		resistance = {
			"type": "stat_block_section",
			"subtype": "resistance"
		}
		if value.find("(") > -1:
			portions = value.split("(")
			assert len(portions) == 2, "Badly formatted resistance with modifier: %s" % value
			value = portions[0].strip()
			modtext = portions[1].strip()
			assert modtext.endswith(")"), "Badly formatted resistance with modifier: %s" % value
			modtext = modtext[:-1]
			resistance["modifiers"] = modifiers_from_string_list(
				[m.strip() for m in modtext.split(",")])
		parts = value.split(" ")
		resistance['value'] = int(parts.pop().strip())
		resistance['name'] = " ".join(parts).strip()
		resistances.append(resistance)
	return resistances

def universal_handle_immunities(value):
	if value.endswith(";"):
		value = value [:-1]
	value = value.replace(" and ", ", ")
	immunities = string_with_modifiers_from_string_list(
		split_maintain_parens(str(value), ","),
		"immunity")
	immunities = link_values(immunities)
	for immunity in immunities:
		if re.search("\d", immunity["name"]):
			assert False, "Bad Immunity: %s" % (immunity["name"])
	return immunities

def universal_handle_defensive_abilities(value):
	def _handle_da_number(da):
		m = re.search(r'^(.*) (\d*)$', da["name"])
		if m:
			groups = m.groups()
			da["name"] = groups[0]
			da["value"] = int(groups[1])

	if value.endswith(";"):
		value = value [:-1]
	das = string_with_modifiers_from_string_list(
		split_maintain_parens(str(value), ","),
		"defensive_ability")
	das = link_values(das)
	for da in das:
		_handle_da_number(da)
		universal_handle_modifier_breakout(da)
	return das

def universal_handle_gear(text):
	def _fix_split_quantities(parts):
		newparts = []
		lastpart = None
		for part in parts:
			join = False
			if lastpart:
				if lastpart[-1].isnumeric() and part[0].isnumeric():
					join = True
					newparts[-1] = "%s,%s" %(newparts[-1], part)
			if not join:
				newparts.append(part)
			lastpart = part
		return newparts
	def _handle_with(item):
		name = item["name"]
		if " with " in name:
			parts = split_maintain_parens(name, " with ")
			if len(parts) == 1:
				return item
			item["name"] = parts.pop(0)
			subtext = " with ".join(parts)
			item_with = universal_handle_gear(subtext)
			assert len(item_with) < 2, "malformed item: %s" % name
			item["with"] = item_with.pop(0)
		return item
	def _handle_quantity(item):
		if "modifiers" in item:
			newmods = []
			for modifier in item["modifiers"]:
				if modifier["name"].isnumeric():
					item["quantity"] = int(modifier["name"])
				else:
					newmods.append(modifier)
			item["modifiers"] = newmods
			if len(item["modifiers"]) == 0:
				del item["modifiers"]
		name = item["name"]
		m = re.search(r'^([0-9,]*) (.*)$', name)
		if m:
			groups = m.groups()
			quantity = groups[0]
			rest = groups[1]
			quantity = quantity.replace(",", "")
			if rest != "gp" and rest.startswith("gp "):
				pass
			else:
				item["name"] = rest
				item["quantity"] = int(quantity)
		return item
	def _clear_sup(text):
		bs = BeautifulSoup(text, 'html.parser')
		sups = bs.find_all('sup')
		for sup in sups:
			sup.replace_with('')
		return str(bs)

	text = clear_tags(text, ["i", "br"])
	text = text.replace("mwk", "masterwork")
	if text.endswith(";"):
		text = text[:-1]
	text = clear_tags(text, ["i", "br"])
	text = _clear_sup(text)
	parts = split_comma_and_semicolon(text)
	parts = _fix_split_quantities(parts)
	gear = []
	for part in parts:
		item = {
			"type": "stat_block_section",
			"subtype": "item",
			"name": part
		}
		item = _handle_with(item)
		item["name"], modifiers = extract_modifiers(item["name"])
		if modifiers:
			item["modifiers"] = modifiers		
		item = _handle_quantity(item)
		gear.append(item)
	return gear