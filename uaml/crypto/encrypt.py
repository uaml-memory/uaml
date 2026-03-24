# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""Record-level encryption for UAML knowledge entries.

Uses per-client/project keys from the KeyVault with AES-256-GCM.
PQC key encapsulation available in Pro/Enterprise tiers.

Usage:
    from uaml.crypto.encrypt import RecordEncryptor
    enc = RecordEncryptor(vault)
    blob = enc.encrypt_record("sensitive text", "client-abc", "project-1")
    text = enc.decrypt_record(blob, "client-abc", "project-1")
"""

from __future__ import annotations
from typing import Optional
from uaml.crypto.vault import KeyVault

RECORD_VERSION = 1
NONCE_SIZE = 12


class RecordEncryptor:
    """Encrypt/decrypt UAML knowledge records using vault-managed keys.

    Requires a configured KeyVault (Pro/Enterprise tier).
    """

    def __init__(self, vault: KeyVault):
        self.vault = vault

    def encrypt_record(self, plaintext: str, client_id: str, project_id: str) -> bytes:
        """Encrypt a knowledge record. Returns encrypted blob."""
        raise NotImplementedError(
            "Record encryption requires UAML Pro license with KeyVault. "
            "Visit https://uaml-memory.com for details."
        )

    def decrypt_record(self, blob: bytes, client_id: str, project_id: str) -> str:
        """Decrypt a knowledge record. Returns plaintext."""
        raise NotImplementedError("Requires UAML Pro license.")
