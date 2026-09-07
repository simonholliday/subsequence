"""Tests for the generator catalogue — the data a control surface builds from.

The wire shape here is a contract with a consumer that cannot see this
repository's internals, so these tests pin the format as much as the content.
A change that breaks one of them is a change somebody else has to hear about.
"""

import inspect
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.declarations
import subsequence.easing
import subsequence.pattern
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

	for name in ("bar_cycle", "signal", "param", "capture", "build_ghost_bias", "duck_map", "section_motif"):
		assert name not in subsequence.catalogue.GENERATORS, name


def test_every_generator_returns_the_builder () -> None:

	"""A generator places notes and returns self for chaining.

	The mechanical form of "does it place notes": an accessor returns its data
	instead, which is how ``section_motif`` reached the catalogue by mistake —
	it returns the Motif bound to the current section and places nothing.
	"""

	for name in subsequence.catalogue.GENERATORS:
		annotation = str(inspect.signature(
			getattr(subsequence.pattern_builder.PatternBuilder, name),
		).return_annotation)
		assert "PatternBuilder" in annotation, f"{name} returns {annotation}"


# Parameters knowingly left out of the catalogue, with the reason.  Every one
# is genuinely unshaped — not merely missing an annotation.
#
# The distinction matters: a parameter that COULD carry a shape but lacks the
# marker is dropped silently while its generator still reports complete, which
# tells a consumer "fully offerable" about something it cannot fully drive.
# That is how thin.pitch, ratchet.pitch and thue_morse.pitch_b were missed.
KNOWINGLY_DROPPED: typing.FrozenSet[typing.Tuple[str, str]] = frozenset({
	# Birth/Survival notation ("B3/S23", "B368/S245") — a grammar, not a
	# vocabulary, so there is no finite option list to offer.
	("cellular_2d", "rule"),
	# Callables that map a raw sequence value onto a note.  No control shape
	# maps to a function, and all three are optional.
	("fibonacci", "mapping"),
	("lorenz", "mapping"),
	("recaman", "mapping"),
	# A step list.  A surface could plausibly offer a step grid, but that
	# would be a sixth kind and is not ours to invent alone.
	("ratchet", "steps"),
})


def test_nothing_is_dropped_silently_from_a_generator_reported_complete () -> None:

	"""Every omitted parameter is either machine-only, or knowingly unshaped.

	This is the sweep that matters.  Three pitch parameters were annotated
	``Optional[Union[int, str]]`` rather than ``Optional[Pitch]``, so the
	deriver could not see them; because they were optional the generator was
	not flagged partial either, and a consumer was told a generator was fully
	offerable while a parameter it needed was silently absent.

	A new parameter added without a marker lands here rather than in somebody
	else's bug report.
	"""

	unexplained: typing.List[typing.Tuple[str, str, str]] = []

	for entry in subsequence.generators():

		# A generator already marked partial has told the consumer it cannot be
		# fully driven, so anything missing from it is disclosed rather than
		# hidden.  The dishonest pairing — and the whole point of this test — is
		# "partial": false alongside a parameter that quietly is not there.
		if entry["partial"]:
			continue

		function = getattr(subsequence.pattern_builder.PatternBuilder, entry["name"])
		hints = typing.get_type_hints(function, include_extras=True)

		# Read the entry's own "dropped" rather than re-deriving it from the
		# signature: the published fact is the one worth testing, and a second
		# derivation here could agree with itself while disagreeing with what
		# a consumer is actually told.
		for name in entry["dropped"]:

			if (entry["name"], name) in KNOWINGLY_DROPPED:
				continue

			unexplained.append((entry["name"], name, str(hints.get(name, "<no annotation>"))))

	assert not unexplained, (
		"parameters dropped with no explanation — annotate them, or add them to "
		f"KNOWINGLY_DROPPED with the reason: {unexplained}"
	)


def test_ratchet_shape_offers_the_easing_curves () -> None:

	"""shape resolves through easing.get_easing(), which raises on an unknown name.

	So the seven names are the whole vocabulary and belong in the annotation,
	not only in prose — the Callable arm stays for callers passing their own.
	"""

	shape = _parameter("ratchet", "shape")

	assert shape["kind"] == "choice"
	assert {option["value"] for option in shape["options"]} == set(
		subsequence.easing.EASING_FUNCTIONS
	)


def test_cellular_2d_offers_its_named_seeds_but_not_its_rule () -> None:

	"""initial_state is a two-name vocabulary; rule is open notation.

	"center" and "random" are the whole named set, so they are offerable. A
	Birth/Survival rule string has no finite option list, so it is left out
	rather than guessed at.
	"""

	initial_state = _parameter("cellular_2d", "initial_state")

	assert initial_state["kind"] == "choice"
	assert {option["value"] for option in initial_state["options"]} == {"center", "random"}

	offered = {p["name"] for p in subsequence.describe_generator("cellular_2d")["parameters"]}
	assert "rule" not in offered


