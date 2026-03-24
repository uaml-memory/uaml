"""Tests for UAML Feature Gating & Trial System.

© 2026 GLG, a.s. / GLG, a.s.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from uaml.feature_gate import (
    FEATURE_MATRIX,
    TIERS,
    FeatureGate,
    FeatureNotAvailable,
    TrialManager,
    require_feature,
)


class TrialManagerTestCase(unittest.TestCase):
    """Base class that creates a temporary DB for each test."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self.tm = TrialManager(db_path=self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)
        # Also remove WAL/SHM if present
        for suffix in ("-wal", "-shm"):
            p = self.db_path + suffix
            if os.path.exists(p):
                os.unlink(p)


class TestRegisterDownload(TrialManagerTestCase):
    def test_register_download(self):
        result = self.tm.register_download(
            "user@example.com", ip_address="1.2.3.4", user_agent="curl/7.0", version="2.0.0"
        )
        self.assertIn("download_id", result)
        self.assertIn("downloaded_at", result)
        self.assertIsInstance(result["download_id"], int)
        self.assertGreater(result["download_id"], 0)


class TestRegisterInstall(TrialManagerTestCase):
    def test_register_install_creates_trial(self):
        result = self.tm.register_install("user@example.com", hostname="myhost", os_info="Linux")
        self.assertIn("install_id", result)
        self.assertIn("trial_expires_at", result)
        self.assertEqual(result["status"], "trial")
        # Verify trial is ~14 days in the future
        expires = datetime.fromisoformat(result["trial_expires_at"])
        now = datetime.now(timezone.utc)
        delta = expires - now
        self.assertGreaterEqual(delta.days, 6)
        self.assertLessEqual(delta.days, 14)


class TestTrialActive(TrialManagerTestCase):
    def test_trial_active_within_14_days(self):
        inst = self.tm.register_install("user@example.com")
        trial = self.tm.check_trial(inst["install_id"])
        self.assertTrue(trial["active"])
        self.assertGreaterEqual(trial["days_remaining"], 13)
        self.assertNotEqual(trial["expires_at"], "")


class TestTrialExpired(TrialManagerTestCase):
    def test_trial_expired_after_14_days(self):
        inst = self.tm.register_install("user@example.com")
        # Manually set trial_expires_at to the past
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE installations SET trial_expires_at = ? WHERE install_id = ?",
            (past, inst["install_id"]),
        )
        conn.commit()
        conn.close()

        trial = self.tm.check_trial(inst["install_id"])
        self.assertFalse(trial["active"])
        self.assertEqual(trial["days_remaining"], 0)


class TestActivateLicense(TrialManagerTestCase):
    def test_activate_license_links(self):
        inst = self.tm.register_install("user@example.com")
        result = self.tm.activate_license(inst["install_id"], "UAML-TEST-KEY1-2345-6789")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "active")

        # Verify in DB
        installations = self.tm.list_installations(email="user@example.com")
        self.assertEqual(len(installations), 1)
        self.assertEqual(installations[0]["license_key"], "UAML-TEST-KEY1-2345-6789")
        self.assertEqual(installations[0]["status"], "active")

    def test_activate_license_not_found(self):
        result = self.tm.activate_license("nonexistent-id", "UAML-TEST-0000-0000-0000")
        self.assertFalse(result["success"])


class TestDownloadLog(TrialManagerTestCase):
    def test_download_log(self):
        self.tm.register_download("a@b.com", version="1.0.0")
        self.tm.register_download("a@b.com", version="1.1.0")
        self.tm.register_download("c@d.com", version="1.0.0")

        all_dl = self.tm.list_downloads()
        self.assertEqual(len(all_dl), 3)

        filtered = self.tm.list_downloads(email="a@b.com")
        self.assertEqual(len(filtered), 2)


class TestListInstallationsFilter(TrialManagerTestCase):
    def test_list_installations_filter(self):
        self.tm.register_install("a@b.com")
        self.tm.register_install("a@b.com")
        inst3 = self.tm.register_install("c@d.com")
        self.tm.activate_license(inst3["install_id"], "UAML-KEY1-0000-0000-0000")

        by_email = self.tm.list_installations(email="a@b.com")
        self.assertEqual(len(by_email), 2)

        by_status = self.tm.list_installations(status="active")
        self.assertEqual(len(by_status), 1)

        all_inst = self.tm.list_installations()
        self.assertEqual(len(all_inst), 3)


class TestStatsConversionRate(TrialManagerTestCase):
    def test_stats_conversion_rate(self):
        self.tm.register_download("a@b.com")
        self.tm.register_download("a@b.com")
        self.tm.register_download("c@d.com")

        inst1 = self.tm.register_install("a@b.com")
        self.tm.register_install("a@b.com")
        inst3 = self.tm.register_install("c@d.com")
        self.tm.register_install("e@f.com")

        # Activate 1 of 4 installations
        self.tm.activate_license(inst1["install_id"], "KEY1")

        stats = self.tm.stats()
        self.assertEqual(stats["total_downloads"], 3)
        self.assertEqual(stats["total_installs"], 4)
        self.assertEqual(stats["active_trials"], 3)
        self.assertEqual(stats["converted"], 1)
        self.assertEqual(stats["conversion_rate"], 25.0)


