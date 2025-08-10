cd "$(dirname "$0")"
source .venv/bin/activate || true

YDAY=$(date -u -v-1d +%F)   # macOS/BSD UTC yesterday
NODES="MPBBAC,MPBNCA,MPBPGE"

python run_from_csv_date.py --date "$YDAY" \
  --nodes "$NODES" \
  --capacity-mwh 10 --efficiency-rt 0.85 \
  --charge-lmp 30 --discharge-lmp 60 --deadband 2 \
  --latest-only --no-auto-open

./archive_snapshot.sh "$YDAY"
