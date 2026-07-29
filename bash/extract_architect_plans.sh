#!/bin/bash
# extract_plans.sh
# Usage: ./extract_plans.sh <logfile> > extracted_plans.md

LOG_FILE=$1

if [ -z "$LOG_FILE" ]; then
    echo "Error: No log file provided."
    echo "Usage: ./extract_architect_plans.sh <logfile> > extracted_architect_plans.md"
    exit 1
fi

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Log file '$LOG_FILE' not found."
    exit 1
fi

awk '
  # 1. Start capturing when a new Task begins
  /INFO: 🚀 STARTING TASK/ {
    capture = 1
    print "\n========================================================================="
    print $0
    print "=========================================================================\n"
    next
  }
  
  # 2. Stop capturing right before the Editor writes code diffs, 
  # or if the task succeeds/fails without outputting diffs
  /► \*\*ANSWER\*\*/ || /INFO: ✅ TASK SUCCESS/ || /INFO: ❌ TASK FAILED/ {
    if (capture == 1) {
      print "\n[END OF ARCHITECT/EDITOR REASONING BLOCK]\n"
      capture = 0
    }
  }

  # 3. Print the line if capturing is active
  capture == 1 { print $0 }
' "$LOG_FILE"

