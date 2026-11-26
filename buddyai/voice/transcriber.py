"""VoiceTranscriber: streams live microphone PCM to Gemini Live Transcribe for real-time text."""

import asyncio
import logging
import sys

from buddyai.exceptions import BuddyError, ModelRequestError

logger = logging.getLogger(__name__)


# Encapsulation & Dependency Injection: streams via AudioDevice and transcribes via Gemini Live.
class VoiceTranscriber:
    """Streams microphone speech for real-time transcription into the regular chat prompt.

    It always uses LIVE_MODEL, a transcription-only Live model; /model does not change it.
    """

    LIVE_MODEL = "gemini-3.5-transcribe-live"
    INPUT_MIME_TYPE = "audio/pcm;rate=16000"
    FLUSH_TIMEOUT_SECONDS = 0.8

    def __init__(self, live_client=None):
        self._live_client = live_client

    def _get_live_client(self):
        if self._live_client is not None:
            return self._live_client
        from google import genai

        self._live_client = genai.Client(http_options={"api_version": "v1alpha"})
        return self._live_client

    @staticmethod
    async def _wait_for_finish(wait_for_stop):
        """Wait for Enter (finish) or Esc/Ctrl+C (cancel) without clobbering live UI."""
        if wait_for_stop is not None:
            await asyncio.to_thread(wait_for_stop)
            return False

        if sys.stdin.isatty():
            try:
                import msvcrt
            except ImportError:
                msvcrt = None
            if msvcrt is not None:
                while True:
                    while msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ("\x03", "\x1b"):
                            return True
                        if ch in ("\r", "\n"):
                            return False
                    await asyncio.sleep(0.04)

        await asyncio.to_thread(input)
        return False

    async def stream_and_transcribe_async(
        self, audio_device, on_update=None, wait_for_stop=None
    ):
        """Stream 16 kHz PCM live to gemini-3.5-transcribe-live, calling on_update(text) as words form."""
        from google.genai import types

        live_client = self._get_live_client()
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT],
            input_audio_transcription=types.AudioTranscriptionConfig(mode="SMART"),
        )

        final_parts = []
        interim = ""
        last_emitted = ""
        stop_sending = asyncio.Event()
        flushed = asyncio.Event()

        def _combine():
            parts = list(final_parts)
            if interim:
                parts.append(interim)
            return " ".join(p for p in parts if p).strip()

        def _notify():
            nonlocal last_emitted
            combined = _combine()
            if on_update is not None and combined != last_emitted:
                last_emitted = combined
                on_update(combined)

        audio_device.open()
        try:
            try:
                async with live_client.aio.live.connect(
                    model=self.LIVE_MODEL, config=config
                ) as session:
                    async def _mic_loop():
                        while not stop_sending.is_set():
                            chunk = await asyncio.to_thread(audio_device.read_chunk)
                            if stop_sending.is_set():
                                break
                            if chunk:
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=chunk, mime_type=self.INPUT_MIME_TYPE
                                    )
                                )

                    async def _recv_loop():
                        nonlocal interim
                        async for msg in session.receive():
                            sc = getattr(msg, "server_content", None)
                            if sc is None:
                                continue
                            final_tr = getattr(sc, "input_transcription", None)
                            if final_tr and final_tr.text:
                                piece = final_tr.text.strip()
                                if piece:
                                    final_parts.append(piece)
                                interim = ""
                                _notify()
                                if stop_sending.is_set():
                                    flushed.set()
                                    return
                            interim_tr = getattr(
                                sc, "interim_input_transcription", None
                            )
                            if interim_tr and interim_tr.text:
                                interim = interim_tr.text.strip()
                                _notify()

                    mic_task = asyncio.create_task(_mic_loop())
                    recv_task = asyncio.create_task(_recv_loop())
                    wait_task = asyncio.create_task(
                        self._wait_for_finish(wait_for_stop)
                    )
                    try:
                        done, _ = await asyncio.wait(
                            [wait_task, mic_task, recv_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in done:
                            if task is wait_task or task.cancelled():
                                continue
                            exc = task.exception()
                            if exc is not None:
                                raise exc

                        cancelled = (
                            wait_task.result() if wait_task.done() and not wait_task.cancelled() else False
                        )
                        stop_sending.set()
                        if cancelled:
                            raise KeyboardInterrupt

                        if not recv_task.done():
                            try:
                                await session.send_realtime_input(audio_stream_end=True)
                                await asyncio.wait_for(
                                    flushed.wait(),
                                    timeout=self.FLUSH_TIMEOUT_SECONDS,
                                )
                            except (asyncio.TimeoutError, Exception):
                                pass
                    finally:
                        stop_sending.set()
                        for task in (mic_task, recv_task, wait_task):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(
                            mic_task, recv_task, wait_task, return_exceptions=True
                        )
            except (KeyboardInterrupt, asyncio.CancelledError, BuddyError):
                raise
            except Exception as exc:
                logger.exception("Live voice transcription failed.")
                raise ModelRequestError(
                    f"Could not transcribe speech: {exc}"
                ) from exc
        finally:
            audio_device.close()

        return _combine()
