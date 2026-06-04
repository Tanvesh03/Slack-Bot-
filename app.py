"""
app.py — Chanakya | StayVista Issue Management Bot
"""

import os
import re
import json
import hashlib
import hmac as hmac_lib
import threading
import traceback
import urllib.request as urllib_req
from datetime import datetime
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from dotenv import load_dotenv

from email_sender import (
    send_assignment_email,
    send_accepted_email,
    send_resolved_email,
    send_reassign_notification_email,
)
from sheets_logger import log_issue, batch_update_issue

load_dotenv()

app = Flask(__name__)
slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
signature_verifier = SignatureVerifier(os.environ["SLACK_SIGNING_SECRET"])

try:
    _auth = slack_client.auth_test()
    SLACK_TEAM_ID = _auth["team_id"]
    print(f"Slack Team ID: {SLACK_TEAM_ID}")
except Exception as _e:
    SLACK_TEAM_ID = ""
    print(f"Could not fetch Slack team ID: {_e}")

ISSUES_FILE = os.path.join(os.path.dirname(__file__), "issues.json")
_save_lock = threading.Lock()

_event_ids_lock = threading.Lock()
processed_event_ids = set()

_issue_counter = 0
_issue_counter_lock = threading.Lock()


def _load_issues():
    if not os.path.exists(ISSUES_FILE):
        return {}
    try:
        with open(ISSUES_FILE, "r") as f:
            data = json.load(f)
        for issue in data.values():
            issue["action_emails_sent"] = set(issue.get("action_emails_sent", []))
        print(f"Loaded {len(data)} issues from disk")
        return data
    except Exception as e:
        print(f"Failed to load issues from disk: {e}")
        return {}


def _save_issues():
    with _save_lock:
        try:
            serializable = {}
            for k, v in issues.items():
                row = dict(v)
                row["action_emails_sent"] = list(row.get("action_emails_sent", set()))
                serializable[k] = row
            with open(ISSUES_FILE, "w") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            print(f"Failed to save issues to disk: {e}")


issues = _load_issues()
if issues:
    _issue_counter = max(int(k.split("-")[1]) for k in issues)

# ── Slack users cache (refreshed every 5 min) ────────────────────────────────
_users_cache = []
_users_cache_lock = threading.Lock()


def _refresh_users_cache():
    global _users_cache
    users = []
    cursor = None
    try:
        while True:
            kwargs = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            result = slack_client.users_list(**kwargs)
            for member in result["members"]:
                if member.get("deleted") or member.get("is_bot") or member.get("id") == "USLACKBOT":
                    continue
                profile = member.get("profile", {})
                name = profile.get("display_name") or profile.get("real_name", "")
                email = profile.get("email", "")
                if name and email:
                    users.append({"id": member["id"], "name": name, "email": email})
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        with _users_cache_lock:
            _users_cache = sorted(users, key=lambda u: u["name"])
        print(f"Users cache refreshed: {len(_users_cache)} users")
    except Exception as e:
        print(f"Failed to refresh users cache: {e}")


def _schedule_users_cache():
    _refresh_users_cache()
    t = threading.Timer(300, _schedule_users_cache)
    t.daemon = True
    t.start()


threading.Thread(target=_schedule_users_cache, daemon=True).start()

# ── Startup backfill — recover missed messages while bot was offline ──────────
BACKFILL_HOURS = int(os.environ.get("BACKFILL_HOURS", 24))


def _backfill_missed_messages():
    """On startup, scan recent channel history and create issues for any
    @mention messages that were missed while the bot was offline."""
    import time
    time.sleep(8)  # wait for users cache to populate first

    # Build set of already-tracked message timestamps
    known_ts = {iss.get("raised_ts") for iss in issues.values() if iss.get("raised_ts")}

    # Collect all channels from existing issues
    known_channels = {iss["channel_id"] for iss in issues.values() if iss.get("channel_id")}

    if not known_channels:
        print("Backfill: no channels to scan")
        return

    oldest = str(datetime.now().timestamp() - BACKFILL_HOURS * 3600)
    total_missed = 0

    for channel_id in known_channels:
        try:
            result = slack_client.conversations_history(
                channel=channel_id,
                oldest=oldest,
                limit=200,
            )
            for msg in result.get("messages", []):
                ts = msg.get("ts", "")
                if ts in known_ts:
                    continue
                if msg.get("bot_id"):
                    continue
                thread_ts = msg.get("thread_ts")
                if thread_ts and thread_ts != ts:
                    continue
                if msg.get("subtype") not in (None, "file_share"):
                    continue
                text = msg.get("text", "")
                if not re.findall(r"<@([A-Z0-9]+)>", text):
                    continue
                # Process as a missed message
                print(f"Backfill: processing missed message ts={ts} in {channel_id}")
                _handle_new_message_inner(msg)
                known_ts.add(ts)
                total_missed += 1
        except Exception as e:
            print(f"[WARN] Backfill failed for {channel_id}: {e}")

    if total_missed:
        print(f"Backfill complete: recovered {total_missed} missed message(s)")
    else:
        print(f"Backfill complete: no missed messages in last {BACKFILL_HOURS}h")


