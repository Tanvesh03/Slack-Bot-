# Chanakya Bot — Team Communication Guide
### How to Assign Tasks and Communicate with the Bot

---

## What is Chanakya?

Chanakya is StayVista's automated task tracking bot. When you send a message in a Slack channel and **@mention** a team member, Chanakya automatically:

- Creates a task ticket (ISS-0001, ISS-0002, etc.)
- Sends an email notification to the assigned person
- Logs the task in Google Sheets
- Posts a status card in Slack with Accept and Mark Done buttons

---

## Section 1 — How to Assign a Task

### Basic Format
```
@PersonName <clear description of the task>
```

### Rules
- Always **@mention the person** you are assigning the task to
- Write the task description **in the same message** as the @mention
- Keep the message **specific and actionable**
- One message can mention **multiple people** — a separate ticket is created for each

---

## Section 2 — Message Format Examples

### ✅ GOOD Messages (These will create a task)

| Message | Why it works |
|---|---|
| `@Krutika Naik Villa Amethyst Saligao — Airbnb listing not showing. Please check and resolve.` | Clear assignee, clear problem, actionable |
| `@Sudesh Patil Guest is requesting early check-in for booking #BK2045. Please coordinate with the property.` | Specific booking reference, clear action |
| `@Tanvesh Bandodkar OTA reconciliation for April is pending. Please share the report by EOD.` | Clear deadline, clear deliverable |
| `@Ashish Chakor @Megha Prasad Please review the pricing for Villa Serenity — rates seem incorrect on Agoda.` | Multiple assignees — two tickets created |

---

### ❌ BAD Messages (These will be ignored or create incorrect tasks)

| Message | Why it fails | Fix |
|---|---|---|
| `@Krutika Naik okay` | Too short, sounds like acknowledgment | Add actual task description |
| `@Sudesh Patil got it` | Acknowledgment phrase — bot skips it | Don't @mention unless assigning a task |
| `@Tanvesh Bandodkar 👍` | No task description | Write what needs to be done |
| `check this` (no @mention) | No @mention — bot ignores it | Add @PersonName |
| `@Ashish Chakor` (no description) | @mention with no task | Add description after the name |

---

## Section 3 — Words That Will NOT Create a Task

The bot automatically ignores messages that contain only the following words after an @mention:

```
okay / ok / thanks / thank you / noted / working on it / got it /
sure / will do / acknowledged / understood / on it / will check /
checking / alright / done / checked / roger / received /
looking into it / ack
```

**Example:**
- `@Krutika Naik noted` → **Ignored** (acknowledgment)
- `@Krutika Naik noted, also please update the listing price` → **Task created** (message is longer than 100 characters and has an action)

---

## Section 4 — Handling Screenshots and Images

### Rule: Images are attachments only — bot reads typed text only

When you attach a screenshot or image to a message:
- The bot will **only read the text you typed**
- It will **NOT extract or read the content** of the image
- The image is stored as an attachment only

### ✅ Correct Way to Use Images
```
@Sudesh Patil Airbnb listing for Villa Amethyst is not showing 
in search results. Screenshot attached for reference.
[attach screenshot]
```
The task description will be: *"Airbnb listing for Villa Amethyst is not showing in search results. Screenshot attached for reference."*

### ❌ Incorrect Way
```
@Sudesh Patil [attach screenshot only — no typed text]
```
This will create a task with an empty or unclear description.

**Always type the task description clearly. Use images only as supporting evidence.**

---

## Section 5 — Thread Replies (Very Important)

### Rule: Replies inside a thread do NOT create new tasks

| Action | Result |
|---|---|
| New message in channel with @mention | ✅ Creates a new task |
| Reply inside an existing thread with @mention | ❌ Ignored — no new task |

### Use Threads For:
- Following up on an existing task
- Sharing updates or comments
- Asking questions related to the task
- Discussing the task with the team

### Use New Messages For:
- Assigning a completely new task
- Raising a fresh issue

### Example:
```
[Channel Message] @Krutika Naik Please check OTA pricing for Villa Pearl.
  └── [Thread Reply] @Krutika Naik any update on this?  ← NO new task created
  └── [Thread Reply] @Krutika Naik checking, will update by 3pm  ← NO new task created
```

---

## Section 6 — Task Types: Issue vs Query

The bot automatically classifies your message:

| If your message contains | Task Type |
|---|---|
| A question mark `?` | **Query** |
| No question mark | **Issue** |

### Examples:
- `@Tanvesh Bandodkar Can you share the Agoda report for May?` → **Query**
- `@Tanvesh Bandodkar Share the Agoda report for May.` → **Issue**

---

## Section 7 — What Happens After You Send a Task

1. **Slack card appears** in the channel with Issue ID, assignee, description, and status
2. **Email sent** to the assigned person with Accept / Reassign / Done / Ask Question buttons
3. **Google Sheet** is updated with the task entry
4. Assigned person clicks **Accept** → status updates to Accepted in Slack and Sheets
5. Assigned person clicks **Mark Done** → enters completion message → status updates to Resolved

---

## Section 8 — Quick Reference Card

```
✅ DO                                   ❌ DON'T
─────────────────────────────────────   ──────────────────────────────────
@Mention + clear task description       Send @mention with only "ok/noted"
Type the full task in the message       Rely on images to explain the task
Use new channel message for new tasks   Reply in thread to assign new task
Be specific — include property/booking  Send vague 1-word instructions
Attach images as supporting reference   Expect bot to read image content
```

---

## Section 9 — Accepted Email Notification Users

Emails are currently sent only when tasks are assigned to the following team members:

- Ashish Chakor
- Krutika Naik
- Kushal Pandey
- Megha Prasad
- Shubhangi Sharma
- Sonu Meena
- Sudesh Patil
- Tanvesh Bandodkar

Tasks assigned to other team members will still create a Slack card and log to Google Sheets — but no email will be sent.

> To add or remove users from the email list, contact the bot administrator.

---

*Chanakya — StayVista Issue Management Bot | Internal Use Only*
