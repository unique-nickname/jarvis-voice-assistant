"""Tests for the synchronous TTS playback result used by voice control."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from voice import tts


class TextToSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = Mock()
        self.initialize = patch("voice.tts.initialize")
        self.initialize.start()
        self.addCleanup(self.initialize.stop)
        self.worker_patch = patch("voice.tts._worker", self.worker)
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    def test_speak_reports_completed_playback(self) -> None:
        with patch("voice.tts._read_response", return_value={"ok": True}):
            self.assertTrue(tts.speak("Hello."))

        self.worker.stdin.write.assert_called_once()
        self.worker.stdin.flush.assert_called_once()

    def test_speak_reports_worker_failure(self) -> None:
        with patch(
            "voice.tts._read_response",
            return_value={"ok": False, "error": "playback failed"},
        ):
            self.assertFalse(tts.speak("Hello."))

    def test_speak_reports_empty_text_as_not_played(self) -> None:
        self.assertFalse(tts.speak("   "))
        self.worker.stdin.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
