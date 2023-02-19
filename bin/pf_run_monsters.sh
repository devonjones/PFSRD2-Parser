#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.pf.monsters.log

if test -f "errors.pf.monsters"; then
	cat errors.pf.monsters | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf_monster_parse -o $PF_DATA_DIR $i ; then
			echo $i >> errors.pf.monsters.log
		fi
	done
else
	for i in `ls $PF_WEB_DIR/MonsterDisplay/MonsterDisplay.aspx.ItemName_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf_monster_parse -o $PF_DATA_DIR $i ; then
			echo $i >> errors.pf.monsters.log
		fi
	done
fi

