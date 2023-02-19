import os
import json
import sys
import re
import html2markdown
from pprint import pprint
from bs4 import BeautifulSoup, NavigableString, Tag
from universal.universal import parse_universal, entity_pass
from universal.universal import get_text, break_out_subtitles
from universal.universal import link_modifiers, modifiers_from_string_list
from universal.universal import extract_source, get_links, extract_link
from universal.universal import html_pass
from universal.universal import remove_empty_sections_pass
from universal.universal import string_with_modifiers
from universal.universal import string_with_modifiers_from_string_list
from universal.universal import string_values_from_string_list
from universal.universal import number_with_modifiers, parse_number
from universal.files import makedirs, char_replace
from universal.utils import split_maintain_parens, split_comma_and_semicolon
from universal.utils import filter_end, clear_tags
from universal.utils import log_element, find_list
from universal.creatures import write_creature
from universal.creatures import universal_handle_alignment
from universal.creatures import universal_handle_aura
from universal.creatures import universal_handle_creature_type
from universal.creatures import universal_handle_defensive_abilities
from universal.creatures import universal_handle_dr
from universal.creatures import universal_handle_immunities
from universal.creatures import universal_handle_languages
from universal.creatures import universal_handle_range
from universal.creatures import universal_handle_resistances
from universal.creatures import universal_handle_save_dc
from universal.creatures import universal_handle_size
from universal.creatures import universal_handle_sr
from universal.creatures import universal_handle_weaknesses
from pfsrd.schema import validate_against_schema

def parse_creature(filename, options):
	basename = os.path.basename(filename)
	if not options.stdout:
		sys.stderr.write("%s\n" % basename)
	details = parse_universal(filename, subtitle_text=False, max_title=3,
		cssclass="ctl00_MainContent_DataListFeats_ctl00_Label1")
	details = entity_pass(details)
	struct = restructure_creature_pass(details, options.subtype)
	top_matter_pass(struct)
	defense_pass(struct)
	offense_pass(struct)
	statistics_pass(struct)
	#ecology_pass(struct)
	#special_ability_pass(struct)
	#section_pass(struct)
	html_pass(struct)
	#log_html_pass(struct, basename)
	remove_empty_sections_pass(struct)
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

def handle_default_list_of_strings(field):
	def _handle_default_list_impl(_, elem, text):
		text = filter_end(text, ["<br/>", ","])
		parts = split_comma_and_semicolon(text)
		elem[field.lower().strip()] = parts
	return _handle_default_list_impl

def handle_default_list_of_objects(name, subtype, field):
	# TODO pull out dice
	def _handle_default_list_impl(_, elem, text):
		text = filter_end(text, ["<br/>", ","])
		retlist = []
		parts = split_comma_and_semicolon(text)
		for text in parts:
			element = {
				'type': 'stat_block_section',
				'subtype': subtype
			}
			if text.find("(") > -1:
				parts = text.split("(")
				text = parts.pop(0).strip()
				modtext = ",".join([p.replace(")", "").strip() for p in parts])
				modparts = split_comma_and_semicolon(modtext, parenleft="[", parenright="]")
				element['modifiers'] = modifiers_from_string_list(modparts)
			element['name'] = text
			retlist.append(element)
		elem[field] = retlist
	return _handle_default_list_impl

def handle_default(field):
	def _handle_default_impl(_, elem, text):
		text = filter_end(text, ["<br/>", ","])
		elem[field.lower().strip()] = text.strip()
	return _handle_default_impl

def handle_noop(name):
	def _handle_noop_impl(_, elem, text):
		pprint("%s: %s" %(name, text))
		#assert False
	return _handle_noop_impl

def restructure_creature_pass(details, subtype):
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
			if detail['name'].endswith("Category"):
				name = detail['name']
				parts = name.split('"')
				assert len(parts) == 3, parts
				name = parts[1]
				details.remove(detail)
				return name

	struct, path = _find_stat_block(details)
	short_desc = path.pop()
	assert path == [], path
	details.remove(short_desc)
	if 'text' in short_desc:
		struct['html'] = short_desc['text']
	struct['sections'].extend(short_desc['sections'])
	assert len(path) == 0, path
	parts = [p.strip() for p in struct['name'].split('CR')]
	name = parts.pop(0)
	cr = parts.pop(0)
	assert len(parts) == 0, parts
	struct['name'] = name
	struct['type'] = 'monster'
	struct['game-obj'] = "Monsters"
	struct['stat_block'] = {'name': name, 'type': 'stat_block'}
	struct['stat_block']['cr'] = cr
	family = _handle_family(details)
	if family:
		struct['stat_block']['family'] = family
	return struct

