#!/usr/bin/env python3
"""
Scrape Slack members (whole workspace, or one channel) + profiles, custom
fields and any links they've put in their profile -> CSV.

  source .slack-env          # SLACK_TOKEN, SLACK_COOKIE, SLACK_TEAM
  export SLACK_CHANNEL='C0123456789'   # optional: one channel only
  python3 slack-member-scrape.py

Env:
  SLACK_TOKEN    xoxc-... from the browser, or xoxp-... from a real Slack app
  SLACK_COOKIE   xoxd-... session cookie (required for xoxc- tokens only)
  SLACK_TEAM     T0123456789 workspace ID
  SLACK_CHANNEL  C0123456789 to scrape one channel; omit for the whole workspace
  SLACK_OUT      output file (default slack-members.csv)
  SLACK_DEEP=0   fast pass: names/titles/emails only, no custom fields
  SLACK_LIMIT=50 stop after N members (test run)

The deep pass costs ~1.2s per member, so a 2,000-person workspace is ~40 min.
Run SLACK_DEEP=0 first to see what you're dealing with.
"""

import os, sys, csv, re, time
import requests

TOKEN   = os.environ.get("SLACK_TOKEN", "").strip()
COOKIE  = os.environ.get("SLACK_COOKIE", "").strip()
TEAM    = os.environ.get("SLACK_TEAM", "").strip()
CHANNEL = os.environ.get("SLACK_CHANNEL", "").strip()
OUT     = os.environ.get("SLACK_OUT", "slack-members.csv")
DEEP    = os.environ.get("SLACK_DEEP", "1") != "0"
LIMIT   = int(os.environ.get("SLACK_LIMIT", "0"))

if not TOKEN:
    sys.exit("Set SLACK_TOKEN first. See the docstring at the top of this file.")
if TOKEN.startswith("xoxc-") and not COOKIE:
    sys.exit("An xoxc- token also needs the session cookie: export SLACK_COOKIE='xoxd-...'")
if COOKIE and not COOKIE.startswith("d="):
    COOKIE = "d=" + COOKIE

S = requests.Session()
S.headers["Authorization"] = f"Bearer {TOKEN}"
S.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
if COOKIE:
    S.headers["Cookie"] = COOKIE

URL_RE = re.compile(r'https?://[^\s<>"\')]+')


def call(method, **params):
    if TEAM:
        params.setdefault("team_id", TEAM)
    params = {k: v for k, v in params.items() if v not in ("", None)}
    for attempt in range(6):
        r = S.post(f"https://slack.com/api/{method}", data=params, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait + 1); continue
        d = r.json()
        if d.get("ok"):
            return d
        err = d.get("error", "unknown")
        if err in ("ratelimited", "internal_error", "service_unavailable"):
            time.sleep(5 * (attempt + 1)); continue
        if err in ("invalid_auth", "not_authed", "token_revoked", "token_expired"):
            sys.exit(f"{method}: {err}\n  -> token/cookie is wrong or expired. "
                     f"Grab a fresh pair from the Slack tab and retry.")
        if err == "missing_scope":
            sys.exit(f"{method}: missing scope '{d.get('needed','?')}'")
        if err in ("channel_not_found", "not_in_channel"):
            sys.exit(f"{method}: {err}\n  -> join the channel, or check the channel ID.")
        raise RuntimeError(f"{method} failed: {err}")
    raise RuntimeError(f"{method}: gave up after retries")


def paged(method, key, **params):
    out, cursor = [], ""
    while True:
        d = call(method, limit=200, cursor=cursor, **params)
        out += d[key]
        print(f"  {len(out)}...", file=sys.stderr)
        cursor = d.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return out


def field_labels():
    """Map custom-field IDs (Xf0123) to their human labels, if we're allowed."""
    try:
        prof = call("team.profile.get")["profile"]
    except (RuntimeError, SystemExit):
        print("! no custom-field map available; using raw field IDs", file=sys.stderr)
        return {}
    return {f["id"]: (f.get("label") or f["id"]) for f in prof.get("fields", [])}


def main():
    print("Reading custom profile field definitions...", file=sys.stderr)
    labels = field_labels()
    print(f"  fields: {', '.join(labels.values()) or '(none)'}", file=sys.stderr)

    print("Fetching workspace directory...", file=sys.stderr)
    raw = paged("users.list", "members")

    if CHANNEL:
        print(f"Fetching members of {CHANNEL}...", file=sys.stderr)
        ids = set(paged("conversations.members", "members", channel=CHANNEL))
        raw = [m for m in raw if m["id"] in ids]
        print(f"  {len(ids)} in channel", file=sys.stderr)

    people = [m for m in raw
              if not m.get("is_bot") and not m.get("deleted")
              and not m.get("is_app_user") and m.get("id") != "USLACKBOT"]
    if LIMIT:
        people = people[:LIMIT]
    print(f"{len(people)} human members to process", file=sys.stderr)

    if DEEP:
        mins = len(people) * 1.2 / 60
        print(f"Deep profile pass: ~{mins:.0f} min. (SLACK_DEEP=0 to skip)", file=sys.stderr)

    rows = []
    for i, m in enumerate(people, 1):
        p = dict(m.get("profile", {}))
        if DEEP:
            if i == 1 or i % 25 == 0:
                print(f"  profile {i}/{len(people)}", file=sys.stderr)
            try:
                p.update(call("users.profile.get", user=m["id"])["profile"])
            except RuntimeError as e:
                print(f"  ! {m['id']}: {e}", file=sys.stderr)
            time.sleep(1.2)

        row = {
            "slack_id": m["id"],
            "handle": m.get("name", ""),
            "real_name": p.get("real_name") or m.get("real_name", ""),
            "display_name": p.get("display_name", ""),
            "first_name": p.get("first_name", ""),
            "last_name": p.get("last_name", ""),
            "title": p.get("title", ""),
            "email": p.get("email", ""),
            "phone": p.get("phone", ""),
            "status_text": p.get("status_text", ""),
            "tz": m.get("tz", ""),
            "tz_label": m.get("tz_label", ""),
            # Seconds from UTC. slack-dm-send.py uses this to keep sends inside
            # each recipient's working hours.
            "tz_offset": m.get("tz_offset", ""),
            "is_admin": m.get("is_admin", False),
            "is_guest": m.get("is_restricted", False),
            "avatar": p.get("image_512") or p.get("image_192", ""),
        }
        blob = [row["title"], row["status_text"]]
        for fid, val in (p.get("fields") or {}).items():
            v = val.get("value", "") if isinstance(val, dict) else str(val)
            row[f"cf_{labels.get(fid, fid)}"] = v
            blob.append(v)

        urls, seen = [], set()
        for chunk in blob:
            for u in URL_RE.findall(chunk or ""):
                u = u.rstrip('.,;)')
                if u not in seen:
                    seen.add(u); urls.append(u)
        row["all_links"] = " | ".join(urls)
        row["linkedin"] = next((u for u in urls if "linkedin.com" in u), "")
        rows.append(row)

    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print(f"\nWrote {len(rows)} rows -> {OUT}", file=sys.stderr)
    print(f"  {sum(1 for r in rows if r['email'])} with email, "
          f"{sum(1 for r in rows if r['linkedin'])} with LinkedIn, "
          f"{sum(1 for r in rows if r['title'])} with a title", file=sys.stderr)


if __name__ == "__main__":
    main()
