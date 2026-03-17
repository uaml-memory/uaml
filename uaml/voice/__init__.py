# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Voice — TTS and STT integration for agent communication.

Provides text-to-speech and speech-to-text capabilities with
local-first, offline-capable processing.

Usage:
    from uaml.voice import TTSEngine, STTEngine

    tts = TTSEngine()
    audio = tts.synthesize("Hello, world!", language="en")

    stt = STTEngine()
    text = stt.transcribe("recording.wav")
"""

from uaml.voice.tts import TTSEngine, TTSResult
from uaml.voice.stt import STTEngine, STTResult

__all__ = ["TTSEngine", "TTSResult", "STTEngine", "STTResult"]
