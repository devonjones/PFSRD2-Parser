#!/bin/bash

source dir.conf
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_333
#./creature_parse -ds $WEB_DIR/Monsters/Monsters.aspx.ID_1
#./creature_parse -d $WEB_DIR/Monsters/Monsters.aspx.ID_*
#./creature_parse -o $DATA_DIR $WEB_DIR/Monsters/Monsters.aspx.ID_*

rm errors.new
touch errors.new

if test -f "errors"; then
	cat errors | while read i
	do
		if ! ./creature_parse -o $DATA_DIR $i ; then
			echo $i >> errors.new
		fi
	done
else
	for i in `ls $WEB_DIR/Monsters/Monsters.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./creature_parse -o $DATA_DIR $i ; then
			echo $i >> errors.new
		fi
	done
fi

#mv errors.new errors

