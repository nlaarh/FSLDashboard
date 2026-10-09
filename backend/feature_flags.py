"""Single source of truth for feature flags.

Defaults live in DEFAULT_FEATURES. The `features` key in the settings table
overrides them, so an admin can switch a module on or off from the Admin screen
and have it take effect immediately — no redeploy, no Azure app setting.

Precedence (lowest to highest):
    DEFAULT_FEATURES  ->  settings table `features`  ->  FSLAPP_FEATURE_OVERRIDES (local only)

FSLAPP_FEATURE_OVERRIDES="scheduler_report_card=1,chat=0" lets a developer switch modules on a local
machine without writing the settings table (which, locally, is the PRODUCTION database). It is
ignored on Azure, never persisted by the Admin screen, and must never be set in a committed config.

Before this module there were two copies of the defaults (routers/misc.py and
routers/admin.py). admin.py's save loop iterates its own copy, so any flag
missing from it was silently dropped on save. Keep this the only copy.
"""

import logging
import os

log = logging.getLogger('feature_flags')
OVERRIDES_ENV = 'FSLAPP_FEATURE_OVERRIDES'
_TRUE, _FALSE = {'1', 'true', 'on', 'yes'}, {'0', 'false', 'off', 'no'}
_logged = set()

DEFAULT_FEATURES = {
    'pta_advisor': True,
    'onroute': True,
    'matrix': True,
    'chat': False,
    'accounting': True,
    # Contractor Dispatch + Map. On by default; admins can switch it off from
    # the Admin screen (Feature Modules), which persists to the settings table.
    'contractor_dispatch': True,
    # Scheduler Report Card (internal forensic view of a past garage-day). Off until released.
    'scheduler_report_card': False,
    # Call Story ("type a call, see what happened and why"). Off until released.
    'call_story': False,
    # Replay: member calls, member texts and the driver's other jobs (extras + text thread). On by default (owner, 2026-10-08).
    'replay_member_contact': True,
    # Speed batch 3 (all off until the owner approves the new tables and switches each on; off = today's behaviour):
    # Replay map reads our own 60 s record of driver positions instead of ServiceResourceHistory.
    'replay_gps_store': False,
    # Reporting and 30-day trends read a daily facts table instead of pulling a month of history from Salesforce.
    'daily_facts': False,
    # Garage revenue: AssetHistory and work-order lookups as semi-join / folded queries instead of ID-chunk fan-out.
    'revenue_semijoin': False,
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
    return {k: bool(saved.get(k, v)) for k, v in DEFAULT_FEATURES.items()} | env_overrides()


def env_overrides() -> dict:
    """Parse FSLAPP_FEATURE_OVERRIDES ("name=1,other=0"). Unknown flags and malformed items are
    skipped. Empty on Azure. Logs a WARNING once per distinct value."""
    raw = (os.environ.get(OVERRIDES_ENV) or '').strip()
    if not raw:
        return {}
    if os.environ.get('WEBSITE_SITE_NAME'):
        if 'azure' not in _logged:
            _logged.add('azure')
            log.error('%s is set on Azure: ignored (local testing only)', OVERRIDES_ENV)
        return {}
    out, bad = {}, []
    for item in raw.split(','):
        name, _, value = (x.strip().lower() for x in item.partition('='))
        if name in DEFAULT_FEATURES and value in _TRUE | _FALSE:
            out[name] = value in _TRUE
        elif item.strip():
            bad.append(item.strip())
    if raw not in _logged:
        _logged.add(raw)
        log.warning('FEATURE FLAG OVERRIDES ACTIVE (%s, local only, not saved): %s%s', OVERRIDES_ENV,
                    ', '.join(f'{k}={"on" if v else "off"}' for k, v in sorted(out.items())) or 'none valid',
                    f'; ignored: {", ".join(bad)}' if bad else '')
    return out


def is_on(name: str) -> bool:
    """True if `name` is currently enabled. Unknown flags are OFF."""
    return effective_features().get(name, False)


env_overrides()  # log the startup WARNING once, as soon as the app imports this module