def top_matter_pass(struct):
	def _handle_sources(struct, _, text):
		bs = BeautifulSoup(text, 'html.parser')
		links = bs.findAll('a')
		retarr = []
		for link in links:
			retarr.append(extract_source(link))
			link.extract()
		assert str(bs).replace(", ", "") == "", str(bs)
		struct['sources'] = retarr

	def _handle_xp(_, sb, text):
		sb['xp'] = int(text.replace(",", "").strip())

	def _handle_initiative(_, sb, text):
		if text.endswith(";"):
			text = text[:-1]
		text = text.replace("–", "-")
		modifiers = []
		if text.find("(") > -1:
			parts = [p.strip() for p in text.split("(")]
			assert len(parts) == 2, text
			text = parts.pop(0)
			mods = parts.pop()
			assert mods[-1] == ")", mods
			mparts = [m.strip() for m in mods[0:-1].split(",")]
			modifiers = modifiers_from_string_list(mparts)
		
		init = {
			"type": "stat_block_section",
			"subtype": "initiative",
			"value": int(text)
		}
		if len(modifiers) > 0:
			init['modifiers'] = modifiers
		sb['initiative'] = init

	def _handle_senses(_, sb, text):
		text = text.replace("–", "-")
		parts = split_comma_and_semicolon(text)
		perclist = []
		newparts = []
		for part in parts:
			name = part.split(" ").pop(0)
			if name in ["Perception", "Listen", "Spot"]:
				perclist.append(part)
			else:
				newparts.append(part)
		if len(perclist) > 0:
			sb['perception'] = _handle_perception(perclist)
		if len(parts) > 0:
			sb['senses'] = modifiers_from_string_list(newparts, "sense")

	def _handle_perception(percskills):
		retarr = []
		for perkskill in percskills:
			parts = perkskill.split(" ")
			skillname = parts.pop(0).strip()
			perkskill = " ".join(parts)
			modifiers = []
			if perkskill.find("(") > -1:
				parts = perkskill.split("(")
				perkskill = parts.pop(0).strip()
				mtext = "(".join(parts).replace(")", "")
				modifiers = modifiers_from_string_list(
					[m.strip() for m in mtext.split(",")]
				)
				modifiers = link_modifiers(modifiers)
			perception = {
				"type": "stat_block_section",
				"subtype": skillname.lower(),
				"value": int(perkskill)
			}
			if len(modifiers) > 0:
				perception['modifiers'] = modifiers
			retarr.append(perception)
		return retarr

	def _handle_aura(_, sb, text):
		sb['auras'] = universal_handle_aura(text)

	def _handle_creature_basics(text, sb):
		subtypes = []
		if text.endswith(")"):
			type_parts = text.split("(")
			assert len(type_parts) == 2, text
			text = type_parts.pop(0)
			subtypes = [s.strip() for s in type_parts.pop().replace(")", "").split(",")]
		basics = text.strip().split(" ")
		creature_type = _handle_creature_type(basics, subtypes)
		sb['creature_type'] = creature_type
		creature_type['size'] = universal_handle_size(basics.pop().capitalize())
		_handle_alignment(creature_type, basics)
		if 'family' in sb:
			creature_type['family'] = sb['family']
			del sb['family']
		if 'cr' in sb:
			creature_type['cr'] = sb['cr']
			del sb['cr']
		if 'xp' in sb:
			creature_type['xp'] = sb['xp']
			del sb['xp']
		if 'grafts' in sb:
			creature_type['grafts'] = sb['grafts']
			del sb['grafts']

	def _handle_alignment(creature_type, basics):
		abbrev = basics[0]
		alignment = universal_handle_alignment(abbrev)
		if alignment:
			creature_type['alignment'] = alignment
		creature_type['alignment_text'] = " ".join(basics)

	def _handle_creature_type(basics, subtype):
		testtype = basics.pop().capitalize()
		if testtype == "Beast":
			testtype = basics.pop().capitalize() + " " + testtype
		elif testtype == "Humanoid" and basics[-1] == "monstrous":
			testtype = basics.pop().capitalize() + " " + testtype
		subtype = ", ".join(subtype)
		return universal_handle_creature_type(testtype, subtype)

	def _handle_grafts(text):
		if text.find("(<i>Pathfinder") > -1:
			p = text.split("(<i>Pathfinder")
			assert len(p) == 2
			text = p.pop(0).strip()

		parts = split_maintain_parens(text, " ")
		newarr = []
		for part in parts:
			try:
				_ = int(part)
				newarr[-1] = newarr[-1] + " " + part
			except:
				if part.startswith("("):
					newarr[-1] = newarr[-1] + " " + part
				else:
					newarr.append(part)

		grafts = string_values_from_string_list(newarr,	"graft", False)
		sb['grafts'] = grafts

	sb = struct['stat_block']
	parts = struct.pop('text').split("<br/>")
	freetext = []
	for part in parts:
		bs = BeautifulSoup(part, 'html.parser')
		output = break_out_subtitles(bs, 'b')
		while len(output) > 0:
			title, text = output.pop(0)
			if title:
				dispatch = {
					"Source": _handle_sources,
					"XP": _handle_xp,
					"Init": _handle_initiative,
					"Senses": _handle_senses,
					"Aura": _handle_aura
				}
				dispatch[title](struct, sb, text)
			else:
				freetext.append(text)

	assert len(freetext) in [1,2], freetext
	if len(freetext) == 2:
		_handle_grafts(freetext.pop(0))
	_handle_creature_basics(freetext.pop(0), sb)

