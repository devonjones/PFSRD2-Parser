#!/bin/bash
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN_DIR/dir.conf"

"$BIN_DIR/pf2_license_parse" -o "$PF2_DATA_DIR" "$PF2_WEB_DIR/Licenses.aspx.html"

cp "$PF2_DATA_DIR/license/"* ~/.pfsrd2
