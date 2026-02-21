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

	_, qualities = subsequence.intervals.DIATONIC_MODE_MAP[mode]
	key_pc = subsequence.chords.key_name_to_pc(key)
	scale_pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)

	return [
		subsequence.chords.Chord(root_pc=root_pc, quality=quality)
		for root_pc, quality in zip(scale_pcs, qualities)
	]


def diatonic_chord_sequence (
	key: str,
	root_midi: int,
	count: int,
	mode: str = "ionian"
) -> typing.List[typing.Tuple[subsequence.chords.Chord, int]]:

	"""Return a list of ``(Chord, midi_root)`` tuples stepping diatonically upward.

	Useful for mapping a continuous value (like altitude or brightness) to a
	chord, or for building explicit rising/falling progressions without using
	the chord graph engine.

	The returned list has ``count`` entries. Each entry contains the ``Chord``
	object (quality and pitch class) and the exact MIDI note number to use as
	that chord's root. Pass both directly to ``p.chord(chord, root=midi_root)``.

	Counts larger than 7 wrap into higher octaves automatically. The sequence
	always steps upward — reverse the list for a falling sequence.

	Parameters:
		key: Note name for the key (e.g., ``"D"``, ``"Eb"``, ``"F#"``).
		root_midi: MIDI note number for the first chord's root. Must fall on a
			scale degree of the chosen key and mode.
		count: Number of ``(Chord, midi_root)`` pairs to generate.
		mode: One of ``"ionian"`` (or ``"major"``), ``"dorian"``,
			``"phrygian"``, ``"lydian"``, ``"mixolydian"``,
			``"aeolian"`` (or ``"minor"``), ``"locrian"``,
			``"harmonic_minor"``, ``"melodic_minor"``.

	Returns:
		List of ``(Chord, int)`` tuples, one per step.

	Raises:
		ValueError: If ``key`` or ``mode`` is not recognised, or if
			``root_midi`` does not fall on a scale degree of the key.

	Example:
		```python
		from subsequence.harmony import diatonic_chord_sequence

		# 7-step D Major ladder starting at D3 (MIDI 50)
		sequence = diatonic_chord_sequence("D", root_midi=50, count=7)

		# Map a 0-1 value to a chord (e.g. from ISS altitude)
		chord, root = sequence[int(ratio * (len(sequence) - 1))]
		p.chord(chord, root=root, sustain=True)

		# Falling sequence
		for chord, root in reversed(diatonic_chord_sequence("A", 57, 7, "minor")):
		    ...
		```
	"""

	if mode not in subsequence.intervals.DIATONIC_MODE_MAP:
		available = ", ".join(sorted(subsequence.intervals.DIATONIC_MODE_MAP.keys()))
		raise ValueError(f"Unknown mode: {mode!r}. Available: {available}")

	scale_key, _ = subsequence.intervals.DIATONIC_MODE_MAP[mode]
	scale_ivs = subsequence.intervals.get_intervals(scale_key)

	key_pc = subsequence.chords.key_name_to_pc(key)
	start_pc = root_midi % 12

	# Locate the scale degree that matches the starting MIDI note.
	start_degree: typing.Optional[int] = None

	for i, iv in enumerate(scale_ivs):
		if (key_pc + iv) % 12 == start_pc:
			start_degree = i
			break

	if start_degree is None:
		raise ValueError(
			f"MIDI note {root_midi} (pitch class {start_pc}) is not a scale "
			f"degree of {key!r} {mode!r}."
		)

	all_chords = diatonic_chords(key, mode=mode)
	result: typing.List[typing.Tuple[subsequence.chords.Chord, int]] = []

	for i in range(count):
		degree = (start_degree + i) % 7
		octave_bump = (start_degree + i) // 7
		midi_root = (
			root_midi
			+ (scale_ivs[degree] - scale_ivs[start_degree])
			+ 12 * octave_bump
		)
		result.append((all_chords[degree], midi_root))

	return result



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
