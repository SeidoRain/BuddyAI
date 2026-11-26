"""Offline unit tests for VoiceSession, VoiceCoordinatorProfile, BuddyApp voice hooks, and /voice."""

import asyncio
import contextlib
from datetime import datetime
from io import StringIO
import logging
import os
import tempfile
import time
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from rich.console import Console

from buddyai.agents import (
    BriefingAgentProfile,
    NotesAgentProfile,
    ScheduleAgentProfile,
    TaskAgentProfile,
    VoiceCoordinatorProfile,
)
from buddyai.app import BuddyApp
from buddyai.cli import CommandRouter, RICH_THEME, TerminalUI
from buddyai.config import DEFAULT_VOICE_MODEL
from buddyai.exceptions import ModelRequestError, VoiceUnavailableError
from buddyai.voice import AudioDevice, VoiceSession, VoiceTranscriber

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)


class FakeAudioDevice(AudioDevice):
    """In-memory AudioDevice for offline VoiceSession tests."""

    def __init__(self, play_delay=0.0):
        self.opened = False
        self.closed = False
        self.played = []
        self.clear_count = 0
        self._play_delay = play_delay

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def read_chunk(self):
        time.sleep(0.01)
        return b"\x01\x00" * 1600

    def play(self, chunk):
        if self._play_delay:
            time.sleep(self._play_delay)
        self.played.append(chunk)

    def clear_playback(self):
        self.clear_count += 1


class _FakeConnection(BaseLlmConnection):
    """Scripted BaseLlmConnection for offline VoiceSession tests."""

    def __init__(
        self,
        responses=None,
        trigger_on_audio=None,
        on_tool_response=None,
        fail_with=None,
    ):
        self.queue = asyncio.Queue()
        self.sent_audio = []
        self.closed = False
        self._trigger_on_audio = trigger_on_audio
        self._on_tool_response = on_tool_response
        self._fail_with = fail_with
        self._fired = False
        for resp in responses or []:
            self.queue.put_nowait(resp)

    async def send_history(self, history):
        pass

    async def send_context_update(self, *, system_instruction=None, tools=None):
        pass

    async def send_realtime(self, blob):
        self.sent_audio.append(blob)
        if not self._fired and self._trigger_on_audio is not None:
            self._fired = True
            for resp in self._trigger_on_audio():
                await self.queue.put(resp)

    async def send_content(self, content):
        if self._on_tool_response is not None and any(
            part.function_response for part in (content.parts or [])
        ):
            for resp in self._on_tool_response(content):
                await self.queue.put(resp)

    async def receive(self):
        if self._fail_with is not None:
            raise self._fail_with
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.closed = True
        await self.queue.put(None)


class _FakeLiveModel(BaseLlm):
    """Stand-in BaseLlm yielding a scripted BaseLlmConnection."""

    connection: object = None

    @contextlib.asynccontextmanager
    async def connect(self, llm_request):
        yield self.connection

    async def generate_content_async(self, llm_request, stream=False):
        raise RuntimeError("Live model is not used for plain requests.")
        yield


class _AddTaskTextLlm(BaseLlm):
    """Stand-in text model for specialists: calls add_task once, then confirms."""

    called_add_task: bool = False

    async def generate_content_async(self, llm_request, stream=False):
        has_tool_response = False
        for content in llm_request.contents or []:
            for part in content.parts or []:
                if part.function_response is not None:
                    has_tool_response = True
        if not has_tool_response and not self.called_add_task:
            self.called_add_task = True
            call = types.FunctionCall(
                name="add_task",
                id="tcall1",
                args={"title": "Buy milk", "due": "2026-11-27"},
            )
            yield LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(function_call=call)]
                )
            )
            return
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="Added task Buy milk.")],
            )
        )


class _QuietTextLlm(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="ok")])
        )


