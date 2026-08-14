"""Shared helpers for the QA verifiers.

Every verifier reads the generated JSON out of the sibling pfsrd2-data repo
and walks it looking for contradictions. The path and the load-a-directory
loop were copied into each one; they live here instead.

PF2_DATA_DIR overrides the default location, matching bin/dir.conf, so a
verifier can run against a data checkout somewhere else.
"""

import glob
import json
import os

DEFAULT_DATA = "/home/devon/MasterworkTools/pfsrd2/pfsrd2-data"


def data_dir():
    """Root of the generated-data repo."""
    return os.environ.get("PF2_DATA_DIR", DEFAULT_DATA)


def load_json_dir(*kinds):
    """Load every JSON doc under the given data subdirectories."""
    docs = []
    for kind in kinds:
        pattern = os.path.join(data_dir(), kind, "**", "*.json")
        for path in glob.glob(pattern, recursive=True):
            with open(path) as handle:
                docs.append(json.load(handle))
    return docs


def load_equipment(predicate=None):
    """Load equipment docs, optionally keeping only those matching predicate."""
    docs = load_json_dir("equipment")
    if predicate is None:
        return docs
    return [doc for doc in docs if predicate(doc)]
