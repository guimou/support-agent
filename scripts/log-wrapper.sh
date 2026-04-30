#!/bin/sh
# Wraps a command, teeing its combined stdout/stderr to a log file.
# Truncates the log file on start so each container restart gets a clean log.
#
# Usage: log-wrapper.sh /path/to/logfile command [args...]

LOGFILE="$1"; shift
: > "$LOGFILE"
exec "$@" 2>&1 | tee -a "$LOGFILE"
