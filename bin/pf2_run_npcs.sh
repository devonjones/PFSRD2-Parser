#!/bin/bash

source dir.conf
#./npc_parse -ds $WEB_DIR/NPCs/NPCs.aspx.ID_333
#./npc_parse -ds $WEB_DIR/NPCs/NPCs.aspx.ID_1
#./npc_parse -d $WEB_DIR/NPCs/NPCs.aspx.ID_*
#./npc_parse -o $DATA_DIR $WEB_DIR/NPCs/NPCs.aspx.ID_*

rm errors.pf2.npc.log

if test -f "errors.pf2.npc"; then
	cat errors.npc | while read i
	do
		if ! ./pf2_npc_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.npc.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/NPCs/NPCs.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_npc_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.fp2.npc.log
		fi
	done
fi

