#!/bin/bash

source dir.conf

rm errors.pf2.feat.log

./copy_schema.sh feat

if test -f "errors.pf2.feat"; then
	cat errors.pf2.feat | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_feat_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.feat.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Feats/Feats.aspx.ID_* | grep -v '\.ArchLevel' | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_feat_parse -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.feat.log
		fi
	done
fi
