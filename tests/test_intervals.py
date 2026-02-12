import unittest

import subsequence.intervals


class IntervalTests (unittest.TestCase):

	"""
	Tests for interval definitions and diatonic construction.
	"""

	def test_get_intervals (self) -> None:

		"""
		Interval lookup should return a known definition.
		"""

		self.assertEqual(subsequence.intervals.get_intervals("major_triad"), [0, 4, 7])


	def test_get_diatonic_intervals (self) -> None:

		"""
		Diatonic chord construction should return the expected tonic triad.
		"""

		major_scale = [0, 2, 4, 5, 7, 9, 11]
		chords = subsequence.intervals.get_diatonic_intervals(major_scale)

		self.assertEqual(chords[0], [0, 4, 7])
