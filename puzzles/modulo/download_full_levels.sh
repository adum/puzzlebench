#!/usr/bin/env bash
set -euo pipefail

START_LEVEL=1
END_LEVEL=100
DEST_DIR="levels"

echo "Generating Modulo levels ${START_LEVEL}-${END_LEVEL} into ${DEST_DIR}"
python3 generate_levels.py --start "${START_LEVEL}" --end "${END_LEVEL}" --output-dir "${DEST_DIR}"
echo "Done."

