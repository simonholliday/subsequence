import unittest

import subsequence.swing


class SwingTests (unittest.TestCase):

	"""
	Tests for swing timing.
	"""

	def test_apply_swing_moves_offbeat (self) -> None:

		"""
		An offbeat eighth should be delayed with swing applied.
		"""

		steps = {0: ["a"], 12: ["b"]}
		swung = subsequence.swing.apply_swing(steps, swing_ratio=2.0, pulses_per_quarter=24)

		self.assertIn(0, swung)
		self.assertIn(16, swung)
