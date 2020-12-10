#!/bin/bash

source dir.conf

rm creatures.validation.new
touch creatures.validation.new

if test -f "creatures.validation"; then
    cat creatures.validation | while read i
    do
        echo $i
        OUTPUT=$(jsonschema -i $i ../pfsrd2/creature.schema.json 2>&1)
        if [ ! -z "$OUTPUT" ]
        then
            echo $OUTPUT
            echo $i >> creatures.validation.new
        fi
    done
else
    for i in `find $DATA_DIR -type f -name "*.json"`
    do
        echo $i
        OUTPUT=$(jsonschema -i $i ../pfsrd2/creature.schema.json 2>&1)
        if [ ! -z "$OUTPUT" ]
        then
            echo $OUTPUT
            echo $i >> creatures.validation.new
        fi
    done
fi

