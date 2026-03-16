#!/bin/bash
# Run the Quayside pipeline on weekdays.
#
# Behaviour:
#   - If today's digest doesn't exist yet → full run (scrape everything)
#   - If digest exists AND current hour is 09–17 → update run (ETag-aware
#     re-check; only re-scrapes ports whose source file has changed)
#   - Outside trading hours or weekends → exit silently
#
# Designed to be called every 30 min via launchd so missed morning runs
# catch up after the Mac wakes from sleep, and intraday PDF updates are
# picked up automatically throughout the trading day.

# Skip weekends
DAY=$(date +%u)  # 1=Mon ... 7=Sun
if [ "$DAY" -ge 6 ]; then
    exit 0
fi

DATE=$(date +%Y-%m-%d)
HOUR=$(date +%H)  # 00–23
DIGEST="/Users/neilpeacock/Projects/quayside/output/digest_${DATE}.html"

cd /Users/neilpeacock/Projects/quayside

if [ ! -f "$DIGEST" ]; then
    # No digest yet — full pipeline run
    /usr/bin/python3 -m quayside
elif [ "$HOUR" -ge 9 ] && [ "$HOUR" -le 17 ]; then
    # Digest exists but we're in trading hours — ETag update check
    /usr/bin/python3 -m quayside --update
fi
