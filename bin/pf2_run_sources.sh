#!/bin/bash

source dir.conf

rm errors.pf2.source.log

if test -f "errors.pf2.source"; then
	cat errors.pf2.source | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_source_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.source.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Sources/Sources.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_source_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.source.log
		fi
	done
fi 