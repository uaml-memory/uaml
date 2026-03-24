# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""Filter Rules Engine — Available in UAML Pro tier.

Configurable rules for filtering, transforming, and routing memory entries
during ingestion and recall.

Visit https://uaml-memory.com for licensing information.
"""


class FilterRuleStore:
    """Persistent filter rules for memory pipeline. Pro/Enterprise only."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "FilterRuleStore requires UAML Pro license. "
            "Visit https://uaml-memory.com for details."
        )
