#!/bin/bash
set -e

source dir.conf

rm -f ~/.pfsrd2/pfsrd2.db

./pf2_run_licenses.sh
./pf2_run_sources.sh
./pf2_source_load -o $PF2_DATA_DIR
./pf2_run_traits.sh
./pf2_trait_load -o $PF2_DATA_DIR
./pf2_run_monster_abilities.sh
./pf2_monster_ability_load -o $PF2_DATA_DIR
./pf2_run_armor_groups.sh
./pf2_armor_group_load -o $PF2_DATA_DIR
./pf2_run_weapon_groups.sh
./pf2_weapon_group_load -o $PF2_DATA_DIR
