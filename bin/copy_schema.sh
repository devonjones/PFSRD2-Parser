#!/bin/bash
# Copy a schema file to the data directory with version in the filename.
# Usage: copy_schema.sh <schema_name>
# Example: copy_schema.sh spell
#   Copies pfsrd2/schema/spell.schema.json -> $PF2_DATA_DIR/spell.schema.2.0.json
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"

if [ $# -ne 1 ]; then
	echo "Usage: $0 <schema_name>"
	exit 1
fi

SCHEMA_NAME=$1
SCHEMA_DIR="$BIN_DIR/../pfsrd2/schema"
SCHEMA_FILE="${SCHEMA_DIR}/${SCHEMA_NAME}.schema.json"

if [ ! -f "$SCHEMA_FILE" ]; then
	echo "Error: Schema file not found: $SCHEMA_FILE"
	exit 1
fi

# Extract schema_version from the schema's top-level properties
VERSION=$(jq -re '.properties.schema_version.enum[0]' "$SCHEMA_FILE" 2>/dev/null)

if [ -z "$VERSION" ]; then
	echo "Error: No schema_version found in $SCHEMA_FILE"
	exit 1
fi

DEST="${PF2_DATA_DIR}/${SCHEMA_NAME}.schema.${VERSION}.json"
cp "$SCHEMA_FILE" "$DEST"
echo "Schema copied: $(basename "$DEST")"
