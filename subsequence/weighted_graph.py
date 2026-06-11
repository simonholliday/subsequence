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
		self._labels: typing.Dict[typing.Tuple[NodeType, NodeType], str] = {}


	def add_transition (self, source: NodeType, target: NodeType, weight: int, label: typing.Optional[str] = None) -> None:

		"""
		Add a weighted transition between two nodes.

		Parameters:
			source: Node the transition leaves from.
			target: Node the transition arrives at.
			weight: Positive transition weight.  Re-adding an existing
				transition accumulates, strengthening the edge.
			label: Optional edge label naming the transition's musical
				function (e.g. ``"cadence"``, ``"deceptive"``).  A label
				given on a re-add replaces the previous one; ``None``
				leaves any existing label untouched.
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

		if label is not None:
			self._labels[(source, target)] = label


	def get_label (self, source: NodeType, target: NodeType) -> typing.Optional[str]:

		"""
		Return the label for a transition, or None if it has none.
		"""

		return self._labels.get((source, target))


	def transitions_with_label (self, source: NodeType, label: str) -> typing.List[typing.Tuple[NodeType, int]]:

		"""
		Return the outgoing transitions from *source* that carry *label*.
		"""

		return [
			(target, weight)
			for target, weight in self.get_transitions(source)
			if self._labels.get((source, target)) == label
		]


	def nodes (self) -> typing.List[NodeType]:

		"""
		Return every node that appears in the graph (as a source or a target),
		in first-seen order.
		"""

		seen: typing.Dict[NodeType, None] = {}

		for source, targets in self._edges.items():
			seen.setdefault(source)
			for target in targets:
				seen.setdefault(target)

		return list(seen)


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

		Returns *source* unchanged if the node has no outgoing transitions,
		or if every outgoing transition has been suppressed by a weight
		modifier that returned zero or a negative value.
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
