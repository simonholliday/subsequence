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
	steps: typing.Dict[int, typing.Any]


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


		logger.debug(f"Scheduled pattern at {start_pulse}, queue size: {len(self.event_queue)}")


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

		self.running = False

		if self.task:
			await self.task

		await self.panic()

		if self.midi_out:
			self.midi_out.close()

		logger.info("Sequencer stopped")


		self.active_notes: typing.Set[typing.Tuple[int, int]] = set()


	async def _run_loop (self) -> None:

		"""
		Main playback loop running as an asyncio task.
		"""

		self.start_time = time.perf_counter()
		self.pulse_count = 0

		while self.running:

			current_time = time.perf_counter()
			elapsed_time = current_time - self.start_time
			
			# Use cached timing values
			target_pulse = int(elapsed_time / self.seconds_per_pulse)

			while self.pulse_count <= target_pulse:
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
