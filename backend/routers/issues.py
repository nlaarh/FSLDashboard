"""Issues router — GitHub-backed issue reporting, comments, triage."""

import os, re, json as _json
import requests as _requests
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from utils import _ET

router = APIRouter()

# ── GitHub & Email config ────────────────────────────────────────────────────
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GITHUB_REPO = "nlaarh/FSLDashboard"
_ISSUES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "issues.json")
_AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
_AGENTMAIL_INBOX = os.environ.get("AGENTMAIL_INBOX", "fslnyaaa@agentmail.to")

# ── Admin PIN (for PIN-protected endpoints) ──────────────────────────────────
_ADMIN_PIN = os.getenv('ADMIN_PIN', '121838')


def _check_pin(request: Request):
    pin = request.headers.get('X-Admin-Pin', '')
    if pin != _ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Invalid PIN")


def _send_issue_email(to_email: str, subject: str, body_text: str):
    """Send email via AgentMail API (fire-and-forget, never raises)."""
    if not _AGENTMAIL_API_KEY or not to_email:
        return
    try:
        _requests.post(
            f"https://api.agentmail.to/v0/inboxes/{_AGENTMAIL_INBOX}/messages/send",
            headers={"Authorization": f"Bearer {_AGENTMAIL_API_KEY}", "Content-Type": "application/json"},
            json={"to": [to_email], "subject": subject, "text": body_text},
            timeout=10,
        )
    except Exception:
        pass


@router.post("/api/issues")
def create_issue(body: dict):
    """Create a user-reported issue. Pushes to GitHub Issues, falls back to local file."""
    description = (body.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    severity = body.get("severity", "medium")
    if severity not in ("low", "medium", "high"):
        severity = "medium"
    page = body.get("page", "/")
    reporter = body.get("reporter", "Anonymous")
    email = body.get("email", "")

    now_et = datetime.now(_ET)
    timestamp = now_et.strftime("%Y-%m-%d %I:%M %p ET")
    title_short = description[:60] + ("..." if len(description) > 60 else "")
    title = f"[User Report] {severity.upper()}: {title_short}"
    email_line = f"\n**Email:** {email}" if email else ""
    gh_body = (
        f"**Reporter:** {reporter}{email_line}\n"
        f"**Page:** `{page}`\n"
        f"**Severity:** {severity}\n"
        f"**Reported at:** {timestamp}\n\n"
        f"---\n\n"
        f"{description}"
    )

    # Try GitHub API first
    if _GITHUB_TOKEN:
        try:
            resp = _requests.post(
                f"https://api.github.com/repos/{_GITHUB_REPO}/issues",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={
                    "title": title,
                    "body": gh_body,
                    "labels": ["user-reported", severity, "status:backlog"],
                },
                timeout=10,
            )
            if resp.status_code in (201, 200):
                data = resp.json()
                issue_num = data.get("number")
                issue_url = data.get("html_url")
                # Send confirmation email to reporter
                if email:
                    _send_issue_email(
                        email,
                        f"FSL App — Issue #{issue_num} received",
                        f"Hi {reporter},\n\n"
                        f"Your issue report has been received and logged as #{issue_num}.\n\n"
                        f"  Page: {page}\n"
                        f"  Severity: {severity}\n"
                        f"  Description: {description}\n\n"
                        f"We'll review it shortly. You can track progress here:\n{issue_url}\n\n"
                        f"— FSL App Team"
                    )
                # Also notify the AgentMail inbox for triage monitoring
                _send_issue_email(
                    _AGENTMAIL_INBOX,
                    f"[NEW ISSUE #{issue_num}] {severity.upper()}: {title_short}",
                    f"New issue reported — needs triage.\n\n"
                    f"  Issue:    #{issue_num}\n"
                    f"  Reporter: {reporter} ({email or 'no email'})\n"
                    f"  Page:     {page}\n"
                    f"  Severity: {severity}\n"
                    f"  GitHub:   {issue_url}\n\n"
                    f"Description:\n{description}"
                )
                return {"ok": True, "method": "github", "issue_number": issue_num, "url": issue_url}
        except Exception:
            pass  # Fall through to local

    # Fallback: local JSON file
    issue = {
        "title": title,
        "body": gh_body,
        "page": page,
        "severity": severity,
        "reporter": reporter,
        "email": email,
        "created_at": now_et.isoformat(),
        "status": "reported",
    }
    try:
        existing = _json.load(open(_ISSUES_FILE)) if os.path.exists(_ISSUES_FILE) else []
    except Exception:
        existing = []
    existing.append(issue)
    with open(_ISSUES_FILE, "w") as f:
        _json.dump(existing, f, indent=2)
    return {"ok": True, "method": "local", "issue_number": len(existing)}


@router.get("/api/issues")
def list_issues(state: str = "open"):
    """List user-reported issues. Reads from GitHub, falls back to local file."""
    if _GITHUB_TOKEN:
        try:
            resp = _requests.get(
                f"https://api.github.com/repos/{_GITHUB_REPO}/issues",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                },
                params={"labels": "user-reported", "state": state, "per_page": 50},
                timeout=10,
            )
            if resp.status_code == 200:
                issues = []
                for iss in resp.json():
                    labels = [l.get("name", "") for l in iss.get("labels", [])]
                    sev = "medium"
                    for s in ("high", "medium", "low"):
                        if s in labels:
                            sev = s
                            break
                    status = "backlog"
                    for lbl in labels:
                        if lbl.startswith("status:"):
                            status = lbl.split(":", 1)[1]
                            break
                    issues.append({
                        "number": iss["number"],
                        "title": iss["title"],
                        "body": iss.get("body", ""),
                        "severity": sev,
                        "status": status,
                        "state": iss["state"],
                        "created_at": iss["created_at"],
                        "url": iss["html_url"],
                        "labels": labels,
                        "comments": iss.get("comments", 0),
                    })
                return {"issues": issues, "source": "github"}
        except Exception:
            pass

    # Fallback: local file
    try:
        existing = _json.load(open(_ISSUES_FILE)) if os.path.exists(_ISSUES_FILE) else []
    except Exception:
        existing = []
    return {"issues": existing, "source": "local"}


