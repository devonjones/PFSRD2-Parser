from pprint import pprint
from markdownify import MarkdownConverter, abstract_inline_conversion
from universal.utils import get_unique_tag_set, log_element

class PFSRDConverter(MarkdownConverter):
	convert_u = MarkdownConverter.convert_i

	def convert_span(self, el, text, convert_as_inline):
		assert 'title' in el.attrs, "Not an action: %s" % el
		action = el['title']
		# [#] [##] [###] [-] [@]
		match action:
			case "Reaction":
				return "[@]"
			case "Free Action":
				return "[-]"
			case "Single Action":
				return "[#]"
			case "Two Actions":
				return "[##]"
			case "Three Actions":
				return "[###]"
			case _:
				assert False, "Malformed action: %s" % el

	def convert_li(self, el, text, convert_as_inline):
		result = "\n" + super().convert_li(el, text, convert_as_inline).replace("\n", "")
		return result

# Create shorthand method for conversion
def md(html, **options):
	return PFSRDConverter(**options).convert(html)

def markdown_pass(struct, name, path, fxn_valid_tags=None):
	def _validate_acceptable_tags(text, fxn_valid_tags):
		validset = set(['i', 'b', 'u', 'strong', 'ol', 'ul', 'li', 'br',
			'table', 'tr', 'td', 'hr'])
		if "license" in struct:
			validset.add('p')
		if fxn_valid_tags:
			fxn_valid_tags(struct, name, path, validset)
		tags = get_unique_tag_set(text)
		assert tags.issubset(validset), "%s : %s - %s" % (name, text, tags)
	
	for k, v in struct.items():
		if isinstance(v, dict):
			markdown_pass(v, name, "%s/%s" % (path,k), fxn_valid_tags=fxn_valid_tags)
		elif isinstance(v, list):
			for item in v:
				if isinstance(item, dict):
					markdown_pass(item, name, "%s/%s" % (path,k), fxn_valid_tags=fxn_valid_tags)
				elif isinstance(item, str):
					if item.find("<") > -1:
						assert False # For now, I'm unaware of any tags in lists of strings
		elif isinstance(v, str):
			if v.find("<") > -1:
				_validate_acceptable_tags(v, fxn_valid_tags)
				struct[k] = md(v).strip()
				log_element("markdown.log")("%s : %s" % ("%s/%s" % (path, k), name))