def defense_pass(struct):
	def _handle_ac(_, defense, text):
		parts = text.replace("–", "-").split("(")
		text = parts.pop(0).strip()
		modtext = ",".join([p.replace(")", "").strip() for p in parts])

		parts = split_comma_and_semicolon(text)
		ac = {
			"name": "AC",
			"type": "stat_block_section",
			"subtype": "armor_class"
		}
		while len(parts) > 0:
			acparts = parts.pop(0).split(" ")
			assert len(acparts) in [1,2], parts
			if len(acparts) == 1:
				ac['ac'] = int(acparts[0])
			else:
				ac[acparts[0].lower()] = int(acparts[1])
		ac['modifiers'] = modifiers_from_string_list(
			[m.strip() for m in modtext.split(",")])
		defense['ac'] = ac

	def _handle_hp(_, defense, text):
		hp = {
			"name": "HP",
			"type": "stat_block_section",
			"subtype": "hitpoints"
		}
		parts = split_comma_and_semicolon(text)
		base = parts.pop(0)
		hptext, hdtext = base.split("(")
		if hptext.strip().endswith(" each"):
			hptext = hptext.replace(" each", "")
		hp['value'] = int(hptext.strip())
		hp['hit_dice'] = hdtext.replace(")", "").strip()
		hp['healing_abilities'] = modifiers_from_string_list(parts, "healing_ability")	
	
	def _handle_save(name):
		def _handle_save_impl(_, defense, text):
			text = text.replace("–", "-")
			saves = defense.setdefault("saves", {
				"type": "stat_block_section",
				"subtype": "saves"
			})
			if text.endswith(",") or text.endswith("."):
				text = text[:-1]
			if text.find("(") > -1:
				tmplist = text.split("(")
				text = ", ".join([t.replace(")", "").strip() for t in tmplist])
			parts = split_comma_and_semicolon(text)
			value = parts.pop(0)
			save = {
				'name': name,
				'type': "stat_block_section",
				"subtype": "save",
				"value": int(value)
			}
			if len(parts) > 0:
				save['modifiers'] = modifiers_from_string_list(parts)

			saves[name.lower()] = save
		return _handle_save_impl

	def _handle_dr(_, defense, text):
		dr = universal_handle_dr(text)
		defense['dr'] = dr

	def _handle_sr(_, defense, text):
		sr = universal_handle_sr(text)
		defense['sr'] = sr

	def _handle_immunities(_, defense, text):
		immunities = universal_handle_immunities(text)
		defense['immunities'] = immunities
	
	def _handle_resistances(_, defense, text):
		resistances = universal_handle_resistances(text)
		defense['resistances'] = resistances

	def _handle_weaknesses(_, defense, text):
		weaknesses = universal_handle_weaknesses(text)
		defense['weaknesses'] = weaknesses

	def _handle_defensive_abilities(_, defense, text):
		bs = BeautifulSoup(text, 'html.parser')
		sups = bs.find_all('sup')
		for sup in sups:
			sup.replace_with('')
		text = str(bs)

		das = universal_handle_defensive_abilities(text)
		defense['defensive_abilities'] = das
	
	sb = struct['stat_block']
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
	for part in parts:
		bs = BeautifulSoup(part, 'html.parser')
		output = break_out_subtitles(bs, 'b')
		while len(output) > 0:
			title, text = output.pop(0)
			if title:
				dispatch = {
					"AC": _handle_ac,
					"hp": _handle_hp,
					"Fort": _handle_save("Fort"),
					"Ref": _handle_save("Ref"),
					"Will": _handle_save("Will"),
					"DR": _handle_dr,
					"SR": _handle_sr,
					"Immune": _handle_immunities,
					"Weaknesses": _handle_weaknesses,
					"Resist": _handle_resistances,
					"Defensive Abilities": _handle_defensive_abilities,
				}
				dispatch[title](struct, defense, text)
			else:
				assert False, output
	sb['defense'] = defense