threading.Thread(target=_backfill_missed_messages, daemon=True).start()

# ── Channel name cache ────────────────────────────────────────────────────────
_channel_cache = {}

# ── Public URL cache ──────────────────────────────────────────────────────────
_public_url_cache = None
_public_url_lock = threading.Lock()

EMAIL_WHITELIST = {
    "Ashish Chakor",
    "Krutika Naik",
    "Kushal Pandey",
    "Megha Prasad",
    "Shubhangi Sharma",
    "Sonu Meena",
    "Sudesh Patil",
    "Tanvesh Bandodkar",
}

SKIP_PHRASES = [
    "okay", "ok", "thanks", "thank you", "noted", "working on it",
    "got it", "sure", "will do", "acknowledged", "understood", "on it",
    "will check", "checking", "alright", "done", "checked", "roger",
    "received", "looking into it", "ack",
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_user_info(user_id):
    with _users_cache_lock:
        for u in _users_cache:
            if u["id"] == user_id:
                return u["name"], u["email"]
    try:
        res = slack_client.users_info(user=user_id)
        user = res["user"]
        name = user["profile"].get("display_name") or user["profile"].get("real_name", "Unknown")
        email = user["profile"].get("email", "")
        return name, email
    except Exception as e:
        print(f"Error fetching user {user_id}: {e}")
        return "Unknown", ""


def get_slack_users():
    with _users_cache_lock:
        return list(_users_cache)


def get_channel_name(channel_id):
    if channel_id in _channel_cache:
        return _channel_cache[channel_id]
    try:
        res = slack_client.conversations_info(channel=channel_id)
        name = "#" + res["channel"].get("name", channel_id)
        _channel_cache[channel_id] = name
        return name
    except Exception:
        return channel_id


def generate_issue_id():
    global _issue_counter
    with _issue_counter_lock:
        _issue_counter += 1
        return f"ISS-{str(_issue_counter).zfill(4)}"


def extract_mentions(text):
    return re.findall(r"<@([A-Z0-9]+)>", text)


def is_acknowledgment(text):
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip().lower()
    clean = re.sub(r"[!.,?]", "", clean).strip()
    if not clean:
        return True
    if len(clean) > 100:
        return False
    return any(phrase in clean for phrase in SKIP_PHRASES)


def clean_slack_text(text):
    clean = re.sub(r"<@[A-Z0-9]+>", "", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def get_issue_type(text):
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    return "Query" if "?" in clean else "Issue"


def get_public_url():
    global _public_url_cache
    with _public_url_lock:
        if _public_url_cache:
            return _public_url_cache
        url = os.environ.get("PUBLIC_URL", "")
        if url:
            result = url if url.startswith("https://") else "https://" + url
            _public_url_cache = result
            return result
        try:
            with urllib_req.urlopen("http://localhost:4040/api/tunnels", timeout=2) as r:
                data = json.loads(r.read())
                raw = data["tunnels"][0]["public_url"]
                result = raw if raw.startswith("https://") else "https://" + raw[7:]
                _public_url_cache = result
                return result
        except Exception:
            return None


def generate_email_token(issue_id: str, action: str) -> str:
    key = os.environ["SLACK_SIGNING_SECRET"].encode()
    return hmac_lib.new(key, f"{issue_id}:{action}".encode(), hashlib.sha256).hexdigest()[:20]


def _get_candidates(issue):
    """Return candidate list, falling back to single-assignee for old issues."""
    candidates = issue.get("candidate_assignees")
    if candidates:
        return candidates
    # Backward compat: old single-assignee issues
    if issue.get("assigned_to_id") and issue.get("assigned_to_email"):
        return [{"id": issue["assigned_to_id"], "name": issue["assigned_to"], "email": issue["assigned_to_email"]}]
    return []


def _get_candidate_ids(issue):
    """Return list of valid actor IDs for this issue."""
    ids = issue.get("candidate_assignee_ids")
    if ids:
        return ids
    if issue.get("assigned_to_id"):
        return [issue["assigned_to_id"]]
    return []


def _issue_blocks(issue_id, assigned_to_name, description, status):
    status_text = status if status else "Pending"
    blocks = [
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Issue ID:*\n{issue_id}"},
                {"type": "mrkdwn", "text": f"*Assigned To:*\n{assigned_to_name}"},
                {"type": "mrkdwn", "text": f"*Description:*\n{description[:200]}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status_text}"},
            ],
        }
    ]

    if status != "Resolved":
        elements = []
        if status not in ("Accepted",):
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Accept"},
                "style": "primary",
                "action_id": "accept_task",
                "value": issue_id,
            })
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Done"},
            "style": "primary",
            "action_id": "done_task",
            "value": issue_id,
        })
        blocks.append({"type": "actions", "elements": elements})

    return blocks


