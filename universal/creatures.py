import os
import json
import re
from pprint import pprint
from universal.universal import modifiers_from_string_list, extract_modifiers
from universal.universal import link_values, get_links, get_text
from universal.universal import split_maintain_parens
from universal.universal import string_values_from_string_list
from universal.files import char_replace
from universal.utils import log_element
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

def universal_handle_save_dc(text):
	# Fortitude DC 22
	# DC 22
	# DC 22 Fortitude
	# DC 22 half

	assert "DC" in text, "Saves must have DCs: %s" % text
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
			save_dc['result'] = part
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
		if len(subtype) > 0:
			creature_type['creature_subtypes'] = _handle_creature_subtypes(subtype)
		return creature_type
	assert ct in types, ct
