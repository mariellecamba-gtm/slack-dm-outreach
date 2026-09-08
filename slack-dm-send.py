#!/usr/bin/env python3
"""
DM Slack members from a scraped CSV, personalised on first name.

DRY RUN IS THE DEFAULT. Nothing is sent unless you pass SEND=1 explicitly.

  source .slack-env
  python3 slack-dm-send.py                     # dry run -> slack-dm-preview.txt
  SEND=1 MAX=25 python3 slack-dm-send.py       # actually send, capped at 25

Env:
  CSV=slack-members.csv       input from slack-member-scrape.py
  MSG=message.txt             template, must contain {first_name}
  SENTLOG=slack-dm-sent.csv   append-only log; makes every run resumable
  MAX=25                      hard cap on sends this run (default 25)
  MIN_DELAY=25 MAX_DELAY=35   random seconds between sends (avg 30)
  TITLE_MATCH='founder|ceo|head of growth'    only DM matching titles (regex)
  TITLE_EXCLUDE='fractional|consultant'       drop matching titles (regex)
  LOCAL_HOURS=9-17            only DM people whose local time is in this window
  SEND_WEEKENDS=1             allow weekend sends (default: off when LOCAL_HOURS set)
  SKIP_ADMINS=0               allow DMing workspace admins (default: skip them)
  SKIP_NAMES='Ada Lovelace,Alan Turing'       extra one-off exclusions

Files it reads if present (all gitignored, all yours):
  blocklist.txt        one name per line, '#' for comments. Never DM these people.
  name-overrides.json  {"U0123456789": "Paige"} for profiles the splitter can't parse.

Every send is appended to SENTLOG and never repeated on a later run, so you can
stop with Ctrl-C at any point and pick up where you left off.
"""

import os, sys, csv, re, time, random, json
import requests

TOKEN   = os.environ.get("SLACK_TOKEN", "").strip()
COOKIE  = os.environ.get("SLACK_COOKIE", "").strip()
TEAM    = os.environ.get("SLACK_TEAM", "").strip()
CSV_IN  = os.environ.get("CSV", "slack-members.csv")
MSG_F   = os.environ.get("MSG", "message.txt")
SENTLOG = os.environ.get("SENTLOG", "slack-dm-sent.csv")
PREVIEW = os.environ.get("PREVIEW", "slack-dm-preview.txt")
SEND    = os.environ.get("SEND", "0") == "1"
MAX     = int(os.environ.get("MAX", "25"))
MIN_D   = int(os.environ.get("MIN_DELAY", "25"))
MAX_D   = int(os.environ.get("MAX_DELAY", "35"))
TITLE_M = os.environ.get("TITLE_MATCH", "").strip()
TITLE_X = os.environ.get("TITLE_EXCLUDE", "").strip()
HOURS   = os.environ.get("LOCAL_HOURS", "").strip()
WEEKEND = os.environ.get("SEND_WEEKENDS", "0") == "1"
SKIP_ADMINS = os.environ.get("SKIP_ADMINS", "1") == "1"

# --- Who never gets a DM -----------------------------------------------------
# Matched loosely on real name / display name / handle, letters only, so
# "ada.lovelace", "Ada Lovelace" and "adalovelace" all hit the same entry.
SKIP_NAMES = [n.strip().lower() for n in os.environ.get("SKIP_NAMES", "").split(",")
              if n.strip()]
if os.path.exists("blocklist.txt"):
    with open("blocklist.txt", encoding="utf-8") as f:
        SKIP_NAMES += [ln.strip().lower() for ln in f
                       if ln.strip() and not ln.startswith("#")]

# Hand-fixes for profiles the first-name splitter can't parse (run-together
# names, no space). Keyed on slack_id so a fix can't misfire on someone else.
NAME_OVERRIDE = {}
if os.path.exists("name-overrides.json"):
    NAME_OVERRIDE = json.load(open("name-overrides.json", encoding="utf-8"))

# A dry run touches no API, so it needs no credentials. Only a real send does.
if SEND and not TOKEN:
    sys.exit("No SLACK_TOKEN. Run:  source .slack-env")