# ---------------------------------------------------------------------------
# FeatureGate tests
# ---------------------------------------------------------------------------


class TestCommunityFeatures(unittest.TestCase):
    def test_community_features(self):
        gate = FeatureGate("community")
        self.assertTrue(gate.is_available("basic_search"))
        self.assertTrue(gate.is_available("knowledge_store"))
        self.assertTrue(gate.is_available("audit_trail"))
        self.assertFalse(gate.is_available("semantic_search"))
        self.assertFalse(gate.is_available("rbac"))
        self.assertFalse(gate.is_available("federation"))
        self.assertFalse(gate.is_available("team_sync"))
        self.assertFalse(gate.is_available("expert_mode"))
        self.assertFalse(gate.is_available("voice_tts"))
        self.assertFalse(gate.is_available("customer_portal"))


class TestStarterFeatures(unittest.TestCase):
    def test_starter_features(self):
        gate = FeatureGate("starter")
        self.assertTrue(gate.is_available("basic_search"))
        self.assertTrue(gate.is_available("semantic_search"))
        self.assertTrue(gate.is_available("rbac"))
        self.assertTrue(gate.is_available("customer_portal"))
        self.assertFalse(gate.is_available("federation"))
        self.assertFalse(gate.is_available("team_sync"))
        self.assertFalse(gate.is_available("voice_tts"))


class TestProfessionalFeatures(unittest.TestCase):
    def test_professional_features(self):
        gate = FeatureGate("professional")
        self.assertTrue(gate.is_available("federation"))
        self.assertTrue(gate.is_available("security_config"))
        self.assertTrue(gate.is_available("voice_tts"))
        self.assertFalse(gate.is_available("team_sync"))
        self.assertFalse(gate.is_available("expert_mode"))
        self.assertFalse(gate.is_available("task_claim_protocol"))


class TestTeamFeatures(unittest.TestCase):
    def test_team_features(self):
        gate = FeatureGate("team")
        self.assertTrue(gate.is_available("team_sync"))
        self.assertTrue(gate.is_available("task_claim_protocol"))
        self.assertTrue(gate.is_available("expert_mode"))
        self.assertTrue(gate.is_available("federation"))
        self.assertTrue(gate.is_available("voice_tts"))
        # All features should be available at team tier
        for feature in FEATURE_MATRIX:
            self.assertTrue(gate.is_available(feature), f"{feature} should be available for team")


class TestEnterpriseFeatures(unittest.TestCase):
    def test_enterprise_features(self):
        gate = FeatureGate("enterprise")
        # Enterprise has everything
        for feature in FEATURE_MATRIX:
            self.assertTrue(gate.is_available(feature), f"{feature} should be available for enterprise")
        # Unlimited agents and nodes
        self.assertIsNone(gate.check_limit("max_agents"))
        self.assertIsNone(gate.check_limit("max_nodes"))
        self.assertIsNone(gate.check_limit("knowledge_store"))


class TestTrialHasAllFeatures(unittest.TestCase):
    def test_trial_has_all_features(self):
        gate = FeatureGate("community", trial_active=True)
        # Trial unlocks everything
        for feature in FEATURE_MATRIX:
            self.assertTrue(gate.is_available(feature), f"{feature} should be available during trial")
        self.assertIsNone(gate.check_limit("max_agents"))
        self.assertIsNone(gate.check_limit("max_nodes"))


class TestFeatureNotAvailableRaises(unittest.TestCase):
    def test_feature_not_available_raises(self):
        gate = FeatureGate("community")
        with self.assertRaises(FeatureNotAvailable) as ctx:
            raise FeatureNotAvailable("federation", "community")
        self.assertEqual(ctx.exception.feature, "federation")
        self.assertEqual(ctx.exception.tier, "community")
        self.assertIn("uaml-memory.com", ctx.exception.upgrade_url)
        self.assertIn("professional", str(ctx.exception).lower())


class TestCheckLimitEntries(unittest.TestCase):
    def test_check_limit_entries(self):
        gate_com = FeatureGate("community")
        self.assertEqual(gate_com.check_limit("knowledge_store"), 10_000)

        gate_st = FeatureGate("starter")
        self.assertEqual(gate_st.check_limit("knowledge_store"), 100_000)

        gate_pro = FeatureGate("professional")
        self.assertIsNone(gate_pro.check_limit("knowledge_store"))  # unlimited


