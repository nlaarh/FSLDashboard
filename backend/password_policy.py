"""Shared password policy helpers."""

MIN_PASSWORD_LENGTH = 12
PASSWORD_SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:',.<>?/`~"


def password_policy_issues(password: str) -> list[str]:
    """Return human-readable policy gaps for a password."""
    issues = []
    if len(password or "") < MIN_PASSWORD_LENGTH:
        issues.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if not any(c.isupper() for c in password or ""):
        issues.append("one uppercase letter")
    if not any(c.islower() for c in password or ""):
        issues.append("one lowercase letter")
    if not any(c.isdigit() for c in password or ""):
        issues.append("one number")
    if not any(c in PASSWORD_SPECIAL_CHARS for c in password or ""):
        issues.append("one special character")
    return issues


def password_policy_error(password: str) -> str:
    issues = password_policy_issues(password)
    return f"Password must contain: {', '.join(issues)}" if issues else ""
