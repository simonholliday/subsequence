"""Tests for WeightedGraph edge labels (the cadence machinery's foundation)."""

import random

import pytest

import subsequence.weighted_graph


def test_label_stored_and_read () -> None:

	"""A labelled transition reports its label; unlabelled ones report None."""

	graph: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()
	graph.add_transition("V", "I", 10, label="cadence")
	graph.add_transition("V", "vi", 5)

	assert graph.get_label("V", "I") == "cadence"
	assert graph.get_label("V", "vi") is None
	assert graph.get_label("I", "V") is None


def test_label_survives_weight_accumulation () -> None:

	"""Re-adding a transition strengthens the edge without losing its label."""

	graph: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()
	graph.add_transition("V", "I", 10, label="cadence")
	graph.add_transition("V", "I", 5)

	assert graph.get_transitions("V") == [("I", 15)]
	assert graph.get_label("V", "I") == "cadence"


def test_label_replaced_on_relabel () -> None:

	"""A label given on a re-add replaces the previous one."""

	graph: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()
	graph.add_transition("V", "vi", 5, label="weak")
	graph.add_transition("V", "vi", 5, label="deceptive")

	assert graph.get_label("V", "vi") == "deceptive"


def test_transitions_with_label () -> None:

	"""transitions_with_label filters outgoing edges by their label."""

	graph: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()
	graph.add_transition("V", "I", 10, label="cadence")
	graph.add_transition("V", "vi", 5, label="deceptive")
	graph.add_transition("V", "IV", 3)

	assert graph.transitions_with_label("V", "cadence") == [("I", 10)]
	assert graph.transitions_with_label("V", "deceptive") == [("vi", 5)]
	assert graph.transitions_with_label("V", "missing") == []


def test_choose_next_is_unaffected_by_labels () -> None:

	"""Labels are metadata — the weighted walk ignores them."""

	labelled: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()
	bare: subsequence.weighted_graph.WeightedGraph = subsequence.weighted_graph.WeightedGraph()

	for graph, label in ((labelled, "cadence"), (bare, None)):
		graph.add_transition("a", "b", 3, label=label)
		graph.add_transition("a", "c", 7)

	assert (
		labelled.choose_next("a", random.Random(5))
		== bare.choose_next("a", random.Random(5))
	)
