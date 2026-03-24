# Copyright (c) 2026 GLG, a.s. All rights reserved.
"""Software Key Vault — Available in UAML Pro and Enterprise tiers.

Provides encrypted key storage with:
- NaCl SecretBox encryption (master password → key via scrypt)
- PQC master keypair (ML-KEM-768) for key encapsulation
- Per-client/project symmetric keys via HKDF
- Key rotation with archival
- Hardware wallet (Trezor) export/import

Visit https://uaml-memory.com for licensing information.
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class PQCKeyPair:
    """Post-quantum cryptographic keypair (ML-KEM-768)."""
    public_key: bytes
    secret_key: bytes


class KeyVault:
    """Encrypted key vault for UAML memory encryption.

    Full PQC implementation available in Pro/Enterprise tiers.
    For custom backends, subclass and override the storage methods.
    """

    def __init__(self, vault_path: str | Path, master_password: str):
        raise NotImplementedError(
            "KeyVault PQC implementation requires UAML Pro license. "
            "Visit https://uaml-memory.com for details."
        )

    def generate_master_key(self) -> PQCKeyPair:
        raise NotImplementedError("Requires UAML Pro license.")

    def derive_key(self, client_id: str, project_id: str) -> bytes:
        raise NotImplementedError("Requires UAML Pro license.")

    def store_key(self, name: str, key_data: bytes, algorithm: str = "AES-256-GCM"):
        raise NotImplementedError("Requires UAML Pro license.")

    def get_key(self, name: str) -> Optional[bytes]:
        raise NotImplementedError("Requires UAML Pro license.")

    def list_keys(self) -> list[str]:
        raise NotImplementedError("Requires UAML Pro license.")

    def rotate_key(self, name: str) -> bytes:
        raise NotImplementedError("Requires UAML Pro license.")
