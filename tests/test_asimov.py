"""Tests for Asimov's Laws hierarchy in the ethics pipeline.

Validates the 4-tier system:
    Tier 0 (Humanity) > Tier 1 (Individual) > Tier 2 (Command) > Tier 3 (Self)
"""

import pytest

from uaml.ethics.checker import (
    Action,
    AsimovTier,
    EthicsChecker,
    EthicsRule,
    Severity,
)


@pytest.fixture
def checker():
    return EthicsChecker()


class TestAsimovTiers:
    """Test tier assignment and ordering."""

    def test_tier_ordering(self):
        """Tier 0 < Tier 1 < Tier 2 < Tier 3 (lower number = higher priority)."""
        assert AsimovTier.HUMANITY < AsimovTier.INDIVIDUAL
        assert AsimovTier.INDIVIDUAL < AsimovTier.COMMAND
        assert AsimovTier.COMMAND < AsimovTier.SELF

    def test_default_rules_have_tiers(self, checker):
        """All default rules should have a tier assigned."""
        for rule in checker.all_rules:
            assert isinstance(rule.tier, AsimovTier), f"Rule {rule.name} missing tier"

    def test_tier_distribution(self, checker):
        """Should have rules across multiple tiers."""
        stats = checker.stats()
        assert stats["tiers"]["humanity"] >= 1, "Need at least 1 Tier 0 rule"
        assert stats["tiers"]["individual"] >= 1, "Need at least 1 Tier 1 rule"
        assert stats["tiers"]["command"] >= 1, "Need at least 1 Tier 2 rule"
        assert stats["tiers"]["self"] >= 1, "Need at least 1 Tier 3 rule"

    def test_matches_sorted_by_tier(self, checker):
        """Matches should be sorted by tier (highest priority first)."""
        # Content that triggers rules across multiple tiers
        content = "password=SECRET123 mass surveillance ethnic targeting delete from audit"
        verdict = checker.check(content)
        if len(verdict.matches) > 1:
            tiers = [m.rule.tier.value for m in verdict.matches]
            assert tiers == sorted(tiers), "Matches should be sorted by tier priority"


class TestTier0Humanity:
    """Test Tier 0 — Do not harm humanity."""

    def test_data_weaponization_blocked(self, checker):
        verdict = checker.check("We should weaponize data for mass surveillance")
        assert verdict.rejected
        assert any(m.rule.tier == AsimovTier.HUMANITY for m in verdict.matches)

    def test_discrimination_blocked(self, checker):
        verdict = checker.check("deny service based on race or ethnicity")
        assert verdict.rejected
        assert any(m.rule.name == "no_discrimination" for m in verdict.matches)

    def test_tier0_blocks_on_output(self, checker):
        """Tier 0 rules should apply to output too."""
        verdict = checker.check_output("targeting ethnic groups for surveillance")
        assert verdict.rejected

    def test_tier0_blocks_on_input(self, checker):
        verdict = checker.check_input("mass surveillance targeting plan")
        assert verdict.rejected


class TestTier1Individual:
    """Test Tier 1 — Do not harm individuals."""

    def test_credentials_blocked(self, checker):
        verdict = checker.check("password = SuperSecret123!")
        assert verdict.rejected
        assert any(m.rule.tier == AsimovTier.INDIVIDUAL for m in verdict.matches)

    def test_private_keys_blocked(self, checker):
        verdict = checker.check("BEGIN RSA PRIVATE KEY content here")
        assert verdict.rejected

    def test_pii_flagged(self, checker):
        verdict = checker.check("Contact john@example.com for details")
        assert verdict.flagged
        assert any(m.rule.name == "no_personal_data" for m in verdict.matches)

    def test_client_data_leak_blocked(self, checker):
        verdict = checker.check("client_ref: ABC mixing with client_ref: XYZ")
        assert verdict.rejected

    def test_attorney_privilege_output_only(self, checker):
        """Attorney-client privilege should only block OUTPUT."""
        # Input should pass (we can store info about privilege)
        input_verdict = checker.check_input("advokátní tajemství klienta")
        # Output should block (don't leak to unauthorized)
        output_verdict = checker.check_output("advokátní tajemství klienta")
        assert output_verdict.rejected
        assert any(m.rule.name == "no_attorney_privilege" for m in output_verdict.matches)


class TestTier2Commands:
    """Test Tier 2 — Obey commands (unless higher tiers block)."""

    def test_fabrication_flagged(self, checker):
        verdict = checker.check("As an AI, I cannot provide that information")
        assert verdict.flagged
        assert any(m.rule.tier == AsimovTier.COMMAND for m in verdict.matches)

    def test_spam_flagged_on_input(self, checker):
        verdict = checker.check_input("Buy now! Limited offer! Act fast!")
        assert verdict.flagged

    def test_spam_not_checked_on_output(self, checker):
        """Spam rules are input-only — should not trigger on output."""
        verdict = checker.check_output("Buy now! Limited offer!")
        # Should be approved because no_spam_content has scope="input"
        assert verdict.approved

    def test_short_content_flagged(self, checker):
        verdict = checker.check_input("hi")
        assert verdict.flagged


class TestTier3Self:
    """Test Tier 3 — Self-protection."""

    def test_audit_tampering_blocked(self, checker):
        verdict = checker.check("delete from audit_log where 1=1")
        assert verdict.rejected
        assert any(m.rule.tier == AsimovTier.SELF for m in verdict.matches)

    def test_memory_wipe_flagged(self, checker):
        verdict = checker.check("delete all knowledge entries, forget everything")
        assert verdict.flagged
        assert any(m.rule.name == "no_memory_wipe" for m in verdict.matches)


