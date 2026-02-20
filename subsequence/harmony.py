import logging
import typing

import subsequence.chords
import subsequence.constants.velocity
import subsequence.harmonic_state
import subsequence.intervals
import subsequence.pattern
import subsequence.voicings


logger = logging.getLogger(__name__)


def diatonic_chords (key: str, mode: str = "ionian") -> typing.List[subsequence.chords.Chord]:

	"""Return the 7 diatonic triads for a key and mode.

	This is a convenience function for generating chord sequences without
	using the chord graph engine. The returned ``Chord`` objects can be
	passed directly to ``p.chord()`` or ``chord.tones()`` inside a pattern.

	Parameters:
		key: Note name for the key (e.g., ``"C"``, ``"Eb"``, ``"F#"``).
		mode: One of ``"ionian"`` (or ``"major"``), ``"dorian"``,
			``"phrygian"``, ``"lydian"``, ``"mixolydian"``,
			``"aeolian"`` (or ``"minor"``), ``"locrian"``,
			``"harmonic_minor"``, ``"melodic_minor"``.

	Returns:
		List of 7 ``Chord`` objects, one per scale degree.

	Example:
		```python
		from subsequence.harmony import diatonic_chords

		# All 7 chords in Eb Major
		chords = diatonic_chords("Eb")

		# Natural minor chords in A
		chords = diatonic_chords("A", mode="minor")

		# Dorian chords in D
		chords = diatonic_chords("D", mode="dorian")
		```
	"""

	if mode not in subsequence.intervals.DIATONIC_MODE_MAP:
		available = ", ".join(sorted(subsequence.intervals.DIATONIC_MODE_MAP.keys()))
		raise ValueError(f"Unknown mode: {mode!r}. Available: {available}")

	scale_key, qualities = subsequence.intervals.DIATONIC_MODE_MAP[mode]
	scale_intervals = subsequence.intervals.get_intervals(scale_key)

	if key not in subsequence.chords.NOTE_NAME_TO_PC:
		raise ValueError(f"Unknown key name: {key!r}")

	key_pc = subsequence.chords.NOTE_NAME_TO_PC[key]

	chords: typing.List[subsequence.chords.Chord] = []

	for degree in range(7):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(subsequence.chords.Chord(root_pc=root_pc, quality=qualities[degree]))

	return chords



class ChordPattern (subsequence.pattern.Pattern):

	"""
	A repeating chord pattern that follows the shared harmonic state.
	"""

	def __init__ (
		self,
		harmonic_state: subsequence.harmonic_state.HarmonicState,
		length: int = 4,
		root_midi: int = 52,
		velocity: int = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY,
		reschedule_lookahead: int = 1,
		channel: typing.Optional[int] = None,
		voice_leading: bool = False
	) -> None:

		"""Initialize a chord pattern driven by composition-level harmony.

		Parameters:
			harmonic_state: Shared harmonic state that provides chord changes
			length: Pattern length in beats (default 4)
			root_midi: Base MIDI note number for the chord root (default 52)
			velocity: MIDI velocity 0-127 (default 90)
			reschedule_lookahead: Reschedule lookahead in beats (default 1)
			channel: MIDI channel (0-15, required)
			voice_leading: When True, each chord automatically picks the
				inversion closest to the previous chord for smooth movement
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
		self._voice_leading_state: typing.Optional[subsequence.voicings.VoiceLeadingState] = (
			subsequence.voicings.VoiceLeadingState() if voice_leading else None
		)

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

		if self._voice_leading_state is not None:
			pitches = self._voice_leading_state.next(chord_intervals, chord_root_midi)
		else:
			pitches = [chord_root_midi + interval for interval in chord_intervals]

		for pitch in pitches:
			self.add_note_beats(
				beat_position = 0.0,
				pitch = pitch,
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