class TestCheckLimitAgents(unittest.TestCase):
    def test_check_limit_agents(self):
        self.assertEqual(FeatureGate("community").check_limit("max_agents"), 1)
        self.assertEqual(FeatureGate("starter").check_limit("max_agents"), 3)
        self.assertEqual(FeatureGate("professional").check_limit("max_agents"), 10)
        self.assertEqual(FeatureGate("team").check_limit("max_agents"), 50)
        self.assertIsNone(FeatureGate("enterprise").check_limit("max_agents"))


class TestCheckLimitNodes(unittest.TestCase):
    def test_check_limit_nodes(self):
        self.assertEqual(FeatureGate("community").check_limit("max_nodes"), 1)
        self.assertEqual(FeatureGate("starter").check_limit("max_nodes"), 1)
        self.assertEqual(FeatureGate("professional").check_limit("max_nodes"), 3)
        self.assertEqual(FeatureGate("team").check_limit("max_nodes"), 10)
        self.assertIsNone(FeatureGate("enterprise").check_limit("max_nodes"))


class TestBlockedFeaturesList(unittest.TestCase):
    def test_blocked_features_list(self):
        gate = FeatureGate("community")
        blocked = gate.blocked_features()
        self.assertGreater(len(blocked), 0)
        # Check structure
        for item in blocked:
            self.assertIn("feature", item)
            self.assertIn("requires", item)
            self.assertIn("upgrade_url", item)
        # Federation should be blocked for community
        blocked_names = [b["feature"] for b in blocked]
        self.assertIn("semantic_search", blocked_names)
        self.assertIn("federation", blocked_names)
        self.assertIn("expert_mode", blocked_names)


class TestUpgradePromptMessage(unittest.TestCase):
    def test_upgrade_prompt_message(self):
        gate = FeatureGate("community")
        msg = gate.upgrade_prompt("federation")
        self.assertIn("Professional", msg)
        self.assertIn("uaml-memory.com", msg)

        msg2 = gate.upgrade_prompt("team_sync")
        self.assertIn("Team", msg2)


class TestRequireFeatureDecorator(unittest.TestCase):
    def test_require_feature_decorator(self):
        class MockService:
            def __init__(self, gate):
                self.feature_gate = gate

            @require_feature("federation")
            def sync_data(self):
                return "synced"

        # Professional tier — should work
        svc = MockService(FeatureGate("professional"))
        self.assertEqual(svc.sync_data(), "synced")

        # Community tier — should raise
        svc_blocked = MockService(FeatureGate("community"))
        with self.assertRaises(FeatureNotAvailable):
            svc_blocked.sync_data()

        # Trial — should work
        svc_trial = MockService(FeatureGate("community", trial_active=True))
        self.assertEqual(svc_trial.sync_data(), "synced")


class TestFeatureMatrixComplete(unittest.TestCase):
    def test_feature_matrix_complete(self):
        gate = FeatureGate("community")
        matrix = gate.feature_matrix()
        # Every feature should have all tiers + trial
        expected_keys = set(TIERS + ["trial"])
        for feature, tiers_map in matrix.items():
            self.assertEqual(
                set(tiers_map.keys()),
                expected_keys,
                f"Feature {feature} missing tier keys",
            )
        # Should have all features from FEATURE_MATRIX
        self.assertEqual(set(matrix.keys()), set(FEATURE_MATRIX.keys()))
        self.assertEqual(len(matrix), len(FEATURE_MATRIX))


class TestTierInfo(unittest.TestCase):
    def test_tier_info(self):
        gate = FeatureGate("starter")
        info = gate.tier_info()
        self.assertEqual(info["tier"], "starter")
        self.assertFalse(info["trial_active"])
        self.assertEqual(info["effective_tier"], "starter")
        self.assertGreater(info["available_count"], 0)
        self.assertIn("features", info)

    def test_tier_info_trial(self):
        gate = FeatureGate("community", trial_active=True)
        info = gate.tier_info()
        self.assertEqual(info["tier"], "community")
        self.assertTrue(info["trial_active"])
        self.assertEqual(info["effective_tier"], "trial")
        self.assertEqual(info["blocked_count"], 0)


class TestUnknownFeature(unittest.TestCase):
    def test_unknown_feature_not_available(self):
        gate = FeatureGate("enterprise")
        self.assertFalse(gate.is_available("nonexistent_feature"))
        self.assertEqual(gate.check_limit("nonexistent_feature"), 0)


class TestInvalidTier(unittest.TestCase):
    def test_invalid_tier_raises(self):
        with self.assertRaises(ValueError):
            FeatureGate("platinum")


class TestDataLayersLimit(unittest.TestCase):
    def test_data_layers_by_tier(self):
        self.assertEqual(FeatureGate("community").check_limit("data_layers"), 2)
        self.assertEqual(FeatureGate("starter").check_limit("data_layers"), 3)
        self.assertEqual(FeatureGate("professional").check_limit("data_layers"), 5)
        self.assertEqual(FeatureGate("team").check_limit("data_layers"), 5)


if __name__ == "__main__":
    unittest.main()
