#!/bin/bash

cat markdown.log | perl -pe "s/ :.*//g" | sort | uniq > markdown.fields
cat markdown.log | sort | uniq > markdown.uniq.log
rm markdown.log

./json_map ../../pfsrd2-data/monsters/ ../../pfsrd2-data/npcs/ > pfsrd2.test.map.json 2> pfsrd2.filelist
cat pfsrd2.filelist | sort | uniq > pfsrd2.test.filelist
rm pfsrd2.filelist