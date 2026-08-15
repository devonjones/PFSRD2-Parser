#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -ne 1 ]; then
	echo "Usage: $0 <affliction_type>"
	echo "  affliction_type: curse or disease"
	echo ""
	echo "ItemCurses is deliberately not parsed: all 15 of its distinct entries"
	echo "resolve to Curses.aspx IDs the curse run already covers, with"
	echo "byte-identical bodies."
	exit 1
fi

AFFLICTION_TYPE=$1

case "$AFFLICTION_TYPE" in
	curse)
		PLURAL="Curses"
		ERROR_SUFFIX="curses"
		;;
	disease)
		PLURAL="Diseases"
		ERROR_SUFFIX="diseases"
		;;
	*)
		echo "Error: Invalid affliction type '$AFFLICTION_TYPE'. Must be curse or disease"
		exit 1
		;;
esac

source "$BIN_DIR/dir.conf"

if [ ! -d "$PF2_WEB_DIR/$PLURAL" ]; then
	echo "missing source directory: $PF2_WEB_DIR/$PLURAL" >&2
	exit 1
fi

rm -f "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"

"$BIN_DIR/copy_schema.sh" affliction

if test -f "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}"; then
	cat "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}" | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! "$BIN_DIR/pf2_affliction_parse" -o "$PF2_DATA_DIR" "$AFFLICTION_TYPE" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"
		fi
	done
else
	for i in `ls "$PF2_WEB_DIR"/$PLURAL/$PLURAL.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! "$BIN_DIR/pf2_affliction_parse" -o "$PF2_DATA_DIR" "$AFFLICTION_TYPE" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"
		fi
	done
fi
