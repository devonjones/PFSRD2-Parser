#!/bin/bash

source dir.conf

rm errors.pf2.condition.log

if test -f "errors.pf2.condition"; then
	cat errors.pf2.condition | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_condition_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.condition.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Conditions/Conditions.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_condition_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.condition.log
		fi
	done
fi

