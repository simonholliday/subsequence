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
import subsequence.event_emitter


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
	note: int = dataclasses.field(compare=False)
	velocity: int = dataclasses.field(compare=False)


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
		record: bool = False,
		record_filename: typing.Optional[str] = None
	) -> None:

		"""Initialize the sequencer with MIDI devices and initial BPM.

		Parameters:
			output_device_name: MIDI output device name. When omitted, auto-discovers
				available devices - uses the only device if one is found, or prompts
				the user to choose if multiple are available.
			initial_bpm: Tempo in BPM (ignored when clock_follow is True)
			input_device_name: Optional MIDI input device name for clock/transport
			clock_follow: When True, follow external MIDI clock instead of internal clock
			record: When True, record all MIDI events to a file.
			record_filename: Optional filename for the recording (defaults to timestamp).
		"""

		if clock_follow and input_device_name is None:
			raise ValueError("clock_follow=True requires an input_device_name")

		self.output_device_name = output_device_name
		self.input_device_name = input_device_name
		self.clock_follow = clock_follow
		self.pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE

		# Recording state
		self.recording = record
		self.record_filename = record_filename
		self.recorded_events: typing.List[typing.Tuple[float, typing.Union[mido.Message, mido.MetaMessage]]] = []


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

		self.set_bpm(initial_bpm)


		self.midi_out = None
		self._init_midi_output()


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

		logger.info(f"BPM set to {self.current_bpm}")

		if self.recording:
			tempo = mido.bpm2tempo(self.current_bpm)
			self._record_event(self.pulse_count, mido.MetaMessage('set_tempo', tempo=tempo))


	def set_target_bpm (self, target_bpm: float, bars: int) -> None:

		"""
		Smoothly transition to a new tempo over a fixed number of bars.
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
			elapsed_pulses=0
		)

		logger.info(f"BPM transition: {self.current_bpm:.2f} → {target_bpm:.2f} over {bars} bars")


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

		try:

			outputs = mido.get_output_names()
			logger.info(f"Available MIDI outputs: {outputs}")

			if not outputs:
				logger.error("No MIDI output devices found.")
				return

			# Explicit device requested.
			if self.output_device_name is not None:

				if self.output_device_name in outputs:
					self.midi_out = mido.open_output(self.output_device_name)
					logger.info(f"Opened MIDI output: {self.output_device_name}")
				else:
					logger.error(
						f"MIDI output device '{self.output_device_name}' not found. "
						f"Available devices: {outputs}"
					)

				return

			# Auto-discover: one device - use it.
			if len(outputs) == 1:
				self.output_device_name = outputs[0]
				self.midi_out = mido.open_output(self.output_device_name)
				logger.info(f"One MIDI output found - using '{self.output_device_name}'")
				return

			# Auto-discover: multiple devices - prompt user.
			print("\nAvailable MIDI output devices:\n")

			for i, name in enumerate(outputs, 1):
				print(f"  {i}. {name}")

			print()

			while True:
				try:
					choice = int(input(f"Select a device (1-{len(outputs)}): "))
					if 1 <= choice <= len(outputs):
						break
				except (ValueError, EOFError):
					pass
				print(f"Enter a number between 1 and {len(outputs)}.")

			self.output_device_name = outputs[choice - 1]
			self.midi_out = mido.open_output(self.output_device_name)
			logger.info(f"Opened MIDI output: {self.output_device_name}")

			print(f"\nTip: To skip this prompt, pass the device name directly:\n")
			print(f"  Sequencer(output_device_name=\"{self.output_device_name}\")")
			print(f"  Composition(output_device=\"{self.output_device_name}\")\n")

		except Exception as e:
			logger.error(f"Failed to open MIDI output: {e}")


	def _init_midi_input (self) -> None:

		"""Initialize the MIDI input port with a callback that bridges to the asyncio queue."""

		if self.input_device_name is None:
			return

		try:

			inputs = mido.get_input_names()

			logger.info(f"Available MIDI inputs: {inputs}")

			target = self.input_device_name

			if target not in inputs:
				logger.warning(f"MIDI input device '{target}' not found.")

				if inputs:
					target = inputs[0]
					logger.warning(f"Fallback to: {target}")
				else:
					return

			self.midi_in = mido.open_input(target, callback=self._on_midi_input)
			logger.info(f"Opened MIDI input: {target}")

		except Exception as e:
			logger.error(f"Failed to open MIDI input: {e}")


	def _on_midi_input (self, message: typing.Any) -> None:

		"""Handle incoming MIDI messages from the input port callback thread.

		This runs in mido's callback thread. Messages are forwarded to the
		asyncio event loop via call_soon_threadsafe.
		"""

		if self._midi_input_queue is None or self._input_loop is None:
			return

		self._input_loop.call_soon_threadsafe(
			self._midi_input_queue.put_nowait, message
		)


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
		Schedules a pattern's notes into the sequencer's event queue.
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

		next_fire_pulse = start_pulse + interval_pulses - lookahead_pulses

		scheduled_callback = ScheduledCallback(
			callback = callback,
			cycle_start_pulse = start_pulse,
			interval_pulses = interval_pulses,
			lookahead_pulses = lookahead_pulses,
			next_fire_pulse = next_fire_pulse
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


	async def start (self) -> None:

		"""Start the sequencer playback in a separate asyncio task.

		When an input device is configured, the MIDI input port is opened here
		(after the event loop is running) so that call_soon_threadsafe works.
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

			for cb in self.callbacks:
				asyncio.create_task(cb(self.current_bar))

			asyncio.create_task(self.events.emit_async("bar", self.current_bar))


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
				interpolated = (
					self._bpm_transition.start_bpm +
					(self._bpm_transition.target_bpm - self._bpm_transition.start_bpm) * progress
				)
				self.current_bpm = interpolated
				self.seconds_per_beat = 60.0 / self.current_bpm
				self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat

		await self._maybe_reschedule_patterns(self.pulse_count)
		await self._process_pulse(self.pulse_count)
		self.pulse_count += 1


	async def _run_loop_internal_clock (self, pulses_per_bar: int) -> None:

		"""Playback loop driven by the internal wall clock."""

		next_pulse_time = self.start_time

		while self.running:

			current_time = time.perf_counter()

			while current_time >= next_pulse_time:
				self._check_bar_change(self.pulse_count, pulses_per_bar)
				await self._advance_pulse()
				next_pulse_time += self.seconds_per_pulse

			# Check if queue is empty and we are past the last event
			async with self.queue_lock:
				if not self.event_queue and not self.active_notes:
					logger.info("Sequence complete (no more events or active notes).")
					self.running = False
					break

			sleep_time = next_pulse_time - time.perf_counter()

			if sleep_time > 0:
				await asyncio.sleep(sleep_time)


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
				await self._advance_pulse()

			elif message.type == "start":
				logger.info("MIDI start received")
				self.pulse_count = 0
				self.current_bar = -1
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

				if self.recording and (event.message_type == 'note_on' or event.message_type == 'note_off'):
					self._record_event(event.pulse, mido.Message(event.message_type, channel=event.channel, note=event.note, velocity=event.velocity))


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

				msg = mido.Message(
					event.message_type,
					channel = event.channel,
					note = event.note,
					velocity = event.velocity
				)

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
