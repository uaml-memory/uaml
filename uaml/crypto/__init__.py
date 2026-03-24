# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Cryptography — post-quantum encryption for data at rest.

Uses ML-KEM-768 (NIST FIPS 203) for key encapsulation + AES-256-GCM for data encryption.
Designed for protecting exported data, backups, and identity layer entries.
"""

try:
    from uaml.crypto.pqc import PQCKeyPair, PQCEncryptor
except ImportError:
    PQCKeyPair = None
    PQCEncryptor = None

__all__ = ["PQCKeyPair", "PQCEncryptor"]
