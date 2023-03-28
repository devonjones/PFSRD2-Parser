from pprint import pprint
from markdownify import MarkdownConverter, abstract_inline_conversion

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