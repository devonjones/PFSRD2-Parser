#!/bin/bash

source dir.conf

rm errors.trait.log

if test -f "errors.trait"; then
	cat errors.trait | while read i
	do
		if ! ./trait_parse -o $DATA_DIR $i ; then
			echo $i >> errors.trait.log
		fi
	done
else
	for i in `ls $WEB_DIR/Traits/Traits.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./trait_parse -o $DATA_DIR $i ; then
			echo $i >> errors.trait.log
		fi
	done
fi

