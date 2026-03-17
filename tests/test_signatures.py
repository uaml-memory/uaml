"""Tests for ML-DSA digital signatures module."""

import json
import tempfile
from pathlib import Path

import pytest

from uaml.crypto.signatures import (
    AgentKeyStore,
    SignatureEnvelope,
    Signer,
    SigningKeyPair,
    VerificationResult,
    Verifier,
)


class TestSigningKeyPair:
    """Test keypair generation and management."""

    def test_generate(self):
        kp = SigningKeyPair.generate("test-agent")
        assert kp.agent_id == "test-agent"
        assert len(kp.secret_key) == 32
        assert len(kp.public_key) == 32
        assert kp.key_id  # non-empty
        assert kp.fingerprint  # non-empty

    def test_generate_deterministic_with_seed(self):
        seed = b"A" * 32
        kp1 = SigningKeyPair.generate("agent", seed=seed)
        kp2 = SigningKeyPair.generate("agent", seed=seed)
        assert kp1.public_key == kp2.public_key
        assert kp1.secret_key == kp2.secret_key

    def test_generate_unique_without_seed(self):
        kp1 = SigningKeyPair.generate("agent")
        kp2 = SigningKeyPair.generate("agent")
        assert kp1.public_key != kp2.public_key

    def test_save_and_load(self, tmp_path):
        kp = SigningKeyPair.generate("saver")
        path = tmp_path / "test.sign"
        kp.save(path)
        loaded = SigningKeyPair.load(path)
        assert loaded.agent_id == "saver"
        assert loaded.public_key == kp.public_key
        assert loaded.secret_key == kp.secret_key

    def test_save_public_only(self, tmp_path):
        kp = SigningKeyPair.generate("pub-only")
        path = tmp_path / "pub.sign"
        kp.save(path, include_secret=False)
        data = json.loads(path.read_text())
        assert "secret_key" not in data
        assert "public_key" in data

    def test_fingerprint_stable(self):
        kp = SigningKeyPair.generate("fp-test", seed=b"X" * 32)
        fp1 = kp.fingerprint
        fp2 = kp.fingerprint
        assert fp1 == fp2
        assert len(fp1) == 16  # 16 hex chars

    def test_different_agents_different_keys(self):
        kp1 = SigningKeyPair.generate("alice", seed=b"A" * 32)
        kp2 = SigningKeyPair.generate("bob", seed=b"B" * 32)
        assert kp1.public_key != kp2.public_key


