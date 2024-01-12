import os
import json
import jsonschema


def get_data(data_name):
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    schema_file = os.path.join(this_dir, data_name)
    with open(schema_file) as fp:
        return json.load(fp)
    raise "Data not found"
