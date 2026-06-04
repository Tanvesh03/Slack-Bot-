# Chanakya — StayVista Issue Management Bot

Chanakya is a Slack bot that automatically converts @mention messages into tracked task tickets. It posts a Slack card, sends email notifications, logs everything to Google Sheets, and lets assignees Accept / Reassign / Mark Done from both Slack and email.

---

## Features

- **Auto task creation** — Any Slack message with an @mention creates an issue (ISS-0001, ISS-0002, …)
- **Shared multi-assignee card** — Mentioning two people in one message creates one shared card; first to Accept claims the task
- **Slack interactive buttons** — Accept and Done buttons on every card; only the assigned person can act
- **Email notifications** — Assignment, Accepted, Reassigned, and Resolved emails with one-click action links
- **Google Sheets logging** — Every issue and status change is logged in real time
- **Startup backfill** — On restart, scans the last 24 hours of channel history to recover any missed messages
- **Thread reply filtering** — Replies inside threads are ignored; only top-level messages create issues
- **Image/file handling** — Bot reads only typed text; images are stored as attachments only
- **Acknowledgment filtering** — Short replies like "ok", "noted", "will check" are automatically skipped
- **Email whitelist** — Emails only sent to specific team members; all others still get Slack cards and Sheets logging
- **Railway deployment ready** — Set `PUBLIC_URL` env var and ngrok is bypassed automatically

---

## Tech Stack

| Component | Technology |
|---|---|
| Bot server | Python / Flask |
| Slack integration | Slack Events API, Block Kit, Bolt interactions |
| Email | Gmail SMTP via App Password |
| Database | `issues.json` (local) + Google Sheets (remote) |
| Tunnel (local) | ngrok via pyngrok |
| Hosting | Railway (production) |

---

## Project Structure

```
slack_issue_bot/
├── app.py                      # Main Flask server — all routes and business logic
├── email_sender.py             # Gmail SMTP email templates and sending
├── sheets_logger.py            # Google Sheets logging and batch updates
├── run.py                      # Launcher — handles ngrok/Railway, prints config URLs
├── issues.json                 # Local issue store (auto-created, gitignored)
├── service_account.json        # Google service account key (gitignored, never commit)
├── .env                        # Environment variables (gitignored, never commit)
├── .env.template               # Template for .env setup
├── Procfile                    # Railway deployment entry point
├── requirements.txt            # Python dependencies
├── TEAM_COMMUNICATION_GUIDE.md # How the team should use the bot (Markdown)
└── TEAM_COMMUNICATION_GUIDE.docx  # Same guide as Word document
```

---

## Environment Variables

Copy `.env.template` to `.env` and fill in all values:

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token from api.slack.com/apps |
| `SLACK_SIGNING_SECRET` | Signing secret from app Basic Information page |
| `EMAIL_ADDRESS` | Gmail address emails are sent from |
| `EMAIL_PASSWORD` | Gmail App Password (16-character, not the login password) |
| `GOOGLE_SHEET_ID` | ID of the Google Sheet (from the URL) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON file (local) |
| `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` | Full JSON content as string (Railway/production) |
| `NGROK_AUTH_TOKEN` | ngrok auth token (local development only) |
| `PORT` | Flask port — default `5000` |
| `PUBLIC_URL` | Full HTTPS URL of the server (Railway) — skips ngrok when set |
| `BACKFILL_HOURS` | How many hours back to scan on startup — default `24` |

---

## Local Development Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.template .env
# Edit .env with your actual values
```

### 3. Start the bot
```bash
python run.py
```

The launcher will:
- Start an ngrok tunnel (or reuse an existing one)
- Print the Event Subscriptions and Interactivity URLs
- Start Flask on port 5000

### 4. Configure Slack app settings
Paste the printed URLs into your Slack app:
- **api.slack.com/apps** → your app → **Event Subscriptions** → Request URL
- **api.slack.com/apps** → your app → **Interactivity & Shortcuts** → Request URL

---

## Railway Deployment

### 1. Deploy
- Go to **railway.app** → New Project → Deploy from GitHub repo → select this repo

### 2. Add environment variables
In Railway dashboard → Variables, add all variables from `.env` plus:

| Variable | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` | Paste the full contents of `service_account.json` |
| `PUBLIC_URL` | Your Railway app URL (e.g. `https://your-app.up.railway.app`) |

### 3. Update Slack app settings
Replace both ngrok URLs with your Railway URL:
- `https://your-app.up.railway.app/slack/events`
- `https://your-app.up.railway.app/slack/actions`