def offense_pass(struct):
	def _handle_spell(offense, title, text):
		def _handle_spell_deets(deets):
			if deets == '':
				return
			parts = split_comma_and_semicolon(deets)
			cl = parts.pop(0)
			cl = cl.replace("caster level", "CL")
			assert cl.upper().startswith("CL "), cl
			clparts = cl.split(" ")
			assert len(clparts) == 2, cl
			try:
				spells['caster_level'] = int(clparts[1])
			except:
				spells['caster_level'] = int(clparts[1][:-2])
			for part in parts:
				if part.find("+") > -1:
					elements = part.split(" ")
					assert len(elements) in [2,3], part
					v = elements.pop()
					n = " ".join(elements)
					assert n in [
						"melee", "ranged", "concentration", "touch", "ranged touch"]
					n = n.replace(" ", "_")
					spells[n] = int(v)
				else:
					spells.setdefault('notes', []).append(part)

		def _handle_spell_list(text):
			def _handle_spell_list_deets(deets):
				deetparts = deets.split("(")
				if deetparts[0].startswith("At will"):
					deetparts = [deets]
				if len(deetparts) == 1:
					spell_list['count_text'] = deetparts[0].strip()
				elif len(deetparts) == 2:
					spell_level_text = deetparts[0].strip()
					spell_list["level_text"] = spell_level_text
					if len(spell_level_text) == 1:
						spell_list["level"] = int(spell_level_text)
					elif len(spell_level_text) == 3:
						spell_list["level"] = int(spell_level_text[:-2])
					else:
						assert False, deets
					spell_list['count_text'] = deetparts[1].replace(")", "").strip()
				else:
					assert False, deets
				count_text = spell_list['count_text']
				if count_text.find("PE") > -1:
					pe, _ = count_text.split(" ")
					spell_list['psychic_energy'] = int(pe)
				elif count_text.find("/") > -1 and count_text.find("(") == -1:
					c, f = count_text.split("/")
					if c.find(" ") > -1:
						c, time = c.split(" ")
						f = "%s/%s" % (time, f)
					spell_list['count'] = int(c)
					spell_list['frequency'] = f
				else:
					spell_list['frequency'] = count_text

			def _handle_spell(spell_list, text):
				spell = {
					"type": "stat_block_section",
					"subtype": "spell"
				}
				text = clear_tags(text, ['a'])
				bs = BeautifulSoup(text, 'html.parser')
				bslist = list(bs.children)
				first = str(bslist[0]).strip()
				metamagic = [
					"empowered", "extended", "heightened", "maximized", "merciful",
					"reach", "quickened", "scarring", "widened", "quickened empowered"]
				prefix = ""
				if(first.endswith(":")):
					note = str(bslist.pop(0)).strip()[:-1]
					spell_list.setdefault('notes', []).append(note)
				elif first == "mass":
					prefix = first + " "
					bslist.pop(0)
				elif first in metamagic:
					if "metamagic" in spell:
						spell['metamagic'] = "%s, %s" % (spell['metamagic'], first)
					else:
						spell['metamagic'] = first
					bslist.pop(0)
				spell['name'] = prefix + clear_tags(str(bslist.pop(0)), ['i']).strip()
				if find_list(spell['name'], metamagic):
					name = spell['name']
					mm = find_list(name, metamagic)
					assert not 'metamagic' in spell, text
					name = name.replace(mm, "").replace("  ", " ").strip()
					spell['name'] = name
					spell['metamagic'] = mm
				if len(bslist) > 0:
					exttext = ''.join([str(b) for b in bslist]).strip()
					if spell['name'] == "summon":
						exttext = get_text(BeautifulSoup(exttext, 'html.parser'))
					if exttext.find("<sup>") > -1:
						bs = BeautifulSoup(exttext, 'html.parser')
						notation = bs.sup.extract().get_text()
						assert spell.get('notation') == None
						spell['notation'] = notation
						exttext = str(bs).strip()
					if exttext.find("*") > -1:
						assert spell.get('notation') == None, text
						spell['notation'] = "*"
						exttext = exttext.replace("*", "").strip()
					if len(exttext.strip()) > 0:
						if exttext.find(");") > -1:
							exttext, note = exttext.split(");")
							exttext = exttext + ")"
							note = note.strip()
							spell_list.setdefault('notes', []).append(note)
						m = re.match(r"^([IVX]*) (.*)", exttext)
						if m:
							spell_version, exttext = m.groups()
							spell['name'] = "%s %sgfvvvvvvvvvvvvvvvvvvvvv99999999999999999899999999" % (spell['name'], spell_version)
						assert exttext.startswith("(") and exttext.endswith(")"), exttext
						exttext = exttext[1:-1]
						extparts = split_comma_and_semicolon(exttext, ";")
						modlist = []
						for extpart in extparts:
							if extpart.endswith("level"):
								level, _ = extpart.split(" ")
								spell['spell_level'] = int(level[:-2])
							elif extpart.startswith("range "):
								_, range, _ = extpart.split(" ")
								spell['spell_range'] = int(range)
							elif extpart.startswith("DC"):
								_, dc = extpart.split(" ")
								spell['spell_dc'] = int(dc)
							elif extpart.endswith("PE"):
								pe, _ = extpart.split(" ")
								spell['psychic_energy'] = int(pe)
							else:
								modlist.append(extpart)
						if len(modlist) > 0:
							spell['modifiers'] = modifiers_from_string_list(modlist)
				return spell

			spell_list = {
				"type": "stat_block_section",
				"subtype": "spell_list",
				"spells": []
			}

			text = text.replace("–", "—")
			text = text.replace("-", "—")
			
			tmplist = split_maintain_parens(text, "—")
			deets = tmplist.pop(0)
			listtext = "—".join(tmplist)
			_handle_spell_list_deets(deets)
			spelltexts = split_maintain_parens(listtext, ",")
			for spelltext in spelltexts:
				spell_list['spells'].append(_handle_spell(spell_list, spelltext))
			spells['spell_list'].append(spell_list)

		offense.setdefault("magic", {
			"name": "Magic",
			"type": "stat_block_section",
			"subtype": "magic"
		})
		spells = {
			"name": title,
			"type": "stat_block_section",
			"subtype": "spells",
			"spell_list": []
		}
		parts = list(filter(lambda d: d != "",
			[d.strip() for d in text.split("<br/>")]))
		deets = parts.pop(0)
		assert deets.startswith("(") and deets.endswith(")"), deets
		_handle_spell_deets(deets[1:-1])
		for part in parts:
			_handle_spell_list(part)
		offense["magic"].setdefault('spells', []).append(spells)

	def _handle_speeds(_, offense, text):
		def _handle_speed(text):
			speed = {
				"type": "stat_block_section",
				"subtype": "speed"
			}
			if text.find("(") > -1:
				move, modtext = text.split("(")
				text = move.strip()
				modtext = modtext.replace(")", "").strip()
				parts = split_comma_and_semicolon(modtext)
				if parts[0] in ['Ex', 'Sp', 'Su']:
					abbrev = parts.pop(0)
					ability_types = {
						"Ex": "Extraordinary",
						"Sp": "Spell-Like",
						"Su": "Supernatural"
					}
					speed['ability_type'] = ability_types[abbrev]
					speed['ability_type_abbrev'] = abbrev
					speed['maneuverability'] = parts.pop(0)
				if len(parts) > 0:
					speed['modifiers'] = modifiers_from_string_list(parts)

			text = filter_end(text, ["<br/>", ";"])
			speed['name'] = text
			if text.find(" ft.") > -1:
				segments = text.replace(" ft.", "").split(" ")
				distance = int(segments.pop())
				if len(segments) == 0:
					speed['movement_type'] = 'walk'
					speed['value'] = int(distance)
				else:
					speed['movement_type'] = " ".join(segments)
					speed['value'] = int(distance)
			return speed

		speeds = {
			"name": "Speed",
			"type": "stat_block_section",
			"subtype": "speeds",
			"movement": []
		}
		parts = split_comma_and_semicolon(text)
		for part in parts:
			speeds['movement'].append(_handle_speed(part))
		offense['speed'] = speeds

	def _handle_attack(attack_type):
		def _handle_attack_impl(_, offense, text):
			def _handle_attack_start(start):
				if start in ["swarm attack", "troop attack", "swarm", "troop"]:
					attack['name'] = start
					return
				parts = start.split(" ")
				if "attack" in parts:
					parts.remove("attack")
				if "touch" == parts[-1]:
					attack['touch'] = True
					parts.pop()
				if "incorporeal" == parts[-1]:
					attack['incorporeal'] = True
					parts.pop()
				if "melee" in parts:
					parts.remove("melee")
				if "ranged" in parts:
					parts.remove("ranged")
				if "swarm" in parts:
					attack['swarm'] = True
					parts.remove("swarm")
				if len(parts) > 0:
					plus = parts.pop().replace("–", "-")
					try:
						attack['count'] = int(parts[0])
						parts.pop(0)
					except:
						# No count at front
						pass
					bs = BeautifulSoup(" ".join(parts), 'html.parser')
					attack['name'] = get_text(bs)
					attack['bonus'] = [int(p) for p in plus.split("/")]

			def _handle_attack_damage(damagetext):
				def _handle_damage_type(damage_type):
					if len(damage_type) == 0:
						return
					parts = filter(
						lambda p: p != "",
						[p.strip() for p in damage_type.split(" ")])
					values = []
					for part in parts:
						part = part.strip()
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
							"random": "Random type"
						}
						comma = False
						if part.find(",") > -1:
							comma = True
							part = part.replace(",", "").strip()
						if part in damage_types:
							values.append(damage_types[part])
						elif part in ["&", "or"]:
							values.append(part)
						else:
							_handle_effects(damage_type)
							#assert False, damage_type
						if comma:
							values[-1] = values[-1] + ","
					attack_damage['damage_type'] = " ".join(values)
					attack_damage['damage_type_text'] = damage_type

				def _handle_effects(effecttext):
					if effecttext.find("critical") > -1:
						attack_damage["critical"] = True
						effecttext = effecttext.replace("critical", "").replace("  ", " ").strip()
					attack_damage["effect"] = effecttext

				damage = []
				damagetext = damagetext.replace(" plus ", "; ")
				damagetext = damagetext.replace(" and ", "; ")
				damageparts = split_comma_and_semicolon(damagetext, parenleft="[", parenright="]")
				for damagepart in damageparts:
					attack_damage = {
						"type": "stat_block_section",
						"subtype": "attack_damage",
					}
					if damagepart.find('[') > -1:
						damagepart, modtext = damagepart.split("[")
						damagepart = damagepart.strip()

						modtext = modtext.replace("]", "").strip()
						modparts = split_comma_and_semicolon(modtext)
						for modpart in modparts:
							if modpart.find("DC") > -1:
								attack_damage['saving_throw'] = universal_handle_save_dc(modpart)
							elif modpart.endswith("ft."):
								attack_damage['range'] = universal_handle_range(modpart)
							else:
								damagepart = damagepart + ";" + modpart

					if damagepart.find("nonlethal") > -1:
						attack_damage['nonlethal'] = True
						damagepart = damagepart.replace("nonlethal", "").strip()
						damagepart = damagepart.replace("  ", " ").strip()
					if re.match("^\d+d\d+", damagepart):
						ps = damagepart.split(" ")
						attack_damage['formula'] = ps.pop(0)
						damage_type = " ".join(ps)
						_handle_damage_type(damage_type)
					elif re.match(".* \d*d?\d+$", damagepart):
						ps = damagepart.split(" ")
						attack_damage['formula'] = ps.pop()
						damagepart = " ".join(ps)
						_handle_effects(damagepart)
					else:
						_handle_effects(damagepart)
					if "formula" in attack_damage and attack_damage['formula'].find("/") > -1:
						tmplist = attack_damage['formula'].split("/")
						ad = tmplist.pop(0)
						ac = "/".join(tmplist)
						attack_damage['formula'] = ad
						assert not 'critical_range' in attack, attacktext
						attack['critical_range'] = ac
					damage.append(attack_damage)
				attack['damage'] = damage

			text = clear_tags(text, ["i"]).replace("<br/>", "")
			textparts = split_maintain_parens(text, ",")
			text = " or ".join(textparts)
			textparts = split_maintain_parens(text, " and ")
			text = " or ".join(textparts)
			melee = []
			attacks = split_maintain_parens(text, " or ")
			attacks = [a.replace("  ", " ") for a in attacks]
			for attacktext in attacks:
				attack = {
					"type": "stat_block_section",
					"subtype": "attack",
					"attack_type": attack_type,
				}
				attackparts = attacktext.split("(")
				start = attackparts.pop(0).strip()
				attackdata = "; ".join(attackparts).replace(")", "").strip()
				_handle_attack_start(start)
				if len(attackparts) > 0:
					_handle_attack_damage(attackdata)
				melee.append(attack)
			offense[attack_type] = melee
		return _handle_attack_impl

	def _handle_reach(_, offense, text):
		reach = {
			"type": "stat_block_section",
			"subtype": "reach"
		}
		text = filter_end(text, ["<br/>", ","])
		if text.find("(") > -1:
			text, modtext = text.split("(")
			text = text.strip()
			modtext = modtext.replace(")", "").strip()
			parts = [p.strip() for p in modtext.split(",")]
			reach['modifiers'] = modifiers_from_string_list(parts)
		reach['value'] = text
		offense['reach'] = reach

	def _handle_notation(name):
		def _handle_notation_impl(_, offense, text):
			magic = offense['magic']
			notations = magic.setdefault("notations", [])
			text = text.replace("<br/>", " ").strip()
			text = filter_end(text, [";"]).strip()
			notation = {
				'name': name,
				'type': 'stat_block_section',
				'subtype': 'notation',
				'value': text.strip()
			}
			notations.append(notation)
		return _handle_notation_impl

	def _handle_class_selection(name):
		def _handle_notation_impl(_, offense, text):
			magic = offense['magic']
			notations = magic.setdefault("class_selections", [])
			text = text.replace("<br/>", " ").strip()
			values = split_comma_and_semicolon(text)
			notation = {
				'name': name,
				'type': 'stat_block_section',
				'subtype': 'class_selection',
				'values': values
			}
			notations.append(notation)
		return _handle_notation_impl

	sb = struct['stat_block']
	offense_section = find_section(struct, "Offense")
	offense_text = offense_section['text']
	struct['sections'].remove(offense_section)
	offense = {
		"name": "Offense",
		"type": "stat_block_section",
		"subtype": "offense"
	}
	bs = BeautifulSoup(offense_text, 'html.parser')
	output = break_out_subtitles(bs, 'b')
	while len(output) > 0:
		title, text = output.pop(0)
		if title:
			if find_list(title, ["Spell", "Magic", "Extract", "Talent"]):
				_handle_spell(offense, title, text)
			else:
				dispatch = {
					"Speed": _handle_speeds,
					"Space": handle_default("space"),
					"Reach": _handle_reach,
					"Melee": _handle_attack("melee"),
					"Ranged": _handle_attack("ranged"),
					"Special Attacks": handle_default_list_of_objects(
						"Special Attack", "special_attack", "special_attacks"),
					"D": _handle_notation("D"),
					"S": _handle_notation("S"),
					"M": _handle_notation("M"),
					"*": _handle_notation("*"),
					"Domains": _handle_class_selection("Domains"),
					"Mystery": _handle_class_selection("Mystery"),
					"Bloodline": _handle_class_selection("Bloodline"),
					"Patron": _handle_class_selection("Patron"),
					"Domain": _handle_class_selection("Domains"),
					"Spirit": _handle_class_selection("Spirit"),
					"Implements": _handle_class_selection("Implements"),
					"Opposition Schools": _handle_class_selection("Opposition Schools"),
					"Evocation": _handle_class_selection("Evocation"),
					"Illusion": _handle_class_selection("Illusion"),
					"Psychic Discipline": _handle_class_selection("psychic discipline"),
				}
				dispatch[title](struct, offense, text)
		else:
			assert False, output
	sb['offense'] = offense

