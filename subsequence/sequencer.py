import dataclasses
import heapq
import logging
import threading
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
		self.current_bpm = initial_bpm
		self.pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE

		self.midi_out = None
		self._init_midi()

		self.event_queue: typing.List[MidiEvent] = []
		self.running = False
		self.thread = None
		self.start_time = 0.0
		self.pulse_count = 0

		self.queue_lock = threading.Lock()


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


	def schedule_pattern (self, pattern: PatternLike, start_pulse: int) -> None:

		"""
		Schedules a pattern's notes into the sequencer's event queue.
		"""

		with self.queue_lock:

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


	def start (self) -> None:

		"""
		Start the sequencer playback in a separate thread.
		"""

		if self.running:
			return

		self.running = True
		self.thread = threading.Thread(target=self._run_loop, daemon=True)
		self.thread.start()

		logger.info("Sequencer started")


	def stop (self) -> None:

		"""
		Stop the sequencer playback and cleanup resources.
		"""

		self.running = False

		if self.thread:
			self.thread.join(timeout=1.0)

		self.panic()

		if self.midi_out:
			self.midi_out.close()

		logger.info("Sequencer stopped")


	def _run_loop (self) -> None:

		"""
		Main playback loop running in a separate thread.
		"""

		self.start_time = time.perf_counter()
		self.pulse_count = 0

		while self.running:

			current_time = time.perf_counter()
			elapsed_time = current_time - self.start_time

			seconds_per_beat = 60.0 / self.current_bpm
			seconds_per_pulse = seconds_per_beat / self.pulses_per_beat

			target_pulse = int(elapsed_time / seconds_per_pulse)

			while self.pulse_count <= target_pulse:
				self._process_pulse(self.pulse_count)
				self.pulse_count += 1

			next_pulse_target_time = (self.pulse_count * seconds_per_pulse) + self.start_time
			sleep_time = next_pulse_target_time - time.perf_counter()

			if sleep_time > 0:
				time.sleep(max(0, sleep_time))


	def _process_pulse (self, pulse: int) -> None:

		"""
		Process and execute all events for a specific pulse.
		"""

		with self.queue_lock:

			while self.event_queue and self.event_queue[0].pulse <= pulse:

				event = heapq.heappop(self.event_queue)

				if event.pulse == pulse:
					self._send_midi(event)

				else:
					# Event is in the past, send it anyway (late)
					self._send_midi(event)


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


	def panic (self) -> None:

		"""
		Send a MIDI panic message to all channels.
		"""

		if self.midi_out:
			self.midi_out.panic()
