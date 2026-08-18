import json
import os

import jsonschema


def get_schema(schema_name):
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    schema_file = os.path.join(this_dir, schema_name)
    with open(schema_file) as fp:
        return json.load(fp)


def validate_against_schema(data, schema_name):
    # Imported here, not at module scope: universal.universal reaches back into
    # pfsrd2.enrichment, and this module is pulled in early by every parser.
    from universal.universal import assert_every_degree_was_modelled

    schema = get_schema(schema_name)
    # Before the schema, because "valid but missing a field" is exactly what
    # jsonschema cannot see and what this feature keeps shipping.
    assert_every_degree_was_modelled(data, schema_name)
    return jsonschema.validate(data, schema)
