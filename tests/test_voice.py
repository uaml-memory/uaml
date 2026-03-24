"""Tests for UAML Voice module (TTS + STT)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uaml.voice.tts import TTSEngine, TTSResult
from uaml.voice.stt import STTEngine, STTResult


class TestTTSResult:
    def test_empty_result(self):
        r = TTSResult()
        assert r.audio_data == b""
        assert r.size_kb == 0

    def test_save(self, tmp_path):
        r = TTSResult(audio_data=b"fake audio data")
        out = tmp_path / "test.wav"
        r.save(out)
        assert out.read_bytes() == b"fake audio data"


class TestTTSEngine:
    def test_init(self):
        engine = TTSEngine(backend="none")
        assert engine.backend == "none"
        assert not engine.available

    def test_status(self):
        engine = TTSEngine(backend="none")
        status = engine.status()
        assert status["backend"] == "none"
        assert status["available"] is False

    def test_synthesize_no_backend(self):
        engine = TTSEngine(backend="none")
        result = engine.synthesize("Hello world")
        assert result.audio_data == b""

    def test_detect_backend(self):
        engine = TTSEngine()
        # Should detect something or "none"
        assert engine.backend in TTSEngine.BACKENDS + ["none"]

    def test_list_voices_none(self):
        engine = TTSEngine(backend="none")
        voices = engine.list_voices()
        assert voices == []


class TestSTTResult:
    def test_empty_result(self):
        r = STTResult()
        assert r.text == ""
        assert r.success is False

    def test_successful_result(self):
        r = STTResult(text="Hello world", language="en", confidence=0.95)
        assert r.success is True

    def test_to_dict(self):
        r = STTResult(text="Test", language="cs", backend="whisper")
        d = r.to_dict()
        assert d["text"] == "Test"
        assert d["language"] == "cs"


class TestSTTEngine:
    def test_init(self):
        engine = STTEngine(backend="none")
        assert engine.backend == "none"
        assert not engine.available

    def test_status(self):
        engine = STTEngine(backend="none")
        status = engine.status()
        assert status["backend"] == "none"
        assert status["available"] is False

    def test_transcribe_missing_file(self):
        engine = STTEngine(backend="whisper")
        result = engine.transcribe("/nonexistent/audio.wav")
        assert result.text == ""

    def test_transcribe_no_backend(self):
        engine = STTEngine(backend="none")
        result = engine.transcribe("/tmp/test.wav")
        assert result.text == ""

    def test_detect_backend(self):
        engine = STTEngine()
        assert engine.backend in STTEngine.BACKENDS + [
            "whisper-python", "faster-whisper", "none"
        ]
