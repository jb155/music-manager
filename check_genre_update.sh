#!/usr/bin/env bash
CONTAINER_NAME="music_manager"
PROJECT_DIR="/srv/dev-disk-by-uuid-bf30c64b-47b4-4699-b768-f50d51147267/Jacques_Documents/DockerFolder/music-manager"
PROGRESS_FILE="$PROJECT_DIR/config/genre_update_progress.json"
LOG_FILE="$PROJECT_DIR/config/genre_update.log"

echo "================================================================="
echo " Music Manager — 5-Genre Upgrade Status"
echo "================================================================="

if docker exec "$CONTAINER_NAME" pgrep -f "upgrade_genres_cli.py" > /dev/null 2>&1; then
    echo "  Status: [RUNNING IN BACKGROUND]"
else
    echo "  Status: [IDLE / NOT CURRENTLY RUNNING]"
fi

if [ -f "$PROGRESS_FILE" ]; then
    echo ""
    echo "Current Progress Summary:"
    python3 -c "
import json
try:
    with open('$PROGRESS_FILE') as f:
        d = json.load(f)
    print(f\"  Progress: {d.get('current', 0)} / {d.get('total', 0)} artists ({d.get('percent', 0.0)}%)\")
    print(f\"  Tracks Updated: {d.get('tracks_updated', 0)} | Files Tagged: {d.get('files_updated', 0)}\")
    print(f\"  Current Artist: {d.get('current_artist', 'None')}\")
    print(f\"  Current Genre:  {d.get('current_genre', 'None')}\")
    print(f\"  Elapsed Time:   {int(d.get('elapsed_sec', 0))}s\")
except Exception as e:
    print('  Could not parse progress file:', e)
" 2>/dev/null || cat "$PROGRESS_FILE"
fi

echo ""
echo "Recent Activity (Last 10 lines from log):"
echo "-----------------------------------------------------------------"
if [ -f "$LOG_FILE" ]; then
    tail -n 10 "$LOG_FILE"
else
    echo "No log file found at $LOG_FILE yet."
fi
echo "================================================================="
