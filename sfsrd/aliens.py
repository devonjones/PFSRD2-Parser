import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString
from pfsrd2.universal import parse_universal, print_struct, entity_pass
from pfsrd2.universal import is_trait, get_text, extract_link
from pfsrd2.universal import link_modifiers, modifiers_from_string_list
from pfsrd2.universal import split_maintain_parens
from pfsrd2.universal import source_pass, extract_source
from pfsrd2.universal import aon_pass, restructure_pass, html_pass
from pfsrd2.universal import remove_empty_sections_pass, get_links
from pfsrd2.universal import walk, test_key_is_value
from pfsrd2.files import makedirs, char_replace
from sfsrd.schema import validate_against_schema
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
	top_matter_pass(struct)
	defense_pass(struct)
	#offense_pass(struct)
	statistics_pass(struct)
	#source_pass(struct, find_stat_block)
	#sidebar_pass(struct)
	#index_pass(struct)
	#aon_pass(struct, basename)
	#restructure_pass(struct, 'stat_block', find_stat_block)
	#trait_pass(struct)
	#db_pass(struct)
	html_pass(struct)
	#log_html_pass(struct, basename)
	#remove_empty_sections_pass(struct)
	basename.split("_")
	if not options.skip_schema:
		validate_against_schema(struct, "alien.schema.json")
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
	struct['type'] = 'alien'
	struct['game-obj'] = "Aliens"
	struct['stat_block'] = {'name': name, 'type': 'stat_block'}
	struct['stat_block']['cr'] = cr
	family = _handle_family(details)
	if family:
		struct['stat_block']['alien_family'] = family
	struct['stat_block']['role'] = _handle_role(top)
	struct['sources'] = _handle_sources(top)
	assert len(top) == 3, str(top)
	struct['sections'].extend(top['sections'])
	return struct

def top_matter_pass(struct):
	def _handle_xp(bs):
		xp = bs.find_all('b').pop(0)
		text = get_text(xp)
		assert text.startswith("XP "), xp
		xp.extract()
		return int(text.replace("XP ", "").replace(",", ""))

	def _handle_initiative(bs):
		text = list(bs.children)[-1]
		text.extract()
		modifiers = []
		if text.find("(") > -1:
			parts = [p.strip() for p in text.split("(")]
			assert len(parts) == 2, text
			text = parts.pop(0)
			mods = parts.pop()
			assert mods[-1] == ")", mods
			mparts = [m.strip() for m in mods[0:-1].split(",")]
			modifiers = modifiers_from_string_list(mparts)
		text = text.strip().replace("+", "")
		title = list(bs.children)[-1]
		assert str(title) == "<b>Init</b>", title
		title.extract()
		init = {
			"name": "Initiative",
			"type": "stat_block_section",
			"subtype": "initiative",
			"value": int(text)
		}
		if len(modifiers) > 0:
			init['modifiers'] = modifiers
		return init

	def _handle_creature_basics(bs, sb):
		parts = list(filter(lambda e: len(e) > 0,
			str(bs).split("<br/>")))
		assert len(parts) in [1,2], bs
		type = parts.pop()
		type_parts = type.split("(")
		assert len(type_parts) in [1,2], str(type)
		basics = type_parts.pop(0).strip().split(" ")
		assert len(basics) in [3,4], basics
		sb['alignment'] = _handle_alignment(basics.pop(0))
		sb['size'] = _handle_size(basics.pop(0).capitalize())
		sb['creature_type'] = _handle_creature_type(
			" ".join([b.capitalize() for b in basics]),
			type_parts)
		assert len(type_parts) == 0, type_parts

		if len(parts) == 1:
			# Grafts
			grafts = parts.pop()
			grafts = modifiers_from_string_list(
				[g.strip().lower() for g in grafts.split(" ")],
				"graft")
			sb['grafts'] = link_modifiers(grafts)

	def _handle_alignment(abbrev):
		alignments = {
			'LG': "Lawful Good",
			'LN': "Lawful Neutral",
			'LE': "Lawful Evil",
			'NG': "Neutral Good",
			'N': "Neutral",
			'NE': "Neutral Evil",
			'CG': "Chaotic Good",
			'CN': "Chaotic Neutral",
			'CE': "Chaotic Evil"
		}
		return alignments[abbrev]

	def _handle_size(s):
		sizes = [
			"Fine", "Diminutive", "Tiny", "Small", "Medium", "Large", "Huge",
			"Gargantuan", "Colossal"]
		if s in sizes:
			return s
		assert s in sizes, s
	
	def _handle_creature_type(ct, subtype):
		types = [
			"Aberration", "Animal", "Construct", "Dragon", "Fey", "Humanoid",
			"Magical Beast", "Monstrous Humanoid", "Ooze", "Outsider", "Plant",
			"Undead", "Vermin"]
		if ct in types:
			creature_type = {
				"name": "creature_type",
				"type": "stat_block_section",
				"subtype": "creature_type",
				"creature_type": ct
			}
			if len(subtype) > 0:
				creature_type['creature_subtypes'] = _handle_creature_subtypes(subtype.pop())
			return creature_type
		assert ct in types, ct

	def _handle_creature_subtypes(subtype):
		subtypes = modifiers_from_string_list(
			[s.strip() for s in subtype.replace(")", "").split(",")],
			"creature_subtype")
		return link_modifiers(subtypes)

	def _handle_perception(title, value):
		assert str(title) == "<b>Perception</b>", title
		text = str(value).strip()
		if text.startswith('+'):
			text = text[1:].strip()
		modifiers = []
		if text.find("(") > -1:
			parts = text.split("(")
			text = parts.pop(0).strip()
			mtext = "(".join(parts).replace(")", "")
			modifiers = modifiers_from_string_list(
				[m.strip() for m in mtext.split(",")]
			)
			modifiers = link_modifiers(modifiers)
		perception = {
			"name": "Perception",
			"type": "stat_block_section",
			"subtype": "perception",
			"value": int(text)
		}
		if len(modifiers) > 0:
			perception['modifiers'] = modifiers
		return perception
	
	def _handle_aura(title, value):
		#TODO: Break out aura components, handle multiple auras
		assert str(title) == "<b>Aura</b>", title
		return value.strip()

	def _handle_senses(text):
		parts = [p.strip() for p in text.replace("<b>Senses</b>", "").split(",")]
		return modifiers_from_string_list(parts, "sense")

	text = struct.pop('text').split(";")
	assert len(text) in [2,3], text

	# Part 1
	bs = BeautifulSoup(text.pop(0), 'html.parser')
	assert len(list(bs.children)) in [6, 8], str(list(bs.children))
	sb = struct['stat_block']
	sb['xp'] = _handle_xp(bs)
	sb['initiative'] = _handle_initiative(bs)
	_handle_creature_basics(bs, sb)

	# Part 2
	bs = BeautifulSoup(text.pop().strip(), 'html.parser')
	[b.extract() for b in bs.find_all("br")]
	parts = list(bs.children)
	assert len(parts) in [2,4], bs
	sb['perception'] = _handle_perception(parts.pop(0), parts.pop(0))
	if len(parts) > 0:
		sb['aura'] = _handle_aura(parts.pop(0), parts.pop(0))

	# Part 3
	if (len(text) > 0):
		sb['senses'] = _handle_senses(text.pop(0))

	assert len(text) == 0, text

