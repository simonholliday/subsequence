import logging
import typing

import subsequence.chords
import subsequence.harmonic_state
import subsequence.pattern


logger = logging.getLogger(__name__)


class ChordPattern (subsequence.pattern.Pattern):

	"""
	A repeating chord pattern that follows the shared harmonic state.
	"""

	def __init__ (
		self,
		harmonic_state: subsequence.harmonic_state.HarmonicState,
		length: int = 4,
		root_midi: int = 52,
		velocity: int = 90,
		reschedule_lookahead: int = 1,
		channel: typing.Optional[int] = None
	) -> None:

		"""
		Initialize a chord pattern driven by composition-level harmony.
		"""

		if channel is None:
			# Decision path: channel is required so composition choices stay in demo.py.
			logger.error("ChordPattern requires an explicit MIDI channel")
			raise ValueError("ChordPattern requires an explicit MIDI channel")

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.key_root_midi = root_midi
		self.velocity = velocity
		self.current_chord = self.harmonic_state.get_current_chord()

		self._build_current_chord()


	def _get_chord_root_midi (self, chord: subsequence.chords.Chord) -> int:

		"""
		Calculate the MIDI root for a chord relative to the key root.
		"""

		return self.harmonic_state.get_chord_root_midi(self.key_root_midi, chord)


	def _build_current_chord (self) -> None:

		"""
		Build the current chord as a sustained voicing.
		"""

		self.steps = {}

		chord_root_midi = self._get_chord_root_midi(self.current_chord)
		chord_intervals = self.current_chord.intervals()

		# Root-position voicing: chord notes ascend from the root.
		# To add inversions later, rotate chord_intervals or adjust chord_root_midi
		# to keep voices closer between transitions.
		for interval in chord_intervals:
			self.add_note_beats(
				beat_position = 0.0,
				pitch = chord_root_midi + interval,
				velocity = self.velocity,
				duration_beats = float(self.length)
			)


	def on_reschedule (self) -> None:

		"""
		Rebuild the chord pattern from the shared harmonic state.
		"""

		# Decision path: chord changes come from harmonic_state.step in the sequencer callback.
		self.current_chord = self.harmonic_state.get_current_chord()

		self._build_current_chord()
