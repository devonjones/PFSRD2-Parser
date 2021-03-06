import sys
import re
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

def noop_pass(details):
	retdetails = []
	for detail in details:
		if not str(detail).strip() == "":
			retdetails.append(detail)
	return retdetails

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
			details = img_details(detail)
			h = Heading(1, get_text(detail), subname)
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
			if fo.name == "b" and get_text(fo) != "Source":
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
				{'type': 'section', 'text': text, 'sections': []}))
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
			raise Exception("This should be unreachable")
	if len(text) > 0:
		newlines.append(''.join(text))
	return newlines

def parse_body(div, book=False, title=False, max_title=5):
	lines = noop_pass(div.contents)
	lines = title_pass(lines, max_title)
	lines = subtitle_pass(lines, max_title)
	lines = text_pass(lines)
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

def parse_universal(filename, title=False, max_title=5):
	fp = open(filename)
	try:
		soup = BeautifulSoup(fp, "lxml")
		href_filter(soup)
		content = soup.find(id="ctl00_MainContent_DetailedOutput")
		if content:
			return parse_body(content, title, max_title)
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
	if(hasattr(span, 'class')):
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

def split_maintain_parens(text, split):
	parts = [t.strip() for t in text.split(split)]
	newparts = []
	while len(parts) > 0:
		part = parts.pop(0)
		if part.find("(") > -1 and part.rfind(")") < part.rfind("("):
			newpart = part
			while newpart.find("(") > -1 and newpart.rfind(")") < newpart.rfind("("):
				newpart = newpart + split + " " + parts.pop(0)
			newparts.append(newpart)
		else:
			newparts.append(part)
	return newparts
