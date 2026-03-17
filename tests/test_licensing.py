"""Tests for uaml.licensing — key generation, validation, and license management.

© 2026 Ladislav Zamazal / GLG, a.s.
"""

import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from uaml.licensing import (
    LicenseKey,
    LicenseManager,
    TIER_CODES,
    CODE_TO_TIER,
)


class TestLicenseKey(unittest.TestCase):
    """Tests for stateless key generation and validation."""

    def test_generate_key_format(self):
        """Key must match UAML-XXXX-XXXX-XXXX-XXXX."""
        key = LicenseKey.generate("Community")
        self.assertRegex(key, r"^UAML-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

    def test_generate_all_tiers(self):
        """Every tier must produce a valid key."""
        for tier in TIER_CODES:
            key = LicenseKey.generate(tier)
            result = LicenseKey.validate(key)
            self.assertTrue(result["valid"], f"Key for {tier} should be valid")
            self.assertEqual(result["tier"], tier)

    def test_validate_valid_key(self):
        """A freshly generated key must validate."""
        key = LicenseKey.generate("Professional")
        result = LicenseKey.validate(key)
        self.assertTrue(result["valid"])
        self.assertEqual(result["tier"], "Professional")
        self.assertIsNone(result["error"])

    def test_validate_invalid_key(self):
        """Garbage keys must not validate."""
        result = LicenseKey.validate("NOT-A-REAL-KEY-NOPE")
        self.assertFalse(result["valid"])
        self.assertIsNotNone(result["error"])

    def test_validate_tampered_key(self):
        """Flipping a character should break validation."""
        key = LicenseKey.generate("Starter")
        # Tamper with one character in the last group
        parts = key.split("-")
        last = parts[-1]
        tampered_char = "A" if last[0] != "A" else "B"
        parts[-1] = tampered_char + last[1:]
        tampered = "-".join(parts)
        result = LicenseKey.validate(tampered)
        self.assertFalse(result["valid"])

    def test_parse_extracts_tier(self):
        """parse() should extract tier without validation."""
        key = LicenseKey.generate("Enterprise")
        parsed = LicenseKey.parse(key)
        self.assertEqual(parsed["tier_code"], "EN")
        self.assertEqual(parsed["tier"], "Enterprise")
        self.assertEqual(len(parsed["random"]), 10)
        self.assertEqual(len(parsed["checksum"]), 4)

    def test_validate_wrong_secret(self):
        """Key generated with one secret should fail with another."""
        key = LicenseKey.generate("Team", secret="secret-A")
        result = LicenseKey.validate(key, secret="secret-B")
        self.assertFalse(result["valid"])

    def test_license_with_custom_secret(self):
        """Key should validate with matching custom secret."""
        secret = "my-super-secret-key-2026"
        key = LicenseKey.generate("Professional", secret=secret)
        result = LicenseKey.validate(key, secret=secret)
        self.assertTrue(result["valid"])
        self.assertEqual(result["tier"], "Professional")

    def test_generate_uniqueness(self):
        """Two generated keys should be different."""
        k1 = LicenseKey.generate("Community")
        k2 = LicenseKey.generate("Community")
        self.assertNotEqual(k1, k2)

    def test_parse_invalid_key(self):
        """parse() on garbage returns None fields."""
        parsed = LicenseKey.parse("garbage")
        self.assertIsNone(parsed["tier_code"])
        self.assertIsNone(parsed["raw"])


class TestLicenseManager(unittest.TestCase):
    """Tests for the full license management system."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmpfile.close()
        self.db_path = self._tmpfile.name
        self.mgr = LicenseManager(db_path=self.db_path)

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _issue_active(self, tier="Professional", max_nodes=3, **kw):
        """Helper: issue + return license dict."""
        return self.mgr.issue(tier, "test@example.com", max_nodes=max_nodes, **kw)

    def test_issue_license(self):
        """issue() should return a valid license dict."""
        lic = self.mgr.issue("Starter", "user@test.com", customer_name="Test User", company="Acme")
        self.assertIn("key", lic)
        self.assertEqual(lic["tier"], "Starter")
        self.assertEqual(lic["status"], "pending")
        self.assertIn("id", lic)

    def test_activate_license(self):
        """activate() should succeed and update active_nodes."""
        lic = self._issue_active(max_nodes=2)
        result = self.mgr.activate(lic["key"], "node-1", hostname="host1")
        self.assertTrue(result["success"])
        self.assertEqual(result["active_nodes"], 1)

    def test_activate_max_nodes_exceeded(self):
        """activate() should reject when max_nodes is reached."""
        lic = self._issue_active(max_nodes=1)
        self.mgr.activate(lic["key"], "node-1")
        result = self.mgr.activate(lic["key"], "node-2")
        self.assertFalse(result["success"])
        self.assertIn("Max nodes", result["error"])

    def test_deactivate_license(self):
        """deactivate() without node_id should deactivate all."""
        lic = self._issue_active(max_nodes=2)
        self.mgr.activate(lic["key"], "node-1")
        self.mgr.activate(lic["key"], "node-2")
        result = self.mgr.deactivate(lic["key"])
        self.assertTrue(result["success"])
        self.assertEqual(result["active_nodes"], 0)

    def test_deactivate_specific_node(self):
        """deactivate() with node_id should only remove that node."""
        lic = self._issue_active(max_nodes=3)
        self.mgr.activate(lic["key"], "node-1")
        self.mgr.activate(lic["key"], "node-2")
        result = self.mgr.deactivate(lic["key"], node_id="node-1")
        self.assertTrue(result["success"])
        self.assertEqual(result["active_nodes"], 1)

    def test_validate_expired_license(self):
        """Expired license should fail validation."""
        lic = self.mgr.issue("Community", "user@test.com", duration_days=0)
        # Force expiry by setting expires_at to the past
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute("UPDATE licenses SET expires_at = ? WHERE license_key = ?", (past, lic["key"]))
        conn.commit()
        conn.close()

        result = self.mgr.validate(lic["key"])
        self.assertFalse(result["valid"])
        self.assertIn("expired", result["error"].lower())

    def test_revoke_license(self):
        """revoke() should set status to 'revoked'."""
        lic = self._issue_active()
        self.mgr.activate(lic["key"], "node-1")
        result = self.mgr.revoke(lic["key"], reason="Terms violation")
        self.assertTrue(result["success"])

        status = self.mgr.status(lic["key"])
        self.assertEqual(status["status"], "revoked")
        self.assertEqual(status["active_nodes"], 0)

    def test_renew_license(self):
        """renew() should extend expiry."""
        lic = self._issue_active()
        original_expires = lic["expires_at"]
        result = self.mgr.renew(lic["key"], duration_days=180)
        self.assertTrue(result["success"])
        self.assertNotEqual(result["expires_at"], original_expires)

    def test_list_licenses_filter_by_tier(self):
        """list_licenses() should filter by tier."""
        self.mgr.issue("Community", "a@test.com")
        self.mgr.issue("Professional", "b@test.com")
        self.mgr.issue("Community", "c@test.com")

        community = self.mgr.list_licenses(tier="Community")
        self.assertEqual(len(community), 2)
        for lic in community:
            self.assertEqual(lic["tier"], "Community")

    def test_list_licenses_filter_by_status(self):
        """list_licenses() should filter by status."""
        lic1 = self.mgr.issue("Starter", "a@test.com")
        lic2 = self.mgr.issue("Starter", "b@test.com")
        self.mgr.activate(lic1["key"], "node-1")

        active = self.mgr.list_licenses(status="active")
        self.assertEqual(len(active), 1)

        pending = self.mgr.list_licenses(status="pending")
        self.assertEqual(len(pending), 1)

    def test_stats_summary(self):
        """stats() should return correct counts."""
        self.mgr.issue("Community", "a@test.com")
        lic = self.mgr.issue("Professional", "b@test.com", max_nodes=2)
        self.mgr.activate(lic["key"], "node-1")

        stats = self.mgr.stats()
        self.assertEqual(stats["total"], 2)
        self.assertIn("Community", stats["by_tier"])
        self.assertIn("Professional", stats["by_tier"])
        self.assertEqual(stats["active_nodes"], 1)

    def test_cleanup_expired(self):
        """cleanup_expired() should mark expired licenses."""
        self.mgr.issue("Community", "a@test.com")
        lic = self.mgr.issue("Starter", "b@test.com")

        # Force expiry
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute("UPDATE licenses SET expires_at = ? WHERE license_key = ?", (past, lic["key"]))
        conn.commit()
        conn.close()

        count = self.mgr.cleanup_expired()
        self.assertEqual(count, 1)

        status = self.mgr.status(lic["key"])
        self.assertEqual(status["status"], "expired")

    def test_duplicate_activation_same_node(self):
        """Activating the same node_id twice should be idempotent."""
        lic = self._issue_active(max_nodes=1)
        r1 = self.mgr.activate(lic["key"], "node-1")
        self.assertTrue(r1["success"])

        r2 = self.mgr.activate(lic["key"], "node-1")
        self.assertTrue(r2["success"])
        self.assertIn("Already activated", r2.get("message", ""))

        # active_nodes should still be 1
        status = self.mgr.status(lic["key"])
        self.assertEqual(status["active_nodes"], 1)

    def test_audit_trail_recorded(self):
        """All operations should create audit entries."""
        lic = self.mgr.issue("Team", "audit@test.com")
        self.mgr.activate(lic["key"], "node-1")
        self.mgr.deactivate(lic["key"], node_id="node-1")
        self.mgr.revoke(lic["key"], reason="test")

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        audits = conn.execute(
            "SELECT action FROM license_audit WHERE license_id = ? ORDER BY id",
            (lic["id"],),
        ).fetchall()
        conn.close()

        actions = [a["action"] for a in audits]
        self.assertIn("issue", actions)
        self.assertIn("activate", actions)
        self.assertIn("deactivate_node", actions)
        self.assertIn("revoke", actions)

    def test_validate_full_lifecycle(self):
        """Full validation should check DB status and expiry."""
        lic = self._issue_active()
        self.mgr.activate(lic["key"], "node-1")

        result = self.mgr.validate(lic["key"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["tier"], "Professional")
        self.assertEqual(result["status"], "active")

    def test_status_detailed(self):
        """status() should return full details including activations."""
        lic = self._issue_active(max_nodes=2)
        self.mgr.activate(lic["key"], "node-1", hostname="host1", ip_address="1.2.3.4")

        info = self.mgr.status(lic["key"])
        self.assertTrue(info["found"])
        self.assertEqual(info["tier"], "Professional")
        self.assertEqual(len(info["activations"]), 1)
        self.assertEqual(info["activations"][0]["node_id"], "node-1")

    def test_revoke_prevents_activation(self):
        """Revoked license should not be activatable."""
        lic = self._issue_active()
        self.mgr.revoke(lic["key"])
        result = self.mgr.activate(lic["key"], "node-1")
        self.assertFalse(result["success"])
        self.assertIn("revoked", result["error"].lower())

    def test_renew_cannot_renew_revoked(self):
        """Cannot renew a revoked license."""
        lic = self._issue_active()
        self.mgr.revoke(lic["key"])
        result = self.mgr.renew(lic["key"])
        self.assertFalse(result["success"])

    def test_case_insensitive_tier(self):
        """Tier names should be case-insensitive."""
        key = LicenseKey.generate("community")
        result = LicenseKey.validate(key)
        self.assertTrue(result["valid"])
        self.assertEqual(result["tier"], "Community")

    def test_invalid_tier_raises(self):
        """Invalid tier name should raise ValueError."""
        with self.assertRaises(ValueError):
            LicenseKey.generate("InvalidTier")


if __name__ == "__main__":
    unittest.main()
