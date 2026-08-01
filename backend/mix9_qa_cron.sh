#!/bin/bash
# Nightly: refresh cache -> QA -> snapshot -> push. Any QA FAIL aborts the push,
# because a snapshot built on data that failed QA is worse than a stale one.
set -uo pipefail
cd "$(dirname "$0")"
LOG=/tmp/mix9_qa_cron.log
{
  echo "=== $(date) ==="
  python3 _qa_system.py --fast
  if [ $? -ne 0 ]; then echo "QA FAILED — aborting snapshot push"; exit 1; fi
  ./mix9_push.sh
  echo "done"
} >> "$LOG" 2>&1
