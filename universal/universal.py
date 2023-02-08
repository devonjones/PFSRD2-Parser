import sys
from universal.utils import split_maintain_parens, clear_tags, filter_entities
from hashlib import md5
from pprint import pprint
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup, BeautifulStoneSoup, Tag, NavigableString

class Heading():
	def __init__(self, level, name, subname=None):
		self.level = level
		self.name = name.strip()
		self.subname = subname
		self.details = []

	def __repr__(self):
		if self.subname:
			return "<Heading %s:%s (%s) %s>" % (
				self.level, self.name, self.subname, self.details)
		else:
			return "<Heading %s:%s %s>" % (
				self.level, self.name, self.details)

def href_filter(soup):
	hrefs = soup.findAll('a')
	for href in hrefs:
		if not href.has_attr('href'):
			href.decompose()
			continue
		if (href["href"].find(".aspx?ID=") > -1):
			o = urlparse(href["href"])
			attrs = list(href.attrs)
			for a in attrs:
				del href[a]
			href["game-obj"] = o.path.split(".")[0]
			q = parse_qs(o.query)
			for k,vs in q.items():
				for v in vs:
					if k == "ID":
						k = "aonid"
					href[k.lower()] = v
		elif (href["href"] == "javascript:void(0);"):
			body = BeautifulSoup(href.renderContents(), "lxml")
			if len(body.contents) == 1:
				href.replaceWith(body.contents[0])
			else:
				href.replaceWith(body.renderContents())

def span_formatting_filter(soup):
	spans = soup.findAll('span')
	for span in spans:
		if span.has_attr('style') and len(list(span.children)) == 1:
			text = get_text(span)
			if len(text.strip()) == 0:
				span.decompose()

def noop_pass(details):
	retdetails = []
	for detail in details:
		if not str(detail).strip() == "":
			retdetails.append(detail)
	return retdetails

def entity_pass(details):
	for detail in details:
		if 'sections' in detail:
			entity_pass(detail['sections'])
		if "text" in detail:
			detail['text'] = detail['text'].replace("\u00c2\u00ba", "º") # u00ba
			detail['text'] = detail['text'].replace("\u00c3\u0097", "×")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u0091", "‑")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u0093", "–")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u0094", "—")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u0099", "’") # u2019
			detail['text'] = detail['text'].replace("\u00e2\u0080\u009c", "“")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u009d", "”")
			detail['text'] = detail['text'].replace("\u00e2\u0080\u00a6", "…") # u2026
			detail['text'] = detail['text'].replace("%5C", "\\")
			detail['text'] = detail['text'].replace("&amp;", "&")
			detail['text'] = detail['text'].replace("\u00ca\u00bc", "’") # u2019 (was u02BC)
			detail['text'] = detail['text'].replace("\u00c2\u00a0", " ")
			detail['text'] = detail['text'].replace("\u00a0", " ")
			detail['text'] = ' '.join([part.strip() for part in detail['text'].split("\n")])
	return details

def title_pass(details, max_title):
	retdetails = []
	for detail in details:
		if has_name(detail, 'h1') and max_title >= 1:
			subname = None
			if len(detail.findAll("span")) > 1:
				raise Exception("unexpected number of subtitles")
			elif len(detail.findAll("span")) == 1:
				obj = detail.findAll("span")[0]
				subname = "".join(obj.extract().strings).strip()
			img = img_details(detail)
			h = Heading(1, get_text(detail), subname)
			if img:
				h.details.extend(img)
			retdetails.append(h)
		elif has_name(detail, 'h2') and max_title >= 2:
			details = img_details(detail)
			h = Heading(2, get_text(detail))
			h.details = details
			retdetails.append(h)
		else:
			retdetails.append(detail)
	return retdetails

def title_collapse_pass(details, level, add_statblocks=True):
	retdetails = []
	curr = None
	for detail in details:
		if detail.__class__ == Heading and detail.level <= level:
			curr = None
			retdetails.append(detail)
		else:
			if curr:
				curr.details.append(detail)
			else:
				retdetails.append(detail)
		if detail.__class__ == Heading and detail.level == level:
			curr = detail
	return retdetails

