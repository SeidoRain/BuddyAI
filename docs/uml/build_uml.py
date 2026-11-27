"""Draw the BuddyAI UML class diagrams (Figures 1 to 3) with matplotlib.

Run from anywhere:   python docs/uml/build_uml.py
It writes six PNG files (300 dpi) next to this script:

    figure1_domain_implemented.png       figure1_domain_proposal.png
    figure2_application_implemented.png  figure2_application_proposal.png
    figure3_interface_implemented.png    figure3_interface_proposal.png

"implemented" shows only classes that exist in the code. "proposal" adds the
planned Sprint 2 classes with a dashed border.

To change a class, edit its entry in the CLASSES table below and run again.
Boxes size themselves from their text. Where boxes sit and how the lines run
is set in the figure1(), figure2() and figure3() functions further down.
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# Look
# ----------------------------------------------------------------------
FONT = ["Arial", "DejaVu Sans"]
FS = 11           # font size in points, the same in every figure
LH = 15.5         # line height
PAD_X = 8         # text padding inside a box
PAD_Y = 5
LW = 1.5          # box and line width
DASH = (0, (6, 4))
MARGIN = 14

# ----------------------------------------------------------------------
# Class data. One entry per class: stereotype, attrs, methods.
# Text only; positions are in the figure functions.
# ----------------------------------------------------------------------
CLASSES = {
    # ---- Figure 1: work items --------------------------------------
    "WorkItem": dict(
        abstract=True,
        attrs=[
            "- _item_id: str",
            "- _title: str",
            "- _created_at: datetime",
            "- _source: str",
        ],
        methods=[
            "+ title: str  {property}",
            "+ rename(title): None",
            "+ is_due(now): bool  {abstract}",
            "+ summarize(): str  {abstract}",
            "+ priority_score(now): int  {abstract}",
            "+ status_note(now): str",
            "+ to_dict(): dict",
            "+ from_dict(data): WorkItem  {classmethod, abstract}",
        ],
    ),
    "Task": dict(
        attrs=["- _due_date: datetime | None", "- _priority: int", "- _status: str"],
        methods=[
            "+ confirm(): None",
            "+ mark_done(): None",
            "+ set_due_date(due_date, now): None",
            "+ set_priority(priority): None",
            "+ is_overdue(now): bool",
            "+ is_due(now): bool",
            "+ summarize(): str",
            "+ priority_score(now): int",
        ],
    ),
    "Reminder": dict(
        attrs=["- _remind_at: datetime", "- _repeat: str"],
        methods=[
            "+ occurrence_on(day, tz): datetime | None",
            "+ next_occurrence(now): datetime | None",
            "+ is_due(now): bool",
            "+ status_note(now): str",
            "+ summarize(): str",
            "+ priority_score(now): int",
        ],
    ),
    "Meeting": dict(
        attrs=[
            "- _start: datetime",
            "- _end: datetime",
            "- _location: str",
            "- _attendees: list[Contact]",
        ],
        methods=[
            "+ overlaps(other): bool",
            "+ reschedule(start, end): None",
            "+ set_location(location): None",
            "+ add_attendee(contact): None",
            "+ is_due(now): bool",
            "+ summarize(): str",
            "+ priority_score(now): int",
        ],
    ),
    "Note": dict(
        attrs=["- _body: str", "- _action_items: list[Task]"],
        methods=[
            "+ add_action_item(task): None",
            "+ is_due(now): bool",
            "+ summarize(): str",
            "+ priority_score(now): int",
        ],
    ),
    "Contact": dict(
        attrs=["- _name: str", "- _email: str", "- _organization: str"],
        methods=[
            "+ email: str  {property}",
            "+ to_dict(): dict",
        ],
    ),
    # ---- Figure 1: managers and workspace --------------------------
    "TaskManager": dict(
        attrs=["- _tasks: dict[str, Task]", "- _reminders: dict[str, Reminder]"],
        methods=[
            "+ add_task(task, now): Task",
            "+ confirm_all(task_ids): list[Task]",
            "+ find_task(id_or_title, include_done): Task",
            "+ update_task(task_id, title, due_date, priority, now): Task",
            "+ complete_task(task_id): Task",
            "+ remove_task(task_id): Task",
            "+ list_by_priority(now): list[Task]",
            "+ list_proposals(): list[Task]",
            "+ add_reminder(reminder, now): Reminder",
            "+ find_reminder(id_or_title): Reminder",
            "+ list_reminders(): list[Reminder]",
            "+ remove_reminder(reminder_id): Reminder",
        ],
    ),
    "Agenda": dict(
        attrs=["- _meetings: dict[str, Meeting]", "- _external: list[Meeting]"],
        methods=[
            "+ schedule(meeting, now): Meeting",
            "+ reschedule(meeting_id, start, end, now): Meeting",
            "+ update_meeting(meeting_id, title, location): Meeting",
            "+ find_meeting(id_or_title): Meeting",
            "+ cancel(meeting_id): Meeting",
            "+ find_conflicts(meeting): list[Meeting]",
            "+ find_free_slot(day, minutes): datetime",
            "+ set_external(meetings): None",
        ],
    ),
    "Notebook": dict(
        attrs=["- _notes: dict[str, Note]"],
        methods=[
            "+ add_note(note): Note",
            "+ find_note(id_or_title): Note",
            "+ search(keyword): list[Note]",
            "+ list_notes(): list[Note]",
            "+ remove_note(note_id): Note",
        ],
    ),
    "Workspace": dict(
        attrs=[
            "- _tasks: TaskManager",
            "- _agenda: Agenda",
            "- _notebook: Notebook",
            "- _sources: list[DataSource]",
            "- _synced: list[WorkItem]",
        ],
        methods=[
            "+ load(): None",
            "+ sync(): None",
            "+ save(): None",
            "+ replace_source(source): None",
            "+ remove_source(name): bool",
            "+ all_items(): list[WorkItem]",
            "+ items_for_day(now): list[WorkItem]",
        ],
    ),
    # ---- Figure 1: data sources ------------------------------------
    "DataSource": dict(
        abstract=True,
        attrs=["- _name: str"],
        methods=[
            "+ name: str  {property}",
            "+ is_read_only: bool  {property}",
            "+ fetch_items(): list[WorkItem]  {abstract}",
            "+ save_item(item): None  (raises ReadOnlySourceError)",
            "+ remove_item(item_id): None  (raises ReadOnlySourceError)",
            "+ save_all(items): None  (raises ReadOnlySourceError)",
        ],
    ),
    "JsonStore": dict(
        attrs=["- _data_dir: str"],
        methods=[
            "+ is_read_only: bool  {property}",
            "+ fetch_items(): list[WorkItem]",
            "+ save_all(items): None",
            "+ save_item(item): None",
            "+ remove_item(item_id): None",
            "- _atomic_write(filepath, data): None",
        ],
    ),
    "IcsCalendarSource": dict(
        attrs=[
            "- _path: str",
            "- _loaded_count: int",
            "- _skipped_count: int",
            "- _all_day_count: int",
            "- _recurring_count: int",
        ],
        methods=[
            "+ path: str  {property}",
            "+ loaded_count: int  {property}",
            "+ skipped_count: int  {property}",
            "+ all_day_count: int  {property}",
            "+ recurring_count: int  {property}",
            "+ fetch_items(): list[Meeting]",
        ],
    ),
    # ---- Figure 2: application, agents, toolkit --------------------
    "BuddyApp": dict(
        attrs=[
            "- _workspace: Workspace",
            "- _toolkit: BuddyToolkit",
            "- _briefing_service: BriefingService",
            "- _document_reader: DocumentReader",
            "- _web_lookup: WebLookup",
            "- _calendar_source: IcsCalendarSource | None",
            "- _catalog: ModelCatalog",
            "- _limit_log: ModelLimitLog",
            "- _llm: PatientGemini",
            "- _coordinator_profile: CoordinatorProfile",
            "- _root_agent: Agent",
            "- _runner: Runner",
            "- _last_request_invocation: str | None",
        ],
        methods=[
            "+ ask(message, files, on_status): str",
            "+ switch_model(choice): str",
            "+ handle_command(text): str | None",
            "+ check_file(path): str",
            "+ run_model_command(text): CommandReply | None",
            "+ load_calendar(path): IcsCalendarSource",
            "+ unload_calendar(): bool",
            "+ build_voice_agent(): Agent",
            "+ start_voice_session(audio_device, on_text, echo_guard): VoiceSession",
            "+ run_voice(session): None",
            "+ transcribe_voice(audio_device, on_update, wait_for_stop, live_client): str",
            "+ save_upload(data, mime_type, name): str",
            "+ root_agent: Agent  {property}",
            "- _start_request(callback_context): None",
        ],
    ),
    "AgentProfile": dict(
        abstract=True,
        attrs=[
            "- _name: str",
            "- _model: PatientGemini | str",
            "- _mode: str",
            "- _toolkit: BuddyToolkit",
        ],
        methods=[
            "+ description(): str  {abstract}",
            "+ instruction(context): str  {abstract}",
            "+ tools(): list[Callable]  {abstract}",
            "+ build(): Agent",
            "- _honesty_rule(): str  {static}",
        ],
    ),
    "VoiceCoordinatorProfile": dict(
        attrs=[],
        methods=["+ instruction(context): str  (adds spoken style)"],
    ),
    "CoordinatorProfile": dict(
        attrs=[
            "- _specialists: list[AgentProfile]",
            "- _command_handler: callable",
            "- _upload_handler: callable",
        ],
        methods=[
            "+ specialists: list[AgentProfile]  {property}",
            "+ description(): str",
            "+ instruction(context): str",
            "+ tools(): list[Callable]",
            "+ build(): Agent  (adds sub_agents)",
        ],
    ),
    "TaskAgentProfile": dict(
        attrs=[],
        methods=["+ description(): str", "+ instruction(context): str", "+ tools(): list[Callable]"],
    ),
    "ScheduleAgentProfile": dict(
        attrs=[],
        methods=["+ description(): str", "+ instruction(context): str", "+ tools(): list[Callable]"],
    ),
    "NotesAgentProfile": dict(
        attrs=[],
        methods=["+ description(): str", "+ instruction(context): str", "+ tools(): list[Callable]"],
    ),
    "BriefingAgentProfile": dict(
        attrs=[],
        methods=["+ description(): str", "+ instruction(context): str", "+ tools(): list[Callable]"],
    ),
    "BuddyToolkit": dict(
        attrs=[
            "- _workspace: Workspace",
            "- _briefing_service: BriefingService",
            "- _document_reader: DocumentReader",
            "- _clock: callable",
            "- _web_lookup: WebLookup",
            "- _read_untrusted: bool",
        ],
        methods=[
            "+ current_time(): datetime",
            "+ begin_request(): None",
            "+ read_untrusted: bool  {property}",
            "+ add_task(title, due, priority): dict",
            "+ delete_reminder(reminder): dict",
            "+ schedule_meeting(title, start, end, location, attendees): dict",
            "+ update_meeting(meeting, title, location): dict",
            "+ delete_note(note): dict",
            "+ summarize_document(path): dict",
            "+ get_daily_briefing(day, at_time, location): dict",
            "+ get_weather(location): dict",
            "+ search_web(query): dict",
            "(24 agent tools in total)",
        ],
    ),
    "BriefingService": dict(
        attrs=[
            "- _workspace: Workspace",
            "- _web_lookup: WebLookup",
            "- _default_location: str",
        ],
        methods=["+ build_briefing(now, location, weather_at, include_live): DailyBriefing"],
    ),
    "DailyBriefing": dict(
        attrs=[
            "- _day: date",
            "- _items: list[WorkItem]",
            "- _now: datetime | None",
            "- _weather: dict | None",
            "- _headlines: list[dict] | None",
        ],
        methods=[
            "+ day: date  {property}",
            "+ items: list[WorkItem]  {property}",
            "+ weather: dict | None  {property}",
            "+ headlines: list[dict] | None  {property}",
            "+ to_text(): str",
        ],
    ),
    "WebLookup": dict(
        attrs=[
            "+ TIMEOUT_SECONDS: int = 8",
            "- _fetcher: callable",
            "- _geo_cache: dict",
        ],
        methods=[
            "+ get_weather(location, at_time): dict",
            "+ get_headlines(limit, country): dict",
            "+ search_web(query, max_results): dict",
        ],
    ),
    "CommandReply": dict(
        attrs=[
            '+ VALID_LEVELS: tuple',
            "- _text: str",
            "- _level: str",
        ],
        methods=["+ text: str  {property}", "+ level: str  {property}"],
    ),
    "DocumentReader": dict(
        attrs=[
            "+ SUPPORTED_TYPES: dict",
            "+ DOCX_TYPE: str",
            "- _model: str",
            "- _client: Client",
            "- _clock: callable",
        ],
        methods=[
            "+ summarize(path, now): Note",
            "+ validate_file(path): tuple",
            "- _extract_docx_text(path): str",
            "+ set_model(model): None",
            "+ extension_for(name, mime_type): str | None  {classmethod}",
        ],
    ),
    "ModelCatalog": dict(
        attrs=["- _names: list[str]", "- _current: str", "- _unavailable: dict[str, str]"],
        methods=[
            "+ current: str  {property}",
            "+ switch(choice): str",
            "+ resolve(choice): str",
            "+ mark_unavailable(name, reason): None",
            "+ next_available(): str | None",
        ],
    ),
    "ModelLimitLog": dict(
        attrs=["- _path: str", "- _clock: callable"],
        methods=[
            "+ limited_today(): list[str]",
            "+ record(name): None",
            "+ next_reset(): datetime",
        ],
    ),
    "PatientGemini": dict(
        attrs=["+ BUSY_RETRIES: int = 2", "+ BUSY_WAIT_SECONDS: float = 3"],
        methods=["+ generate_content_async(llm_request, stream)"],
    ),
    "Gemini": dict(external="ADK"),
    # ---- Figure 3: terminal interface ------------------------------
    "CommandRouter": dict(
        attrs=[
            '+ EXIT: str = "exit"',
            '+ HANDLED: str = "handled"',
            '+ NOT_A_COMMAND: str = "not_a_command"',
            "- _app: BuddyApp",
            "- _ui: TerminalUI",
            "- _commands: dict[str, Callable]",
            "- _pending_input: str",
        ],
        methods=[
            "+ handle(text): str",
            "+ send(prompt_text, files): None",
            "+ take_pending_input(): str",
            "- _take_file_mentions(text): tuple[str, list[str]]",
            "- _mentioned_path(match): tuple[str | None, str]",
            "- _unknown_command_text(word): str",
            "- _show_brief(arguments): None",
            "- _change_model(arguments): None",
            "- _attach_file(arguments): None",
            "- _calendar_command(arguments): None",
            "- _live_command(arguments): None",
            "- _voice_command(arguments): None",
            "- _task_command(arguments): None",
            "- _meet_command(arguments): None",
            "- _done_command(arguments): None",
        ],
    ),
    "TerminalUI": dict(
        attrs=[
            "- _interactive: bool",
            "- _console: Console",
            "- _glyphs: dict[str, str]",
        ],
        methods=[
            "+ interactive: bool  {property}",
            "+ console: Console  {property}",
            "+ glyphs: dict[str, str]  {property}",
            "+ thinking_context(): ThinkingIndicator",
            "+ render_welcome(app): None",
            "+ render_buddy_reply(text, agents, elapsed): None",
            "+ render_ok(text): None",
            "+ render_tasks(app): None",
            "+ render_help(): None",
            "+ pick_model_interactive(app): str | None",
        ],
    ),
    "ThinkingIndicator": dict(
        attrs=[
            "- _console: Console",
            "- _label: str",
            "- _agents: list[str]",
            "- _elapsed: float",
        ],
        methods=[
            "+ update(stage, agent): None",
            "+ elapsed: float  {property}",
            "+ agents: list[str]  {property}",
            "+ __enter__(): ThinkingIndicator",
            "+ __exit__(exc_type, exc, tb): bool",
        ],
    ),
    "BuddyPrompt": dict(
        attrs=[
            "+ SWITCH_NOTE_SECONDS: int = 30",
            "- _get_model_name: callable",
            "- _clock: callable",
            "- _interactive: bool",
            "- _glyphs: dict[str, str]",
            "- _session: PromptSession",
            "- _shown_model: str | None",
            "- _switched_from: str",
            "- _switched_at: float | None",
        ],
        methods=[
            "+ read_input(default): str",
            "+ toolbar_text(): str",
            "+ interactive: bool  {property}",
        ],
    ),
    "BuddyCompleter": dict(
        attrs=["- _path_completer: PathCompleter"],
        methods=[
            "+ get_completions(document, complete_event): Iterator[Completion]",
            "- _mention_before_cursor(text): str | None",
            "- _complete_path(typed, complete_event): Iterator[Completion]",
        ],
    ),
    "Completer": dict(external="prompt_toolkit"),
    "main.py": dict(
        stereotype="«module»",
        attrs=["+ LOG_FILE: str"],
        methods=[
            "+ main(): int",
            "- _configure_logging(): None",
            "- _configure_stdio(): None",
        ],
    ),
    "VoiceSession": dict(
        attrs=[
            "- _agent: Agent",
            "- _audio_device: AudioDevice",
            "- _echo_guard: bool",
        ],
        methods=["+ run(): None", "+ stop(): None", "+ interrupt_playback(): None"],
    ),
    "VoiceTranscriber": dict(
        attrs=[
            '+ LIVE_MODEL: str = "gemini-3.5-transcribe-live"',
            "- _live_client: Client",
        ],
        methods=["+ stream_and_transcribe_async(audio_device, on_update, wait_for_stop): str"],
    ),
    "AudioDevice": dict(
        abstract=True,
        attrs=["+ INPUT_RATE: int = 16000", "+ OUTPUT_RATE: int = 24000"],
        methods=[
            "+ open(): None  {abstract}",
            "+ close(): None  {abstract}",
            "+ read_chunk(): bytes  {abstract}",
            "+ play(chunk): None  {abstract}",
            "+ clear_playback(): None  {abstract}",
        ],
    ),
    "SoundDeviceAudio": dict(
        attrs=["- _input: RawInputStream", "- _output: RawOutputStream"],
        methods=[
            "+ open(): None  (raises VoiceUnavailableError)",
            "+ close(): None",
            "+ read_chunk(): bytes",
            "+ play(chunk): None",
            "+ clear_playback(): None",
        ],
    ),
}


# ----------------------------------------------------------------------
# Drawing helper
# ----------------------------------------------------------------------
_meas_fig = plt.figure(figsize=(4, 4), dpi=72)
_meas_rend = _meas_fig.canvas.get_renderer()


def text_width(s, bold=False, italic=False):
    """Width of a string in points (the measuring figure is 72 dpi)."""
    t = _meas_fig.text(
        0, 0, s, fontsize=FS, family=FONT,
        fontweight="bold" if bold else "normal",
        fontstyle="italic" if italic else "normal",
    )
    width = t.get_window_extent(_meas_rend).width
    t.remove()
    return width


class Box:
    """A UML class box that sizes itself from its text."""

    def __init__(self, name, attrs=(), methods=(), abstract=False, planned=False,
                 external=None, stub=None, stereotype=None, min_width=0, title=None):
        self.name = name
        self.title = title or name
        self.attrs = list(attrs)
        self.methods = list(methods)
        self.abstract = abstract
        self.planned = planned
        self.external = external
        self.stub = stub
        if abstract:
            stereotype = "«abstract»"
        elif planned:
            stereotype = "«planned, Sprint 2»"
        elif external:
            stereotype = "«%s»" % external
        self.stereotype = stereotype
        if stub:
            self.methods = [stub]
        self.header_only = bool(external)
        self.x = 0.0
        self.y = 0.0
        # sizes
        head_lines = 2 if self.stereotype else 1
        self.h_head = 2 * PAD_Y + head_lines * LH
        self.h_attrs = 2 * PAD_Y + max(len(self.attrs), 1) * LH if not self.header_only else 0
        self.h_meth = 2 * PAD_Y + max(len(self.methods), 1) * LH if not self.header_only else 0
        self.h = self.h_head + self.h_attrs + self.h_meth
        widths = [text_width(self.title, bold=True, italic=abstract) + 2 * PAD_X]
        if self.stereotype:
            widths.append(text_width(self.stereotype) + 2 * PAD_X)
        for line in self.attrs + self.methods:
            widths.append(text_width(line) + 2 * PAD_X)
        self.w = max(max(widths), min_width)

    # --- position helpers ---
    def at(self, x, y):
        self.x, self.y = x, y
        return self

    @property
    def left(self):
        return self.x

    @property
    def right(self):
        return self.x + self.w

    @property
    def top(self):
        return self.y

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def pt(self, side, frac=0.5, off=None):
        """Point on an edge. frac is 0..1 along the edge; off is points from the
        start of the edge (left or top) and overrides frac."""
        if side in ("top", "bottom"):
            px = self.x + (off if off is not None else frac * self.w)
            return (px, self.top if side == "top" else self.bottom)
        py = self.y + (off if off is not None else frac * self.h)
        return (self.left if side == "left" else self.right, py)

    def line_y(self, index_in_methods=0):
        """y of a methods line (to aim a horizontal connector at a given row)."""
        return self.y + self.h_head + self.h_attrs + PAD_Y + LH * (index_in_methods + 0.5)

    def attr_y(self, index=0):
        return self.y + self.h_head + PAD_Y + LH * (index + 0.5)

    def head_y(self):
        return self.y + self.h_head / 2


class Diagram:
    """Boxes, connectors and labels for one figure; draws them to a PNG."""

    TRI_L, TRI_W = 15, 7.5
    DIA_L, DIA_W = 20, 6.5
    ARR_L, ARR_W = 11, 5.5

    def __init__(self):
        self.boxes = []
        self.lines = []     # (points, start_deco, end_deco, dashed)
        self.labels = []    # (x, y, text, ha, va)

    def add(self, box):
        self.boxes.append(box)
        return box

    # --- connectors ---
    def link(self, points, start=None, end=None, dashed=False):
        """Polyline with optional decorations: 'tri', 'dia_h', 'dia_f', 'open'."""
        self.lines.append((list(points), start, end, dashed))

    def inherit(self, parent, children, bus, side="bottom", parent_x=None):
        """Hollow triangle at the parent, one shared bus line, drops to the children.
        bus is the y of the bus (parent below the children uses side='top')."""
        px = parent.cx if parent_x is None else parent_x
        py = parent.bottom if side == "bottom" else parent.top
        child_side = "top" if side == "bottom" else "bottom"
        self.link([(px, py), (px, bus)], start="tri")
        xs = [c.cx for c in children] + [px]
        self.link([(min(xs), bus), (max(xs), bus)])
        for c in children:
            cy = c.top if child_side == "top" else c.bottom
            self.link([(c.cx, bus), (c.cx, cy)])

    def label(self, x, y, text, ha="left", va="center"):
        self.labels.append((x, y, text, ha, va))

    # --- checks ---
    def check(self, title=""):
        problems = []
        for i, a in enumerate(self.boxes):
            for b in self.boxes[i + 1:]:
                if a.left < b.right + 8 and b.left < a.right + 8 and a.top < b.bottom + 8 and b.top < a.bottom + 8:
                    problems.append("boxes too close or overlapping: %s / %s" % (a.name, b.name))
        for pts, _, _, _ in self.lines:
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                lo_x, hi_x = min(x1, x2), max(x1, x2)
                lo_y, hi_y = min(y1, y2), max(y1, y2)
                for b in self.boxes:
                    if hi_x > b.left + 1.5 and lo_x < b.right - 1.5 and hi_y > b.top + 1.5 and lo_y < b.bottom - 1.5:
                        problems.append("line crosses box %s: %s" % (b.name, [(round(x1), round(y1)), (round(x2), round(y2))]))
        for x, y, text, ha, va in self.labels:
            w = text_width(text)
            lx0 = x if ha == "left" else (x - w if ha == "right" else x - w / 2)
            lx1, ly0, ly1 = lx0 + w, y - LH / 2, y + LH / 2
            for b in self.boxes:
                if lx1 > b.left and lx0 < b.right and ly1 > b.top and ly0 < b.bottom:
                    problems.append("label '%s' overlaps box %s" % (text, b.name))
            for pts, _, _, _ in self.lines:
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    if max(x1, x2) > lx0 - 1 and min(x1, x2) < lx1 + 1 and max(y1, y2) > ly0 + 1 and min(y1, y2) < ly1 - 1:
                        problems.append("label '%s' touches a line" % text)
        for p in sorted(set(problems)):
            print("  CHECK %s: %s" % (title, p))
        return problems

    # --- drawing ---
    def _deco(self, ax, tip, direction, kind):
        dx, dy = direction
        nx, ny = -dy, dx
        tx, ty = tip
        if kind == "tri":
            L, W = self.TRI_L, self.TRI_W
            pts = [(tx, ty), (tx - dx * L + nx * W, ty - dy * L + ny * W),
                   (tx - dx * L - nx * W, ty - dy * L - ny * W)]
            ax.add_patch(Polygon(pts, closed=True, fc="white", ec="black", lw=LW, zorder=2.5))
        elif kind in ("dia_h", "dia_f"):
            L, W = self.DIA_L, self.DIA_W
            pts = [(tx, ty), (tx - dx * L / 2 + nx * W, ty - dy * L / 2 + ny * W),
                   (tx - dx * L, ty - dy * L), (tx - dx * L / 2 - nx * W, ty - dy * L / 2 - ny * W)]
            ax.add_patch(Polygon(pts, closed=True, fc="black" if kind == "dia_f" else "white",
                                 ec="black", lw=LW, zorder=2.5))
        elif kind == "open":
            L, W = self.ARR_L, self.ARR_W
            for s in (1, -1):
                ax.plot([tx, tx - dx * L + s * nx * W], [ty, ty - dy * L + s * ny * W],
                        color="black", lw=LW, solid_capstyle="butt", zorder=2.5)

    def _unit(self, p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = (dx * dx + dy * dy) ** 0.5
        return (dx / n, dy / n)

    def bounds(self):
        xs, ys = [], []
        for b in self.boxes:
            xs += [b.left, b.right]
            ys += [b.top, b.bottom]
        for pts, _, _, _ in self.lines:
            for x, y in pts:
                xs.append(x)
                ys.append(y)
        for x, y, text, ha, va in self.labels:
            w = text_width(text)
            x0 = x if ha == "left" else (x - w if ha == "right" else x - w / 2)
            xs += [x0, x0 + w]
            ys += [y - LH / 2, y + LH / 2]
        return min(xs), min(ys), max(xs), max(ys)

    def save(self, filename, title=""):
        self.check(title)
        x0, y0, x1, y1 = self.bounds()
        x0 -= MARGIN
        y0 -= MARGIN
        x1 += MARGIN
        y1 += MARGIN
        W, H = x1 - x0, y1 - y0
        fig = plt.figure(figsize=(W / 72, H / 72), dpi=72)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(x0, x1)
        ax.set_ylim(y1, y0)     # y grows downward
        ax.axis("off")
        fig.patch.set_facecolor("white")

        for pts, start, end, dashed in self.lines:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color="black", lw=LW,
                    linestyle=DASH if dashed else "-", solid_joinstyle="miter",
                    dash_capstyle="butt", zorder=1)
            if start:
                self._deco(ax, pts[0], self._unit(pts[1], pts[0]), start)
            if end:
                self._deco(ax, pts[-1], self._unit(pts[-2], pts[-1]), end)

        for b in self.boxes:
            self._draw_box(ax, b)

        for x, y, text, ha, va in self.labels:
            ax.text(x, y, text, fontsize=FS, family=FONT, ha=ha, va="center_baseline",
                    zorder=6, bbox=dict(fc="white", ec="none", pad=1.2))

        path = os.path.join(OUT_DIR, filename)
        fig.savefig(path, dpi=300, facecolor="white")
        plt.close(fig)
        # printed size of the text when the figure is scaled to fit landscape A4
        # (usable area about 770 x 523 pt with 1.27 cm margins)
        eff = FS * min(770.0 / W, 523.0 / H)
        print("wrote %s  (%d x %d pt, ratio %.2f, text about %.1f pt on A4 landscape)"
              % (filename, W, H, W / H, eff))

    def _draw_box(self, ax, b):
        style = DASH if b.planned else "-"
        ax.add_patch(Rectangle((b.x, b.y), b.w, b.h, fc="white", ec="black", lw=LW,
                               linestyle=style, zorder=3))
        y = b.y
        # name compartment
        if b.stereotype:
            ax.text(b.cx, y + PAD_Y + LH * 0.5, b.stereotype, fontsize=FS, family=FONT,
                    ha="center", va="center_baseline", zorder=4)
            ax.text(b.cx, y + PAD_Y + LH * 1.5, b.title, fontsize=FS, family=FONT,
                    ha="center", va="center_baseline", fontweight="bold",
                    fontstyle="italic" if b.abstract else "normal", zorder=4)
        else:
            ax.text(b.cx, y + PAD_Y + LH * 0.5, b.title, fontsize=FS, family=FONT,
                    ha="center", va="center_baseline", fontweight="bold", zorder=4)
        if b.header_only:
            return
        y += b.h_head
        for height, lines in ((b.h_attrs, b.attrs), (b.h_meth, b.methods)):
            ax.plot([b.x, b.right], [y, y], color="black", lw=LW, zorder=4,
                    linestyle=DASH if b.planned else "-")
            for i, line in enumerate(lines):
                ax.text(b.x + PAD_X, y + PAD_Y + LH * (i + 0.5), line, fontsize=FS,
                        family=FONT, ha="left", va="center_baseline", zorder=4)
            y += height


def make(name, planned_ok=True, **overrides):
    """Build a Box from the CLASSES table."""
    spec = dict(CLASSES[name])
    spec.update(overrides)
    return Box(name, **spec)


# ----------------------------------------------------------------------
# Figure 1: work items, managers and data sources
# ----------------------------------------------------------------------
def figure1(planned):
    d = Diagram()
    b = {n: d.add(make(n)) for n in (
        "WorkItem", "Task", "Reminder", "Meeting", "Note", "Contact",
        "TaskManager", "Agenda", "Notebook", "Workspace", "DataSource", "JsonStore",
        "IcsCalendarSource")}
    note, task, rem, mtg, con = b["Note"], b["Task"], b["Reminder"], b["Meeting"], b["Contact"]
    ws, nb, tm, ag = b["Workspace"], b["Notebook"], b["TaskManager"], b["Agenda"]
    ds, js, ics, wi = b["DataSource"], b["JsonStore"], b["IcsCalendarSource"], b["WorkItem"]

    GAP = 28
    # items row (y fixed later)
    x = 0
    for box, gap in ((note, 50), (task, GAP), (rem, GAP), (mtg, 50), (con, 0)):
        box.x = x
        x += box.w + gap
    # managers above their items
    nb.x = note.cx - nb.w / 2
    tm.x = (task.cx + rem.cx) / 2 - tm.w / 2
    ag.x = mtg.cx - ag.w / 2
    ws.x = (nb.cx + ag.cx) / 2 - ws.w / 2
    # data sources on the right
    ds_x = max(ag.right, con.right) + 60
    ds.x = ds_x + 0
    row_a = 0
    ws.y = row_a
    ds.y = row_a
    row_b = max(ws.bottom, ds.bottom) + 52
    for m in (nb, tm, ag):
        m.y = row_b
    js.x = ag.right + 50
    ics.x = js.right + 24
    ds.x = (js.x + ics.right) / 2 - ds.w / 2
    bus_ds = ds.bottom + 30
    js.y = ics.y = max(ds.bottom + 62, row_b)
    row_c = max(m.bottom for m in (nb, tm, ag)) + 48
    for box in (note, task, rem, mtg, con):
        box.y = row_c
    bus_wi = max(note.bottom, task.bottom, rem.bottom, mtg.bottom) + 30
    wi.x = con.right + 38
    wi.y = bus_wi - 0.6 * wi.h

    # Workspace composes the managers
    mid = ws.bottom + 30
    for m, fx in ((nb, 0.2), (tm, 0.5), (ag, 0.8)):
        px = ws.x + fx * ws.w
        tx = m.cx
        d.link([(px, ws.bottom), (px, mid), (tx, mid), (tx, m.top)], start="dia_f")
        d.label(tx + 6, m.top - 11, "1")
    # Workspace aggregates the data sources
    ly = ws.y + 56
    d.link([(ws.right, ly), (ds.left, ly)], start="dia_h")
    d.label(ds.left - 8, ly - 12, "0..*", ha="right")
    # managers aggregate their items
    for m, items in ((nb, [note]), (tm, [task, rem]), (ag, [mtg])):
        for it in items:
            d.link([(it.cx, m.bottom), (it.cx, it.top)], start="dia_h")
            d.label(it.cx + 6, it.top - 11, "0..*")
    # Meeting aggregates Contact, Note aggregates Task
    y = mtg.attr_y(3)
    d.link([(mtg.right, y), (con.left, y)], start="dia_h")
    d.label(con.left - 5, y - 12, "0..*", ha="right")
    y = note.attr_y(1)
    d.link([(note.right, y), (task.left, y)], start="dia_h")
    d.label(task.left - 5, y - 12, "0..*", ha="right")
    # inheritance
    # WorkItem sits to the right; its triangle faces the bus that runs under the items
    kids3 = [note, task, rem, mtg]
    d.link([(wi.left, bus_wi), (note.cx, bus_wi)], start="tri")
    for c in kids3:
        d.link([(c.cx, c.bottom), (c.cx, bus_wi)])
    d.inherit(ds, [js, ics], bus_ds, side="bottom")
    return d


# ----------------------------------------------------------------------
# Figure 2: agents, toolkit and application
# ----------------------------------------------------------------------
def figure2(planned):
    d = Diagram()
    names = ("BuddyApp", "AgentProfile", "CoordinatorProfile", "TaskAgentProfile",
             "ScheduleAgentProfile", "NotesAgentProfile", "BriefingAgentProfile",
             "BuddyToolkit", "BriefingService", "DailyBriefing", "DocumentReader",
             "ModelCatalog", "ModelLimitLog", "PatientGemini", "Gemini",
             "VoiceCoordinatorProfile", "WebLookup", "CommandReply")
    b = {n: d.add(make(n)) for n in names}
    ws = d.add(Box("Workspace", stub="(see Figure 1)"))
    app, ap, co, tk = b["BuddyApp"], b["AgentProfile"], b["CoordinatorProfile"], b["BuddyToolkit"]
    bs, db, dr = b["BriefingService"], b["DailyBriefing"], b["DocumentReader"]
    mc, ml, pg, gm = b["ModelCatalog"], b["ModelLimitLog"], b["PatientGemini"], b["Gemini"]
    vco, wl, cr = b["VoiceCoordinatorProfile"], b["WebLookup"], b["CommandReply"]
    specs = [b["TaskAgentProfile"], b["ScheduleAgentProfile"], b["NotesAgentProfile"],
             b["BriefingAgentProfile"]]

    # row 2: DocumentReader | BuddyToolkit | Workspace | BriefingService | DailyBriefing
    dr.at(0, 0)
    tk.at(dr.right + 50, 0)
    ws.at(tk.right + 40, 0)
    bs.at(ws.right + 50, 0)
    db.at(bs.right - db.w, 0)
    # BuddyApp sits above the Toolkit / Workspace gap
    off = [20, 84, 148, 212]            # where the four diamonds leave the bottom edge
    app.x = (tk.right - 14) - off[1]
    app.y = 30
    r2 = app.bottom + 80
    for box in (dr, tk, ws, bs):
        box.y = r2
    db.y = bs.bottom + 44
    # right column next to BuddyApp
    col = app.right + 80
    pg.at(col, 0)
    mc.at(col, pg.bottom + 25)
    gm.at(pg.right + 60, pg.cy - gm.h / 2)
    # ModelLimitLog sits left of BuddyApp, above the Toolkit
    ml.at(app.x - 80 - ml.w, app.y + 100)
    # row 3: agent profiles
    r3 = tk.bottom + 46
    ap.at(tk.x, r3)
    co.at(0, r3)
    vco.at(co.x, co.top - 46 - vco.h)
    wl.at(max(bs.right, db.right) + 70, r2)
    cr.at(0, app.y + 30)
    ap_bus = ap.top + 30
    x = ap.right + 70
    for s_ in specs:
        s_.at(x, ap.top + 70)
        x += s_.w + 30

    # BuddyApp composes its parts (diamond at the BuddyApp end)
    mid_dr, mid_bs = app.bottom + 62, app.bottom + 36
    d.link([(app.x + off[0], app.bottom), (app.x + off[0], mid_dr), (dr.cx, mid_dr), (dr.cx, dr.top)], start="dia_f")
    d.link([(app.x + off[1], app.bottom), (app.x + off[1], tk.top)], start="dia_f")
    d.link([(app.x + off[2], app.bottom), (app.x + off[2], ws.top)], start="dia_f")
    d.link([(app.x + off[3], app.bottom), (app.x + off[3], mid_bs), (bs.cx, mid_bs), (bs.cx, bs.top)], start="dia_f")
    yml = ml.y + 40
    d.link([(app.left, yml), (ml.right, yml)], start="dia_f")
    d.link([(app.right, mc.y + 50), (mc.left, mc.y + 50)], start="dia_f")
    y_llm = app.y + 30
    d.link([(app.right, y_llm), (pg.left, y_llm)], end="open")
    d.label((app.right + pg.left) / 2, y_llm - 12, "_llm", ha="center")
    ya = app.bottom - 14
    lane = -34
    d.link([(app.left, ya), (lane, ya), (lane, co.y + 44), (co.left, co.y + 44)], start="dia_f")
    # BuddyApp owns the WebLookup and creates CommandReply objects
    yw = app.bottom - 30
    d.link([(app.right, yw), (wl.cx, yw), (wl.cx, wl.top)], start="dia_f")
    ycr = app.y + 70
    d.link([(app.left, ycr), (cr.right, ycr)], end="open", dashed=True)
    d.label((app.left + cr.right) / 2, ycr - 12, "creates", ha="center")
    # inheritance
    d.link([(co.cx, co.top), (co.cx, vco.bottom)], start="tri")
    d.link([(pg.right, pg.cy), (gm.left, pg.cy)], end="tri")
    y1, y2 = co.y + 40, co.y + 118
    d.link([(co.right, y1), (ap.left, y1)], start="dia_h")
    d.label(ap.left - 6, y1 - 12, "1..*", ha="right")
    d.link([(co.right, y2), (ap.left, y2)], end="tri")
    d.link([(ap.right, ap_bus), (specs[-1].cx, ap_bus)], start="tri")
    for s_ in specs:
        d.link([(s_.cx, ap_bus), (s_.cx, s_.top)])
    # associations
    y = r2 + 44
    d.link([(tk.right, y), (ws.left, y)], end="open")
    d.link([(bs.left, y), (ws.right, y)], end="open")
    d.link([(tk.left, y), (dr.right, y)], end="open")
    yu = tk.bottom + 28
    d.link([(tk.right - 30, tk.bottom), (tk.right - 30, yu), (bs.left + 30, yu), (bs.left + 30, bs.bottom)], end="open")
    d.link([(ap.x + 60, ap.top), (ap.x + 60, tk.bottom)], end="open")
    d.label(ap.x + 66, (ap.top + tk.bottom) / 2, "_toolkit")
    # BriefingService and BuddyToolkit both use WebLookup
    d.link([(bs.right, wl.y + 64), (wl.left, wl.y + 64)], end="open")
    yt = tk.bottom + 56
    d.link([(tk.right - 60, tk.bottom), (tk.right - 60, yt), (wl.cx + 40, yt), (wl.cx + 40, wl.bottom)], end="open")
    xd = bs.right - 30
    d.link([(xd, bs.bottom), (xd, db.top)], end="open", dashed=True)
    d.label(xd + 8, (bs.bottom + db.top) / 2, "creates")
    return d


# ----------------------------------------------------------------------
# Figure 3: terminal interface
# ----------------------------------------------------------------------
def figure3(planned):
    d = Diagram()
    mn = d.add(make("main.py"))
    app = d.add(Box("BuddyApp", stub="(see Figure 2)", min_width=200))
    tk = d.add(Box("BuddyToolkit", stub="(see Figure 2)"))
    ro, ui, ti = d.add(make("CommandRouter")), d.add(make("TerminalUI")), d.add(make("ThinkingIndicator"))
    pr, co, ex = d.add(make("BuddyPrompt")), d.add(make("BuddyCompleter")), d.add(make("Completer"))
    vs, vt = d.add(make("VoiceSession")), d.add(make("VoiceTranscriber"))
    ad, sd = d.add(make("AudioDevice")), d.add(make("SoundDeviceAudio"))

    GAP_UR = 96                       # between TerminalUI and CommandRouter
    row3 = 330
    pr.at(0, row3)
    ui.at(max(pr.right, co.right) + 70, row3)
    ro.at(ui.right + GAP_UR, row3)
    app.at((ui.right + ro.x) / 2 - app.w / 2, 170)
    mn.at(app.cx - mn.w / 2, 0)
    ti.at(ro.x, ro.bottom + 50)
    tk.at(ti.right + 30, ti.y)
    colA = ro.right + 70
    vs.at(colA, app.y - 26)
    vt.at(colA, vs.bottom + 90)
    ad.at(colA, vt.bottom + 56)
    sd.at(colA, ad.bottom + 50)
    co.at(pr.x, pr.bottom + 55)
    ex.at(co.cx - ex.w / 2, co.bottom + 55)

    # main.py creates the four objects (dashed arrows)
    y_p, y_u = mn.y + 22, mn.y + 50
    d.link([(mn.left, y_p), (pr.cx, y_p), (pr.cx, pr.top)], end="open", dashed=True)
    d.link([(mn.left, y_u), (ui.cx, y_u), (ui.cx, ui.top)], end="open", dashed=True)
    x_mr = ro.right - 15
    d.link([(mn.right, mn.y + 36), (x_mr, mn.y + 36), (x_mr, ro.top)], end="open", dashed=True)
    d.link([(mn.cx, mn.bottom), (app.cx, app.top)], end="open", dashed=True)
    d.label(pr.cx + 8, row3 - 30, "creates")
    d.label(ui.cx + 8, row3 - 30, "creates")
    d.label(x_mr + 8, row3 - 30, "creates")
    d.label(app.cx + 8, (mn.bottom + app.top) / 2, "creates")
    # CommandRouter and TerminalUI use the app
    xa1, xa2 = ui.right - 30, ro.x + 30
    d.link([(xa1, ui.top), (xa1, app.bottom)], end="open", dashed=True)
    d.label(xa1 - 8, (ui.top + app.bottom) / 2, "uses", ha="right")
    d.link([(xa2, ro.top), (xa2, app.bottom)], end="open")
    d.label(xa2 + 8, (ro.top + app.bottom) / 2, "_app")
    # CommandRouter holds the TerminalUI
    y = row3 + 40
    d.link([(ro.left, y), (ui.right, y)], end="open")
    d.label((ro.left + ui.right) / 2, y - 12, "_ui", ha="center")
    # CommandRouter calls toolkit methods (/task, /meet, /task done)
    x_tk = tk.x + 40
    d.link([(x_tk, ro.bottom), (x_tk, tk.top)], end="open", dashed=True)
    d.label(x_tk + 8, (ro.bottom + tk.top) / 2, "calls")
    # TerminalUI creates ThinkingIndicator
    x_ti, y_ti = ui.right - 50, ti.y + 28
    d.link([(x_ti, ui.bottom), (x_ti, y_ti), (ti.left, y_ti)], end="open", dashed=True)
    d.label((x_ti + ti.left) / 2 + 10, y_ti - 12, "creates", ha="center")
    # BuddyPrompt creates BuddyCompleter; BuddyCompleter extends Completer
    d.link([(pr.cx, pr.bottom), (pr.cx, co.top)], end="open", dashed=True)
    d.label(pr.cx + 8, (pr.bottom + co.top) / 2, "creates")
    d.link([(co.cx, co.bottom), (co.cx, ex.top)], end="tri")
    # BuddyApp creates the VoiceSession (start_voice_session)
    yv = vs.attr_y(0)
    d.link([(app.right, yv), (vs.left, yv)], end="open", dashed=True)
    d.label((app.right + vs.left) / 2, yv - 12, "creates", ha="center")
    # BuddyApp creates the VoiceTranscriber (transcribe_voice)
    xm = ro.right + 35
    yt_ = vt.attr_y(0)
    ya_ = app.y + 80
    d.link([(app.right, ya_), (xm, ya_), (xm, yt_), (vt.left, yt_)], end="open", dashed=True)
    d.label(xm + 8, ya_ + (yt_ - ya_) * 0.7, "creates")
    # VoiceSession and VoiceTranscriber use an AudioDevice
    xs = vt.right + 35
    ys, yd = vs.attr_y(1), ad.y + 30
    d.link([(vs.right, ys), (xs, ys), (xs, yd), (ad.right, yd)], end="open")
    d.label(vs.right + 5, ys - 12, "_audio_device")
    xt = ad.cx
    d.link([(xt, vt.bottom), (xt, ad.top)], end="open", dashed=True)
    d.label(xt + 8, (vt.bottom + ad.top) / 2, "uses")
    # SoundDeviceAudio implements AudioDevice
    d.link([(sd.cx, sd.top), (sd.cx, ad.bottom)], start="tri")
    return d


def build_all():
    for planned, tag in ((False, "implemented"), (True, "proposal")):
        figure1(planned).save("figure1_domain_%s.png" % tag, "figure1 " + tag)
        figure2(planned).save("figure2_application_%s.png" % tag, "figure2 " + tag)
        figure3(planned).save("figure3_interface_%s.png" % tag, "figure3 " + tag)


if __name__ == "__main__":
    build_all()
