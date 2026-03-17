# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML TTS Engine — text-to-speech synthesis.

Supports multiple backends with automatic fallback:
1. Piper TTS (recommended, local, MIT)
2. eSpeak-NG (fallback, local, lightweight)
3. Cloud API (optional fallback)

Usage:
    from uaml.voice.tts import TTSEngine

    engine = TTSEngine(backend="piper")
    result = engine.synthesize("Ahoj, jak se máš?", language="cs")
    result.save("output.wav")
"""

from __future__ import annotations

import subprocess
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TTSResult:
    """Result of TTS synthesis."""
    audio_data: bytes = b""
    format: str = "wav"
    sample_rate: int = 22050
    duration_ms: int = 0
    backend: str = ""
    language: str = ""
    model: str = ""

    def save(self, path: str | Path) -> None:
        """Save audio to file."""
        Path(path).write_bytes(self.audio_data)

    @property
    def size_kb(self) -> float:
        return len(self.audio_data) / 1024


class TTSEngine:
    """Multi-backend TTS engine with automatic fallback."""

    BACKENDS = ["piper", "espeak", "cli"]

    def __init__(
        self,
        backend: Optional[str] = None,
        model_path: Optional[str | Path] = None,
        voice: Optional[str] = None,
    ):
        self.model_path = Path(model_path) if model_path else None
        self.voice = voice
        self._backend = backend or self._detect_backend()

    def _detect_backend(self) -> str:
        """Auto-detect available TTS backend."""
        if shutil.which("piper"):
            return "piper"
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        return "none"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def available(self) -> bool:
        return self._backend != "none"

    def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        voice: Optional[str] = None,
        output_path: Optional[str | Path] = None,
    ) -> TTSResult:
        """Synthesize text to speech.

        Args:
            text: Text to speak
            language: Language code (en, cs, de, etc.)
            voice: Voice name/path override
            output_path: Optional path to save audio directly

        Returns:
            TTSResult with audio data
        """
        if self._backend == "piper":
            result = self._synth_piper(text, language, voice)
        elif self._backend == "espeak":
            result = self._synth_espeak(text, language, voice)
        else:
            result = TTSResult(backend="none")

        if output_path and result.audio_data:
            result.save(output_path)

        return result

    def _synth_piper(self, text: str, language: str, voice: Optional[str]) -> TTSResult:
        """Synthesize using Piper TTS."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = ["piper", "--output_file", tmp_path]
            if self.model_path:
                cmd.extend(["--model", str(self.model_path)])
            elif voice:
                cmd.extend(["--model", voice])

            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )

            if proc.returncode == 0 and Path(tmp_path).exists():
                audio_data = Path(tmp_path).read_bytes()
                return TTSResult(
                    audio_data=audio_data,
                    backend="piper",
                    language=language,
                    model=str(self.model_path or voice or "default"),
                )
            return TTSResult(backend="piper")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return TTSResult(backend="piper")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _synth_espeak(self, text: str, language: str, voice: Optional[str]) -> TTSResult:
        """Synthesize using eSpeak-NG."""
        espeak = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [espeak, "-v", voice or language, "-w", tmp_path, text]

            proc = subprocess.run(cmd, capture_output=True, timeout=10)

            if proc.returncode == 0 and Path(tmp_path).exists():
                audio_data = Path(tmp_path).read_bytes()
                return TTSResult(
                    audio_data=audio_data,
                    backend="espeak",
                    language=language,
                    model=voice or language,
                )
            return TTSResult(backend="espeak")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return TTSResult(backend="espeak")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def list_voices(self) -> list[dict]:
        """List available voices for the current backend."""
        if self._backend == "piper" and self.model_path:
            return [{"name": self.model_path.stem, "path": str(self.model_path)}]
        if self._backend == "espeak":
            try:
                espeak = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak"
                proc = subprocess.run(
                    [espeak, "--voices"], capture_output=True, text=True, timeout=5,
                )
                voices = []
                for line in proc.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        voices.append({"language": parts[1], "name": parts[3]})
                return voices[:20]  # Limit output
            except Exception:
                pass
        return []

    def status(self) -> dict:
        """Get engine status."""
        return {
            "backend": self._backend,
            "available": self.available,
            "model_path": str(self.model_path) if self.model_path else None,
            "voice": self.voice,
        }
