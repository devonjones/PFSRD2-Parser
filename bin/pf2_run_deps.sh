#!/bin/bash

source dir.conf

./pf2_run_licenses.sh
./pf2_run_sources.sh
./pf2_source_load -o $PF2_DATA_DIR
./pf2_run_traits.sh
./pf2_trait_load -o $PF2_DATA_DIR
./pf2_run_monster_abilities.sh
./pf2_monster_ability_load -o $PF2_DATA_DIR
