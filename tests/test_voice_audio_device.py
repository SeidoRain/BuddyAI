"""Offline unit tests for AudioDevice and SoundDeviceAudio error handling."""

import sys
import types
import unittest
from unittest import mock

from buddyai.exceptions import BuddyError, VoiceUnavailableError
from buddyai.voice import AudioDevice, SoundDeviceAudio


class TestSoundDeviceAudio(unittest.TestCase):
    """Checks lazy sounddevice import and VoiceUnavailableError handling."""

    def test_voice_unavailable_error_is_a_buddy_error(self):
        self.assertTrue(issubclass(VoiceUnavailableError, BuddyError))

    def test_open_raises_voice_unavailable_error_when_sounddevice_is_missing(self):
        audio = SoundDeviceAudio()
        with mock.patch.dict(sys.modules, {"sounddevice": None}):
            with self.assertRaises(VoiceUnavailableError) as ctx:
                audio.open()
        self.assertIn("pip install sounddevice", str(ctx.exception))

    def test_open_raises_voice_unavailable_error_when_hardware_fails(self):
        fake_sd = types.SimpleNamespace(
            PortAudioError=RuntimeError,
            RawInputStream=mock.Mock(side_effect=OSError("no default input device")),
            RawOutputStream=mock.Mock(),
        )
        audio = SoundDeviceAudio()
        with mock.patch.dict(sys.modules, {"sounddevice": fake_sd}):
            with self.assertRaises(VoiceUnavailableError) as ctx:
                audio.open()
        self.assertIn("no default input device", str(ctx.exception))

    def test_audio_device_constants_match_gemini_live_pcm_rates(self):
        self.assertEqual(AudioDevice.INPUT_RATE, 16000)
        self.assertEqual(AudioDevice.OUTPUT_RATE, 24000)
        self.assertEqual(AudioDevice.CHUNK_MILLISECONDS, 100)

    def test_clear_playback_stops_mid_chunk_without_aborting_and_allows_next_chunk(self):
        written = []
        abort_calls = []
        audio = SoundDeviceAudio()

        class _FakeOutputStream:
            active = True

            def start(self):
                self.active = True

            def abort(self):
                abort_calls.append(True)

            def stop(self):
                pass

            def close(self):
                pass

            def write(self, data):
                written.append(data)
                if len(written) == 1:
                    audio.clear_playback()

        audio._output = _FakeOutputStream()
        big_chunk = b"\x01\x00" * (SoundDeviceAudio.PLAYBACK_SLICE_BYTES * 2)
        audio.play(big_chunk)
        self.assertEqual(len(written), 1)
        self.assertEqual(abort_calls, [])

        next_chunk = b"\x02\x00" * 500
        audio.play(next_chunk)
        self.assertEqual(len(written), 2)
        self.assertEqual(written[1], next_chunk)


if __name__ == "__main__":
    unittest.main()
