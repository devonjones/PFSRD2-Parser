import os
import json
import re
from pprint import pprint
from universal.universal import modifiers_from_string_list, extract_modifiers
from universal.universal import link_values, get_links, get_text
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
		log_element("%s.log" % "special_senses")("%s" % (part))
		sense = {
			"type": "stat_block_section",
			"subtype": "special_sense",
		}
		part = _get_link(part)
		part = _handle_special_sense_range(part, sense)
		if part.find("(") > -1:
			assert part.endswith(")"), part
			parts = [p.strip() for p in part.split("(")]
			assert len(parts) == 2, part
			part = parts.pop(0)
			mods = parts.pop()
			mparts = [m.strip() for m in mods[0:-1].split(",")]
			modifiers = modifiers_from_string_list(mparts)
			sense["modifiers"] = link_values(modifiers, "name")
		
		sense["value"] = part
		special_senses.append(sense)
	special_senses = link_values(special_senses, singleton=True)
	return special_senses
