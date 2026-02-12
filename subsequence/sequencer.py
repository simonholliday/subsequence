import asyncio
import dataclasses
import heapq
import logging
import time
import typing

import mido

import subsequence.constants


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
		self.active_notes: typing.Set[typing.Tuple[int, int]] = set()

		self.queue_lock = asyncio.Lock()
		self.pattern_lock = asyncio.Lock()
		self.scheduled_patterns: typing.List[ScheduledPattern] = []
		
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


	def _get_pattern_timing (self, pattern: PatternLike) -> typing.Tuple[int, int]:

		"""
		Convert pattern length and reschedule lookahead from beats to pulses.
		"""

		length_beats = pattern.length
		lookahead_beats = pattern.reschedule_lookahead

		if length_beats <= 0:
			raise ValueError("Pattern length must be positive")

		if lookahead_beats < 0:
			raise ValueError("Reschedule lookahead cannot be negative")

		if lookahead_beats > length_beats:
			raise ValueError("Reschedule lookahead cannot exceed pattern length")

		length_pulses = int(length_beats * self.pulses_per_beat)
		lookahead_pulses = int(lookahead_beats * self.pulses_per_beat)

		if length_pulses <= 0:
			raise ValueError("Pattern length must be at least one pulse")

		return length_pulses, lookahead_pulses


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

		scheduled_pattern = ScheduledPattern(
			pattern = pattern,
			cycle_start_pulse = start_pulse,
			length_pulses = length_pulses,
			lookahead_pulses = lookahead_pulses
		)

		async with self.pattern_lock:
			self.scheduled_patterns.append(scheduled_pattern)


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
			self.scheduled_patterns = []

		self.active_notes: typing.Set[typing.Tuple[int, int]] = set()


	async def _run_loop (self) -> None:

		"""
		Main playback loop running as an asyncio task.
		"""

		self.start_time = time.perf_counter()
		self.pulse_count = 0
		
		current_bar = -1
		pulses_per_bar = 4 * self.pulses_per_beat # Assuming 4/4

		while self.running:

			current_time = time.perf_counter()
			elapsed_time = current_time - self.start_time
			
			# Use cached timing values
			target_pulse = int(elapsed_time / self.seconds_per_pulse)
			
			# Check for bar change
			new_bar = target_pulse // pulses_per_bar
			if new_bar > current_bar:
				current_bar = new_bar
				for cb in self.callbacks:
					asyncio.create_task(cb(current_bar))

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
		Reschedule repeating patterns when they reach their lookahead threshold.
		"""

		to_reschedule: typing.List[typing.Tuple[PatternLike, int]] = []

		async with self.pattern_lock:

			for scheduled_pattern in self.scheduled_patterns:

				reschedule_pulse = scheduled_pattern.cycle_start_pulse + scheduled_pattern.length_pulses - scheduled_pattern.lookahead_pulses

				if pulse >= reschedule_pulse:

					next_start_pulse = scheduled_pattern.cycle_start_pulse + scheduled_pattern.length_pulses
					scheduled_pattern.cycle_start_pulse = next_start_pulse

					to_reschedule.append((scheduled_pattern.pattern, next_start_pulse))

		for pattern, start_pulse in to_reschedule:

			pattern.on_reschedule()

			await self.schedule_pattern(pattern, start_pulse)


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

				if event.pulse == pulse:
					self._send_midi(event)

				else:
					# Event is in the past, send it anyway (late)
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