def post_issue_notification(channel, issue_id, description, assigned_to_name, issue_type):
    label = "Query" if issue_type == "Query" else "Issue"
    result = slack_client.chat_postMessage(
        channel=channel,
        blocks=_issue_blocks(issue_id, assigned_to_name, description, ""),
        text=f"{label} {issue_id} assigned to {assigned_to_name}",
    )
    return result.get("ts")


def _update_slack_message(issue_id, status):
    issue = issues.get(issue_id)
    if not issue or not issue.get("slack_ts") or not issue.get("channel_id"):
        return
    try:
        slack_client.chat_update(
            channel=issue["channel_id"],
            ts=issue["slack_ts"],
            blocks=_issue_blocks(issue_id, issue["assigned_to"], issue["description"], status),
            text=f"{issue_id} - {status}",
        )
    except Exception as e:
        print(f"Failed to update Slack message for {issue_id}: {e}")


def _build_action_urls(public_url, issue_id, raiser_id="", actor_id=""):
    """Build email action URLs. actor_id encodes who this email is addressed to."""
    if not public_url:
        return None, None, None, None
    accept_token   = generate_email_token(issue_id, "accept")
    reassign_token = generate_email_token(issue_id, "reassign")
    done_token     = generate_email_token(issue_id, "done")
    ask_token      = generate_email_token(issue_id, "ask")
    actor_param    = f"&actor_id={actor_id}" if actor_id else ""
    ask_url        = f"{public_url}/email/ask-redirect?issue_id={issue_id}&token={ask_token}"
    return (
        f"{public_url}/email/action?issue_id={issue_id}&action=accept&token={accept_token}{actor_param}",
        f"{public_url}/email/reassign-form?issue_id={issue_id}&token={reassign_token}",
        f"{public_url}/email/done-form?issue_id={issue_id}&token={done_token}",
        ask_url,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _process_accepted(issue_id, actor_id):
    issue = issues.get(issue_id)
    if not issue:
        return

    # Guard: already accepted or resolved
    if issue["status"] in ("Accepted", "Resolved"):
        return
    # Guard: race condition — another thread accepted first
    if issue.get("assigned_to_id") and issue["assigned_to_id"] != actor_id:
        return

    # Resolve actor from candidate list
    actor = next((c for c in _get_candidates(issue) if c["id"] == actor_id), None)
    if actor is None:
        print(f"[WARN] actor {actor_id} not a valid candidate for {issue_id}")
        return

    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    issue["status"]              = "Accepted"
    issue["working_started_time"] = now
    issue["assigned_to"]         = actor["name"]
    issue["assigned_to_email"]   = actor["email"]
    issue["assigned_to_id"]      = actor["id"]

    # Update Slack card instantly
    _update_slack_message(issue_id, "Accepted")

    batch_update_issue(issue_id, {
        "working_started_time": now,
        "status":               "Accepted",
        "assigned_to":          actor["name"],
    })

    sent = issue.setdefault("action_emails_sent", set())
    # Use the per-actor thread_message_id for correct email threading
    thread_id = (
        issue.get("thread_message_ids", {}).get(actor_id)
        or issue.get("thread_message_id")
    )
    if "accepted" not in sent:
        sent.add("accepted")
        accept_msg_id = send_accepted_email(
            to_email=actor["email"],
            to_name=actor["name"],
            issue_id=issue_id,
            issue_text=issue["description"],
            assignee_name=actor["name"],
            raised_by=issue["raised_by"],
            raiser_email=issue["raised_by_email"] or None,
            original_message_id=thread_id,
        )
        issue["accept_message_id"] = accept_msg_id

    _save_issues()
    print(f"{issue_id} -> Accepted by {actor['name']}")


def _process_done(issue_id, completion_message, actor_id):
    issue = issues.get(issue_id)
    if not issue or issue["status"] == "Resolved":
        return

    # If not yet accepted, the person clicking Done implicitly accepts
    if not issue.get("assigned_to_id"):
        actor = next((c for c in _get_candidates(issue) if c["id"] == actor_id), None)
        if actor is None:
            print(f"[WARN] actor {actor_id} not a valid candidate for {issue_id}")
            return
        issue["assigned_to"]       = actor["name"]
        issue["assigned_to_email"] = actor["email"]
        issue["assigned_to_id"]    = actor["id"]
    elif issue["assigned_to_id"] != actor_id:
        print(f"[WARN] {actor_id} tried to mark {issue_id} done but accepted by {issue['assigned_to']}")
        return

    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    issue["status"]             = "Resolved"
    issue["completion_time"]    = now
    issue["completion_message"] = completion_message

    try:
        raised = datetime.strptime(issue["raised_time"], "%d %b %Y, %I:%M %p")
        delta  = datetime.strptime(now, "%d %b %Y, %I:%M %p") - raised
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        issue["resolution_duration"] = f"{hours}h {remainder // 60}m"
    except Exception:
        issue["resolution_duration"] = "N/A"

    _update_slack_message(issue_id, "Resolved")

    batch_update_issue(issue_id, {
        "completion_time":    now,
        "status":             "Resolved",
        "resolution_duration": issue["resolution_duration"],
        "completion_message": completion_message,
        "assigned_to":        issue["assigned_to"],
    })

    sent      = issue.setdefault("action_emails_sent", set())
    thread_id = (
        issue.get("thread_message_ids", {}).get(actor_id)
        or issue.get("thread_message_id")
    )
    accept_id = issue.get("accept_message_id")
    if "resolved" not in sent:
        sent.add("resolved")
        send_resolved_email(
            to_email=issue["assigned_to_email"],
            to_name=issue["assigned_to"],
            issue_id=issue_id,
            issue_text=issue["description"],
            assignee_name=issue["assigned_to"],
            raised_by=issue["raised_by"],
            completion_message=completion_message,
            resolution_duration=issue["resolution_duration"],
            completion_time=now,
            raiser_email=issue["raised_by_email"] or None,
            original_message_id=thread_id,
            accept_message_id=accept_id,
        )

    _save_issues()
    print(f"{issue_id} -> Resolved by {issue['assigned_to']}")


def _process_reassign(issue_id, new_assignee_id, reason, actor_name):
    issue = issues.get(issue_id)
    if not issue or issue["status"] == "Resolved":
        return

    new_assignee_name, new_assignee_email = get_user_info(new_assignee_id)
    if not new_assignee_email:
        print(f"[WARN] No email for new assignee {new_assignee_id}")
        return

    now                = datetime.now().strftime("%d %b %Y, %I:%M %p")
    old_assignee_name  = issue["assigned_to"]
    old_assignee_email = issue["assigned_to_email"]

    issue["reassigned_from"]     = old_assignee_name
    issue["reassignment_reason"] = reason
    issue["reassignment_time"]   = now
    issue["assigned_to"]         = new_assignee_name
    issue["assigned_to_email"]   = new_assignee_email
    issue["assigned_to_id"]      = new_assignee_id
    issue["status"]              = ""
    issue["working_started_time"] = ""
    # Reset candidate list to just the new assignee
    issue["candidate_assignee_ids"] = [new_assignee_id]
    issue["candidate_assignees"]    = [{"id": new_assignee_id, "name": new_assignee_name, "email": new_assignee_email}]
    issue["thread_message_ids"]     = {}
    issue.setdefault("action_emails_sent", set()).discard("accepted")
    issue["action_emails_sent"].discard("resolved")

    _update_slack_message(issue_id, "Reassigned")

    batch_update_issue(issue_id, {
        "assigned_to":         new_assignee_name,
        "reassigned_from":     old_assignee_name,
        "reassignment_reason": reason,
        "reassignment_time":   now,
        "status":              "Reassigned",
    })

    public_url = get_public_url()
    accept_url, reassign_url, done_url, ask_url = _build_action_urls(
        public_url, issue_id, issue.get("raised_by_id", ""), actor_id=new_assignee_id
    )
    thread_id = issue.get("thread_message_id")

    if new_assignee_name in EMAIL_WHITELIST:
        new_msg_id = send_assignment_email(
            to_email=new_assignee_email,
            to_name=new_assignee_name,
            issue_id=issue_id,
            issue_text=issue["description"],
            raised_by=issue["raised_by"],
            channel=issue["channel"],
            timestamp=issue["raised_time"],
            issue_type=issue["issue_type"],
            accept_url=accept_url,
            reassign_url=reassign_url,
            done_url=done_url,
            ask_url=ask_url,
            raiser_email=issue["raised_by_email"],
            reassigned_from=old_assignee_name,
            reassignment_reason=reason,
        )
        issue["thread_message_id"] = new_msg_id
        issue["thread_message_ids"][new_assignee_id] = new_msg_id

        send_reassign_notification_email(
            to_email=issue["raised_by_email"],
            raised_by=issue["raised_by"],
            issue_id=issue_id,
            issue_text=issue["description"],
            old_assignee=old_assignee_name,
            new_assignee=new_assignee_name,
            reason=reason,
            reassign_time=now,
            raiser_email=old_assignee_email,
            original_message_id=thread_id,
        )
    else:
        print(f"Skipping reassign emails for {new_assignee_name} (not in whitelist)")

    _save_issues()
    print(f"{issue_id} reassigned from {old_assignee_name} -> {new_assignee_name}")


def _send_assignment_email_bg(issue_id, actor_id, email_kwargs):
    """Send assignment email in background and store thread_message_id for this actor."""
    try:
        msg_id = send_assignment_email(**email_kwargs)
        if issue_id in issues:
            issues[issue_id].setdefault("thread_message_ids", {})[actor_id] = msg_id
            # Keep thread_message_id for backward compat (first email wins)
            if not issues[issue_id].get("thread_message_id"):
                issues[issue_id]["thread_message_id"] = msg_id
            _save_issues()
    except Exception as e:
        print(f"[ERROR] Assignment email failed for {issue_id}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.after_request
def set_response_headers(response):
    response.headers["ngrok-skip-browser-warning"] = "skip"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/slack/events", methods=["POST"])
def slack_events():
    if not signature_verifier.is_valid_request(request.get_data(), request.headers):
        return jsonify({"error": "Invalid signature"}), 403

    payload = request.json

    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload["challenge"]})

    event    = payload.get("event", {})
    event_id = payload.get("event_id", "")

    with _event_ids_lock:
        if event_id in processed_event_ids:
            return jsonify({"ok": True})
        processed_event_ids.add(event_id)
        if len(processed_event_ids) > 2000:
            processed_event_ids.clear()

    if (
        event.get("type") == "message"
        and not event.get("bot_id")
        and event.get("subtype") in (None, "file_share")
    ):
        threading.Thread(target=handle_new_message, args=(event,), daemon=True).start()

    return jsonify({"ok": True})


