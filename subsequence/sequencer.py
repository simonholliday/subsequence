import asyncio
import dataclasses
import heapq
import itertools
import datetime
import logging
import time
import typing

import mido

import subsequence.constants
import subsequence.easing
import subsequence.event_emitter
import subsequence.midi_utils


logger = logging.getLogger(__name__)


@typing.runtime_checkable
class PatternLike (typing.Protocol):

	"""
	Protocol for pattern objects that can be scheduled.
	"""

	channel: int
	length: float
	reschedule_lookahead: float
	steps: typing.Dict[int, typing.Any]


	def on_reschedule (self) -> None:

		"""
		Hook called immediately before the pattern is rescheduled.
		"""

		...


@dataclasses.dataclass (order=True)
class MidiEvent:

	"""
	Represents a MIDI event scheduled at a specific pulse.
	"""

	pulse: int
	message_type: str = dataclasses.field(compare=False)
	channel: int = dataclasses.field(compare=False)
	note: int = dataclasses.field(compare=False, default=0)
	velocity: int = dataclasses.field(compare=False, default=0)
	control: int = dataclasses.field(compare=False, default=0)
	value: int = dataclasses.field(compare=False, default=0)
	data: typing.Any = dataclasses.field(compare=False, default=None)


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
	
	The `Sequencer` maintains a stable clock (internal or external), 
	handles the scheduling of MIDI events, and triggers pattern rebuilds.
	"""

	def __init__ (
		self,
		output_device_name: typing.Optional[str] = None,
		initial_bpm: float = 125,
		input_device_name: typing.Optional[str] = None,
		clock_follow: bool = False,
		clock_output: bool = False,
		record: bool = False,
		record_filename: typing.Optional[str] = None,
		spin_wait: bool = True,
		_jitter_log: typing.Optional[typing.List[float]] = None
	) -> None:

		"""Initialize the sequencer with MIDI devices and initial BPM.

		Parameters:
			output_device_name: MIDI output device name. When omitted, auto-discovers
				available devices - uses the only device if one is found, or prompts
				the user to choose if multiple are available.
			initial_bpm: Tempo in BPM (ignored when clock_follow is True)
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
				to during playback.  Intended for the clock jitter benchmark — not
				for general use.
		"""

		if clock_follow and input_device_name is None:
			raise ValueError("clock_follow=True requires an input_device_name")

		self.output_device_name = output_device_name
		self.input_device_name = input_device_name
		self.clock_follow = clock_follow
		self.clock_output = clock_output and not clock_follow
		self.pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE

		# Recording state
		self.recording = record
		self.record_filename = record_filename
		self.recorded_events: typing.List[typing.Tuple[float, typing.Union[mido.Message, mido.MetaMessage]]] = []

		# Render mode: run as fast as possible and stop after render_bars or render_max_seconds.
		# Both limits are optional — at least one must be set (enforced in Composition.render).
		self.render_mode: bool = False
		self.render_bars: int = 0                          # 0 = no bar limit
		self.render_max_seconds: typing.Optional[float] = None  # None = no time limit
		self._render_elapsed_seconds: float = 0.0


		# CC input mapping — populated from Composition.cc_map()
		self.cc_mappings: typing.List[typing.Dict[str, typing.Any]] = []
		# Shared reference to composition.data so CC mappings can update it
		self._composition_data: typing.Dict[str, typing.Any] = {}

		# Internal state initialization (needed before set_bpm)
		self.midi_in: typing.Any = None
		self._midi_input_queue: typing.Optional[asyncio.Queue] = None
		self._input_loop: typing.Optional[asyncio.AbstractEventLoop] = None
		self._clock_tick_times: typing.List[float] = []
		self._waiting_for_start: bool = False

		self.event_queue: typing.List[MidiEvent] = []
		self.task: typing.Optional[asyncio.Task] = None
		self.start_time = 0.0
		self.pulse_count = 0
		self.current_bar: int = -1
		self.current_beat: int = -1
		self.active_notes: typing.Set[typing.Tuple[int, int]] = set()

		self.queue_lock = asyncio.Lock()
		self.pattern_lock = asyncio.Lock()
		self.reschedule_queue: typing.List[typing.Tuple[int, int, ScheduledPattern]] = []
		self._reschedule_counter = itertools.count()
		self.events = subsequence.event_emitter.EventEmitter()
		self.callback_lock = asyncio.Lock()
		self.callback_queue: typing.List[typing.Tuple[int, int, ScheduledCallback]] = []
		self._callback_counter = itertools.count()
		self.data: typing.Dict[str, typing.Any] = {}

		# Timing variables
		self.current_bpm: float = 0
		self.seconds_per_beat = 0.0
		self.seconds_per_pulse = 0.0
		self.running = False
		self._bpm_transition: typing.Optional[BpmTransition] = None
		self._spin_wait: bool = spin_wait
		# Spin threshold: sleep all the way to this many seconds before the target,
		# then busy-wait for the remainder.  1ms is enough to absorb OS wakeup latency
		# while keeping spin time short enough not to starve the event loop.
		self._spin_threshold: float = 0.001
		self._jitter_log: typing.Optional[typing.List[float]] = _jitter_log

		self.set_bpm(initial_bpm)


		self.midi_out = None
		self._init_midi_output()

		# OSC server reference — set by Composition after osc_server.start()
		self.osc_server: typing.Optional[typing.Any] = None


		# Callbacks
		self.callbacks: typing.List[typing.Callable[[int], typing.Coroutine]] = []

	def _record_event (self, pulse: int, message: typing.Union[mido.Message, mido.MetaMessage]) -> None:

		"""Record a MIDI message with an absolute pulse timestamp for later export."""

		if not self.recording:
			return

		self.recorded_events.append((float(pulse), message))

	def save_recording (self) -> None:

		"""Save the recorded session to a MIDI file."""

		if not self.recording or not self.recorded_events:
			return

		if self.record_filename:
			filename = self.record_filename
		else:
			now = datetime.datetime.now()
			filename = now.strftime("session_%Y%m%d_%H%M%S.mid")

		logger.info(f"Saving MIDI recording ({len(self.recorded_events)} events) to {filename}...")

		mid = mido.MidiFile(type=1) # Type 1 = multiple tracks (though we might just use one)
		track = mido.MidiTrack()
		mid.tracks.append(track)

		# Resolution (ticks per beat). Standard is 480.
		# Subsequence uses 24 PPQN internal.
		# To get 480 PPQN output without losing precision, we scale up by 20.
		ticks_per_pulse = 20
		mid.ticks_per_beat = 480

		# Sort events by pulse just in case
		self.recorded_events.sort(key=lambda x: x[0])

		last_pulse = 0.0

		for pulse, message in self.recorded_events:
			
			delta_pulses = pulse - last_pulse
			delta_ticks = int(delta_pulses * ticks_per_pulse)
			
			# Ensure delta is non-negative (floating point jitter?)
			if delta_ticks < 0:
				delta_ticks = 0
			
			message.time = delta_ticks
			track.append(message)

			last_pulse = pulse

		try:
			mid.save(filename)
			logger.info(f"Saved {filename}")
		except Exception as e:
			logger.error(f"Failed to save MIDI recording: {e}")

	def disable_spin_wait (self) -> None:

		"""Disable the hybrid sleep+spin timing strategy.

		By default the sequencer busy-waits for the final sub-millisecond of each
		pulse interval to minimise clock jitter.  Call this to revert to pure
		``asyncio.sleep()`` — lower CPU usage at the cost of higher jitter (typically
		±0.5–2 ms on Linux vs ±50–200 μs with spin-wait enabled).

		Can also be set at construction time: ``Sequencer(spin_wait=False)``.
		"""

		self._spin_wait = False


	def set_bpm (self, bpm: float) -> None:

		"""
		Instantly change the tempo.

		Note: If `clock_follow` is enabled and the sequencer is running,
		this method will be ignored as the tempo is slaved to the external source.
		"""

		if self.clock_follow and self.running:
			logger.info("BPM is controlled by external clock - set_bpm() ignored")
			return

		if bpm <= 0:
			raise ValueError("BPM must be positive")

		self._bpm_transition = None
		self.current_bpm = bpm
		self.seconds_per_beat = 60.0 / self.current_bpm
		self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat

		logger.info(f"BPM set to {self.current_bpm:.2f}")

		if self.recording:
			tempo = mido.bpm2tempo(self.current_bpm)
			self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=tempo))


	def set_target_bpm (self, target_bpm: float, bars: int, shape: typing.Union[str, subsequence.easing.EasingFn] = "linear") -> None:

		"""
		Smoothly transition to a new tempo over a fixed number of bars.

		Parameters:
			target_bpm: The BPM to ramp toward.
			bars: Duration of the transition in bars.
			shape: Easing curve — a name string (e.g. ``"ease_in_out"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       ``"ease_in_out"`` or ``"s_curve"`` are recommended for natural-
			       sounding tempo changes.  See :mod:`subsequence.easing`.
		"""

		if self.clock_follow and self.running:
			logger.info("BPM is controlled by external clock - set_target_bpm() ignored")
			return

		if target_bpm <= 0:
			raise ValueError("Target BPM must be positive")

		if bars <= 0:
			raise ValueError("Transition bars must be positive")

		total_pulses = bars * self.pulses_per_beat * 4

		self._bpm_transition = BpmTransition(
			start_bpm=self.current_bpm,
			target_bpm=target_bpm,
			total_pulses=total_pulses,
			easing_fn=subsequence.easing.get_easing(shape)
		)

		logger.info(f"BPM transition: {self.current_bpm:.2f} → {target_bpm:.2f} over {bars} bars ({shape!r})")


	def add_callback (self, callback: typing.Callable[[int], typing.Coroutine]) -> None:

		"""
		Add an async callback to be invoked at the start of each bar.
		"""
		
		self.callbacks.append(callback)


	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a named event.
		"""

		self.events.on(event_name, callback)


	def _init_midi_output (self) -> None:

		"""Initialize the MIDI output port.

		When ``output_device_name`` was provided, opens that device directly.
		When omitted, auto-discovers available devices: uses the only one if
		exactly one is found, or prompts the user to choose if several exist.
		"""

		# Use the helper function for device selection
		device_name, midi_out = subsequence.midi_utils.select_output_device(self.output_device_name)
		
		if device_name:
			self.output_device_name = device_name
			self.midi_out = midi_out


	def _init_midi_input (self) -> None:

		"""Initialize the MIDI input port with a callback that bridges to the asyncio queue."""

		if self.input_device_name is None:
			return

		# Use the helper function for device selection
		device_name, midi_in = subsequence.midi_utils.select_input_device(self.input_device_name, self._on_midi_input)
		
		if device_name:
			self.input_device_name = device_name
			self.midi_in = midi_in


	def _on_midi_input (self, message: typing.Any) -> None:

		"""Handle incoming MIDI messages from the input port callback thread.

		This runs in mido's callback thread. Clock/transport messages are
		forwarded to the asyncio event loop via call_soon_threadsafe.

		CC input mappings are applied immediately here.  Single dict writes
		are safe from a non-asyncio thread under CPython's GIL.
		"""

		if self._midi_input_queue is None or self._input_loop is None:
			return

		self._input_loop.call_soon_threadsafe(
			self._midi_input_queue.put_nowait, message
		)

		# Apply CC input mappings: map incoming CC values to composition.data.
		if message.type == 'control_change' and self.cc_mappings:
			for mapping in self.cc_mappings:
				if message.control != mapping['cc']:
					continue
				ch = mapping.get('channel')
				if ch is not None and message.channel != ch:
					continue
				scaled = mapping['min_val'] + (message.value / 127.0) * (mapping['max_val'] - mapping['min_val'])
				self._composition_data[mapping['key']] = scaled


	def _estimate_bpm (self, tick_time: float) -> None:

		"""Estimate BPM from recent MIDI clock tick timestamps for display purposes."""

		self._clock_tick_times.append(tick_time)

		# Keep last 48 ticks (2 beats) for averaging.
		if len(self._clock_tick_times) > 48:
			self._clock_tick_times = self._clock_tick_times[-48:]

		if len(self._clock_tick_times) >= 24:
			# Average interval over last 24 ticks (1 beat).
			recent = self._clock_tick_times[-24:]
			interval = (recent[-1] - recent[0]) / (len(recent) - 1)

			if interval > 0:
				self.current_bpm = int(round(60.0 / (interval * self.pulses_per_beat)))


	def _get_schedule_timing (self, length_beats: float, lookahead_beats: float) -> typing.Tuple[int, int]:

		"""
		Convert schedule length and reschedule lookahead from beats to pulses.
		"""

		if length_beats <= 0:
			raise ValueError("Schedule length must be positive")

		if lookahead_beats < 0:
			raise ValueError("Reschedule lookahead cannot be negative")

		if lookahead_beats > length_beats:
			raise ValueError("Reschedule lookahead cannot exceed schedule length")

		length_pulses = int(length_beats * self.pulses_per_beat)
		lookahead_pulses = int(lookahead_beats * self.pulses_per_beat)

		if length_pulses <= 0:
			raise ValueError("Schedule length must be at least one pulse")

		return length_pulses, lookahead_pulses


	def _get_pattern_timing (self, pattern: PatternLike) -> typing.Tuple[int, int]:

		"""
		Convert pattern length and reschedule lookahead from beats to pulses.
		"""

		return self._get_schedule_timing(pattern.length, pattern.reschedule_lookahead)


	async def schedule_pattern (self, pattern: PatternLike, start_pulse: int) -> None:

		"""
		Schedules a pattern's notes and CC events into the sequencer's event queue.
		"""

		async with self.queue_lock:

			for position, step in pattern.steps.items():

				abs_pulse = start_pulse + position

				for note in step.notes:

					# Note On
					on_event = MidiEvent(
						pulse = abs_pulse,
						message_type = 'note_on',
						channel = note.channel,
						note = note.pitch,
						velocity = note.velocity
					)

					heapq.heappush(self.event_queue, on_event)

					# Note Off
					off_event = MidiEvent(
						pulse = abs_pulse + note.duration,
						message_type = 'note_off',
						channel = note.channel,
						note = note.pitch,
						velocity = 0
					)

					heapq.heappush(self.event_queue, off_event)

			# CC / pitch bend events
			for cc_event in getattr(pattern, 'cc_events', []):

				abs_pulse = start_pulse + cc_event.pulse

				midi_event = MidiEvent(
					pulse = abs_pulse,
					message_type = cc_event.message_type,
					channel = pattern.channel,
					control = cc_event.control,
					value = cc_event.value,
					data = cc_event.data
				)

				heapq.heappush(self.event_queue, midi_event)

			# OSC events
			for osc_event in getattr(pattern, 'osc_events', []):

				abs_pulse = start_pulse + osc_event.pulse

				osc_midi_event = MidiEvent(
					pulse = abs_pulse,
					message_type = 'osc',
					channel = 0,
					data = (osc_event.address, osc_event.args)
				)

				heapq.heappush(self.event_queue, osc_midi_event)

		logger.debug(f"Scheduled pattern at {start_pulse}, queue size: {len(self.event_queue)}")


	async def schedule_pattern_repeating (self, pattern: PatternLike, start_pulse: int) -> None:

		"""
		Schedule a pattern and register it for rescheduling each cycle.
		"""

		length_pulses, lookahead_pulses = self._get_pattern_timing(pattern)

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
			next_fire_pulse = initial_fire_pulse
		)

		async with self.callback_lock:
			counter = next(self._callback_counter)
			heapq.heappush(self.callback_queue, (scheduled_callback.next_fire_pulse, counter, scheduled_callback))


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


	def _send_clock_message (self, message_type: str) -> None:

		"""Send a bare MIDI system-realtime message (clock, start, stop, continue).

		These messages carry no channel or data bytes — they are sent directly to
		the output port.  Used for MIDI clock output when ``clock_output`` is True.

		Parameters:
			message_type: One of ``"clock"``, ``"start"``, ``"stop"``, ``"continue"``.
		"""

		if self.midi_out:
			try:  # type: ignore[unreachable]
				self.midi_out.send(mido.Message(message_type))
			except Exception:
				logger.exception(f"Failed to send MIDI {message_type} message")


	async def start (self) -> None:

		"""Start the sequencer playback in a separate asyncio task.

		When an input device is configured, the MIDI input port is opened here
		(after the event loop is running) so that call_soon_threadsafe works.
		When ``clock_output`` is True, a MIDI Start (0xFA) message is sent before
		the first clock tick so connected hardware begins from the top.
		"""

		if self.running:
			return

		# Set up MIDI input queue before opening the port.
		if self.input_device_name is not None:
			self._input_loop = asyncio.get_running_loop()
			self._midi_input_queue = asyncio.Queue()
			self._init_midi_input()

		self._waiting_for_start = self.clock_follow
		self.running = True
		self.task = asyncio.create_task(self._run_loop())

		if self.clock_output:
			self._send_clock_message("start")

		logger.info("Sequencer started")

		await self.events.emit_async("start")


	async def stop (self) -> None:

		"""
		Stop the sequencer playback and cleanup resources.
		"""

		if not self.running and self.midi_out is None:
			return

		logger.info("Stopping sequencer...")

		self.running = False

		if self.task:
			await self.task

		if self.clock_output:
			self._send_clock_message("stop")

		await self.panic()

		if self.midi_out:
			self.midi_out.close()  # type: ignore[unreachable]
			self.midi_out = None

		if self.midi_in:
			self.midi_in.close()
			self.midi_in = None

		self._midi_input_queue = None
		self._input_loop = None

		self.save_recording()

		logger.info("Sequencer stopped")

		async with self.pattern_lock:
			self.reschedule_queue = []
			self._reschedule_counter = itertools.count()

		async with self.callback_lock:
			self.callback_queue = []
			self._callback_counter = itertools.count()

		self.active_notes = set()

		await self.events.emit_async("stop")


	async def _run_loop (self) -> None:

		"""Main playback loop - delegates to internal or external clock mode."""

		self.start_time = time.perf_counter()
		self.pulse_count = 0
		self.current_bar = -1

		pulses_per_bar = 4 * self.pulses_per_beat  # 4/4 time assumed throughout

		if self.clock_follow and self._midi_input_queue is not None:
			await self._run_loop_external_clock(pulses_per_bar)
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

			for cb in self.callbacks:
				asyncio.create_task(cb(self.current_bar))

			asyncio.create_task(self.events.emit_async("bar", self.current_bar))


	def _check_beat_change (self, pulse: int, pulses_per_beat: int) -> None:

		"""Detect beat boundaries within the bar and fire beat events."""

		beat_in_bar = (pulse % (4 * pulses_per_beat)) // pulses_per_beat

		if beat_in_bar != self.current_beat:
			self.current_beat = beat_in_bar
			asyncio.create_task(self.events.emit_async("beat", self.current_beat))


	async def _advance_pulse (self) -> None:

		"""Reschedule patterns, process events, and increment the pulse counter."""

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

			# In render mode, simulate time advancing one pulse at a time so
			# the inner loop always fires exactly once without spin-waiting.
			current_time = next_pulse_time if self.render_mode else time.perf_counter()

			while current_time >= next_pulse_time:
				# Ordering within each pulse:
				#   1. _check_bar/beat_change() — update counters and queue "bar"/"beat"
				#      event tasks (asyncio.create_task; not run yet).
				#   2. Send MIDI clock tick (if clock_output) so hardware receives it at
				#      the same time as note events for tight sync.
				#   3. _advance_pulse() — fire callbacks, then send MIDI via _process_pulse().
				#   4. After the await returns, the event loop runs the queued event tasks,
				#      which update the terminal display.
				#
				# Consequence: MIDI notes are sent *before* the display updates. The display
				# always trails the audio by roughly one pulse-processing cycle plus any
				# terminal rendering latency (~10-50 ms). This is expected and acceptable for
				# a visual status line — it cannot be tightened without restructuring the loop.
				self._check_bar_change(self.pulse_count, pulses_per_bar)
				self._check_beat_change(self.pulse_count, self.pulses_per_beat)
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
								and not self.reschedule_queue and not self.callback_queue):
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
		Transport messages (``start``, ``stop``, ``continue``) control sequencer state.
		The loop waits for a ``start`` or ``continue`` before processing clock ticks.
		"""

		assert self._midi_input_queue is not None, "MIDI input queue must be initialized for external clock"

		while self.running:

			try:
				message = await asyncio.wait_for(
					self._midi_input_queue.get(), timeout=2.0
				)
			except asyncio.TimeoutError:
				continue

			if message.type == "clock":

				# Ignore clock ticks until we receive a start or continue.
				if self._waiting_for_start:
					continue

				self._estimate_bpm(time.perf_counter())
				self._check_bar_change(self.pulse_count, pulses_per_bar)
				self._check_beat_change(self.pulse_count, self.pulses_per_beat)
				await self._advance_pulse()

			elif message.type == "start":
				logger.info("MIDI start received")
				self.pulse_count = 0
				self.current_bar = -1
				self.current_beat = -1
				self._clock_tick_times = []
				self._waiting_for_start = False

			elif message.type == "stop":
				logger.info("MIDI stop received")
				self.running = False

			elif message.type == "continue":
				logger.info("MIDI continue received")
				self._waiting_for_start = False


	async def _maybe_reschedule_patterns (self, pulse: int) -> None:

		"""
		Reschedule repeating callbacks and patterns when they reach their lookahead threshold.
		"""

		to_fire: typing.List[ScheduledCallback] = []
		to_reschedule: typing.List[ScheduledPattern] = []

		async with self.callback_lock:
            # DEBUG LOGGING
			# logger.info(f"Checking callbacks at pulse {pulse}. Queue head: {self.callback_queue[0] if self.callback_queue else 'Empty'}")

			while self.callback_queue and self.callback_queue[0][0] <= pulse:

				_, _, scheduled_callback = heapq.heappop(self.callback_queue)

				next_start_pulse = scheduled_callback.cycle_start_pulse + scheduled_callback.interval_pulses
				scheduled_callback.cycle_start_pulse = next_start_pulse
				scheduled_callback.next_fire_pulse = next_start_pulse + scheduled_callback.interval_pulses - scheduled_callback.lookahead_pulses

				to_fire.append(scheduled_callback)

		if to_fire:
			# Decision path: composition-level callbacks fire before pattern rebuilds.
			for scheduled_callback in to_fire:
				result = scheduled_callback.callback(pulse)

				if asyncio.iscoroutine(result):
					await result

		async with self.callback_lock:
			for scheduled_callback in to_fire:
				counter = next(self._callback_counter)
				heapq.heappush(self.callback_queue, (scheduled_callback.next_fire_pulse, counter, scheduled_callback))

		async with self.pattern_lock:

			while self.reschedule_queue and self.reschedule_queue[0][0] <= pulse:

				_, _, scheduled_pattern = heapq.heappop(self.reschedule_queue)

				next_start_pulse = scheduled_pattern.cycle_start_pulse + scheduled_pattern.length_pulses
				scheduled_pattern.cycle_start_pulse = next_start_pulse

				to_reschedule.append(scheduled_pattern)

		if to_reschedule:
			# Decision path: update shared composition state before pattern rebuilds.
			patterns = [scheduled_pattern.pattern for scheduled_pattern in to_reschedule]
			await self.events.emit_async("reschedule_pulse", pulse, patterns)

		for scheduled_pattern in to_reschedule:

			scheduled_pattern.pattern.on_reschedule()

			# Re-read length in case on_reschedule() changed it (e.g. via set_length).
			new_length_pulses, new_lookahead_pulses = self._get_pattern_timing(scheduled_pattern.pattern)
			scheduled_pattern.length_pulses = new_length_pulses
			scheduled_pattern.lookahead_pulses = new_lookahead_pulses
			scheduled_pattern.next_reschedule_pulse = scheduled_pattern.cycle_start_pulse + new_length_pulses - new_lookahead_pulses

			await self.schedule_pattern(scheduled_pattern.pattern, scheduled_pattern.cycle_start_pulse)
			asyncio.create_task(self.events.emit_async("pattern_reschedule", scheduled_pattern.pattern, scheduled_pattern.cycle_start_pulse))

		async with self.pattern_lock:
			for scheduled_pattern in to_reschedule:
				counter = next(self._reschedule_counter)
				heapq.heappush(self.reschedule_queue, (scheduled_pattern.next_reschedule_pulse, counter, scheduled_pattern))


	async def _process_pulse (self, pulse: int) -> None:

		"""
		Process and execute all events for a specific pulse.
		"""

		async with self.queue_lock:

			while self.event_queue and self.event_queue[0].pulse <= pulse:

				event = heapq.heappop(self.event_queue)
				
				# Track active notes
				if event.message_type == 'note_on' and event.velocity > 0:
					self.active_notes.add((event.channel, event.note))
				elif event.message_type == 'note_off' or (event.message_type == 'note_on' and event.velocity == 0):
					if (event.channel, event.note) in self.active_notes:
						self.active_notes.remove((event.channel, event.note))

				# Send events at or before the current pulse (late events are sent immediately).
				self._send_midi(event)

				if self.recording and event.message_type != 'osc':

					if event.message_type in ('note_on', 'note_off'):
						self._record_event(event.pulse, mido.Message(event.message_type, channel=event.channel, note=event.note, velocity=event.velocity))

					elif event.message_type == 'control_change':
						self._record_event(event.pulse, mido.Message('control_change', channel=event.channel, control=event.control, value=event.value))

					elif event.message_type == 'pitchwheel':
						self._record_event(event.pulse, mido.Message('pitchwheel', channel=event.channel, pitch=event.value))

					elif event.message_type == 'program_change':
						self._record_event(event.pulse, mido.Message('program_change', channel=event.channel, program=event.value))

					elif event.message_type == 'sysex':
						raw = event.data if event.data is not None else b''
						self._record_event(event.pulse, mido.Message('sysex', data=raw))


	async def _stop_all_active_notes (self) -> None:
	
		"""
		Send note_off for all currently tracked active notes.
		"""
		
		async with self.queue_lock:
			for channel, note in list(self.active_notes):
				if self.midi_out:
					self.midi_out.send(mido.Message('note_off', channel=channel, note=note, velocity=0))  # type: ignore[unreachable]
			self.active_notes.clear()


	def _send_midi (self, event: MidiEvent) -> None:

		"""
		Send a MIDI message to the output port.
		"""

		if self.midi_out:

			try:  # type: ignore[unreachable]

				if event.message_type in ('note_on', 'note_off'):
					msg = mido.Message(
						event.message_type,
						channel = event.channel,
						note = event.note,
						velocity = event.velocity
					)

				elif event.message_type == 'control_change':
					msg = mido.Message(
						'control_change',
						channel = event.channel,
						control = event.control,
						value = event.value
					)

				elif event.message_type == 'pitchwheel':
					msg = mido.Message(
						'pitchwheel',
						channel = event.channel,
						pitch = event.value
					)

				elif event.message_type == 'program_change':
					msg = mido.Message(
						'program_change',
						channel = event.channel,
						program = event.value
					)

				elif event.message_type == 'sysex':
					msg = mido.Message(
						'sysex',
						data = event.data if event.data is not None else b''
					)

				elif event.message_type == 'osc':
					if self.osc_server is not None:
						address, args = event.data
						self.osc_server.send(address, *args)
					return

				else:
					return

				self.midi_out.send(msg)

			except Exception:
				logger.exception("MIDI send failed (device may be disconnected)")


	async def panic (self) -> None:

		"""
		Send a MIDI panic message to all channels.
		"""

		logger.info("Panic: sending all notes off.")
		
		# 1. Stop all tracked active notes manually
		await self._stop_all_active_notes()

		if self.midi_out:

			try:  # type: ignore[unreachable]

				# 2. Send "All Notes Off" (CC 123) and "All Sound Off" (CC 120) to all 16 channels
				for channel in range(16):
					self.midi_out.send(mido.Message('control_change', channel=channel, control=123, value=0))
					self.midi_out.send(mido.Message('control_change', channel=channel, control=120, value=0))

				# 3. Use built-in panic and reset
				self.midi_out.panic()

				# Note: reset() might close/reopen ports or clear internal buffers depending on backend,
				# but mido docs say it sends "All Notes Off" and "Reset All Controllers".
				self.midi_out.reset()

			except Exception:
				logger.exception("MIDI panic failed (device may be disconnected)")
