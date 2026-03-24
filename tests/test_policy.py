"""Tests for context budgeting and output complexity policy resolution."""

from uaml.core.policy import (
    ModelProfile,
    OutputProfile,
    PolicyDecision,
    ProvenanceMode,
    QueryClass,
    RecallTier,
    RiskLevel,
    resolve_policy,
)


class TestPolicyResolution:
    def test_casual_is_none_and_brief(self):
        decision = resolve_policy(QueryClass.CASUAL, ModelProfile.CLOUD_FAST)
        assert isinstance(decision, PolicyDecision)
        assert decision.recall_tier == RecallTier.NONE
        assert decision.output_profile == OutputProfile.BRIEF
        assert decision.budget_tokens == 0
        assert decision.provenance_mode == ProvenanceMode.OFF

    def test_cloud_fast_factual_stays_micro(self):
        decision = resolve_policy(QueryClass.FACTUAL, ModelProfile.CLOUD_FAST)
        assert decision.recall_tier == RecallTier.MICRO
        assert decision.output_profile == OutputProfile.BRIEF
        assert 100 <= decision.budget_tokens <= 300

    def test_cloud_expensive_planning_stays_small(self):
        decision = resolve_policy(QueryClass.PLANNING, ModelProfile.CLOUD_EXPENSIVE)
        assert decision.recall_tier == RecallTier.MICRO
        assert decision.output_profile == OutputProfile.STANDARD
        assert decision.provenance_mode == ProvenanceMode.MINIMAL

    def test_cloud_large_context_strategic_can_go_deep(self):
        decision = resolve_policy(
            QueryClass.STRATEGIC,
            ModelProfile.CLOUD_LARGE_CONTEXT,
            RiskLevel.HIGH,
        )
        assert decision.recall_tier == RecallTier.FULL
        assert decision.output_profile == OutputProfile.DEEP
        assert decision.provenance_mode == ProvenanceMode.FULL
        assert 900 <= decision.budget_tokens <= 2500

    def test_local_weak_simplifies_output(self):
        decision = resolve_policy(QueryClass.STRATEGIC, ModelProfile.LOCAL_WEAK)
        assert decision.recall_tier == RecallTier.STANDARD
        assert decision.output_profile == OutputProfile.STANDARD
        assert decision.provenance_mode == ProvenanceMode.OFF

    def test_local_rich_planning_is_standard(self):
        decision = resolve_policy(QueryClass.PLANNING, ModelProfile.LOCAL_RICH)
        assert decision.recall_tier == RecallTier.STANDARD
        assert decision.output_profile == OutputProfile.STANDARD
        assert decision.provenance_mode == ProvenanceMode.MINIMAL

    def test_audit_always_full(self):
        decision = resolve_policy(QueryClass.AUDIT, ModelProfile.CLOUD_FAST)
        assert decision.recall_tier == RecallTier.FULL
        assert decision.output_profile == OutputProfile.AUDIT
        assert decision.provenance_mode == ProvenanceMode.FULL

    def test_certification_profile_forces_audit(self):
        decision = resolve_policy(QueryClass.OPERATIONAL, ModelProfile.CERTIFICATION)
        assert decision.recall_tier == RecallTier.FULL
        assert decision.output_profile == OutputProfile.AUDIT
        assert decision.provenance_mode == ProvenanceMode.FULL


class TestPolicyRecall:
    """Tests for policy-aware recall integration in MemoryStore."""

    def setup_method(self):
        """Create a temporary store with test data."""
        from uaml.core.store import MemoryStore
        self.store = MemoryStore(":memory:", agent_id="test")
        # Add some test knowledge
        self.store.learn("Python's GIL prevents true multithreading", topic="python")
        self.store.learn("UAML uses SQLite for local-first storage", topic="uaml")
        self.store.learn("ML-KEM-768 is a post-quantum key encapsulation mechanism", topic="security")
        self.store.learn("Audit trails must be immutable and append-only", topic="compliance")
        self.store.learn("Focus Engine prioritizes tasks using P0-P3 levels", topic="uaml")

    def teardown_method(self):
        self.store.close()

    def test_casual_returns_empty(self):
        result = self.store.policy_recall(
            "hello",
            query_class="casual",
            model_profile="cloud_fast",
        )
        assert result["policy"]["recall_tier"] == "none"
        assert result["results"] == []
        assert result["policy"]["budget_tokens"] == 0

    def test_factual_returns_limited(self):
        result = self.store.policy_recall(
            "python threading",
            query_class="factual",
            model_profile="cloud_fast",
        )
        assert result["policy"]["recall_tier"] == "micro"
        assert len(result["results"]) <= 3
        assert result["policy"]["output_profile"] == "brief"

    def test_audit_returns_full(self):
        result = self.store.policy_recall(
            "audit compliance",
            query_class="audit",
            model_profile="cloud_standard",
        )
        assert result["policy"]["recall_tier"] == "full"
        assert result["policy"]["provenance_mode"] == "full"
        assert result["policy"]["output_profile"] == "audit"

    def test_strategic_high_risk_expands(self):
        result = self.store.policy_recall(
            "security encryption",
            query_class="strategic",
            model_profile="cloud_large_context",
            risk_level="high",
        )
        assert result["policy"]["recall_tier"] == "full"
        assert result["policy"]["budget_tokens"] >= 900

    def test_policy_dict_has_all_fields(self):
        result = self.store.policy_recall(
            "UAML storage",
            query_class="operational",
            model_profile="cloud_standard",
        )
        policy = result["policy"]
        assert "recall_tier" in policy
        assert "output_profile" in policy
        assert "response_scope" in policy
        assert "budget_tokens" in policy
        assert "provenance_mode" in policy

    def test_budget_limits_results(self):
        """Results should not exceed budget_tokens."""
        result = self.store.policy_recall(
            "UAML",
            query_class="factual",
            model_profile="cloud_fast",
        )
        # Micro tier: budget 100-300 tokens ≈ 400-1200 chars
        total_chars = sum(len(r.entry.content) for r in result["results"])
        max_chars = result["policy"]["budget_tokens"] * 4 + 200  # margin for short entries
        assert total_chars <= max_chars
