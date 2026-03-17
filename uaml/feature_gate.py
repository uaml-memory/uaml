# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Feature Gating & Trial System.

Provides trial management (download/install tracking, 14-day trials) and
tier-based feature gating. ONE distribution — ALL features during trial,
then gated by license tier.

Data collection principle: ALL modules collect data regardless of tier.
Only ACCESS/QUERY is gated. Example: Audit trail always logs, but
detailed audit queries need Starter+.

Usage:
    from uaml.feature_gate import TrialManager, FeatureGate, require_feature

    # Trial management
    tm = TrialManager("licenses.db")
    dl = tm.register_download("user@example.com")
    inst = tm.register_install("user@example.com")
    trial = tm.check_trial(inst["install_id"])

    # Feature gating
    gate = FeatureGate("professional")
    if gate.is_available("federation"):
        ...

    # Decorator
    @require_feature("federation")
    def sync_data(self):
        ...

© 2026 Ladislav Zamazal / GLG, a.s.
"""

from __future__ import annotations

import functools
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

__all__ = [
    "TrialManager",
    "FeatureGate",
    "FeatureNotAvailable",
    "require_feature",
    "FEATURE_MATRIX",
    "TIERS",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIERS = ["community", "starter", "professional", "team", "enterprise"]

UPGRADE_URL = "https://uaml-memory.com"

# Feature matrix: feature -> {tier: value}
# Values: True (available), False (blocked), "basic"/"full" (level),
#         int (numeric limit), None (unlimited)
FEATURE_MATRIX = {
    "knowledge_store": {
        "community": 10_000,
        "starter": 100_000,
        "professional": None,  # unlimited
        "team": None,
        "enterprise": None,
        "trial": None,
    },
    "basic_search": {
        "community": True,
        "starter": True,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "semantic_search": {
        "community": False,
        "starter": True,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "rbac": {
        "community": False,
        "starter": True,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "audit_trail": {
        "community": "basic",
        "starter": "full",
        "professional": "full",
        "team": "full",
        "enterprise": "full",
        "trial": "full",
    },
    "data_layers": {
        "community": 2,
        "starter": 3,
        "professional": 5,
        "team": 5,
        "enterprise": 5,
        "trial": 5,
    },
    "federation": {
        "community": False,
        "starter": False,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "team_sync": {
        "community": False,
        "starter": False,
        "professional": False,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "task_claim_protocol": {
        "community": False,
        "starter": False,
        "professional": False,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "security_config": {
        "community": False,
        "starter": False,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "expert_mode": {
        "community": False,
        "starter": False,
        "professional": False,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "customer_portal": {
        "community": False,
        "starter": True,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "voice_tts": {
        "community": False,
        "starter": False,
        "professional": True,
        "team": True,
        "enterprise": True,
        "trial": True,
    },
    "max_agents": {
        "community": 1,
        "starter": 3,
        "professional": 10,
        "team": 50,
        "enterprise": None,  # unlimited
        "trial": None,
    },
    "max_nodes": {
        "community": 1,
        "starter": 1,
        "professional": 3,
        "team": 10,
        "enterprise": None,
        "trial": None,
    },
    "support": {
        "community": "community",
        "starter": "email",
        "professional": "priority",
        "team": "dedicated",
        "enterprise": "sla",
        "trial": "email",
    },
    "encryption": {
        "community": "standard",
        "starter": "standard",
        "professional": "post-quantum",
        "team": "post-quantum",
        "enterprise": "post-quantum",
        "trial": "post-quantum",
    },
}

# Minimum tier required for each feature (for upgrade prompts)
_MIN_TIER = {}
for _feat, _tiers_map in FEATURE_MATRIX.items():
    for _t in TIERS:
        _val = _tiers_map.get(_t)
        if _val is not False:
            _MIN_TIER[_feat] = _t
            break
    else:
        _MIN_TIER[_feat] = "enterprise"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FeatureNotAvailable(Exception):
    """Raised when a feature is not available for the current tier."""

    def __init__(self, feature: str, tier: str, upgrade_url: str = UPGRADE_URL):
        self.feature = feature
        self.tier = tier
        self.upgrade_url = upgrade_url
        min_tier = _MIN_TIER.get(feature, "enterprise")
        super().__init__(
            f"Feature '{feature}' is not available on {tier} tier. "
            f"Requires {min_tier} or higher. Upgrade at {upgrade_url}"
        )


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def require_feature(feature: str):
    """Decorator that raises FeatureNotAvailable if the feature is blocked.

    Expects the decorated method's instance to have a ``feature_gate``
    attribute (a FeatureGate instance), or accepts a ``gate`` keyword arg.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            gate = kwargs.pop("__feature_gate__", None)
            if gate is None and args:
                gate = getattr(args[0], "feature_gate", None)
            if gate is not None and not gate.is_available(feature):
                raise FeatureNotAvailable(feature, gate.tier)
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