class TestVoiceSession(unittest.TestCase):
    """Tests VoiceSession audio loops, interruption, transcripts, stop, errors, and delegation."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(
            data_dir=self._tmp.name,
            model=_QuietTextLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            ics_file="",
        )

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def _build_coordinator(self, connection, specialist_llm=None):
        text_llm = specialist_llm or _QuietTextLlm(model="gemini-3.5-flash-lite")
        specialists = [
            TaskAgentProfile(model=text_llm, toolkit=self.app.toolkit),
            ScheduleAgentProfile(model=text_llm, toolkit=self.app.toolkit),
            NotesAgentProfile(model=text_llm, toolkit=self.app.toolkit),
            BriefingAgentProfile(model=text_llm, toolkit=self.app.toolkit),
        ]
        live_llm = _FakeLiveModel(model=DEFAULT_VOICE_MODEL, connection=connection)
        return VoiceCoordinatorProfile(
            model=live_llm,
            toolkit=self.app.toolkit,
            specialists=specialists,
        ).build()

    def test_microphone_audio_reaches_connection_with_16khz_pcm_mime_type(self):
        audio_seen = asyncio.Event()
        conn = _FakeConnection()
        orig_send = conn.send_realtime

        async def _capture(blob):
            await orig_send(blob)
            audio_seen.set()

        conn.send_realtime = _capture
        device = FakeAudioDevice()
        session = VoiceSession(self._build_coordinator(conn), device)

        async def _run():
            task = asyncio.create_task(session.run())
            await audio_seen.wait()
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertGreaterEqual(len(conn.sent_audio), 1)
        self.assertEqual(conn.sent_audio[0].mime_type, "audio/pcm;rate=16000")
        self.assertEqual(len(conn.sent_audio[0].data), 3200)

    def test_audio_part_from_model_is_played_on_audio_device(self):
        pcm_reply = b"\x02\x00" * 400
        conn = _FakeConnection(
            trigger_on_audio=lambda: [
                LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=pcm_reply, mime_type="audio/pcm;rate=24000"
                                )
                            )
                        ],
                    )
                ),
                LlmResponse(turn_complete=True),
            ]
        )
        device = FakeAudioDevice()
        session = VoiceSession(self._build_coordinator(conn), device)

        async def _run():
            task = asyncio.create_task(session.run())
            while not device.played:
                await asyncio.sleep(0.02)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertIn(pcm_reply, device.played)

    def test_audio_still_plays_on_next_turn_after_interruption(self):
        first_pcm = b"\x03\x00" * 200
        second_pcm = b"\x05\x00" * 200
        conn = _FakeConnection(
            trigger_on_audio=lambda: [
                LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=first_pcm, mime_type="audio/pcm;rate=24000"
                                )
                            )
                        ],
                    )
                ),
                LlmResponse(interrupted=True),
                LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=second_pcm, mime_type="audio/pcm;rate=24000"
                                )
                            )
                        ],
                    )
                ),
                LlmResponse(turn_complete=True),
            ]
        )
        device = FakeAudioDevice(play_delay=0.02)
        session = VoiceSession(self._build_coordinator(conn), device)

        async def _run():
            task = asyncio.create_task(session.run())
            while second_pcm not in device.played:
                await asyncio.sleep(0.02)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertGreaterEqual(device.clear_count, 1)
        self.assertIn(second_pcm, device.played)

    def test_echo_guard_mutes_mic_while_speaking_and_interrupt_unmutes(self):
        conn = _FakeConnection()
        device = FakeAudioDevice()
        session = VoiceSession(self._build_coordinator(conn), device, echo_guard=True)
        session._is_playing = True
        self.assertTrue(session._mic_is_gated())

        session.interrupt_playback()
        self.assertFalse(session._mic_is_gated())
        self.assertEqual(device.clear_count, 1)

        barge_session = VoiceSession(
            self._build_coordinator(conn), device, echo_guard=False
        )
        barge_session._is_playing = True
        self.assertFalse(barge_session._mic_is_gated())

    def test_interrupted_event_clears_playback_queue_and_calls_clear_playback(self):
        conn = _FakeConnection(
            trigger_on_audio=lambda: [
                LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=b"\x03\x00" * 200,
                                    mime_type="audio/pcm;rate=24000",
                                )
                            )
                        ],
                    )
                ),
                LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=b"\x04\x00" * 200,
                                    mime_type="audio/pcm;rate=24000",
                                )
                            )
                        ],
                    )
                ),
                LlmResponse(interrupted=True),
            ]
        )
        device = FakeAudioDevice(play_delay=0.05)
        session = VoiceSession(self._build_coordinator(conn), device)

        async def _run():
            task = asyncio.create_task(session.run())
            while device.clear_count == 0:
                await asyncio.sleep(0.02)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertGreaterEqual(device.clear_count, 1)

    def test_output_transcription_reaches_on_text_as_buddyai(self):
        received = []
        conn = _FakeConnection(
            trigger_on_audio=lambda: [
                LlmResponse(
                    output_transcription=types.Transcription(
                        text="Hello there.", finished=True
                    )
                ),
                LlmResponse(turn_complete=True),
            ]
        )
        device = FakeAudioDevice()
        session = VoiceSession(
            self._build_coordinator(conn),
            device,
            on_text=lambda speaker, text: received.append((speaker, text)),
        )

        async def _run():
            task = asyncio.create_task(session.run())
            while not received:
                await asyncio.sleep(0.02)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertEqual(received, [("BuddyAI", "Hello there.")])

    def test_spoken_stop_phrase_ends_run_automatically(self):
        received = []
        conn = _FakeConnection(
            trigger_on_audio=lambda: [
                LlmResponse(
                    input_transcription=types.Transcription(
                        text="Stop.", finished=True
                    )
                )
            ]
        )
        device = FakeAudioDevice()
        session = VoiceSession(
            self._build_coordinator(conn),
            device,
            on_text=lambda speaker, text: received.append((speaker, text)),
        )

        asyncio.run(asyncio.wait_for(session.run(), timeout=10))
        self.assertIn(("You", "Stop."), received)
        self.assertTrue(device.closed)

    def test_stop_method_ends_run_and_closes_audio_device(self):
        conn = _FakeConnection()
        device = FakeAudioDevice()
        session = VoiceSession(self._build_coordinator(conn), device)

        async def _run():
            task = asyncio.create_task(session.run())
            await asyncio.sleep(0.05)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        self.assertTrue(device.opened)
        self.assertTrue(device.closed)
        self.assertTrue(conn.closed)

    def test_connection_error_is_wrapped_as_model_request_error_and_closes_device(self):
        conn = _FakeConnection(fail_with=RuntimeError("websocket closed"))
        device = FakeAudioDevice()
        session = VoiceSession(self._build_coordinator(conn), device)

        with self.assertRaises(ModelRequestError) as ctx:
            asyncio.run(asyncio.wait_for(session.run(), timeout=10))
        self.assertIn("websocket closed", str(ctx.exception))
        self.assertTrue(device.closed)

    def test_live_function_call_to_task_agent_creates_task_in_workspace(self):
        done_event = asyncio.Event()

        def _on_audio():
            call = types.FunctionCall(
                name="task_agent",
                id="fc1",
                args={"request": "Add a task called Buy milk due 2026-11-27"},
            )
            return [
                LlmResponse(
                    content=types.Content(
                        role="model", parts=[types.Part(function_call=call)]
                    )
                )
            ]

        def _on_tool_resp(content):
            done_event.set()
            return [
                LlmResponse(
                    output_transcription=types.Transcription(
                        text="Added Buy milk.", finished=True
                    )
                ),
                LlmResponse(turn_complete=True),
            ]

        conn = _FakeConnection(
            trigger_on_audio=_on_audio,
            on_tool_response=_on_tool_resp,
        )
        device = FakeAudioDevice()
        agent = self._build_coordinator(
            conn, specialist_llm=_AddTaskTextLlm(model="gemini-3.5-flash-lite")
        )
        session = VoiceSession(agent, device)

        async def _run():
            task = asyncio.create_task(session.run())
            await done_event.wait()
            await asyncio.sleep(0.05)
            session.stop()
            await task

        asyncio.run(asyncio.wait_for(_run(), timeout=10))
        titles = [t.title for t in self.app.workspace.tasks.list_all_tasks()]
        self.assertIn("Buy milk", titles)


class TestVoiceAgentAndCommand(unittest.TestCase):
    """Checks build_voice_agent, VoiceCoordinatorProfile, and /voice command routing."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(
            data_dir=self._tmp.name,
            model=_QuietTextLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            ics_file="",
        )
        self.buffer = StringIO()
        console = Console(
            file=self.buffer,
            theme=RICH_THEME,
            highlight=False,
            no_color=True,
            width=200,
        )
        self.ui = TerminalUI(console=console, interactive=False)

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_build_voice_agent_uses_live_model_for_coordinator_and_text_model_for_sub_agents(self):
        with mock.patch.dict(
            os.environ, {"BUDDYAI_VOICE_MODEL": "gemini-3.8-live"}, clear=False
        ):
            agent = self.app.build_voice_agent()
        self.assertEqual(agent.canonical_live_model.model, "gemini-3.8-live")
        self.assertEqual(len(agent.sub_agents), 4)
        for sub in agent.sub_agents:
            with self.subTest(sub=sub.name):
                self.assertEqual(sub.model.model, "gemini-3.5-flash-lite")

    def test_voice_coordinator_profile_instruction_adds_spoken_style_guidance(self):
        profile = VoiceCoordinatorProfile(
            model=_QuietTextLlm(model="gemini-3.8-live"),
            toolkit=self.app.toolkit,
            specialists=[],
        )
        instr = profile.instruction()
        self.assertIn("speaking aloud", instr)
        self.assertIn("one or two short sentences", instr)

    def test_live_command_warns_and_starts_nothing_when_api_key_is_missing(self):
        started = []

        class _StandInApp:
            def start_voice_session(self, **kwargs):
                started.append(kwargs)

        router = CommandRouter(_StandInApp(), self.ui)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            outcome = router.handle("/live")
        self.assertEqual(outcome, CommandRouter.HANDLED)
        self.assertEqual(started, [])
        self.assertIn("GOOGLE_API_KEY", self.buffer.getvalue())

    def test_live_command_uses_echo_guard_by_default_and_disables_it_for_barge(self):
        seen = []

        class _StandInApp:
            def start_voice_session(self, **kwargs):
                seen.append(kwargs.get("echo_guard"))
                return "session"

            def run_voice(self, session):
                pass

        router = CommandRouter(_StandInApp(), self.ui)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            router.handle("/live")
            router.handle("/live barge")
        self.assertEqual(seen, [True, False])

    def test_live_command_shows_voice_unavailable_error_and_returns_to_prompt(self):
        class _StandInApp:
            def start_voice_session(self, **kwargs):
                raise VoiceUnavailableError("No microphone found.")

            def run_voice(self, session):
                raise AssertionError("run_voice must not be called")

        router = CommandRouter(_StandInApp(), self.ui)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            outcome = router.handle("/live")
        out = self.buffer.getvalue()
        self.assertEqual(outcome, CommandRouter.HANDLED)
        self.assertIn("VoiceUnavailableError", out)
        self.assertIn("No microphone found.", out)
        self.assertIn("BuddyAI Live ended.", out)

    def test_voice_dictation_command_prefills_pending_input_for_prompt(self):
        class _StandInApp:
            def transcribe_voice(self):
                return "Add a task to submit slides tomorrow."

        router = CommandRouter(_StandInApp(), self.ui)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            outcome = router.handle("/voice")
        self.assertEqual(outcome, CommandRouter.HANDLED)
        self.assertEqual(
            router.take_pending_input(), "Add a task to submit slides tomorrow."
        )
        self.assertEqual(router.take_pending_input(), "")
        self.assertIn("Transcribed", self.buffer.getvalue())

    def test_voice_dictation_command_handles_empty_speech_and_missing_key(self):
        class _StandInApp:
            def transcribe_voice(self):
                return ""

        router = CommandRouter(_StandInApp(), self.ui)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            router.handle("/voice")
        self.assertIn("GOOGLE_API_KEY", self.buffer.getvalue())

        self.buffer.truncate(0)
        self.buffer.seek(0)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            router.handle("/voice")
        self.assertEqual(router.take_pending_input(), "")
        self.assertIn("No speech detected.", self.buffer.getvalue())