def handle_new_message(event):
    try:
        _handle_new_message_inner(event)
    except Exception as e:
        print(f"[ERROR] handle_new_message crashed: {e}")
        traceback.print_exc()


def _handle_new_message_inner(event):
    # Skip thread replies
    thread_ts = event.get("thread_ts")
    if thread_ts and thread_ts != event.get("ts"):
        print(f"Skipped thread reply in {event.get('channel')}")
        return

    text      = event.get("text", "")
    channel   = event.get("channel", "")
    user_id   = event.get("user", "")
    timestamp = event.get("ts", "")

    mentions = extract_mentions(text)
    if not mentions:
        return

    if is_acknowledgment(text):
        print(f"Skipped acknowledgment: {text[:60]}")
        return

    raiser_name, raiser_email = get_user_info(user_id)
    channel_name = get_channel_name(channel)
    raised_time  = datetime.fromtimestamp(float(timestamp)).strftime("%d %b %Y, %I:%M %p")
    description  = clean_slack_text(text)
    issue_type   = get_issue_type(text)
    public_url   = get_public_url()

    # Resolve all mentioned users first
    candidates = []
    for assignee_id in mentions:
        a_name, a_email = get_user_info(assignee_id)
        if not a_email:
            print(f"[WARN] No email for {assignee_id} ({a_name}), skipping")
            continue
        candidates.append({"id": assignee_id, "name": a_name, "email": a_email})

    if not candidates:
        return

    # ONE issue for all candidates — shared task card
    issue_id            = generate_issue_id()
    assigned_to_display = " / ".join(c["name"] for c in candidates)

    issues[issue_id] = {
        "issue_id":              issue_id,
        "description":           description,
        "issue_type":            issue_type,
        "raised_by":             raiser_name,
        "raised_by_id":          user_id,
        "raised_by_email":       raiser_email,
        "assigned_to":           assigned_to_display,  # all names; updated on acceptance
        "assigned_to_email":     "",                   # set when first person accepts
        "assigned_to_id":        "",                   # set when first person accepts
        "candidate_assignee_ids": [c["id"] for c in candidates],
        "candidate_assignees":    candidates,
        "channel":               channel_name,
        "channel_id":            channel,
        "raised_time":           raised_time,
        "working_started_time":  "",
        "completion_time":       "",
        "completion_message":    "",
        "status":                "",
        "resolution_duration":   "",
        "reassigned_from":       "",
        "reassignment_reason":   "",
        "reassignment_time":     "",
        "raised_ts":             timestamp,
        "action_emails_sent":    set(),
        "thread_message_id":     None,
        "thread_message_ids":    {},  # {actor_id: message_id}
        "accept_message_id":     None,
        "slack_ts":              None,
    }

    print(f"Raiser: {raiser_name} | Candidates: {assigned_to_display} | URL: {public_url}")

    # Post ONE shared Slack card immediately
    slack_ts = post_issue_notification(channel, issue_id, description, assigned_to_display, issue_type)
    issues[issue_id]["slack_ts"] = slack_ts
    _save_issues()

    threading.Thread(target=log_issue, args=(dict(issues[issue_id]),), daemon=True).start()

    # Send individual emails to each candidate (each email has their own actor_id in the accept URL)
    for candidate in candidates:
        if candidate["name"] in EMAIL_WHITELIST:
            accept_url, reassign_url, done_url, ask_url = _build_action_urls(
                public_url, issue_id, user_id, actor_id=candidate["id"]
            )
            email_kwargs = dict(
                to_email=candidate["email"],
                to_name=candidate["name"],
                issue_id=issue_id,
                issue_text=description,
                raised_by=raiser_name,
                channel=channel_name,
                timestamp=raised_time,
                issue_type=issue_type,
                accept_url=accept_url,
                reassign_url=reassign_url,
                done_url=done_url,
                ask_url=ask_url,
                raiser_email=raiser_email,
            )
            threading.Thread(
                target=_send_assignment_email_bg,
                args=(issue_id, candidate["id"], email_kwargs),
                daemon=True,
            ).start()
        else:
            print(f"Skipping email for {candidate['name']} (not in whitelist)")

    print(f"{issue_type} {issue_id} assigned to {assigned_to_display}")


