import asyncio
import dataclasses
import heapq
import itertools
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
	length: int
	reschedule_lookahead: int
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


class Sequencer:

	"""
	Plays any scheduled patterns with a rock-solid stable clock.
	"""

	def __init__ (self, midi_device_name: str, initial_bpm: int = 125) -> None:

		"""
		Initialize the sequencer with a MIDI device and initial BPM.
		"""

		self.midi_device_name = midi_device_name
		self.pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE
		
		# Timing variables
		self.current_bpm = 0
		self.seconds_per_beat = 0.0
		self.seconds_per_pulse = 0.0
		
		self.set_bpm(initial_bpm)

		self.midi_out = None
		self._init_midi()

		self.event_queue: typing.List[MidiEvent] = []
		self.running = False
		self.task = None
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

		# Callbacks
		self.callbacks: typing.List[typing.Callable[[int], typing.Coroutine]] = []


	def set_bpm (self, bpm: int) -> None:

		"""
		Set the tempo and recalculate timing constants.
		"""
		
		if bpm <= 0:
			raise ValueError("BPM must be positive")
			
		self.current_bpm = bpm
		self.seconds_per_beat = 60.0 / self.current_bpm
		self.seconds_per_pulse = self.seconds_per_beat / self.pulses_per_beat
		
		logger.info(f"BPM set to {self.current_bpm}")


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


	def _init_midi (self) -> None:

		"""
		Initialize the MIDI output port.
		"""

		try:

			outputs = mido.get_output_names()

			logger.info(f"Available MIDI outputs: {outputs}")

			if self.midi_device_name in outputs:
				self.midi_out = mido.open_output(self.midi_device_name)
				logger.info(f"Opened MIDI output: {self.midi_device_name}")

			else:
				logger.warning(f"MIDI device '{self.midi_device_name}' not found.")

				if outputs:
					self.midi_out = mido.open_output(outputs[0])
					logger.warning(f"Fallback to: {outputs[0]}")

		except Exception as e:
			logger.error(f"Failed to open MIDI output: {e}")


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

		"""
		Start the sequencer playback in a separate asyncio task.
		"""

		if self.running:
			return

		self.running = True
		self.task = asyncio.create_task(self._run_loop())

		logger.info("Sequencer started")

		await self.events.emit_async("start")


	async def stop (self) -> None:

		"""
		Stop the sequencer playback and cleanup resources.
		"""

		logger.info("Stopping sequencer...")

		self.running = False

		if self.task:
			await self.task

		await self.panic()

		if self.midi_out:
			self.midi_out.close()

		logger.info("Sequencer stopped")

		async with self.pattern_lock:
			self.reschedule_queue = []
			self._reschedule_counter = itertools.count()

		async with self.callback_lock:
			self.callback_queue = []
			self._callback_counter = itertools.count()

		self.active_notes: typing.Set[typing.Tuple[int, int]] = set()

		await self.events.emit_async("stop")


	async def _run_loop (self) -> None:

		"""
		Main playback loop running as an asyncio task.
		"""

		self.start_time = time.perf_counter()
		self.pulse_count = 0
		self.current_bar = -1

		pulses_per_bar = 4 * self.pulses_per_beat  # 4/4 time assumed throughout

		while self.running:

			current_time = time.perf_counter()
			elapsed_time = current_time - self.start_time

			# Use cached timing values
			target_pulse = int(elapsed_time / self.seconds_per_pulse)

			# Check for bar change
			new_bar = target_pulse // pulses_per_bar
			if new_bar > self.current_bar:
				self.current_bar = new_bar
				for cb in self.callbacks:
					asyncio.create_task(cb(self.current_bar))
				asyncio.create_task(self.events.emit_async("bar", self.current_bar))

			while self.pulse_count <= target_pulse:
				await self._maybe_reschedule_patterns(self.pulse_count)
				await self._process_pulse(self.pulse_count)
				self.pulse_count += 1
			
			# Check if queue is empty and we are past the last event
			async with self.queue_lock:
				if not self.event_queue and not self.active_notes:
					logger.info("Sequence complete (no more events or active notes).")
					self.running = False
					break

			next_pulse_target_time = (self.pulse_count * self.seconds_per_pulse) + self.start_time
			sleep_time = next_pulse_target_time - time.perf_counter()

			if sleep_time > 0:
				await asyncio.sleep(max(0, sleep_time))


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


	async def _stop_all_active_notes (self) -> None:
	
		"""
		Send note_off for all currently tracked active notes.
		"""
		
		async with self.queue_lock:
			for channel, note in list(self.active_notes):
				if self.midi_out:
					self.midi_out.send(mido.Message('note_off', channel=channel, note=note, velocity=0))
			self.active_notes.clear()


	def _send_midi (self, event: MidiEvent) -> None:

		"""
		Send a MIDI message to the output port.
		"""

		if self.midi_out:

			msg = mido.Message(
				event.message_type,
				channel = event.channel,
				note = event.note,
				velocity = event.velocity
			)

			self.midi_out.send(msg)


	async def panic (self) -> None:

		"""
		Send a MIDI panic message to all channels.
		"""

		logger.info("Panic: sending all notes off.")
		
		# 1. Stop all tracked active notes manually
		await self._stop_all_active_notes()

		if self.midi_out:
			
			# 2. Send "All Notes Off" (CC 123) and "All Sound Off" (CC 120) to all 16 channels
			for channel in range(16):
				self.midi_out.send(mido.Message('control_change', channel=channel, control=123, value=0))
				self.midi_out.send(mido.Message('control_change', channel=channel, control=120, value=0))

			# 3. Use built-in panic and reset
			self.midi_out.panic()
			
			# Note: reset() might close/reopen ports or clear internal buffers depending on backend,
			# but mido docs say it sends "All Notes Off" and "Reset All Controllers".
			self.midi_out.reset()
