#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"

rm -f "$BIN_DIR/errors.pf2.monster_family.log"

if test -f "$BIN_DIR/errors.pf2.monster_family"; then
	cat "$BIN_DIR/errors.pf2.monster_family" | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! "$BIN_DIR/pf2_monster_family_parse" -o "$PF2_DATA_DIR" "$@" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.monster_family.log"
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/MonsterFamilies/MonsterFamilies.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! "$BIN_DIR/pf2_monster_family_parse" -o "$PF2_DATA_DIR" "$@" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.monster_family.log"
		fi
	done
fi

"$BIN_DIR/copy_schema.sh" monster_family