@app.route("/slack/actions", methods=["POST"])
def slack_actions():
    if not signature_verifier.is_valid_request(request.get_data(), request.headers):
        return jsonify({"error": "Invalid signature"}), 403

    payload      = json.loads(request.form.get("payload", "{}"))
    payload_type = payload.get("type")

    if payload_type == "block_actions":
        action     = payload["actions"][0]
        action_id  = action["action_id"]
        issue_id   = action["value"]
        user_id    = payload["user"]["id"]
        channel    = payload["channel"]["id"]
        trigger_id = payload.get("trigger_id", "")

        issue = issues.get(issue_id)
        if not issue:
            return jsonify({"ok": True})

        candidate_ids = _get_candidate_ids(issue)

        if action_id == "accept_task":
            # Must be a candidate
            if user_id not in candidate_ids:
                slack_client.chat_postEphemeral(
                    channel=channel, user=user_id,
                    text=f"You are not assigned to {issue_id}.",
                )
                return jsonify({"ok": True})
            # Check if someone else already accepted
            current_accepter = issue.get("assigned_to_id")
            if current_accepter and current_accepter != user_id:
                slack_client.chat_postEphemeral(
                    channel=channel, user=user_id,
                    text=f"*{issue['assigned_to']}* already accepted {issue_id}.",
                )
                return jsonify({"ok": True})

            threading.Thread(
                target=_process_accepted,
                args=(issue_id, user_id),
                daemon=True,
            ).start()

        elif action_id == "done_task":
            current_accepter = issue.get("assigned_to_id")
            if current_accepter and current_accepter != user_id:
                # Task already accepted by someone else
                slack_client.chat_postEphemeral(
                    channel=channel, user=user_id,
                    text=f"Only *{issue['assigned_to']}* can mark {issue_id} as done.",
                )
                return jsonify({"ok": True})
            if not current_accepter and user_id not in candidate_ids:
                # Not a candidate at all
                slack_client.chat_postEphemeral(
                    channel=channel, user=user_id,
                    text=f"Only assigned team members can take action on {issue_id}.",
                )
                return jsonify({"ok": True})

            modal_view = {
                "type": "modal",
                "callback_id": "done_modal",
                # Store actor_id so view_submission knows who submitted
                "private_metadata": json.dumps({"issue_id": issue_id, "actor_id": user_id}),
                "title":  {"type": "plain_text", "text": "Mark as Done"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close":  {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*{issue_id}* — {issue['description'][:100]}"},
                    },
                    {
                        "type": "input",
                        "block_id": "completion_block",
                        "label": {"type": "plain_text", "text": "Completion Message"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "completion_message",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "Briefly describe what was done..."},
                            "min_length": 5,
                        },
                    },
                ],
            }
            # Synchronous — trigger_id has a 3-second expiry window
            try:
                slack_client.views_open(trigger_id=trigger_id, view=modal_view)
            except Exception as e:
                print(f"[ERROR] views_open failed for {issue_id}: {e}")

    elif payload_type == "view_submission":
        if payload["view"]["callback_id"] == "done_modal":
            metadata   = json.loads(payload["view"]["private_metadata"])
            issue_id   = metadata["issue_id"]
            actor_id   = metadata.get("actor_id", "")
            completion = payload["view"]["state"]["values"]["completion_block"]["completion_message"]["value"]
            issue      = issues.get(issue_id)
            if issue:
                threading.Thread(
                    target=_process_done,
                    args=(issue_id, completion, actor_id),
                    daemon=True,
                ).start()
            return jsonify({})

    return jsonify({"ok": True})


