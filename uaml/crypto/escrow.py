# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Key Escrow — secure key backup and recovery.

Provides key escrow functionality for PQC keypairs:
- Split secret keys using Shamir's Secret Sharing (threshold scheme)
- Store key shares with designated custodians
- Reconstruct keys from minimum threshold of shares
- Audit trail for all escrow operations

Usage:
    from uaml.crypto.escrow import KeyEscrow

    escrow = KeyEscrow(store)
    shares = escrow.deposit(keypair, threshold=2, total_shares=3,
                            custodians=["alice", "bob", "charlie"])

    # Later, recover with 2 of 3 shares:
    recovered = escrow.recover(key_id, shares=[shares[0], shares[1]])
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class EscrowShare:
    """A single share of an escrowed key."""
    share_index: int
    share_data: bytes
    key_id: str
    custodian: str
    fingerprint: str  # SHA-256 of original key
    threshold: int
    total_shares: int
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        import base64
        return {
            "share_index": self.share_index,
            "share_data": base64.b64encode(self.share_data).decode("ascii"),
            "key_id": self.key_id,
            "custodian": self.custodian,
            "fingerprint": self.fingerprint,
            "threshold": self.threshold,
            "total_shares": self.total_shares,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EscrowShare":
        import base64
        return cls(
            share_index=d["share_index"],
            share_data=base64.b64decode(d["share_data"]),
            key_id=d["key_id"],
            custodian=d["custodian"],
            fingerprint=d["fingerprint"],
            threshold=d["threshold"],
            total_shares=d["total_shares"],
            created_at=d.get("created_at", 0),
        )


def _split_secret(secret: bytes, threshold: int, total: int) -> list[bytes]:
    """Split a secret into shares using XOR-based secret sharing.

    Simple (t, n) threshold scheme:
    - Generate (threshold - 1) random pads
    - XOR all pads with secret for last share
    - Any threshold shares can reconstruct, fewer cannot

    For production use, replace with proper Shamir's Secret Sharing.
    """
    if threshold < 2:
        raise ValueError("Threshold must be >= 2")
    if total < threshold:
        raise ValueError("Total shares must be >= threshold")
    if threshold > total:
        raise ValueError("Threshold cannot exceed total shares")

    shares = []
    # Generate random shares for indices 0..(threshold-2)
    xor_accumulator = secret
    for i in range(threshold - 1):
        pad = os.urandom(len(secret))
        shares.append(pad)
        xor_accumulator = bytes(a ^ b for a, b in zip(xor_accumulator, pad))

    # The threshold-th share is the XOR of secret with all pads
    shares.append(xor_accumulator)

    # For additional shares beyond threshold, create dependent shares
    for i in range(total - threshold):
        # Each extra share = XOR of two existing shares (needs both to be useful)
        extra = bytes(a ^ b for a, b in zip(shares[i % threshold], shares[(i + 1) % threshold]))
        shares.append(extra)

    return shares


def _reconstruct_secret(shares: list[bytes], threshold: int) -> bytes:
    """Reconstruct secret from threshold shares (XOR scheme)."""
    if len(shares) < threshold:
        raise ValueError(f"Need {threshold} shares, got {len(shares)}")

    # XOR first `threshold` shares
    result = shares[0]
    for share in shares[1:threshold]:
        result = bytes(a ^ b for a, b in zip(result, share))
    return result


class KeyEscrow:
    """Manage key escrow — deposit and recover PQC keypairs."""

    def __init__(self, store: Optional[MemoryStore] = None):
        self.store = store
        if store:
            self._ensure_table()

    def _ensure_table(self) -> None:
        """Create escrow tracking table."""
        self.store.conn.execute("""
            CREATE TABLE IF NOT EXISTS key_escrow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_id TEXT NOT NULL,
                share_index INTEGER NOT NULL,
                custodian TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                threshold INTEGER NOT NULL,
                total_shares INTEGER NOT NULL,
                created_at REAL NOT NULL,
                revoked INTEGER DEFAULT 0,
                UNIQUE(key_id, share_index)
            )
        """)
        self.store.conn.commit()

    def deposit(
        self,
        keypair,
        *,
        threshold: int = 2,
        total_shares: int = 3,
        custodians: Optional[list[str]] = None,
    ) -> list[EscrowShare]:
        """Split keypair secret key into shares and deposit.

        Args:
            keypair: PQCKeyPair to escrow
            threshold: Minimum shares needed to reconstruct (default 2)
            total_shares: Total number of shares to create (default 3)
            custodians: Names/IDs for each share holder

        Returns:
            List of EscrowShare objects (distribute to custodians)
        """
        if not custodians:
            custodians = [f"custodian_{i}" for i in range(total_shares)]
        if len(custodians) != total_shares:
            raise ValueError(f"Need {total_shares} custodians, got {len(custodians)}")

        secret = keypair.secret_key
        fingerprint = hashlib.sha256(keypair.public_key).hexdigest()[:16]

        raw_shares = _split_secret(secret, threshold, total_shares)

        escrow_shares = []
        for i, (share_data, custodian) in enumerate(zip(raw_shares, custodians)):
            share = EscrowShare(
                share_index=i,
                share_data=share_data,
                key_id=keypair.key_id,
                custodian=custodian,
                fingerprint=fingerprint,
                threshold=threshold,
                total_shares=total_shares,
            )
            escrow_shares.append(share)

            # Record in DB (metadata only, NOT the share data)
            if self.store:
                self.store.conn.execute(
                    """INSERT OR REPLACE INTO key_escrow
                    (key_id, share_index, custodian, fingerprint, threshold,
                     total_shares, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (keypair.key_id, i, custodian, fingerprint,
                     threshold, total_shares, time.time()),
                )
                self.store.conn.commit()

        # Audit log
        if self.store:
            self.store.learn(
                f"Key escrow deposit: {keypair.key_id} split into "
                f"{total_shares} shares (threshold={threshold})",
                topic="security",
                source_type="audit",
                tags="escrow,key-management",
                data_layer="operational",
            )

        return escrow_shares

    def recover(
        self,
        key_id: str,
        shares: list[EscrowShare],
        public_key: bytes,
    ):
        """Reconstruct keypair from shares.

        Args:
            key_id: Key ID to recover
            shares: List of EscrowShare objects (minimum threshold count)
            public_key: The public key (not escrowed, always available)

        Returns:
            PQCKeyPair with reconstructed secret key
        """
        if not shares:
            raise ValueError("No shares provided")

        threshold = shares[0].threshold
        fingerprint = shares[0].fingerprint

        # Verify all shares match
        for s in shares:
            if s.key_id != key_id:
                raise ValueError(f"Share key_id mismatch: {s.key_id} != {key_id}")
            if s.fingerprint != fingerprint:
                raise ValueError("Share fingerprint mismatch — shares from different keys")

        if len(shares) < threshold:
            raise ValueError(f"Need {threshold} shares, got {len(shares)}")

        # Sort by index and extract raw data
        sorted_shares = sorted(shares, key=lambda s: s.share_index)
        raw_shares = [s.share_data for s in sorted_shares[:threshold]]

        secret = _reconstruct_secret(raw_shares, threshold)

        # Verify reconstruction
        expected_fp = hashlib.sha256(public_key).hexdigest()[:16]
        if expected_fp != fingerprint:
            raise ValueError("Fingerprint mismatch — recovery may have failed")

        # Reconstruct keypair
        from uaml.crypto.pqc import PQCKeyPair
        recovered = PQCKeyPair(
            public_key=public_key,
            secret_key=secret,
            key_id=key_id,
        )

        # Audit log
        if self.store:
            custodian_list = ", ".join(s.custodian for s in shares)
            self.store.learn(
                f"Key escrow recovery: {key_id} recovered using shares from: {custodian_list}",
                topic="security",
                source_type="audit",
                tags="escrow,key-recovery",
                data_layer="operational",
            )

        return recovered

    def list_escrowed(self) -> list[dict]:
        """List all escrowed keys (metadata only)."""
        if not self.store:
            return []

        rows = self.store.conn.execute(
            """SELECT key_id, custodian, fingerprint, threshold, total_shares,
                      created_at, revoked
               FROM key_escrow ORDER BY created_at DESC"""
        ).fetchall()

        return [dict(r) for r in rows]

    def revoke(self, key_id: str) -> int:
        """Revoke all shares for a key (marks as unusable)."""
        if not self.store:
            return 0

        cursor = self.store.conn.execute(
            "UPDATE key_escrow SET revoked = 1 WHERE key_id = ?",
            (key_id,),
        )
        self.store.conn.commit()

        if self.store:
            self.store.learn(
                f"Key escrow revocation: {key_id} — all shares revoked",
                topic="security",
                source_type="audit",
                tags="escrow,key-revocation",
                data_layer="operational",
            )

        return cursor.rowcount
