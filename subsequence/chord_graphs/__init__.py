"""
Chord graph builders for different harmonic transition models.
"""

import abc
import typing

import subsequence.chords
import subsequence.intervals
import subsequence.weighted_graph


# Shared transition weights used by all chord graph builders.
WEIGHT_STRONG = 6
WEIGHT_MEDIUM = 4
WEIGHT_COMMON = 3
WEIGHT_DECEPTIVE = 2
WEIGHT_WEAK = 1


class ChordGraph (abc.ABC):

	"""Abstract base for chord transition graphs."""

	@abc.abstractmethod
	def build (self, key_name: str) -> typing.Tuple[subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord], subsequence.chords.Chord]:

		"""Build the weighted graph and return it with the tonic chord."""

		...

	@abc.abstractmethod
	def gravity_sets (self, key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

		"""Return (diatonic_set, functional_set) for key gravity weighting."""

		...


def validate_key_name (key_name: str) -> int:

	"""Validate a key name and return its pitch class.

	Raises ValueError if the key name is not recognised.

	Parameters:
		key_name: Note name (e.g., ``"C"``, ``"F#"``, ``"Bb"``)

	Returns:
		Pitch class integer (0-11)
	"""

	if key_name not in subsequence.chords.NOTE_NAME_TO_PC:
		raise ValueError(f"Unknown key name: {key_name}")

	return subsequence.chords.NOTE_NAME_TO_PC[key_name]


def build_diatonic_chords (key_pc: int, scale_intervals: typing.List[int], degree_qualities: typing.List[str]) -> typing.List[subsequence.chords.Chord]:

	"""Build chords for each scale degree.

	Parameters:
		key_pc: Root pitch class (0-11)
		scale_intervals: Semitone offset for each degree (e.g., ``[0, 2, 4, 5, 7, 9, 11]`` for major)
		degree_qualities: Chord quality for each degree (e.g., ``["major", "minor", ...]``)

	Returns:
		List of Chord objects, one per scale degree
	"""

	chords: typing.List[subsequence.chords.Chord] = []

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

	return chords


def _major_key_gravity_sets (key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

	"""Return diatonic and functional chord sets for a major key."""

	key_pc = validate_key_name(key_name)
	scale_intervals = subsequence.intervals.get_intervals("major_ionian")

	chords = build_diatonic_chords(key_pc, scale_intervals, subsequence.intervals.IONIAN_QUALITIES)
	diatonic: typing.Set[subsequence.chords.Chord] = set(chords)

	# Functional set: I, ii, V, V7.
	function_intervals = [0, 2, 7]
	function_qualities = ["major", "minor", "major"]

	function_chords: typing.Set[subsequence.chords.Chord] = set()

	for interval, quality in zip(function_intervals, function_qualities):
		root_pc = (key_pc + interval) % 12
		function_chords.add(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

	dominant_7th = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="dominant_7th")
	function_chords.add(dominant_7th)
	diatonic.add(dominant_7th)

	return diatonic, function_chords
