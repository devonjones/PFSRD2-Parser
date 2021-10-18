#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.pf.creatures.log

if test -f "errors.pf.creatures"; then
	cat errors.pf.creatures | while read i
	do
		if ! ./pf_creature_parse -o $PF_DATA_DIR $i ; then
			echo $i >> errors.pf.creatures.log
		fi
	done
else
	for i in `ls $PF_WEB_DIR/AlienDisplay/AlienDisplay.aspx.ItemName_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf_creature_parse -o $PF_DATA_DIR $i ; then
			echo $i >> errors.pf.creatures.log
		fi
	done
fi