def statistics_pass(struct):
	def _handle_stats(statistics, text):
		parts = split_comma_and_semicolon(text)
		assert len(parts) == 6, parts
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			bsparts = list(bs.children)
			assert len(bsparts) == 2, str(bs)
			name = bsparts.pop(0).get_text().lower()
			assert name in ["str", "dex", "con", "int", "wis", "cha"], name
			value = bsparts.pop().strip()
			if value in ["-", "—"]:
				statistics[name] = None
			else:
				statistics[name] = int(value)
	
	def _handle_attribute(name):
		def _handle_attribute_impl(_, stats, text):
			text = filter_end(text, [",", "<br/>"]).strip()
			if text in ["-", "—"]:
				stats[name] = None
			else:
				stats[name] = int(text)
		return _handle_attribute_impl

	def _handle_bab(name):
		def _handle_bab_impl(struct, _, text):
			offense = struct['stat_block']['offense']
			if text.endswith(";"):
				text = text[:-1]
			elif text.endswith("<br/>"):
				text = text[:-5]
			elif text.endswith("<br/>"):
				assert False, "Unrecognized string structure: %s" % text
			offense[name.lower()] = number_with_modifiers(text.strip(), name.lower())
		return _handle_bab_impl

	def _handle_feats(_, statistics, text):
		assert text.find(";") == -1, text
		parts = split_maintain_parens(text.strip(), ",")
		feats = []
		for part in parts:
			bs = BeautifulSoup(part, 'html.parser')
			notation = None
			sups = bs.find_all('sup')
			for sup in sups:
				sup.replace_with('')
				ntext = sup.extract().get_text()
				assert notation == None
				notation = ntext
			link = None
			if bs.a and bs.a['href'].startswith('FeatDisplay'):
				_, link = extract_link(bs.a)
				bs.a.replace_with(bs.a.get_text())
			part = str(bs)
			part = clear_tags(part, ["br"])
			feat = string_with_modifiers(part, "feat")
			if "modifiers" in feat:
				feat['modifiers'] = link_modifiers(feat['modifiers'])
			if link:
				feat['link'] = link
			if notation:
				feat['notation'] = notation
			feats.append(feat)
		statistics['feats'] = feats
	
	def _handle_skills(_, statistics, text):
		if text.endswith(";"):
			text = text[:-1]
		assert ";" not in text, bs
		skills = {
			"type": "stat_block_section",
			"subtype": "skills",
			"skills": []
		}
		assert "<a" not in text, text
		parts = split_maintain_parens(text, ",")
		for part in parts:
			skill = {
				"type": "stat_block_section",
				"subtype": "skill",
			}
			m = re.search(r'(.*) +([-—+]?[0-9]+) +\((.*)\)', part)
			if m:
				parts = m.groups()
				assert len(parts) == 3, parts
				skill['name'] = parts[0]
				skill['value'] = parse_number(parts[1])
				modtext = parts[2]
				skill['modifiers'] = modifiers_from_string_list(
					[m.strip() for m in modtext.split(",")])
			else:
				m = re.search(r'(.*) +([-–—+]?[0-9]+)', part)
				if m:
					parts = m.groups()
					assert len(parts) == 2, parts
					skill['name'] = parts[0]
					skill['value'] = parse_number(parts[1])
				else:
					assert False, "%s: %s" % (part, str(bs))
			skills["skills"].append(skill)
		statistics['skills'] = skills
	
	def _handle_racial_modifiers(_, statistics, text):
		text = clear_tags(text, ["br"])
		rmods = modifiers_from_string_list(
			split_maintain_parens(text, ","), subtype="racial_modifier")
		modifiers = statistics['skills'].setdefault("modifiers", [])
		modifiers.extend(rmods)
	
	def _handle_languages(_, statistics, text):
		text = clear_tags(text, ["br"])
		#parts = text.split(";")
		#languages = {
		#	"type": "stat_block_section",
		#	"subtype": "languages",
		#	"languages": []
		#}
		#langs = parts.pop(0)
		#if len(parts) > 0:
		#	modtext = ", ".join(parts)
		#	# TODO: actually handle communication abilities
		#	languages['communication_abilities'] = string_with_modifiers_from_string_list(
		#		split_maintain_parens(modtext, ","),
		#		"communication_ability")
		#	vs = split_maintain_parens(modtext, ",")
		#	for v in vs:
		#		log_element("%s.log" % "communication_ability")("%s" % (v))
		#
		#ls = split_maintain_parens(langs, ",")
		#langs = string_with_modifiers_from_string_list(
		#		split_maintain_parens(langs, ","), "language")
		#
		#for l in ls:
		#	log_element("%s.log" % "languages")("%s" % (l))
		#languages['languages'] = langs
		languages = universal_handle_languages(text)
		statistics['languages'] = languages

	def _handle_sq(_, statistics, text):
		text = clear_tags(text, ["br"])
		bs = BeautifulSoup(text, 'html.parser')
		sups = bs.find_all('sup')
		for sup in sups:
			sup.replace_with('')
		text = str(bs)

		sqs = string_with_modifiers_from_string_list(
				split_maintain_parens(text, ","),
				"special_quality")
		for sq in sqs:
			assert ";" not in sq["name"], "Don't presently handle the SQ list having modifiers: %s" % text
		statistics["special_qualities"] = sqs

	def _handle_grapple(_, statistics, text):
		assert False

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

	sb = struct['stat_block']
	stats_section = find_section(struct, "Statistics")
	stats_text = stats_section['text']
	struct['sections'].remove(stats_section)
	statistics = {
		"type": "stat_block_section",
		"subtype": "statistics"
	}
	bs = BeautifulSoup(stats_text, 'html.parser')
	output = break_out_subtitles(bs, 'b')
	while len(output) > 0:
		title, text = output.pop(0)
		if title:
			dispatch = {
				"Str": _handle_attribute("str"),
				"Dex": _handle_attribute("dex"),
				"Con": _handle_attribute("con"),
				"Int": _handle_attribute("int"),
				"Wis": _handle_attribute("wis"),
				"Cha": _handle_attribute("cha"),
				"Base Atk": _handle_bab('bab'),
				"CMB": _handle_bab("cmb"),
				"CMD": _handle_bab("cmd"),
				"Feats": _handle_feats,
				"Skills": _handle_skills,
				"Racial Modifiers": _handle_racial_modifiers,
				"Racial Modifier": _handle_racial_modifiers,
				"Languages": _handle_languages,
				"SQ": _handle_sq,
				"Grapple": _handle_bab("grapple"),
				"Gear": handle_noop("Gear"),
				"Combat Gear": handle_noop("Combat Gear"),
				"Other Gear": handle_noop("Other Gear"),
			}
			dispatch[title](struct, statistics, text)
		else:
			assert False, output
	sb['statistics'] = statistics
	struct['stat_block']['statistics'] = statistics

