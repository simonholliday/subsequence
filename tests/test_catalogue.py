"""Tests for the generator catalogue — the data a control surface builds from.

The wire shape here is a contract with a consumer that cannot see this
repository's internals, so these tests pin the format as much as the content.
A change that breaks one of them is a change somebody else has to hear about.
"""

import typing

import pytest

import subsequence
import subsequence.catalogue
import subsequence.pattern_builder


VALID_KINDS = {"switch", "number", "choice", "range", "pitch"}


# ---------------------------------------------------------------------------
# The catalogue as a whole
# ---------------------------------------------------------------------------

def test_every_declared_generator_exists_on_the_builder () -> None:

	"""The curated list cannot name a method that has been renamed away.

	This is the test that fails when somebody renames a generator, which is
	the point: the name is published, so a rename is visible outside this
	repository and should not pass quietly.
	"""

	for name in subsequence.catalogue.GENERATORS:
		assert hasattr(subsequence.pattern_builder.PatternBuilder, name), name


def test_the_catalogue_covers_every_declared_generator () -> None:

	"""generators() describes all of them, in the declared order."""

	described = [entry["name"] for entry in subsequence.generators()]

	assert described == list(subsequence.catalogue.GENERATORS)


def test_mini_notation_is_not_offered () -> None:

	"""seq() stays out: mini-notation is ratified legacy and frozen.

	Nothing new may accept, emit, extend or document it, and putting it in a
	published catalogue would do the last two.  Its parameter is a notation
	string, which maps to no control shape in any case.
	"""

	assert "seq" not in subsequence.catalogue.GENERATORS


def test_raw_note_primitives_and_transport_actions_are_not_offered () -> None:

	"""Halves of a pair, and All-Notes-Off, are not generators.

	A surface offering note_on with no matching note_off is a hanging-note
	generator; silence() is a transport action.
	"""

	for name in ("note_on", "note_off", "drone_off", "silence"):
		assert name not in subsequence.catalogue.GENERATORS, name


def test_transforms_and_accessors_are_not_offered () -> None:

	"""The line is "does it place notes", so reshaping verbs stay out."""

	for name in ("rotate", "invert", "swing", "dropout", "stretch", "transpose"):
		assert name not in subsequence.catalogue.GENERATORS, name

	for name in ("bar_cycle", "signal", "param", "capture", "build_ghost_bias", "duck_map"):
		assert name not in subsequence.catalogue.GENERATORS, name


# ---------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------

def test_every_entry_has_the_agreed_top_level_keys () -> None:

	"""name, summary, partial and parameters, on every generator."""

	for entry in subsequence.generators():
		assert set(entry) == {"name", "summary", "partial", "parameters"}
		assert isinstance(entry["name"], str) and entry["name"]
		assert isinstance(entry["summary"], str) and entry["summary"]
		assert isinstance(entry["partial"], bool)
		assert isinstance(entry["parameters"], list)


def test_every_parameter_declares_one_of_the_five_kinds () -> None:

	"""A parameter whose type maps to no shape is left out, never guessed at."""

	for entry in subsequence.generators():

		for parameter in entry["parameters"]:
			assert parameter["kind"] in VALID_KINDS, (entry["name"], parameter)
			assert isinstance(parameter["name"], str) and parameter["name"]
			assert isinstance(parameter["label"], str) and parameter["label"]


def test_the_catalogue_is_plain_data () -> None:

	"""Only dicts, lists, strings, numbers and bools — nothing to import.

	The consumer must not need a class from this package to read the answer.
	"""

	def plain (value: typing.Any) -> bool:

		if isinstance(value, dict):
			return all(isinstance(k, str) and plain(v) for k, v in value.items())

		if isinstance(value, list):
			return all(plain(v) for v in value)

		return isinstance(value, (str, int, float, bool)) or value is None

	assert plain(subsequence.generators())


def test_a_choice_carries_its_options () -> None:

	"""ghost_fill's bias reports all eight curves, as value/label pairs."""

	bias = _parameter("ghost_fill", "bias")

	assert bias["kind"] == "choice"
	assert [option["value"] for option in bias["options"]] == [
		"uniform", "offbeat", "sixteenths", "before", "after", "downbeat", "upbeat", "e_and_a",
	]
	assert bias["default"] == "uniform"


def test_thin_reports_its_own_ninth_strategy () -> None:

	"""thin adds "strength" to the shared curves — nine options, not eight."""

	strategy = _parameter("thin", "strategy")

	assert strategy["kind"] == "choice"
	assert len(strategy["options"]) == 9
	assert "strength" in [option["value"] for option in strategy["options"]]


