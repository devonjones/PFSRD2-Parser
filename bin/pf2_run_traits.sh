#!/bin/bash

source dir.conf

rm errors.pf2.trait.log

if test -f "errors.pf2.trait"; then
	cat errors.pf2.trait | while read i
	do
		if ! ./pf2_trait_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.trait.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/Traits/Traits.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_trait_parse -o $PF2_DATA_DIR $i ; then
			echo $i >> errors.pf2.trait.log
		fi
	done
fi

