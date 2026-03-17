#!/bin/bash
# Run the Quayside pipeline on weekdays.
#
# Schedule logic (launchd fires every 10 minutes):
#
#   - Weekends → exit silently
#   - Outside 07:00–17:00 → exit silently
#   - No digest today yet → full pipeline run (catches up after sleep/wake)
#   - Digest exists:
#       · If last_changed_at was < 60 min ago → ETag update check (fast mode:
#         catches any intraday PDF updates within one 10-min slot)
#       · Else if ≥ 60 min since last_attempted_at → ETag update check (hourly pulse)
#       · Otherwise → skip this tick
#
# State files (written after each attempted run):
#   data/last_changed.txt   — ISO timestamp of last run that returned new data
#   data/last_attempted.txt — ISO timestamp of last ETag update attempt
#
# update_run() exit codes: 0=new data, 1=errors, 2=no change

# Skip weekends
DAY=$(date +%u)  # 1=Mon ... 7=Sun
if [ "$DAY" -ge 6 ]; then
    exit 0
fi

HOUR=$(date +%H)  # 00–23
if [ "$HOUR" -lt 7 ] || [ "$HOUR" -ge 17 ]; then
    exit 0
fi

DATE=$(date +%Y-%m-%d)
DIGEST="/Users/neilpeacock/Projects/quayside/output/digest_${DATE}.html"
LAST_CHANGED="/Users/neilpeacock/Projects/quayside/data/last_changed.txt"
LAST_ATTEMPTED="/Users/neilpeacock/Projects/quayside/data/last_attempted.txt"

cd /Users/neilpeacock/Projects/quayside

now_epoch=$(date +%s)

# Helper: seconds since a timestamp file was written (or large number if missing)
seconds_since() {
    local file="$1"
    if [ -f "$file" ]; then
        local ts
        ts=$(cat "$file")
        local file_epoch
        file_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${ts%%.*}" +%s 2>/dev/null || echo 0)
        echo $(( now_epoch - file_epoch ))
    else
        echo 999999
    fi
}

if [ ! -f "$DIGEST" ]; then
    # No digest yet today — full pipeline run
    /usr/bin/python3 -m quayside
    exit $?
fi

# Digest exists — decide whether to do an ETag update check
secs_since_changed=$(seconds_since "$LAST_CHANGED")
secs_since_attempted=$(seconds_since "$LAST_ATTEMPTED")

should_run=0
if [ "$secs_since_changed" -lt 3600 ]; then
    # New data appeared recently — stay in 10-min fast mode
    should_run=1
elif [ "$secs_since_attempted" -ge 3600 ]; then
    # Been an hour since we last checked — hourly pulse
    should_run=1
fi

if [ "$should_run" -eq 0 ]; then
    exit 0
fi

# Record attempt time
python3 -c "from datetime import datetime; print(datetime.now().isoformat())" > "$LAST_ATTEMPTED"

/usr/bin/python3 -m quayside --update
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    # New data found — update last_changed timestamp
    python3 -c "from datetime import datetime; print(datetime.now().isoformat())" > "$LAST_CHANGED"
fi

exit $EXIT_CODE
