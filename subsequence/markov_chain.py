import random
import typing


StateType = typing.TypeVar("StateType")


def choose_weighted (options: typing.List[typing.Tuple[StateType, int]], rng: random.Random) -> StateType:

	"""
	Choose one item from a list of weighted options.
	"""

	if not options:
		raise ValueError("Options cannot be empty")

	total_weight = 0

	for _, weight in options:
		if weight <= 0:
			raise ValueError("Weights must be positive")
		total_weight += weight

	roll = rng.uniform(0, total_weight)
	accum = 0.0

	for option, weight in options:
		accum += weight
		if roll <= accum:
			return option

	return options[-1][0]


class MarkovChain (typing.Generic[StateType]):

	"""
	A simple weighted Markov chain over arbitrary states.
	"""

	def __init__ (
		self,
		transitions: typing.Dict[StateType, typing.List[typing.Tuple[StateType, int]]],
		initial_state: typing.Optional[StateType] = None,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""
		Initialize the chain with transitions and an optional initial state.
		"""

		if not transitions:
			raise ValueError("Transitions cannot be empty")

		self.transitions = transitions
		self.rng = rng or random.Random()

		if initial_state is None:
			initial_state = next(iter(transitions))

		if initial_state not in transitions:
			raise ValueError("Initial state must exist in transitions")

		self.state = initial_state


	def step (self) -> StateType:

		"""
		Advance to the next state and return it.
		"""

		options = self.transitions.get(self.state, [])

		if not options:
			return self.state

		self.state = choose_weighted(options, self.rng)

		return self.state


	def get_state (self) -> StateType:

		"""
		Return the current state.
		"""

		return self.state
