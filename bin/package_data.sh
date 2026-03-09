#!/bin/bash
# Package pfsrd2-data into tgz files organized by schema.
# Each tgz contains the schema file and all data folders that use it.
# Output goes to the parent directory of pfsrd2-data.
#
# Usage: ./package_data.sh
#   Requires: dir.conf sourced (for PF2_DATA_DIR)

source dir.conf

DATA_DIR="$PF2_DATA_DIR"
OUT_DIR="$(dirname "$DATA_DIR")"
DATE=$(date +%Y-%m-%d)

if [ ! -d "$DATA_DIR" ]; then
	echo "Error: Data directory not found: $DATA_DIR"
	exit 1
fi

# Schema -> data folder mapping
# Each line: schema_name|folder1,folder2,...
MAPPINGS=(
	"item_group|armor_groups,weapon_groups"
	"condition|conditions"
	"creature|monsters,npcs"
	"equipment|armor,equipment,shields,siege_weapons,vehicles,weapons"
	"feat|feats"
	"monster_ability|monster_abilities"
	"skill|skills"
	"source|sources"
	"spell|spells"
	"trait|traits"
)

for mapping in "${MAPPINGS[@]}"; do
	schema_name="${mapping%%|*}"
	folders_csv="${mapping#*|}"

	# Find the schema file (with version in name)
	schema_file=$(ls "$DATA_DIR"/${schema_name}.schema.*.json 2>/dev/null | head -1)
	if [ -z "$schema_file" ]; then
		echo "SKIP: No schema file found for ${schema_name}"
		continue
	fi

	schema_basename=$(basename "$schema_file" .json)
	tgz_name="${schema_basename}.${DATE}.tgz"

	# Build list of paths to include (relative to DATA_DIR)
	paths=()
	paths+=("$(basename "$schema_file")")

	IFS=',' read -ra folder_list <<< "$folders_csv"
	missing=false
	for folder in "${folder_list[@]}"; do
		if [ -d "$DATA_DIR/$folder" ]; then
			paths+=("$folder")
		else
			echo "WARN: Folder $folder not found for schema $schema_name"
			missing=true
		fi
	done

	# Create the tgz
	tar -czf "$OUT_DIR/$tgz_name" -C "$DATA_DIR" "${paths[@]}"
	echo "Created: $tgz_name (${paths[*]})"
done