def test_optional_pitch_parameters_are_offered () -> None:

	"""Targeting one voice is most of the point of thin() and ratchet().

	Without the marker a surface could thin a whole kit but not just the
	hi-hats, which is the ordinary musical request.
	"""

	for generator, name in (("thin", "pitch"), ("ratchet", "pitch"), ("thue_morse", "pitch_b")):
		assert _parameter(generator, name)["kind"] == "pitch"


# ---------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------

def test_every_entry_has_the_agreed_top_level_keys () -> None:

	"""name, summary, partial, parameters and dropped, on every generator."""

	for entry in subsequence.generators():
		assert set(entry) == {"name", "summary", "partial", "parameters", "dropped"}
		assert isinstance(entry["name"], str) and entry["name"]
		assert isinstance(entry["summary"], str) and entry["summary"]
		assert isinstance(entry["partial"], bool)
		assert isinstance(entry["parameters"], list)
		assert isinstance(entry["dropped"], list)
		assert all(isinstance(name, str) for name in entry["dropped"])


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

	"""Eleven generators take a pool rather than one pitch.

	Without this they would all report as unofferable for a reason that is
	really about multiplicity, not shape.
	"""

	pitches = _parameter("recaman", "pitches")

	assert pitches["kind"] == "pitch"
	assert pitches["multiple"] is True


def test_a_covariant_sequence_of_pitches_is_a_pool_too () -> None:

	"""``Sequence[Pitch]`` has to read as a pool exactly as ``List[Pitch]`` does.

	``list`` is invariant, so a parameter annotated ``List[Pitch]`` rejects the
	``List[int]`` a caller already holds — ``held_notes()``, ``scale_notes()``.
	``Sequence`` is the annotation that accepts those, so the catalogue has to
	recognise it or the honest annotation costs the generator its controls.
	"""

	pitch = subsequence.declarations.Pitch

	assert subsequence.catalogue._pitch_arity(typing.Sequence[pitch]) is True
	assert subsequence.catalogue._pitch_arity(typing.List[pitch]) is True
	assert subsequence.catalogue._pitch_arity(pitch) is False
	assert subsequence.catalogue._pitch_arity(typing.Sequence[int]) is None


def test_a_pool_sharing_a_union_with_a_chord_is_still_a_pool () -> None:

	"""``arpeggio`` takes a chord OR a pool, and the pool is the offerable half."""

	arity = subsequence.catalogue._pitch_arity(
		typing.Union[
			subsequence.chords.Chord,
			typing.Sequence[subsequence.declarations.Pitch],
		]
	)

	assert arity is True


def test_arpeggio_offers_its_notes_rather_than_reporting_partial () -> None:

	"""#2155: ``notes: typing.Any`` made a headline generator unofferable.

	The type was never in doubt — the docstring said "a chord, or a list of
	pitches" all along — it was simply unwritten, so the catalogue could see
	nothing and a surface listed a generator it could not drive.
	"""

	arpeggio = subsequence.describe_generator("arpeggio")
	notes = _parameter("arpeggio", "notes")

	assert arpeggio["partial"] is False
	assert notes["kind"] == "pitch"
	assert notes["multiple"] is True


def test_every_pitch_pool_annotation_stays_covariant () -> None:

	"""No pool may be spelled ``List``, because ``list`` is invariant.

	``p.arpeggio(p.held_notes())`` is printed in three places in this package,
	and ``held_notes()`` returns ``List[int]`` — which is not a ``List[Pitch]``
	and never will be.  The same goes for the ``List[int]`` out of
	``scale_notes()`` and for any homogeneous list a caller already holds, so a
	pool a caller supplies must be annotated with the covariant ``Sequence``.

	Swept rather than asserted one generator at a time: this was fixed on
	``arpeggio`` for #2155 while ten others still said ``List``, and it stayed
	invisible only because #2156's signature erasure meant nothing checked
	them.  A sweep is what stops the next one being written the old way.
	"""

	invariant: typing.List[str] = []

	for entry in subsequence.generators():

		hints = typing.get_type_hints(
			getattr(subsequence.pattern_builder.PatternBuilder, entry["name"]),
			include_extras=True,
		)

		for parameter in entry["parameters"]:

			if parameter["kind"] != "pitch" or not parameter.get("multiple"):
				continue

			annotation = hints[parameter["name"]]
			containers = [annotation, *typing.get_args(annotation)]

			if any(typing.get_origin(arm) is list for arm in containers):
				invariant.append(f'{entry["name"]}.{parameter["name"]}')

	assert not invariant, (
		"a pitch pool annotated List rejects the list a caller already holds — "
		f"use typing.Sequence: {invariant}"
	)


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

		# Nor are they *dropped*: they were never candidates.  Reporting them
		# as dropped would say "this could not be shaped", which is not what
		# happened and would make the key mean nothing.
		assert not set(entry["dropped"]) & subsequence.catalogue._NOT_FOR_PEOPLE, entry["name"]


