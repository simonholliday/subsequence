"""The ``Sequencer`` - clock, scheduling, and MIDI delivery.

Owns the pulse clock, the event heap, and the output ports, turning scheduled
patterns and callbacks into timed MIDI messages.  ``Composition`` drives one
internally; you rarely construct it directly.
"""

import asyncio
import collections
import dataclasses
import heapq
import itertools
import datetime
import logging
import selectors
import sys
import threading
import time
import typing
import weakref

import mido

import subsequence.constants
import subsequence.constants.pulses
import subsequence.easing
import subsequence.event_emitter
import subsequence.held_notes
import subsequence.metre
import subsequence.midi_utils


logger = logging.getLogger(__name__)

# How far behind the clock may fall and still play through what it missed,
# pulse by pulse.  One beat: past that, working through the backlog is a burst
# of noise rather than music - eight hats in 0.2 ms after a one-second stall at
# 120 BPM.  So the internal clock carries on from where it stopped, just later
# (#3374), and the Link clock moves to where the session actually is (#2993).
_CATCH_UP_PULSES = 24

# The device a recorded tempo or metre marking belongs to: none of them.  Those
# describe the file, so they are saved on its first track whatever synths played
# (#3067).  Not an index, so it cannot collide with one.
CONDUCTOR = -1


@typing.runtime_checkable
class PatternLike (typing.Protocol):

	"""
	Protocol for pattern objects that can be scheduled.
	"""

	channel: int
	device: int
	length: float
	reschedule_lookahead: float
	steps: typing.Dict[int, typing.Any]
	_cycle_start_pulse: int


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		...


def _dispatch_rank (message_type: str, velocity: int) -> int:

	"""0 for a note-off (a note-on at velocity 0 is one), 2 for a note-on, 1 for everything else."""

	if message_type == 'note_off' or (message_type == 'note_on' and velocity == 0):
		return 0

	if message_type == 'note_on':
		return 2

	return 1


def _forward_identity (message: mido.Message, device: int) -> typing.Optional[typing.Tuple[typing.Any, ...]]:

	"""What makes two forwarded messages the same control, or None where every message matters.

	A control's later value replaces its earlier one; a note, or anything
	else forwarded, is an event in its own right and is always kept (#2967).
	"""

	if message.type == 'control_change':
		return (device, message.type, message.channel, message.control)

	if message.type in ('pitchwheel', 'aftertouch', 'program_change'):
		return (device, message.type, message.channel)

	if message.type == 'polytouch':
		return (device, message.type, message.channel, message.note)

	return None


def _can_sound (channel: typing.Any, note: typing.Any, velocity: typing.Any) -> bool:

	"""Whether a note-on with these values is a message MIDI can carry: a 0-15 channel and 0-127 note and velocity, all whole numbers.

	One that is not fails to send and never sounds, so nothing tracks it as
	sounding: a release built for it would fail in turn, and a stop that
	failed there would leave every valid note ringing (#2958).
	"""

	return all(
		isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= limit
		for value, limit in ((channel, 15), (note, 127), (velocity, 127))
	)


@dataclasses.dataclass (order=True)
class MidiEvent:

	"""
	Represents a MIDI event scheduled at a specific pulse.

	``sequence`` is a FIFO tie-breaker: when two events share a pulse, the
	one pushed first dispatches first.  Without it, ``heapq`` ordering of
	same-pulse events is undefined, which would break NRPN/RPN sequences
	(CC 99 → 98 → 6 → 38) and risk reordering bank-select-before-program-change.
	The Sequencer assigns ``sequence`` via its monotonic ``_event_counter``
	at push time (see ``Sequencer._push_event``); direct constructions in
	tests can leave it at the default.

	``rank`` comes first at a shared pulse, and follows from the message
	(#2791): note-offs go out first, then everything that sets a channel's
	state (bank select, program change, CCs, NRPN, pitch bend, SysEx, OSC),
	then note-ons.  So a note starts with the sound, controller values and
	bend it shares its moment with, and a note ending on that moment is
	released before the next begins.  It is set when the event is built and
	again when it is pushed (``Sequencer._push_event``).

	``priority`` orders events of one rank: lower first.  A tuning onset bend
	carries ``-1`` so it lands ahead of any other bend on its pulse;
	everything else stays at ``0``.
	"""

	pulse: int
	rank: int = dataclasses.field(init=False, default=1)
	message_type: str = dataclasses.field(compare=False)
	channel: int = dataclasses.field(compare=False)
	note: int = dataclasses.field(compare=False, default=0)
	velocity: int = dataclasses.field(compare=False, default=0)
	control: int = dataclasses.field(compare=False, default=0)
	value: int = dataclasses.field(compare=False, default=0)
	data: typing.Any = dataclasses.field(compare=False, default=None)
	device: int = dataclasses.field(compare=False, default=0)
	priority: int = 0
	sequence: int = 0

	# Which pattern placed this, so a teardown can tell its own notes from
	# everybody else's on the same channel (#2996).  Never compared, and never
	# printed: a pattern's repr is long and this is bookkeeping.
	owner: typing.Any = dataclasses.field(compare=False, default=None, repr=False)


	def __post_init__ (self) -> None:

		"""Place the event among others at its pulse by what it is."""

		self.rank = _dispatch_rank(self.message_type, self.velocity)


	def to_mido (self) -> typing.Optional[typing.Union[mido.Message, mido.MetaMessage]]:

		"""Convert this event to a mido.Message, or None if it's an internal type (like OSC)."""

		if self.message_type in ('note_on', 'note_off'):
			return mido.Message(
				self.message_type,
				channel = self.channel,
				note = self.note,
				velocity = self.velocity
			)

		if self.message_type == 'control_change':
			return mido.Message(
				'control_change',
				channel = self.channel,
				control = self.control,
				value = self.value
			)

		if self.message_type == 'pitchwheel':
			return mido.Message(
				'pitchwheel',
				channel = self.channel,
				pitch = self.value
			)

		if self.message_type == 'program_change':
			return mido.Message(
				'program_change',
				channel = self.channel,
				program = self.value
			)

		# Channel pressure and per-note pressure.  A forwarded one used to fall
		# past every branch here and come back None, which `_send_midi` reads as
		# "an internal type, skip it" — so a keyboard's pressure was dropped on
		# the way to the synth with nothing said (#3068).
		if self.message_type == 'aftertouch':
			return mido.Message(
				'aftertouch',
				channel = self.channel,
				value = self.value
			)

		if self.message_type == 'polytouch':
			return mido.Message(
				'polytouch',
				channel = self.channel,
				note = self.note,
				value = self.value
			)

		if self.message_type == 'sysex':
			return mido.Message(
				'sysex',
				data = self.data if self.data is not None else b''
			)

		return None


	@classmethod
	def from_mido (cls, pulse: int, msg: typing.Union[mido.Message, mido.MetaMessage], device: int = 0) -> "MidiEvent":

		"""Convert a mido.Message to a MidiEvent."""

		if msg.type == 'pitchwheel':
			return cls(
				pulse = pulse,
				message_type = 'pitchwheel',
				channel = msg.channel,
				value = msg.pitch,
				device = device,
			)

		if msg.type == 'control_change':
			return cls(
				pulse = pulse,
				message_type = 'control_change',
				channel = msg.channel,
				control = msg.control,
				value = msg.value,
				device = device,
			)

		# A program change carries its number as `program`, not `value`, so the
		# fallback below read 0 from it and `to_mido` wrote program 0 back out:
		# forwarding a patch change from a controller silently selected patch 0
		# on the synth (#3068).
		if msg.type == 'program_change':
			return cls(
				pulse = pulse,
				message_type = 'program_change',
				channel = msg.channel,
				value = msg.program,
				device = device,
			)

		return cls(
			pulse = pulse,
			message_type = msg.type,
			channel = getattr(msg, 'channel', 0),
			value = getattr(msg, 'value', 0),
			note = getattr(msg, 'note', 0),
			velocity = getattr(msg, 'velocity', 0),
			data = getattr(msg, 'data', None),
			control = getattr(msg, 'control', 0),
			device = device,
		)


@dataclasses.dataclass
class _MirrorTarget:

	"""A resolved fan-out destination - a ``(device, channel)`` plus an optional
	per-device ``drum_note_map`` used to re-resolve mirrored drum names.

	Constructed transiently inside ``schedule_pattern`` (never stored on the
	Pattern, never public) purely for ergonomic attribute access in the
	fan-out loops.  Stored mirror entries remain plain tuples - a dict-bearing
	entry would be unhashable and could not live in the ``set`` used by
	``_stop_pattern_notes``.
	"""

	device: int
	channel: int
	drum_note_map: typing.Optional[typing.Dict[str, int]] = None


def _to_target (entry: typing.Sequence[typing.Any]) -> _MirrorTarget:

	"""Coerce a stored mirror entry to a ``_MirrorTarget``.

	*entry* is ``(device, channel)`` or ``(device, channel, drum_note_map)`` -
	a tuple or list.  Branching on length here keeps the 2-vs-3 split in one
	place (and off the typed ``MirrorSpec`` union).
	"""

	drum_map = entry[2] if len(entry) == 3 else None
	return _MirrorTarget(entry[0], entry[1], drum_map)


def _destination_pitch (note: typing.Any, target: _MirrorTarget, primary: bool) -> typing.Optional[int]:

	"""Return the MIDI note to emit for *note* at *target*, or None to drop it.

	Drum names are resolved per destination: a destination that has no voice for
	the name stays silent (returns None) rather than sounding a wrong number.

	- A ``primary_unmapped`` note (its ``origin`` was absent from the pattern's
	  own map) has no real primary pitch - only a mirror whose map contains the
	  name voices it; the primary and raw (map-less) mirrors return None.
	- Otherwise the primary and raw 2-tuple mirrors copy ``note.pitch``; a
	  symbolic (map-bearing) mirror re-resolves ``note.origin`` through its own
	  map, dropping a named voice it lacks and copying an origin-less literal
	  pitch.
	"""

	if note.primary_unmapped:
		# No real primary note exists; only a mapping mirror can sound it.
		if primary or target.drum_note_map is None:
			return None
		if note.origin is not None and note.origin in target.drum_note_map:
			return target.drum_note_map[note.origin]
		return None

	if primary or target.drum_note_map is None:
		return typing.cast(int, note.pitch)

	if note.origin is not None:
		if note.origin in target.drum_note_map:
			return target.drum_note_map[note.origin]
		return None   # a named voice this device lacks → silent (not a wrong note)

	return typing.cast(int, note.pitch)


_RunResult = typing.TypeVar("_RunResult")


def new_event_loop () -> asyncio.AbstractEventLoop:

	"""Create an event loop that wakes the clock when it asked to be woken.

	The clock sleeps to within 1 ms of each pulse and spins the rest, so a
	sleep that overruns by more than that makes the pulse late.  On Linux the
	default loop waits in epoll, and CPython's epoll selector rounds a timeout
	up to whole milliseconds twice - once in Python, then again in C after a
	float conversion - so a wait that rounds to 13 or 18 ms asks the kernel for
	a millisecond more.  Tempos whose pulse lands the sleep there (130 and 180
	BPM among them) then run up to 1.5 ms late.  ``select()`` takes a
	microsecond timeout and overruns by kernel wake-up latency alone, so that
	is the selector used wherever epoll is the default.

	``select()`` cannot watch a descriptor numbered 1024 or above, which would
	matter only to a process holding about a thousand files open before the
	loop opens its sockets.  Other platforms keep their default loop: macOS's
	kqueue takes a nanosecond timeout, and Windows uses its proactor.
	"""

	epoll = getattr(selectors, "EpollSelector", None)

	if epoll is not None and selectors.DefaultSelector is epoll:
		return asyncio.SelectorEventLoop(selectors.SelectSelector())

	return asyncio.new_event_loop()


def run (main: typing.Coroutine[typing.Any, typing.Any, _RunResult]) -> _RunResult:

	"""Run *main* as ``asyncio.run`` would, on a loop from :func:`new_event_loop`.

	``Composition.play()`` and ``render()`` start this way.  Use it in place of
	``asyncio.run`` when driving a ``Sequencer`` directly, or its clock keeps
	the default loop's late wake-ups.
	"""

	if sys.version_info >= (3, 11):
		with asyncio.Runner(loop_factory = new_event_loop) as runner:
			return runner.run(main)

	# Python 3.10 has no Runner: these are the steps its asyncio.run takes.
	loop = new_event_loop()

	try:
		asyncio.set_event_loop(loop)
		return loop.run_until_complete(main)

	finally:
		try:
			_cancel_remaining_tasks(loop)
			loop.run_until_complete(loop.shutdown_asyncgens())
			loop.run_until_complete(loop.shutdown_default_executor())

		finally:
			asyncio.set_event_loop(None)
			loop.close()


def _cancel_remaining_tasks (loop: asyncio.AbstractEventLoop) -> None:

	"""Cancel and reap the tasks *loop* still holds, as ``asyncio.run`` does on 3.10."""

	remaining = asyncio.all_tasks(loop)

	if not remaining:
		return

	for task in remaining:
		task.cancel()

	loop.run_until_complete(asyncio.gather(*remaining, return_exceptions = True))

	for task in remaining:
		if not task.cancelled() and task.exception() is not None:
			loop.call_exception_handler({
				"message": "unhandled exception during shutdown",
				"exception": task.exception(),
				"task": task,
			})


@dataclasses.dataclass
class ScheduledPattern:

	"""
	Tracks a repeating pattern and its scheduling metadata.
	"""

	pattern: PatternLike
	cycle_start_pulse: int
	length_pulses: int
	lookahead_pulses: int
	next_reschedule_pulse: int


@dataclasses.dataclass
class ScheduledCallback:

	"""
	Tracks a repeating callback and its scheduling metadata.
	"""

	callback: typing.Callable[[int], typing.Any]
	cycle_start_pulse: int
	interval_pulses: int
	lookahead_pulses: int
	next_fire_pulse: int

	# The pulse this was originally scheduled against, kept so an external
	# Start can put it back exactly where a fresh start would (#3053).  It is
	# what tells the harmonic clock (scheduled one interval in, so it does not
	# fire at pulse 0) from an ordinary callback scheduled at 0, which does.
	initial_start_pulse: int = 0


