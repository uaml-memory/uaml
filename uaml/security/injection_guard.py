# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""Injection Guard — Available in UAML Enterprise tier.

Detects and blocks prompt injection, data exfiltration, and adversarial
inputs targeting the memory layer.

Visit https://uaml-memory.com for licensing information.
"""

from dataclasses import dataclass


@dataclass
class InjectionResult:
    """Result of injection scan."""
    is_safe: bool = True
    threat_type: str = ""
    confidence: float = 0.0
    details: str = ""


class InjectionGuard:
    """Memory injection attack detector.

    Available in UAML Enterprise tier.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "InjectionGuard requires UAML Enterprise license. "
            "Visit https://uaml-memory.com for details."
        )


def scan_text(text: str, *, source_trusted: bool = True) -> InjectionResult:
    """Scan text for injection attacks. Enterprise only."""
    raise NotImplementedError("Requires UAML Enterprise license.")


def sanitize_text(text: str) -> str:
    """Sanitize text by removing injection patterns. Enterprise only."""
    raise NotImplementedError("Requires UAML Enterprise license.")
