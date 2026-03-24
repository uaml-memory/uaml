# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""Token Anonymizer — Available in UAML Pro and Enterprise tiers.

Automatically detects and replaces PII, IP addresses, file paths, and other
sensitive tokens before they enter the memory layer (GDPR, CCPA compliant).

Visit https://uaml-memory.com for licensing information.
"""


class TokenAnonymizer:
    """PII/token anonymizer for memory ingestion pipeline.

    Available in UAML Pro and Enterprise tiers.
    Free tier users can implement custom anonymization via the ingestion hooks API.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "TokenAnonymizer requires UAML Pro license. "
            "Visit https://uaml-memory.com for details.\n"
            "For custom anonymization, see: https://uaml.dev/docs/hooks/ingestion"
        )