@dataclasses.dataclass
class ScheduledCallbackSequence:

	"""Tracks a self-rescheduling callback whose firing interval varies per hop.

	The variable-interval counterpart to :class:`ScheduledCallback` - built
	for clocks that walk irregular spans (the harmonic clock under a bound
	progression).  Each fire targets a *boundary* pulse; the callback's
	return value sets the distance to the next boundary.

	Attributes:
		callback: Called with the boundary pulse it is preparing.  Returns
			the number of **beats** to the next boundary, or ``None`` to
			stop firing (the sequence is dropped from the queue).  May be
			sync or async.
		boundary_pulse: The pulse this fire prepares (the musical boundary,
			not the fire time).
		lookahead_pulses: How far before each boundary the callback fires.
		next_fire_pulse: When the next fire is due.
		initial_start_pulse: The first boundary it was scheduled against, kept
			so an external Start can put it back where a fresh start would
			(#3053).
	"""

	callback: typing.Callable[[int], typing.Union[typing.Optional[float], typing.Coroutine[typing.Any, typing.Any, typing.Optional[float]]]]
	boundary_pulse: int
	lookahead_pulses: int
	next_fire_pulse: int
	initial_start_pulse: int = 0


@dataclasses.dataclass
class BpmTransition:

	"""State for a gradual BPM transition."""

	start_bpm: float
	target_bpm: float
	total_pulses: int
	elapsed_pulses: int = 0
	easing_fn: typing.Callable[[float], float] = dataclasses.field(default=subsequence.easing.linear)


