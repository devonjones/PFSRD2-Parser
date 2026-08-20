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
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path) as handle:
                docs.append(json.load(handle))
    return docs


def iter_json_dir(*kinds):
    """Yield every JSON doc under the given data subdirectories, one at a time.

    The streaming counterpart of load_json_dir. A verifier that folds over the
    whole corpus does not need it resident: measured on the published data,
    degree_exemptions.main() peaked at 1453 MB holding 30k docs and 34 MB
    streaming the same folds to the same answers.
    """
    for kind in kinds:
        pattern = os.path.join(data_dir(), kind, "**", "*.json")
        # sorted: glob order is arbitrary, so verifier output could differ
        # between machines. Not load-bearing any more -- the callers no longer
        # stop early -- and not observable from a single process, so no test
        # pins it. Kept for reproducible output, which is worth a sort().
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path) as handle:
                yield json.load(handle)


def load_equipment(predicate=None):
    """Load equipment docs, optionally keeping only those matching predicate."""
    docs = load_json_dir("equipment")
    if predicate is None:
        return docs
    return [doc for doc in docs if predicate(doc)]
