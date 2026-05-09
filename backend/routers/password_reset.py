"""Password reset endpoints — forgot + PIN verify + reset flow with email delivery."""

import os, secrets, time, logging, threading
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
import requests as _requests
import users
from password_policy import password_policy_error
import database as db

router = APIRouter()
_log = logging.getLogger("password_reset")

# ── Config ────────────────────────────────────────────────────────────────────
_AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
_AGENTMAIL_INBOX = os.environ.get("AGENTMAIL_INBOX", "fslnyaaa@agentmail.to")
_ADMIN_NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "alaaroubi@nyaaa.com")
_TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
_ON_AZURE = bool(os.environ.get("WEBSITE_SITE_NAME"))
_APP_URL = "https://fslapp-nyaaa.azurewebsites.net" if _ON_AZURE else "http://localhost:8000"

# ── Constants ─────────────────────────────────────────────────────────────────
_TOKEN_TTL_SECONDS = 900          # 15 minutes for initial token
_VALIDATION_TTL_SECONDS = 300     # 5 minutes for validation token after PIN verified
_MAX_PIN_ATTEMPTS = 3
_MAX_PER_HOUR = 3
_MAX_PER_HOUR_IP = 10             # IP-based rate limit (keyless bot protection)

# ── Rate limiter: {email_lower: [timestamps]} ────────────────────────────────
_rate: dict[str, list[float]] = {}
_rate_lock = threading.Lock()

# ── IP rate limiter: {ip: [timestamps]} ──────────────────────────────────────
_rate_ip: dict[str, list[float]] = {}
_rate_ip_lock = threading.Lock()

# ── PG audit table creation flag ─────────────────────────────────────────────
_pg_table_created = False


def _check_rate(email: str) -> bool:
    """Return True if under rate limit, False if exceeded."""
    key = email.lower()
    now = time.time()
    cutoff = now - 3600
    with _rate_lock:
        timestamps = _rate.get(key, [])
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= _MAX_PER_HOUR:
            _rate[key] = timestamps
            return False
        timestamps.append(now)
        _rate[key] = timestamps
        return True


def _check_rate_ip(ip: str) -> bool:
    """Return True if under IP rate limit, False if exceeded."""
    now = time.time()
    cutoff = now - 3600
    with _rate_ip_lock:
        timestamps = _rate_ip.get(ip, [])
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= _MAX_PER_HOUR_IP:
            _rate_ip[ip] = timestamps
            return False
        timestamps.append(now)
        _rate_ip[ip] = timestamps
        return True


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting Azure/front-proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _verify_turnstile(token: str, client_ip: str) -> bool:
    """Verify a Cloudflare Turnstile response token. Returns True if valid."""
    if not _TURNSTILE_SECRET_KEY:
        _log.warning("Turnstile secret key not configured; skipping verification")
        return True
    if not token:
        return False
    try:
        resp = _requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": _TURNSTILE_SECRET_KEY, "response": token, "remoteip": client_ip},
            timeout=10,
        )
        result = resp.json()
        return result.get("success", False)
    except Exception as e:
        _log.error(f"Turnstile verification failed: {e}")
        return False


def _send_email(to_email: str, subject: str, body_text: str):
    """Send email via AgentMail API (fire-and-forget)."""
    if not _AGENTMAIL_API_KEY or not to_email:
        _log.warning("Cannot send email: missing API key or recipient")
        return
    try:
        _requests.post(
            f"https://api.agentmail.to/v0/inboxes/{_AGENTMAIL_INBOX}/messages/send",
            headers={"Authorization": f"Bearer {_AGENTMAIL_API_KEY}", "Content-Type": "application/json"},
            json={"to": [to_email], "subject": subject, "text": body_text},
            timeout=10,
        )
    except Exception as e:
        _log.error(f"Failed to send email: {e}")


def _generate_pin() -> str:
    """Generate a 6-digit PIN (zero-padded)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _cleanup_expired_tokens():
    """Remove expired reset tokens from SQLite."""
    try:
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE expires_at < ?", (time.time(),))
    except Exception as e:
        _log.warning(f"Token cleanup failed: {e}")


def _audit_pg(username: str, email: str, password_hash: str, salt: str):
    """Write password change to PostgreSQL audit table (fire-and-forget)."""
    global _pg_table_created
    try:
        import pg_pool
        with pg_pool.writer() as conn:
            if not _pg_table_created:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS password_audit (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL,
                        email TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        changed_at TIMESTAMP DEFAULT NOW(),
                        changed_via TEXT DEFAULT 'reset_link'
                    )
                """)
                _pg_table_created = True
            conn.execute(
                "INSERT INTO password_audit (username, email, password_hash, salt, changed_via) VALUES (%s, %s, %s, %s, %s)",
                (username, email, password_hash, salt, "reset_link"),
            )
    except Exception as e:
        _log.error(f"PG audit write failed: {e}")


