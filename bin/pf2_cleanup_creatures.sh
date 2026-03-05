#!/bin/bash

cat markdown.log | perl -pe "s/ :.*//g" | sort | uniq > pf2.logs/markdown.fields
cat markdown.log | sort | uniq > pf2.logs/markdown.uniq.log
rm markdown.log

./json_map ../../pfsrd2-data/monsters/ ../../pfsrd2-data/npcs/ > pf2.logs/pfsrd2.test.map.json 2> pfsrd2.filelist
cat pfsrd2.filelist | sort | uniq > pf2.logs/pfsrd2.test.filelist
rm pfsrd2.filelist