if COOKIE and not COOKIE.startswith("d="):
    COOKIE = "d=" + COOKIE

HOUR_FROM = HOUR_TO = None
if HOURS:
    m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", HOURS)
    if not m:
        sys.exit(f"LOCAL_HOURS must look like '9-17', got {HOURS!r}")
    HOUR_FROM, HOUR_TO = int(m.group(1)), int(m.group(2))

S = requests.Session()
S.headers["Authorization"] = f"Bearer {TOKEN}"
S.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
if COOKIE:
    S.headers["Cookie"] = COOKIE


def call(method, **params):
    if TEAM:
        params.setdefault("team_id", TEAM)
    r = S.post(f"https://slack.com/api/{method}", data=params, timeout=30)
    if r.status_code == 429:
        return {"ok": False, "error": "ratelimited",
                "retry_after": int(r.headers.get("Retry-After", 60))}
    return r.json()


def letters(*vals):
    return re.sub(r"[^a-z]", "", "".join(v or "" for v in vals).lower())


def first_name_for(row):
    """Best-effort first name. Returns '' if we can't get a clean one.

    A wrong first name is worse than no DM, so anything that doesn't look like
    a human given name (handles, emoji, all-caps org names, single letters)
    is rejected and the person is skipped rather than guessed at.
    """
    if row.get("slack_id") in NAME_OVERRIDE:
        return NAME_OVERRIDE[row["slack_id"]]
    for cand in (row.get("first_name", ""),
                 (row.get("real_name", "") or "").split(" ")[0],
                 (row.get("display_name", "") or "").split(" ")[0]):
        n = (cand or "").strip().strip(",.|-")
        if (len(n) >= 2 and re.fullmatch(r"[A-Za-z][A-Za-z'\-]+", n)
                and not n.isupper()):
            return n[0].upper() + n[1:]
    return ""


def in_working_hours(row):
    """True if it's a decent time where this person is. Unknown tz -> False."""
    if HOUR_FROM is None:
        return True
    try:
        offset = int(row.get("tz_offset") or "")
    except ValueError:
        return False
    local = time.gmtime(time.time() + offset)
    if not WEEKEND and local.tm_wday >= 5:
        return False
    return HOUR_FROM <= local.tm_hour < HOUR_TO


