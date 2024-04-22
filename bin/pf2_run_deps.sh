#!/bin/bash

source dir.conf

./pf2_run_licenses.sh
./pf2_run_traits.sh
./pf2_load_traits -o $PF2_DATA_DIR
./pf2_run_monster_abilities.sh
./pf2_load_monster_abilities -o $PF2_DATA_DIR
