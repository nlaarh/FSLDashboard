"""Email draft templates for admin actions.

Generates Outlook Web compose URLs so admins can send personalized
welcome / password-changed emails without needing SMTP config.
"""

import os
import urllib.parse

_ON_AZURE = bool(os.environ.get("WEBSITE_SITE_NAME"))
_APP_URL = "https://fslapp-nyaaa.azurewebsites.net" if _ON_AZURE else "http://localhost:8000"
_OUTLOOK_BASE = "https://outlook.cloud.microsoft/mail/deeplink/compose"


def _compose_url(to: str, subject: str, body: str) -> str:
    """Build an Outlook Web compose deeplink."""
    params = {
        "to": to,
        "subject": subject,
        "body": body,
    }
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{_OUTLOOK_BASE}?{qs}"


def _welcome_body(username, name, password, role, department):
    dept_line = f"Department: {department.upper()}\n" if department else ""
    role_line = f"Role: {role}\n" if role else ""
    return (
        f"Hi {name},\n\n"
        f"Your FleetPulse account has been created. Here are your login details:\n\n"
        f"URL: {_APP_URL}/login\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        f"{role_line}"
        f"{dept_line}"
        f"\n"
        f"Please log in and change your password after your first login.\n\n"
        f"If you have any questions, reach out to the admin team.\n\n"
        f"— FleetPulse Team"
    )


def welcome_email_url(
    username: str,
    name: str,
    email: str,
    password: str,
    role: str = "",
    department: str = "",
) -> dict:
    """Return Outlook compose URL + plain text for a new-account welcome email."""
    subject = "Welcome to FleetPulse — Your Account is Ready"
    body = _welcome_body(username, name, password, role, department)
    return {
        "url": _compose_url(email, subject, body),
        "subject": subject,
        "body": body,
        "to": email,
    }


def _password_changed_body(username, name, password):
    return (
        f"Hi {name},\n\n"
        f"Your FleetPulse password has been reset by an administrator.\n\n"
        f"URL: {_APP_URL}/login\n"
        f"Username: {username}\n"
        f"New Password: {password}\n\n"
        f"Please log in and change your password to something only you know.\n\n"
        f"If you did not request this change, contact the admin team immediately.\n\n"
        f"— FleetPulse Team"
    )


def password_changed_email_url(
    username: str,
    name: str,
    email: str,
    password: str,
) -> dict:
    """Return Outlook compose URL + plain text for a password-changed notification."""
    subject = "FleetPulse Password Changed"
    body = _password_changed_body(username, name, password)
    return {
        "url": _compose_url(email, subject, body),
        "subject": subject,
        "body": body,
        "to": email,
    }
