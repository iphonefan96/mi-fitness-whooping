#!/bin/sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
EXTRACTOR="$SCRIPT_DIR/mi_fitness_etl.py"

OUTPUT_DIR=""
SOURCE_DIR=""
EXPECT_OUTPUT=0
EXPECT_SOURCE=0
for ARG in "$@"; do
    if [ "$EXPECT_OUTPUT" -eq 1 ]; then
        OUTPUT_DIR=$ARG
        EXPECT_OUTPUT=0
        continue
    fi
    if [ "$EXPECT_SOURCE" -eq 1 ]; then
        SOURCE_DIR=$ARG
        EXPECT_SOURCE=0
        continue
    fi
    case "$ARG" in
        --output)
            EXPECT_OUTPUT=1
            ;;
        --output=*)
            OUTPUT_DIR=${ARG#--output=}
            ;;
        --source)
            EXPECT_SOURCE=1
            ;;
        --source=*)
            SOURCE_DIR=${ARG#--source=}
            ;;
    esac
done

if [ -z "$SOURCE_DIR" ]; then
    echo "ERROR: --source is required" >&2
    exit 2
fi

if [ -z "$OUTPUT_DIR" ]; then
    echo "ERROR: --output is required" >&2
    exit 2
fi

if [ ! -d "$SOURCE_DIR" ]; then
    echo "SKIPPED: Mi Fitness NAS source unavailable"
    exit 0
fi

mkdir -p "$OUTPUT_DIR"
LOCK_DIR="$OUTPUT_DIR/.mi_fitness_etl.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [ -f "$LOCK_DIR/pid" ]; then
        OLD_PID=$(sed -n '1p' "$LOCK_DIR/pid" 2>/dev/null || true)
        case "$OLD_PID" in
            ''|*[!0-9]*) OLD_PID="" ;;
        esac
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            OLD_COMMAND=$(/bin/ps -p "$OLD_PID" -o command= 2>/dev/null || true)
            case "$OLD_COMMAND" in
                *mi_fitness_etl.py*|*run_mi_fitness_etl.sh*|*run_production_macos.sh*)
                    echo "Mi Fitness ETL is already running (PID $OLD_PID)" >&2
                    exit 3
                    ;;
            esac
        fi
    fi
    # Exact, output-scoped stale lock only; never remove a broad path.
    rm -f "$LOCK_DIR/pid" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || {
        echo "ERROR: cannot clear stale lock: $LOCK_DIR" >&2
        exit 3
    }
    mkdir "$LOCK_DIR" || exit 3
fi

echo "$$" > "$LOCK_DIR/pid"
cleanup() {
    rm -f "$LOCK_DIR/pid" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

LOG_DIR=${MI_FITNESS_LOG_DIR:-"$OUTPUT_DIR/logs"}
mkdir -p "$LOG_DIR"
# Logs are diagnostic only. Keep at most 30 days without touching health data.
find "$LOG_DIR" -type f -name 'mi_fitness_etl-*.log' -mtime +30 -delete 2>/dev/null || true
STAMP=$(date '+%Y%m%d-%H%M%S')
RUN_LOG="$LOG_DIR/mi_fitness_etl-$STAMP.log"
TEMP_LOG="$LOCK_DIR/current.log"

PYTHON_BIN=${MI_FITNESS_PYTHON:-python3}
"$PYTHON_BIN" "$EXTRACTOR" "$@" > "$TEMP_LOG" 2>&1
STATUS=$?
tee -a "$RUN_LOG" < "$TEMP_LOG"
rm -f "$TEMP_LOG"
exit "$STATUS"
