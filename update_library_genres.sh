#!/usr/bin/env bash
set -e

CONTAINER_NAME="music_manager"
PROJECT_DIR="/srv/dev-disk-by-uuid-bf30c64b-47b4-4699-b768-f50d51147267/Jacques_Documents/DockerFolder/music-manager"
LOG_FILE="$PROJECT_DIR/config/genre_update.log"

echo "================================================================="
echo " Music Manager — Library 5-Genre Bulk Upgrade"
echo "================================================================="

# Verify container is running
if ! docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q "$CONTAINER_NAME"; then
    echo "[ERROR] Docker container '$CONTAINER_NAME' is NOT running!"
    echo "Please start it with: cd $PROJECT_DIR && docker compose up -d"
    exit 1
fi

# Check if upgrade is already running
if docker exec "$CONTAINER_NAME" pgrep -f "upgrade_genres_cli.py" > /dev/null 2>&1; then
    echo "[!] A genre upgrade is ALREADY RUNNING in the background!"
    echo "[i] View real-time log:  tail -f $LOG_FILE"
    echo "[i] Or check status:     ./check_genre_update.sh"
    exit 0
fi

echo "[*] Launching 5-genre bulk upgrade in background (detached mode)..."
docker exec -d "$CONTAINER_NAME" python3 /app/app/upgrade_genres_cli.py "$@"

sleep 2

if docker exec "$CONTAINER_NAME" pgrep -f "upgrade_genres_cli.py" > /dev/null 2>&1; then
    echo ""
    echo "================================================================="
    echo " [✓] 5-GENRE UPGRADE RUNNING IN BACKGROUND!"
    echo "================================================================="
    echo " -> You can safely DISCONNECT and CLOSE YOUR SSH TERMINAL now."
    echo " -> The process will continue running inside Docker until done."
    echo ""
    echo " Monitoring Options:"
    echo "   1. Quick Status:     ./check_genre_update.sh"
    echo "   2. Stream Live Log:  tail -f $LOG_FILE"
    echo "   3. Web UI Dashboard: http://192.168.178.100:8085"
    echo "================================================================="
elif grep -q "Completed Successfully" "$LOG_FILE" 2>/dev/null; then
    echo ""
    echo "================================================================="
    echo " [✓] Upgrade job finished!"
    echo " Run './check_genre_update.sh' to view summary."
    echo "================================================================="
else
    echo "[ERROR] Process did not stay running. Check recent logs:"
    docker exec "$CONTAINER_NAME" tail -n 20 /config/genre_update.log 2>/dev/null || true
    exit 1
fi
