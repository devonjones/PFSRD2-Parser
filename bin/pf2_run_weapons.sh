#!/bin/bash

source dir.conf

rm -f errors.pf2.weapons.log

if test -f "errors.pf2.weapons"; then
	cat errors.pf2.weapons | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_weapon_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.weapons.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Weapons/Weapons.aspx.ID_*.html | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_weapon_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.weapons.log
		fi
	done
fi
