# StayVista Slack Issue Management Bot

## Quick Start

1. Copy `.env.template` to `.env` and fill in all values
2. Install dependencies: `pip install -r requirements.txt`
3. Run locally: `python app.py`
4. Start ngrok: `ngrok http 3000`
5. Paste the ngrok URL into Slack → Event Subscriptions

## Slack Event Subscriptions URL
`https://YOUR-NGROK-URL.ngrok.io/slack/events`

## Slack Interactivity URL
`https://YOUR-NGROK-URL.ngrok.io/slack/actions`

## Files
- `app.py` — Main bot server
- `email_sender.py` — Gmail SMTP email automation
- `sheets_logger.py` — Google Sheets logging
- `.env.template` — Environment variable template
- `service_account.json` — Google service account key (DO NOT commit to Git)