# ---------------------------------------------------------------------------
# dropped — what could not be shaped, said out loud
# ---------------------------------------------------------------------------

def test_a_generator_that_shapes_everything_drops_nothing () -> None:

	"""The key means something only if it is empty in the ordinary case."""

	assert subsequence.describe_generator("euclidean")["dropped"] == []


def test_an_optional_parameter_with_no_shape_is_named_not_hidden () -> None:

	"""The defect this exists for: complete-looking, and quietly missing something.

	``fibonacci`` takes an optional ``mapping`` callable.  No control shape
	maps to a function, so it is left out — and because it is optional the
	generator is not flagged partial either.  Before #2239 a consumer was
	told "fully offerable" with no way to learn otherwise.
	"""

	entry = subsequence.describe_generator("fibonacci")

	assert entry["partial"] is False
	assert entry["dropped"] == ["mapping"]
	assert "mapping" not in {p["name"] for p in entry["parameters"]}


def test_a_partial_generator_names_what_it_could_not_shape () -> None:

	"""partial says *that* it cannot be driven; dropped says *what* it wanted."""

	entry = subsequence.describe_generator("markov")

	assert entry["partial"] is True
	assert set(entry["dropped"]) >= {"transitions"}


def test_nothing_is_both_offered_and_dropped () -> None:

	"""The two lists partition the parameters a person could care about."""

	for entry in subsequence.generators():
		offered = {parameter["name"] for parameter in entry["parameters"]}
		assert not offered & set(entry["dropped"]), entry["name"]


# ---------------------------------------------------------------------------
# transforms — the other half of the line
# ---------------------------------------------------------------------------

