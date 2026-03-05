#!/bin/bash

source dir.conf

./pf2_license_parse -o $PF2_DATA_DIR $PF2_WEB_DIR/Licenses.aspx.html

cp $PF2_DATA_DIR/license/* ~/.pfsrd2

