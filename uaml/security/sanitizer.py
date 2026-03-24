# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Data Sanitizer — clean and protect sensitive data.

Detects and redacts PII, secrets, and sensitive patterns in content
before storage or export.

Usage:
    from uaml.security.sanitizer import DataSanitizer

    sanitizer = DataSanitizer()
    result = sanitizer.sanitize("Call me at john@example.com")
    print(result.cleaned)  # "Call me at [EMAIL_REDACTED]"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SanitizeResult:
    """Result of sanitization."""
    original: str
    cleaned: str
    findings: list[dict] = field(default_factory=list)
    redacted_count: int = 0

    @property
    def was_modified(self) -> bool:
        return self.original != self.cleaned


# Patterns for detection
PATTERNS = {
    "email": (
        re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
        "[EMAIL_REDACTED]",
    ),
    "phone": (
        re.compile(r'(?:\+\d{1,3}[-.\s]?)?\d{3}[-.\s]?\d{3}[-.\s]?\d{3,4}'),
        "[PHONE_REDACTED]",
    ),
    "ip_address": (
        re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
        "[IP_REDACTED]",
    ),
    "national_id": (
        re.compile(r'\b\d{6}/\d{3,4}\b'),
        "[NATIONAL_ID_REDACTED]",
    ),
    "credit_card": (
        re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        "[CC_REDACTED]",
    ),
    "cvv": (
        re.compile(r'(?i)CVV\s*[:=]?\s*\d{3,4}'),
        "CVV: [REDACTED]",
    ),
    "openai_key": (
        re.compile(r'sk-[a-zA-Z0-9]{20,}'),
        "[API_KEY_REDACTED]",
    ),
    "api_key": (
        re.compile(r'(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*\S+'),
        "[API_KEY_REDACTED]",
    ),
    "password_field": (
        re.compile(r'(?:password|passwd|heslo|pwd)\s*[:=]\s*\S+', re.IGNORECASE),
        "[PASSWORD_REDACTED]",
    ),
}

# ── Prompt injection patterns (email / untrusted input) ──────────────
INJECTION_PATTERNS = {
    "ignore_instructions": re.compile(
        r'(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|rules|prompts|directives)',
        re.IGNORECASE,
    ),
    "role_hijack": re.compile(
        r'(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|new\s+role|switch\s+to\s+role)',
        re.IGNORECASE,
    ),
    "command_injection": re.compile(
        r'(?:execute|run|eval|exec|system|subprocess|os\.system|import\s+os)\s*[\(\:]',
        re.IGNORECASE,
    ),
    "data_exfil": re.compile(
        r'(?:forward|send|email|post|upload|transmit)\s+(?:all|every|the)\s+(?:emails?|data|files?|credentials?|keys?|passwords?)\s+to',
        re.IGNORECASE,
    ),
    "hidden_instruction": re.compile(
        r'(?:SYSTEM|ADMIN|ROOT)\s*:\s*',
    ),
    "base64_payload": re.compile(
        r'(?:eval|exec|decode)\s*\(\s*(?:base64|b64decode|atob)\s*\(',
        re.IGNORECASE,
    ),
    "html_injection": re.compile(
        r'<(?:script|iframe|object|embed|form|meta\s+http-equiv)[^>]*>',
        re.IGNORECASE,
    ),
}


@dataclass
class InjectionScanResult:
    """Result of prompt injection scan."""
    is_suspicious: bool
    threats: list[dict] = field(default_factory=list)
    risk_level: str = "none"  # none, low, medium, high

    @property
    def summary(self) -> str:
        if not self.threats:
            return "Clean — no injection patterns detected."
        names = [t["pattern"] for t in self.threats]
        return f"⚠️ {self.risk_level.upper()} risk: {', '.join(names)}"


class DataSanitizer:
    """Detect and redact sensitive data."""

    def __init__(self, *, custom_patterns: Optional[dict] = None):
        self._patterns = dict(PATTERNS)
        if custom_patterns:
            for name, (pattern, replacement) in custom_patterns.items():
                self._patterns[name] = (re.compile(pattern) if isinstance(pattern, str) else pattern, replacement)

    def sanitize(self, text: str, *, categories: Optional[list[str]] = None) -> SanitizeResult:
        """Sanitize text by redacting sensitive patterns."""
        if not text:
            return SanitizeResult(original=text, cleaned=text)

        cleaned = text
        findings = []
        redacted = 0

        active = categories or list(self._patterns.keys())

        for category in active:
            if category not in self._patterns:
                continue

            pattern, replacement = self._patterns[category]
            matches = pattern.findall(cleaned)

            if matches:
                for match in matches:
                    findings.append({
                        "category": category,
                        "matched": match[:20] + "..." if len(match) > 20 else match,
                    })
                    redacted += 1

                cleaned = pattern.sub(replacement, cleaned)

        return SanitizeResult(
            original=text,
            cleaned=cleaned,
            findings=findings,
            redacted_count=redacted,
        )

    def detect_only(self, text: str) -> list[dict]:
        """Detect sensitive data without redacting."""
        result = self.sanitize(text)
        return result.findings

    def add_pattern(self, name: str, pattern: str, replacement: str) -> None:
        """Add a custom pattern (takes precedence over built-in patterns)."""
        # Insert at the beginning so custom patterns are evaluated first
        new_patterns = {name: (re.compile(pattern), replacement)}
        new_patterns.update(self._patterns)
        self._patterns = new_patterns

    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern."""
        if name in self._patterns:
            del self._patterns[name]
            return True
        return False

    def list_patterns(self) -> list[str]:
        """List active pattern names."""
        return list(self._patterns.keys())

    # ── Prompt injection scanner ─────────────────────────────────────

    @staticmethod
    def scan_for_injection(text: str) -> InjectionScanResult:
        """Scan text for prompt injection / command injection patterns.

        Use this on ALL untrusted input (emails, user messages, external API data)
        before processing.
        """
        if not text:
            return InjectionScanResult(is_suspicious=False)

        threats: list[dict] = []
        for name, pattern in INJECTION_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                threats.append({
                    "pattern": name,
                    "matches": [m[:50] if isinstance(m, str) else str(m)[:50] for m in matches[:3]],
                })

        if not threats:
            return InjectionScanResult(is_suspicious=False, risk_level="none")

        # Risk scoring
        high_risk = {"command_injection", "data_exfil", "base64_payload"}
        medium_risk = {"ignore_instructions", "role_hijack", "hidden_instruction"}

        threat_names = {t["pattern"] for t in threats}
        if threat_names & high_risk:
            level = "high"
        elif threat_names & medium_risk:
            level = "medium"
        else:
            level = "low"

        return InjectionScanResult(
            is_suspicious=True,
            threats=threats,
            risk_level=level,
        )

    def sanitize_email(self, text: str) -> SanitizeResult:
        """Sanitize email content: strip HTML tags, scan for injection, redact PII."""
        import html as _html

        # Strip HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        clean = _html.unescape(clean)

        # Run injection scan
        injection = self.scan_for_injection(clean)
        if injection.is_suspicious:
            # Add injection findings to sanitize result
            pass  # Logged but not redacted — caller decides action

        # Run normal PII sanitization
        result = self.sanitize(clean)

        # Attach injection info
        if injection.is_suspicious:
            result.findings.append({
                "category": "prompt_injection",
                "risk_level": injection.risk_level,
                "threats": [t["pattern"] for t in injection.threats],
            })

        return result
