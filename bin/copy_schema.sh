#!/bin/bash
# Copy a schema file to the data directory with version in the filename.
# Usage: copy_schema.sh <schema_name>
# Example: copy_schema.sh spell
#   Copies pfsrd2/schema/spell.schema.json -> $PF2_DATA_DIR/spell.schema.2.0.json

if [ $# -ne 1 ]; then
	echo "Usage: $0 <schema_name>"
	exit 1
fi

SCHEMA_NAME=$1
SCHEMA_DIR=$(dirname "$0")/../pfsrd2/schema
SCHEMA_FILE="${SCHEMA_DIR}/${SCHEMA_NAME}.schema.json"

if [ ! -f "$SCHEMA_FILE" ]; then
	echo "Error: Schema file not found: $SCHEMA_FILE"
	exit 1
fi

# Extract schema_version from the schema's top-level properties
VERSION=$(python3 -c "
import json, sys
with open('$SCHEMA_FILE') as f:
    schema = json.load(f)
v = schema.get('properties', {}).get('schema_version', {}).get('enum', [])
if v:
    print(v[0])
else:
    print('', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null)

if [ -z "$VERSION" ]; then
	echo "Error: No schema_version found in $SCHEMA_FILE"
	exit 1
fi

DEST="${PF2_DATA_DIR}/${SCHEMA_NAME}.schema.${VERSION}.json"
cp "$SCHEMA_FILE" "$DEST"
echo "Schema copied: $(basename "$DEST")"
