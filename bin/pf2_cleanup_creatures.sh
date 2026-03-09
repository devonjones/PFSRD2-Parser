#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat "$BIN_DIR/markdown.log" | perl -pe "s/ :.*//g" | sort | uniq > "$BIN_DIR/pf2.logs/markdown.fields"
cat "$BIN_DIR/markdown.log" | sort | uniq > "$BIN_DIR/pf2.logs/markdown.uniq.log"
rm "$BIN_DIR/markdown.log"

"$BIN_DIR/json_map" ../../pfsrd2-data/monsters/ ../../pfsrd2-data/npcs/ > "$BIN_DIR/pf2.logs/pfsrd2.test.map.json" 2> "$BIN_DIR/pfsrd2.filelist"
cat "$BIN_DIR/pfsrd2.filelist" | sort | uniq > "$BIN_DIR/pf2.logs/pfsrd2.test.filelist"
rm "$BIN_DIR/pfsrd2.filelist"
