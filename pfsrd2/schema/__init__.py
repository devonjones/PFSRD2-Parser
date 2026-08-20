import json
import os

import jsonschema

from universal.universal import assert_every_degree_was_modelled


def get_schema(schema_name):
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    schema_file = os.path.join(this_dir, schema_name)
    with open(schema_file) as fp:
        return json.load(fp)


def validate_against_schema(data, schema_name):
    """The output gate: is this object publishable?

    Two checks, deliberately not two functions. jsonschema answers "is the
    shape legal", which cannot see a MISSING optional field -- and "valid but
    missing degree_effects" is indistinguishable from "this degree had no
    damage", which is how every degree-writer but one shipped unmodelled at
    some point in this feature's history, equipment included and still.

    They stay together because the invariant is only worth anything if EVERY
    parser runs it, and a second function each caller must remember to call is
    a guard that gets dropped -- the exact failure it exists to catch. If a
    third such invariant appears, extract a publishable() that composes them
    rather than growing this one.

    The degree check runs first so its message is what a developer sees.
    """
    assert_every_degree_was_modelled(data, schema_name)
    return jsonschema.validate(data, get_schema(schema_name))
