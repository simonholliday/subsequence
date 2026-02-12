import unittest

import subsequence.harmony


class HarmonyGraphTests (unittest.TestCase):

	"""
	Tests for chord transition graph construction.
	"""

	def test_dominant_7th_included (self) -> None:

		"""
		Dominant seventh should appear when enabled and resolve to tonic.
		"""

		graph, tonic = subsequence.harmony.build_major_key_graph("E", include_dominant_7th=True)

		dominant = subsequence.harmony.Chord(root_pc=11, quality="major")
		dominant_7th = subsequence.harmony.Chord(root_pc=11, quality="dominant_7th")

		transitions = graph.get_transitions(dominant)
		self.assertTrue(any(chord == dominant_7th for chord, _ in transitions))

		transitions_7th = graph.get_transitions(dominant_7th)
		self.assertTrue(any(chord == tonic for chord, _ in transitions_7th))


	def test_invalid_key_name (self) -> None:

		"""
		Invalid key names should raise an error.
		"""

		with self.assertRaises(ValueError):
			subsequence.harmony.build_major_key_graph("H", include_dominant_7th=True)
