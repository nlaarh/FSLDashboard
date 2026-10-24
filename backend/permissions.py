"""Centralized feature permissions.

FEATURE_ROLES holds the code defaults. The editable features can be overridden from the database
(access_store.py); any database problem falls back to these defaults, so nobody is ever locked out.
A user has one primary role (users.role) plus optional extra roles; a feature is allowed when ANY of
their roles is allowed.
"""

# Matrix columns, in display order. constants/users.js ROLES must stay a subset of this list.
ROLES = ("superadmin", "admin", "manager", "officer", "supervisor", "viewer", "finance", "ers", "executive",
         "ers-manager", "ers-supervisor", "ers-director", "ers-member-relations", "contractor")

# Restrictive roles: the deny rules and territory scoping look at the primary role only, so these cannot be combined.
EXCLUSIVE_ROLES = frozenset({"contractor", "ers-supervisor", "ers-member-relations"})

_ALL = set(ROLES)
_STAFF = _ALL - {"contractor"}                                  # everyone who gets the main FleetPulse menu
_NO_ACCOUNTING = _STAFF - {"ers-supervisor", "ers-member-relations"}  # supervisors are blocked from accounting
_MANAGERS = {"superadmin", "admin", "executive"}

# (key, group, label, default roles, description). Defaults reproduce today's access exactly: the page and tab
# rows were open to every staff role (the frontend hid them only for the restricted roles listed above).
_CATALOG = [
    ("page.command_center", "Pages", "Command Center", _STAFF, "Main menu page."),
    ("page.garages", "Pages", "Garages", _STAFF, "Garage list and the garage page."),
    ("page.queue", "Pages", "Queue", _STAFF, "Main menu page."),
    ("page.forecast", "Pages", "Forecast", _STAFF, "Main menu page."),
    ("page.pta", "Pages", "PTA Advisor", _STAFF, "Main menu page."),
    ("page.route_tracker", "Pages", "Route Tracker", _STAFF, "Main menu page."),
    ("page.insights", "Pages", "Insights", _STAFF, "Main menu page."),
    ("page.sa_watchlist", "Pages", "SA Watchlist", _STAFF, "Live watchlist page."),
    ("page.accounting", "Pages", "Accounting", _NO_ACCOUNTING, "Accounting page and its data."),
    ("page.reporting", "Pages", "Reporting", _STAFF, "Reporting page."),
    ("page.issues", "Pages", "Report / track bugs", _STAFF, "Bug list."),
    ("page.help", "Pages", "Help Center", _STAFF, "Help pages."),
    ("garage.tab_schedule", "Garage page tabs", "Schedule tab", _ALL, "Garage page."),
    ("garage.tab_dashboard", "Garage page tabs", "Dashboard tab", _ALL, "Garage page."),
    ("garage.tab_operations", "Garage page tabs", "Dashboard: Operations sub-tab", _ALL, "Inside the garage Dashboard tab."),
    ("garage.revenue_performance", "Garage page tabs", "Dashboard: Performance and Revenue sub-tabs", {"superadmin", "admin", "executive", "ers-director", "ers-manager", "contractor"}, "Inside the garage Dashboard tab."),
    ("garage.tab_dispatch_map", "Garage page tabs", "Dispatch Map tab", _ALL, "Garage page."),
    ("garage.tab_satisfaction", "Garage page tabs", "Satisfaction Score tab", _ALL, "Garage page."),
    ("watchlist.tab_alerts", "SA Watchlist tabs", "Operational Watchlist tab", _ALL, "Watchlist sub-tab."),
    ("watchlist.tab_cancellations", "SA Watchlist tabs", "Cancellations tab", _ALL, "Watchlist sub-tab."),
    ("watchlist.tab_manual", "SA Watchlist tabs", "Manual Dispatch SAs tab", _ALL, "Watchlist sub-tab."),
    ("watchlist.tab_live", "SA Watchlist tabs", "ERS Live Board tab", _ALL, "Watchlist sub-tab."),
    ("accounting.tab_wo_adjustments", "Accounting tabs", "WO Adjustments tab", _NO_ACCOUNTING, "Accounting sub-tab."),
    ("accounting.tab_analytics", "Accounting tabs", "Analytics tab", _NO_ACCOUNTING, "Accounting sub-tab."),
    ("accounting.tab_help", "Accounting tabs", "Help & Guide tab", _NO_ACCOUNTING, "Accounting sub-tab."),
    ("reporting.tab_garage_performance", "Reporting tabs", "Garage Performance tab", _STAFF, "Reporting sub-tab."),
    ("reporting.user_adoption", "Reporting tabs", "User Adoption tab", _MANAGERS, "Who logs in and uses which screen."),
    ("reporting.dispatch_scorecard", "Reporting tabs", "Dispatcher Scorecard tab", _MANAGERS, "Also enforced on the server."),
    # Never "contractor": the report card shows other drivers' workloads and dispatcher behaviour.
    ("scheduler.report_card", "Scheduler", "Scheduler report card", {"superadmin", "admin", "executive", "ers-director"}, "Scheduler audit. Never for contractors."),
    # Replay (garage and work order): administrators, executives and ERS managers; not ers-director. Superadmin sits above admin.
    ("scheduler.replay", "Scheduler", "Replay (garage and work order)", {"superadmin", "admin", "executive", "ers-manager"}, "Replay menu page and the call replay."),
    ("scheduler.report_card_admin", "Scheduler", "Report card refresh and AI", {"superadmin", "admin"}, "Rebuild and AI actions on the report card."),
    ("admin.panel", "Admin", "Admin panel", {"superadmin", "admin"}, "The Admin page (still asks for the admin PIN)."),
    ("admin.reference_data", "Admin", "Reference Data (no PIN for non-admins)", {"superadmin", "admin", "executive", "ers-director"}, "Reference tables. Executives and ERS directors need no PIN."),
    ("admin.impersonate", "Admin", "Log in as another user", {"superadmin"}, "Support and verification."),
    ("access.edit", "Admin", "Edit access (this screen)", {"superadmin"}, "Change the matrix."),
    ("contractor.portal", "Contractor portal", "Contractor portal (all its pages)", {"contractor"}, "Separate contractor menu, scoped to their own garages."),
]

