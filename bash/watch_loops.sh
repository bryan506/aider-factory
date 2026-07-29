#!/bin/bash
# watchdog.sh
# Monitors a log file for redundant volume
# and kills the target process if an infinite loop is detected.

LOG_FILE=$1
TARGET_PID=$2

# if [ -z "$LOG_FILE" ] || [ -z "$TARGET_PID" ]; then
#     echo "Usage: ./watchdog.sh <log_file> <target_pid>"
#     exit 1
# fi

# # Poll every 5 seconds while the target process is running
# while kill -0 $TARGET_PID 2>/dev/null; do
#     if [ -f "$LOG_FILE" ]; then

#         # Count the total number of non-empty lines we are evaluating
#         LINE_COUNT=$(tail -n 400 "$LOG_FILE" | grep -c '[^[:space:]]')

#         # Only evaluate if we have at least 100 lines of output to look at
#         if [ "$LINE_COUNT" -ge 100 ]; then
#             # Count the number of UNIQUE lines in this window
#             UNIQUE_LINES=$(tail -n 400 "$LOG_FILE" | grep -v '^[[:space:]]*$' | sort | uniq | wc -l)

#             # Calculate the volume of redundant (repeating) lines
#             REDUNDANT_LINES=$(( LINE_COUNT - UNIQUE_LINES ))

#             # Dynamic threshold: 75% of the recent non-empty lines must be redundant
#             # If line_count is exactly 400, threshold is 300 redundant lines.
#             THRESHOLD=$(( LINE_COUNT * 300 / 400 ))

#             if [ "$REDUNDANT_LINES" -ge "$THRESHOLD" ]; then
#                 echo ""
#                 echo "🚨 [WATCHDOG] Detected infinite loop! $REDUNDANT_LINES out of $LINE_COUNT recent lines are redundant repetitions."
#                 echo "Killing Aider (PID $TARGET_PID) to prevent deadlock."
#                 kill -9 $TARGET_PID
#                 exit 0
#             fi
#         fi
#     fi
#     sleep 5
# done