def ecology_pass(struct):
	def _handle_environment(ecology, bs):
		assert str(bs).find(";") == -1, bs
		ecology['environment'] = str(bs).strip()

	def _handle_organization(ecology, bs):
		#TODO: Handle links
		ecology['organization'] = str(bs).strip()

	stats_section = find_section(struct, "Ecology")
	stats_text = stats_section['text']
	struct['sections'].remove(stats_section)
	parts = list(filter(lambda d: d != "",
		[d.strip() for d in stats_text.split("<br/>")]))
	ecology = {
		"name": "Ecology",
		"type": "stat_block_section",
		"subtype": "ecology"
	}
	for part in parts:
		bs = BeautifulSoup(part, 'html.parser')
		namebs = list(bs.children).pop(0)
		name = namebs.get_text()
		namebs.extract()
		dispatch = {
			"Environment": _handle_environment,
			"Organization": _handle_organization
		}
		dispatch[name](ecology, bs)
	struct['stat_block']['ecology'] = ecology

def special_ability_pass(struct):
	def _handle_special_ability(data):
		#TODO: Handle links
		sa = {
			"type": "stat_block_section",
			"subtype": "special_ability",
		}
		bs = BeautifulSoup(data, 'html.parser')
		name_tag = list(bs.children)[0]
		name = name_tag.get_text()
		name_tag.extract()
		text = str(bs).strip()
		while text.endswith("<br/>"):
			text = text[:-5]
		sa['text'] = text
		name_parts = name.split("(")
		sa['name'] = name_parts.pop(0).strip()
		assert len(name_parts) == 1, name_tag
		sa_type = name_parts[0].replace(")", "").strip()
		ability_types = {
			"Ex": "Extraordinary",
			"Sp": "Spell-Like",
			"Su": "Supernatural"
		}
		assert sa_type in ability_types.keys()
		sa['ability_type'] = ability_types[sa_type]
		sa['ability_type_abbrev'] = sa_type
		return sa

	sa_section = find_section(struct, "Special Abilities")
	if sa_section:
		sa_text = sa_section['text']
		struct['sections'].remove(sa_section)
		bs = BeautifulSoup(sa_text, 'html.parser')
		parts = break_out_subtitles(bs)
		parts = [''.join([str(t) for t in p]) for p in parts]
		special_abilities = []
		for part in parts:
			special_abilities.append(_handle_special_ability(part))
		struct['stat_block']['special_abilities'] = special_abilities