def subtitle_pass(details, max_title):
	retdetails = []
	for detail in details:
		if hasattr(detail, 'name'):
			if issubclass(detail.__class__, Heading):
				detail.details = subtitle_pass(detail.details, max_title)
				retdetails.append(detail)
			elif has_name(detail, 'h3') and max_title >= 3:
				sub = img_details(detail)
				h = Heading(3, get_text(detail))
				h.details = sub
				retdetails.append(h)
			elif has_name(detail, 'span') and not is_trait(detail):
				retdetails.append(span_to_heading(detail, 3))
			else:
				retdetails.append(detail)
		else:
			retdetails.append(detail)
	return retdetails

def subtitle_text_pass(details, max_title):
	retdetails = []
	for detail in details:
		if issubclass(detail.__class__, str):
			bs = BeautifulSoup(detail, 'html.parser')
			objs = list(bs.children)
			fo = objs.pop(0)
			if fo.name == "b" and get_text(fo) != "Source" and max_title > 2:
				h = Heading(3, get_text(fo))
				h.details = ''.join([str(o) for o in objs])
				retdetails.append(h)
			else:
				retdetails.append(detail)
		else:
			retdetails.append(detail)
	return retdetails

def section_pass(struct):
	proclist = []
	if struct.__class__ == Heading:
		for d in struct.details:
			proclist.append(section_pass(d))
		oldstruct = struct
		struct = {
			'name': filter_name(oldstruct.name),
			'type': 'section',
			'sections': []
		}
		if oldstruct.subname:
			struct['subname'] = oldstruct.subname
		if len(proclist) > 0:
			struct['sections'] = proclist
		struct = section_text_pass(struct)
	return struct

# Adds text to sections
def section_text_pass(struct):
	text = []
	newsections = []
	for item in struct.get('sections', []):
		if item.__class__ == Tag or item.__class__ == NavigableString:
			# Item is text, append it to the text list for attaching to an obj
			text.append(str(item))
		elif item.__class__ == str:
			text.append(item)
		else:
			newsections.append(item)
	if len(text) > 0:
		if 'text' in struct:
			newsections.append(section_text_pass(
				{'type': 'section', 'text': text.strip(), 'sections': []}))
		else:
			struct['text'] = ''.join(text)
	if len(newsections) > 0:
		struct['sections'] = newsections
	else:
		if 'sections' in struct:
			struct['sections'] = []
	return struct

def text_pass(lines):
	newlines = []
	text = []
	for line in lines:
		if line.__class__ == Heading:
			if len(text) > 0:
				newlines.append(''.join(text))
				text = []
			line.details = text_pass(line.details)
			newlines.append(line)
		elif line.__class__ == Tag or line.__class__ == NavigableString:
			text.append(str(line))
		else:
			assert False, line
	if len(text) > 0:
		newlines.append(''.join(text))
	return newlines

def parse_body(div, book=False, title=False, subtitle_text=False, max_title=5):
	lines = noop_pass(div.contents)
	lines = title_pass(lines, max_title)
	lines = subtitle_pass(lines, max_title)
	lines = text_pass(lines)
	if subtitle_text:
		lines = subtitle_text_pass(lines, max_title)
	if max_title >= 5:
		lines = title_collapse_pass(lines, 5, add_statblocks=False)
	if max_title >= 4:
		lines = title_collapse_pass(lines, 4, add_statblocks=False)
	if max_title >= 3:
		lines = title_collapse_pass(lines, 3, add_statblocks=False)
	if max_title >= 2:
		lines = title_collapse_pass(lines, 2)
	if max_title >= 1:
		lines = title_collapse_pass(lines, 1)

	newlines = []
	for line in lines:
		section = section_pass(line)
		newlines.append(section)
	return newlines

