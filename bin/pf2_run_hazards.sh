#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"

rm -f "$BIN_DIR/errors.pf2.hazard.log"

"$BIN_DIR/copy_schema.sh" hazard

if test -f "$BIN_DIR/errors.pf2.hazard"; then
	cat "$BIN_DIR/errors.pf2.hazard" | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! "$BIN_DIR/pf2_hazard_parse" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.hazard.log"
		fi
	done
else
	# Hazards live in two directories. A missing one would otherwise yield a
	# partial run with an empty error log, which reads exactly like success.
	for d in Hazards WeatherHazards; do
		if [ ! -d "$PF2_WEB_DIR/$d" ]; then
			echo "missing source directory: $PF2_WEB_DIR/$d" >&2
			exit 1
		fi
	done
	for i in `ls "$PF2_WEB_DIR"/Hazards/Hazards.aspx.ID_* "$PF2_WEB_DIR"/WeatherHazards/WeatherHazards.aspx.ID_* | msort -j -q -l -n 1 -c hybrid`
	do
		if ! "$BIN_DIR/pf2_hazard_parse" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.hazard.log"
		fi
	done
fi
