# Adding a New Content Type Parser

This guide explains how to add support for parsing a new content type (e.g., items, armor, weapons, spells).

## Overview

Adding a new parser requires creating 4 files:

1. **Parser module** - `pfsrd2/<type>.py` - Python code that parses HTML to JSON
2. **Parse script** - `bin/pf2_<type>_parse` - Entry point for parsing individual files
3. **Load script** - `bin/pf2_<type>_load` - Database loader (optional, for later)
4. **Runner script** - `bin/pf2_run_<type>s.sh` - Shell script that runs the full pipeline

## Step 1: Create the Parser Module

Create `pfsrd2/<type>.py` based on an existing simple parser like `skill.py`.

### Basic Structure

```python
import os
import json
import sys
from pprint import pprint
from bs4 import BeautifulSoup, Tag
from universal.universal import parse_universal, entity_pass
from universal.universal import extract_link, extract_links, extract_source
from universal.universal import aon_pass
from universal.utils import is_tag_named, get_text
from pfsrd2.license import license_pass, license_consolidation_pass


def parse_<type>(filename, options):
    """Main parsing function - entry point for the parser"""
    basename = os.path.basename(filename)
    if not options.stdout:
        sys.stderr.write("%s\n" % basename)

    # Parse HTML into initial structure
    details = parse_universal(filename, subtitle_text=True, max_title=4,
                              cssclass="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    details = entity_pass(details)

    # Restructure and process
    struct = restructure_<type>_pass(details)
    aon_pass(struct, basename)
    section_pass(struct)

    # License information (always include)
    license_pass(struct)
    license_consolidation_pass(struct)

    # For development: just print the structure
    pprint(struct)

    # Later: uncomment these for schema validation and file output
    # if not options.skip_schema:
    #    struct['schema_version'] = 1.0
    #    validate_against_schema(struct, "<type>.schema.json")
    # if not options.dryrun:
    #    output = options.output
    #    jsondir = makedirs(output, '<type>s')
    #    write_creature(jsondir, struct, char_replace(struct['name']))


def restructure_<type>_pass(details):
    """Create the basic structure for this content type"""
    sb = None
    rest = []
    for obj in details:
        if sb == None:
            sb = obj
        else:
            rest.append(obj)

    # Top-level structure
    top = {'name': sb['name'], 'type': '<type>', 'sections': [sb]}
    sb['type'] = 'stat_block_section'
    sb['subtype'] = '<type>'

    # Flatten sections
    top['sections'].extend(rest)
    if len(sb['sections']) > 0:
        top['sections'].extend(sb['sections'])
        sb['sections'] = []

    return top


def section_pass(struct):
    """Extract structured data from sections"""
    def _handle_source(section):
        """Extract source book information"""
        # Implementation here - see skill.py for example
        pass

    def _clear_garbage(section):
        """Remove unwanted HTML elements"""
        # Implementation here - see skill.py for example
        pass

    def _clear_links(section):
        """Extract links into structured format"""
        text = section.setdefault('text', "")
        links = section.setdefault('links', [])
        text, links = extract_links(text)

    _handle_source(struct)
    _clear_garbage(struct)
    _clear_links(struct)
```

### Key Points

- **Start simple** - Just get the basic structure working with `pprint()`
- **Use existing helpers** - Import from `universal.universal` and `universal.utils`
- **Fail fast** - Don't catch exceptions unless you're 100% certain how to handle them
- **Iterate** - Add structured extraction passes incrementally

## Step 2: Create the Parse Script

Create `bin/pf2_<type>_parse` - this is the command-line entry point.

```python
#!/usr/bin/env python
import sys
import os
from pfsrd2.<type> import parse_<type>
from universal.warnings import WarningReporting
from universal.options import exec_main, option_parser


def main():
    usage = "usage: %prog [options] [filenames]\nParses <type>s from pfsrd2 html to json and writes them to the specified directory"
    parser = option_parser(usage)
    (options, args) = parser.parse_args()
    options.subtype = "<type>"
    exec_main(options, args, parse_<type>, "<type>s")


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x bin/pf2_<type>_parse
```

## Step 3: Create the Load Script (Optional)

Create `bin/pf2_<type>_load` - for loading parsed JSON into a database.

This can be created later once you have stable JSON output. For now, just create a placeholder:

```python
#!/usr/bin/env python
import sys
import os
import json
from sh import find
from optparse import OptionParser
from pfsrd2.sql import get_db_path, create_db
from pfsrd2.sql.<type>s import insert_<type>, truncate_<type>s


def load_<type>s(conn, options):
    path = options.output + "/" + "<type>s"
    assert os.path.exists(path), "JSON Directory doesn't exist: %s" % path
    files = find(path, "-type", "f", "-name", "*.json").strip().split("\n")
    files = [os.path.abspath(f) for f in files]
    curs = conn.cursor()
    truncate_<type>s(curs)
    for f in files:
        with open(f) as fp:
            data = json.load(fp)
            print(data['name'])
            insert_<type>(curs, data)
    conn.commit()


def option_parser(usage):
    parser = OptionParser(usage=usage)
    parser.add_option(
        "-o", "--output", dest="output",
        help="Output data directory.  Should be top level directory of psrd data. (required)")
    return parser


def main():
    usage = "usage: %prog [options] [filenames]\nReads <type> json and inserts them into a <type> db"
    parser = option_parser(usage)
    (options, args) = parser.parse_args()
    db_path = get_db_path("pfsrd2.db")
    conn = create_db(db_path)
    load_<type>s(conn, options)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x bin/pf2_<type>_load
```

