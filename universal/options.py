import argparse
import os
import sys


def exec_main(options, args, function, localdir):
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


def exec_load_main(parser, function):
    args = parser.parse_args()
    if not args.db:
        sys.stderr.write("-d/--db required")
        sys.exit(1)
    function(args.db, [], args.parent)


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
    parser.add_argument("files", nargs="*", help="Input files to process")
    return parser


def load_option_parser(usage):
    parser = argparse.ArgumentParser(usage=usage)
    parser.add_argument("-d", "--db", dest="db", help="Sqlite DB to load into (required)")
    parser.add_argument(
        "-p", "--parent", dest="parent", help="Parent object to load under (default: psrd)"
    )
    return parser