def _log_activity(user: str, action: str, detail: str = None, status_code: int = 200):
    """Log to SQLite activity_log."""
    try:
        db.log_activity(user=user, action=action, detail=detail, status_code=status_code)
    except Exception:
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/auth/forgot-password")
def forgot_password(request: Request, body: dict):
    email = (body.get("email") or "").strip()
    # Honeypot: bots often fill hidden fields; humans leave them empty
    honeypot = (body.get("website") or "").strip()
    if honeypot:
        _log_activity(user=email, action="forgot_password_honeypot", detail="Bot caught by honeypot", status_code=200)
        # Return same success message to prevent enumeration
        return {"ok": True, "message": "If an account with that email exists, you'll receive a reset link and PIN."}

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    client_ip = _client_ip(request)

    # Cloudflare Turnstile verification (if configured)
    turnstile_token = (body.get("turnstile") or "").strip()
    if not _verify_turnstile(turnstile_token, client_ip):
        _log_activity(user=email, action="forgot_password_turnstile_fail", detail="Turnstile verification failed", status_code=400)
        raise HTTPException(status_code=400, detail="Security verification failed. Please refresh the page and try again.")

    # Always return success to prevent enumeration
    success_msg = {"ok": True, "message": "If an account with that email exists, you'll receive a reset link and PIN."}

    # Rate limit by email
    if not _check_rate(email):
        _log_activity(user=email, action="forgot_password_rate_limited", detail="Email rate limit exceeded", status_code=429)
        return success_msg

    # Rate limit by IP (keyless bot protection)
    if not _check_rate_ip(client_ip):
        _log_activity(user=email, action="forgot_password_rate_limited", detail=f"IP rate limit exceeded: {client_ip}", status_code=429)
        return success_msg

    # Find user
    user = users.find_by_email(email)
    if not user:
        _log_activity(user=email, action="forgot_password_no_user", detail="User not found (enumeration protection)")
        return success_msg

    # Cleanup old tokens
    _cleanup_expired_tokens()

    # Invalidate any existing tokens for this user
    try:
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE username = ?", (user["username"],))
    except Exception as e:
        _log.warning(f"Failed to invalidate old tokens for {user['username']}: {e}")

    # Generate token + PIN
    token = secrets.token_urlsafe(32)
    pin = _generate_pin()
    expires_at = time.time() + _TOKEN_TTL_SECONDS

    try:
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO password_reset_tokens (token, username, email, pin, expires_at) VALUES (?, ?, ?, ?, ?)",
                (token, user["username"], user["email"], pin, expires_at),
            )
    except Exception as e:
        _log.error(f"Failed to store reset token for {user['username']}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create reset token")

    # Send reset email
    reset_url = f"{_APP_URL}/reset-password?token={token}"
    body_text = (
        f"Hi {user['name']},\n\n"
        f"You requested a password reset for your FleetPulse account.\n\n"
        f"Your verification PIN: {pin}\n\n"
        f"Click the link below to reset your password (expires in 15 minutes):\n"
        f"{reset_url}\n\n"
        f"You must enter your PIN on the reset page before you can set a new password.\n\n"
        f"If you did not request this, you can safely ignore this email.\n\n"
        f"— FleetPulse Team"
    )
    _send_email(user["email"], "FleetPulse Password Reset", body_text)
    _log.info(f"Password reset token + PIN generated for {user['username']} from {client_ip}")
    _log_activity(user=user["username"], action="forgot_password", detail="Reset token and PIN generated")

    return success_msg


