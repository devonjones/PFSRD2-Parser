#!/bin/bash
set -e
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"

rm -f ~/.pfsrd2/pfsrd2.db

"$BIN_DIR/pf2_run_licenses.sh"
"$BIN_DIR/pf2_run_sources.sh"
"$BIN_DIR/pf2_source_load" -o "$PF2_DATA_DIR"
"$BIN_DIR/pf2_run_traits.sh"
"$BIN_DIR/pf2_trait_load" -o "$PF2_DATA_DIR"
"$BIN_DIR/pf2_run_monster_abilities.sh"
"$BIN_DIR/pf2_monster_ability_load" -o "$PF2_DATA_DIR"
"$BIN_DIR/pf2_run_armor_groups.sh"
"$BIN_DIR/pf2_armor_group_load" -o "$PF2_DATA_DIR"
"$BIN_DIR/pf2_run_weapon_groups.sh"
"$BIN_DIR/pf2_weapon_group_load" -o "$PF2_DATA_DIR"
"$BIN_DIR/pf2_run_monster_families.sh"
"$BIN_DIR/pf2_monster_family_load" -o "$PF2_DATA_DIR"