@app.route("/email/action", methods=["GET"])
def email_action():
    issue_id = request.args.get("issue_id", "")
    action   = request.args.get("action", "")
    token    = request.args.get("token", "")
    actor_id = request.args.get("actor_id", "")

    if not all([issue_id, action, token]):
        return "<h2>Invalid request</h2>", 400
    if token != generate_email_token(issue_id, action):
        return "<h2>Invalid or expired link</h2>", 403

    issue = issues.get(issue_id)
    if not issue:
        return (
            f"<html><body style='font-family:Arial;text-align:center;padding:60px;'>"
            f"<h2>Issue {issue_id} not found</h2>"
            f"<p>The bot may have restarted. Please update from Slack instead.</p>"
            f"</body></html>"
        ), 404

    if action in ("accept", "assign"):
        if issue["status"] in ("Accepted", "Resolved"):
            return _action_page("Already Accepted", issue_id, issue["status"], "#4A154B")

        # Validate the actor is a legitimate candidate
        candidate_ids = _get_candidate_ids(issue)
        effective_actor = actor_id if actor_id in candidate_ids else issue.get("assigned_to_id", "")
        if not effective_actor:
            return "<h2>Invalid accept link.</h2>", 403

        # Check if someone else already accepted
        current_accepter = issue.get("assigned_to_id")
        if current_accepter and current_accepter != effective_actor:
            return _action_page(
                f"Already Accepted by {issue['assigned_to']}",
                issue_id, "Accepted", "#4A154B"
            )

        threading.Thread(
            target=_process_accepted,
            args=(issue_id, effective_actor),
            daemon=True,
        ).start()
        return _action_page("Task Accepted", issue_id, "Accepted", "#4A154B")

    return "<h2>Unknown action</h2>", 400