@router.post("/api/auth/verify-reset-pin")
def verify_reset_pin(body: dict):
    token = (body.get("token") or "").strip()
    pin = (body.get("pin") or "").strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    if not pin:
        raise HTTPException(status_code=400, detail="PIN is required")

    _cleanup_expired_tokens()

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ?", (token,)
        ).fetchone()

    if not row:
        _log_activity(user=None, action="verify_pin", detail="Invalid or expired token", status_code=400)
        raise HTTPException(status_code=400, detail="Invalid or expired token. Please request a new reset link.")

    username = row["username"]
    email = row["email"]
    attempts = row["attempts"] or 0

    # Check expiry
    if row["expires_at"] < time.time():
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE token = ?", (token,))
        _log_activity(user=username, action="verify_pin", detail="Token expired", status_code=400)
        raise HTTPException(status_code=400, detail="Token has expired. Please request a new reset link.")

    # Check max attempts
    if attempts >= _MAX_PIN_ATTEMPTS:
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE token = ?", (token,))
        _log_activity(user=username, action="verify_pin", detail="Max PIN attempts exceeded", status_code=400)
        raise HTTPException(status_code=400, detail="Too many failed attempts. Please request a new reset link.")

    # Validate PIN
    if row["pin"] != pin:
        new_attempts = attempts + 1
        remaining = _MAX_PIN_ATTEMPTS - new_attempts
        with db.get_db() as conn:
            conn.execute(
                "UPDATE password_reset_tokens SET attempts = ? WHERE token = ?",
                (new_attempts, token),
            )
        _log_activity(user=username, action="verify_pin", detail=f"Invalid PIN (attempt {new_attempts})", status_code=400)
        raise HTTPException(status_code=400, detail=f"Invalid PIN. {remaining} attempt(s) remaining.")

    # PIN valid — issue validation token
    validation_token = secrets.token_urlsafe(32)
    validation_expires = time.time() + _VALIDATION_TTL_SECONDS

    with db.get_db() as conn:
        conn.execute(
            "UPDATE password_reset_tokens SET validated = 1, validation_token = ?, validation_expires_at = ? WHERE token = ?",
            (validation_token, validation_expires, token),
        )

    _log.info(f"PIN verified for {username}, validation token issued")
    _log_activity(user=username, action="verify_pin", detail="PIN verified, validation token issued")

    return {"ok": True, "message": "PIN verified.", "validation_token": validation_token}


@router.post("/api/auth/reset-password")
def reset_password(body: dict):
    validation_token = (body.get("validation_token") or "").strip()
    password = body.get("password") or ""
    password_confirm = body.get("password_confirm") or ""

    if not validation_token:
        raise HTTPException(status_code=400, detail="Validation token is required")

    _cleanup_expired_tokens()

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE validation_token = ?", (validation_token,)
        ).fetchone()

    if not row:
        _log_activity(user=None, action="reset_password", detail="Invalid validation token", status_code=400)
        raise HTTPException(status_code=400, detail="Invalid or expired session. Please request a new reset link.")

    username = row["username"]
    email = row["email"]

    # Check validation expiry
    if not row["validated"] or not row["validation_expires_at"] or row["validation_expires_at"] < time.time():
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE validation_token = ?", (validation_token,))
        _log_activity(user=username, action="reset_password", detail="Validation token expired", status_code=400)
        raise HTTPException(status_code=400, detail="Session expired. Please request a new reset link.")

    # Validate passwords match
    if password != password_confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    # Validate password policy
    password_error = password_policy_error(password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    # Check not reusing old password
    if users.check_password_against_user(username, password):
        _log_activity(user=username, action="reset_password", detail="Attempted to reuse old password", status_code=400)
        raise HTTPException(status_code=400, detail="You cannot reuse your previous password. Please choose a new one.")

    # Update password
    try:
        users.update_user(username, password=password)
    except Exception as e:
        _log.error(f"Failed to update password for {username}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password")

    # Invalidate token
    with db.get_db() as conn:
        conn.execute("DELETE FROM password_reset_tokens WHERE validation_token = ?", (validation_token,))

    # Invalidate all existing sessions for this user (security: attacker gets kicked out)
    users.invalidate_user_sessions(username)

    # Get the new hash+salt for audit
    with db.get_db() as conn:
        row = conn.execute("SELECT password_hash, salt FROM users WHERE username = ?", (username,)).fetchone()
        new_hash = row["password_hash"] if row else ""
        new_salt = row["salt"] if row else ""

    # Admin notification (fire-and-forget, includes hash NOT plaintext)
    notif_body = (
        f"Password Reset Notification\n\n"
        f"User: {username}\n"
        f"Email: {email}\n"
        f"Hash: {new_hash}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}\n"
        f"Method: Self-service reset link + PIN\n"
    )
    _send_email(_ADMIN_NOTIFY_EMAIL, f"[FleetPulse] Password Reset: {username}", notif_body)

    # PG audit (fire-and-forget in background)
    threading.Thread(target=_audit_pg, args=(username, email, new_hash, new_salt), daemon=True).start()

    # SQLite activity log
    _log_activity(user=username, action="reset_password", detail="Password successfully reset, sessions invalidated")

    _log.info(f"Password reset completed for {username}, all sessions invalidated")
    return {"ok": True, "message": "Password updated successfully."}
