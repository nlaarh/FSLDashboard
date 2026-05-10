"""Password reset token repository."""

import logging
import time
import db_adapter

_log = logging.getLogger("repo.password_reset")


def create_token(token, username, email, pin, expires_at):
    """Insert a new password reset token."""
    with db_adapter.writer() as db:
        db.execute(
            """
            INSERT INTO password_reset_tokens
                (token, username, email, pin, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (token, username, email, pin, expires_at),
        )
    _log.info(f"Password reset token created for {username}")


def get_token(token) -> dict | None:
    """Fetch a token row by primary token."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT token, username, email, pin, expires_at, validated,
                   validation_token, validation_expires_at, attempts, created_at
            FROM password_reset_tokens
            WHERE token = %s
            """,
            (token,),
        )
        row = db.fetchone()
    return row


def get_token_by_validation(validation_token) -> dict | None:
    """Fetch a token row by validation_token."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT token, username, email, pin, expires_at, validated,
                   validation_token, validation_expires_at, attempts, created_at
            FROM password_reset_tokens
            WHERE validation_token = %s
            """,
            (validation_token,),
        )
        row = db.fetchone()
    return row


def increment_attempts(token):
    """Bump the PIN attempt counter for a token."""
    with db_adapter.writer() as db:
        db.execute(
            """
            UPDATE password_reset_tokens
            SET attempts = attempts + 1
            WHERE token = %s
            """,
            (token,),
        )


def validate_token(token, validation_token, validation_expires_at):
    """Mark a token as validated and set its validation token + expiry."""
    with db_adapter.writer() as db:
        db.execute(
            """
            UPDATE password_reset_tokens
            SET validated = 1,
                validation_token = %s,
                validation_expires_at = %s
            WHERE token = %s
            """,
            (validation_token, validation_expires_at, token),
        )
    _log.info("Password reset token validated")


def delete_token(token):
    """Delete a token by its primary token value."""
    with db_adapter.writer() as db:
        db.execute(
            "DELETE FROM password_reset_tokens WHERE token = %s",
            (token,),
        )


def delete_tokens_by_username(username):
    """Delete all tokens belonging to a username."""
    with db_adapter.writer() as db:
        db.execute(
            "DELETE FROM password_reset_tokens WHERE username = %s",
            (username,),
        )
    _log.info(f"Invalidated old tokens for {username}")


def cleanup_expired_tokens():
    """Remove tokens whose expires_at is in the past."""
    now = time.time()
    with db_adapter.writer() as db:
        db.execute(
            "DELETE FROM password_reset_tokens WHERE expires_at < %s",
            (now,),
        )
        # rowcount isn't exposed on _DbConn; just log completion
    _log.debug("Expired password reset tokens cleaned up")