@app.route("/email/reassign-form", methods=["GET", "POST"])
def email_reassign_form():
    if request.method == "GET":
        issue_id = request.args.get("issue_id", "")
        token    = request.args.get("token", "")

        if not issue_id or not token:
            return "<h2>Invalid request</h2>", 400
        if token != generate_email_token(issue_id, "reassign"):
            return "<h2>Invalid or expired link</h2>", 403

        issue = issues.get(issue_id)
        if not issue:
            return f"<h2>Issue {issue_id} not found</h2><p>The bot may have restarted.</p>", 404

        if issue["status"] == "Resolved":
            return _action_page("Already Resolved", issue_id, "Resolved", "#1D7A46")

        users = get_slack_users()
        options_html = "\n".join(
            f'<option value="{u["id"]}">{u["name"]} ({u["email"]})</option>'
            for u in users
            if u["email"] != issue.get("assigned_to_email")
        )

        return f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;">
        <div style="background:white;border-radius:10px;padding:40px;max-width:520px;width:90%;box-shadow:0 4px 16px rgba(0,0,0,0.1);">
            <h2 style="color:#E67E22;margin:0 0 6px;">Reassign Task</h2>
            <p style="color:#666;margin:0 0 20px;font-size:14px;">
                <strong>{issue_id}</strong> — {issue['description'][:100]}
            </p>
            <form method="POST">
                <input type="hidden" name="issue_id" value="{issue_id}">
                <input type="hidden" name="token" value="{token}">
                <label style="font-weight:bold;display:block;margin-bottom:6px;font-size:14px;">
                    Reassign To <span style="color:red;">*</span>
                </label>
                <select name="new_assignee_id" required
                    style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;font-size:14px;margin-bottom:16px;box-sizing:border-box;">
                    <option value="">— Select person —</option>
                    {options_html}
                </select>
                <label style="font-weight:bold;display:block;margin-bottom:6px;font-size:14px;">
                    Reason for Reassignment <span style="color:red;">*</span>
                </label>
                <textarea name="reason" required minlength="5" rows="4"
                    style="width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;resize:vertical;"
                    placeholder="Why are you reassigning this task?"></textarea>
                <button type="submit"
                    style="margin-top:16px;width:100%;background:#E67E22;color:white;border:none;padding:14px;border-radius:6px;font-size:16px;font-weight:bold;cursor:pointer;">
                    Reassign Task
                </button>
            </form>
        </div>
        </body></html>"""

    # POST
    issue_id        = request.form.get("issue_id", "")
    token           = request.form.get("token", "")
    new_assignee_id = request.form.get("new_assignee_id", "").strip()
    reason          = request.form.get("reason", "").strip()

    if token != generate_email_token(issue_id, "reassign"):
        return "<h2>Invalid token</h2>", 403

    issue = issues.get(issue_id)
    if not issue:
        return f"<h2>Issue {issue_id} not found</h2>", 404

    if not new_assignee_id:
        return "<h2>Please select a person to reassign to.</h2>", 400
    if len(reason) < 5:
        return "<h2>Please enter a reason (at least 5 characters).</h2>", 400

    if issue["status"] == "Resolved":
        return _action_page("Already Resolved", issue_id, "Resolved", "#1D7A46")

    threading.Thread(
        target=_process_reassign,
        args=(issue_id, new_assignee_id, reason, issue["assigned_to"]),
        daemon=True,
    ).start()

    new_name, _ = get_user_info(new_assignee_id)
    return _action_page(f"Task Reassigned to {new_name}", issue_id, "Reassigned", "#E67E22")


@app.route("/email/done-form", methods=["GET", "POST"])
def email_done_form():
    if request.method == "GET":
        issue_id = request.args.get("issue_id", "")
        token    = request.args.get("token", "")

        if not issue_id or not token:
            return "<h2>Invalid request</h2>", 400
        if token != generate_email_token(issue_id, "done"):
            return "<h2>Invalid or expired link</h2>", 403

        issue = issues.get(issue_id)
        if not issue:
            return f"<h2>Issue {issue_id} not found</h2><p>The bot may have restarted.</p>", 404

        return f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;">
        <div style="background:white;border-radius:10px;padding:40px;max-width:500px;width:90%;box-shadow:0 4px 16px rgba(0,0,0,0.1);">
            <h2 style="color:#1D7A46;margin:0 0 6px;">Mark as Done</h2>
            <p style="color:#666;margin:0 0 24px;font-size:14px;">
                <strong>{issue_id}</strong> — {issue['description'][:120]}
            </p>
            <form method="POST">
                <input type="hidden" name="issue_id" value="{issue_id}">
                <input type="hidden" name="token" value="{token}">
                <label style="font-weight:bold;display:block;margin-bottom:8px;font-size:14px;">
                    Completion Message <span style="color:red;">*</span>
                </label>
                <textarea name="completion_message" required minlength="5" rows="5"
                    style="width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;resize:vertical;"
                    placeholder="Briefly describe what was done..."></textarea>
                <button type="submit"
                    style="margin-top:16px;width:100%;background:#1D7A46;color:white;border:none;padding:14px;border-radius:6px;font-size:16px;font-weight:bold;cursor:pointer;">
                    Submit &amp; Mark Done
                </button>
            </form>
        </div>
        </body></html>"""

    # POST — actor is whoever accepted (or the person using the done link)
    issue_id           = request.form.get("issue_id", "")
    token              = request.form.get("token", "")
    completion_message = request.form.get("completion_message", "").strip()

    if token != generate_email_token(issue_id, "done"):
        return "<h2>Invalid token</h2>", 403

    issue = issues.get(issue_id)
    if not issue:
        return f"<h2>Issue {issue_id} not found</h2>", 404

    if len(completion_message) < 5:
        return "<h2>Please enter a longer completion message (at least 5 characters).</h2>", 400

    if issue["status"] == "Resolved":
        return _action_page("Already Resolved", issue_id, "Resolved", "#1D7A46")

    # For email-done, the actor is whoever accepted; fall back to first candidate
    actor_id = issue.get("assigned_to_id") or (
        issue.get("candidate_assignee_ids", [None])[0]
    )

    threading.Thread(
        target=_process_done,
        args=(issue_id, completion_message, actor_id),
        daemon=True,
    ).start()

    return _action_page("Task Marked as Done", issue_id, "Resolved", "#1D7A46")