def defense_pass(struct):
	def _handle_hp(defense, text):
		parts = [t.strip() for t in text.split(";")]
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text()
			value = int(bsparts.pop().strip())
			if name == "HP":
				defense['hp'] = value
			elif name == "RP":
				defense['rp'] = value
			else:
				assert False, bs
	
	def _handle_ac(defense, text):
		parts = [t.strip() for t in text.split(";")]
		ac = {
			"name": "AC",
			"type": "stat_block_section",
			"subtype": "armor_class"
		}
		if len(parts) > 2:
			ac['modifiers'] = modifiers_from_string_list(parts[2:])
			parts = parts[0:2]
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text()
			value = int(bsparts.pop().strip())
			assert name in ["EAC", "KAC"], name
			ac[name.lower()] = value
		defense['ac'] = ac
	
	def _handle_saves(defense, text):
		parts = [t.strip() for t in text.split(";")]
		saves = {
			"name": "Saves",
			"type": "stat_block_section",
			"subtype": "saves"
		}
		if len(parts) > 3:
			saves['modifiers'] = modifiers_from_string_list(parts[3:])
			parts = parts[0:3]
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text()
			assert name in ["Fort", "Ref", "Will"], name
			save = {
				'name': name,
				'type': "stat_block_section",
				"subtype": "save"
			}
			valuetext = bsparts.pop().strip()
			if valuetext.find("(") > -1:
				vparts = [v.strip() for v in valuetext.split("(")]
				assert len(vparts) == 2, vparts
				valuetext = vparts.pop(0)
				modifiertext = vparts.pop(0).replace(")", "").strip()
				save['modifiers'] = modifiers_from_string_list(
					[m.strip() for m in modifiertext.split(",")])
			save['value'] = int(valuetext)
			
			saves[name.lower()] = save
		defense['saves'] = saves

	def _handle_defensive_abilities(defense, daparts):
		for dapart in daparts:
			bs = BeautifulSoup(dapart, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text()
			names = [
				"Defensive Abilities", "Immunities", "Resistances", "DR", "SR",
				"Weaknesses"]
			assert name in names, name
			value = bsparts.pop().strip()
			if name == "SR":
				defense['sr'] = value
			else:
				name = name.lower().replace(" ", "_")
				values = [v.strip() for v in value.split(",")]
				defense[name] = values

	defense_section = find_section(struct, "Defense")
	defense_text = defense_section['text']
	struct['sections'].remove(defense_section)
	parts = list(filter(lambda d: d != "",
		[d.strip() for d in defense_text.split("<br/>")]))
	defense = {
		"name": "Defense",
		"type": "stat_block_section",
		"subtype": "defense"
	}
	_handle_hp(defense, parts.pop(0))
	_handle_ac(defense, parts.pop(0))
	_handle_saves(defense, parts.pop(0))
	abilities = list(filter(
		lambda p: p != "",
		[part.strip() for part in ";".join(parts).split(";")]))
	if len(abilities) > 0:
		_handle_defensive_abilities(defense, abilities)
	struct['stat_block']['defense'] = defense

def offense_pass(struct):
	offense_section = find_section(struct, "Offense")
	offense_text = offense_section['text']
	struct['sections'].remove(offense_section)
	parts = list(filter(lambda d: d != "",
		[d.strip() for d in offense_text.split("<br/>")]))
	#pprint(parts)

def statistics_pass(struct):
	def _handle_stats(statistics, text):
		parts = [t.strip() for t in text.split(";")]
		assert len(parts) == 6, parts
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text().lower()
			assert name in ["str", "dex", "con", "int", "wis", "cha"], name
			value = bsparts.pop().strip()
			if value == "-":
				statistics[name] = None
			else:
				statistics[name] = int()
	
	def _handle_feats(statistics, bs):
		assert str(bs).find(";") == -1, bs
		statistics['feats'] = [b.strip() for b in str(bs).split(",")]
	
	def _handle_skills(statistics, bs):
		parts = str(bs).split(";")
		assert len(parts) in [1,2], bs
		skills = {
			"type": "stat_block_section",
			"subtype": "skills",
			"name": "Skills",
			"skills": []
		}
		if len(parts) > 1:
			modtext = parts.pop()
			skills['modifiers'] = modifiers_from_string_list(
				[m.strip() for m in modtext.split(",")])
		parts = split_maintain_parens(parts.pop(), ",")
		for part in parts:
			skill = {
				"type": "stat_block_section",
				"subtype": "skill",
			}
			m = re.search(r'(.*) +([-+]?[0-9]+) +\((.*)\)', part)
			if m:
				parts = m.groups()
				assert len(parts) == 3, parts
				skill['name'] = parts[0]
				skill['value'] = int(parts[1])
				modtext = parts[2]
				skill['modifiers'] = modifiers_from_string_list(
					[m.strip() for m in modtext.split(",")])
			else:
				m = re.search(r'(.*) +([-+]?[0-9]+)', part)
				if m:
					parts = m.groups()
					assert len(parts) == 2, parts
					skill['name'] = parts[0]
					skill['value'] = int(parts[1])
				else:
					assert False, "%s: %s" % (part, str(bs))
			skills['skills'].append(skill)
		statistics['skills'] = skills
	
	def _handle_languages(statistics, bs):
		parts = str(bs).split(";")
		languages = {
			"type": "stat_block_section",
			"subtype": "languages",
			"name": "Languages",
			"languages": []
		}
		langs = parts.pop(0)
		if len(parts) > 0:
			modtext = ", ".join(parts)
			languages['communication_abilities'] = modifiers_from_string_list(
				[m.strip() for m in modtext.split(",")])
		if langs.find("(") > -1:
			langparts = langs.split("(")
			modtext = langparts.pop().replace(")", "")
			langs = "(".join(langparts)
			languages['modifiers'] = modifiers_from_string_list(
				[m.strip() for m in modtext.split(",")])

		parts = split_maintain_parens(langs, ",")
		for part in parts:
			assert part.find("(") == -1, part
			language = {
				"type": "stat_block_section",
				"subtype": "language",
				"name": part
			}
			languages['languages'].append(language)
		statistics['languages'] = languages

	def _handle_other_abilities(statistics, bs):
		parts = split_maintain_parens(str(bs), ",")
		abilities = modifiers_from_string_list(parts, "other_ability")
		statistics['other_abilities'] = abilities
	
	def _handle_gear(statistics, bs):
		assert str(bs).find(";") == -1, bs
		parts = split_maintain_parens(str(bs), ",")
		gear = modifiers_from_string_list(parts, "gear")
		statistics['gear'] = gear
	
	def _handle_augmentations(statistics, bs):
		parts = split_maintain_parens(str(bs), ",")
		augmentations = modifiers_from_string_list(parts, "augmentation")
		statistics['augmentations'] = augmentations

	stats_section = find_section(struct, "Statistics")
	stats_text = stats_section['text']
	struct['sections'].remove(stats_section)
	parts = list(filter(lambda d: d != "",
		[d.strip() for d in stats_text.split("<br/>")]))
	statistics = {
		"name": "Statistics",
		"type": "stat_block_section",
		"subtype": "statistics"
	}
	_handle_stats(statistics, parts.pop(0))
	for part in parts:
		bs = BeautifulSoup(part, 'html.parser')
		namebs = list(bs.children).pop(0)
		name = namebs.get_text()
		namebs.extract()
		dispatch = {
			"Feats": _handle_feats,
			"Skills": _handle_skills,
			"Languages": _handle_languages,
			"Other Abilities": _handle_other_abilities,
			"Gear": _handle_gear,
			"Augmentations": _handle_augmentations
		}
		dispatch[name](statistics, bs)

	struct['stat_block']['statistics'] = statistics

def find_section(struct, name):
	for s in struct['sections']:
		if s['name'] == name:
			return s
	for s in struct['sections']:
		return creature_stat_block_pass(s)

