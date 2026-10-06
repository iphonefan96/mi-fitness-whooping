#!/bin/sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR="/Volumes/home/miFitness"
MOUNT_POINT="/Volumes/home"
EXPECTED_SHARE="//RR@JDS._smb._tcp.local/home"
RUNTIME_ROOT="/Users/rus/Library/Application Support/MiFitnessETL"
OUTPUT_DIR="$RUNTIME_ROOT/data"
LOG_DIR="$RUNTIME_ROOT/logs"
PYTHON_BIN="/opt/homebrew/bin/python3"

log_and_exit() {
    MESSAGE=$1
    STATUS=$2
    /bin/mkdir -p "$LOG_DIR"
    /usr/bin/find "$LOG_DIR" -type f -name 'mi_fitness_etl-*.log' -mtime +30 -delete 2>/dev/null || true
    STAMP=$(/bin/date '+%Y%m%d-%H%M%S')
    /usr/bin/printf '%s\n' "$MESSAGE" | /usr/bin/tee "$LOG_DIR/mi_fitness_etl-$STAMP.log"
    exit "$STATUS"
}

# Require the exact known SMB share at the exact mount point. Never guess home-1.
MOUNT_INFO=$(/sbin/mount | /usr/bin/awk -v point="$MOUNT_POINT" '$3 == point { print; exit }')
case "$MOUNT_INFO" in
    "$EXPECTED_SHARE on $MOUNT_POINT (smbfs,"*) ;;
    *)
        log_and_exit "SKIPPED: Mi Fitness NAS source unavailable" 0
        ;;
esac

if [ ! -d "$SOURCE_DIR/DataBase" ]; then
    log_and_exit "SKIPPED: Mi Fitness NAS source unavailable" 0
fi

if [ ! -x "$PYTHON_BIN" ]; then
    log_and_exit "ERROR: configured Python is unavailable: $PYTHON_BIN" 1
fi

MI_FITNESS_PYTHON="$PYTHON_BIN" \
MI_FITNESS_LOG_DIR="$LOG_DIR" \
exec "$SCRIPT_DIR/run_mi_fitness_etl.sh" \
    --source "$SOURCE_DIR" \
    --output "$OUTPUT_DIR" \
    --overlap-hours 48
