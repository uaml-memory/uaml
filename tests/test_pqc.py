"""Tests for PQC encryption module — ML-KEM-768 + AES-256-GCM.

Validates key generation, encryption/decryption, file ops, and edge cases.
"""

import json
import os
import pytest

from uaml.crypto.pqc import PQCKeyPair, PQCEncryptor, PQCBackupEncryptor


class TestPQCKeyPair:
    """Test keypair generation and management."""

    def test_generate(self):
        kp = PQCKeyPair.generate()
        assert len(kp.public_key) == 1184  # ML-KEM-768 public key size
        assert len(kp.secret_key) == 2400  # ML-KEM-768 secret key size
        assert kp.algorithm == "ML-KEM-768"
        assert kp.key_id
        assert kp.created_at

    def test_generate_with_id(self):
        kp = PQCKeyPair.generate(key_id="agent-metod")
        assert kp.key_id == "agent-metod"

    def test_fingerprint(self):
        kp = PQCKeyPair.generate()
        fp = kp.fingerprint
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)

    def test_public_only(self):
        kp = PQCKeyPair.generate()
        pub = kp.public_only()
        assert pub.public_key == kp.public_key
        assert pub.secret_key == b""
        assert pub.key_id == kp.key_id

    def test_save_and_load(self, tmp_path):
        kp = PQCKeyPair.generate(key_id="test-key")
        path = tmp_path / "test.key"
        kp.save(path)

        loaded = PQCKeyPair.load(path)
        assert loaded.public_key == kp.public_key
        assert loaded.secret_key == kp.secret_key
        assert loaded.key_id == "test-key"

    def test_save_public_only(self, tmp_path):
        kp = PQCKeyPair.generate()
        path = tmp_path / "public.key"
        kp.save(path, include_secret=False)

        loaded = PQCKeyPair.load(path)
        assert loaded.public_key == kp.public_key
        assert loaded.secret_key == b""

    def test_file_permissions(self, tmp_path):
        kp = PQCKeyPair.generate()
        path = tmp_path / "secret.key"
        kp.save(path)
        # Should be 600 (owner read/write only)
        mode = oct(os.stat(path).st_mode)[-3:]
        assert mode == "600"

    def test_two_keypairs_differ(self):
        kp1 = PQCKeyPair.generate()
        kp2 = PQCKeyPair.generate()
        assert kp1.public_key != kp2.public_key
        assert kp1.secret_key != kp2.secret_key