def section_pass(struct):
	def _handle_affliction(section):
		# TODO pull out dice
		sec_text = section['text']
		del section['text']
		del section['sections']
		struct['sections'].remove(section)
		bs = BeautifulSoup(sec_text, 'html.parser')
		parts = break_out_subtitles(bs)
		output = []
		for part in parts:
			pname = part.pop(0).get_text()
			text = ''.join([str(p) for p in part]).strip()
			while text.endswith("<br/>"):
				text = text[:-5]
			if text.endswith(";"):
				text = text[:-1]
			output.append((pname, text))
		for element in output:
			name, text = element
			name = name.lower().strip()
			if name == "type":
				name = "affliction_type"
			section[name] = text
		section['type'] = 'stat_block_section'
		section['subtype'] = 'affliction'
		return section

	afflictions = []
	for section in struct['sections']:
		bs = BeautifulSoup(section['text'].strip(), 'html.parser')
		children = list(bs.children)
		if len(children) == 1:
			# Table, leave it in sections
			pass
		elif section['name'] not in ["Description"]:
			afflictions.append(_handle_affliction(section))
	if len(afflictions) > 0:
		struct['stat_block']['afflictions'] = afflictions

def find_section(struct, name):
	for s in struct['sections']:
		if s['name'] == name:
			return s
