from pprint import pprint
from bs4 import BeautifulSoup, Tag

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
	return str(bs)

def find_list(text, elements):
	for element in elements:
		if text.find(element) > -1:
			return element
	return False