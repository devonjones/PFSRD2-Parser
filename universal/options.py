import argparse
import os
import sys

from pfsrd2.ability_enrichment import set_inline_enrich


def exec_main(options, args, function, localdir):
    if getattr(options, "no_enrich", False):
        set_inline_enrich(False)
    if not options.output and not options.dryrun:
        sys.stderr.write("-o/--output required")
        sys.exit(1)
    else:
        if not options.dryrun and not os.path.exists(options.output):
            sys.stderr.write("-o/--output points to a directory that does not exist")
            sys.exit(1)
        if not options.dryrun and not os.path.isdir(options.output):
            sys.stderr.write("-o/--output points to a file, it must point to a directory")
            sys.exit(1)
        for arg in args:
            function(arg, options)


def option_parser(usage):
    parser = argparse.ArgumentParser(usage=usage)
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        help="Output data directory.  Should be top level directory of psrd data. (required)",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        dest="dryrun",
        default=False,
        action="store_true",
        help="Dry run (no actual output)",
    )
    parser.add_argument(
        "-k",
        "--skip-schema",
        dest="skip_schema",
        default=False,
        action="store_true",
        help="Skip schema validation",
    )
    parser.add_argument(
        "-s",
        "--stdout",
        dest="stdout",
        default=False,
        action="store_true",
        help="Write json to stdout",
    )
    parser.add_argument(
        "--no-enrich",
        dest="no_enrich",
        default=False,
        action="store_true",
        help="Skip inline regex enrichment (use for from-scratch rebuilds)",
    )
    parser.add_argument("files", nargs="*", help="Input files to process")
    return parser