def main():
    if not os.path.exists(MSG_F):
        sys.exit(f"{MSG_F} not found. Copy message.example.txt to {MSG_F} and write your own.")
    template = open(MSG_F, encoding="utf-8").read().rstrip() + "\n"
    if "{first_name}" not in template:
        sys.exit(f"{MSG_F} has no {{first_name}} placeholder.")

    already = set()
    if os.path.exists(SENTLOG):
        with open(SENTLOG, encoding="utf-8") as f:
            already = {r["slack_id"] for r in csv.DictReader(f)}

    me = ""
    if SEND:
        auth = call("auth.test")
        if not auth.get("ok"):
            sys.exit(f"auth.test failed: {auth.get('error')} - refresh your token/cookie.")
        me = auth.get("user_id", "")
        print(f"Authenticated as {auth.get('user')} ({me}) in {auth.get('team')}",
              file=sys.stderr)

    if not os.path.exists(CSV_IN):
        sys.exit(f"{CSV_IN} not found - run slack-member-scrape.py first.")
    with open(CSV_IN, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    queue = []
    skipped = {"already": 0, "no_name": 0, "title": 0, "self": 0,
               "blocked": 0, "admin": 0, "hours": 0}
    for r in rows:
        uid = r.get("slack_id", "")
        if not uid or uid == me:
            skipped["self"] += 1; continue
        if uid in already:
            skipped["already"] += 1; continue
        if SKIP_ADMINS and r.get("is_admin") == "True":
            skipped["admin"] += 1; continue
        who = letters(r.get("real_name"), r.get("display_name"), r.get("handle"))
        if any(letters(n) and letters(n) in who for n in SKIP_NAMES):
            skipped["blocked"] += 1; continue
        title = r.get("title", "")
        if TITLE_X and re.search(TITLE_X, title, re.I):
            skipped["title"] += 1; continue
        if TITLE_M and not re.search(TITLE_M, title, re.I):
            skipped["title"] += 1; continue
        if not in_working_hours(r):
            skipped["hours"] += 1; continue
        fn = first_name_for(r)
        if not fn:
            skipped["no_name"] += 1; continue
        queue.append((uid, fn, r))

    print(f"\n{len(rows)} in CSV -> {len(queue)} eligible", file=sys.stderr)
    print(f"  skipped: {skipped['already']} already DM'd, {skipped['no_name']} no usable "
          f"first name, {skipped['title']} title filter, {skipped['blocked']} blocklisted, "
          f"{skipped['admin']} admins, {skipped['hours']} outside working hours",
          file=sys.stderr)

    batch = queue[:MAX]

    if not SEND:
        with open(PREVIEW, "w", encoding="utf-8") as f:
            f.write(f"DRY RUN - nothing was sent.\n"
                    f"{len(queue)} eligible, showing the first {len(batch)} (MAX={MAX}).\n"
                    f"{'='*70}\n\n")
            for uid, fn, r in batch:
                f.write(f"--- TO: {r.get('real_name','?')} ({uid})  "
                        f"title: {r.get('title','') or '(none)'}\n")
                f.write(template.format(first_name=fn))
                f.write("\n" + "-"*70 + "\n\n")
        est = len(batch) * (MIN_D + MAX_D) / 2 / 60
        print(f"\nDRY RUN. Wrote {len(batch)} rendered messages -> {PREVIEW}", file=sys.stderr)
        print(f"Nothing sent. Read it. Sending {len(batch)} would take ~{est:.0f} min "
              f"at the current delay.", file=sys.stderr)
        print(f"To send for real:  SEND=1 MAX={MAX} python3 {sys.argv[0]}", file=sys.stderr)
        return

    print(f"\nSENDING to {len(batch)} people. Ctrl-C to abort.", file=sys.stderr)
    new = not os.path.exists(SENTLOG)
    log = open(SENTLOG, "a", newline="", encoding="utf-8")
    w = csv.writer(log)
    if new:
        w.writerow(["slack_id", "real_name", "first_name", "dm_channel", "ts", "when"])

    sent = fails = 0
    for i, (uid, fn, r) in enumerate(batch, 1):
        conv = call("conversations.open", users=uid)
        if not conv.get("ok"):
            err = conv.get("error")
            print(f"  [{i}/{len(batch)}] {uid} open failed: {err}", file=sys.stderr)
            if err in ("invalid_auth", "token_revoked", "account_inactive", "ratelimited"):
                print("  ! stopping - auth or rate limit hit.", file=sys.stderr); break
            fails += 1; continue

        ch = conv["channel"]["id"]
        res = call("chat.postMessage", channel=ch, text=template.format(first_name=fn))
        if res.get("ok"):
            sent += 1
            w.writerow([uid, r.get("real_name", ""), fn, ch, res.get("ts", ""),
                        time.strftime("%Y-%m-%d %H:%M:%S")])
            log.flush()
            print(f"  [{i}/{len(batch)}] sent to {fn} ({uid})", file=sys.stderr)
        else:
            err = res.get("error")
            fails += 1
            print(f"  [{i}/{len(batch)}] {uid} post failed: {err}", file=sys.stderr)
            if err in ("invalid_auth", "token_revoked", "account_inactive",
                       "ratelimited", "restricted_action"):
                print("  ! stopping - auth, rate limit, or workspace restriction.",
                      file=sys.stderr); break

        if i < len(batch):
            d = random.randint(MIN_D, MAX_D)
            print(f"      waiting {d}s", file=sys.stderr)
            time.sleep(d)

    log.close()
    print(f"\nDone. {sent} sent, {fails} failed. Log: {SENTLOG}", file=sys.stderr)


if __name__ == "__main__":
    main()
