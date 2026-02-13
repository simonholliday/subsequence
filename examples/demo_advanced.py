import asyncio
import json
import logging
import random
import typing
import urllib.request

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

	def __init__ (self, data: typing.Dict[str, typing.Any], length: int, reschedule_lookahead: int = 1) -> None:

		"""
		Initialize the kick/snare pattern and build the first cycle.
		"""

		super().__init__(
			channel = MIDI_CHANNEL_DRM1,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.data = data
		self.rng = random.Random()
		self.cycle_count = 0

		self._build_pattern()


	def _build_pattern (self) -> None:

		"""
		Build a 16-step kick/snare cycle with evolving snare.
		"""

		self.steps = {}

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		# Fixed four-on-the-floor kick — steps 0, 4, 8, 12 on a 16-step grid.
		kick_sequence = [0] * 16
		for idx in [0, 4, 8, 12]:
			kick_sequence[idx] = 1

		self.add_sequence(
			kick_sequence,
			step_duration = step_duration,
			pitch = DRM1_MKIV_KICK,
			velocity = 127
		)

		# Euclidean snare: ISS longitude modulates max density.
		if self.cycle_count > 3:
			nl = self.data.get("longitude_norm", 0.5)
			max_snare_hits = max(2, round(nl * 8))
			snare_hits = self.rng.randint(1, max_snare_hits)
			snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, snare_hits)
			snare_indices = subsequence.sequence_utils.sequence_to_indices(snare_seq)
			snare_indices = subsequence.sequence_utils.roll(snare_indices, 4, 16)

			snare_sequence = [0] * 16
			for idx in snare_indices:
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
		Build a 16-step hi-hat cycle with stochastic accents.
		"""

		self.steps = {}

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		# 8 hits distributed across 16 steps via Bresenham.
		hh_sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=16, pulses=8)

		# Van der Corput velocity shaping for organic feel.
		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(n=16, base=2)
		hh_velocities = [int(60 + (v * 40)) for v in vdc_values]

		# Stochastic dropout.
		for i in range(16):

			if hh_sequence[i] and self.rng.random() < 0.1:
				hh_sequence[i] = 0

		self.add_sequence(
			hh_sequence,
			step_duration = step_duration,
			pitch = DRM1_MKIV_HH1_CLOSED,
			velocity = hh_velocities
		)

		# Occasional open hat at step 14 (beat 3.5).
		if self.rng.random() < 0.6:
			self.add_note(
				14 * step_duration,
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
	A 16-step bassline that follows the composition-level harmony.
	"""

	def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState, channel: int, length: int = 4, reschedule_lookahead: int = 1, root_midi: int = 40) -> None:

		"""
		Initialize the bass pattern with shared harmonic state.
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
		Build a 16-step bassline anchored to the current chord root.
		"""

		self.steps = {}

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)

		# Fill all 16 steps with the chord root.
		bass_sequence = [1] * 16

		self.add_sequence(
			bass_sequence,
			step_duration = step_duration,
			pitch = chord_root,
			velocity = 90,
			note_duration = 5
		)


	def on_reschedule (self) -> None:

		"""
		Rebuild the bassline after the harmonic state advances.
		"""

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

	# ─── External Data ───────────────────────────────────────────────────

	def fetch_iss () -> None:

		"""Fetch ISS position and normalize lat/long to 0-1 range."""

		try:
			request = urllib.request.urlopen("https://api.wheretheiss.at/v1/satellites/25544", timeout=5)
			body = json.loads(request.read())
			seq.data["latitude_norm"] = (body["latitude"] + 52) / 104.0
			seq.data["longitude_norm"] = (body["longitude"] + 180) / 360.0
			logger.info(f"ISS lat={body['latitude']:.1f} lon={body['longitude']:.1f}")

		except Exception as exc:
			logger.warning(f"ISS fetch failed (keeping last value): {exc}")

	await subsequence.composition.schedule_task(sequencer=seq, fn=fetch_iss, cycle_beats=32)

	# Decision: all percussion on a unified 4-beat / 16-step grid.
	kick_snare = KickSnarePattern(data=seq.data, length=4, reschedule_lookahead=1)
	hats = HatPattern(length=4, reschedule_lookahead=1)
	chords = subsequence.harmony.ChordPattern(
		harmonic_state = harmonic_state,
		length = harmonic_cycle_beats,
		root_midi = 52,
		velocity = 90,
		reschedule_lookahead = 1,
		# Decision: assign the harmonic layer to the EP channel explicitly.
		channel = MIDI_CHANNEL_VOCE_EP
	)
	# Decision: arpeggio on MATRIARCH, cycling through chord tones across 16 steps.
	motif = MotifPattern(
		harmonic_state = harmonic_state,
		length = harmonic_cycle_beats,
		reschedule_lookahead = 1,
		channel = MIDI_CHANNEL_MATRIARCH,
		root_midi = 76
	)
	# Decision: 16-step bassline on MINITAUR, filling every step with the chord root.
	bass = BassPattern(
		harmonic_state = harmonic_state,
		channel = MIDI_CHANNEL_MINITAUR,
		length = harmonic_cycle_beats,
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