def parse_universal(filename, title=False, subtitle_text=False, max_title=5, cssclass="ctl00_MainContent_DetailedOutput"):
	fp = open(filename)
	try:
		soup = BeautifulSoup(fp, "lxml")
		href_filter(soup)
		span_formatting_filter(soup)
		content = soup.find(id=cssclass)
		if content:
			return parse_body(content, title=title, subtitle_text=subtitle_text, max_title=max_title)
	finally:
		fp.close()

def print_struct(top, level=0):
	if issubclass(top.__class__, list):
		print("[")
		for t in top:
			print_struct(t, level)
		print("]")
	if not top:
		return
	sys.stdout.write(''.join(["-" for i in range(0, level)]))
	if top.__class__ == dict:
		if 'name' in top:
			print("# " + top['name'])
		else:
			print("# <Anonymous>")
		if 'sections' in top:
			for s in top['sections']:
				print_struct(s, level + 2)
	elif issubclass(top.__class__, Heading):
		print("* " + top.name)
		for detail in top.details:
			print_struct(detail, level + 2)
	else:
		print("<text>")

def has_name(tag, name):
	if hasattr(tag, 'name') and tag.name == name:
		return True
	return False

def get_text(detail):
	return ''.join(detail.findAll(text=True))

def filter_name(name):
	name = name.strip()
	if name[-1] == ':':
		name = name[:-1]
	return name.strip()

def is_trait(span):
	if(span.has_attr('class')):
		c = span['class']
		if "".join(c).startswith('trait'):
			return True
	return False

def span_to_heading(span, level):
	details = span.contents
	title = get_text(details.pop(0))
	h = Heading(level, title)
	h.details = details
	return h

def img_details(detail):
	if len(detail.findAll("img")) > 0:
		return detail.findAll("img")
	return []

def extract_link(a):
	assert a.name == "a"
	name = get_text(a)
	link = {'type': 'link', 'name': name.strip(), 'alt': name.strip()}
	if a.has_attr('game-obj'):
		link['game-obj'] = a['game-obj']
	if a.has_attr('aonid'):
		link['aonid'] = int(a['aonid'])
	if a.has_attr('href'):
		link['href'] = a['href']
	return name, link

def source_pass(struct, find_object_fxn):
	def _extract_source(section):
		if 'text' in section:
			bs = BeautifulSoup(section['text'], 'html.parser')
			children = list(bs.children)
			if children[0].name == "b" and get_text(children[0]) == "Source":
				children.pop(0)
				book = children.pop(0)
				source = extract_source(book)
				if children[0].name == "sup":
					sup = children.pop(0)
					errata = extract_link(sup.find("a"))
					source['errata'] = errata[1]
				if children[0].name == "br":
					children.pop(0)
				section['text'] = ''.join([str(c) for c in children])
				return [source]
	
	def propagate_sources(section, sources):
		retval = _extract_source(section)
		if retval:
			sources = retval
		if 'sources' in section:
			sources = section['sources']
		else:
			section['sources'] = sources
		for s in section['sections']:
			propagate_sources(s, sources)

	if 'sources' not in struct:
		sb = find_object_fxn(struct)
		struct['sources'] = sb['sources']
	sources = struct['sources']
	for section in struct['sections']:
		propagate_sources(section, sources)

def extract_source(obj):
	text, link = extract_link(obj)
	parts = text.split(" pg. ")
	assert len(parts) == 2
	name = parts.pop(0)
	page = int(parts.pop(0))
	return {'type': 'source', 'name': name, 'link': link, 'page': page}

def aon_pass(struct, basename):
	parts = basename.split("_")
	assert len(parts) == 2
	id_text = parts[1].replace(".html", "")
	struct["aonid"] = int(id_text)
	struct["game-obj"] = parts[0].split(".")[0]

def restructure_pass(struct, obj_name, find_object_fxn):
	sb = find_object_fxn(struct)
	struct[obj_name] = sb
	struct['sections'].remove(sb)

def html_pass(section):
	if 'sections' in section:
		for s in section['sections']:
			html_pass(s)
	if 'stat_block' in section:
		html_pass(section['stat_block'])
	if 'text' in section:
		section['html'] = section['text'].strip()
		del section['text']

