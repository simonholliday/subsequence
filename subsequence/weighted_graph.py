import random
import typing


NodeType = typing.TypeVar("NodeType")
WeightModifierType = typing.Optional[typing.Callable[[NodeType, NodeType, int], float]]


class WeightedGraph (typing.Generic[NodeType]):

	"""
	A weighted directed graph with optional runtime weight adjustment.
	"""

	def __init__ (self) -> None:

		"""
		Initialize an empty weighted graph.
		"""

		self._edges: typing.Dict[NodeType, typing.Dict[NodeType, int]] = {}


	def add_transition (self, source: NodeType, target: NodeType, weight: int) -> None:

		"""
		Add a weighted transition between two nodes.
		"""

		if weight <= 0:
			raise ValueError("Weight must be positive")

		if source not in self._edges:
			self._edges[source] = {}

		# If a transition already exists, accumulate to strengthen the edge.
		if target in self._edges[source]:
			self._edges[source][target] += weight

		else:
			self._edges[source][target] = weight


	def get_transitions (self, source: NodeType) -> typing.List[typing.Tuple[NodeType, int]]:

		"""
		Return weighted transitions for a source node.
		"""

		if source not in self._edges:
			return []

		return list(self._edges[source].items())


	def choose_next (self, source: NodeType, rng: random.Random, weight_modifier: WeightModifierType = None) -> NodeType:

		"""
		Choose the next node from a source using weighted randomness.
		"""

		options = self.get_transitions(source)

		if not options:
			# Decision path: with no outgoing edges we remain on the current node.
			return source

		adjusted: typing.List[typing.Tuple[NodeType, float]] = []
		total_weight = 0.0

		for target, weight in options:

			if weight_modifier is None:
				modifier = 1.0

			else:
				modifier = float(weight_modifier(source, target, weight))

			if modifier <= 0:
				# Decision path: non-positive modifiers suppress this transition entirely.
				continue

			adjusted_weight = float(weight) * modifier
			adjusted.append((target, adjusted_weight))
			total_weight += adjusted_weight

		if total_weight <= 0:
			# Decision path: if every transition is suppressed, stay on the current node.
			return source

		roll = rng.uniform(0, total_weight)
		accum = 0.0

		for target, adj_weight in adjusted:
			accum += adj_weight
			if roll <= accum:
				return target

		return adjusted[-1][0]
