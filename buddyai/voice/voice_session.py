"""VoiceSession bridging an AudioDevice with ADK Runner.run_live."""

import asyncio
import logging
import re
import sys
import time

from buddyai.exceptions import BuddyError, ModelRequestError

logger = logging.getLogger(__name__)


# Encapsulation: owns the live queue and the send and receive loops so the rest of the app only starts and stops it.
class VoiceSession:
    """Manages one bidirectional voice session over ADK live streaming."""

    INPUT_MIME_TYPE = "audio/pcm;rate=16000"
    STOP_PHRASES = (
        "stop",
        "stop voice",
        "stop voice mode",
        "stop live",
        "exit voice mode",
        "exit live mode",
    )
    CLOSE_TIMEOUT_SECONDS = 3.0
    # Brief quiet tail after speaker playback finishes so laptop speaker echo
    # dies out before mic audio resumes in speaker-safe mode.
    ECHO_TAIL_SECONDS = 0.35

    def __init__(
        self,
        agent,
        audio_device,
        on_text=None,
        echo_guard=True,
        app_name="buddyai_voice",
        user_id="local_user",
        session_id="voice_session",
    ):
        self._agent = agent
        self._audio_device = audio_device
        self._on_text = on_text
        self._echo_guard = bool(echo_guard)
        self._app_name = app_name
        self._user_id = user_id
        self._session_id = session_id
        self._stop_event = None
        self._stop_requested = False
        self._playback_queue = None
        self._playback_gen = 0
        self._is_playing = False
        self._echo_tail_until = 0.0

    @property
    def agent(self):
        return self._agent

    @property
    def audio_device(self):
        return self._audio_device

    @property
    def echo_guard(self):
        return self._echo_guard

    def stop(self):
        """Request that a running session end cleanly."""
        self._stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()

    def interrupt_playback(self):
        """Stop queued and in-flight speaker playback and immediately unmute the mic."""
        self._playback_gen += 1
        if self._playback_queue is not None:
            self._drain_queue(self._playback_queue)
        self._audio_device.clear_playback()
        self._is_playing = False
        self._echo_tail_until = 0.0

    @staticmethod
    def _normalize_spoken(text):
        cleaned = re.sub(r"[^\w\s]", "", (text or "").lower())
        return " ".join(cleaned.split())

    def _emit_text(self, speaker, text):
        cleaned = (text or "").strip()
        if cleaned and self._on_text is not None:
            self._on_text(speaker, cleaned)

    @staticmethod
    def _drain_queue(playback_queue):
        while not playback_queue.empty():
            try:
                playback_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _mic_is_gated(self):
        """Return True while speaker-safe echo guard should mute mic upload."""
        if not self._echo_guard:
            return False
        if self._is_playing:
            return True
        if self._playback_queue is not None and not self._playback_queue.empty():
            return True
        return time.monotonic() < self._echo_tail_until

    async def _mic_loop(self, live_queue):
        from google.genai import types

        while not self._stop_event.is_set():
            chunk = await asyncio.to_thread(self._audio_device.read_chunk)
            if self._stop_event.is_set():
                break
            if not chunk or self._mic_is_gated():
                continue
            live_queue.send_realtime(
                types.Blob(data=chunk, mime_type=self.INPUT_MIME_TYPE)
            )

    async def _play_loop(self):
        while not self._stop_event.is_set():
            gen, chunk = await self._playback_queue.get()
            if self._stop_event.is_set():
                break
            if gen != self._playback_gen or not chunk:
                continue
            self._is_playing = True
            try:
                await asyncio.to_thread(self._audio_device.play, chunk)
            finally:
                if self._playback_queue.empty():
                    self._is_playing = False
                    if gen == self._playback_gen:
                        self._echo_tail_until = (
                            time.monotonic() + self.ECHO_TAIL_SECONDS
                        )

    async def _key_loop(self):
        """Allow Space or Enter in interactive Windows terminals to interrupt playback."""
        if not self._echo_guard or not sys.stdin.isatty():
            return
        try:
            import msvcrt
        except ImportError:
            return

        while not self._stop_event.is_set():
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == "\x03":
                    self.stop()
                    return
                if ch in (" ", "\r", "\n"):
                    if self._is_playing or (
                        self._playback_queue is not None
                        and not self._playback_queue.empty()
                    ):
                        self.interrupt_playback()
                        self._emit_text("System", "Interrupted. Go ahead and speak.")
            await asyncio.sleep(0.05)

    async def _receive_loop(self, runner, live_queue, run_config):
        in_buffer = []
        out_buffer = []

        async for event in runner.run_live(
            user_id=self._user_id,
            session_id=self._session_id,
            live_request_queue=live_queue,
            run_config=run_config,
        ):
            if event.error_message:
                self._emit_text("BuddyAI (error)", event.error_message)

            if event.interrupted:
                self.interrupt_playback()
                out_buffer.clear()

            if event.content and event.content.parts:
                for part in event.content.parts:
                    blob = part.inline_data
                    if (
                        blob is not None
                        and blob.data
                        and (blob.mime_type or "").lower().startswith("audio/pcm")
                    ):
                        await self._playback_queue.put(
                            (self._playback_gen, blob.data)
                        )

            in_tr = event.input_transcription
            if in_tr and in_tr.text:
                if in_tr.finished:
                    spoken = in_tr.text.strip()
                    in_buffer.clear()
                    self._emit_text("You", spoken)
                    if self._normalize_spoken(spoken) in self.STOP_PHRASES:
                        self.stop()
                        break
                else:
                    in_buffer.append(in_tr.text)

            out_tr = event.output_transcription
            if out_tr and out_tr.text:
                if out_tr.finished:
                    spoken = out_tr.text.strip()
                    out_buffer.clear()
                    self._emit_text("BuddyAI", spoken)
                else:
                    out_buffer.append(out_tr.text)

            if event.turn_complete:
                if in_buffer:
                    spoken_in = "".join(in_buffer).strip()
                    in_buffer.clear()
                    self._emit_text("You", spoken_in)
                    if self._normalize_spoken(spoken_in) in self.STOP_PHRASES:
                        self.stop()
                        break
                if out_buffer:
                    spoken_out = "".join(out_buffer).strip()
                    out_buffer.clear()
                    self._emit_text("BuddyAI", spoken_out)

            if self._stop_event.is_set():
                break

    async def run(self):
        """Run the voice session until stop() is called, cancelled, or an error occurs."""
        from google.adk.agents.run_config import RunConfig, StreamingMode
        from google.adk.live.live_request_queue import LiveRequestQueue
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        self._stop_event = asyncio.Event()
        if self._stop_requested:
            self._stop_event.set()
        self._playback_queue = asyncio.Queue()
        self._playback_gen = 0
        self._is_playing = False
        self._echo_tail_until = 0.0

        self._audio_device.open()
        live_queue = LiveRequestQueue()
        recv_task = None
        mic_task = None
        play_task = None
        key_task = None
        stop_task = None

        try:
            session_service = InMemorySessionService()
            await session_service.create_session(
                app_name=self._app_name,
                user_id=self._user_id,
                session_id=self._session_id,
            )
            runner = Runner(
                agent=self._agent,
                app_name=self._app_name,
                session_service=session_service,
            )
            run_config = RunConfig(
                streaming_mode=StreamingMode.BIDI,
                response_modalities=[types.Modality.AUDIO],
            )

            mic_task = asyncio.create_task(self._mic_loop(live_queue))
            play_task = asyncio.create_task(self._play_loop())
            recv_task = asyncio.create_task(
                self._receive_loop(runner, live_queue, run_config)
            )
            stop_task = asyncio.create_task(self._stop_event.wait())
            wait_tasks = [mic_task, play_task, recv_task, stop_task]
            if self._echo_guard and sys.stdin.isatty():
                key_task = asyncio.create_task(self._key_loop())
                wait_tasks.append(key_task)

            done, _ = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for finished in done:
                if finished in (stop_task, key_task) or finished.cancelled():
                    continue
                exc = finished.exception()
                if exc is not None:
                    if isinstance(exc, BuddyError):
                        raise exc
                    logger.exception("Voice session failed.")
                    raise ModelRequestError(
                        f"The voice connection failed: {exc}"
                    ) from exc
        finally:
            self._stop_event.set()
            self._is_playing = False
            live_queue.close()
            if recv_task is not None and not recv_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(recv_task),
                        timeout=self.CLOSE_TIMEOUT_SECONDS,
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass

            tasks = [
                task
                for task in (mic_task, play_task, recv_task, key_task, stop_task)
                if task is not None and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            self._audio_device.close()