FEATURE_ROLES = {key: set(roles) for key, _, _, roles, _ in _CATALOG}

# Not editable on the Access screen: always the code default, never read from the database.
LOCKED_FEATURES = {
    "admin.impersonate": "Only the owner account may log in as another user (checked in code).",
    "admin.panel": "Editing it could lock everyone out of the screen that fixes access.",
    "access.edit": "Only a superadmin may change access.",
    "scheduler.report_card_admin": "Triggers refresh and AI work against shared Salesforce; cost control is not a checkbox.",
    "contractor.portal": "Contractors have their own scoped portal; it is fixed in code.",
}

# Roles refused even if the database says otherwise.
HARD_DENY = {"scheduler.report_card": {"contractor"}}

# key -> (label, description, group)
FEATURE_META = {key: (label, desc, group) for key, group, label, _, desc in _CATALOG}


# The one account allowed to log in as another user.
IMPERSONATOR_USERNAME = "nlaaroubi@nyaaa.com"


def _as_set(roles) -> set:
    return {roles} if isinstance(roles, str) else set(roles or ())


def feature_roles(feature: str) -> set:
    """Roles allowed for a feature: database value for editable features, else the code default."""
    default = FEATURE_ROLES.get(feature, set())
    if feature in LOCKED_FEATURES or feature not in FEATURE_ROLES:
        return set(default)
    import access_store
    return access_store.feature_roles(feature, default)[0]


def get_user_features(roles) -> list[str]:
    return [f for f in FEATURE_ROLES if can_access(roles, f)]


def can_access(roles, feature: str) -> bool:
    """`roles` is one role name or a set of them; allowed when any role is allowed."""
    return bool((_as_set(roles) - HARD_DENY.get(feature, set())) & feature_roles(feature))


def require_feature(feature: str | tuple, request) -> None:
    """Raise 401/403 if request user lacks the feature (or all of a tuple of features). No-op if request is None (direct Python call)."""
    if request is None:
        return
    from fastapi import HTTPException
    from routers.auth import _verify_cookie
    import users as _users
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = payload.split(":")[0]
    user = _users.get_user(username) or {}
    roles = user.get("roles") or user.get("role") or ""
    if not any(can_access(roles, f) for f in (feature if isinstance(feature, tuple) else (feature,))):
        raise HTTPException(status_code=403, detail="Access restricted")
