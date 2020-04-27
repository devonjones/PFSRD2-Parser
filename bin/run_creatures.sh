#!/bin/bash
set -e

source dir.conf
ls $WEB_DIR/Monsters/Monsters.aspx.ID_* | xargs ./creature_parse -o $DATA_DIR
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_5
