#!/usr/bin/env bash
set -euo pipefail

CSV="${1:-Plays20260103.csv}"
OUT="${2:-natak}"

python3 generator.py "$CSV" "$OUT"
echo "Built site into $OUT/"
