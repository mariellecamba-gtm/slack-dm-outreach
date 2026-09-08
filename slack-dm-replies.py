#!/usr/bin/env python3
"""
Check who replied to your DMs. Read this before you send another batch.

  source .slack-env
  python3 slack-dm-replies.py                        # reads slack-dm-sent.csv
  SENTLOG=other-campaign.csv python3 slack-dm-replies.py

Env:
  SENTLOG=slack-dm-sent.csv   the log written by slack-dm-send.py
  OUT=replies.csv             write the replies to a CSV as well as stdout

Costs one API call per row, ~0.3s each, so 300 sends takes about 90 seconds.
"""

import csv, os, sys, time
import requests

TOKEN   = os.environ.get("SLACK_TOKEN", "").strip()
COOKIE  = os.environ.get("SLACK_COOKIE", "").strip()
SENTLOG = os.environ.get("SENTLOG", "slack-dm-sent.csv")
OUT     = os.environ.get("OUT", "").strip()

if not TOKEN:
    sys.exit("No SLACK_TOKEN. Run:  source .slack-env")
if COOKIE and not COOKIE.startswith("d="):
    COOKIE = "d=" + COOKIE
if not os.path.exists(SENTLOG):
    sys.exit(f"{SENTLOG} not found - nothing has been sent yet.")

S = requests.Session()
S.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
})
if COOKIE:
    S.headers["Cookie"] = COOKIE

auth = S.post("https://slack.com/api/auth.test", timeout=30).json()
if not auth.get("ok"):
    sys.exit(f"auth failed: {auth.get('error')} - refresh your token/cookie.")
me = auth["user_id"]

rows = list(csv.DictReader(open(SENTLOG, encoding="utf-8")))
replied, none, err = [], 0, 0

for i, r in enumerate(rows, 1):
    d = S.post("https://slack.com/api/conversations.history",
               data={"channel": r["dm_channel"], "limit": 20}, timeout=30).json()
    if not d.get("ok"):
        err += 1
    else:
        theirs = [m for m in d.get("messages", []) if m.get("user") and m["user"] != me]
        if theirs:
            replied.append({
                "slack_id": r.get("slack_id", ""),
                "real_name": r.get("real_name", ""),
                "sent_when": r.get("when", ""),
                "reply": theirs[-1].get("text", "").replace("\n", " ")[:300],
            })
        else:
            none += 1
    if i % 200 == 0:
        print(f"  checked {i}/{len(rows)}", file=sys.stderr)
    time.sleep(0.3)

checked = max(len(rows) - err, 1)
print(f"\n=== {SENTLOG} ({auth.get('team')}) ===")
print(f"sent {len(rows)} | replied {len(replied)} | no reply {none} | errors {err}")
print(f"reply rate: {len(replied) / checked * 100:.2f}%")
for r in replied:
    print(f"  * {r['real_name']}: {r['reply']}")

if OUT and replied:
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(replied[0]))
        w.writeheader(); w.writerows(replied)
    print(f"\nWrote {len(replied)} replies -> {OUT}")