@router.get("/api/issues/{issue_number}")
def get_issue(issue_number: int):
    """Get a single issue with its comments."""
    if not _GITHUB_TOKEN:
        raise HTTPException(status_code=501, detail="GitHub not configured")
    try:
        # Fetch issue
        resp = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Issue not found")
        iss = resp.json()
        labels = [l.get("name", "") for l in iss.get("labels", [])]
        sev = "medium"
        for s in ("high", "medium", "low"):
            if s in labels:
                sev = s
                break
        status = "backlog"
        for lbl in labels:
            if lbl.startswith("status:"):
                status = lbl.split(":", 1)[1]
                break
        # Fetch comments
        comments = []
        if iss.get("comments", 0) > 0:
            cr = _requests.get(
                f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}/comments",
                headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            if cr.status_code == 200:
                for c in cr.json():
                    comments.append({
                        "id": c["id"],
                        "body": c["body"],
                        "user": c["user"]["login"],
                        "created_at": c["created_at"],
                    })
        return {
            "number": iss["number"],
            "title": iss["title"],
            "body": iss.get("body", ""),
            "severity": sev,
            "status": status,
            "state": iss["state"],
            "created_at": iss["created_at"],
            "updated_at": iss.get("updated_at"),
            "closed_at": iss.get("closed_at"),
            "url": iss["html_url"],
            "labels": labels,
            "comments": comments,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/issues/{issue_number}/comments")
def add_issue_comment(issue_number: int, body: dict):
    """Add a comment to an issue. Open to all users (no PIN required)."""
    comment = (body.get("comment") or "").strip()
    commenter = (body.get("name") or "").strip() or "Anonymous"
    if not comment:
        raise HTTPException(status_code=400, detail="Comment is required")
    if not _GITHUB_TOKEN:
        raise HTTPException(status_code=501, detail="GitHub not configured")
    # Prefix comment with commenter name so GitHub shows who said what
    gh_comment = f"**{commenter}:**\n\n{comment}"
    try:
        resp = _requests.post(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}/comments",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            json={"body": gh_comment},
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=resp.status_code, detail="Failed to add comment")
        # Try to email reporter
        _notify_reporter_on_comment(issue_number, comment)
        return {"ok": True, "comment": resp.json()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_ISSUE_STATUSES = ["backlog", "acknowledged", "in-progress", "testing", "released", "closed", "cancelled"]

@router.patch("/api/issues/{issue_number}")
def update_issue(issue_number: int, body: dict, request: Request):
    """Update issue workflow status and/or GitHub state. PIN-protected."""
    _check_pin(request)
    if not _GITHUB_TOKEN:
        raise HTTPException(status_code=501, detail="GitHub not configured")

    new_status = body.get("status")
    if new_status and new_status not in _ISSUE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(_ISSUE_STATUSES)}")

    # First, read current issue to get existing labels
    try:
        cur = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if cur.status_code != 200:
            raise HTTPException(status_code=cur.status_code, detail="Issue not found")
        current = cur.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    current_labels = [l["name"] for l in current.get("labels", [])]

    payload = {}
    if new_status:
        # Remove old status labels, add new one
        labels = [l for l in current_labels if not l.startswith("status:")]
        labels.append(f"status:{new_status}")
        payload["labels"] = labels
        # Auto-close on "released", "closed", "cancelled"; reopen otherwise
        if new_status in ("released", "closed", "cancelled"):
            payload["state"] = "closed"
            payload["state_reason"] = "completed" if new_status in ("released", "closed") else "not_planned"
        elif current["state"] == "closed":
            payload["state"] = "open"

    if "state" in body and "state" not in payload:
        payload["state"] = body["state"]
    if "state_reason" in body and "state_reason" not in payload:
        payload["state_reason"] = body["state_reason"]

    if not payload:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        resp = _requests.patch(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to update issue")
        iss = resp.json()
        result_labels = [l["name"] for l in iss.get("labels", [])]
        # Email reporter about status change
        if new_status:
            _notify_reporter_status(issue_number, new_status, new_status)
        return {"ok": True, "state": iss["state"], "status": new_status, "labels": result_labels}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _extract_reporter_email(issue_body: str) -> str:
    """Extract reporter email from issue body markdown."""
    m = re.search(r'\*\*Email:\*\*\s*(\S+)', issue_body or "")
    return m.group(1) if m else ""


def _notify_reporter_on_comment(issue_number: int, comment: str):
    """Send email to reporter when a comment is added."""
    try:
        resp = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            email = _extract_reporter_email(resp.json().get("body", ""))
            if email:
                _send_issue_email(
                    email,
                    f"FSL App — Update on Issue #{issue_number}",
                    f"A new comment was added to your issue #{issue_number}:\n\n"
                    f"{comment}\n\n"
                    f"View the full issue: {resp.json().get('html_url', '')}\n\n"
                    f"— FSL App Team"
                )
    except Exception:
        pass


def _notify_reporter_status(issue_number: int, new_status: str, _unused: str = ""):
    """Send email to reporter when issue workflow status changes."""
    try:
        resp = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
            headers={"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            iss = resp.json()
            email = _extract_reporter_email(iss.get("body", ""))
            if email:
                _send_issue_email(
                    email,
                    f"FSL App — Issue #{issue_number} status: {new_status}",
                    f"Your issue #{issue_number} has been updated to: {new_status.upper()}\n\n"
                    f"Title: {iss.get('title', '')}\n\n"
                    f"View details: {iss.get('html_url', '')}\n\n"
                    f"— FSL App Team"
                )
    except Exception:
        pass


@router.post("/api/issues/triage")
def triage_issues(request: Request):
    """Auto-triage: acknowledge all backlog issues, comment, email reporters.
    PIN-protected. Returns list of triaged issue numbers."""
    _check_pin(request)
    if not _GITHUB_TOKEN:
        raise HTTPException(status_code=501, detail="GitHub not configured")
    _gh_headers = {"Authorization": f"token {_GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # Fetch open issues with user-reported label
    try:
        resp = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/issues",
            headers=_gh_headers,
            params={"labels": "user-reported", "state": "open", "per_page": 50},
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch issues")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    triaged = []
    for iss in resp.json():
        labels = [l["name"] for l in iss.get("labels", [])]
        # Only triage issues still in backlog
        if "status:backlog" not in labels:
            continue

        issue_number = iss["number"]
        reporter = "there"
        m = re.search(r'\*\*Reporter:\*\*\s*(\S+)', iss.get("body", ""))
        if m:
            reporter = m.group(1)
        email = _extract_reporter_email(iss.get("body", ""))
        severity = "medium"
        for s in ("high", "medium", "low"):
            if s in labels:
                severity = s
                break

        # Post acknowledgement comment
        ack_comment = (
            f"**FSL App — Auto-Triage**\n\n"
            f"Hi {reporter}, thanks for reporting this issue. "
            f"It has been reviewed and moved to **Acknowledged**.\n\n"
            f"{'This is marked as **high** severity and will be prioritized.' if severity == 'high' else 'We will look into this shortly.'}\n\n"
            f"You'll receive email updates as the status changes."
        )
        try:
            _requests.post(
                f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}/comments",
                headers=_gh_headers,
                json={"body": ack_comment},
                timeout=10,
            )
        except Exception:
            pass

        # Update labels: backlog -> acknowledged
        new_labels = [l for l in labels if not l.startswith("status:")]
        new_labels.append("status:acknowledged")
        try:
            _requests.patch(
                f"https://api.github.com/repos/{_GITHUB_REPO}/issues/{issue_number}",
                headers=_gh_headers,
                json={"labels": new_labels},
                timeout=10,
            )
        except Exception:
            pass

        # Email reporter
        if email:
            _send_issue_email(
                email,
                f"FSL App — Issue #{issue_number} acknowledged",
                f"Hi {reporter},\n\n"
                f"Your issue #{issue_number} has been reviewed and acknowledged.\n\n"
                f"Title: {iss.get('title', '')}\n"
                f"Severity: {severity}\n\n"
                f"We're on it. You'll receive updates as progress is made.\n\n"
                f"View: {iss.get('html_url', '')}\n\n"
                f"— FSL App Team"
            )

        triaged.append({"number": issue_number, "title": iss["title"], "severity": severity})

    return {"triaged": triaged, "count": len(triaged)}
