import os
import json
import jsonschema

def get_schema(schema_name):
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    schema_file = os.path.join(this_dir, schema_name)
    with open(schema_file) as fp:
        return json.load(fp)
    raise "No schema found"

def validate_against_schema(data, schema_name):
    schema = get_schema(schema_name)
    return jsonschema.validate(data, schema)
