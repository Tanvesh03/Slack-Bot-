"""
email_sender.py — Automated email notifications via Gmail SMTP.

Thread chain per issue:
  New Task Assigned  →  Reply: Task Accepted  →  Reply: Task Resolved
All three emails share the same Gmail thread via Message-ID / In-Reply-To / References.
"""

import smtplib
import os
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

EMAIL_ADDRESS = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _send_email(to_email: str, subject: str, html_body: str,
                cc_email: str = None, in_reply_to: str = None, references: str = None):
    """Send an HTML email. Returns its Message-ID for thread chaining."""
    message_id = f"<{uuid.uuid4()}@stayvista.chanakya>"
    msg = MIMEMultipart("alternative")
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = f"Chanakya - StayVista Issue Bot <{EMAIL_ADDRESS}>"
    msg["To"] = to_email
    if cc_email:
        msg["Cc"] = cc_email
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    msg.attach(MIMEText(html_body, "html"))
    recipients = [to_email] + ([cc_email] if cc_email else [])
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, recipients, msg.as_string())
        print(f"Email sent to {to_email}: {subject}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
    return message_id


def _row(label, value, shaded=False):
    bg = "background:#f4ecf5;" if shaded else ""
    return (
        f'<tr style="{bg}">'
        f'<td style="padding:10px;font-weight:bold;width:40%;border:1px solid #ddd;">{label}</td>'
        f'<td style="padding:10px;border:1px solid #ddd;">{value}</td>'
        f"</tr>"
    )


def _buttons_html(accept_url=None, reassign_url=None, done_url=None, ask_url=None):
    if not any([accept_url, reassign_url, done_url, ask_url]):
        return (
            '<p style="background:#f4ecf5;padding:12px;border-left:4px solid #4A154B;border-radius:4px;">'
            "Please update the status from the Slack channel.</p>"
        )
    btns = ""
    if accept_url:
        btns += f'''<a href="{accept_url}"
           style="display:inline-block;background:#4A154B;color:white;padding:12px 28px;
                  border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px;margin:4px;">
           Accept
        </a>'''
    if reassign_url:
        btns += f'''<a href="{reassign_url}"
           style="display:inline-block;background:#E67E22;color:white;padding:12px 28px;
                  border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px;margin:4px;">
           Reassign
        </a>'''
    if done_url:
        btns += f'''<a href="{done_url}"
           style="display:inline-block;background:#1D7A46;color:white;padding:12px 28px;
                  border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px;margin:4px;">
           Done
        </a>'''

    ask_section = ""
    if ask_url:
        ask_section = f'''
        <div style="text-align:center;margin-top:12px;">
            <a href="{ask_url}"
               style="display:inline-block;background:#2196F3;color:white;padding:10px 24px;
                      border-radius:6px;text-decoration:none;font-weight:bold;font-size:13px;">
               💬 Ask Question
            </a>
            <p style="color:#888;font-size:11px;margin-top:4px;">
                Need clarification? Ask the raiser directly via Slack DM.
            </p>
        </div>'''

    return f'''
    <div style="text-align:center;margin:28px 0 4px;">{btns}</div>
    <p style="text-align:center;color:#888;font-size:12px;margin-top:6px;">
        <strong>Accept</strong> to start working &nbsp;|&nbsp;
        <strong>Reassign</strong> if wrong person &nbsp;|&nbsp;
        <strong>Done</strong> once completed
    </p>
    {ask_section}'''


# ── 1. Initial assignment email ────────────────────────────────────────────────

def send_assignment_email(
    to_email, to_name, issue_id, issue_text,
    raised_by, channel, timestamp,
    issue_type="Issue", accept_url=None, reassign_url=None,
    done_url=None, ask_url=None, raiser_email=None,
    reassigned_from=None, reassignment_reason=None
):
    """
    Sent on issue creation (or reassignment) to the assignee.
    Returns Message-ID — save as thread_message_id.
    """
    label = "Query" if issue_type == "Query" else "Issue"
    subject = "New Task Assigned"

    reassign_notice = ""
    if reassigned_from:
        reassign_notice = f'''
        <div style="background:#FFF3CD;border-left:4px solid #E67E22;padding:12px;border-radius:4px;margin-bottom:16px;">
            <strong>🔄 Reassigned Task</strong><br>
            Previously assigned to <strong>{reassigned_from}</strong>.<br>
            Reason: <em>{reassignment_reason or "—"}</em>
        </div>'''

    rows = (
        _row("Issue ID", f"<strong>{issue_id}</strong>", shaded=True)
        + _row("Type", label)
        + _row("Description", issue_text, shaded=True)
        + _row("Raised By", raised_by)
        + _row("Timestamp", timestamp, shaded=True)
        + _row("Status", "—")
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#2c2c2c;max-width:600px;margin:auto;">
      <div style="background:#4A154B;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">New Task Assigned — {issue_id}</h2>
      </div>
      <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
        {reassign_notice}
        <p>Hi <strong>{to_name}</strong>,</p>
        <p>A new {label.lower()} has been assigned to you. Please review and take action.</p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;">{rows}</table>
        {_buttons_html(accept_url, reassign_url, done_url, ask_url)}
        <p style="color:#888;font-size:12px;margin-top:24px;">Chanakya — StayVista Issue Management Bot</p>
      </div>
    </body></html>"""
    return _send_email(to_email, subject, html)


# ── 2. Accept reply ────────────────────────────────────────────────────────────

def send_accepted_email(
    to_email, to_name, issue_id, issue_text,
    assignee_name, raised_by,
    raiser_email=None, original_message_id=None
):
    """
    Sent (CC raiser) when assignee clicks Accept.
    Returns Message-ID — save as accept_message_id.
    """
    subject = "Re: New Task Assigned"

    rows = (
        _row("Issue ID", f"<strong>{issue_id}</strong>", shaded=True)
        + _row("Description", issue_text)
        + _row("Raised By", raised_by, shaded=True)
        + _row("Accepted By", assignee_name)
        + _row(
            "Status",
            '<span style="background:#ff9800;color:white;padding:4px 10px;border-radius:4px;font-weight:bold;">Accepted</span>',
            shaded=True,
        )
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#2c2c2c;max-width:600px;margin:auto;">
      <div style="background:#4A154B;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">Task Accepted — {issue_id}</h2>
      </div>
      <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
        <p>Hi <strong>{raised_by}</strong>,</p>
        <p><strong>{assignee_name}</strong> has accepted the task and started working on it.</p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;">{rows}</table>
        <p style="color:#888;font-size:12px;margin-top:24px;">Chanakya — StayVista Issue Management Bot</p>
      </div>
    </body></html>"""
    return _send_email(to_email, subject, html, cc_email=raiser_email, in_reply_to=original_message_id)


# ── 3. Reassign notification ───────────────────────────────────────────────────

def send_reassign_notification_email(
    to_email, raised_by, issue_id, issue_text,
    old_assignee, new_assignee, reason, reassign_time,
    raiser_email=None, original_message_id=None
):
    """
    Sent to raiser (CC old assignee) when task is reassigned.
    """
    subject = "Re: New Task Assigned"

    rows = (
        _row("Issue ID", f"<strong>{issue_id}</strong>", shaded=True)
        + _row("Description", issue_text)
        + _row("Previously Assigned To", old_assignee, shaded=True)
        + _row("Reassigned To", f"<strong>{new_assignee}</strong>")
        + _row("Reason", f"<em>{reason}</em>", shaded=True)
        + _row("Reassigned At", reassign_time)
        + _row(
            "Status",
            '<span style="background:#E67E22;color:white;padding:4px 10px;border-radius:4px;font-weight:bold;">Reassigned</span>',
            shaded=True,
        )
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#2c2c2c;max-width:600px;margin:auto;">
      <div style="background:#E67E22;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">Task Reassigned — {issue_id}</h2>
      </div>
      <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
        <p>Hi <strong>{raised_by}</strong>,</p>
        <p>Your task has been reassigned from <strong>{old_assignee}</strong> to <strong>{new_assignee}</strong>.</p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;">{rows}</table>
        <p style="color:#888;font-size:12px;margin-top:24px;">Chanakya — StayVista Issue Management Bot</p>
      </div>
    </body></html>"""
    return _send_email(to_email, subject, html, cc_email=raiser_email, in_reply_to=original_message_id)


# ── 4. Resolved reply ──────────────────────────────────────────────────────────

def send_resolved_email(
    to_email, to_name, issue_id, issue_text,
    assignee_name, raised_by,
    completion_message, resolution_duration, completion_time,
    raiser_email=None, original_message_id=None, accept_message_id=None
):
    """
    Sent (CC raiser) when Done is submitted.
    """
    subject = "Re: New Task Assigned"

    if original_message_id and accept_message_id:
        in_reply_to = accept_message_id
        references = f"{original_message_id} {accept_message_id}"
    elif original_message_id:
        in_reply_to = original_message_id
        references = original_message_id
    else:
        in_reply_to = references = None

    rows = (
        _row("Issue ID", f"<strong>{issue_id}</strong>", shaded=True)
        + _row("Description", issue_text)
        + _row("Raised By", raised_by, shaded=True)
        + _row("Resolved By", assignee_name)
        + _row("Completion Time", completion_time, shaded=True)
        + _row("Resolution Duration", resolution_duration)
        + _row("Completion Message", f"<em>{completion_message}</em>", shaded=True)
        + _row(
            "Status",
            '<span style="background:#1D7A46;color:white;padding:4px 10px;border-radius:4px;font-weight:bold;">Resolved</span>',
        )
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#2c2c2c;max-width:600px;margin:auto;">
      <div style="background:#1D7A46;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">Task Resolved — {issue_id}</h2>
      </div>
      <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
        <p>Hi <strong>{raised_by}</strong>,</p>
        <p>Task <strong>{issue_id}</strong> has been resolved by <strong>{assignee_name}</strong>.</p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;">{rows}</table>
        <p style="background:#e8f5ee;padding:12px;border-left:4px solid #1D7A46;border-radius:4px;">
          If the issue recurs, please raise a new issue in the Slack channel.
        </p>
        <p style="color:#888;font-size:12px;margin-top:24px;">Chanakya — StayVista Issue Management Bot</p>
      </div>
    </body></html>"""
    return _send_email(to_email, subject, html, cc_email=raiser_email, in_reply_to=in_reply_to, references=references)