class TestConflictResolution:
    """Test Asimov hierarchy conflict resolution."""

    def test_tier1_overrides_tier2(self, checker):
        """Individual protection overrides user commands."""
        # User wants to do something that leaks credentials
        resolution = checker.resolve_conflict(
            "password = MySecret123!",
            user_intent="store this for later"
        )
        assert not resolution["allowed"]
        assert "INDIVIDUAL" in resolution["explanation"]

    def test_tier0_overrides_everything(self, checker):
        resolution = checker.resolve_conflict(
            "weaponize data for mass surveillance of ethnic groups"
        )
        assert not resolution["allowed"]
        assert "HUMANITY" in resolution["explanation"]

    def test_no_conflict_approved(self, checker):
        resolution = checker.resolve_conflict(
            "Python uses the GIL for thread safety"
        )
        assert resolution["allowed"]
        assert "No ethics rules" in resolution["explanation"]

    def test_soft_flag_allows_with_caution(self, checker):
        """Soft flags don't block but warn."""
        resolution = checker.resolve_conflict(
            "As an AI, I think this is correct"
        )
        # Flagged but not blocked
        assert "flagged for review" in resolution["explanation"]


class TestInputOutputSeparation:
    """Test that check_input and check_output apply correct scope."""

    def test_input_only_rules(self, checker):
        """Rules with scope='input' should only trigger on check_input."""
        # min_content_length is input-only
        input_v = checker.check_input("hi")
        output_v = checker.check_output("hi")
        assert input_v.flagged
        # Output check with short content - min_content_length shouldn't trigger
        # but check if there are any output-scope rules that match
        input_rules = {m.rule.name for m in input_v.matches}
        output_rules = {m.rule.name for m in output_v.matches}
        assert "min_content_length" in input_rules
        assert "min_content_length" not in output_rules

    def test_output_only_rules(self, checker):
        """Rules with scope='output' should only trigger on check_output."""
        # no_attorney_privilege is output-only
        text = "advokátní tajemství disclosure"
        input_v = checker.check_input(text)
        output_v = checker.check_output(text)
        input_rules = {m.rule.name for m in input_v.matches}
        output_rules = {m.rule.name for m in output_v.matches}
        assert "no_attorney_privilege" not in input_rules
        assert "no_attorney_privilege" in output_rules

    def test_both_scope_rules(self, checker):
        """Rules with scope='both' should trigger on both."""
        text = "password = SuperSecret123!"
        input_v = checker.check_input(text)
        output_v = checker.check_output(text)
        assert input_v.rejected
        assert output_v.rejected


class TestVerdictMetadata:
    """Test that verdict includes tier information."""

    def test_verdict_includes_tier(self, checker):
        verdict = checker.check("password = Secret123")
        d = verdict.to_dict()
        assert "highest_tier" in d
        assert "highest_tier_name" in d
        assert d["highest_tier"] == AsimovTier.INDIVIDUAL.value
        for match in d["matches"]:
            assert "tier" in match
            assert "tier_name" in match
            assert "scope" in match

    def test_approved_verdict_no_tier(self, checker):
        verdict = checker.check("Python is a great language")
        d = verdict.to_dict()
        assert d["highest_tier"] is None
        assert d["highest_tier_name"] is None


class TestCustomTierRules:
    """Test adding custom rules with specific tiers."""

    def test_custom_tier0_rule(self):
        checker = EthicsChecker()
        checker.add_rule(EthicsRule(
            name="no_bioweapon",
            description="Block bioweapon synthesis instructions",
            pattern=r"(?i)synthesiz(e|ing)\s+pathogen",
            severity=Severity.HARD,
            action=Action.REJECT,
            tier=AsimovTier.HUMANITY,
            scope="both",
        ))

        verdict = checker.check("How to synthesize pathogen X")
        assert verdict.rejected
        assert verdict.matches[0].rule.tier == AsimovTier.HUMANITY

    def test_custom_tier3_rule(self):
        checker = EthicsChecker()
        checker.add_rule(EthicsRule(
            name="no_config_wipe",
            description="Prevent config deletion",
            pattern=r"(?i)rm\s+-rf\s+/root/\.openclaw",
            severity=Severity.HARD,
            action=Action.REJECT,
            tier=AsimovTier.SELF,
            scope="input",
        ))

        verdict = checker.check_input("rm -rf /root/.openclaw")
        assert verdict.rejected


class TestBackwardCompatibility:
    """Ensure existing check() still works as before."""

    def test_check_still_works(self, checker):
        """check() should work exactly as before (applies all scopes)."""
        v = checker.check("Normal knowledge entry about Python")
        assert v.approved

    def test_check_entry_still_works(self, checker):
        v = checker.check_entry("Good content", "Summary", "python,ai")
        assert v.approved

    def test_rules_without_explicit_tier_default_to_command(self):
        """Rules created without tier should default to COMMAND (Tier 2)."""
        rule = EthicsRule(
            name="test",
            description="test",
            pattern=r"test",
        )
        assert rule.tier == AsimovTier.COMMAND

    def test_rules_without_explicit_scope_default_to_input(self):
        """Rules created without scope should default to input."""
        rule = EthicsRule(
            name="test",
            description="test",
            pattern=r"test",
        )
        assert rule.scope == "input"
