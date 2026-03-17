# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Telemetry — anonymous installation and error reporting.

Collects ONLY:
- Installation status (success/failure)
- Software version
- OS type and version
- Python version
- CPU architecture
- Anonymous device ID (SHA256 of hostname — no PII)
- Error messages (on failure only)

Does NOT collect:
- User data, memory content, or file paths
- IP addresses (not logged server-side)
- Personal information of any kind

Opt-out: uaml config set telemetry false
Or: set UAML_TELEMETRY=0 environment variable

© 2026 Ladislav Zamazal / GLG, a.s.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import sys
import threading
from pathlib import Path
from typing import Optional

__all__ = ["report_event", "is_enabled", "disable", "enable"]

TELEMETRY_ENDPOINT = os.environ.get(
    "UAML_TELEMETRY_URL",
    "https://telemetry.uaml.ai/v1/report"
)

TIMEOUT_SECONDS = 5


def _get_config_path() -> Path:
    """Get path to telemetry config file."""
    config_dir = Path(os.environ.get("UAML_CONFIG_DIR", Path.home() / ".uaml"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "telemetry.json"


def _load_config() -> dict:
    """Load telemetry config."""
    path = _get_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"enabled": True}


def _save_config(config: dict) -> None:
    """Save telemetry config."""
    path = _get_config_path()
    path.write_text(json.dumps(config, indent=2))


def is_enabled() -> bool:
    """Check if telemetry is enabled."""
    # Environment variable override
    env = os.environ.get("UAML_TELEMETRY", "").lower()
    if env in ("0", "false", "off", "no"):
        return False
    if env in ("1", "true", "on", "yes"):
        return True
    # Config file
    return _load_config().get("enabled", True)


def disable() -> None:
    """Disable telemetry."""
    config = _load_config()
    config["enabled"] = False
    _save_config(config)


def enable() -> None:
    """Enable telemetry."""
    config = _load_config()
    config["enabled"] = True
    _save_config(config)


def _anonymous_id() -> str:
    """Generate anonymous device ID from hostname hash."""
    hostname = socket.gethostname()
    return hashlib.sha256(hostname.encode()).hexdigest()[:16]


def _get_version() -> str:
    """Get UAML version."""
    try:
        from uaml import __version__
        return __version__
    except Exception:
        return "unknown"


def _build_payload(
    event: str,
    error_msg: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Build telemetry payload."""
    payload = {
        "event": event,
        "version": _get_version(),
        "os": platform.system(),
        "os_version": platform.release(),
        "python": platform.python_version(),
        "arch": platform.machine(),
        "anonymous_id": _anonymous_id(),
    }
    if error_msg:
        payload["error"] = error_msg[:500]  # Truncate long errors
    if extra:
        payload["extra"] = {k: str(v)[:200] for k, v in extra.items()}
    return payload


def _send(payload: dict) -> None:
    """Send telemetry payload (fire-and-forget)."""
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            TELEMETRY_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
    except Exception:
        pass  # Telemetry must never break the application


def report_event(
    event: str,
    error_msg: Optional[str] = None,
    extra: Optional[dict] = None,
    blocking: bool = False,
) -> None:
    """Report a telemetry event.

    Events:
        install_ok      — successful installation
        install_fail    — installation failure
        init_ok         — successful uaml init
        init_fail       — init failure
        runtime_error   — unhandled runtime error
        health_ping     — periodic health check

    Args:
        event: Event type string
        error_msg: Optional error message (truncated to 500 chars)
        extra: Optional extra metadata dict
        blocking: If True, wait for response. Default False (fire-and-forget).
    """
    if not is_enabled():
        return

    payload = _build_payload(event, error_msg, extra)

    if blocking:
        _send(payload)
    else:
        # Fire and forget — don't slow down the user
        t = threading.Thread(target=_send, args=(payload,), daemon=True)
        t.start()
