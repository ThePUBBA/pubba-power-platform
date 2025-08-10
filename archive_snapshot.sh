#!/usr/bin/env bash
set -euo pipefail
DATE="${1:?usage: archive_snapshot.sh YYYY-MM-DD}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/reports/latest"
DST="$ROOT/reports/archive/$DATE"

mkdir -p "$DST"
cp "$SRC"/*.html "$DST"/

if [ ! -f "$ROOT/reports/history.csv" ]; then
  cp "$ROOT/reports/last_run_summary.csv" "$ROOT/reports/history.csv"
else
  tail -n +2 "$ROOT/reports/last_run_summary.csv" >> "$ROOT/reports/history.csv"
fi

echo "✅ Archived charts to $DST and updated reports/history.csv"
