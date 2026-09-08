# Slack DM Outreach

**Three small Python scripts for doing outreach in the Slack communities you're
already a member of: pull the member list with real job titles, preview every
message before it goes, send them slowly with a first name that's actually
right, then check who replied.**

No Slack app to install, no admin approval, no seat pricing. It runs off your
own browser session, so it works in any workspace you can log into — which is
the whole point, because in most communities you are a member, not an admin,
and a member can't install anything.

Dry run is the default. Nothing is ever sent unless you type `SEND=1`.

```
slack-member-scrape.py   ->  slack-members.csv      who's in here, and what they do
slack-dm-send.py         ->  slack-dm-preview.txt   read this before you send anything
slack-dm-send.py SEND=1  ->  slack-dm-sent.csv      resumable, duplicate-proof
slack-dm-replies.py      ->  who actually wrote back
```

## Who this is for

- **Founders and GTM people** in a few good Slack communities who want to talk
  to the right 200 members instead of posting into a channel and hoping.
- **Community-led sales**, where the member directory is the list and job title
  is the only segmentation you get.
- **Anyone who has been told "just DM people in the community"** and wants to do
  it without burning the community, or their name in it.

It is not a growth-hack cannon. It sends slowly, one message per person, logs
everything, and makes it easy to stop. Read [Sending like a
person](#sending-like-a-person) before your first batch.

---

## What you need

| | What for | Cost |
| --- | --- | --- |
| **Python 3.8+** | running it | free |
| **`requests`** | the one dependency | `pip install -r requirements.txt` |
| **A Slack account in the workspace** | everything | free — a normal member account is enough |

You do **not** need to be an admin, and you do **not** need to install a Slack
app.

---

## Quick start

```bash
git clone https://github.com/mariellecamba-gtm/slack-dm-outreach.git
cd slack-dm-outreach
pip install -r requirements.txt

cp .slack-env.example .slack-env      # then fill in your token, cookie, team ID
cp message.example.txt message.txt    # then write your own message
cp blocklist.example.txt blocklist.txt

source .slack-env

# 1. Who's in here? Start with the fast pass to see the size of it.
SLACK_DEEP=0 python3 slack-member-scrape.py

# 2. The full pass, with titles and custom profile fields (~1.2s per member).
python3 slack-member-scrape.py

# 3. Preview. Nothing is sent. Open the file and read every message.
python3 slack-dm-send.py

# 4. Send a small first batch, inside their working hours.
SEND=1 MAX=25 LOCAL_HOURS=9-17 python3 slack-dm-send.py

# 5. A day later, before you send another batch:
python3 slack-dm-replies.py
```

---

## Getting your token and cookie

This is the part nobody documents. A Slack **app** token (`xoxp-`) requires an
admin to approve an install, which you won't get in someone else's community.
So instead you borrow the session your browser already has.

Two pieces, and you need both:

**1. The token (`xoxc-...`)** — open the workspace in Slack **in a browser**
(not the desktop app), open the JS console (`Cmd+Option+J` / `Ctrl+Shift+J`) and
run:

```js
JSON.parse(localStorage.localConfig_v2).teams
```

Expand the result. Each workspace you're in is one entry, keyed by its team ID
(`T0123456789` — that's your `SLACK_TEAM`), and each has a `token` starting
`xoxc-`. That's your `SLACK_TOKEN`.

**2. The cookie (`xoxd-...`)** — this one JavaScript cannot read, by design, so
it has to be copied by hand: **DevTools → Application → Cookies →
`https://app.slack.com` → `d`**. Copy the whole value. That's your
`SLACK_COOKIE`.

Put both in `.slack-env` and `source` it. They're sent together with a browser
User-Agent, which is what makes the request look like the browser session it is.

> **Treat these as your password, because they are.** They authenticate as
> *you*, with everything your account can do — not a scoped bot. `.slack-env` is
> gitignored; keep it that way, never paste it anywhere, and log out of that
> browser session to revoke it. Expect to refresh them every few weeks: when a
> script stops with `invalid_auth` or `token_expired`, grab a fresh pair.

If you *do* have an approved Slack app, an `xoxp-` token works everywhere here
too, and needs no cookie. You'll want the `users:read`, `users:read.email`,
`users.profile:read`, `conversations:read`, `chat:write` and `im:write` scopes.

---

## The three scripts

### 1. `slack-member-scrape.py` — build the list

Pulls every human member (bots, deleted accounts and Slackbot are dropped), then
walks each profile for the fields the directory doesn't return: title, email,
custom profile fields, and any URL anyone has put in their profile — LinkedIn
gets its own column.

```bash
python3 slack-member-scrape.py
SLACK_CHANNEL=C0123456789 python3 slack-member-scrape.py   # one channel only
SLACK_DEEP=0 python3 slack-member-scrape.py                # fast, no custom fields
SLACK_LIMIT=50 python3 slack-member-scrape.py              # test on 50 people
```

| Env | Default | What it does |
| --- | --- | --- |
| `SLACK_TOKEN` | — | required |
| `SLACK_COOKIE` | — | required for `xoxc-` tokens |
| `SLACK_TEAM` | — | workspace ID, `T…` |
| `SLACK_CHANNEL` | *(all)* | scrape one channel's members instead of the workspace |
| `SLACK_OUT` | `slack-members.csv` | output file |
| `SLACK_DEEP` | `1` | `0` skips the per-profile pass — much faster, no titles from custom fields |
| `SLACK_LIMIT` | `0` | stop after N members |

**Check whether the channel is real segmentation before you trust it.** Some
communities auto-join every member to every channel, so a 60,000-member
`#revops` channel is just the whole workspace wearing a hat, and picking it buys
you nothing. Compare the channel count to the workspace count. If they match,
title is your only filter.

Expect most members to have no title at all — 15% coverage is normal. That's
not a bug in the scraper, it's Slack profiles.

### 2. `slack-dm-send.py` — preview, then send

Run it with no `SEND=1` and it writes every rendered message to
`slack-dm-preview.txt` and sends nothing. That preview is the product. Read it.

```bash
python3 slack-dm-send.py                                    # dry run
SEND=1 MAX=25 python3 slack-dm-send.py                      # send 25
SEND=1 MAX=50 TITLE_MATCH='revops|head of sales' python3 slack-dm-send.py
```

| Env | Default | What it does |
| --- | --- | --- |
| `SEND` | `0` | `1` actually sends. Everything else is a dry run. |
| `CSV` | `slack-members.csv` | input list |
| `MSG` | `message.txt` | template; must contain `{first_name}` |
| `SENTLOG` | `slack-dm-sent.csv` | append-only log. One per campaign. |
| `MAX` | `25` | hard cap on sends this run |
| `MIN_DELAY` / `MAX_DELAY` | `25` / `35` | random seconds between sends |
| `TITLE_MATCH` | — | regex; only DM titles that match |
| `TITLE_EXCLUDE` | — | regex; drop titles that match |
| `LOCAL_HOURS` | — | e.g. `9-17`: only DM people whose *own* local time is in that window |
| `SEND_WEEKENDS` | `0` | weekends are skipped when `LOCAL_HOURS` is set |
| `SKIP_ADMINS` | `1` | don't DM workspace admins |
| `SKIP_NAMES` | — | comma-separated one-off exclusions |

Four things it does that matter more than they look:

- **It never guesses a first name.** Handles, emoji names, all-caps company
  names and single letters are rejected and the person is skipped, because
  "Hi BIGCORP" is worse than no message. Fix individual profiles in
  `name-overrides.json` (`{"U0123456789": "Paige"}`), keyed on Slack ID so a fix
  can't misfire on someone else.
- **Every send is logged and never repeated.** Ctrl-C whenever you like; the
  next run picks up where you stopped, and re-running can't double-DM anyone.
- **`blocklist.txt` is absolute.** Community founders, mods, people who've asked
  you not to contact them, people you actually know. Add names before you need
  them.
- **`LOCAL_HOURS` uses each recipient's timezone**, not yours. People with no
  timezone in their profile are skipped while it's on.

### 3. `slack-dm-replies.py` — did it work?

```bash
python3 slack-dm-replies.py
SENTLOG=campaign-b.csv OUT=replies.csv python3 slack-dm-replies.py
```

Walks every DM channel in the log and prints the reply rate plus the text of
every reply. One API call per row, ~0.3s each. **Run this before every new
batch.** It is the only feedback loop you have.

---

## Sending like a person

The scripts are the easy half. The reason most Slack outreach fails is the
message, and the volume you sent it at before finding out.

- **50 before 500.** Send a small batch, wait a day, run the replies script. A
  campaign that gets nothing at 50 will get nothing at 500 — you'll just have
  burned 500 first impressions to learn it.
- **Identical messages get identical results, and the result is usually zero.**
  If the only thing that changes between recipients is the first name, you have
  a broadcast, not outreach. Segment on title with `TITLE_MATCH` and write a
  genuinely different message per segment.
- **Ask one question.** A first DM with no ask gives nobody a reason to type.
  Three links gives them a reason not to.
- **Timing is not a detail.** A message that lands at 3am is read while they're
  clearing notifications. Use `LOCAL_HOURS=9-17`.
- **One message, one person, once.** No follow-up sequences. This is a Slack DM
  from a human, and it should stay legible as one.
- **Read the community rules first.** Plenty of communities explicitly forbid
  cold DMs, and being the person who ignored that costs more than the pipeline
  is worth. If they forbid it, don't — use the scraped list to know who to talk
  to *in public* instead.

**Use this only in communities you actually belong to, for messages a real
person would be glad to receive.** Slack's Terms of Service are between you and
Slack, and this tool authenticates as you: your account carries the consequences
of what you send with it.

---

## Troubleshooting

| What you see | What it means |
| --- | --- |
| `invalid_auth` / `token_expired` | Session ended. Grab a fresh token **and** cookie from the browser. |
| `not_authed` with a token set | Missing or stale `d` cookie — `xoxc-` tokens are useless without it. |
| `missing_scope` | An `xoxp-` app token without the scopes listed above. |
| `channel_not_found` / `not_in_channel` | Join the channel first, or the ID is wrong. |
| `restricted_action` | The workspace blocks DMs between these members. It stops on its own. |
| `ratelimited` | It backs off and retries; on send it stops so you can decide. |
| `cannot_dm_bot` | A bot slipped into the CSV. Harmless, it's counted as a failure and skipped. |
| Everyone skipped as "no usable first name" | Your CSV was written by `SLACK_DEEP=0`, or this workspace hides profiles. |
| Everyone skipped as "outside working hours" | `LOCAL_HOURS` is on and it's night where they are. That's it working. |

---

## What's in your working copy

Everything you generate stays local and gitignored: `.slack-env`,
`message.txt`, `blocklist.txt`, `name-overrides.json`, every `.csv`, and the
preview. The repo ships only the scripts and the `.example` files, so a clone of
your fork never leaks your list, your copy, or your credentials.

## License

MIT — see [LICENSE](LICENSE). Do what you like with it; the responsibility for
what you send is yours.