def remove_empty_sections_pass(struct):
	if 'sections' in struct:
		for section in struct['sections']:
			remove_empty_sections_pass(section)
			if len(struct.get('sections', [])) == 0:
				del section['sections']
	if "stat_block" in struct:
		remove_empty_sections_pass(struct['stat_block'])
	if 'sections' in struct:
		if len(struct.get('sections', [])) == 0:
			del struct['sections']

def walk(struct, test, function, parent=None):
	if test(struct):
		function(struct, parent)
	if isinstance(struct, dict):
		for k,v in struct.items():
			walk(v, test, function, struct)
	elif isinstance(struct, list):
		for i in struct:
			walk(i, test, function, struct)

def test_key_is_value(k, v):
	def test(struct):
		if isinstance(struct, dict):
			if 'type' in struct:
				if struct.get(k) == v:
					return True
		return False
	return test

def game_id_pass(struct):
	source = struct['sources'][0]
	name = struct['name']
	pre_id = "%s: %s: %s" % (source['name'], source['page'], name)
	struct['game-id'] = md5(str.encode(pre_id)).hexdigest()

def get_links(bs):
	all_a = bs.find_all("a")
	links = []
	for a in all_a:
		_, link = extract_link(a)
		links.append(link)
	return links

def link_modifiers(modifiers):
	for m in modifiers:
		bs = BeautifulSoup(m['name'], 'html.parser')
		links = get_links(bs)
		if links:
			m['name'] = get_text(bs)
			m['links'] = links
	return modifiers

def link_values(values, field="name", singleton=False):
	for v in values:
		bs = BeautifulSoup(v[field], 'html.parser')
		links = get_links(bs)
		if links:
			if singleton:
				assert len(links) == 1, "Multiple links found where one expected: %s" % v[field]
				v[field] = get_text(bs)
				v['link'] = links[0]
			else:
				v[field] = get_text(bs)
				v['links'] = links
	return values

def extract_modifiers(text):
	if text.find("(") > -1:
		assert text.endswith(")"), "Modifiers should be at the end only: %s" % text
		parts = [p.strip() for p in text.split("(")]
		assert len(parts) == 2, text
		text = parts.pop(0)
		mods = parts.pop()
		mtext = split_maintain_parens(mods[0:-1], ",", parenleft="[", parenright="]")
		modifiers = modifiers_from_string_list(mtext)
		return text, link_modifiers(modifiers)
	return text, []

def string_values_from_string_list(strlist, subtype):
	svs = []
	for part in strlist:
		sv = {
			"type": "stat_block_section",
			"subtype": subtype
		}
		part, modifiers = extract_modifiers(part)
		if modifiers:
			assert False, "String Values have no modifiers: %s" % part
		sv["name"] = part
		svs.append(sv)
	return svs

def string_with_modifiers_from_string_list(strlist, subtype):
	swms = []
	for mpart in strlist:
		swm = {
			"type": "stat_block_section",
			"subtype": subtype
		}
		mpart, modifiers = extract_modifiers(mpart)
		if modifiers:
			swm["modifiers"] = modifiers
		swm["name"] = clear_tags(mpart, ["i"])
		swms.append(swm)
	return swms

def modifiers_from_string_list(modlist, subtype="modifier"):
	modifiers = []
	for mpart in modlist:
		mpart = clear_tags(mpart, "i")
		modifiers.append({
			"type": "stat_block_section",
			"subtype": subtype,
			"name": mpart
		})
	return modifiers

def break_out_subtitles(bs, tagname):
	parts = []
	part = []
	title = None
	for tag in bs.children:
		if tag.name == tagname:
			if len(part) > 0:
				if title:
					title = title.get_text().strip()
				parts.append((title, "".join([str(p) for p in part]).strip()))
				part = []
				title = None
			title = tag
		else:
			part.append(tag)
	if len(part) > 0:
		if title:
			title = title.get_text().strip()
		parts.append((title, "".join([str(p) for p in part]).strip()))
	return parts