class TestSigner:
    """Test data signing."""

    def test_sign_bytes(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        envelope = signer.sign(b"hello world")
        assert envelope.agent_id == "signer"
        assert envelope.version == 1
        assert len(envelope.signature) == 64
        assert envelope.content_hash  # SHA-256 hex

    def test_sign_text(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        envelope = signer.sign_text("hello world")
        assert envelope.agent_id == "signer"
        assert envelope.content_hash  # non-empty

    def test_sign_dict(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        data = {"key": "value", "number": 42}
        envelope = signer.sign_dict(data)
        assert envelope.agent_id == "signer"

    def test_sign_with_metadata(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        envelope = signer.sign(b"data", metadata={"entry_id": 42, "type": "knowledge"})
        assert envelope.metadata["entry_id"] == 42
        assert envelope.metadata["type"] == "knowledge"

    def test_different_content_different_hash(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        e1 = signer.sign(b"content A")
        e2 = signer.sign(b"content B")
        assert e1.content_hash != e2.content_hash

    def test_sign_empty_content(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        envelope = signer.sign(b"")
        assert envelope.content_hash  # SHA-256 of empty bytes
        assert len(envelope.signature) == 64

    def test_timestamp_set(self):
        kp = SigningKeyPair.generate("signer")
        signer = Signer(kp)
        import time
        before = time.time()
        envelope = signer.sign(b"data")
        after = time.time()
        assert before <= envelope.timestamp <= after


class TestSignatureEnvelope:
    """Test envelope serialization."""

    def test_to_bytes_and_back(self):
        kp = SigningKeyPair.generate("serializer")
        signer = Signer(kp)
        original = signer.sign(b"test data")
        raw = original.to_bytes()
        restored = SignatureEnvelope.from_bytes(raw)
        assert restored.agent_id == original.agent_id
        assert restored.content_hash == original.content_hash
        assert restored.signature == original.signature
        assert restored.timestamp == original.timestamp

    def test_to_dict_and_back(self):
        kp = SigningKeyPair.generate("dict-test")
        signer = Signer(kp)
        original = signer.sign(b"dict data", metadata={"x": 1})
        d = original.to_dict()
        restored = SignatureEnvelope.from_dict(d)
        assert restored.agent_id == original.agent_id
        assert restored.content_hash == original.content_hash
        assert restored.metadata == {"x": 1}

    def test_invalid_magic_raises(self):
        with pytest.raises(ValueError, match="bad magic"):
            SignatureEnvelope.from_bytes(b"INVALID" + b"\x00" * 100)

    def test_dict_roundtrip_json_safe(self):
        kp = SigningKeyPair.generate("json-test")
        signer = Signer(kp)
        envelope = signer.sign(b"json safe")
        d = envelope.to_dict()
        # Should be JSON serializable
        json_str = json.dumps(d)
        restored = SignatureEnvelope.from_dict(json.loads(json_str))
        assert restored.content_hash == envelope.content_hash


class TestVerifier:
    """Test signature verification."""

    def test_verify_valid(self):
        kp = SigningKeyPair.generate("verifiable")
        signer = Signer(kp)
        envelope = signer.sign(b"trusted data")

        verifier = Verifier()
        verifier.add_trusted_key(kp.public_key, "verifiable")
        result = verifier.verify(envelope)
        assert result.valid
        assert result.agent_id == "verifiable"

    def test_verify_with_content(self):
        kp = SigningKeyPair.generate("content-check")
        signer = Signer(kp)
        content = b"verify this content"
        envelope = signer.sign(content)

        verifier = Verifier()
        verifier.add_trusted_key(kp.public_key, "content-check")
        result = verifier.verify_content(envelope, content)
        assert result.valid
        assert result.content_hash_match

    def test_verify_wrong_content_fails(self):
        kp = SigningKeyPair.generate("tamper-check")
        signer = Signer(kp)
        envelope = signer.sign(b"original content")

        verifier = Verifier()
        verifier.add_trusted_key(kp.public_key, "tamper-check")
        result = verifier.verify_content(envelope, b"tampered content")
        assert not result.valid
        assert not result.content_hash_match

    def test_verify_unknown_key_fails(self):
        kp = SigningKeyPair.generate("unknown")
        signer = Signer(kp)
        envelope = signer.sign(b"data")

        verifier = Verifier()  # no keys registered
        result = verifier.verify(envelope)
        assert not result.valid
        assert "Unknown key_id" in result.error

    def test_verify_agent_mismatch_fails(self):
        kp = SigningKeyPair.generate("alice")
        signer = Signer(kp)
        envelope = signer.sign(b"data")

        verifier = Verifier()
        # Register key under different agent name
        verifier.add_trusted_key(kp.public_key, "bob")
        result = verifier.verify(envelope)
        assert not result.valid
        assert "mismatch" in result.error.lower()

    def test_verify_text(self):
        kp = SigningKeyPair.generate("text-verify")
        signer = Signer(kp)
        text = "verify this text"
        envelope = signer.sign_text(text)

        verifier = Verifier()
        verifier.add_trusted_key(kp.public_key, "text-verify")
        result = verifier.verify_text(envelope, text)
        assert result.valid

    def test_trusted_agents_list(self):
        verifier = Verifier()
        kp1 = SigningKeyPair.generate("agent-a")
        kp2 = SigningKeyPair.generate("agent-b")
        verifier.add_trusted_key(kp1.public_key, "agent-a")
        verifier.add_trusted_key(kp2.public_key, "agent-b")
        agents = verifier.trusted_agents
        assert "agent-a" in agents
        assert "agent-b" in agents


class TestAgentKeyStore:
    """Test key store management."""

    def test_generate_and_load(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        kp = store.generate_key("test-agent")
        assert kp.agent_id == "test-agent"

        loaded = store.load_key("test-agent")
        assert loaded is not None
        assert loaded.public_key == kp.public_key

    def test_get_or_create_new(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        kp = store.get_or_create("new-agent")
        assert kp.agent_id == "new-agent"

    def test_get_or_create_existing(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        kp1 = store.get_or_create("existing")
        kp2 = store.get_or_create("existing")
        assert kp1.public_key == kp2.public_key

    def test_load_nonexistent_returns_none(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        assert store.load_key("ghost") is None

    def test_agents_list(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        store.generate_key("alpha")
        store.generate_key("beta")
        agents = store.agents
        assert "alpha" in agents
        assert "beta" in agents

    def test_get_verifier(self, tmp_path):
        store = AgentKeyStore(tmp_path / "keys")
        store.generate_key("pepa2")
        store.generate_key("cyril")

        verifier = store.get_verifier()
        assert "pepa2" in verifier.trusted_agents
        assert "cyril" in verifier.trusted_agents

    def test_full_sign_verify_flow(self, tmp_path):
        """End-to-end: generate keys, sign, verify across agents."""
        store = AgentKeyStore(tmp_path / "keys")

        # Two agents
        kp_pepa = store.get_or_create("pepa2")
        kp_cyril = store.get_or_create("cyril")

        # Pepa2 signs data
        signer = Signer(kp_pepa)
        envelope = signer.sign_text("UAML architecture decision: Variant D")

        # Cyril verifies
        verifier = store.get_verifier()
        result = verifier.verify(envelope)
        assert result.valid
        assert result.agent_id == "pepa2"

        # Verify content integrity
        result2 = verifier.verify_text(envelope, "UAML architecture decision: Variant D")
        assert result2.valid
        assert result2.content_hash_match

        # Tampered content detected
        result3 = verifier.verify_text(envelope, "UAML architecture decision: Variant X")
        assert not result3.valid
