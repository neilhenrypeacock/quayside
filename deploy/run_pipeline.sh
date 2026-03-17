#!/bin/bash
# Run the Quayside pipeline on the server (Linux/systemd version of run_if_needed.sh).
#
# Schedule logic (timer fires every 10 minutes):
#
#   - Weekends → exit silently
#   - Outside 07:00–17:00 → exit silently
#   - No digest today yet → full pipeline run
#   - Digest exists:
#       · If last_changed_at was < 60 min ago → ETag update check (fast mode)
#       · Else if ≥ 60 min since last_attempted_at → ETag update check (hourly pulse)
#       · Otherwise → skip this tick

APP=/home/quayside/app
PYTHON=$APP/venv/bin/python

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
DIGEST="$APP/output/digest_${DATE}.html"
LAST_CHANGED="$APP/data/last_changed.txt"
LAST_ATTEMPTED="$APP/data/last_attempted.txt"

cd "$APP"

now_epoch=$(date +%s)

# Helper: seconds since a timestamp file was written (or large number if missing)
seconds_since() {
    local file="$1"
    if [ -f "$file" ]; then
        local ts
        ts=$(cat "$file")
        local file_epoch
        file_epoch=$(date -d "${ts%%.*}" +%s 2>/dev/null || echo 0)
        echo $(( now_epoch - file_epoch ))
    else
        echo 999999
    fi
}

if [ ! -f "$DIGEST" ]; then
    # No digest yet today — full pipeline run
    $PYTHON -m quayside
    exit $?
fi

# Digest exists — decide whether to do an ETag update check
secs_since_changed=$(seconds_since "$LAST_CHANGED")
secs_since_attempted=$(seconds_since "$LAST_ATTEMPTED")

should_run=0
if [ "$secs_since_changed" -lt 3600 ]; then
    should_run=1
elif [ "$secs_since_attempted" -ge 3600 ]; then
    should_run=1
fi

if [ "$should_run" -eq 0 ]; then
    exit 0
fi

$PYTHON -c "from datetime import datetime; print(datetime.now().isoformat())" > "$LAST_ATTEMPTED"

$PYTHON -m quayside --update
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    $PYTHON -c "from datetime import datetime; print(datetime.now().isoformat())" > "$LAST_CHANGED"
fi

exit $EXIT_CODE
