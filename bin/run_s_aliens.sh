#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.aliens.log

if test -f "errors.aliens"; then
	cat errors.creatures | while read i
	do
		if ! ./alien_parse -o $SDATA_DIR $i ; then
			echo $i >> errors.aliens.log
		fi
	done
else
	for i in `ls $SWEB_DIR/AlienDisplay/AlienDisplay.aspx.ItemName_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./alien_parse -o $SDATA_DIR $i ; then
			echo $i >> errors.aliens.log
		fi
	done
fi

