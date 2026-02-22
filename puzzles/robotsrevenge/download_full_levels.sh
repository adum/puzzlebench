#!/usr/bin/env bash
set -euo pipefail

count="0"
if [[ -d levels ]]; then
  count="$(find levels -maxdepth 1 -type f -name '*.level' | wc -l | tr -d ' ')"
fi

echo "Robot's Revenge levels are already included in this folder."
echo "Found ${count} level files in levels/."
