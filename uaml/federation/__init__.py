# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Federation — multi-agent memory sharing.

Enables agents to share knowledge entries with access control,
provenance tracking, and conflict resolution.

Usage:
    from uaml.federation import FederationHub

    hub = FederationHub()
    hub.register_agent(store_a, agent_id="cyril")
    hub.register_agent(store_b, agent_id="metod")
    hub.share("cyril", "metod", entry_ids=[1, 2, 3], layer="team")
"""

from uaml.federation.hub import FederationHub, ShareRequest, ShareResult

__all__ = ["FederationHub", "ShareRequest", "ShareResult"]
