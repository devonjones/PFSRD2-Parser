#!/bin/bash

source dir.conf

rm errors.pf2.monster_abilities.log

if test -f "errors.pf2.monster_abilities"; then
	cat errors.pf2.monster_abilities | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_monster_ability_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.monster_abilities.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/MonsterAbilities/MonsterAbilities.aspx.ID_*.html | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_monster_ability_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.monster_abilities.log
		fi
	done
fi

