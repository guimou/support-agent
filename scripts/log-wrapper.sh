#!/bin/sh
# Wraps a command, teeing its combined stdout/stderr to a log file.
# Truncates the log file on start so each container restart gets a clean log.
# Uses a FIFO so exec replaces this shell — the wrapped command becomes PID 1
# and receives container stop signals (SIGTERM/SIGINT) directly.
#
# Usage: log-wrapper.sh /path/to/logfile command [args...]

LOGFILE="$1"; shift
: > "$LOGFILE"

FIFO=$(mktemp -u /tmp/logfifo.XXXXXX)
mkfifo "$FIFO"
tee -a "$LOGFILE" < "$FIFO" &
exec "$@" > "$FIFO" 2>&1