## Step 4: Create the Runner Script

Create `bin/pf2_run_<type>s.sh` - the pipeline script that processes all files.

```bash
#!/bin/bash

source dir.conf

rm errors.pf2.<type>.log

if test -f "errors.pf2.<type>"; then
	cat errors.pf2.<type> | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_<type>_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.<type>.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/<ContentDir>/<Pattern> | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_<type>_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.<type>.log
		fi
	done
fi
```

**Replace:**
- `<type>` - Your content type (e.g., `item`, `spell`, `feat`)
- `<ContentDir>` - Directory in web files (e.g., `Armor`, `Spells`, `Feats`)
- `<Pattern>` - File pattern to match (e.g., `Armor.aspx.ID_*`, `Spells.aspx.ID_*`)

Make it executable:
```bash
chmod +x bin/pf2_run_<type>s.sh
```

### How the Runner Works

1. **Sources dir.conf** - Loads `$PF2_DATA_DIR` and `$PF2_WEB_DIR` environment variables
2. **Clears old error log** - Removes `errors.pf2.<type>.log`
3. **Checks for error file** - If `errors.pf2.<type>` exists (no .log), only process those files
4. **Otherwise processes all files** - Matches pattern and processes each file
5. **Logs failures** - Any failed file gets written to `errors.pf2.<type>.log`

## Step 5: Test the Parser

```bash
cd PFSRD2-Parser/bin
source dir.conf

# Test on a single file
./pf2_<type>_parse -o $PF2_DATA_DIR $PF2_WEB_DIR/<ContentDir>/<specific_file>

# Run the full pipeline
./pf2_run_<type>s.sh

# Check for errors
cat errors.pf2.<type>.log
```

## Step 6: Iterate on Structured Extraction

Once you have basic parsing working:

1. **Examine the output** - Look at the `pprint()` output to see what data exists
2. **Identify mechanics in text** - Find game mechanics buried in text blocks
3. **Extract to structured fields** - Create new passes to pull out structured data
4. **Update the schema** - Document new fields in `pfsrd2/schema/<type>.schema.json`

### Common Extraction Patterns

Look for these in text blocks to extract:

- **Action types** - "as a reaction", "two actions", etc.
- **Traits** - Often in `<span>` tags with special styling
- **Requirements** - "You must be wielding...", etc.
- **Durations** - "for 1 minute", "until the end of your turn"
- **Costs** - "1 action", "10 gp", etc.
- **Conditions** - "frightened 1", "stunned"
- **Damage** - "2d6 fire damage"

Create focused passes to extract each category.

## Example: Items/Armor

For armor, you might add passes to extract:

```python
def armor_stats_pass(struct):
    """Extract armor-specific mechanics"""
    # AC bonus: +3 AC
    # Dex cap: max Dex +2
    # Check penalty: -2 to checks
    # Speed penalty: -5 ft speed
    # Strength requirement: Str 16
    # Armor group: plate
    # Traits: bulwark, noisy
    pass
```

Each pass should extract specific mechanical properties into discrete fields rather than leaving them as opaque text.

## File Naming Conventions

- **Parser module:** `pfsrd2/<type>.py` (singular)
- **Parse script:** `bin/pf2_<type>_parse` (singular, no extension)
- **Load script:** `bin/pf2_<type>_load` (singular, no extension)
- **Runner script:** `bin/pf2_run_<type>s.sh` (plural, .sh extension)
- **Error log:** `bin/errors.pf2.<type>.log` (singular)
- **Error file:** `bin/errors.pf2.<type>` (singular, no extension)
- **Output directory:** `pfsrd2-data/<type>s/` (plural)

## Summary Checklist

- [ ] Create `pfsrd2/<type>.py` with `parse_<type>()` function
- [ ] Create `bin/pf2_<type>_parse` (make executable)
- [ ] Create `bin/pf2_<type>_load` (make executable, can be placeholder)
- [ ] Create `bin/pf2_run_<type>s.sh` (make executable)
- [ ] Update script with correct content directory and file pattern
- [ ] Test on a single file first
- [ ] Run full pipeline and check errors
- [ ] Iterate on extracting structured mechanics
- [ ] Create/update JSON schema when ready

## Philosophy

Remember the project mission:

- **Structured over opaque** - Extract mechanics into discrete fields
- **Fail fast** - Let exceptions propagate for easier debugging
- **Iterate progressively** - Don't extract everything at once
- **Schema as contract** - Document what data is exposed

Start simple, get it working, then progressively extract more structured data over time.
