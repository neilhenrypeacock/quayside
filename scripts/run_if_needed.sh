#!/bin/bash
# Run the Quayside pipeline only if today's digest hasn't been produced yet.
# Designed to be called frequently (e.g. every 30 min) so missed runs catch up
# after the Mac wakes from sleep.

# Skip weekends
DAY=$(date +%u)  # 1=Mon ... 7=Sun
if [ "$DAY" -ge 6 ]; then
    exit 0
fi

DATE=$(date +%Y-%m-%d)
DIGEST="/Users/neilpeacock/Projects/quayside/output/digest_${DATE}.html"

if [ -f "$DIGEST" ]; then
    exit 0
fi

cd /Users/neilpeacock/Projects/quayside
/usr/bin/python3 -m quayside
