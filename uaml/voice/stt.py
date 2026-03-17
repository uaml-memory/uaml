# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML STT Engine — speech-to-text transcription.

Supports multiple backends with automatic fallback:
1. Whisper.cpp (recommended, local, MIT)
2. faster-whisper (alternative, local, MIT)
3. Vosk (lightweight alternative)

Usage:
    from uaml.voice.stt import STTEngine

    engine = STTEngine(backend="whisper")
    result = engine.transcribe("recording.wav")
    print(result.text)
    print(result.language)
"""

from __future__ import annotations

import json
import subprocess
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class STTResult:
    """Result of STT transcription."""
    text: str = ""
    language: str = ""
    confidence: float = 0.0
    duration_ms: int = 0
    backend: str = ""
    model: str = ""
    segments: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "backend": self.backend,
            "model": self.model,
        }


class STTEngine:
    """Multi-backend STT engine with automatic fallback."""

    BACKENDS = ["whisper", "vosk"]

    def __init__(
        self,
        backend: Optional[str] = None,
        model: str = "tiny",
        model_path: Optional[str | Path] = None,
    ):
        self.model = model
        self.model_path = Path(model_path) if model_path else None
        self._backend = backend or self._detect_backend()

    def _detect_backend(self) -> str:
        """Auto-detect available STT backend."""
        # Check for whisper.cpp
        if shutil.which("whisper-cpp") or shutil.which("main"):
            return "whisper"
        # Check for Python whisper
        try:
            import whisper  # noqa: F401
            return "whisper-python"
        except ImportError:
            pass
        # Check for faster-whisper
        try:
            import faster_whisper  # noqa: F401
            return "faster-whisper"
        except ImportError:
            pass
        # Check for vosk
        try:
            import vosk  # noqa: F401
            return "vosk"
        except ImportError:
            pass
        return "none"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def available(self) -> bool:
        return self._backend != "none"

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: Optional[str] = None,
    ) -> STTResult:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to audio file (WAV, MP3, OGG, etc.)
            language: Hint language code (auto-detect if None)

        Returns:
            STTResult with transcribed text
        """
        path = Path(audio_path)
        if not path.exists():
            return STTResult(backend=self._backend)

        if self._backend == "whisper":
            return self._transcribe_whisper_cpp(path, language)
        elif self._backend == "whisper-python":
            return self._transcribe_whisper_python(path, language)
        elif self._backend == "faster-whisper":
            return self._transcribe_faster_whisper(path, language)
        elif self._backend == "vosk":
            return self._transcribe_vosk(path, language)

        return STTResult(backend="none")

    def _transcribe_whisper_cpp(self, path: Path, language: Optional[str]) -> STTResult:
        """Transcribe using whisper.cpp CLI."""
        whisper_bin = shutil.which("whisper-cpp") or shutil.which("main")
        if not whisper_bin:
            return STTResult(backend="whisper")

        cmd = [whisper_bin, "-f", str(path), "--output-json"]
        if language:
            cmd.extend(["-l", language])
        if self.model_path:
            cmd.extend(["-m", str(self.model_path)])

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                try:
                    data = json.loads(proc.stdout)
                    text = " ".join(s.get("text", "") for s in data.get("transcription", []))
                    return STTResult(
                        text=text.strip(),
                        language=language or "auto",
                        backend="whisper",
                        model=self.model,
                    )
                except json.JSONDecodeError:
                    # Plain text output
                    return STTResult(
                        text=proc.stdout.strip(),
                        language=language or "auto",
                        backend="whisper",
                        model=self.model,
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return STTResult(backend="whisper")

    def _transcribe_whisper_python(self, path: Path, language: Optional[str]) -> STTResult:
        """Transcribe using OpenAI Whisper Python library."""
        try:
            import whisper
            model = whisper.load_model(self.model)
            result = model.transcribe(str(path), language=language)
            return STTResult(
                text=result.get("text", "").strip(),
                language=result.get("language", language or "auto"),
                backend="whisper-python",
                model=self.model,
                segments=[
                    {"start": s["start"], "end": s["end"], "text": s["text"]}
                    for s in result.get("segments", [])
                ],
            )
        except Exception:
            return STTResult(backend="whisper-python")

    def _transcribe_faster_whisper(self, path: Path, language: Optional[str]) -> STTResult:
        """Transcribe using faster-whisper."""
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(self.model)
            segments, info = model.transcribe(str(path), language=language)
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)
            return STTResult(
                text=" ".join(text_parts).strip(),
                language=info.language if hasattr(info, "language") else (language or "auto"),
                backend="faster-whisper",
                model=self.model,
            )
        except Exception:
            return STTResult(backend="faster-whisper")

    def _transcribe_vosk(self, path: Path, language: Optional[str]) -> STTResult:
        """Transcribe using Vosk."""
        try:
            import vosk
            import wave

            model = vosk.Model(str(self.model_path)) if self.model_path else vosk.Model(lang=language or "en")
            with wave.open(str(path), "rb") as wf:
                rec = vosk.KaldiRecognizer(model, wf.getframerate())
                text_parts = []
                while True:
                    data = wf.readframes(4000)
                    if len(data) == 0:
                        break
                    if rec.AcceptWaveform(data):
                        result = json.loads(rec.Result())
                        text_parts.append(result.get("text", ""))
                final = json.loads(rec.FinalResult())
                text_parts.append(final.get("text", ""))

            return STTResult(
                text=" ".join(text_parts).strip(),
                language=language or "auto",
                backend="vosk",
                model="vosk",
            )
        except Exception:
            return STTResult(backend="vosk")

    def status(self) -> dict:
        """Get engine status."""
        return {
            "backend": self._backend,
            "available": self.available,
            "model": self.model,
            "model_path": str(self.model_path) if self.model_path else None,
        }
