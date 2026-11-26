"""Audio device abstraction and sounddevice implementation for BuddyAI voice mode."""

from abc import ABC, abstractmethod
import logging
import threading

from buddyai.exceptions import VoiceUnavailableError

logger = logging.getLogger(__name__)


# Abstraction: the session talks to any audio device, so tests use a fake and the real one is replaceable.
class AudioDevice(ABC):
    """Abstract microphone and speaker interface using 16-bit mono PCM bytes."""

    INPUT_RATE = 16000
    OUTPUT_RATE = 24000
    CHUNK_MILLISECONDS = 100

    @abstractmethod
    def open(self):
        """Start the microphone and speaker streams, or raise VoiceUnavailableError."""

    @abstractmethod
    def close(self):
        """Stop and release audio streams cleanly."""

    @abstractmethod
    def read_chunk(self):
        """Block for roughly one chunk and return 16 kHz 16-bit mono PCM bytes."""

    @abstractmethod
    def play(self, chunk):
        """Hand a 24 kHz 16-bit mono PCM chunk to the speaker."""

    @abstractmethod
    def clear_playback(self):
        """Drop any queued speaker audio immediately (used when interrupted)."""


# Inheritance & Encapsulation: wraps sounddevice RawInputStream and RawOutputStream behind AudioDevice.
class SoundDeviceAudio(AudioDevice):
    """Concrete AudioDevice backed by sounddevice and PortAudio."""

    # Write output audio in 40 ms slices (960 frames * 2 bytes at 24 kHz) so
    # clear_playback() stops speaker output quickly without calling PortAudio
    # abort() concurrently with write() on Windows.
    PLAYBACK_SLICE_BYTES = 1920

    def __init__(self):
        self._sd = None
        self._input = None
        self._output = None
        self._frames_per_chunk = self.INPUT_RATE * self.CHUNK_MILLISECONDS // 1000
        self._output_lock = threading.Lock()
        self._playback_token = 0

    def open(self):
        """Import sounddevice lazily and open 16 kHz input and 24 kHz output streams."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceUnavailableError(
                "Voice mode needs the sounddevice package. Install it with: "
                r".\.venv\Scripts\python.exe -m pip install sounddevice, "
                "then start BuddyAI again."
            ) from exc

        self._sd = sd
        try:
            self._input = sd.RawInputStream(
                samplerate=self.INPUT_RATE,
                channels=1,
                dtype="int16",
                blocksize=self._frames_per_chunk,
            )
            self._output = sd.RawOutputStream(
                samplerate=self.OUTPUT_RATE,
                channels=1,
                dtype="int16",
            )
            self._input.start()
            self._output.start()
        except (OSError, ValueError, sd.PortAudioError) as exc:
            self.close()
            raise VoiceUnavailableError(
                f"No working microphone or speaker could be opened: {exc}"
            ) from exc

    def _reopen_output(self):
        """Recreate the output stream cleanly if PortAudio stopped unexpectedly."""
        if self._sd is None:
            return False
        port_error = getattr(self._sd, "PortAudioError", OSError)
        old = self._output
        if old is not None:
            try:
                old.close()
            except (OSError, port_error):
                pass
        try:
            self._output = self._sd.RawOutputStream(
                samplerate=self.OUTPUT_RATE,
                channels=1,
                dtype="int16",
            )
            self._output.start()
            return True
        except (OSError, ValueError, port_error) as exc:
            logger.warning("Could not reopen speaker output stream: %s", exc)
            self._output = None
            return False

    def read_chunk(self):
        """Read one 100 ms PCM chunk from the microphone."""
        if self._input is None:
            return b""
        port_error = getattr(self._sd, "PortAudioError", OSError)
        try:
            buf, _ = self._input.read(self._frames_per_chunk)
            return bytes(buf)
        except (OSError, port_error):
            return b""

    def play(self, chunk):
        """Write one 24 kHz PCM chunk to the speaker in small interruptible slices."""
        if self._output is None or not chunk:
            return
        port_error = getattr(self._sd, "PortAudioError", OSError)
        token = self._playback_token
        step = self.PLAYBACK_SLICE_BYTES

        for offset in range(0, len(chunk), step):
            if self._playback_token != token:
                return
            piece = chunk[offset : offset + step]
            with self._output_lock:
                if self._output is None or self._playback_token != token:
                    return
                try:
                    if not getattr(self._output, "active", True):
                        self._output.start()
                    self._output.write(piece)
                except (OSError, port_error) as exc:
                    logger.warning("Speaker write failed; attempting recovery: %s", exc)
                    if not self._reopen_output() or self._playback_token != token:
                        return
                    try:
                        self._output.write(piece)
                    except (OSError, port_error):
                        return

    def clear_playback(self):
        """Interrupt any in-progress play() call safely without aborting PortAudio mid-write."""
        self._playback_token += 1

    def close(self):
        """Stop and close both audio streams safely."""
        self._playback_token += 1
        port_error = getattr(self._sd, "PortAudioError", OSError)
        if self._input is not None:
            try:
                self._input.abort()
            except (OSError, port_error):
                pass
            try:
                self._input.close()
            except (OSError, port_error):
                pass
            self._input = None

        with self._output_lock:
            if self._output is not None:
                try:
                    self._output.stop()
                except (OSError, port_error):
                    pass
                try:
                    self._output.close()
                except (OSError, port_error):
                    pass
                self._output = None
