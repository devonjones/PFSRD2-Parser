#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.sf.aliens.log

if test -f "errors.sf.aliens"; then
	cat errors.sf.aliens | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./sf_alien_parse -o $SF_DATA_DIR $i ; then
			echo $i >> errors.sf.aliens.log
		fi
	done
else
	for i in `ls $SF_WEB_DIR/AlienDisplay/AlienDisplay.aspx.ItemName_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./sf_alien_parse -o $SF_DATA_DIR $i ; then
			echo $i >> errors.sf.aliens.log
		fi
	done
fi