### 4. Persistent storage (recommended)
Railway filesystem resets on redeploy. To keep `issues.json` across deploys:
- Service → **Volumes** → Add Volume → mount path `/app`

---

## How It Works

### Task creation flow
```
Team member sends: "@Kushal Pandey Please check OTA pricing for Villa Serenity"
        ↓
Bot detects @mention → extracts assignee(s) → checks not acknowledgment
        ↓
Creates ONE issue (ISS-XXXX) — shared card if multiple mentions
        ↓
Posts Slack card with [Accept] [Done] buttons
        ↓ (in background)
Sends assignment email to assignee (if in whitelist)
Logs row to Google Sheets
```

### Multi-assignee flow
```
Message: "@Kushal @Tanvesh Please update OTA RR sheet"
        ↓
One issue created: ISS-XXXX
Assigned To: Kushal Pandey / Tanvesh Bandodkar
        ↓
Both receive separate assignment emails with their own Accept links
        ↓
First person to click Accept → becomes sole assignee
Second person clicking Accept → sees "Kushal already accepted ISS-XXXX"
```

### Accept / Done flow
```
Assignee clicks Accept (Slack or email)
        ↓
Slack card updates immediately → Status: Accepted, Accept button hidden
Google Sheets updated (batch — single API call)
Accept confirmation email sent (CC raiser)
        ↓
Assignee clicks Done → types completion message
        ↓
Slack card updates → Status: Resolved, buttons removed
Google Sheets updated (batch — single API call)
Resolved email sent (CC raiser)
```

### Startup backfill
```
Bot starts → waits 8 seconds for users cache
        ↓
Scans last 24 hours of all known channels
        ↓
Compares message timestamps against existing issues
        ↓
Creates issues for any @mention messages missed while bot was offline
```

---

## Issue Lifecycle

| Status | Meaning |
|---|---|
| *(empty)* | Pending — assigned but not yet accepted |
| Accepted | Assignee has accepted and started working |
| Resolved | Task marked done with a completion message |
| Reassigned | Task moved to a different person |

---

## Email Whitelist

Emails are sent only when tasks are assigned to:

- Ashish Chakor
- Krutika Naik
- Kushal Pandey
- Megha Prasad
- Shubhangi Sharma
- Sonu Meena
- Sudesh Patil
- Tanvesh Bandodkar

Tasks assigned to anyone else still create a Slack card and log to Sheets — no email is sent.

---

## Acknowledgment Filter

Messages that are only acknowledgments are automatically skipped and do not create issues:

**Skipped:** `ok`, `noted`, `got it`, `sure`, `will do`, `will check`, `noted will check`, `acknowledged`, `checking`, `done`, `roger`, `received` — and combinations of these.

**Not skipped:** Any message with substantive task content, even if it ends with "Thanks." or "Thank you."

---

## Slack App Requirements

The bot requires the following OAuth scopes:

**Bot Token Scopes:**
- `channels:history` — Read messages from public channels
- `channels:read` — Get channel info
- `chat:write` — Post and update messages
- `users:read` — Get user info and email
- `users:read.email` — Get user email addresses

**Event Subscriptions:**
- `message.channels` — Listen to messages in public channels

---

## Google Sheets Structure

The **Issues** tab tracks:

| Column | Description |
|---|---|
| Issue ID | ISS-0001, ISS-0002, … |
| Issue Description | Task text (mentions stripped) |
| Raised By | Person who sent the message |
| Assigned To | Assignee name (updates on acceptance) |
| Raised Date / Time | When the message was sent |
| Working Started Date / Time | When Accept was clicked |
| Task Completion Date / Time | When Done was submitted |
| Completion Message | What the assignee wrote on Done |
| Current Status | Pending / Accepted / Resolved / Reassigned |
| Resolution Duration | Time from raised to resolved |
| Reassigned From | Previous assignee if reassigned |
| Reassignment Reason | Reason entered on reassignment |
| Reassignment Time | When reassignment happened |

---

## Security Notes

- `.env` — never commit to GitHub
- `service_account.json` — never commit to GitHub
- `issues.json` — excluded from git (contains names and emails)
- Email action URLs are HMAC-signed tokens — cannot be guessed or forged
- Slack button actions verify the Slack signing secret on every request
- Only the assigned person can Accept or mark Done on a task

---

*Chanakya — StayVista Issue Management Bot | Internal Use Only*
