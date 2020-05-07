#!/bin/bash
set -e

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

#169
