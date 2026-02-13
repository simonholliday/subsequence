import asyncio
import logging
import math
import random

import subsequence.chords
import subsequence.composition
import subsequence.constants
import subsequence.harmonic_state
import subsequence.harmony
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.sequencer


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# MIDI channel and drum note assignments (previously in subsequence.constants,
# now defined locally since they are studio-specific).
MIDI_CHANNEL_DRM1 = 9
MIDI_CHANNEL_VOCE_EP = 8
MIDI_CHANNEL_MATRIARCH = 0
MIDI_CHANNEL_MINITAUR = 5

DRM1_MKIV_KICK = 36
DRM1_MKIV_SNARE = 38
DRM1_MKIV_HH1_CLOSED = 44
DRM1_MKIV_HH1_OPEN = 46


class KickSnarePattern (subsequence.pattern.Pattern):

	"""
	A kick and snare pattern that evolves on each reschedule.
	"""

	def __init__ (self, length: int, reschedule_lookahead: int = 1) -> None:

		"""
		Initialize the kick/snare pattern and build the first cycle.
		"""

		super().__init__(
			channel = MIDI_CHANNEL_DRM1,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.rng = random.Random()
		self.cycle_count = 0

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
			pitch = DRM1_MKIV_KICK,
			velocity = 127
		)

		if self.cycle_count > 3:
			snare_sequence = [0] * steps
			snare_indices = [4, 12]

			for idx in snare_indices:
				if idx < steps:
					snare_sequence[idx] = 1

			self.add_sequence(
				snare_sequence,
				step_duration = step_duration,
				pitch = DRM1_MKIV_SNARE,
				velocity = 100
			)


	def on_reschedule (self) -> None:

		"""
		Rebuild the pattern before the next cycle is scheduled.
		"""

		self.cycle_count += 1
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
			channel = MIDI_CHANNEL_DRM1,
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
			pitch = DRM1_MKIV_HH1_CLOSED,
			velocity = hh_velocities
		)

		open_hat_step = steps - 2

		if open_hat_step >= 0 and self.rng.random() < 0.6:
			self.add_note(
				open_hat_step * step_duration,
				DRM1_MKIV_HH1_OPEN,
				85,
				step_duration
			)


	def on_reschedule (self) -> None:

		"""
		Rebuild the pattern before the next cycle is scheduled.
		"""

		self._build_pattern()


class MotifPattern (subsequence.pattern.Pattern):

	"""
	A motif pattern that follows the shared harmonic state.
	"""

	def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState, length: int, reschedule_lookahead: int, channel: int, root_midi: int = 52) -> None:

		"""
		Initialize the motif pattern with shared harmonic state.
		"""

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.root_midi = root_midi

		self._build_pattern()


	def _build_pattern (self) -> None:

		"""
		Build a cycling arpeggio based on the current chord.
		"""

		self.steps = {}

		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)
		chord_intervals = chord.intervals()[:3]

		# Decision: use chord tones so motif follows chord changes.
		pitches = [chord_root + interval for interval in chord_intervals]

		self.add_arpeggio_beats(pitches=pitches, step_beats=0.25, velocity=90)


	def on_reschedule (self) -> None:

		"""
		Rebuild the motif after the harmonic state advances.
		"""

		# Decision path: chord changes are read from harmonic_state; key changes would be handled there.
		self._build_pattern()


