"""Tests for UAML Ethics Pipeline."""

import tempfile
from pathlib import Path

import pytest

from uaml.ethics.checker import (
    EthicsChecker,
    EthicsRule,
    EthicsVerdict,
    Severity,
    Action,
    DEFAULT_RULES,
)
from uaml.core.store import MemoryStore, EthicsViolation


class TestEthicsChecker:
    def test_default_rules_loaded(self):
        checker = EthicsChecker()
        assert len(checker.rules) == len(DEFAULT_RULES)

    def test_clean_content_approved(self):
        checker = EthicsChecker()
        verdict = checker.check("Python uses indentation for code blocks")
        assert verdict.approved
        assert verdict.verdict == "APPROVED"
        assert len(verdict.matches) == 0

    def test_credentials_rejected(self):
        checker = EthicsChecker()
        verdict = checker.check("The API key is: api_key=sk-ant-abc123456789xyz")
        assert verdict.rejected
        assert "no_credentials" in verdict.rules_triggered or "no_private_keys" in verdict.rules_triggered

    def test_private_key_rejected(self):
        checker = EthicsChecker()
        verdict = checker.check("-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...")
        assert verdict.rejected
        assert "no_private_keys" in verdict.rules_triggered

    def test_pii_flagged(self):
        checker = EthicsChecker()
        verdict = checker.check("Contact john@example.com for details")
        assert verdict.flagged
        assert "no_personal_data" in verdict.rules_triggered

    def test_fabrication_flagged(self):
        checker = EthicsChecker()
        verdict = checker.check("As an AI, I don't have access to real-time data")
        assert verdict.flagged
        assert "no_fabrication_markers" in verdict.rules_triggered

    def test_short_content_flagged(self):
        checker = EthicsChecker()
        verdict = checker.check("ok")
        assert verdict.flagged
        assert "min_content_length" in verdict.rules_triggered

    def test_spam_flagged(self):
        checker = EthicsChecker()
        verdict = checker.check("Buy now! Limited offer! Click here for discount!")
        assert verdict.flagged
        assert "no_spam_content" in verdict.rules_triggered

    def test_hard_rule_overrides_soft(self):
        """If both hard and soft rules match, verdict should be REJECTED."""
        checker = EthicsChecker()
        # Content with both PII (soft) and credentials (hard)
        verdict = checker.check("password=SuperSecret123 email john@example.com")
        assert verdict.rejected  # Hard rule wins

    def test_verdict_to_dict(self):
        checker = EthicsChecker()
        verdict = checker.check("Contact john@example.com")
        d = verdict.to_dict()
        assert "verdict" in d
        assert "rules_triggered" in d
        assert "matches" in d


class TestCustomRules:
    def test_add_custom_rule(self):
        checker = EthicsChecker()
        checker.add_rule(EthicsRule(
            name="no_competitor",
            description="Block competitor names",
            pattern=r"(?i)\bcompetitor\b",
            severity=Severity.HARD,
            action=Action.REJECT,
        ))
        verdict = checker.check("competitor data should not be stored")
        assert verdict.rejected
        assert "no_competitor" in verdict.rules_triggered

    def test_remove_rule(self):
        checker = EthicsChecker()
        assert checker.remove_rule("no_spam_content")
        verdict = checker.check("Buy now! Limited offer!")
        assert verdict.approved  # Spam rule removed

    def test_disable_rule(self):
        checker = EthicsChecker()
        checker.disable_rule("no_personal_data")
        verdict = checker.check("Contact john@example.com")
        assert verdict.approved  # PII rule disabled

    def test_enable_rule(self):
        checker = EthicsChecker()
        checker.disable_rule("no_personal_data")
        checker.enable_rule("no_personal_data")
        verdict = checker.check("Contact john@example.com")
        assert verdict.flagged

    def test_no_defaults(self):
        checker = EthicsChecker(use_defaults=False)
        assert len(checker.rules) == 0
        verdict = checker.check("password=SuperSecret123")
        assert verdict.approved  # No rules = everything passes

    def test_custom_rules_only(self):
        rules = [EthicsRule(
            name="custom_only",
            description="Test",
            pattern=r"test",
            severity=Severity.SOFT,
            action=Action.FLAG,
        )]
        checker = EthicsChecker(rules=rules, use_defaults=False)
        assert len(checker.rules) == 1

    def test_stats(self):
        checker = EthicsChecker()
        s = checker.stats()
        assert s["total_rules"] > 0
        assert s["hard_rules"] > 0
        assert s["soft_rules"] > 0


class TestStoreIntegration:
    def test_ethics_warn_mode(self):
        """In warn mode, flagged content is still stored."""
        checker = EthicsChecker()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path, ethics_checker=checker, ethics_mode="warn")
        # PII should be flagged but still stored
        entry_id = store.learn("Contact john@example.com for the project update")
        assert entry_id > 0
        store.close()
        Path(db_path).unlink(missing_ok=True)

    def test_ethics_enforce_mode(self):
        """In enforce mode, rejected content raises EthicsViolation."""
        checker = EthicsChecker()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path, ethics_checker=checker, ethics_mode="enforce")
        with pytest.raises(EthicsViolation):
            store.learn("password=SuperSecret123456789")
        store.close()
        Path(db_path).unlink(missing_ok=True)

    def test_ethics_enforce_allows_clean(self):
        """In enforce mode, clean content is stored normally."""
        checker = EthicsChecker()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path, ethics_checker=checker, ethics_mode="enforce")
        entry_id = store.learn("Python uses dynamic typing")
        assert entry_id > 0
        store.close()
        Path(db_path).unlink(missing_ok=True)

    def test_ethics_off_mode(self):
        """Ethics off = no checking at all."""
        checker = EthicsChecker()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path, ethics_checker=checker, ethics_mode="off")
        # Even credentials should be stored
        entry_id = store.learn("password=SuperSecret123456789")
        assert entry_id > 0
        store.close()
        Path(db_path).unlink(missing_ok=True)

    def test_no_ethics_checker(self):
        """Without ethics checker, everything works normally."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path)
        entry_id = store.learn("password=SuperSecret123456789")
        assert entry_id > 0
        store.close()
        Path(db_path).unlink(missing_ok=True)
