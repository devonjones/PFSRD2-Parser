#!/bin/bash

source dir.conf
#./npc_parse -ds $WEB_DIR/NPCs/NPCs.aspx.ID_333
#./npc_parse -ds $WEB_DIR/NPCs/NPCs.aspx.ID_1
#./npc_parse -d $WEB_DIR/NPCs/NPCs.aspx.ID_*
#./npc_parse -o $DATA_DIR $WEB_DIR/NPCs/NPCs.aspx.ID_*

rm errors.npc.log

if test -f "errors.npc"; then
	cat errors.npc | while read i
	do
		if ! ./npc_parse -o $DATA_DIR $i ; then
			echo $i >> errors.npc.log
		fi
	done
else
	for i in `ls $WEB_DIR/NPCs/NPCs.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./npc_parse -o $DATA_DIR $i ; then
			echo $i >> errors.npc.log
		fi
	done
fi