class TestVoiceTranscriber(unittest.TestCase):
    """Checks live streaming dictation and how its errors are reported."""

    def test_a_failed_live_connection_is_wrapped_as_model_request_error(self):
        class _BrokenLiveNamespace:
            @contextlib.asynccontextmanager
            async def connect(self, *, model, config):
                raise RuntimeError("network down")
                yield

        class _BrokenLiveClient:
            aio = type("Aio", (), {"live": _BrokenLiveNamespace()})()

        device = FakeAudioDevice()
        transcriber = VoiceTranscriber(live_client=_BrokenLiveClient())
        with self.assertLogs("buddyai.voice.transcriber", level="ERROR"):
            with self.assertRaises(ModelRequestError) as ctx:
                asyncio.run(
                    transcriber.stream_and_transcribe_async(
                        device, wait_for_stop=lambda: time.sleep(0.04)
                    )
                )
        self.assertIn("network down", str(ctx.exception))
        self.assertTrue(device.closed)

    def test_stream_and_transcribe_emits_live_interim_updates_and_returns_final(self):
        updates = []
        sent_end = []

        class _FakeTranscribeSession:
            def __init__(self):
                self._queue = asyncio.Queue()
                self._sent = 0

            async def send_realtime_input(self, *, audio=None, audio_stream_end=None):
                if audio is not None:
                    self._sent += 1
                    if self._sent == 1:
                        await self._queue.put(
                            types.LiveServerMessage(
                                server_content=types.LiveServerContent(
                                    interim_input_transcription=types.Transcription(
                                        text="What is the"
                                    )
                                )
                            )
                        )
                    elif self._sent == 2:
                        await self._queue.put(
                            types.LiveServerMessage(
                                server_content=types.LiveServerContent(
                                    interim_input_transcription=types.Transcription(
                                        text="What is the weather"
                                    )
                                )
                            )
                        )
                if audio_stream_end:
                    sent_end.append(True)
                    await self._queue.put(
                        types.LiveServerMessage(
                            server_content=types.LiveServerContent(
                                input_transcription=types.Transcription(
                                    text="What is the weather in Manila?"
                                )
                            )
                        )
                    )

            async def receive(self):
                while True:
                    yield await self._queue.get()

        class _FakeLiveNamespace:
            def __init__(self, session):
                self._session = session

            @contextlib.asynccontextmanager
            async def connect(self, *, model, config):
                yield self._session

        class _FakeLiveClient:
            def __init__(self):
                self.session = _FakeTranscribeSession()
                self.aio = type("Aio", (), {"live": _FakeLiveNamespace(self.session)})()

        device = FakeAudioDevice()
        fake_client = _FakeLiveClient()
        transcriber = VoiceTranscriber(live_client=fake_client)
        result = asyncio.run(
            transcriber.stream_and_transcribe_async(
                device,
                on_update=lambda text: updates.append(text),
                wait_for_stop=lambda: time.sleep(0.06),
            )
        )
        self.assertEqual(result, "What is the weather in Manila?")
        self.assertTrue(sent_end)
        self.assertTrue(device.opened)
        self.assertTrue(device.closed)
        self.assertIn("What is the", updates)
        self.assertIn("What is the weather in Manila?", updates)


if __name__ == "__main__":
    unittest.main()
