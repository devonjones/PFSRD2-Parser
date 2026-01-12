#!/bin/bash

source dir.conf

rm errors.pf2.skill.log

if test -f "errors.pf2.skill"; then
	cat errors.pf2.skill | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_skill_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.skill.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Skills/Skills.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_skill_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.skill.log
		fi
	done
fi

