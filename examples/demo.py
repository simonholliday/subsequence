import asyncio
import logging
import os
import random
import signal

import yaml

import subsequence.constants
import subsequence.harmony
import subsequence.motif
import subsequence.pattern
import subsequence.sequencer
import subsequence.sequence_utils


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config (config_path: str = 'config.yaml') -> dict:

	"""
	Load configuration from a YAML file.
	"""

	if not os.path.exists(config_path):
		logger.warning(f"Config file {config_path} not found. Using defaults.")
		return {}

	with open(config_path, 'r') as f:
		return yaml.safe_load(f)


class KickSnarePattern (subsequence.pattern.Pattern):

	"""
	A kick and snare pattern that evolves on each reschedule.
	"""

	def __init__ (self, length: int, reschedule_lookahead: int = 1) -> None:

		"""
		Initialize the kick/snare pattern and build the first cycle.
		"""

		super().__init__(
			channel = subsequence.constants.MIDI_CHANNEL_DRM1,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.rng = random.Random()

		self._build_pattern()


	def _build_pattern (self) -> None:

		"""
		Build a new kick/snare cycle with light variation.
		"""

		self.steps = {}

		steps = self.length * 4
		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		kick_hits = max(1, steps // 4)
		kick_sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=steps, pulses=kick_hits)

		for i in range(steps):

			if kick_sequence[i] and self.rng.random() < 0.2:
				kick_sequence[i] = 0

		self.add_sequence(
			kick_sequence,
			step_duration = step_duration,
			pitch = subsequence.constants.DRM1_MKIV_KICK,
			velocity = 105
		)

		snare_sequence = [0] * steps
		snare_indices = [4, 12]

		for idx in snare_indices:
			if idx < steps:
				snare_sequence[idx] = 1

		self.add_sequence(
			snare_sequence,
			step_duration = step_duration,
			pitch = subsequence.constants.DRM1_MKIV_SNARE,
			velocity = 100
		)


	def on_reschedule (self) -> None:

		"""
		Rebuild the pattern before the next cycle is scheduled.
		"""

		self._build_pattern()


class HatPattern (subsequence.pattern.Pattern):

	"""
	A hi-hat pattern with evolving velocities and occasional open hats.
	"""

	def __init__ (self, length: int, reschedule_lookahead: int = 1) -> None:

		"""
		Initialize the hi-hat pattern and build the first cycle.
		"""

		super().__init__(
			channel = subsequence.constants.MIDI_CHANNEL_DRM1,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.rng = random.Random()

		self._build_pattern()


	def _build_pattern (self) -> None:

		"""
		Build a new hi-hat cycle with stochastic accents.
		"""

		self.steps = {}

		steps = self.length * 4
		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		hat_hits = max(1, steps // 2)
		hh_sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=steps, pulses=hat_hits)

		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(n=steps, base=2)
		hh_velocities = [int(60 + (v * 40)) for v in vdc_values]

		for i in range(steps):

			if hh_sequence[i] and self.rng.random() < 0.1:
				hh_sequence[i] = 0

		self.add_sequence(
			hh_sequence,
			step_duration = step_duration,
			pitch = subsequence.constants.DRM1_MKIV_HH1_CLOSED,
			velocity = hh_velocities
		)

		open_hat_step = steps - 2

		if open_hat_step >= 0 and self.rng.random() < 0.6:
			self.add_note(
				open_hat_step * step_duration,
				subsequence.constants.DRM1_MKIV_HH1_OPEN,
				85,
				step_duration
			)


	def on_reschedule (self) -> None:

		"""
		Rebuild the pattern before the next cycle is scheduled.
		"""

		self._build_pattern()


def generate_motif_pattern () -> subsequence.pattern.Pattern:

	"""
	Generate a simple swung motif pattern.
	"""

	motif = subsequence.motif.Motif()

	# Decision: use a compact four-note shape to add a gentle melodic layer.
	root = 52
	notes = [root, root + 4, root + 7, root + 12]
	beat_positions = [0.0, 0.5, 1.0, 1.5]

	for beat_position, pitch in zip(beat_positions, notes):
		motif.add_note_beats(beat_position=beat_position, pitch=pitch, velocity=90, duration_beats=0.5)

	pattern = motif.to_pattern(
		# Decision: place the motif on MODEL_D to separate it from the VOCE chords.
		channel = subsequence.constants.MIDI_CHANNEL_MODEL_D,
		length_beats = 4,
		reschedule_lookahead = 1
	)

	# Decision: swing adds a humanized feel to the motif without changing the rhythm grid.
	pattern.apply_swing(swing_ratio=2.0)

	return pattern


async def main () -> None:

	"""
	Main entry point for the demo application.
	"""

	logger.info("Subsequence Demo starting...")

	config = load_config()

	midi_device = config.get('midi', {}).get('device_name', 'Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0')
	initial_bpm = config.get('sequencer', {}).get('initial_bpm', 125)

	seq = subsequence.sequencer.Sequencer(midi_device_name=midi_device, initial_bpm=initial_bpm)

	# Decision: 4-beat kick/snare anchors the groove.
	kick_snare = KickSnarePattern(length=4, reschedule_lookahead=1)
	# Decision: 5-beat hats create a subtle polyrhythm against the 4-beat core.
	hats = HatPattern(length=5, reschedule_lookahead=1)
	chords = subsequence.harmony.ChordPattern(
		# Decision: E major establishes the harmonic center for the VOCE.
		key_name = "E",
		length = 4,
		root_midi = 52,
		velocity = 90,
		reschedule_lookahead = 1,
		include_dominant_7th = True,
		# Decision: assign the harmonic layer to the VOCE EP channel explicitly.
		channel = subsequence.constants.MIDI_CHANNEL_VOCE_EP,
		# Decision: explicit graph choice makes it easy to experiment.
		graph_style = "turnaround_global",
#		graph_style = "functional_major",
		# Decision: blend functional and full diatonic gravity toward stability.
		key_gravity_blend = 0.8,
		# Decision: allow minor turnarounds but keep them relatively rare.
		minor_turnaround_weight = 0.25
	)
	# Decision: add a swung motif layer for contrast.
	motif = generate_motif_pattern()

	await seq.schedule_pattern_repeating(kick_snare, start_pulse=0)
	await seq.schedule_pattern_repeating(hats, start_pulse=0)
	await seq.schedule_pattern_repeating(chords, start_pulse=0)
	await seq.schedule_pattern_repeating(motif, start_pulse=0)

	async def on_bar (bar: int) -> None:

		"""
		Log the current bar for visibility.
		"""

		logger.info(f"Bar {bar + 1}")

	seq.add_callback(on_bar)

	logger.info("Playing sequence. Press Ctrl+C to stop.")

	await seq.start()

	stop_event = asyncio.Event()
	loop = asyncio.get_running_loop()

	def _request_stop () -> None:

		"""
		Signal handler to request a clean shutdown.
		"""

		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(sig, _request_stop)

	await asyncio.wait(
		[asyncio.create_task(stop_event.wait()), seq.task],
		return_when = asyncio.FIRST_COMPLETED
	)

	await seq.stop()


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