@app.route("/email/ask-redirect", methods=["GET"])
def email_ask_redirect():
    issue_id = request.args.get("issue_id", "")
    token    = request.args.get("token", "")

    if not issue_id or not token:
        return "<h2>Invalid request</h2>", 400
    if token != generate_email_token(issue_id, "ask"):
        return "<h2>Invalid or expired link</h2>", 403

    issue = issues.get(issue_id)
    if not issue:
        return f"<h2>Issue {issue_id} not found</h2>", 404

    raiser_id = issue.get("raised_by_id", "")
    slack_url = f"slack://user?team={SLACK_TEAM_ID}&id={raiser_id}" if SLACK_TEAM_ID and raiser_id else ""
    fallback  = f"https://slack.com/app_redirect?channel={raiser_id}&team={SLACK_TEAM_ID}" if SLACK_TEAM_ID and raiser_id else ""

    return f"""<html>
    <head>
        <style>body{{margin:0;padding:0;background:white;}}</style>
        <script>
            window.location.replace("{slack_url}");
            setTimeout(function(){{ window.location.replace("{fallback}"); }}, 1500);
        </script>
    </head>
    <body></body>
    </html>"""


def _action_page(title, issue_id, status_label, color):
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
        <div style="background:white;border-radius:10px;padding:48px 40px;max-width:420px;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.1);">
            <div style="font-size:48px;color:{color};margin-bottom:16px;">&#10003;</div>
            <h2 style="color:{color};margin:0 0 12px;">{title}</h2>
            <p style="color:#555;">Issue <strong>{issue_id}</strong> is now: <strong>{status_label}</strong></p>
            <p style="color:#aaa;font-size:12px;margin-top:24px;">Chanakya — StayVista Issue Bot</p>
        </div>
    </body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Chanakya running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
