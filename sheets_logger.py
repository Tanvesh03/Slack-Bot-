"""
sheets_logger.py — Logs and updates issue data in Google Sheets.

Two tabs:
  "Issues"  — 13 display columns (human-readable, clean)
  "BotData" — all operational fields (auto-managed, used for restart persistence)
"""

import os
import json as json_lib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
SHEET_NAME = "Issues"

COLUMNS = [
    "Issue ID",
    "Issue Description",
    "Raised By",
    "Assigned To",
    "Raised Date",
    "Raised Time",
    "Working Started Date",
    "Working Started Time",
    "Task Completion Date",
    "Task Completion Time",
    "Completion Message",
    "Current Status",
    "Resolution Duration",
    "Reassigned From",
    "Reassignment Reason",
    "Reassignment Time",
]

FIELD_MAP = {
    "status":               "Current Status",
    "completion_message":   "Completion Message",
    "resolution_duration":  "Resolution Duration",
    "reassigned_from":      "Reassigned From",
    "reassignment_reason":  "Reassignment Reason",
    "reassignment_time":    "Reassignment Time",
    "assigned_to":          "Assigned To",
}

SPLIT_FIELDS = {
    "working_started_time": ("Working Started Date", "Working Started Time"),
    "completion_time":      ("Task Completion Date",  "Task Completion Time"),
}

def _get_creds():
    # Support JSON string (Railway env var) or file path (local)
    json_content = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")
    if json_content:
        info = json_lib.loads(json_content)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=SCOPES
    )


def _get_sheet():
    client = gspread.authorize(_get_creds())
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


def _ensure_headers(sheet):
    existing = sheet.row_values(1)
    if not existing:
        sheet.append_row(COLUMNS)
        return
    missing = [col for col in COLUMNS if col not in existing]
    if missing:
        start_col = len(existing) + 1
        for i, col in enumerate(missing):
            sheet.update_cell(1, start_col + i, col)


def _split_timestamp(timestamp: str):
    try:
        dt = datetime.strptime(timestamp, "%d %b %Y, %I:%M %p")
        return dt.strftime("%d %b %Y"), dt.strftime("%I:%M %p")
    except Exception:
        return "", ""


def log_issue(issue: dict):
    try:
        sheet = _get_sheet()
        _ensure_headers(sheet)

        raised_date, raised_time = _split_timestamp(issue.get("raised_time", ""))
        ws_date, ws_time = _split_timestamp(issue.get("working_started_time", ""))
        tc_date, tc_time = _split_timestamp(issue.get("completion_time", ""))

        row = [
            issue.get("issue_id", ""),
            issue.get("description", ""),
            issue.get("raised_by", ""),
            issue.get("assigned_to", ""),
            raised_date,
            raised_time,
            ws_date,
            ws_time,
            tc_date,
            tc_time,
            issue.get("completion_message", ""),
            issue.get("status", ""),
            issue.get("resolution_duration", ""),
            issue.get("reassigned_from", ""),
            issue.get("reassignment_reason", ""),
            issue.get("reassignment_time", ""),
        ]
        sheet.append_row(row)
        print(f"Logged {issue['issue_id']} to Issues sheet")
    except Exception as e:
        print(f"Failed to log to Google Sheets: {e}")


def update_issue_status(issue_id: str, field: str, value: str):
    try:
        sheet = _get_sheet()
        cell = sheet.find(issue_id, in_column=1)
        if not cell:
            print(f"Issue {issue_id} not found in sheet")
            return

        if field in SPLIT_FIELDS:
            date_col_name, time_col_name = SPLIT_FIELDS[field]
            date_str, time_str = _split_timestamp(value)
            sheet.update_cell(cell.row, COLUMNS.index(date_col_name) + 1, date_str)
            sheet.update_cell(cell.row, COLUMNS.index(time_col_name) + 1, time_str)
            return

        col_name = FIELD_MAP.get(field)
        if not col_name:
            return
        sheet.update_cell(cell.row, COLUMNS.index(col_name) + 1, value)
        print(f"Updated {col_name} for {issue_id}")
    except Exception as e:
        print(f"Failed to update Sheets for {issue_id}: {e}")


