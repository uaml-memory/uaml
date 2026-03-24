"""Tests for UAML Key Escrow."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.crypto.pqc import PQCKeyPair
from uaml.crypto.escrow import KeyEscrow, EscrowShare, _split_secret, _reconstruct_secret


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db", agent_id="test")
    yield s
    s.close()


class TestSecretSharing:
    def test_split_and_reconstruct(self):
        secret = b"super_secret_key_material_32byte!"
        shares = _split_secret(secret, threshold=2, total=3)
        assert len(shares) == 3
        recovered = _reconstruct_secret(shares[:2], threshold=2)
        assert recovered == secret

    def test_threshold_validation(self):
        with pytest.raises(ValueError):
            _split_secret(b"secret", threshold=1, total=3)
        with pytest.raises(ValueError):
            _split_secret(b"secret", threshold=4, total=3)

    def test_insufficient_shares(self):
        secret = b"test_secret_data"
        shares = _split_secret(secret, threshold=3, total=3)
        with pytest.raises(ValueError):
            _reconstruct_secret(shares[:2], threshold=3)


class TestEscrowShare:
    def test_serialization(self):
        share = EscrowShare(
            share_index=0, share_data=b"\x01\x02\x03",
            key_id="test-key", custodian="alice",
            fingerprint="abc123", threshold=2, total_shares=3,
        )
        d = share.to_dict()
        assert d["custodian"] == "alice"

        restored = EscrowShare.from_dict(d)
        assert restored.share_data == b"\x01\x02\x03"
        assert restored.custodian == "alice"


class TestKeyEscrow:
    def test_deposit_and_list(self, store):
        escrow = KeyEscrow(store)
        keypair = PQCKeyPair.generate(key_id="test-key")

        shares = escrow.deposit(
            keypair, threshold=2, total_shares=3,
            custodians=["alice", "bob", "charlie"],
        )
        assert len(shares) == 3
        assert shares[0].custodian == "alice"

        listed = escrow.list_escrowed()
        assert len(listed) == 3

    def test_deposit_recover(self, store):
        escrow = KeyEscrow(store)
        keypair = PQCKeyPair.generate(key_id="recover-test")

        shares = escrow.deposit(keypair, threshold=2, total_shares=3)

        recovered = escrow.recover(
            "recover-test", shares[:2], keypair.public_key,
        )
        assert recovered.key_id == "recover-test"
        assert recovered.secret_key == keypair.secret_key

    def test_revoke(self, store):
        escrow = KeyEscrow(store)
        keypair = PQCKeyPair.generate(key_id="revoke-test")
        escrow.deposit(keypair, threshold=2, total_shares=3)

        count = escrow.revoke("revoke-test")
        assert count == 3

    def test_key_id_mismatch(self, store):
        escrow = KeyEscrow(store)
        keypair = PQCKeyPair.generate(key_id="key1")
        shares = escrow.deposit(keypair, threshold=2, total_shares=2)
        shares[0].key_id = "wrong"

        with pytest.raises(ValueError, match="mismatch"):
            escrow.recover("key1", shares, keypair.public_key)
