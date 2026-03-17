"""Tests for UAML Customer Portal — CustomerDB and authentication.

At least 20 tests covering registration, login, tokens, customer management,
newsletter, stats, audit trail, and security.

© 2026 Ladislav Zamazal / GLG, a.s.
"""

import os
import sys
import tempfile
import time
import unittest

# Ensure uaml package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from uaml.customer import (
    CustomerDB,
    _hash_password,
    _verify_password,
    _generate_token,
    _verify_token,
    _TOKEN_SECRET,
)


class TestCustomerDB(unittest.TestCase):
    """Test suite for CustomerDB."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = CustomerDB(self.tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    # -- Registration -------------------------------------------------------

    def test_register_customer(self):
        result = self.db.register("alice@example.com", "secret123", name="Alice", company="ACME")
        self.assertTrue(result["success"])
        self.assertIn("customer_id", result)
        self.assertEqual(result["email"], "alice@example.com")

    def test_register_duplicate_email(self):
        self.db.register("bob@example.com", "pass1")
        result = self.db.register("bob@example.com", "pass2")
        self.assertFalse(result["success"])
        self.assertIn("already registered", result["error"].lower())

    def test_register_empty_email(self):
        result = self.db.register("", "pass")
        self.assertFalse(result["success"])

    def test_register_email_case_insensitive(self):
        self.db.register("Alice@Example.COM", "pass1")
        result = self.db.register("alice@example.com", "pass2")
        self.assertFalse(result["success"])

    # -- Login --------------------------------------------------------------

    def test_login_success(self):
        self.db.register("login@test.com", "mypassword", name="Test")
        result = self.db.login("login@test.com", "mypassword")
        self.assertTrue(result["success"])
        self.assertIn("token", result)
        self.assertIn("customer_id", result)

    def test_login_wrong_password(self):
        self.db.register("user@test.com", "correct")
        result = self.db.login("user@test.com", "wrong")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_login_nonexistent_email(self):
        result = self.db.login("nobody@test.com", "pass")
        self.assertFalse(result["success"])

    def test_login_updates_last_login(self):
        self.db.register("ts@test.com", "pass")
        self.db.login("ts@test.com", "pass")
        customer = self.db.list_customers()[0]
        self.assertIsNotNone(customer["last_login"])

    # -- Token verification -------------------------------------------------

    def test_verify_valid_token(self):
        reg = self.db.register("token@test.com", "pass", name="Tok")
        login = self.db.login("token@test.com", "pass")
        self.assertTrue(login["success"])

        result = self.db.verify_token(login["token"])
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "token@test.com")

    def test_verify_expired_token(self):
        """Token with timestamp far in the past should be rejected."""
        # Manually craft an expired token
        cid = 999
        old_ts = str(int(time.time()) - 100000)  # ~28 hours ago
        payload = f"{cid}:{old_ts}"
        import hashlib
        import hmac as _hmac
        sig = _hmac.new(_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        expired_token = f"{cid}:{old_ts}:{sig}"

        result = _verify_token(expired_token)
        self.assertIsNone(result)

    def test_verify_invalid_token(self):
        result = self.db.verify_token("garbage:token:value")
        self.assertIsNone(result)

    def test_verify_tampered_token(self):
        reg = self.db.register("tamper@test.com", "pass")
        login = self.db.login("tamper@test.com", "pass")
        # Tamper with the signature
        parts = login["token"].split(":")
        parts[2] = "0" * 64
        tampered = ":".join(parts)
        result = self.db.verify_token(tampered)
        self.assertIsNone(result)

    # -- Customer management ------------------------------------------------

    def test_get_customer(self):
        reg = self.db.register("get@test.com", "pass", name="Getter", company="Co")
        customer = self.db.get_customer(reg["customer_id"])
        self.assertIsNotNone(customer)
        self.assertEqual(customer["email"], "get@test.com")
        self.assertEqual(customer["name"], "Getter")
        self.assertEqual(customer["company"], "Co")

    def test_get_customer_nonexistent(self):
        result = self.db.get_customer(99999)
        self.assertIsNone(result)

    def test_update_customer(self):
        reg = self.db.register("upd@test.com", "pass")
        result = self.db.update_customer(reg["customer_id"], name="Updated", company="NewCo")
        self.assertTrue(result["success"])
        customer = self.db.get_customer(reg["customer_id"])
        self.assertEqual(customer["name"], "Updated")
        self.assertEqual(customer["company"], "NewCo")

    def test_update_customer_invalid_field(self):
        reg = self.db.register("inv@test.com", "pass")
        result = self.db.update_customer(reg["customer_id"], password_hash="evil")
        self.assertFalse(result["success"])

    def test_list_customers(self):
        self.db.register("a@test.com", "p")
        self.db.register("b@test.com", "p")
        self.db.register("c@test.com", "p")
        all_customers = self.db.list_customers()
        self.assertEqual(len(all_customers), 3)

    def test_list_customers_by_status(self):
        reg = self.db.register("sus@test.com", "p")
        self.db.update_customer(reg["customer_id"], status="suspended")
        self.db.register("act@test.com", "p")

        active = self.db.list_customers(status="active")
        self.assertEqual(len(active), 1)
        suspended = self.db.list_customers(status="suspended")
        self.assertEqual(len(suspended), 1)

    # -- Licenses -----------------------------------------------------------

    def test_link_license(self):
        reg = self.db.register("lic@test.com", "p")
        result = self.db.link_license(
            reg["customer_id"], "UAML-TEST-1234-5678-ABCD",
            "Professional", amount_eur=99.0, payment_ref="INV-001"
        )
        self.assertTrue(result["success"])
        self.assertIn("license_id", result)

    def test_customer_licenses(self):
        reg = self.db.register("lics@test.com", "p")
        self.db.link_license(reg["customer_id"], "UAML-KEY1-1111-2222-3333", "Starter", amount_eur=29.0)
        self.db.link_license(reg["customer_id"], "UAML-KEY2-4444-5555-6666", "Professional", amount_eur=99.0)

        licenses = self.db.customer_licenses(reg["customer_id"])
        self.assertEqual(len(licenses), 2)
        tiers = {lic["tier"] for lic in licenses}
        self.assertIn("Starter", tiers)
        self.assertIn("Professional", tiers)

    # -- Newsletter ---------------------------------------------------------

    def test_subscribe_newsletter(self):
        result = self.db.subscribe("news@test.com", source="web")
        self.assertTrue(result["success"])

    def test_subscribe_duplicate(self):
        """Subscribing the same email twice should be idempotent."""
        self.db.subscribe("dup@test.com")
        result = self.db.subscribe("dup@test.com")
        self.assertTrue(result["success"])
        self.assertIn("already", result["message"].lower())

    def test_subscribe_reactivate(self):
        """Re-subscribing after unsubscribe should reactivate."""
        self.db.subscribe("react@test.com")
        self.db.unsubscribe("react@test.com")
        result = self.db.subscribe("react@test.com")
        self.assertTrue(result["success"])
        self.assertIn("resubscribed", result["message"].lower())

    def test_unsubscribe(self):
        self.db.subscribe("unsub@test.com")
        result = self.db.unsubscribe("unsub@test.com")
        self.assertTrue(result["success"])

    def test_unsubscribe_nonexistent(self):
        result = self.db.unsubscribe("nobody@test.com")
        self.assertFalse(result["success"])

    def test_subscriber_count(self):
        self.db.subscribe("s1@test.com")
        self.db.subscribe("s2@test.com")
        self.db.subscribe("s3@test.com")
        self.db.unsubscribe("s3@test.com")

        counts = self.db.subscriber_count()
        self.assertEqual(counts["active"], 2)
        self.assertEqual(counts["total"], 3)

    def test_list_subscribers(self):
        self.db.subscribe("ls1@test.com", source="web")
        self.db.subscribe("ls2@test.com", source="purchase")
        subs = self.db.list_subscribers("active")
        self.assertEqual(len(subs), 2)

    # -- Stats --------------------------------------------------------------

    def test_stats_summary(self):
        self.db.register("st1@test.com", "p")
        self.db.register("st2@test.com", "p")
        reg = self.db.register("st3@test.com", "p")
        self.db.link_license(reg["customer_id"], "UAML-STAT-1111-2222-3333", "Professional", amount_eur=99.0)
        self.db.link_license(reg["customer_id"], "UAML-STAT-4444-5555-6666", "Starter", amount_eur=29.0)
        self.db.subscribe("st1@test.com")

        stats = self.db.stats()
        self.assertEqual(stats["total_customers"], 3)
        self.assertEqual(stats["active"], 3)
        self.assertAlmostEqual(stats["revenue_total"], 128.0)
        self.assertEqual(stats["subscribers"], 1)
        self.assertIn("Professional", stats["by_tier"])
        self.assertIn("Starter", stats["by_tier"])

    # -- Audit trail --------------------------------------------------------

    def test_audit_trail(self):
        reg = self.db.register("audit@test.com", "p")
        self.db.login("audit@test.com", "p")
        self.db.update_customer(reg["customer_id"], name="Audited")
        self.db.link_license(reg["customer_id"], "UAML-AUD-1111-2222-3333", "Starter")

        audit = self.db.get_audit(reg["customer_id"])
        self.assertGreaterEqual(len(audit), 4)
        actions = [a["action"] for a in audit]
        self.assertIn("register", actions)
        self.assertIn("login", actions)
        self.assertIn("update", actions)
        self.assertIn("link_license", actions)

    def test_audit_failed_login(self):
        self.db.register("fail@test.com", "pass")
        self.db.login("fail@test.com", "wrong")
        audit = self.db.get_audit()
        actions = [a["action"] for a in audit]
        self.assertIn("login_failed", actions)

    # -- Security -----------------------------------------------------------

    def test_password_hash_is_not_plaintext(self):
        """Password must be stored as PBKDF2 hash, not plaintext."""
        self.db.register("hash@test.com", "supersecret")
        # Read raw from DB
        import sqlite3
        conn = sqlite3.connect(self.tmp.name)
        row = conn.execute("SELECT password_hash FROM customers WHERE email = 'hash@test.com'").fetchone()
        conn.close()

        stored = row[0]
        self.assertNotEqual(stored, "supersecret")
        self.assertIn(":", stored)  # salt:hash format
        self.assertGreater(len(stored), 64)  # should be substantial

    def test_password_hash_verify(self):
        """Low-level password hash/verify functions."""
        h = _hash_password("testpass")
        self.assertTrue(_verify_password("testpass", h))
        self.assertFalse(_verify_password("wrong", h))

    def test_token_format(self):
        """Token should have customer_id:timestamp:signature format."""
        token = _generate_token(42)
        parts = token.split(":")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "42")
        # Timestamp should be recent
        ts = int(parts[1])
        self.assertAlmostEqual(ts, time.time(), delta=5)
        # Signature should be hex
        self.assertEqual(len(parts[2]), 64)  # SHA256 hex

    def test_different_salts(self):
        """Two hashes of the same password should use different salts."""
        h1 = _hash_password("samepass")
        h2 = _hash_password("samepass")
        self.assertNotEqual(h1, h2)  # Different salts
        self.assertTrue(_verify_password("samepass", h1))
        self.assertTrue(_verify_password("samepass", h2))


if __name__ == "__main__":
    unittest.main()
