import warnings
from pprint import pprint
from bs4 import BeautifulSoup, Tag, MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

def split_maintain_parens(text, split, parenleft="(", parenright=")"):
	parts = text.split(split)
	newparts = []
	while len(parts) > 0:
		part = parts.pop(0)
		if part.find(parenleft) > -1 and part.rfind(parenright) < part.rfind(parenleft):
			newpart = part
			while newpart.find(parenleft) > -1 and newpart.rfind(parenright) < newpart.rfind(parenleft):
				newpart = newpart + split + parts.pop(0)
			newparts.append(newpart)
		else:
			newparts.append(part)
	return [p.strip() for p in newparts]

def split_comma_and_semicolon(text, parenleft="(", parenright=")"):
	parts = [
		split_maintain_parens(t, ",", parenleft, parenright) for t in split_maintain_parens(text, ";", parenleft, parenright)]
	return list(filter(
		lambda e: e != "",
		[item for sublist in parts for item in sublist]
	))

def filter_end(text, tokens):
	while True:
		text = text.strip()
		testtext = text
		for token in tokens:
			if text.endswith(token):
				flen = len(token) * -1
				text = text[:flen]
		if testtext == text:
			return text

def filter_entities(text):
	text = text.replace("\u00c2\u00ba", "º") # u00ba
	text = text.replace("\u00c3\u0097", "×")
	text = text.replace("\u00e2\u0080\u0091", "‑")
	text = text.replace("\u00e2\u0080\u0093", "–")
	text = text.replace("\u00e2\u0080\u0094", "—")
	text = text.replace("\u00e2\u0080\u0099", "’") # u2019
	text = text.replace("\u00e2\u0080\u009c", "“")
	text = text.replace("\u00e2\u0080\u009d", "”")
	text = text.replace("\u00e2\u0080\u00a6", "…") # u2026
	text = text.replace("%5C", "\\")
	text = text.replace("&amp;", "&")
	text = text.replace("\u00ca\u00bc", "’") # u2019 (was u02BC)
	text = text.replace("\u00c2\u00a0", " ")
	text = text.replace("\u00a0", " ")
	text = ' '.join([part.strip() for part in text.split("\n")])
	return text

def log_element(fn):
	fp = open(fn, "a+")
	def log_e(element):
		fp.write(element)
		fp.write("\n")
	return log_e

def clear_tags(text, taglist):
	bs = BeautifulSoup(text, 'html.parser')
	for tag in taglist:
		for t in bs.find_all(tag):
			t.replace_with(t.get_text())
	return filter_entities(str(bs))

def find_list(text, elements):
	for element in elements:
		if text.find(element) > -1:
			return element
	return False

def is_tag_named(element, taglist):
	if type(element) != Tag:
		return False
	elif element.name in taglist:
		return True
	return False

def has_name(tag, name):
	if hasattr(tag, 'name') and tag.name == name:
		return True
	return False

def get_text(detail):
	return ''.join(detail.findAll(text=True))

def bs_pop_spaces(children):
	clean = False
	while not clean:
		testval = children[0]
		if type(testval) == Tag:
			clean = True
		elif testval.strip() != "":
			clean = True
		else:
			children.pop(0)

def get_unique_tag_set(text):
	bs = BeautifulSoup(text, 'html.parser')
	return set([tag.name for tag in bs.find_all()])

def split_on_tag(text, tag):
	bs = BeautifulSoup(text, 'html.parser')
	parts = bs.findAll(tag)
	for part in parts:
		part.insert_after("|")
		part.unwrap()
	return str(bs).split("|")

def clear_garbage(text):
	if type(text) == list:
		text = ''.join(text).strip()
	bs = BeautifulSoup(text, 'html.parser')
	children = list(bs.children)
	while children and is_tag_named(children[0], ['br', 'hr']):
		children.pop(0).decompose()
	while children and is_tag_named(children[-1], ['br', 'hr']):
		children.pop().decompose()
	return str(bs)