def _arguments_for (entry: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:

	"""Plausible arguments for a described method, taken from its own description.

	Derived rather than tabulated, so the probe below exercises the published
	shapes as well as the behaviour — a table here would be a second copy of
	facts the catalogue already states.
	"""

	arguments: typing.Dict[str, typing.Any] = {}

	for parameter in entry["parameters"]:

		if "default" in parameter:
			arguments[parameter["name"]] = parameter["default"]
		elif parameter["kind"] == "number":
			arguments[parameter["name"]] = parameter.get("min", 1)
		elif parameter["kind"] == "choice":
			arguments[parameter["name"]] = parameter["options"][0]["value"]
		elif parameter["kind"] == "switch":
			arguments[parameter["name"]] = False
		elif parameter["kind"] == "pitch":
			arguments[parameter["name"]] = [60] if parameter.get("multiple") else 60
		elif parameter["kind"] == "range":
			arguments[parameter["name"]] = [1, 127]

	return arguments


def test_every_declared_transform_exists_on_the_builder () -> None:

	"""A name that is not there would fail at the surface, not here."""

	for name in subsequence.catalogue.TRANSFORMS:
		assert callable(getattr(subsequence.pattern_builder.PatternBuilder, name, None)), name


def test_the_two_catalogues_do_not_overlap () -> None:

	"""A method places notes or reshapes them; being in both would say neither."""

	assert not set(subsequence.catalogue.GENERATORS) & set(subsequence.catalogue.TRANSFORMS)


def test_every_transform_returns_the_builder () -> None:

	"""The family test, run rather than eyeballed — an accessor returns its data.

	This is the check that caught `section_motif` among the generators (#2096),
	and a second curated tuple is a second chance to make that mistake.
	"""

	for name in subsequence.catalogue.TRANSFORMS:
		hints = typing.get_type_hints(getattr(subsequence.pattern_builder.PatternBuilder, name))
		assert "PatternBuilder" in str(hints.get("return")), name


def test_a_transform_never_places_a_note () -> None:

	"""The mechanical form of the line: reshaping is not placing.

	Run on an empty pattern (a transform has nothing to do, so nothing appears)
	and on a populated one (it may move, shorten, quieten or remove notes, but
	never add any).  Anything failing this is a generator and belongs in the
	other tuple.
	"""

	for entry in subsequence.transforms():

		arguments = _arguments_for(entry)

		empty = _builder()
		getattr(empty, entry["name"])(**arguments)
		assert _note_count(empty) == 0, f'{entry["name"]} placed notes on an empty pattern'

		populated = _builder()
		populated.hit(60, [0.0, 1.0, 2.0, 3.0])
		before = _note_count(populated)
		getattr(populated, entry["name"])(**arguments)
		assert _note_count(populated) <= before, f'{entry["name"]} added notes'


def test_every_transform_entry_has_the_agreed_shape () -> None:

	"""One describer, so a consumer needs no second code path."""

	for entry in subsequence.transforms():
		assert set(entry) == {"name", "summary", "partial", "parameters", "dropped"}
		assert isinstance(entry["summary"], str) and entry["summary"]

		for parameter in entry["parameters"]:
			assert parameter["kind"] in VALID_KINDS, (entry["name"], parameter)


def test_asking_the_wrong_catalogue_says_which_one_to_ask () -> None:

	"""The two are easy to confuse and the answer is one call away."""

	with pytest.raises(ValueError, match="is a transform, not a generator"):
		subsequence.describe_generator("rotate")

	with pytest.raises(ValueError, match="is a generator, not a transform"):
		subsequence.describe_transform("euclidean")

	with pytest.raises(ValueError, match=r"transforms\(\)"):
		subsequence.describe_transform("nonsense")


def test_midi_plumbing_is_not_a_transform () -> None:

	"""It emits control events; it does not reshape notes.

	Kept out so `transforms()` stays a category rather than becoming
	"everything that is not a generator", which would not survive its first
	addition.
	"""

	for name in ("cc", "cc_ramp", "nrpn", "rpn", "osc", "sysex", "bend", "program_change"):
		assert name not in subsequence.catalogue.TRANSFORMS, name


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


def test_chord_and_strum_offer_their_pitches () -> None:

	"""#2240: both took a Chord only, so a surface saw a disabled button.

	They now take the same first argument as `arpeggio()`, and the catalogue
	already understood that shape — recognising `Sequence[Pitch]` as a pool was
	the second half of the `arpeggio` fix (#2155), so this needed no change here.
	"""

	for name in ("chord", "strum"):
		entry = subsequence.describe_generator(name)
		assert entry["partial"] is False, name
		assert entry["dropped"] == [], name
		assert entry["parameters"][0]["kind"] == "pitch", name
		assert entry["parameters"][0]["multiple"] is True, name


def test_broken_chord_stays_partial_for_its_own_reason () -> None:

	"""Its `order` is a step list, which maps to no control shape.

	Left alone deliberately: widening its first argument would have meant
	either reordering its parameters — breaking every positional caller — or
	giving `order` a default it does not have, which would report the method
	complete while dropping something it genuinely requires.
	"""

	entry = subsequence.describe_generator("broken_chord")

	assert entry["partial"] is True
	assert "order" in entry["dropped"]


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

	"""The refusal carries the vocabulary rather than just refusing.

	``rotate`` used to be the example here, as a chainable method that is not
	a generator.  It is a declared *transform* now, and the refusal says so
	instead — see `test_asking_the_wrong_catalogue_says_which_one_to_ask`.  So
	this needs a name that is in neither catalogue.
	"""

	with pytest.raises(ValueError, match="not a declared generator"):
		subsequence.describe_generator("cc_ramp")

	with pytest.raises(ValueError, match="generators\\(\\)"):
		subsequence.describe_generator("nonsense")


def test_the_summary_is_the_docstring_first_line () -> None:

	"""Taken from the code, so it cannot drift from what the method says."""

	assert subsequence.describe_generator("ghost_fill")["summary"] == (
		"Fill the pattern with probability-biased ghost notes."
	)


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	"""A PatternBuilder over a bare 4-beat pattern (no MIDI required)."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)

	return subsequence.pattern_builder.PatternBuilder(pattern, cycle=0)


def _note_count (builder: subsequence.pattern_builder.PatternBuilder) -> int:

	"""How many notes are on the pattern this builder is writing to.

	Counts drones as well as step notes.  Counting only ``steps`` would let a
	verb that places a raw Note On through the sieve below, which is exactly
	the under-reporting `placed()` had to fix (#2102).
	"""

	return (
		sum(len(step.notes) for step in builder._pattern.steps.values())
		+ len(builder._pattern.raw_note_events)
	)


def _parameter (generator: str, name: str) -> typing.Dict[str, typing.Any]:

	"""The named parameter of a generator, for brevity in the tests above."""

	for parameter in subsequence.describe_generator(generator)["parameters"]:

		if parameter["name"] == name:
			return parameter

	raise AssertionError(f"{generator} has no parameter {name!r}")
