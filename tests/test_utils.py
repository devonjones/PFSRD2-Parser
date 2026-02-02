from universal.utils import filter_entities, recursive_filter_entities


class TestFilterEntities:
    def test_mojibake_emdash(self):
        assert filter_entities("\u00e2\u0080\u0094") == "\u2014"

    def test_mojibake_endash(self):
        assert filter_entities("\u00e2\u0080\u0093") == "\u2013"

    def test_mojibake_right_single_quote(self):
        assert filter_entities("\u00e2\u0080\u0099") == "\u2019"

    def test_mojibake_left_single_quote(self):
        assert filter_entities("\u00e2\u0080\u0098") == "\u2018"

    def test_mojibake_left_double_quote(self):
        assert filter_entities("\u00e2\u0080\u009c") == "\u201c"

    def test_mojibake_right_double_quote(self):
        assert filter_entities("\u00e2\u0080\u009d") == "\u201d"

    def test_mojibake_ellipsis(self):
        assert filter_entities("\u00e2\u0080\u00a6") == "\u2026"

    def test_mojibake_multiplication(self):
        assert filter_entities("\u00c3\u0097") == "\u00d7"

    def test_mojibake_degree(self):
        assert filter_entities("\u00c2\u00ba") == "\u00ba"

    def test_mojibake_nonbreaking_hyphen(self):
        assert filter_entities("\u00e2\u0080\u0091") == "\u2011"

    def test_percent_encoded_backslash(self):
        assert filter_entities("%5C") == "\\"

    def test_amp_entity(self):
        assert filter_entities("&amp;") == "&"

    def test_modifier_letter_apostrophe(self):
        assert filter_entities("\u00ca\u00bc") == "\u2019"

    def test_nbsp_c2a0(self):
        assert filter_entities("a\u00c2\u00a0b") == "a b"

    def test_nbsp_a0(self):
        assert filter_entities("a\u00a0b") == "a b"

    def test_html_entity_emdash(self):
        assert filter_entities("\u00e2\u20ac\u201d") == "\u2014"

    def test_html_entity_endash(self):
        assert filter_entities("\u00e2\u20ac\u201c") == "\u2013"

    def test_html_entity_right_single_quote(self):
        assert filter_entities("\u00e2\u20ac\u2122") == "\u2019"

    def test_html_entity_left_double_quote(self):
        assert filter_entities("\u00e2\u20ac\u0153") == "\u201c"

    def test_html_entity_right_double_quote(self):
        assert filter_entities("\u00e2\u20ac\u009d") == "\u201d"

    def test_newline_normalization(self):
        assert filter_entities("line one\nline two") == "line one line two"

    def test_newline_strips_surrounding_whitespace(self):
        assert filter_entities("a \n b") == "a b"


class TestRecursiveFilterEntities:
    def test_nested_dict(self):
        data = {"a": "\u00e2\u0080\u0094", "b": {"c": "\u00e2\u0080\u0093"}}
        recursive_filter_entities(data)
        assert data == {"a": "\u2014", "b": {"c": "\u2013"}}

    def test_nested_list(self):
        data = ["\u00e2\u0080\u0094", ["\u00e2\u0080\u0093"]]
        recursive_filter_entities(data)
        assert data == ["\u2014", ["\u2013"]]

    def test_mixed_structure(self):
        data = {"items": [{"name": "\u00e2\u0080\u0099test"}]}
        recursive_filter_entities(data)
        assert data == {"items": [{"name": "\u2019test"}]}

    def test_does_not_normalize_newlines(self):
        data = {"text": "line one\nline two"}
        recursive_filter_entities(data)
        assert data["text"] == "line one\nline two"

    def test_non_string_values_unchanged(self):
        data = {"count": 42, "flag": True, "empty": None}
        recursive_filter_entities(data)
        assert data == {"count": 42, "flag": True, "empty": None}
