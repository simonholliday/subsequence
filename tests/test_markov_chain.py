import random
import pytest

import subsequence.markov_chain


def test_single_transition () -> None:

	"""
	A single transition should always be selected.
	"""

	transitions = {"A": [("B", 1)]}
	chain = subsequence.markov_chain.MarkovChain(transitions=transitions, initial_state="A", rng=random.Random(1))

	assert chain.step() == "B"
	assert chain.get_state() == "B"


def test_invalid_weight_raises () -> None:

	"""
	Invalid weights should raise in choose_weighted.
	"""

	with pytest.raises(ValueError):
		subsequence.markov_chain.choose_weighted([("A", 0)], random.Random(1))
