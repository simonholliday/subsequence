"""
Chord graph builders for different harmonic transition models.
"""

import abc
import typing

import subsequence.chords
import subsequence.weighted_graph


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


def _major_key_gravity_sets (key_name: str) -> typing.Tuple[typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]]:

	"""Return diatonic and functional chord sets for a major key."""

	key_pc = subsequence.chords.NOTE_NAME_TO_PC[key_name]
	scale_intervals = [0, 2, 4, 5, 7, 9, 11]
	degree_qualities = ["major", "minor", "minor", "major", "major", "minor", "diminished"]

	diatonic: typing.Set[subsequence.chords.Chord] = set()

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		diatonic.add(subsequence.chords.Chord(root_pc=root_pc, quality=quality))

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
