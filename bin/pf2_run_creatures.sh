#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm -f "$BIN_DIR/errors.pf2.creatures.log"

if test -f "$BIN_DIR/errors.pf2.creatures"; then
	cat "$BIN_DIR/errors.pf2.creatures" | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! "$BIN_DIR/pf2_creature_parse" -o $PF2_DATA_DIR "$@" $i ; then
			echo $i >> "$BIN_DIR/errors.pf2.creatures.log"
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Monsters/Monsters.aspx.ID_*.html | msort -j -q -l -n 1 -c hybrid`
	do
		if ! "$BIN_DIR/pf2_creature_parse" -o $PF2_DATA_DIR "$@" $i ; then
			echo $i >> "$BIN_DIR/errors.pf2.creatures.log"
		fi
	done
fi


"$BIN_DIR/copy_schema.sh" creature
