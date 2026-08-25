"""Single source of truth for feature flags.

Defaults live in DEFAULT_FEATURES. The `features` key in the settings table
overrides them, so an admin can switch a module on or off from the Admin screen
and have it take effect immediately — no redeploy, no Azure app setting.

Precedence (lowest to highest):
    DEFAULT_FEATURES  ->  settings table `features`

Before this module there were two copies of the defaults (routers/misc.py and
routers/admin.py). admin.py's save loop iterates its own copy, so any flag
missing from it was silently dropped on save. Keep this the only copy.
"""

import logging

log = logging.getLogger('feature_flags')

DEFAULT_FEATURES = {
    'pta_advisor': True,
    'onroute': True,
    'matrix': True,
    'chat': False,
    'accounting': True,
    # Contractor Dispatch + Map. On by default; admins can switch it off from
    # the Admin screen (Feature Modules), which persists to the settings table.
    'contractor_dispatch': True,
}


def effective_features() -> dict:
    """Defaults merged with the admin's saved overrides from the settings table.

    Never raises: if the database is unreachable the defaults still apply, so a
    DB outage cannot silently switch every module off.
    """
    try:
        from repositories import settings as _settings
        saved = _settings.get_setting('features') or {}
        if not isinstance(saved, dict):
            log.warning("settings['features'] is %s, not a dict — ignoring", type(saved).__name__)
            saved = {}
    except Exception as e:
        log.warning("Could not read feature overrides, using defaults: %s", e)
        saved = {}
    # Only keys we know about — a stale key left in the DB shouldn't invent a flag.
    return {k: bool(saved.get(k, v)) for k, v in DEFAULT_FEATURES.items()}


def is_on(name: str) -> bool:
    """True if `name` is currently enabled. Unknown flags are OFF."""
    return effective_features().get(name, False)