class TestPQCEncryptor:
    """Test encryption and decryption."""

    def test_encrypt_decrypt_basic(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        plaintext = b"Hello, post-quantum world!"
        envelope = enc.encrypt(plaintext)
        decrypted = enc.decrypt(envelope)
        assert decrypted == plaintext

    def test_encrypt_decrypt_large(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        plaintext = os.urandom(1024 * 100)  # 100KB
        envelope = enc.encrypt(plaintext)
        assert enc.decrypt(envelope) == plaintext

    def test_encrypt_decrypt_empty(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        envelope = enc.encrypt(b"")
        assert enc.decrypt(envelope) == b""

    def test_encrypt_with_aad(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        plaintext = b"Secret data"
        aad = b"metadata:agent=metod,layer=identity"
        envelope = enc.encrypt(plaintext, aad=aad)
        assert enc.decrypt(envelope, aad=aad) == plaintext

    def test_aad_mismatch_fails(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        envelope = enc.encrypt(b"data", aad=b"correct")
        with pytest.raises((ValueError, Exception)):
            enc.decrypt(envelope, aad=b"wrong")

    def test_tampered_data_fails(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        envelope = enc.encrypt(b"important data")
        # Flip a byte in the ciphertext
        tampered = bytearray(envelope)
        tampered[-10] ^= 0xFF
        with pytest.raises((ValueError, Exception)):
            enc.decrypt(bytes(tampered))

    def test_encrypt_only_needs_public_key(self):
        kp = PQCKeyPair.generate()
        pub_only = PQCEncryptor(kp.public_key)

        envelope = pub_only.encrypt(b"one-way message")
        assert len(envelope) > 0

        # Cannot decrypt without secret key
        with pytest.raises(ValueError, match="Secret key required"):
            pub_only.decrypt(envelope)

        # Can decrypt with full keypair
        full = PQCEncryptor.from_keypair(kp)
        assert full.decrypt(envelope) == b"one-way message"

    def test_unique_ciphertext(self):
        """Each encryption should produce different ciphertext (fresh KEM + nonce)."""
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        e1 = enc.encrypt(b"same data")
        e2 = enc.encrypt(b"same data")
        assert e1 != e2  # Different KEM ciphertext + nonce each time

    def test_encrypt_json(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        data = {"name": "agent-a", "role": "coordinator", "tier": 0}
        envelope = enc.encrypt_json(data)
        decrypted = enc.decrypt_json(envelope)
        assert decrypted == data

    def test_encrypt_json_unicode(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        data = {"jméno": "agent-aěj", "poznámka": "šifrování 🔐"}
        envelope = enc.encrypt_json(data)
        assert enc.decrypt_json(envelope) == data

    def test_wrong_key_fails(self):
        kp1 = PQCKeyPair.generate()
        kp2 = PQCKeyPair.generate()

        enc1 = PQCEncryptor.from_keypair(kp1)
        enc2 = PQCEncryptor.from_keypair(kp2)

        envelope = enc1.encrypt(b"secret")
        with pytest.raises(Exception):
            enc2.decrypt(envelope)


class TestPQCBackupEncryptor:
    """Test file-level encryption for backups."""

    def test_encrypt_decrypt_file(self, tmp_path):
        kp = PQCKeyPair.generate()
        benc = PQCBackupEncryptor(kp)

        # Create test file
        source = tmp_path / "test.db"
        source.write_bytes(b"SQLite database content " * 100)

        encrypted = tmp_path / "test.db.pqc"
        meta = benc.encrypt_file(source, encrypted)

        assert encrypted.exists()
        assert meta["algorithm"] == "ML-KEM-768+AES-256-GCM"
        assert meta["encrypted_size"] > meta["plain_size"]

        # Decrypt
        restored = tmp_path / "test_restored.db"
        dec_meta = benc.decrypt_file(encrypted, restored)

        assert restored.read_bytes() == source.read_bytes()
        assert dec_meta["sha256"] == meta["plain_sha256"]

    def test_encrypt_file_with_aad(self, tmp_path):
        kp = PQCKeyPair.generate()
        benc = PQCBackupEncryptor(kp)

        source = tmp_path / "data.json"
        source.write_text('{"test": true}')

        encrypted = tmp_path / "data.json.pqc"
        aad = b"backup_id=full_2026-03-08"
        benc.encrypt_file(source, encrypted, aad=aad)

        restored = tmp_path / "data_restored.json"
        benc.decrypt_file(encrypted, restored, aad=aad)
        assert restored.read_text() == '{"test": true}'

    def test_large_file(self, tmp_path):
        """Test with 1MB file."""
        kp = PQCKeyPair.generate()
        benc = PQCBackupEncryptor(kp)

        source = tmp_path / "large.bin"
        source.write_bytes(os.urandom(1024 * 1024))

        encrypted = tmp_path / "large.bin.pqc"
        benc.encrypt_file(source, encrypted)

        restored = tmp_path / "large_restored.bin"
        benc.decrypt_file(encrypted, restored)
        assert restored.read_bytes() == source.read_bytes()


class TestEnvelopeFormat:
    """Test envelope binary format."""

    def test_envelope_contains_version(self):
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        envelope = enc.encrypt(b"test")
        # First 4 bytes = version (big-endian uint32)
        import struct
        version = struct.unpack(">I", envelope[:4])[0]
        assert version == 1

    def test_envelope_overhead(self):
        """Envelope overhead should be reasonable."""
        kp = PQCKeyPair.generate()
        enc = PQCEncryptor.from_keypair(kp)

        plaintext = b"x" * 1000
        envelope = enc.encrypt(plaintext)

        # Overhead = version(4) + kem_ct_len(4) + kem_ct(1088) + nonce(12) + tag(16)
        expected_overhead = 4 + 4 + 1088 + 12 + 16  # = 1124 bytes
        actual_overhead = len(envelope) - len(plaintext)
        assert actual_overhead == expected_overhead or actual_overhead < expected_overhead + 32