class BassPattern (subsequence.pattern.Pattern):

	"""
	A simple bassline that follows the composition-level harmony.
	"""

	def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState, channel: int, cycle_beats: int, step_beats: float = 1.0, note_duration_beats: float = 0.5, reschedule_lookahead: int = 1, root_midi: int = 40) -> None:

		"""
		Initialize the bass pattern with shared harmonic state.
		"""

		sequence_length = cycle_beats / step_beats
		sequence_length_int = int(round(sequence_length))

		if not math.isclose(sequence_length, sequence_length_int, rel_tol=0.0, abs_tol=1e-9):
			raise ValueError("cycle_beats must be divisible by step_beats")


		if note_duration_beats <= 0:
			raise ValueError("note_duration_beats must be positive")


		if note_duration_beats > step_beats:
			raise ValueError("note_duration_beats cannot exceed step_beats")


		sequence = [1] * sequence_length_int

		super().__init__(
			channel = channel,
			length = cycle_beats,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.root_midi = root_midi
		self.base_key_name = harmonic_state.get_key_name()
		self.step_beats = step_beats
		self.note_duration_beats = note_duration_beats
		self.sequence = sequence

		self._build_pattern()


	def _get_key_root_midi (self) -> int:

		"""
		Translate the current key into a MIDI root for the bassline.
		"""

		base_pc = subsequence.chords.NOTE_NAME_TO_PC[self.base_key_name]
		current_pc = subsequence.chords.NOTE_NAME_TO_PC[self.harmonic_state.get_key_name()]

		# Decision path: key changes transpose the bass root; chord changes do not.
		offset = (current_pc - base_pc) % 12

		return self.root_midi + offset


	def _build_pattern (self) -> None:

		"""
		Build a steady bassline anchored to the current chord root.
		"""

		self.steps = {}

		# Decision: follow the current chord root so bass updates with harmonic changes.
		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)

		# Decision: cycle length sets duration; step_beats sets note density within the cycle.
		self.add_sequence_beats(
			sequence = self.sequence,
			step_beats = self.step_beats,
			pitch = chord_root,
			velocity = 90,
			note_duration_beats = self.note_duration_beats
		)


	def on_reschedule (self) -> None:

		"""
		Rebuild the bassline after the harmonic state advances.
		"""

		# Decision path: chord changes drive bass transposition; key changes are implicit via harmonic_state.
		self._build_pattern()

async def main () -> None:

	"""
	Main entry point for the demo application.
	"""

	logger.info("Subsequence Demo starting...")

	midi_device = "Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"
	initial_bpm = 125

	seq = subsequence.sequencer.Sequencer(midi_device_name=midi_device, initial_bpm=initial_bpm)

	# Decision: E major is the global key center; key changes would be handled via harmonic_state in future.
	harmonic_state = subsequence.harmonic_state.HarmonicState(
		key_name = "E",
		graph_style = "dark_minor",
		include_dominant_7th = True,
		key_gravity_blend = 0.8,
		minor_turnaround_weight = 0.25
	)

	harmonic_cycle_beats = 4

	# Decision: schedule harmonic changes independently of any pattern, aligned to a 4-beat grid.
	await subsequence.composition.schedule_harmonic_clock(
		sequencer = seq,
		harmonic_state = harmonic_state,
		cycle_beats = harmonic_cycle_beats,
		reschedule_lookahead = 1
	)

	# Decision: 4-beat kick/snare anchors the groove.
	kick_snare = KickSnarePattern(length=4, reschedule_lookahead=1)
	# Decision: 5-beat hats create a subtle polyrhythm against the 4-beat core.
	hats = HatPattern(length=5, reschedule_lookahead=1)
	chords = subsequence.harmony.ChordPattern(
		harmonic_state = harmonic_state,
		length = harmonic_cycle_beats,
		root_midi = 52,
		velocity = 90,
		reschedule_lookahead = 1,
		# Decision: assign the harmonic layer to the EP channel explicitly.
		channel = MIDI_CHANNEL_VOCE_EP
	)
	# Decision: add a swung motif layer for contrast.
	motif = MotifPattern(
		harmonic_state = harmonic_state,
		length = harmonic_cycle_beats,
		reschedule_lookahead = 1,
		# Decision: place the motif on MATRIARCH to keep it distinct from chords.
		channel = MIDI_CHANNEL_MATRIARCH,
		root_midi = 76
	)
	# Decision: add a steady chord-root bassline to reinforce harmony (chord changes, not key changes).
	bass = BassPattern(
		harmonic_state = harmonic_state,
		# Decision: place the bass on MINITAUR for a dedicated low-end voice.
		channel = MIDI_CHANNEL_MINITAUR,
		# Decision: match the chord cycle length so bass updates on every chord change.
		cycle_beats = harmonic_cycle_beats,
		# Decision: 16th-note grid inside each cycle for a busier bassline.
		step_beats = 0.25,
		note_duration_beats = 0.2,
		reschedule_lookahead = 1,
		root_midi = 28
	)

	await subsequence.composition.schedule_patterns(
		sequencer = seq,
		patterns = [kick_snare, hats, chords, motif, bass],
		start_pulse = 0
	)

	async def on_bar (bar: int) -> None:

		"""
		Log the current bar for visibility.
		"""

		logger.info(f"Bar {bar + 1}")

	seq.add_callback(on_bar)

	await subsequence.composition.run_until_stopped(seq)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