# ---------------------------------------------------------------------------
# Trial DB schema
# ---------------------------------------------------------------------------

_TRIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS installations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    install_id      TEXT    UNIQUE NOT NULL,
    email           TEXT    NOT NULL,
    download_ip     TEXT    DEFAULT '',
    hostname        TEXT    DEFAULT '',
    os_info         TEXT    DEFAULT '',
    installed_at    TEXT    NOT NULL,
    trial_expires_at TEXT   NOT NULL,
    license_key     TEXT,
    status          TEXT    DEFAULT 'trial'
);

CREATE TABLE IF NOT EXISTS download_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL,
    ip_address      TEXT    DEFAULT '',
    user_agent      TEXT    DEFAULT '',
    version         TEXT    DEFAULT '1.0.0',
    downloaded_at   TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# TrialManager
# ---------------------------------------------------------------------------


class TrialManager:
    """Manage downloads, installations, and 14-day trial periods.

    Uses SQLite for persistence. Thread-safe via per-call connections.
    """

    TRIAL_DAYS = 14

    def __init__(self, db_path: str = "licenses.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_TRIAL_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def register_download(
        self,
        email: str,
        ip_address: str = "",
        user_agent: str = "",
        version: str = "1.0.0",
    ) -> dict:
        """Log a download event.

        Returns:
            dict with download_id and downloaded_at.
        """
        now = _now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO download_log (email, ip_address, user_agent, version, downloaded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (email, ip_address, user_agent, version, now),
            )
            conn.commit()
            return {"download_id": cur.lastrowid, "downloaded_at": now}
        finally:
            conn.close()

    def register_install(
        self,
        email: str,
        hostname: str = "",
        os_info: str = "",
    ) -> dict:
        """Create a new installation with a 14-day trial.

        Returns:
            dict with install_id, trial_expires_at, status.
        """
        install_id = str(uuid.uuid4())
        now = _now_utc()
        expires = now + timedelta(days=self.TRIAL_DAYS)
        now_iso = now.isoformat()
        expires_iso = expires.isoformat()

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO installations "
                "(install_id, email, hostname, os_info, installed_at, trial_expires_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'trial')",
                (install_id, email, hostname, os_info, now_iso, expires_iso),
            )
            conn.commit()
            return {
                "install_id": install_id,
                "email": email,
                "trial_expires_at": expires_iso,
                "status": "trial",
            }
        finally:
            conn.close()

    def check_trial(self, install_id: str) -> dict:
        """Check trial status for an installation.

        Returns:
            dict with active (bool), days_remaining (int), expires_at (str).
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM installations WHERE install_id = ?", (install_id,)
            ).fetchone()
            if not row:
                return {"active": False, "days_remaining": 0, "expires_at": ""}

            # If license is activated, trial is irrelevant
            if row["status"] == "active":
                return {"active": True, "days_remaining": -1, "expires_at": row["trial_expires_at"]}

            if row["status"] == "blocked":
                return {"active": False, "days_remaining": 0, "expires_at": row["trial_expires_at"]}

            expires = datetime.fromisoformat(row["trial_expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)

            now = _now_utc()
            if now >= expires:
                # Auto-update status
                if row["status"] == "trial":
                    conn.execute(
                        "UPDATE installations SET status = 'expired' WHERE install_id = ?",
                        (install_id,),
                    )
                    conn.commit()
                return {"active": False, "days_remaining": 0, "expires_at": row["trial_expires_at"]}

            remaining = (expires - now).days
            return {
                "active": True,
                "days_remaining": remaining,
                "expires_at": row["trial_expires_at"],
            }
        finally:
            conn.close()

    def activate_license(self, install_id: str, license_key: str) -> dict:
        """Link a license key to an installation, activating it.

        Returns:
            dict with success (bool), install_id, status.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM installations WHERE install_id = ?", (install_id,)
            ).fetchone()
            if not row:
                return {"success": False, "error": "Installation not found"}

            conn.execute(
                "UPDATE installations SET license_key = ?, status = 'active' WHERE install_id = ?",
                (license_key, install_id),
            )
            conn.commit()
            return {"success": True, "install_id": install_id, "status": "active"}
        finally:
            conn.close()

    def list_installations(
        self, email: Optional[str] = None, status: Optional[str] = None
    ) -> list:
        """List installations with optional filters.

        Returns:
            list of dicts.
        """
        conn = self._connect()
        try:
            sql = "SELECT * FROM installations WHERE 1=1"
            params: list = []
            if email is not None:
                sql += " AND email = ?"
                params.append(email)
            if status is not None:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY id DESC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_downloads(self, email: Optional[str] = None) -> list:
        """List download log entries with optional email filter.

        Returns:
            list of dicts.
        """
        conn = self._connect()
        try:
            if email is not None:
                rows = conn.execute(
                    "SELECT * FROM download_log WHERE email = ? ORDER BY id DESC",
                    (email,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM download_log ORDER BY id DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self) -> dict:
        """Summary statistics for downloads and installations.

        Returns:
            dict with total_downloads, total_installs, active_trials,
            converted, conversion_rate.
        """
        conn = self._connect()
        try:
            total_downloads = conn.execute(
                "SELECT COUNT(*) FROM download_log"
            ).fetchone()[0]
            total_installs = conn.execute(
                "SELECT COUNT(*) FROM installations"
            ).fetchone()[0]
            active_trials = conn.execute(
                "SELECT COUNT(*) FROM installations WHERE status = 'trial'"
            ).fetchone()[0]
            converted = conn.execute(
                "SELECT COUNT(*) FROM installations WHERE status = 'active'"
            ).fetchone()[0]

            conversion_rate = (
                round(converted / total_installs * 100, 2)
                if total_installs > 0
                else 0.0
            )

            return {
                "total_downloads": total_downloads,
                "total_installs": total_installs,
                "active_trials": active_trials,
                "converted": converted,
                "conversion_rate": conversion_rate,
            }
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# FeatureGate
# ---------------------------------------------------------------------------


class FeatureGate:
    """Control feature access based on license tier.

    During active trial, all features are unlocked (equivalent to enterprise).
    After trial expiry, features are gated by the actual tier.
    """

    def __init__(self, tier: str = "community", trial_active: bool = False):
        self.tier = tier.lower().strip()
        self.trial_active = trial_active
        if self.tier not in TIERS:
            raise ValueError(
                f"Unknown tier: {tier!r}. Valid tiers: {', '.join(TIERS)}"
            )

    @property
    def _effective_tier(self) -> str:
        """Return 'trial' if trial is active, otherwise the actual tier."""
        return "trial" if self.trial_active else self.tier

    def is_available(self, feature: str) -> bool:
        """Check if a feature is available for the current tier.

        Returns True for features with any truthy value (True, int > 0,
        non-empty string). Returns False only for explicitly False values.
        """
        feature_lower = feature.lower().strip()
        if feature_lower not in FEATURE_MATRIX:
            return False

        value = FEATURE_MATRIX[feature_lower].get(self._effective_tier, False)
        return value is not False

    def check_limit(self, feature: str) -> Optional[int]:
        """Return the numeric limit for a feature, or None for unlimited.

        For boolean features, returns None (no numeric limit applies).
        """
        feature_lower = feature.lower().strip()
        if feature_lower not in FEATURE_MATRIX:
            return 0

        value = FEATURE_MATRIX[feature_lower].get(self._effective_tier, False)
        if value is False:
            return 0
        if value is True or value is None:
            return None  # unlimited
        if isinstance(value, int):
            return value
        return None  # string values like "basic", "full" → no numeric limit

    def available_features(self) -> list:
        """List all features available for the current tier."""
        result = []
        for feature in FEATURE_MATRIX:
            if self.is_available(feature):
                result.append(feature)
        return result

    def blocked_features(self) -> list:
        """List features blocked for the current tier, with upgrade hints."""
        result = []
        for feature in FEATURE_MATRIX:
            if not self.is_available(feature):
                min_tier = _MIN_TIER.get(feature, "enterprise")
                result.append({
                    "feature": feature,
                    "requires": min_tier,
                    "upgrade_url": UPGRADE_URL,
                })
        return result

    def tier_info(self) -> dict:
        """Return current tier details."""
        available = self.available_features()
        blocked = self.blocked_features()
        return {
            "tier": self.tier,
            "trial_active": self.trial_active,
            "effective_tier": self._effective_tier,
            "available_count": len(available),
            "blocked_count": len(blocked),
            "features": {f: self.check_limit(f) for f in available},
        }

    def upgrade_prompt(self, feature: str) -> str:
        """Return an upgrade prompt message for a blocked feature."""
        feature_lower = feature.lower().strip()
        min_tier = _MIN_TIER.get(feature_lower, "enterprise")
        return (
            f"This feature requires {min_tier.title()} tier. "
            f"Upgrade at {UPGRADE_URL}"
        )

    def feature_matrix(self) -> dict:
        """Return the complete feature matrix for all tiers."""
        return {
            feature: {
                tier: values.get(tier)
                for tier in TIERS + ["trial"]
            }
            for feature, values in FEATURE_MATRIX.items()
        }
