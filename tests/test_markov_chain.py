import random
import unittest

import subsequence.markov_chain


class MarkovChainTests (unittest.TestCase):

	"""
	Tests for the weighted Markov chain utility.
	"""

	def test_single_transition (self) -> None:

		"""
		A single transition should always be selected.
		"""

		transitions = {"A": [("B", 1)]}
		chain = subsequence.markov_chain.MarkovChain(transitions=transitions, initial_state="A", rng=random.Random(1))

		self.assertEqual(chain.step(), "B")
		self.assertEqual(chain.get_state(), "B")


	def test_invalid_weight_raises (self) -> None:

		"""
		Invalid weights should raise in choose_weighted.
		"""

		with self.assertRaises(ValueError):
			subsequence.markov_chain.choose_weighted([("A", 0)], random.Random(1))
