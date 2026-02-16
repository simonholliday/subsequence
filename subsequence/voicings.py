"""Chord inversions and voice leading.

Provides functions for rotating chord intervals into different inversions and
choosing the smoothest voicing between consecutive chords. Voice leading
minimises the total semitone movement so that chord pads sound connected
rather than jumping around the keyboard.

Example:
	```python
	# Manual inversion
	from subsequence.voicings import invert_chord
	first_inv = invert_chord([0, 4, 7], inversion=1)  # [0, 3, 8]

	# Automatic voice leading across a pattern
	@composition.pattern(channel=0, length=4, voice_leading=True)
	def chords(p, chord):
		p.chord(chord, root=52, velocity=90, sustain=True)
	```
"""

import typing


def invert_chord (intervals: typing.List[int], inversion: int) -> typing.List[int]:

	"""Rotate chord intervals to produce an inversion.

	Inversion 0 is root position. Inversion 1 raises the bottom note by an
	octave (first inversion). Wraps around for inversions >= the number of
	notes.

	Parameters:
		intervals: Chord intervals in semitones from root (e.g., ``[0, 4, 7]``)
		inversion: Which inversion to produce (0 = root position)

	Returns:
		New interval list re-zeroed so the caller can add any root

	Example:
		```python
		invert_chord([0, 4, 7], 0)  # [0, 4, 7]  - root position
		invert_chord([0, 4, 7], 1)  # [0, 3, 8]  - first inversion
		invert_chord([0, 4, 7], 2)  # [0, 5, 9]  - second inversion
		```
	"""

	n = len(intervals)

	if n == 0:
		return []

	inversion = inversion % n

	if inversion == 0:
		return list(intervals)

	rotated = intervals[inversion:] + [i + 12 for i in intervals[:inversion]]
	base = rotated[0]

	return [i - base for i in rotated]


def voice_lead (intervals: typing.List[int], root_midi: int, previous_voicing: typing.Optional[typing.List[int]]) -> typing.List[int]:

	"""Find the inversion closest to a previous voicing.

	Tries every inversion and picks the one with the smallest total semitone
	movement from ``previous_voicing``. If ``previous_voicing`` is ``None`` or
	the chord sizes differ, returns root position.

	Parameters:
		intervals: Chord intervals in semitones from root (e.g., ``[0, 4, 7]``)
		root_midi: MIDI note number for the chord root
		previous_voicing: MIDI note numbers of the previous chord, or ``None``

	Returns:
		MIDI note numbers for the best voicing
	"""

	n = len(intervals)

	if n == 0:
		return []

	# No previous voicing or size mismatch - return root position.
	if previous_voicing is None or len(previous_voicing) != n:
		return [root_midi + i for i in intervals]

	best_voicing: typing.Optional[typing.List[int]] = None
	best_cost = float("inf")

	for inv in range(n):
		inv_intervals = invert_chord(intervals, inv)
		candidate = [root_midi + i for i in inv_intervals]

		cost = sum(abs(candidate[i] - previous_voicing[i]) for i in range(n))

		if cost < best_cost:
			best_cost = cost
			best_voicing = candidate

	assert best_voicing is not None
	return best_voicing


class VoiceLeadingState:

	"""Track the previous voicing across chord changes.

	Each pattern that uses voice leading gets its own instance so that a bass
	line and a pad can voice-lead independently.

	Example:
		```python
		state = VoiceLeadingState()
		voicing1 = state.next([0, 4, 7], 60)   # root position (no previous)
		voicing2 = state.next([0, 3, 7], 60)    # picks closest inversion to voicing1
		```
	"""

	def __init__ (self) -> None:

		"""Start with no previous voicing."""

		self.previous_voicing: typing.Optional[typing.List[int]] = None

	def next (self, intervals: typing.List[int], root_midi: int) -> typing.List[int]:

		"""Choose the smoothest voicing and update state.

		Parameters:
			intervals: Chord intervals in semitones from root
			root_midi: MIDI note number for the chord root

		Returns:
			MIDI note numbers for the chosen voicing
		"""

		result = voice_lead(intervals, root_midi, self.previous_voicing)
		self.previous_voicing = result

		return result