def test_a_bounded_number_carries_its_span () -> None:

	"""density reports 0.0-1.0 because its annotation does."""

	density = _parameter("ghost_fill", "density")

	assert density["kind"] == "number"
	assert (density["min"], density["max"]) == (0.0, 1.0)
	assert density["default"] == 0.3


def test_an_unbounded_number_omits_min_and_max_rather_than_inventing_them () -> None:

	"""duration is a length in beats with no documented ceiling."""

	duration = _parameter("ghost_fill", "duration")

	assert duration["kind"] == "number"
	assert "min" not in duration and "max" not in duration


def test_an_int_steps_by_one_and_a_float_does_not () -> None:

	"""step is emitted only where the type genuinely implies one."""

	assert _parameter("euclidean", "pulses")["step"] == 1
	assert "step" not in _parameter("euclidean", "duration")


def test_a_pitch_carries_no_options () -> None:

	"""Which pitches are legal is the caller's business, never this package's.

	The rig decides which ten voices a drum machine has; Subsequence says only
	that the parameter is a pitch.
	"""

	pitch = _parameter("euclidean", "pitch")

	assert pitch["kind"] == "pitch"
	assert "options" not in pitch
	assert "multiple" not in pitch


def test_a_pitch_pool_is_marked_as_taking_several () -> None:

	"""Ten generators take a pool rather than one pitch.

	Without this they would all report as unofferable for a reason that is
	really about multiplicity, not shape.
	"""

	pitches = _parameter("recaman", "pitches")

	assert pitches["kind"] == "pitch"
	assert pitches["multiple"] is True


def test_a_velocity_range_reports_the_midi_bounds () -> None:

	"""An int-or-(low, high) parameter becomes a range control."""

	velocity = _parameter("euclidean", "velocity")

	assert velocity["kind"] == "range"
	assert (velocity["min"], velocity["max"]) == (1, 127)


def test_machine_parameters_are_not_offered () -> None:

	"""rng and seed are for the machine, not for a person.

	seed is an int in the signature but what a musician wants is a freeze
	switch, which the five kinds cannot express without either a sixth kind or
	per-parameter knowledge in the consumer.  Left out until freezing is
	designed on its own terms.
	"""

	for entry in subsequence.generators():
		names = {parameter["name"] for parameter in entry["parameters"]}
		assert "rng" not in names, entry["name"]
		assert "seed" not in names, entry["name"]
		assert "self" not in names, entry["name"]


# ---------------------------------------------------------------------------
# partial
# ---------------------------------------------------------------------------

def test_a_generator_needing_a_dict_is_marked_partial () -> None:

	"""markov cannot be driven from a surface: its transitions are a dict.

	Reported rather than hidden, because a control that can never be completed
	is worse than one that is absent — and only the caller can decide which to
	show.
	"""

	assert subsequence.describe_generator("markov")["partial"] is True


def test_a_fully_shaped_generator_is_not_partial () -> None:

	"""euclidean's every required parameter maps to a control."""

	assert subsequence.describe_generator("euclidean")["partial"] is False


def test_an_optional_unshaped_parameter_does_not_make_it_partial () -> None:

	"""Only a REQUIRED parameter with no shape blocks a generator.

	ghost_fill's velocity accepts a Sequence or a Callable as well as a number,
	but it has a default, so the generator is fully offerable without them.
	"""

	assert subsequence.describe_generator("ghost_fill")["partial"] is False


# ---------------------------------------------------------------------------
# describe_generator
# ---------------------------------------------------------------------------

def test_describing_an_unknown_generator_says_how_to_find_the_real_ones () -> None:

	"""The refusal carries the vocabulary rather than just refusing."""

	with pytest.raises(ValueError, match="not a declared generator"):
		subsequence.describe_generator("rotate")

	with pytest.raises(ValueError, match="generators\\(\\)"):
		subsequence.describe_generator("nonsense")


def test_the_summary_is_the_docstring_first_line () -> None:

	"""Taken from the code, so it cannot drift from what the method says."""

	assert subsequence.describe_generator("ghost_fill")["summary"] == (
		"Fill the pattern with probability-biased ghost notes."
	)


def _parameter (generator: str, name: str) -> typing.Dict[str, typing.Any]:

	"""The named parameter of a generator, for brevity in the tests above."""

	for parameter in subsequence.describe_generator(generator)["parameters"]:

		if parameter["name"] == name:
			return parameter

	raise AssertionError(f"{generator} has no parameter {name!r}")
