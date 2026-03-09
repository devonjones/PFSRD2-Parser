#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -ne 1 ]; then
	echo "Usage: $0 <equipment_type>"
	echo "  equipment_type: weapon, armor, shield, siege_weapon, vehicle, or equipment"
	exit 1
fi

EQUIPMENT_TYPE=$1

# Pluralize for directory names and error files
# NOTE: When adding a new equipment type, you must add a new case here.
case "$EQUIPMENT_TYPE" in
	weapon)
		PLURAL="Weapons"
		ERROR_SUFFIX="weapons"
		;;
	armor)
		PLURAL="Armor"
		ERROR_SUFFIX="armor"
		;;
	shield)
		PLURAL="Shields"
		ERROR_SUFFIX="shields"
		;;
	siege_weapon)
		PLURAL="SiegeWeapons"
		ERROR_SUFFIX="siege_weapons"
		;;
	vehicle)
		PLURAL="Vehicles"
		ERROR_SUFFIX="vehicles"
		;;
	equipment)
		PLURAL="Equipment"
		ERROR_SUFFIX="equipment"
		;;
	*)
		echo "Error: Invalid equipment type '$EQUIPMENT_TYPE'. Must be weapon, armor, shield, siege_weapon, vehicle, or equipment"
		exit 1
		;;
esac

source "$BIN_DIR/dir.conf"

rm -f "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"

if test -f "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}"; then
	cat "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}" | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! "$BIN_DIR/pf2_equipment_parse" "$EQUIPMENT_TYPE" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/$PLURAL/$PLURAL.aspx.ID_*.html | msort -j -q -l -n 1 -c hybrid`
	do
		if ! "$BIN_DIR/pf2_equipment_parse" "$EQUIPMENT_TYPE" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> "$BIN_DIR/errors.pf2.${ERROR_SUFFIX}.log"
		fi
	done
fi

"$BIN_DIR/copy_schema.sh" equipment
