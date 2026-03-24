# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""UAML Feature Gating — Available in Pro and Enterprise tiers.

Manages feature availability based on license tier.

Visit https://uaml-memory.com for licensing information.
"""


class FeatureNotAvailable(Exception):
    """Raised when a feature requires a higher license tier."""
    pass


class FeatureGate:
    """Controls feature availability based on license. Pro/Enterprise only."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "License-based feature gating requires UAML Pro license. "
            "All community features are enabled by default."
        )


def get_gate() -> FeatureGate:
    """Get the global feature gate. Pro/Enterprise only."""
    raise NotImplementedError("Requires UAML Pro license.")