class Sequencer:

	"""
	The engine that drives Subsequence timing and MIDI output.
	
	The ``Sequencer`` maintains a stable clock (internal or external),
	handles the scheduling of MIDI events, and triggers pattern rebuilds.
	"""

	# How often a paused clock loop checks whether it has been resumed.  Resume
	# latency is bounded by this, and 5 ms is comfortably inside one pulse at any
	# usable tempo (20.8 ms at 120 BPM, 24 PPQN) — so a resumed transport lands
	# on the same pulse it would have without the polling.
	_PAUSE_POLL_SECONDS: float = 0.005

	# A silence longer than this between clock ticks is the master stopping,
	# not slowing down, so the tempo window starts again rather than averaging
	# across it.  Half a second a tick is 5 BPM at 24 PPQN — an order of
	# magnitude below anything anybody plays, so no real tempo trips it.
	_CLOCK_GAP_SECONDS: float = 0.5

	# How far past the last deferred send for a device the next one is held, so
	# that two clamped to the same floor keep their dispatch order.  A
	# microsecond: below MIDI's own resolution, and far below the loop's.
	_SEND_ORDER_EPSILON: float = 1e-6

	def __init__ (
		self,
		output_device_name: typing.Optional[str] = None,
		initial_bpm: float = 125,
		time_signature: typing.Tuple[int, int] = (4, 4),
		input_device_name: typing.Optional[str] = None,
		clock_follow: bool = False,
		clock_output: bool = False,
		record: bool = False,
		record_filename: typing.Optional[str] = None,
		spin_wait: bool = True,
		_jitter_log: typing.Optional[typing.List[float]] = None
	) -> None:

		"""Initialise the sequencer with MIDI devices and initial BPM.

		Parameters:
			output_device_name: MIDI output device name. When omitted, auto-discovers
				available devices - uses the only device if one is found, or prompts
				the user to choose if multiple are available.
			initial_bpm: Tempo in BPM (ignored when clock_follow is True)
			time_signature: The metre as ``(beats, unit)``.  A bar lasts
				``beats × 4 / unit`` quarter notes, and the beat counter counts
				the unit.  The unit must be 1, 2, 4, 8, 16 or 32.
			input_device_name: Optional MIDI input device name for clock/transport
			clock_follow: When True, follow external MIDI clock instead of internal clock
			clock_output: When True, send MIDI timing clock (0xF8), start (0xFA), and
				stop (0xFC) messages so connected hardware can sync to Subsequence's
				tempo.  Mutually exclusive with ``clock_follow`` (ignored when both
				are set, to prevent feedback loops).
			record: When True, record all MIDI events to a file.
			record_filename: Optional filename for the recording (defaults to timestamp).
			spin_wait: When True (default), use a hybrid sleep+spin strategy for the
				final sub-millisecond of each pulse interval.  This significantly
				reduces clock jitter at the cost of ~1–5% extra CPU.  Set to False
				to use pure ``asyncio.sleep()`` (lower CPU, higher jitter).
			_jitter_log: Optional list to append per-pulse jitter values (seconds)
				to during playback.  Intended for the clock jitter benchmark - not
				for general use.
		"""

		if clock_follow and input_device_name is None:
			raise ValueError("clock_follow=True requires an input_device_name")

		self.output_device_name = output_device_name
		self.input_device_name = input_device_name
		self.time_signature = subsequence.metre.check(time_signature)
		self.clock_follow = clock_follow
		self.clock_device_idx: int = 0
		self.clock_output = clock_output and not clock_follow
		self.pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE
		# What the beat counter counts: the time signature's written unit.
		self._pulses_per_unit = subsequence.metre.pulses_per_unit(self.time_signature, self.pulses_per_beat)

		# Recording state
		self.recording = record
		self.record_filename = record_filename
		# (pulse, message, device).  The device is which output port the message
		# was sent to, so a session driving several synths saves as several
		# tracks instead of merging them all onto one (#3067).  CONDUCTOR is the
		# device for a tempo or metre marking, which belongs to the file rather
		# than to any one synth.
		self.recorded_events: typing.List[typing.Tuple[float, typing.Union[mido.Message, mido.MetaMessage], int]] = []

		# Device names as they were when each device first recorded something.
		# Captured then rather than read at save time because ``stop()`` closes
		# and clears the registry before it saves, so by then there is nothing
		# left to ask (#3067).
		self._recorded_device_names: typing.Dict[int, str] = {}

		# Render mode: run as fast as possible and stop after render_bars or render_max_seconds.
		# Both limits are optional — at least one must be set (enforced in Composition.render).
		self.render_mode: bool = False
		self.render_bars: int = 0                          # 0 = no bar limit
		self.render_max_seconds: typing.Optional[float] = None  # None = no time limit
		self._render_elapsed_seconds: float = 0.0


		# CC input mapping — populated from Composition.cc_map()
		self.cc_mappings: typing.List[typing.Dict[str, typing.Any]] = []
		# CC forwarding — populated from Composition.cc_forward()
		self.cc_forwards: typing.List[typing.Dict[str, typing.Any]] = []
		# Buffer for queued CC forwards: deque of (pulse, mido.Message) tuples.
		# Appended on the mido callback thread; drained on the event loop thread.
		self._forward_buffer: collections.deque = collections.deque()
		# Shared reference to composition.data so CC mappings can update it
		self._composition_data: typing.Dict[str, typing.Any] = {}

		# Held-note input — populated from Composition.note_input().
		# The tracker (created in _run when note_input was declared) and a buffer
		# of raw (is_on, pitch, velocity, perf_counter) note events.  The buffer is
		# appended on the mido callback thread and drained on the loop thread in
		# _advance_pulse, so all tracker state stays single-threaded — no lock.
		self._held_notes: typing.Optional[subsequence.held_notes.HeldNotes] = None
		self._note_input_buffer: collections.deque = collections.deque()
		self._note_input_channel: typing.Optional[int] = None  # None = any channel
		self._note_input_device: typing.Optional[int] = None   # None = any input device

		# Ableton Link clock — set by Composition._run() when comp.link() was called.
		# Must be initialized before set_bpm() is called below.
		self._link_clock: typing.Optional[typing.Any] = None

		# Multi-device MIDI port registries.
		# Output device 0 is always the primary/default device.
		self._output_devices: subsequence.midi_utils.MidiDeviceRegistry = subsequence.midi_utils.MidiDeviceRegistry()
		self._input_devices: subsequence.midi_utils.MidiDeviceRegistry = subsequence.midi_utils.MidiDeviceRegistry()

		# Internal state initialization (needed before set_bpm)
		self._midi_input_queue: typing.Optional[asyncio.Queue] = None
		self._input_loop: typing.Optional[asyncio.AbstractEventLoop] = None
		self._event_loop: typing.Optional[asyncio.AbstractEventLoop] = None
		self._clock_tick_times: typing.List[float] = []

		# True while an external transport is not running, so incoming clock
		# ticks prime the BPM estimate but advance nothing.  It covers both of
		# the moments that look the same from here: before the first Start, and
		# after a Stop that holds the position (#3053).
		self._transport_held: bool = False
		# Set by a Composition: put the piece back to its opening when an
		# external Start arrives (#3089).  A bare Sequencer has no form or
		# harmony to rewind, so it leaves this None.
		self.on_restart: typing.Optional[typing.Callable[[], typing.Awaitable[None]]] = None

		self.event_queue: typing.List[MidiEvent] = []
		self.task: typing.Optional[asyncio.Task] = None
		self.start_time = 0.0
		self.pulse_count = 0
		self.current_bar: int = -1
		self.current_beat: int = -1
		self.active_notes: typing.Set[typing.Tuple[int, int, int]] = set()  # (device, channel, note)

		# Who struck each sounding note.  A weak map, so a torn-down pattern
		# that left a note hanging is still collectable (#2996).
		self._note_owner: "weakref.WeakValueDictionary[typing.Tuple[int, int, int], typing.Any]" = weakref.WeakValueDictionary()

		# The drones each pattern has scheduled on and not yet off, per
		# destination, so one left on a destination the pattern stops playing
		# to (its channel changed, a mirror went) can be released there.
		self._held_drones: "weakref.WeakKeyDictionary[typing.Any, typing.Set[typing.Tuple[int, int, int]]]" = weakref.WeakKeyDictionary()

		# Transport pause.  ``pause()``/``resume()`` only flip _paused — a plain
		# bool so they are safe to call from a UI or OSC thread — and the clock
		# loop does the work when it notices, which is also what makes the
		# "pause"/"resume" events report the transport's real state rather than
		# that a button was pressed.  _paused_seconds accumulates the total held
		# time for diagnostics; start_time is deliberately never shifted.
		self._paused: bool = False
		self._paused_seconds: float = 0.0

		# When the current hold began, for the external-transport path.  The
		# internal clock's _hold_while_paused keeps its own local instead: it
		# blocks for the whole hold, so it has somewhere to put one.
		self._paused_from: float = 0.0

		# When the last deferred send for each device is due, on the loop's own
		# clock.  Nothing for a device may be sent before this, so a latency
		# change mid-piece cannot let a message overtake one already waiting
		# (#3069).
		self._send_floor: typing.Dict[int, float] = {}

		# Device latency compensation: cached max across all output devices, and
		# the set of in-flight deferred sends (call_later handles) awaiting their
		# per-device offset.  See _dispatch_with_compensation() and stop().
		self._max_device_latency_ms: float = 0.0
		self._pending_sends: typing.Set[asyncio.TimerHandle] = set()

		# Strong references to fire-and-forget bar/beat/event tasks.  Without
		# retaining them asyncio holds only a weak reference and the task can be
		# garbage-collected mid-flight; the done-callback also surfaces exceptions
		# that a bare create_task would otherwise swallow until GC.
		self._background_tasks: typing.Set[asyncio.Task] = set()

		self.queue_lock = asyncio.Lock()
		self.pattern_lock = asyncio.Lock()
		self.reschedule_queue: typing.List[typing.Tuple[int, int, ScheduledPattern]] = []
		self._reschedule_counter = itertools.count()
		self.events = subsequence.event_emitter.EventEmitter()
		self.callback_lock = asyncio.Lock()
		self.callback_queue: typing.List[typing.Tuple[int, int, ScheduledCallback]] = []
		self._callback_counter = itertools.count()

		# Variable-interval callback sequences share callback_lock; they fire
		# after the fixed callbacks at the same pulse (see
		# _maybe_reschedule_patterns), preserving form-before-harmony ordering.
		self.callback_sequence_queue: typing.List[typing.Tuple[int, int, ScheduledCallbackSequence]] = []

		# FIFO tie-breaker for same-pulse MidiEvents in event_queue.  Without
		# it, ``heapq`` ordering of equal-pulse events is undefined, which
		# breaks NRPN/RPN bursts (CC 99 → 98 → 6 → 38 must stay in order).
		self._event_counter = itertools.count()

		# Serialises actual port writes.  Every send runs on the event-loop
		# thread EXCEPT instant-mode cc_forward, which fires on the mido input
		# callback thread — without this lock the two threads could interleave
		# bytes on the same port and corrupt a multi-byte message.
		self._port_send_lock = threading.Lock()

		self.data: typing.Dict[str, typing.Any] = {}

		# Timing variables
		self.current_bpm: float = 0
		self.seconds_per_beat = 0.0
		self.seconds_per_pulse = 0.0
		self.running = False
		# Whether stop() has already done its cleanup.  It is the flag, not the
		# port registry, that makes stop() idempotent: a render that opened no
		# port still has a file to write, inputs to close and a stop event to
		# fire (#2994).
		self._stopped = False
		self._bpm_transition: typing.Optional[BpmTransition] = None
		self._spin_wait: bool = spin_wait
		# Spin threshold: sleep all the way to this many seconds before the target,
		# then busy-wait for the remainder.  1ms is enough to absorb OS wakeup latency
		# while keeping spin time short enough not to starve the event loop.
		self._spin_threshold: float = 0.001
		self._jitter_log: typing.Optional[typing.List[float]] = _jitter_log

		self.set_bpm(initial_bpm)

		# The port is NOT opened here.  Building a Composition must not open a
		# device or prompt for one — a render has no business touching the
		# rig, and it is render() that says so, after the Sequencer exists
		# (#2995).  start() opens it, and Composition._run opens it earlier
		# still, so the primary holds device 0 before any extra is added.

		# OSC server reference — set by Composition after osc_server.start()
		self.osc_server: typing.Optional[typing.Any] = None

	# ------------------------------------------------------------------
	# Backward-compatible properties: midi_out / midi_in
	# External code and tests may reference these directly.  They always
	# resolve to device 0 of the respective registry.
	# ------------------------------------------------------------------

	@property
	def midi_out (self) -> typing.Optional[typing.Any]:
		"""Return the primary output port (device 0), or None."""
		return self._output_devices.get(0)

	@midi_out.setter
	def midi_out (self, value: typing.Optional[typing.Any]) -> None:
		"""Allow test code to inject a fake output port as device 0."""
		if value is None:
			return
		if len(self._output_devices) == 0:
			self._output_devices.add("default", value)
		else:
			self._output_devices.replace(0, value)

	@property
	def midi_in (self) -> typing.Optional[typing.Any]:
		"""Return the primary input port (device 0), or None."""
		return self._input_devices.get(0)

	@midi_in.setter
	def midi_in (self, value: typing.Optional[typing.Any]) -> None:
		"""Allow test code to inject a fake input port as device 0."""
		if value is None:
			return
		if len(self._input_devices) == 0:
			self._input_devices.add("default", value)
		else:
			self._input_devices.replace(0, value)

	def add_output_device (self, name: str, port: typing.Any, latency_ms: float = 0.0) -> int:
		"""Register an additional output device.  Returns the device index.

		*latency_ms* is the device's physical output latency for compensation
		(see :meth:`set_device_latency`).
		"""
		idx = self._output_devices.add(name, port, latency_ms)
		self._max_device_latency_ms = self._output_devices.max_latency()
		return idx

	def add_input_device (self, name: str, port: typing.Any) -> int:
		"""Register an additional input device.  Returns the device index."""
		return self._input_devices.add(name, port)

	def set_device_latency (self, device: subsequence.midi_utils.DeviceId, latency_ms: float) -> None:

		"""Set an output device's physical latency (ms) for delay compensation.

		Latency is normalised engine-wide: the slowest device plays at its
		logical time and every faster device's output is deferred by
		``max_latency − its_latency`` so all devices sound together.  See
		:meth:`_dispatch_with_compensation`.

		Parameters:
			device: Output device id (int index, name str, or None for device 0).
			latency_ms: Non-negative physical output latency in milliseconds.
				Raises ``ValueError`` if negative or the device is unknown.
		"""

		self._output_devices.set_latency(device, latency_ms)
		self._max_device_latency_ms = self._output_devices.max_latency()

	def _record_event (
		self,
		pulse: int,
		message: typing.Union[mido.Message, mido.MetaMessage],
		device: int = CONDUCTOR,
	) -> None:

		"""Record a MIDI message with an absolute pulse timestamp for later export.

		*device* is the output port the message went to, and decides which track
		it is saved on.  It defaults to :data:`CONDUCTOR` - the tempo and metre
		markings, which belong to the file rather than to a synth.
		"""

		if not self.recording:
			return

		# Ask for the name while the registry still has it: stop() closes the
		# ports before it saves, so a name read at save time is always None.
		if device != CONDUCTOR and device not in self._recorded_device_names:
			name = self._output_devices.name_of(device)
			if name is not None:
				self._recorded_device_names[device] = name

		self.recorded_events.append((float(pulse), message, device))

	def _record_opening (self) -> None:

		"""Open a recording with its metre and the tempo playback starts at, at pulse 0.

		A DAW takes both from the file, and without them imports at its own
		tempo and in 4/4, so every bar line after the first lands in the wrong
		place (#2719).  A tempo set before playback - the constructor's own
		``set_bpm`` among them - was recorded at pulse 0 already; the opening
		replaces it with the tempo playback actually starts at, so the file
		states it once.

		The metre is written as declared: a ``(7, 8)`` bar is seven eighth notes
		long, so a DAW draws its bar lines where they are played (#2738).
		"""

		if not self.recording:
			return

		self.recorded_events = [
			(pulse, message, device) for pulse, message, device in self.recorded_events
			if not (pulse == 0 and message.is_meta and message.type == 'set_tempo')
		]

		beats, unit = self.time_signature

		self.recorded_events[:0] = [
			(0.0, mido.MetaMessage('time_signature', numerator=beats, denominator=unit), CONDUCTOR),
			(0.0, mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(self.current_bpm)), CONDUCTOR),
		]


	def save_recording (self) -> None:

		"""Save the recorded session to a MIDI file, a track per output device.

		Every device used to share one track, so a session driving two synths
		saved as if it were one: two parts on channel 0 of different synths came
		back as two overlapping note-ons on one channel, which no importer can
		pair with the right note-offs (#3067).  A track apiece keeps them
		separate and lets a DAW route each one back where it came from.

		**The first device shares track 0 with the tempo and metre**, rather
		than there being a conductor track of its own.  That keeps a
		single-device recording - which is nearly all of them - exactly the
		one-track file it has always been, so nothing downstream changes for a
		piece that drives one synth.

		Tracks are named after their devices when there is more than one, so an
		import reads "Integra-7" rather than "Track 2".
		"""

		if not self.recording or not self.recorded_events:
			return

		if self.record_filename:
			filename = self.record_filename
		else:
			now = datetime.datetime.now()
			filename = now.strftime("session_%Y%m%d_%H%M%S.mid")

		logger.info(f"Saving MIDI recording ({len(self.recorded_events)} events) to {filename}...")

		mid = mido.MidiFile(type=1)

		# Resolution (ticks per beat). Standard is 480.
		# Subsequence uses 24 PPQN internal.
		# To get 480 PPQN output without losing precision, we scale up by 20.
		ticks_per_pulse = 20
		mid.ticks_per_beat = 480

		# Sort events by pulse just in case
		self.recorded_events.sort(key=lambda x: x[0])

		# Which devices actually recorded anything, lowest first.  The lowest
		# takes track 0 alongside the conductor's markings; the rest follow.
		devices = sorted({
			device for _, _, device in self.recorded_events if device != CONDUCTOR
		})

		first_device = devices[0] if devices else CONDUCTOR
		later_devices = devices[1:]

		track_of = {CONDUCTOR: 0, first_device: 0}
		track_of.update({device: index + 1 for index, device in enumerate(later_devices)})

		tracks = [mido.MidiTrack() for _ in range(1 + len(later_devices))]

		for track in tracks:
			mid.tracks.append(track)

		if later_devices:
			for device in [first_device] + later_devices:
				name = self._recorded_device_names.get(device)
				if name is not None:
					tracks[track_of[device]].append(mido.MetaMessage('track_name', name=name, time=0))

		# Each track carries its own delta times, so each needs its own clock.
		last_pulse = dict.fromkeys(range(len(tracks)), 0.0)

		for pulse, message, device in self.recorded_events:

			# An event recorded before the session's start sounds at its start.
			# Clamping the *delta* instead left `last_pulse` negative, so every
			# event after it — the tempo and the time signature among them —
			# moved later by as much as the stray event was early (#3005).
			pulse = max(0.0, pulse)

			index = track_of.get(device, 0)

			delta_pulses = pulse - last_pulse[index]
			delta_ticks = int(delta_pulses * ticks_per_pulse)

			# Ensure delta is non-negative (floating point jitter?)
			if delta_ticks < 0:
				delta_ticks = 0

			message.time = delta_ticks
			tracks[index].append(message)

			last_pulse[index] = pulse

		# The file ends where playback stopped, not at its last event, so a
		# render of N bars is N bars long in a DAW even when its last bar ends
		# in silence.  A recording saved without playing ends at its last event.
		# Every track is closed at that same point, or a DAW reads the shorter
		# ones as the piece ending early on those synths.
		end_pulse = max(list(last_pulse.values()) + [float(self.pulse_count)])

		for index, track in enumerate(tracks):
			track.append(mido.MetaMessage(
				'end_of_track', time=int((end_pulse - last_pulse[index]) * ticks_per_pulse)
			))

		try:
			mid.save(filename)
			logger.info(f"Saved {filename}")
		except Exception as e:
			logger.error(f"Failed to save MIDI recording: {e}")

	def disable_spin_wait (self) -> None:

		"""Disable the hybrid sleep+spin timing strategy.

		By default the sequencer busy-waits for the final sub-millisecond of each
		pulse interval to minimise clock jitter.  Call this to revert to pure
		``asyncio.sleep()`` - lower CPU usage at the cost of higher jitter: a median of
		about 0.4 ms on Linux, against 1 μs with spin-wait on (see the README's
		Performance section).

		Can also be set at construction time: ``Sequencer(spin_wait=False)``.
		"""

		self._spin_wait = False


	def set_bpm (self, bpm: float) -> None:

		"""
		Instantly change the tempo.

		Note: If ``clock_follow`` is enabled and the sequencer is running,
		this method will be ignored as the tempo is slaved to the external source.
		When Ableton Link is active, the new BPM is proposed to the Link network
		instead of being applied locally - the network-authoritative tempo is
		then picked up on the next pulse.
		"""

		# Validate BEFORE the Link branch — a zero/negative tempo must never
		# be proposed to the whole Link session.
		if bpm <= 0:
			raise ValueError("BPM must be positive")

		if self.clock_follow and self.running:
			logger.info("BPM is controlled by external clock - set_bpm() ignored")
			return

		if self._link_clock is not None and self.running:
			self._link_clock.request_tempo(bpm)
			logger.info(f"BPM {bpm:.2f} proposed to Ableton Link session")
			return

		# The clock reads the tempo and the ramp several times within one pulse,
		# on its own loop.  Changed from another thread in between, the ramp
		# vanished under it and the clock task died, which stops the music
		# (#3381) - so the change is made on that loop.
		self._on_the_clock(self._apply_bpm, bpm)

	def _apply_bpm (self, bpm: float) -> None:

		"""Set the tempo now, ending any ramp: on the clock's loop, or before it runs."""

		self._bpm_transition = None
		self.current_bpm = bpm
		self.seconds_per_beat = 60.0 / self.current_bpm
		self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat

		logger.info(f"BPM set to {self.current_bpm:.2f}")

		if self.recording:
			tempo = mido.bpm2tempo(self.current_bpm)
			self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=tempo))

	def _on_the_clock (self, change: typing.Callable[..., typing.Any], *args: typing.Any) -> None:

		"""Make a change to what the clock reads on the clock's own loop (#3381).

		On that loop, or with no loop running - before ``play()``, or after it
		ends - the change is made at once.  From any other thread (a synchronous
		``schedule()`` function's executor thread, or one a performer starts) it
		is handed to the loop, which makes it between pulses, in the order the
		calls arrived.  Anything the clock reads more than once within a pulse
		must only ever change here.
		"""

		loop = self._event_loop

		try:
			on_loop = loop is not None and asyncio.get_running_loop() is loop
		except RuntimeError:
			on_loop = False

		if loop is not None and loop.is_running() and not on_loop:
			loop.call_soon_threadsafe(change, *args)
		else:
			change(*args)


	def set_target_bpm (self, target_bpm: float, bars: int, shape: typing.Union[str, subsequence.easing.EasingFn] = "linear") -> None:

		"""
		Smoothly transition to a new tempo over a fixed number of bars.

		Parameters:
			target_bpm: The BPM to ramp toward.
			bars: Duration of the transition in bars.
			shape: Easing curve - a name string (e.g. ``"ease_in_out"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       ``"ease_in_out"`` or ``"s_curve"`` are recommended for natural-
			       sounding tempo changes.  See :mod:`subsequence.easing`.

		Note:
			When Ableton Link is active the shared network tempo is authoritative,
			so a local ramp cannot be honoured - this call is ignored.  Use
			``set_bpm()`` to propose a new tempo to the Link session instead.
		"""

		if self.clock_follow and self.running:
			logger.info("BPM is controlled by external clock - set_target_bpm() ignored")
			return

		if self._link_clock is not None and self.running:
			logger.info("Tempo is controlled by the Ableton Link session - set_target_bpm() ramp ignored; use set_bpm() to propose a new Link tempo")
			return

		if target_bpm <= 0:
			raise ValueError("Target BPM must be positive")

		if bars <= 0:
			raise ValueError("Transition bars must be positive")

		total_pulses = bars * subsequence.metre.pulses_per_bar(self.time_signature, self.pulses_per_beat)

		# Resolved here so an unknown shape is heard by the caller; the ramp
		# itself starts on the clock's loop, as a tempo change does (#3381).
		easing_fn = subsequence.easing.get_easing(shape)

		self._on_the_clock(self._begin_transition, target_bpm, total_pulses, easing_fn, f"over {bars} bars ({shape!r})")

	def _begin_transition (self, target_bpm: float, total_pulses: int, easing_fn: subsequence.easing.EasingFn, described: str) -> None:

		"""Start a ramp from the tempo as it is now: on the clock's loop, or before it runs."""

		self._bpm_transition = BpmTransition(
			start_bpm=self.current_bpm,
			target_bpm=target_bpm,
			total_pulses=total_pulses,
			easing_fn=easing_fn
		)

		logger.info(f"BPM transition: {self.current_bpm:.2f} → {target_bpm:.2f} {described}")


	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a named event.
		"""

		self.events.on(event_name, callback)


	def _init_midi_output (self) -> None:

		"""Initialise the primary MIDI output port (device 0).

		When ``output_device_name`` was provided, opens that device directly.
		When omitted, auto-discovers available devices: uses the only one if
		exactly one is found, or prompts the user to choose if several exist.
		"""

		device_name, midi_out = subsequence.midi_utils.select_output_device(self.output_device_name)

		if device_name and midi_out is not None:
			self.output_device_name = device_name
			self._output_devices.add(device_name, midi_out)

		elif self.output_device_name:
			# The primary holds index 0 even when it does not open, so a second
			# device is never promoted into its place and a part written for
			# the drum machine does not arrive at the lead synth (#2997).
			logger.warning(
				"Output device '%s' did not open - it keeps device 0 and stays silent, "
				"so every other device keeps its own number.",
				self.output_device_name,
			)
			self._output_devices.add(self.output_device_name, None)


	def _open_midi_inputs (self) -> None:

		"""
		Set up the internal event loops and MIDI input ports.

		This is called automatically by start(), but may be called manually
		by Composition._run() earlier in the startup sequence to ensure
		MIDI CC configuration is shared before ports begin background draining.
		"""

		# A render reaches no device (#2995), inputs included (#3485).  It
		# ignores an input's clock, and a control arriving mid-render would
		# change the file - and resolving the name refused to render at all
		# a piece whose controller was not plugged in.
		if self.render_mode:
			return

		if self.input_device_name is not None and self._midi_input_queue is None:
			self._input_loop = asyncio.get_running_loop()
			self._midi_input_queue = asyncio.Queue()
			self._init_midi_input()


	def _init_midi_input (self) -> None:

		"""Initialise the primary MIDI input port (device 0) with a callback."""

		if self.input_device_name is None:
			return

		callback = self._make_input_callback(0)
		device_name, midi_in = subsequence.midi_utils.select_input_device(self.input_device_name, callback)

		if device_name and midi_in is not None:
			self.input_device_name = device_name
			self._input_devices.add(device_name, midi_in)

	def _make_input_callback (self, device_idx: int) -> typing.Callable:
		"""Return a mido callback closure that tags messages with *device_idx*."""

		def _callback (message: typing.Any) -> None:
			self._on_midi_input(message, device_idx)

		return _callback


	def _on_midi_input (self, message: typing.Any, device_idx: int = 0) -> None:

		"""Handle incoming MIDI messages from the input port callback thread.

		This runs in mido's callback thread. Clock/transport messages are
		forwarded to the asyncio event loop via call_soon_threadsafe.

		CC input mappings are applied immediately here.  Single dict writes
		are safe from a non-asyncio thread under CPython's GIL.

		Parameters:
			message: The incoming mido.Message.
			device_idx: Index of the input device this message arrived on (0 = primary).
		"""

		if self._midi_input_queue is None or self._input_loop is None:
			return

		# The queue feeds only the external-clock loop, so enqueue only when
		# following: with the internal clock nothing ever drains it, and a
		# synced device's 24-ticks-per-beat clock would grow it forever.
		if self.clock_follow:
			# Stamp the arrival HERE, on the port's own callback thread, which
			# is the only place that knows when the message actually came off
			# the cable.  The loop used to take the time when it got round to
			# reading the message, so every delay between the two — a rebuild,
			# a busy callback, an ordinary scheduling hiccup — was measured as
			# a tempo change and written into the recording (#3066).
			self._input_loop.call_soon_threadsafe(
				self._midi_input_queue.put_nowait, (device_idx, message, time.perf_counter())
			)

		# Apply CC input mappings: map incoming CC values to composition.data.
		if message.type == 'control_change' and self.cc_mappings:
			for mapping in self.cc_mappings:
				if message.control != mapping['cc']:
					continue
				ch = mapping.get('channel')
				if ch is not None and message.channel != ch:
					continue
				# Filter by input device if specified (None = any device).
				in_dev = mapping.get('input_device')
				if in_dev is not None and device_idx != in_dev:
					continue
				scaled = mapping['min_val'] + (message.value / 127.0) * (mapping['max_val'] - mapping['min_val'])
				self._composition_data[mapping['data_key']] = scaled

		# Apply CC forwards: route incoming CC to MIDI output in real-time.
		if message.type == 'control_change' and self.cc_forwards:
			for fwd in self.cc_forwards:
				if message.control != fwd['cc']:
					continue
				ch = fwd.get('channel')
				if ch is not None and message.channel != ch:
					continue
				# Filter by input device if specified (None = any device).
				in_dev = fwd.get('input_device')
				if in_dev is not None and device_idx != in_dev:
					continue
				try:
					out_msg = fwd['transform'](message.value, message.channel)
				except Exception:
					logger.exception("CC forward transform failed")
					continue
				if out_msg is None:
					continue
				if fwd['mode'] == 'instant':
					# Route to the specified output device (default: device 0).
					out_dev = fwd.get('output_device', 0)
					port = self._output_devices.get(out_dev)
					if port is not None:
						try:
							# Instant mode fires on the mido callback thread, so the
							# send must take the lock the loop thread also holds.
							self._locked_send(port, out_msg)
						except Exception:
							logger.exception("CC forward send failed")
				else:
					# Queued: buffer for drain in _process_pulse on the event loop
					# thread.  The output device travels with the message so the
					# drain can route it (dropping it sent everything to device 0).
					out_dev = fwd.get('output_device')
					self._forward_buffer.append((self.pulse_count, out_msg, 0 if out_dev is None else out_dev))

		# Buffer incoming note on/off for the held-note tracker.  Only the
		# GIL-atomic deque.append happens here; the tracker is updated when the
		# loop thread drains the buffer in _advance_pulse.
		if self._held_notes is not None and message.type in ('note_on', 'note_off'):
			if self._note_input_channel is not None and message.channel != self._note_input_channel:
				return
			if self._note_input_device is not None and device_idx != self._note_input_device:
				return
			# A note_on with velocity 0 is the running-status form of note-off.
			if message.type == 'note_on' and message.velocity > 0:
				self._note_input_buffer.append((True, message.note, message.velocity, time.perf_counter()))
			else:
				self._note_input_buffer.append((False, message.note, 0, time.perf_counter()))



	def _estimate_bpm (self, tick_time: float) -> None:

		"""Estimate BPM from recent MIDI clock tick arrival times, for display and recording.

		*tick_time* is when the tick came off the cable, stamped on the input
		port's callback thread - not when this loop got round to it (#3066).

		A silence is not a slow tempo.  The averaging window is a beat wide, so
		a master that stops sending and starts again leaves a window straddling
		the gap: a two-second silence had a steady 120 BPM master reading
		**23 BPM for 23 ticks**, and a longer one reads 0.  A gap therefore
		starts the window again rather than being averaged into it.
		"""

		if self._clock_tick_times and tick_time - self._clock_tick_times[-1] > self._CLOCK_GAP_SECONDS:
			# The cable went quiet.  Whatever comes next is a fresh measurement,
			# and the tempo stands where it was until there is enough of one.
			self._clock_tick_times = [tick_time]
			return

		self._clock_tick_times.append(tick_time)

		# Keep last 48 ticks (2 beats) for averaging.
		if len(self._clock_tick_times) > 48:
			self._clock_tick_times = self._clock_tick_times[-48:]

		if len(self._clock_tick_times) >= 24:
			# Average interval over last 24 ticks (1 beat).
			recent = self._clock_tick_times[-24:]
			interval = (recent[-1] - recent[0]) / (len(recent) - 1)

			if interval > 0:
				new_bpm = int(round(60.0 / (interval * self.pulses_per_beat)))

				# The review's "current_bpm reads 0 after a gap" is fixed by the
				# reset above rather than by a guard here, and that is why there
				# is none: every interval left in the window is at most
				# _CLOCK_GAP_SECONDS, so the mean is too, and the slowest tempo
				# this can now produce is 5 BPM.  Zero is unreachable.  A guard
				# for it was written and then removed when a break for it failed
				# nothing (#3066).

				# Record tempo changes so a clock-following session's .mid
				# plays back at the external tempo, not the constructor BPM.
				# Integer rounding above already filters tick jitter.
				if self.recording and new_bpm != self.current_bpm and new_bpm > 0:
					self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(new_bpm)))

				self.current_bpm = new_bpm


	def _get_schedule_timing (self, length_beats: float, lookahead_beats: float) -> typing.Tuple[int, int]:

		"""
		Convert schedule length and reschedule lookahead from beats to pulses.
		"""

		if length_beats <= 0:
			raise ValueError("Schedule length must be positive")

		if lookahead_beats < 0:
			raise ValueError("Reschedule lookahead cannot be negative")

		length_pulses = subsequence.constants.pulses.beats_to_pulses(length_beats, self.pulses_per_beat)
		lookahead_pulses = subsequence.constants.pulses.beats_to_pulses(lookahead_beats, self.pulses_per_beat)

		# Compared in pulses, not beats: five triplet eighths come to
		# 1.6666666666666665 beats, a hair under the 1.6666666666666667 a
		# lookahead of 5/3 is written as, and a float comparison would refuse a
		# length the clock can schedule exactly.
		if lookahead_pulses > length_pulses:
			raise ValueError(
				f"A reschedule_lookahead of {lookahead_beats:g} beats cannot exceed the {length_beats:g} beats it repeats over - "
				f"set reschedule_lookahead= to {length_beats:g} or less"
			)

		if length_pulses <= 0:
			raise ValueError("Schedule length must be at least one pulse")

		return length_pulses, lookahead_pulses


	def _get_pattern_timing (self, pattern: PatternLike) -> typing.Tuple[int, int]:

		"""
		Convert pattern length and reschedule lookahead from beats to pulses.
		"""

		return self._get_schedule_timing(pattern.length, pattern.reschedule_lookahead)


	def _push_event (self, event: MidiEvent, owner: typing.Any = None) -> None:

		"""Push a MidiEvent onto the queue, stamping a FIFO tie-breaker.

		The ``sequence`` field guarantees that events of one rank sharing a
		``pulse`` dispatch in insertion order - required for NRPN/RPN bursts
		and Bank Select before Program Change.  The rank is re-read here, so an
		event altered after it was built still sorts by what it now is.

		*owner*, when given, is the pattern this event belongs to - what lets
		``unregister()`` release its notes without cutting a neighbour's on the
		same channel (#2996).
		"""

		if owner is not None:
			event.owner = owner

		event.rank = _dispatch_rank(event.message_type, event.velocity)
		event.sequence = next(self._event_counter)
		heapq.heappush(self.event_queue, event)


	def _remember_owner (self, event: MidiEvent) -> None:

		"""Record which pattern a sounding note belongs to, where one is known.

		A note struck by ``trigger()`` or sent straight to a port has no owner;
		it simply is not in the map, and a teardown leaves it alone.
		"""

		if event.owner is None:
			return

		try:
			self._note_owner[(event.device, event.channel, event.note)] = event.owner
		except TypeError:
			# Something not weak-referenceable placed it.  Not knowing the owner
			# is the old behaviour, and better than refusing to play the note.
			pass


	def _spawn (self, coro: typing.Coroutine) -> None:

		"""Fire-and-forget *coro* on the event loop, tracked and exception-safe.

		Retains a strong reference until the task completes (so it cannot be
		collected mid-flight) and surfaces any exception via the done-callback -
		a bare ``asyncio.create_task`` drops both, silently losing a raising bar
		or beat callback.
		"""

		task = asyncio.create_task(coro)
		self._background_tasks.add(task)
		task.add_done_callback(self._reap_background_task)


	def _reap_background_task (self, task: "asyncio.Task") -> None:

		"""Done-callback: drop the reference and log any exception."""

		self._background_tasks.discard(task)

		if not task.cancelled() and task.exception() is not None:
			logger.error("Background task failed", exc_info=task.exception())


	async def schedule_pattern (self, pattern: PatternLike, start_pulse: int) -> None:

		"""
		Schedules a pattern's notes and CC events into the sequencer's event queue.

		If ``pattern.mirrors`` is non-empty, every note, CC, pitch bend, program
		change, SysEx, NRPN/RPN burst, and drone event is duplicated onto each
		mirror destination.  OSC events are not mirrored.

		**Bandwidth note**: each mirror destination multiplies the per-pattern
		event count.  A dense pattern with two mirrors emits 3× the original.
		For DIN-MIDI hardware on a saturated bus this can matter; over USB or
		IAC it is rarely a concern.

		**Tuning + mirrors**: ``CcEvent.channel`` and ``CcEvent.device`` overrides
		(used by polyphonic microtonal tuning to rotate notes onto separate
		channels) apply to the *primary* destination only.  Mirror destinations
		always use their own pinned ``(device, channel)`` - i.e. a polyphonic-
		tuning pattern mirrored to another synth will collapse all channel
		rotations onto the mirror's single channel, losing per-note bend
		isolation on that destination.  Apply tuning per-pattern if both ends
		need it.
		"""

		# A pattern built by hand may still hold the glides and tunings its
		# builder left for the end of the build; lay them against its final
		# notes before reading them (#2959).  The engine's patterns hold none.
		finish_builds = getattr(pattern, '_finish_builds', None)
		if finish_builds is not None:
			finish_builds()

		# Primary destination first; mirrors follow.  Iteration order matters
		# only for human readability when inspecting the queue — FIFO ordering
		# at equal pulses is enforced by ``_push_event`` (the ``sequence``
		# tie-breaker on ``MidiEvent``).
		mirrors = getattr(pattern, 'mirrors', [])
		destinations: typing.List[_MirrorTarget] = [_MirrorTarget(pattern.device, pattern.channel, None)] + [_to_target(entry) for entry in mirrors]

		async with self.queue_lock:

			# A drone sounds until the pattern turns it off, and it turns it off
			# only where it plays now.  One it holds on a destination it has
			# left would ring for ever, so it is released as this cycle starts,
			# before anything plays where the pattern went.
			#
			# A part that has been SILENCED — muted by hand, closed by the
			# energy gate, or held quiet through a transition — lets go of all
			# of them, wherever they are.  Its builder is not running, so the
			# `drone_off` it had planned never comes, and the note rang until
			# the performance stopped: one struck at beat 0 and muted at cycle 2
			# was released when the render ended, at beat 48.  Unmuting does not
			# strike it again; the builder decides what sounds (decision 3 of
			# #2991).
			held = self._held_drones.setdefault(pattern, set())
			silenced = bool(getattr(pattern, "is_silenced", False))
			playing_to = {(target.device, target.channel) for target in destinations}

			for device, channel, note in sorted(held):
				if silenced or (device, channel) not in playing_to:
					held.discard((device, channel, note))
					self._push_event(MidiEvent(
						pulse = start_pulse,
						message_type = 'note_off',
						channel = channel,
						note = note,
						velocity = 0,
						device = device,
					), owner = pattern)

			for position, step in pattern.steps.items():

				abs_pulse = start_pulse + position

				for note in step.notes:

					for i, target in enumerate(destinations):

						# Resolve the drum name for this destination; None means the
						# destination has no voice for it, so it stays silent (no
						# note_on AND no note_off — nothing can hang).
						note_value = _destination_pitch(note, target, primary = (i == 0))
						if note_value is None:
							# A mirror carrying its own map that lacks this named
							# voice drops it here by design (faithful-core: silence,
							# never a wrong note).  Surface it at debug level so
							# "why is the clap missing on the sampler?" is answerable
							# without guessing — the build-time warning only covers a
							# name absent from *every* destination.
							if i != 0 and note.origin is not None and target.drum_note_map is not None:
								logger.debug(
									"Mirror device %d channel %d has no voice for drum '%s' - dropped for this destination",
									target.device, target.channel, note.origin,
								)
							continue

						# Primary preserves the Note's own channel (so polyphonic
						# tuning's per-voice channel rotation lands correctly).
						# Mirrors collapse onto the mirror's pinned channel and
						# re-resolve the drum name through their own map.
						note_channel = note.channel if i == 0 else target.channel
						note_device = pattern.device if i == 0 else target.device

						on_event = MidiEvent(
							pulse = abs_pulse,
							message_type = 'note_on',
							channel = note_channel,
							note = note_value,
							velocity = note.velocity,
							device = note_device,
						)
						self._push_event(on_event, owner = pattern)

						# At least a pulse after its note-on: note-offs lead their
						# pulse, so a zero-length note would otherwise be released
						# before it started and hang.
						off_event = MidiEvent(
							pulse = abs_pulse + max(1, note.duration),
							message_type = 'note_off',
							channel = note_channel,
							note = note_value,
							velocity = 0,
							device = note_device,
						)
						self._push_event(off_event, owner = pattern)

			# CC / pitch bend / program change / SysEx events
			for cc_event in getattr(pattern, 'cc_events', []):

				abs_pulse = start_pulse + cc_event.pulse

				for i, target in enumerate(destinations):

					if i == 0:
						# Primary: respect per-event channel/device override if set
						# (e.g. tuning pitch bends targeting specific channels).
						event_channel = cc_event.channel if cc_event.channel is not None else target.channel
						event_device = cc_event.device if cc_event.device is not None else target.device
					else:
						# Mirror: always use the mirror's pinned (device, channel).
						# See class docstring for the tuning interaction note.
						event_channel = target.channel
						event_device = target.device

					midi_event = MidiEvent(
						pulse = abs_pulse,
						message_type = cc_event.message_type,
						channel = event_channel,
						control = cc_event.control,
						value = cc_event.value,
						data = cc_event.data,
						device = event_device,
						priority = getattr(cc_event, 'priority', 0),
					)
					self._push_event(midi_event, owner = pattern)

			# Raw Note On/Off events (drones)
			for note_ev in getattr(pattern, 'raw_note_events', []):

				abs_pulse = start_pulse + note_ev.pulse

				for i, target in enumerate(destinations):

					# Same faithful-core rule as step notes: a named drone is
					# re-resolved through each mirror's own drum_note_map, and
					# a destination lacking the voice stays silent rather than
					# sounding the primary device's note number.
					note_value = _destination_pitch(note_ev, target, primary = (i == 0))
					if note_value is None:
						if i != 0 and note_ev.origin is not None and target.drum_note_map is not None:
							logger.debug(
								"Mirror device %d channel %d has no voice for drum '%s' - dropped for this destination",
								target.device, target.channel, note_ev.origin,
							)
						continue

					midi_event = MidiEvent(
						pulse = abs_pulse,
						message_type = note_ev.message_type,
						channel = target.channel,
						note = note_value,
						velocity = note_ev.velocity,
						device = target.device,
					)
					self._push_event(midi_event, owner = pattern)

					if midi_event.rank == 2:
						held.add((target.device, target.channel, note_value))
					else:
						held.discard((target.device, target.channel, note_value))

			# OSC events — never mirrored.  OSC isn't bound to a MIDI port and
			# mirroring it would require a different abstraction (multiple OSC
			# servers / addresses).  If users want to broadcast OSC to several
			# endpoints, that belongs in the OSC server config, not here.
			for osc_event in getattr(pattern, 'osc_events', []):

				abs_pulse = start_pulse + osc_event.pulse

				osc_midi_event = MidiEvent(
					pulse = abs_pulse,
					message_type = 'osc',
					channel = 0,
					data = (osc_event.address, osc_event.args)
				)

				self._push_event(osc_midi_event, owner = pattern)

		logger.debug(f"Scheduled pattern at {start_pulse}, queue size: {len(self.event_queue)}")


	async def schedule_pattern_repeating (self, pattern: PatternLike, start_pulse: int) -> None:

		"""
		Schedule a pattern and register it for rescheduling each cycle.
		"""

		length_pulses, lookahead_pulses = self._get_pattern_timing(pattern)

		# Anchor the first cycle for window-reading rebuilds (kept current on
		# every reschedule in _maybe_reschedule_patterns).
		pattern._cycle_start_pulse = start_pulse

		await self.schedule_pattern(pattern, start_pulse)

		next_reschedule_pulse = start_pulse + length_pulses - lookahead_pulses

		scheduled_pattern = ScheduledPattern(
			pattern = pattern,
			cycle_start_pulse = start_pulse,
			length_pulses = length_pulses,
			lookahead_pulses = lookahead_pulses,
			next_reschedule_pulse = next_reschedule_pulse
		)

		async with self.pattern_lock:
			counter = next(self._reschedule_counter)
			heapq.heappush(self.reschedule_queue, (scheduled_pattern.next_reschedule_pulse, counter, scheduled_pattern))


	async def schedule_callback_repeating (self, callback: typing.Callable[[int], typing.Any], interval_beats: float, start_pulse: int = 0, reschedule_lookahead: float = 1) -> None:

		"""
		Schedule a repeating callback on a beat interval.
		"""

		interval_pulses, lookahead_pulses = self._get_schedule_timing(interval_beats, reschedule_lookahead)

		# "Backshift" initialization: treat start_pulse as the *target* of the first fire,
		# not the start of the first cycle. This ensures callbacks fire `lookahead` before
		# start_pulse (often ≤ 0, so they fire immediately when playback begins).
		#
		# Formula: cycle_start = start_pulse - interval
		#          first_fire  = start_pulse - lookahead
		#
		# After the first fire the loop advances normally:
		#   next_start = cycle_start + interval = start_pulse
		#   next_fire  = start_pulse + interval - lookahead
		#
		# Note: if start_pulse = 0, first_fire is negative, so the callback fires
		# at pulse 0 (the very start of playback). Pass start_pulse = interval_pulses
		# to skip the initial fire and have the first fire at (interval - lookahead).
		# The harmonic clock does this because HarmonicState already holds the tonic.

		initial_cycle_start = start_pulse - interval_pulses
		initial_fire_pulse = start_pulse - lookahead_pulses

		scheduled_callback = ScheduledCallback(
			callback = callback,
			cycle_start_pulse = initial_cycle_start,
			interval_pulses = interval_pulses,
			lookahead_pulses = lookahead_pulses,
			next_fire_pulse = initial_fire_pulse,
			initial_start_pulse = start_pulse
		)

		async with self.callback_lock:
			counter = next(self._callback_counter)
			heapq.heappush(self.callback_queue, (scheduled_callback.next_fire_pulse, counter, scheduled_callback))


	async def schedule_callback_sequence (
		self,
		callback: typing.Callable[[int], typing.Union[typing.Optional[float], typing.Coroutine[typing.Any, typing.Any, typing.Optional[float]]]],
		start_pulse: int = 0,
		reschedule_lookahead: float = 1,
	) -> None:

		"""Schedule a self-rescheduling callback with a variable firing interval.

		Where :meth:`schedule_callback_repeating` fires on a fixed beat
		interval, this primitive lets the callback decide each hop: it is
		called ``lookahead`` before every *boundary* pulse, receives that
		boundary pulse, and returns the number of beats to the **next**
		boundary - or ``None`` to stop.  Built for clocks that walk irregular
		spans, e.g. the harmonic clock under a bound progression's
		harmonic rhythm.

		The first fire targets *start_pulse* as its boundary and is due
		``lookahead`` before it (immediately, when that is already past -
		the same backshift idiom as the repeating scheduler).

		Parameters:
			callback: ``fn(boundary_pulse) -> beats_to_next_boundary | None``.
				May be sync or async.
			start_pulse: The first boundary pulse.
			reschedule_lookahead: How many beats before each boundary the
				callback fires.
		"""

		lookahead_pulses = subsequence.constants.pulses.beats_to_pulses(reschedule_lookahead, self.pulses_per_beat)

		if lookahead_pulses < 0:
			raise ValueError("Reschedule lookahead cannot be negative")

		scheduled = ScheduledCallbackSequence(
			callback = callback,
			boundary_pulse = start_pulse,
			lookahead_pulses = lookahead_pulses,
			next_fire_pulse = start_pulse - lookahead_pulses,
			initial_start_pulse = start_pulse,
		)

		async with self.callback_lock:
			counter = next(self._callback_counter)
			heapq.heappush(self.callback_sequence_queue, (scheduled.next_fire_pulse, counter, scheduled))


	async def play (self) -> None:

		"""
		Convenience method to start playback and wait for completion.
		"""

		await self.start()

		try:
			if self.task:
				await self.task
		except asyncio.CancelledError:
			pass
		finally:
			await self.stop()


	def _send_clock_message (self, message_type: str, compensated: bool = True) -> None:

		"""Send a bare MIDI system-realtime message (clock, start, stop, continue).

		These messages carry no channel or data bytes - they are sent directly to
		the output port.  Used for MIDI clock output when ``clock_output`` is True.

		**Latency-compensated, like every note.**  They used to go straight out
		while the notes for the same device were held back, so compensation
		pulled the transport and the music apart instead of together: with one
		device at 0 ms and another at 20 ms, a Start reached the faster synth in
		0.01 ms where its notes wait 20 ms, and a slaved drum machine ran a whole
		offset ahead of the part it was locking to (#3069).

		Parameters:
			message_type: One of ``"clock"``, ``"start"``, ``"stop"``, ``"continue"``.
			compensated: False sends immediately, for the Stop at shutdown -
				``stop()`` closes the ports straight afterwards, so a deferred
				send would fire on a closed one, and a Stop arriving an offset
				early at the very end of a piece costs nothing.
		"""

		# No render_mode guard here on purpose: Composition.render() turns
		# clock_output off outright (#2995), while a bare Sequencer in render
		# mode is how the clock-output tests read this traffic quickly.
		for index, port in self._output_devices.indexed():

			def deliver (port: typing.Any = port, index: int = index) -> None:
				try:
					self._locked_send(port, mido.Message(message_type))
				except Exception:
					logger.exception(f"Failed to send MIDI {message_type} message")

			if compensated:
				self._send_after_compensating(index, deliver)
			else:
				deliver()


	async def start (self) -> None:

		"""Start the sequencer playback in a separate asyncio task.

		When an input device is configured, the MIDI input port is opened here
		(after the event loop is running) so that call_soon_threadsafe works.
		When ``clock_output`` is True, a MIDI Start (0xFA) message is sent before
		the first clock tick so connected hardware begins from the top.
		"""

		if self.running:
			return

		# Open the output now rather than at construction — and never in a
		# render, which writes a file and must not reach a device (#2995).
		# Composition._run has usually done this already, so the registry is
		# non-empty and this is a no-op; a bare Sequencer arrives here first.
		if not self._output_devices and not self.render_mode:
			self._init_midi_output()

		# Set up MIDI input queue before opening the port.
		self._open_midi_inputs()

		# Store the event loop for thread-safe scheduling (e.g., trigger() from user threads)
		self._event_loop = asyncio.get_running_loop()

		self._transport_held = self.clock_follow
		self.running = True
		self._stopped = False
		self.task = asyncio.create_task(self._run_loop())

		if self.clock_output:
			self._send_clock_message("start")

		logger.info("Sequencer started")

		await self.events.emit_async("start")


	async def stop (self) -> None:

		"""
		Stop the sequencer playback and cleanup resources.
		"""

		if self._stopped:
			return

		self._stopped = True

		logger.info("Stopping sequencer...")

		self.running = False

		# Wake the external-clock loop, which is parked on its input queue for
		# up to two seconds at a time.  It used to be a master's Stop that ended
		# that loop; a Stop holds the position now (#3053), so Ctrl+C is the way
		# out and it should not have to wait for a timeout that exists only to
		# notice a silent cable.  A device index the loop does not follow is
		# skipped before anything reads the message, so this advances nothing.
		if self._midi_input_queue is not None:
			try:
				self._midi_input_queue.put_nowait((-1, mido.Message("stop"), time.perf_counter()))
			except Exception:
				logger.exception("Failed to wake the external clock loop for shutdown")

		if self.task:
			try:
				await self.task
			except asyncio.CancelledError:
				# The loop task was cancelled (the Ctrl-C path) — since
				# Python 3.8 CancelledError is a BaseException, so a bare
				# `except Exception` missed it and the whole cleanup below
				# was skipped.
				logger.info("Sequencer loop task cancelled - continuing shutdown")
			except Exception:
				# A crashed loop must not abort shutdown - the cleanup below
				# (pending-send cancellation, panic, port close, recording
				# save) is exactly what a dying session needs most.
				logger.exception("Sequencer loop task ended with an exception - continuing shutdown")

		# Cancel any latency-compensation deferrals still in flight.  Must happen
		# after the loop has stopped producing (await self.task) and before
		# close_all() so a pending call_later can't fire on a closed port.
		# panic() below is the silence authority for any note stranded by this.
		self._cancel_pending_sends()

		if self.clock_output:
			# Uncompensated on purpose: close_all() is four lines below, so a
			# deferred Stop would fire on a closed port — and the cancellation
			# above has just thrown away everything it would have queued behind
			# anyway.  Early by one offset at the very end of a piece is nothing;
			# a Stop that never arrives leaves a slaved device running (#3069).
			self._send_clock_message("stop", compensated=False)

		await self.panic()

		self._output_devices.close_all()
		self._input_devices.close_all()

		# Leave the Ableton Link session cleanly if one was active, rather than
		# letting the socket linger in the session until process exit.
		if self._link_clock is not None:
			try:
				self._link_clock.disable()
			except Exception:
				logger.exception("Failed to disable Ableton Link clock")

		self._midi_input_queue = None
		self._input_loop = None

		self.save_recording()

		logger.info("Sequencer stopped")

		async with self.pattern_lock:
			self.reschedule_queue = []
			self._reschedule_counter = itertools.count()

		async with self.callback_lock:
			self.callback_queue = []
			self.callback_sequence_queue = []
			self._callback_counter = itertools.count()

		# Note: ``_event_counter`` is intentionally NOT reset here.  The two
		# counters above pair with queues that we do clear, so resetting them
		# is symmetric.  ``self.event_queue`` is left to drain naturally and
		# may carry stale items into a restart; resetting ``_event_counter``
		# alongside an un-cleared queue would let a fresh push (sequence=0)
		# sort ahead of a stale push (sequence=N) at the same pulse.  Since
		# pulse is the primary heap key and the counter never overflows, we
		# just let it keep counting forever.

		self.active_notes = set()
		self._paused = False

		await self.events.emit_async("stop")


	def pause (self) -> None:

		"""Hold the clock where it is, keeping the composition's place.

		Playback stops advancing, sounding notes are released, and MIDI Stop
		(0xFC) goes out when ``clock_output`` is on.  ``resume()`` continues
		from the same pulse, beat and bar - unlike ``stop()``, which discards
		the position.

		Takes effect on the clock loop's next turn (within a few milliseconds),
		not on return: the ``"pause"`` event fires when the transport has
		actually stopped, so a UI following it shows the real state rather than
		assuming its own button worked.  Safe to call from any thread, and
		idempotent - pausing a paused sequencer does nothing.

		**A note cut short by a pause is not re-struck on resume.**  Re-striking
		would invent an articulation the composition never asked for; the
		pattern's next cycle is where it returns.

		Refused, with a log line rather than silently, when the pulse is not
		ours to hold: under ``clock_follow`` the tempo comes from the cable, and
		under Ableton Link the transport belongs to the session.  Render mode is
		refused too - its clock is simulated, so there is nothing to hold.
		"""

		if not self.running or self._paused:
			return

		if self.render_mode:
			logger.info("Render mode has no wall clock to hold - pause() ignored")
			return

		if self.clock_follow:
			logger.info("Transport is controlled by external clock - pause() ignored")
			return

		if self._link_clock is not None:
			logger.info("Transport belongs to the Ableton Link session - pause() ignored")
			return

		self._paused = True


	def resume (self) -> None:

		"""Continue playback from the pulse ``pause()`` held.

		Sends MIDI Continue (0xFB) when ``clock_output`` is on - never Start
		(0xFA), which would reset downstream hardware to the top of its own
		pattern.  Idempotent: resuming a running sequencer does nothing.

		Refused wherever ``pause()`` is refused, and for the same reason: a
		transport that is not ours to hold is not ours to release either.  Under
		``clock_follow`` it is the master's Continue that resumes the piece
		(#3053).
		"""

		if self.clock_follow:
			logger.info("Transport is controlled by external clock - resume() ignored")
			return

		if self._link_clock is not None:
			logger.info("Transport belongs to the Ableton Link session - resume() ignored")
			return

		self._paused = False


	@property
	def bar_beats (self) -> float:

		"""How many beats (quarter notes) one bar lasts: ``beats × 4 / unit``, so 3.5 in 7/8."""

		return subsequence.metre.bar_beats(self.time_signature)


	@property
	def paused (self) -> bool:

		"""True while the transport is held by :meth:`pause`."""

		return self._paused


	async def _hold_while_paused (self, next_pulse_time: float) -> float:

		"""Block until resumed, and return *next_pulse_time* rebased past the pause.

		The clock loop's inner ``while current_time >= next_pulse_time`` catches
		up every overdue pulse in one pass, so a pause that left the deadline
		where it was would fire the whole held span as a burst on resume - 480
		pulses for a ten-second pause at 120 BPM.  Shifting the deadline by the
		measured hold carries the remainder of the interrupted pulse across it
		and puts the next pulse a proper interval after the resume instant.

		``start_time`` is deliberately not shifted: it is read in exactly one
		place (to seed this deadline), so an accumulated offset here is the
		whole of the bookkeeping.
		"""

		held_from = time.perf_counter()

		# Release before announcing: a listener that reacts to "pause" should
		# find the rig already quiet.  Routed through latency compensation so a
		# note_on still deferred in _pending_sends cannot be overtaken by its
		# own note_off — those sends are real notes already dispatched, so they
		# are left to land rather than cancelled (stop() cancels; pause does not).
		await self._stop_all_active_notes(compensated=True)

		if self.clock_output:
			self._send_clock_message("stop")

		await self.events.emit_async("pause")

		while self._paused and self.running:
			await asyncio.sleep(self._PAUSE_POLL_SECONDS)

		held_for = time.perf_counter() - held_from
		self._paused_seconds += held_for

		# A stop() during the pause ends the loop; it sends its own transport
		# message and there is nothing to continue.
		if not self.running:
			return next_pulse_time + held_for

		# A knob turned while the transport was held queued every value it
		# passed through; send where it now stands, not its whole journey.
		self._coalesce_forwards()

		if self.clock_output:
			self._send_clock_message("continue")

		await self.events.emit_async("resume")

		return next_pulse_time + held_for


	# ------------------------------------------------------------------
	# The transport, when it belongs to somebody else
	# ------------------------------------------------------------------
	#
	# Under ``clock_follow`` the master's Stop, Continue and Start drive the
	# three methods below.  ``pause()`` and ``resume()`` refuse here on purpose:
	# the *user* cannot hold a clock that is not theirs, but the cable can, and
	# what it asks for is the same held state (#3053).

	async def _transport_pause (self) -> None:

		"""Hold the position and release what is sounding - an external Stop.

		Stop used to end the session outright, so a master's Stop button tore
		down the piece and the Continue after it had nothing to resume.  It
		pauses now: the pulse, bar and beat stay where they are, ticks keep
		feeding the BPM estimate, and the piece carries on from here.

		The release is compensated because the rig is still live and a note_on
		may be deferred on a device offset - the same reason ``pause()`` gives.
		"""

		if self._transport_held:
			return

		self._transport_held = True
		self._paused = True
		self._paused_from = time.perf_counter()

		await self._stop_all_active_notes(compensated=True)

		await self.events.emit_async("pause")


	async def _transport_resume (self) -> None:

		"""Carry on from the held pulse - an external Continue.

		Never a restart: Continue means *from where you were*, which is the
		whole of the difference between it and Start.
		"""

		if not self._transport_held:
			return

		self._transport_held = False

		if self._paused:
			self._paused = False
			self._paused_seconds += time.perf_counter() - self._paused_from

			# A knob turned while the transport was held queued every value it
			# passed through; send where it now stands, not its whole journey.
			self._coalesce_forwards()

			await self.events.emit_async("resume")


	async def _restart_from_the_top (self) -> None:

		"""Put the piece back at bar 0 - an external Start.

		A Start used to reset the pulse counter and nothing else, so the queues
		kept their old numbering: a piece stopped six beats in went silent for
		six beats and then resumed *mid-phrase*, and a note still sounding was
		left on.  Measured before the fix, the first thing heard after a Start
		was the pattern's seventh note, 6.04 beats later (#3053).

		So: release what is sounding, drop every event the old position had
		queued, rewind the composition, and re-anchor every part and clock on
		cycle 0.

		**The whole piece goes back, not only the transport** (#3089).  The MIDI
		specification is the argument: Start means "start at the beginning of
		the song", and Continue is the message that resumes where a Stop left
		off.  A Composition registers ``on_restart`` to put its form back to
		section 0 and its harmony back to the tonic; a bare Sequencer has no
		such thing to rewind and the hook is simply absent.
		"""

		if self._transport_held and self.pulse_count == 0 and self.current_bar < 0:
			# The session's first Start, with nothing yet played.  There is no
			# position to discard, and ``Composition._run`` has already laid
			# cycle 0 down — so this begins the piece rather than restarting it.
			await self._transport_resume()
			return

		await self._stop_all_active_notes(compensated=True)

		async with self.queue_lock:
			self.event_queue = []

		self.pulse_count = 0
		self.current_bar = -1
		self.current_beat = -1

		# Before the re-anchor, so the clocks are re-placed around a
		# composition that has already gone back to its opening.
		if self.on_restart is not None:
			await self.on_restart()

		await self._reanchor_on_cycle_zero()

		await self._transport_resume()


	async def _reanchor_on_cycle_zero (self) -> None:

		"""Re-place every repeating pattern, callback and sequence as at pulse 0.

		Each is put back exactly where the call that scheduled it would put it
		now, so a restart and a fresh ``start()`` leave the queues in the same
		shape.  That is why the callbacks carry ``initial_start_pulse``: the
		harmonic clock is scheduled one interval in so it does *not* fire at
		pulse 0 (``HarmonicState`` already holds the tonic), while an ordinary
		callback scheduled at 0 does - and nothing else distinguishes them.
		"""

		async with self.pattern_lock:
			scheduled_patterns = [entry[2] for entry in self.reschedule_queue]
			self.reschedule_queue = []
			self._reschedule_counter = itertools.count()

		live = [
			scheduled for scheduled in scheduled_patterns
			if not getattr(scheduled.pattern, "_removed", False)
		]

		for scheduled in live:
			scheduled.cycle_start_pulse = 0
			scheduled.pattern._cycle_start_pulse = 0
			scheduled.next_reschedule_pulse = scheduled.length_pulses - scheduled.lookahead_pulses

			await self.schedule_pattern(scheduled.pattern, 0)

		async with self.pattern_lock:
			for scheduled in live:
				counter = next(self._reschedule_counter)
				heapq.heappush(self.reschedule_queue, (scheduled.next_reschedule_pulse, counter, scheduled))

		async with self.callback_lock:

			callbacks = [entry[2] for entry in self.callback_queue]
			sequences = [entry[2] for entry in self.callback_sequence_queue]

			self.callback_queue = []
			self.callback_sequence_queue = []
			self._callback_counter = itertools.count()

			for scheduled_callback in callbacks:
				scheduled_callback.cycle_start_pulse = scheduled_callback.initial_start_pulse - scheduled_callback.interval_pulses
				scheduled_callback.next_fire_pulse = scheduled_callback.initial_start_pulse - scheduled_callback.lookahead_pulses

				counter = next(self._callback_counter)
				heapq.heappush(self.callback_queue, (scheduled_callback.next_fire_pulse, counter, scheduled_callback))

			for scheduled_sequence in sequences:
				scheduled_sequence.boundary_pulse = scheduled_sequence.initial_start_pulse
				scheduled_sequence.next_fire_pulse = scheduled_sequence.initial_start_pulse - scheduled_sequence.lookahead_pulses

				counter = next(self._callback_counter)
				heapq.heappush(self.callback_sequence_queue, (scheduled_sequence.next_fire_pulse, counter, scheduled_sequence))


	def _coalesce_forwards (self) -> None:

		"""Keep only the latest value of each control the transport held back.

		Queued ``cc_forward`` messages drain a pulse at a time, so a pause
		queues every value a knob passed through and the resume sent the lot
		within a millisecond - the knob's journey rather than where it now is
		(#2967).  Notes and anything else queued keep every message, and the
		controls that remain stay in the order they were last touched.

		Runs on the loop thread, where the buffer is drained.
		"""

		if not self._forward_buffer:
			return

		held = list(self._forward_buffer)
		self._forward_buffer.clear()

		kept: typing.List[typing.Tuple[int, typing.Any, int]] = []
		seen: typing.Set[typing.Tuple[typing.Any, ...]] = set()

		for pulse, message, device in reversed(held):

			identity = _forward_identity(message, device)

			if identity is not None:
				if identity in seen:
					continue
				seen.add(identity)

			kept.append((pulse, message, device))

		self._forward_buffer.extend(reversed(kept))


	async def _run_loop (self) -> None:

		"""Main playback loop - delegates to internal, external, or Link clock mode."""

		self.start_time = time.perf_counter()
		self.pulse_count = 0
		self.current_bar = -1

		self._record_opening()

		pulses_per_bar = subsequence.metre.pulses_per_bar(self.time_signature, self.pulses_per_beat)

		# A render always runs the simulated internal clock: an external clock
		# would wait for ticks that never arrive, and a Link session would tie
		# the render to the room's tempo (#2995).
		if self.render_mode:
			await self._run_loop_internal_clock(pulses_per_bar)
		elif self.clock_follow and self._midi_input_queue is not None:
			await self._run_loop_external_clock(pulses_per_bar)
		elif self._link_clock is not None:
			await self._run_loop_link_clock(self._link_clock, pulses_per_bar)
		else:
			await self._run_loop_internal_clock(pulses_per_bar)


	def _check_bar_change (self, pulse: int, pulses_per_bar: int) -> None:

		"""Detect bar boundaries and fire bar callbacks + events."""

		new_bar = pulse // pulses_per_bar

		if new_bar > self.current_bar:
			self.current_bar = new_bar

			# In render mode, stop after the requested number of bars.
			if self.render_mode and self.render_bars > 0 and self.current_bar >= self.render_bars:
				self.running = False
				return

			self._spawn(self.events.emit_async("bar", self.current_bar))


	def _check_beat_change (self, pulse: int, pulses_per_unit: int) -> None:

		"""Detect beat boundaries within the bar and fire beat events.

		A beat here is the time signature's written unit, so 6/8 counts six
		eighth notes to the bar, while every ``beat=`` argument elsewhere is
		still a quarter note.
		"""

		beats, _ = self.time_signature
		beat_in_bar = (pulse % (beats * pulses_per_unit)) // pulses_per_unit

		if beat_in_bar != self.current_beat:
			self.current_beat = beat_in_bar
			self._spawn(self.events.emit_async("beat", self.current_beat))


	async def _advance_pulse (self) -> None:

		"""Send this pulse's events, reschedule patterns, and increment the pulse counter."""

		if self._bpm_transition is not None:
			self._bpm_transition.elapsed_pulses += 1

			if self._bpm_transition.elapsed_pulses >= self._bpm_transition.total_pulses:
				target = self._bpm_transition.target_bpm
				self._bpm_transition = None
				self.set_bpm(target)
			else:
				progress = self._bpm_transition.elapsed_pulses / self._bpm_transition.total_pulses
				eased = self._bpm_transition.easing_fn(progress)
				interpolated = (
					self._bpm_transition.start_bpm +
					(self._bpm_transition.target_bpm - self._bpm_transition.start_bpm) * eased
				)
				self.current_bpm = interpolated
				self.seconds_per_beat = 60.0 / self.current_bpm
				self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat

				# Keep the recording's tempo map honest: without these events
				# a recorded ramp plays back at the pre-ramp tempo and jumps.
				if self.recording:
					self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(interpolated)))

		# Accumulate simulated time and enforce the render time cap.
		if self.render_mode:
			self._render_elapsed_seconds += self.seconds_per_pulse
			if (
				self.render_max_seconds is not None
				and self._render_elapsed_seconds >= self.render_max_seconds
			):
				max_min = self.render_max_seconds / 60.0
				logger.warning(
					f"Render stopped at {max_min:.1f}-minute safety limit. "
					f"Pass max_minutes=None with an explicit bars= count to remove this limit."
				)
				self.running = False
				return

		# Drain buffered note input into the held-note tracker BEFORE patterns
		# rebuild, so a pattern's held_notes() snapshot reflects this pulse rather
		# than the previous one.  deque.popleft() is GIL-atomic; the tracker is
		# only ever touched on this loop thread (here and during rebuild).
		if self._held_notes is not None:
			while self._note_input_buffer:
				is_on, pitch, velocity, when = self._note_input_buffer.popleft()
				if is_on:
					self._held_notes.note_on(pitch, velocity, when)
				else:
					self._held_notes.note_off(pitch, when)

		# Send this pulse's events BEFORE rebuilding anything due on it.  They
		# were placed by an earlier rebuild, so nothing the coming one does can
		# change them — sending them after it made every note on a rebuild pulse
		# late by the whole rebuild, and the default one-beat lookahead puts a
		# one-bar pattern's rebuild on beat 4.  The second pass sends whatever
		# the rebuild step placed on this same pulse (a zero lookahead's downbeat,
		# a callback's pattern) now rather than a pulse late; it finds nothing to
		# do on almost every pulse.
		await self._process_pulse(self.pulse_count)
		await self._maybe_reschedule_patterns(self.pulse_count)
		await self._process_pulse(self.pulse_count)
		self.pulse_count += 1


	async def _run_loop_internal_clock (self, pulses_per_bar: int) -> None:

		"""Playback loop driven by the internal wall clock.

		In normal mode the loop sleeps between pulses to maintain tempo.
		In render mode it runs as fast as possible (simulates time rather than
		waiting for the wall clock), stopping after *render_bars* bars.
		"""

		next_pulse_time = self.start_time

		while self.running:

			# Held between pulses, never mid-catch-up, so a pause cannot split
			# the ordering within one pulse.  Returns the deadline rebased past
			# the hold — without that the inner while below would fire every
			# pulse the pause spanned, in one burst.
			if self._paused:
				next_pulse_time = await self._hold_while_paused(next_pulse_time)

				if not self.running:
					# Reachable: stop() while paused clears running, which is
					# what releases the hold.  mypy narrows running from the
					# while condition and cannot see across the await.
					break  # type: ignore[unreachable]

			# In render mode, simulate time advancing one pulse at a time so
			# the inner loop always fires exactly once without spin-waiting.
			current_time = next_pulse_time if self.render_mode else time.perf_counter()

			# Held for longer than a beat - by a slow build, a runaway line that was
			# stopped, the machine itself - the loop would play every missed pulse
			# in one burst.  Carry on from where it stopped instead, just later, as
			# after a pause (#3374, Simon's decision).  A shorter stall plays
			# through, as the Link clock's does.
			behind = (current_time - next_pulse_time) / self.seconds_per_pulse

			if behind > _CATCH_UP_PULSES:
				logger.warning(
					"The clock was held for %.2f s (%.1f beats); carrying on from where it stopped "
					"instead of playing everything it missed at once.",
					current_time - next_pulse_time, behind / self.pulses_per_beat,
				)
				next_pulse_time = current_time

			while current_time >= next_pulse_time:
				# Ordering within each pulse:
				#   1. _check_bar/beat_change() — update counters and queue "bar"/"beat"
				#      event tasks (asyncio.create_task; not run yet).
				#   2. Send MIDI clock tick (if clock_output) so hardware receives it at
				#      the same time as note events for tight sync.
				#   3. _advance_pulse() — send this pulse's MIDI via _process_pulse(), then
				#      fire callbacks and rebuild patterns, then send anything they placed
				#      on this same pulse.
				#   4. After the await returns, the event loop runs the queued event tasks,
				#      which update the terminal display.
				#
				# Consequence: MIDI notes are sent *before* the display updates. The display
				# always trails the audio by roughly one pulse-processing cycle plus any
				# terminal rendering latency (~10-50 ms). This is expected and acceptable for
				# a visual status line — it cannot be tightened without restructuring the loop.
				self._check_bar_change(self.pulse_count, pulses_per_bar)

				if not self.running:
					# A render bar-limit trips inside _check_bar_change; stop before
					# dispatching this pulse so the first beat of the next (unrendered)
					# bar never leaks into the recording.
					break  # type: ignore[unreachable]

				self._check_beat_change(self.pulse_count, self._pulses_per_unit)
				if self.clock_output:
					self._send_clock_message("clock")
				await self._advance_pulse()
				next_pulse_time += self.seconds_per_pulse

				if not self.running:
					break  # type: ignore[unreachable]

			if not self.running:
				break  # type: ignore[unreachable]

			if not self.render_mode:
				# Check if queue is empty and we are past the last event.
				# Skipped in benchmark mode (_jitter_log set) so the clock
				# runs until explicitly cancelled via asyncio.
				if self._jitter_log is None:
					async with self.queue_lock:
						if (not self.event_queue and not self.active_notes
								and not self.reschedule_queue and not self.callback_queue
								and not self.callback_sequence_queue):
							logger.info("Sequence complete (no more events or active notes).")
							self.running = False
							break

				sleep_time = next_pulse_time - time.perf_counter()

				if sleep_time > 0:
					if self._spin_wait and sleep_time > self._spin_threshold:
						# Sleep to within _spin_threshold of the target, then busy-wait
						# for the remaining sub-millisecond.  Trades ~1ms of CPU spin per
						# pulse for significantly tighter timing than asyncio.sleep alone.
						await asyncio.sleep(sleep_time - self._spin_threshold)
						while time.perf_counter() < next_pulse_time:
							pass
					else:
						await asyncio.sleep(sleep_time)

				if self._jitter_log is not None:
					self._jitter_log.append(time.perf_counter() - next_pulse_time)
			else:
				# Yield to the event loop so queued tasks (pattern rescheduling,
				# asyncio.create_task callbacks) can run between pulses.
				await asyncio.sleep(0)


	async def _run_loop_external_clock (self, pulses_per_bar: int) -> None:

		"""Playback loop driven by incoming MIDI clock messages.

		Each MIDI ``clock`` tick advances exactly one pulse (24 ppqn = internal ppqn).
		The loop waits for a ``start`` or ``continue`` before advancing pulses,
		but still uses incoming ticks to estimate BPM for display.

		**The transport is the master's** (#3053).  Following it as a slave means:

		- **Stop** holds the position and releases what is sounding.  It does
			not end the session - only Ctrl+C or :meth:`stop` does - so the
			piece is still there when the master presses play again.
		- **Continue** carries on from the held pulse.
		- **Start** restarts from bar 0: it releases, drops every queued event
			and rebuilds every part from cycle 0.

		Song Position Pointer is not followed yet, so a master that locates
		before starting is still heard from the top.
		"""

		assert self._midi_input_queue is not None, "MIDI input queue must be initialized for external clock"

		while self.running:

			try:
				device_idx, message, arrived_at = await asyncio.wait_for(
					self._midi_input_queue.get(), timeout=2.0
				)
			except asyncio.TimeoutError:
				continue

			if device_idx != self.clock_device_idx:
				continue

			if message.type == "clock":

				# Prime BPM estimation while the transport is held, but do not
				# advance pulses or schedule events yet.
				if self._transport_held:
					self._estimate_bpm(arrived_at)
					continue

				self._estimate_bpm(arrived_at)
				self._check_bar_change(self.pulse_count, pulses_per_bar)
				self._check_beat_change(self.pulse_count, self._pulses_per_unit)
				await self._advance_pulse()

			elif message.type == "start":
				logger.info("MIDI start received - restarting from bar 0")
				await self._restart_from_the_top()

			elif message.type == "stop":
				logger.info("MIDI stop received - holding position")
				await self._transport_pause()

			elif message.type == "continue":
				logger.info("MIDI continue received - resuming")
				await self._transport_resume()


	async def _run_loop_link_clock (self, link_clock: typing.Any, pulses_per_bar: int) -> None:

		"""Playback loop driven by Ableton Link beat clock.

		``link_clock.sync(period)`` is the timing gate, and what it takes is a
		**period**: aalink resumes at the next *multiple* of it.  This used to
		pass an absolute beat - ``beat_origin + pulse / PPQN`` - so every pulse
		waited for a multiple of itself.  Pulse 0 waited for two bars, and every
		pulse after it landed on a lattice twice as coarse as intended, so the
		piece played at exactly **half tempo** while the display showed the
		right BPM (#2993).  It stepped with ``sync(1 / PPQN)`` - the next pulse
		lattice point - and reads the beat it is handed.

		A stall is caught up pulse by pulse, exactly as the internal clock's
		inner loop does, up to a beat's worth.  Past that, playing every missed
		pulse would be a burst of noise, so the position moves to where Link
		actually is and says so.

		Typical jitter at 24 PPQN is ~0.3–0.5 ms, dominated by asyncio and OS
		scheduling.  Playback starts on the next bar boundary so bar 0 aligns
		with every other participant in the session.
		"""

		logger.info("Ableton Link clock mode: waiting for bar boundary…")

		# Wait for the next quantum boundary (bar start) for a clean, phase-locked start.
		beat_origin = await link_clock.wait_for_bar()

		logger.info(f"Ableton Link: started at beat {beat_origin:.3f} (tempo={link_clock.tempo:.1f} BPM, peers={link_clock.num_peers})")

		# Reset pulse counter here so bar/beat tracking starts from 0 at beat_origin.
		self.pulse_count = 0
		self.current_bar = -1
		self.current_beat = -1

		pulse_period = 1.0 / self.pulses_per_beat
		sounded_beat = beat_origin		# pulse 0 belongs to the bar line itself

		def play_one_pulse () -> None:
			"""Bar and beat bookkeeping, and a clock tick if one is due."""

			self._check_bar_change(self.pulse_count, pulses_per_bar)
			self._check_beat_change(self.pulse_count, self._pulses_per_unit)

			if self.clock_output:
				self._send_clock_message("clock")

		while self.running:

			# Update local tempo from the Link session — propagates network BPM changes.
			link_bpm = link_clock.tempo
			if abs(link_bpm - self.current_bpm) > 0.01:
				# Record the change so a recorded session's .mid plays back
				# at the Link session tempo (mirrors the external-clock path).
				if self.recording:
					self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(link_bpm)))
				self.current_bpm = link_bpm
				self.seconds_per_beat = 60.0 / self.current_bpm
				self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat
				logger.debug(f"Link tempo update: {link_bpm:.2f} BPM")

			play_one_pulse()

			if not self.running:
				# A render bar-limit trips inside _check_bar_change.
				break  # type: ignore[unreachable]

			await self._advance_pulse()

			# Stop when all events are exhausted (same check as internal clock).
			async with self.queue_lock:
				if (not self.event_queue and not self.active_notes
						and not self.reschedule_queue and not self.callback_queue
						and not self.callback_sequence_queue):
					logger.info("Sequence complete (no more events or active notes).")
					self.running = False
					break

			# The next point on the pulse lattice, wherever the session has got
			# to.  A PERIOD, not a position — that is the whole of #2993.
			beat = await link_clock.sync(pulse_period)

			# How far the session moved while we were away.  One pulse is the
			# ordinary case; anything more was missed while we were busy.
			missed = int(round((beat - sounded_beat) * self.pulses_per_beat)) - 1
			sounded_beat = beat

			if missed > _CATCH_UP_PULSES:
				# Too far behind to play through.  Working the backlog off is a
				# burst of noise and then a piece running at a fraction of the
				# session's tempo, which is what a 42 ms stall used to cause —
				# so the position moves to where Link actually is.
				logger.warning(
					"Ableton Link: %d pulses behind (%.2f beats) - moving to the session's "
					"position instead of playing the backlog.",
					missed, missed / self.pulses_per_beat,
				)
				self.pulse_count += missed

			elif missed > 0:
				# A short stall: play through it, as the internal clock's inner
				# loop does when the wall clock has run ahead of it.
				for _ in range(missed):

					play_one_pulse()

					if not self.running:
						break  # type: ignore[unreachable]

					await self._advance_pulse()


	async def _maybe_reschedule_patterns (self, pulse: int) -> None:

		"""
		Reschedule repeating callbacks and patterns when they reach their lookahead threshold.
		"""

		to_fire: typing.List[ScheduledCallback] = []
		to_reschedule: typing.List[ScheduledPattern] = []

		async with self.callback_lock:

			while self.callback_queue and self.callback_queue[0][0] <= pulse:

				_, _, scheduled_callback = heapq.heappop(self.callback_queue)

				next_start_pulse = scheduled_callback.cycle_start_pulse + scheduled_callback.interval_pulses
				scheduled_callback.cycle_start_pulse = next_start_pulse
				scheduled_callback.next_fire_pulse = next_start_pulse + scheduled_callback.interval_pulses - scheduled_callback.lookahead_pulses

				to_fire.append(scheduled_callback)

		if to_fire:
			# Decision path: composition-level callbacks fire before pattern rebuilds.
			for scheduled_callback in to_fire:
				try:
					result = scheduled_callback.callback(pulse)

					if asyncio.iscoroutine(result):
						await result

				except Exception:
					# Isolate a misbehaving callback so the rest still fire and
					# get rescheduled below — one bad callback must not stall the clock.
					logger.exception("Scheduled callback failed during reschedule (pulse %d) - continuing", pulse)

		async with self.callback_lock:
			for scheduled_callback in to_fire:
				counter = next(self._callback_counter)
				heapq.heappush(self.callback_queue, (scheduled_callback.next_fire_pulse, counter, scheduled_callback))

		# Variable-interval sequences fire after the fixed callbacks at the
		# same pulse (the form clock is fixed; the harmonic span clock is a
		# sequence — form-before-harmony ordering is preserved) and before
		# pattern rebuilds below.
		sequences_to_fire: typing.List[ScheduledCallbackSequence] = []

		async with self.callback_lock:

			while self.callback_sequence_queue and self.callback_sequence_queue[0][0] <= pulse:
				_, _, scheduled_sequence = heapq.heappop(self.callback_sequence_queue)
				sequences_to_fire.append(scheduled_sequence)

		requeue: typing.List[ScheduledCallbackSequence] = []

		for scheduled_sequence in sequences_to_fire:

			try:
				result = scheduled_sequence.callback(scheduled_sequence.boundary_pulse)

				if asyncio.iscoroutine(result):
					result = await result

			except Exception:
				# Isolate a misbehaving callback so the clock survives; the
				# sequence is dropped — with no interval there is no next hop.
				logger.exception("Callback sequence failed (pulse %d) - sequence stopped", pulse)
				continue

			if result is None:
				continue	# the sequence chose to stop

			interval_pulses = max(1, subsequence.constants.pulses.beats_to_pulses(float(result), self.pulses_per_beat))
			scheduled_sequence.boundary_pulse += interval_pulses
			scheduled_sequence.next_fire_pulse = max(
				pulse + 1,
				scheduled_sequence.boundary_pulse - scheduled_sequence.lookahead_pulses,
			)
			requeue.append(scheduled_sequence)

		if requeue:
			async with self.callback_lock:
				for scheduled_sequence in requeue:
					counter = next(self._callback_counter)
					heapq.heappush(self.callback_sequence_queue, (scheduled_sequence.next_fire_pulse, counter, scheduled_sequence))

		async with self.pattern_lock:

			while self.reschedule_queue and self.reschedule_queue[0][0] <= pulse:

				_, _, scheduled_pattern = heapq.heappop(self.reschedule_queue)

				# Lazy pattern removal: if Composition.unregister() set the
				# ``_removed`` flag on this pattern, skip both the rebuild and
				# the re-push so it disappears from rotation.  Already-queued
				# events in event_queue play out; sustaining notes were stopped
				# by unregister() via _stop_pattern_notes().
				if getattr(scheduled_pattern.pattern, '_removed', False):
					continue

				next_start_pulse = scheduled_pattern.cycle_start_pulse + scheduled_pattern.length_pulses
				scheduled_pattern.cycle_start_pulse = next_start_pulse

				# Anchor the upcoming cycle on the pattern itself, BEFORE
				# on_reschedule() below — rebuilds read it to place the cycle
				# on the absolute beat axis (the harmony window's axis).
				scheduled_pattern.pattern._cycle_start_pulse = next_start_pulse

				to_reschedule.append(scheduled_pattern)

		if to_reschedule:
			# Decision path: update shared composition state before pattern rebuilds.
			patterns = [scheduled_pattern.pattern for scheduled_pattern in to_reschedule]

			try:
				await self.events.emit_async("reschedule_pulse", pulse, patterns)
			except Exception:
				logger.exception("reschedule_pulse listener failed (pulse %d) - continuing", pulse)

		for scheduled_pattern in to_reschedule:

			# Containment: a failing rebuild — or an invalid set_length() that
			# makes _get_pattern_timing raise — must cost this pattern its
			# cycle, never the clock.  On failure the pattern keeps its
			# previous timing and is re-queued below for another try.
			try:
				scheduled_pattern.pattern.on_reschedule()

				# Re-read length in case on_reschedule() changed it (e.g. via set_length).
				new_length_pulses, new_lookahead_pulses = self._get_pattern_timing(scheduled_pattern.pattern)
				scheduled_pattern.length_pulses = new_length_pulses
				scheduled_pattern.lookahead_pulses = new_lookahead_pulses
				scheduled_pattern.next_reschedule_pulse = scheduled_pattern.cycle_start_pulse + new_length_pulses - new_lookahead_pulses

				await self.schedule_pattern(scheduled_pattern.pattern, scheduled_pattern.cycle_start_pulse)

			except Exception:
				logger.exception("Pattern reschedule failed - pattern is silent this cycle and keeps its previous timing")
				scheduled_pattern.next_reschedule_pulse = scheduled_pattern.cycle_start_pulse + scheduled_pattern.length_pulses - scheduled_pattern.lookahead_pulses

			self._spawn(self.events.emit_async("pattern_reschedule", scheduled_pattern.pattern, scheduled_pattern.cycle_start_pulse))

		async with self.pattern_lock:
			for scheduled_pattern in to_reschedule:
				counter = next(self._reschedule_counter)
				heapq.heappush(self.reschedule_queue, (scheduled_pattern.next_reschedule_pulse, counter, scheduled_pattern))


	async def _process_pulse (self, pulse: int) -> None:

		"""
		Process and execute all events for a specific pulse.
		"""

		async with self.queue_lock:

			# Drain queued CC forwards into the event heap.
			# deque.popleft() is GIL-atomic; safe to call from the event loop thread
			# while the callback thread calls append().
			while self._forward_buffer:
				fwd_pulse, fwd_msg, fwd_device = self._forward_buffer.popleft()
				self._push_event(MidiEvent.from_mido(fwd_pulse, fwd_msg, device=fwd_device))

			while self.event_queue and self.event_queue[0].pulse <= pulse:

				event = heapq.heappop(self.event_queue)

				# Defensive: dispatching a single malformed event must not
				# crash the sequencer loop and stop the whole composition.
				# A bad event (e.g. a tuple stored on Note.velocity by a
				# misuse of a builder method) is logged with full context
				# and skipped; subsequent events continue normally.
				try:

					# Track active notes (keyed by device, channel, note) - only
					# those MIDI can carry, since any other never sounds.
					if event.message_type == 'note_on' and event.velocity > 0:
						if _can_sound(event.channel, event.note, event.velocity):
							self.active_notes.add((event.device, event.channel, event.note))
							self._remember_owner(event)
					elif event.message_type == 'note_off' or (event.message_type == 'note_on' and event.velocity == 0):
						if (event.device, event.channel, event.note) in self.active_notes:
							self.active_notes.remove((event.device, event.channel, event.note))
							self._note_owner.pop((event.device, event.channel, event.note), None)

					# Send events at or before the current pulse (late events are sent
					# immediately).  Latency compensation may defer the actual send by
					# the device's offset, but recording below always uses the LOGICAL
					# pulse — the .mid is the uncompensated score.
					self._dispatch_with_compensation(event)

					if self.recording and event.message_type != 'osc':

						mido_msg = event.to_mido()
						if mido_msg is not None:
							self._record_event(event.pulse, mido_msg, event.device)

				except Exception:

					logger.exception(
						"Failed to dispatch %s event at pulse %d (device=%s, channel=%s) - skipping",
						event.message_type, event.pulse, event.device, event.channel
					)


	async def _stop_all_active_notes (self, compensated: bool = False) -> None:

		"""
		Send note_off for all currently tracked active notes.

		Parameters:
			compensated: Route the note_offs through
				:meth:`_dispatch_with_compensation` instead of sending them
				straight to the port.  Needed whenever in-flight deferred sends
				are being left to land - a note_on still waiting on its device
				offset would otherwise be overtaken by its own note_off and ring
				forever (the same hazard ``_stop_pattern_notes`` guards against).
				``stop()`` leaves this False because it cancels the pending sends
				first, which makes the immediate form safe and faster; ``pause()``
				sets it because the rig keeps playing.

		A recording hears each release (``_record_release``), so a note still
		sounding when a render or recording ends, or when the transport pauses,
		is closed in the file where it stopped (#2790).
		"""

		async with self.queue_lock:
			self._held_drones.clear()

			for dev, channel, note in list(self.active_notes):

				self._record_release(channel, note, dev)

				if compensated:
					try:
						self._dispatch_with_compensation(MidiEvent(
							pulse = self.pulse_count,
							message_type = 'note_off',
							channel = channel,
							note = note,
							velocity = 0,
							device = dev,
						))
					except Exception:
						logger.exception(f"Failed to send note_off during pause (dev={dev}, ch={channel}, note={note})")
					continue

				port = self._output_devices.get(dev)
				if port is not None:
					try:
						self._locked_send(port, mido.Message('note_off', channel=channel, note=note, velocity=0))
					except Exception:
						logger.exception("Failed to send note_off during stop")
			self.active_notes.clear()


	def _record_release (self, channel: int, note: int, device: int = 0) -> None:

		"""Record a note-off at the current pulse for a note silenced outside the event queue.

		*device* is the port the note was sounding on, so the release lands on
		the same track as its note-on (#3067) - both callers take it straight
		off the ``active_notes`` entry they are releasing.

		Only ``_process_pulse`` records what it dispatches, so a release sent
		straight from ``stop()``, ``pause()`` or ``unregister()`` never reached
		the file, and the note hung there to its end (#2790).

		It never raises: it runs inside the passes that silence everything,
		and one that failed part-way would leave the notes after it ringing
		and the recording unsaved (#2958).
		"""

		if not self.recording:
			return

		try:
			self._record_event(self.pulse_count, mido.Message('note_off', channel=channel, note=note, velocity=0), device)
		except (ValueError, TypeError):
			logger.exception(f"Could not record the release of note {note!r} on channel {channel!r} - continuing")


	async def _stop_pattern_notes (self, pattern: PatternLike) -> None:

		"""Send note_off for active notes belonging to a single pattern.

		Targets the pattern's primary ``(device, channel)`` plus every entry
		in ``pattern.mirrors``, so patterns with mirrors have their notes
		stopped on every output port they fan out to.  Used by
		``Composition.unregister()`` to flush drones and any sustaining
		notes when a pattern is being torn down.

		**Another pattern's notes are left alone.**  This used to release
		everything sounding on the pattern's ``(device, channel)``, so
		unregistering an arp cut the pad beside it: a four-beat pad note went
		off 0.08 of a beat in (#2996).

		A note nobody owns is still released.  That is deliberate: a one-shot
		from ``trigger()``, or anything sent straight to a port, has no builder
		coming back to turn it off, so a teardown of its channel is the last
		chance it gets.  Only a note another *live pattern* struck is spared,
		because that pattern will end it itself.

		It also drops the pattern's own note-ons still waiting in the queue.
		A drone struck inside the reschedule lookahead played *after* the
		release pass, and nothing ever released it.
		"""

		mirrors = getattr(pattern, 'mirrors', [])
		# Build the target set from each entry's (device, channel) prefix — a
		# 3-tuple mirror carries a dict (drum_note_map) and would be unhashable.
		targets: typing.Set[typing.Tuple[int, int]] = {(pattern.device, pattern.channel)} | {(e[0], e[1]) for e in mirrors}

		async with self.queue_lock:

			dropped = {
				id(event) for event in self.event_queue
				if event.owner is pattern and event.message_type == 'note_on' and event.velocity > 0
			}

			if dropped:
				# By identity: two events of one rank on one pulse differ only
				# in their sequence number, and equality does not look at what
				# they are.
				self.event_queue = [event for event in self.event_queue if id(event) not in dropped]
				heapq.heapify(self.event_queue)

			stranded = [
				t for t in self.active_notes
				if (t[0], t[1]) in targets and self._note_owner.get(t, pattern) is pattern
			]

			self._held_drones.pop(pattern, None)

			for dev, channel, note in stranded:
				self._record_release(channel, note, dev)

				# Route through latency compensation, NOT straight to the
				# port: a note_on for this device may still be deferred in
				# _pending_sends, and an immediate note_off would overtake it,
				# leaving the note stuck ringing (drones have no later
				# note_off to rescue them).  The shared per-device offset
				# preserves on→off order.
				try:
					self._dispatch_with_compensation(MidiEvent(
						pulse = self.pulse_count,
						message_type = 'note_off',
						channel = channel,
						note = note,
						velocity = 0,
						device = dev,
					))
				except Exception:
					logger.exception(f"Failed to send note_off during unregister (dev={dev}, ch={channel}, note={note})")
				self.active_notes.discard((dev, channel, note))
				self._note_owner.pop((dev, channel, note), None)


	def _send_offset_seconds (self, device: int) -> float:

		"""Return the latency-compensation send offset (seconds) for *device*.

		``(max_latency − device_latency) / 1000``, clamped ≥ 0.  The slowest
		device returns 0 (sent at logical time); faster devices return a
		positive delay so they sound together.

		Invariant: the offset is **per-device**, so every event for one device
		shares it.  That is what preserves same-pulse FIFO order through
		deferral - an NRPN burst (CC 99 → 98 → 6 → 38) on one device stays in
		order because all four are deferred by the same amount.  A future
		per-channel/per-message latency would break that and must not be added
		without re-thinking burst ordering.
		"""

		offset_ms = self._max_device_latency_ms - self._output_devices.latency_of(device)
		if offset_ms <= 0.0:
			return 0.0
		return offset_ms / 1000.0

	def _send_after_compensating (self, device: int, send: typing.Callable[[], None]) -> None:

		"""Call *send* now, or defer it by *device*'s latency offset.

		Deferral is a wall-clock ``call_later`` so it is correct regardless of
		tempo or clock source.  Skipped entirely in render mode (no real clock -
		deferring would drop events from the rendered file) and when no event
		loop is running (the synchronous test path).

		**Nothing may overtake what is already deferred for its device.**  The
		offset is read at dispatch, and ``set_device_latency`` can move it under
		a performer's hand mid-piece - so a note_on deferred by 50 ms could have
		its own note_off dispatched under an offset of 0 and sent first, leaving
		the note ringing for good.  Measured before this: the synth received
		``['note_off', 'note_on']``, and ``active_notes`` had already forgotten
		the note, so neither the release sweep nor ``stop()`` would catch it
		(#3069).

		A per-device floor fixes the whole class rather than that one pair: each
		send is held to at least the moment the last one for its device is due,
		which also keeps an NRPN burst (CC 99 → 98 → 6 → 38) in order across a
		latency change, exactly as the per-device offset keeps it in order
		without one.
		"""

		if self.render_mode or self._event_loop is None:
			send()
			return

		offset_s = self._send_offset_seconds(device)

		now = self._event_loop.time()

		# The floor is nudged past the last send rather than merely matched, so
		# two messages clamped to it keep the order they were dispatched in:
		# asyncio's timer heap orders on the due time alone and breaks a tie
		# arbitrarily.  A microsecond is far below anything MIDI can express and
		# four of them across an NRPN burst is not a delay anybody can measure.
		floor = self._send_floor.get(device, 0.0) + self._SEND_ORDER_EPSILON
		due = max(now + offset_s, floor)

		self._send_floor[device] = due

		if due <= now:
			send()
			return

		# Deferred to an ABSOLUTE time, not a delay: ``call_later`` reads the
		# clock again itself, so the send would land a few hundred nanoseconds
		# past the floor recorded here — which is enough to put a note_off
		# ahead of the note_on it was clamped behind, and did (#3069).
		#
		# The one-element ``cell`` lets the callback discard exactly its own
		# handle from _pending_sends (the handle isn't known until call_at
		# returns, but _fire only runs after we append).
		cell: typing.List[asyncio.TimerHandle] = []

		def _fire () -> None:
			self._pending_sends.discard(cell[0])
			send()

		handle = self._event_loop.call_at(due, _fire)
		cell.append(handle)
		self._pending_sends.add(handle)


	def _dispatch_with_compensation (self, event: MidiEvent) -> None:

		"""Send *event* now, or defer it by its device's latency offset."""

		self._send_after_compensating(event.device, lambda: self._send_midi(event))

	def _cancel_pending_sends (self) -> None:

		"""Cancel and forget all in-flight deferred sends.  Idempotent.

		Called during ``stop()`` before ports close so a pending ``call_later``
		can never fire ``port.send()`` on a closed port.  Stranded notes are not
		a concern here: ``panic()`` runs after this and is the silence
		authority (``active_notes`` reflects logical time and can diverge from
		what physically fired, so it is not relied upon).
		"""

		for handle in self._pending_sends:
			handle.cancel()
		self._pending_sends.clear()

	def _locked_send (self, port: typing.Any, message: typing.Any) -> None:

		"""Write one message to a port under the send lock.

		The lock keeps the loop thread and the instant cc_forward callback
		thread from interleaving bytes on the same port.
		"""

		with self._port_send_lock:
			port.send(message)

	def _send_midi (self, event: MidiEvent) -> None:

		"""
		Send a MIDI message to the appropriate output device.
		"""

		# OSC does not go to a MIDI port, so it must not wait for one: the
		# lookup below used to gate it, and an OSC-only piece — or any piece
		# whose device is a placeholder — sent nothing at all (#2995).
		if event.message_type == 'osc':

			if self.osc_server is not None:
				try:
					address, args = event.data
					self.osc_server.send(address, *args)
				except Exception:
					logger.exception("OSC send failed")

			return

		port = self._output_devices.get(event.device)
		if port is not None:

			try:

				msg = event.to_mido()
				if msg is None:
					# OSC returned above, so anything still unconvertible here
					# is a message we meant to send and cannot.  Say which:
					# aftertouch and polytouch went this way for months, and a
					# silent drop looks exactly like a synth ignoring them
					# (#3068).
					logger.warning(
						f"Dropped a {event.message_type} message: nothing knows how to put it on the wire. "
						f"Please report this."
					)
					return

				self._locked_send(port, msg)

			except Exception:
				# Say which number MIDI would not take.  Blaming the cable sent
				# people looking at their hardware for a pitch of 140 (#3004).
				out_of_range = [
					f"{name} {value}"
					for name, value in (
						("note", getattr(event, "note", None)),
						("velocity", getattr(event, "velocity", None)),
						("CC", getattr(event, "control", None)),
						("value", getattr(event, "value", None)),
						("channel", getattr(event, "channel", None)),
					)
					if isinstance(value, int) and not 0 <= value <= 127
				]

				if out_of_range:
					logger.exception(
						"A %s cannot be sent: %s is outside 0–127. The device is fine; the number is not.",
						event.message_type, ", ".join(out_of_range),
					)
				else:
					logger.exception("MIDI send failed (device may be disconnected)")


	async def panic (self) -> None:

		"""
		Send a MIDI panic message to all channels.
		"""

		# A render sends nothing: it closes the sounding notes in its file (#3530).
		if not self.render_mode:
			logger.info("Panic: sending all notes off.")
		
		# 1. Stop all tracked active notes manually
		await self._stop_all_active_notes()

		for port in self._output_devices:

			try:

				# Hold the send lock so an instant cc_forward on the callback
				# thread cannot interleave with the panic sweep.
				with self._port_send_lock:

					# 2. Send "All Notes Off" (CC 123) and "All Sound Off" (CC 120) to all 16 channels
					for channel in range(16):
						port.send(mido.Message('control_change', channel=channel, control=123, value=0))
						port.send(mido.Message('control_change', channel=channel, control=120, value=0))

					# 3. Use built-in panic and reset
					port.panic()

					# Note: reset() might close/reopen ports or clear internal buffers depending on backend,
					# but mido docs say it sends "All Notes Off" and "Reset All Controllers".
					port.reset()

			except Exception:
				logger.exception("MIDI panic failed (device may be disconnected)")
