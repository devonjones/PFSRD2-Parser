#!/bin/bash

if [ $# -ne 1 ]; then
	echo "Usage: $0 <equipment_type>"
	echo "  equipment_type: weapon, armor, or shield"
	exit 1
fi

EQUIPMENT_TYPE=$1

# Pluralize for directory names and error files
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
	*)
		echo "Error: Invalid equipment type '$EQUIPMENT_TYPE'. Must be weapon, armor, or shield"
		exit 1
		;;
esac

source dir.conf

rm -f errors.pf2.${ERROR_SUFFIX}.log

if test -f "errors.pf2.${ERROR_SUFFIX}"; then
	cat errors.pf2.${ERROR_SUFFIX} | while read i
	do
		if [[ "$i" == "done" ]]; then
			exit
		fi
		if ! ./pf2_equipment_parse --type "$EQUIPMENT_TYPE" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.${ERROR_SUFFIX}.log
		fi
	done
else
	for i in `ls $PF2_WEB_DIR/$PLURAL/$PLURAL.aspx.ID_*.html | msort -j -q -l -n 1 -c hybrid`
	do
		if ! ./pf2_equipment_parse --type "$EQUIPMENT_TYPE" -o "$PF2_DATA_DIR" "$i" ; then
			echo "$i" >> errors.pf2.${ERROR_SUFFIX}.log
		fi
	done
fi
