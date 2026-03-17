"""Tests for UAML Data Sanitizer."""

from __future__ import annotations

import pytest

from uaml.security.sanitizer import DataSanitizer


@pytest.fixture
def sanitizer():
    return DataSanitizer()


class TestDataSanitizer:
    def test_email_redaction(self, sanitizer):
        result = sanitizer.sanitize("Contact john@example.com for info")
        assert "[EMAIL_REDACTED]" in result.cleaned
        assert result.was_modified

    def test_phone_redaction(self, sanitizer):
        result = sanitizer.sanitize("Call 555-123-4567 now")
        assert "[PHONE_REDACTED]" in result.cleaned

    def test_ip_redaction(self, sanitizer):
        result = sanitizer.sanitize("Server at 192.168.1.100")
        assert "[IP_REDACTED]" in result.cleaned

    def test_credit_card(self, sanitizer):
        result = sanitizer.sanitize("Card: 4111-1111-1111-1111")
        assert "[CC_REDACTED]" in result.cleaned

    def test_password_field(self, sanitizer):
        result = sanitizer.sanitize("password: mysecret123")
        assert "[PASSWORD_REDACTED]" in result.cleaned

    def test_no_sensitive_data(self, sanitizer):
        result = sanitizer.sanitize("Just a normal sentence.")
        assert not result.was_modified
        assert result.redacted_count == 0

    def test_empty_string(self, sanitizer):
        result = sanitizer.sanitize("")
        assert result.cleaned == ""

    def test_detect_only(self, sanitizer):
        findings = sanitizer.detect_only("Email: test@test.com")
        assert len(findings) >= 1
        assert findings[0]["category"] == "email"

    def test_category_filter(self, sanitizer):
        result = sanitizer.sanitize(
            "john@test.com at 192.168.1.1",
            categories=["email"],
        )
        assert "[EMAIL_REDACTED]" in result.cleaned
        assert "192.168.1.1" in result.cleaned  # IP not redacted

    def test_custom_pattern(self, sanitizer):
        sanitizer.add_pattern("czech_id", r'\b\d{6}/\d{4}\b', "[ID_REDACTED]")
        result = sanitizer.sanitize("RČ: 900101/1234")
        assert "[ID_REDACTED]" in result.cleaned

    def test_remove_pattern(self, sanitizer):
        assert sanitizer.remove_pattern("email") is True
        result = sanitizer.sanitize("test@test.com")
        assert result.was_modified is False

    def test_list_patterns(self, sanitizer):
        patterns = sanitizer.list_patterns()
        assert "email" in patterns
        assert "phone" in patterns

    def test_multiple_findings(self, sanitizer):
        result = sanitizer.sanitize("Email john@test.com and jane@test.com")
        assert result.redacted_count == 2
