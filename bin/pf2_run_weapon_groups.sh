#!/bin/bash

source dir.conf

rm -f errors.pf2.weapon_group.log

if test -f "errors.pf2.weapon_group"; then
	cat errors.pf2.weapon_group | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_weapon_group_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.weapon_group.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/WeaponGroups/WeaponGroups.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_weapon_group_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.weapon_group.log
		fi
	done
fi
