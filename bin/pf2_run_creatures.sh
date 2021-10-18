#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.pf2.creatures.log

if test -f "errors.pf2.creatures"; then
	cat errors.pf2.creatures | while read i
	do
		if ! ./pf2_creature_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.creatures.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Monsters/Monsters.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_creature_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.creatures.log
		fi
	done
fi

