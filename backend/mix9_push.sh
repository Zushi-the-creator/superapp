#!/bin/bash
# Nightly MIX9 snapshot: compute locally (needs ~4.5GB; the 1GB Fly machine
# cannot), then push to prod. Install with:
#   crontab -e   ->   30 18 * * 1-5 /Users/igalozik/PycharmProjects/superapp/backend/mix9_push.sh
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/mix9_push.log
{
  echo "=== $(date) ==="
  EQ=$(curl -s --max-time 60 https://superapp-ke5bhg.fly.dev/api/v2/portfolio \
       | python3 -c "import sys,json;print(json.load(sys.stdin)['summary']['total_value'])" 2>/dev/null || echo 19511)
  HOLD=$(curl -s --max-time 60 https://superapp-ke5bhg.fly.dev/api/v2/portfolio \
       | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(json.dumps({p['ticker']:round(float(p.get('current_value') or 0),2)
                  for p in d.get('positions',[]) if float(p.get('current_value') or 0)>0}))" 2>/dev/null || echo '{}')
  echo "equity=$EQ holdings=$HOLD"
  python3 mix9_snapshot.py "$EQ" "$HOLD"
  python3 -c "import json,mix9_snapshot as s;open('/tmp/mix9_snap.json','w').write(json.dumps(s.load()))"
  curl -s -X POST --max-time 120 -H "Content-Type: application/json" \
       -d @/tmp/mix9_snap.json https://superapp-ke5bhg.fly.dev/api/v2/mix9/snapshot
  echo
} >> "$LOG" 2>&1
