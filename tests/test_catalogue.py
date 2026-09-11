"""Tests for the generator catalogue — the data a control surface builds from.

The wire shape here is a contract with a consumer that cannot see this
repository's internals, so these tests pin the format as much as the content.
A change that breaks one of them is a change somebody else has to hear about.
"""

import inspect
import json
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.declarations
import subsequence.easing
import subsequence.pattern
import subsequence.catalogue
import subsequence.pattern_builder


VALID_KINDS = {"switch", "number", "choice", "range", "pitch", "chord", "position"}


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
	# One duration, or one per step.  The shape is real — parallel lists
	# stepped through together is what sequence() is for — but describing it
	# would mean putting "multiple" on a number, and thirty velocity
	# parameters are the same scalar-or-list shape while meaning a random
	# range instead.  Today only branch ORDER keeps those reading as "range",
	# which is too thin a thread to hang thirty controls on, so this waits to
	# be asked for deliberately rather than invented here (#2411).
	("sequence", "durations"),
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


def test_an_int_steps_by_one_and_a_float_only_where_declared () -> None:

	"""step is emitted only where the type or the declaration genuinely implies one.

	An int steps by one.  A float used to carry no step at all, on the
	reasoning that its increment depends on what it measures — which was right,
	and is why a float now carries one only where its declaration says what
	that is (#2367).  A float that declares nothing still gets nothing, rather
	than an increment invented here.
	"""

	assert _parameter("euclidean", "pulses")["step"] == 1
	assert _parameter("euclidean", "duration")["step"] == 0.05
	assert "step" not in _parameter("lorenz", "sigma")


def test_every_published_step_divides_its_default () -> None:

	"""The rule that chose the sizes, and the one that would catch a wrong one.

	Superconductor's stepper adds and subtracts from where it is and never
	snaps, so a step the default is not a multiple of walks a lattice that can
	never come back to a musical value — a 0.25 step on a duration defaulting
	to 0.1 goes 0.35, 0.6, 0.85 for ever.  This is what ruled a sixteenth out
	for durations and a strum's stagger, rather than anybody's taste.
	"""

	off: typing.List[str] = []

	for entry in subsequence.generators() + subsequence.transforms():

		for parameter in entry["parameters"]:

			step = parameter.get("step")
			default = parameter.get("default")

			if not step or isinstance(default, bool) or not isinstance(default, (int, float)):
				continue

			if abs(round(default / step) * step - default) > 1e-9:
				off.append(f"{entry['name']}.{parameter['name']}: default {default}, step {step}")

	assert not off, "a stepper could never return to these defaults: " + "; ".join(off)


@pytest.mark.parametrize("generator,name", [
	("arpeggio", "beat"), ("arpeggio", "span"), ("arpeggio", "spacing"), ("phrase", "offset"),
])
def test_time_on_the_grid_steps_by_a_sixteenth (generator: str, name: str) -> None:

	"""Where a note lands, how long a figure runs, the gap between onsets.

	Superconductor's invented tenth could never reach a sixteenth — 0.1, 0.2,
	0.3 — so a beat position could not be stepped onto the grid the rest of
	this package assumes.
	"""

	assert _parameter(generator, name)["step"] == 0.25


def test_a_gate_steps_finer_than_the_grid_and_still_reaches_it () -> None:

	"""How long a note sounds lives below a sixteenth, so it needs a finer step.

	A drum gate defaults to 0.1 and a strum's stagger to 0.05, and a sixteenth
	step could reach neither.  A twentieth divides both — and every sixteenth
	is a multiple of it, so stepping a duration up still passes 0.25, 0.5, 1.0.
	"""

	duration = _parameter("euclidean", "duration")

	assert duration["step"] == 0.05
	assert round(0.25 / duration["step"]) * duration["step"] == pytest.approx(0.25)

	# strum shares chord's placement vocabulary but staggers rather than places,
	# so its spacing is a gate and not a grid position.
	assert _parameter("strum", "spacing")["step"] == 0.05
	assert _parameter("arpeggio", "spacing")["step"] == 0.25


def test_a_documented_zero_to_one_dial_is_now_a_slider () -> None:

	"""Eleven dials promised 0.0-1.0 in their docstrings and declared no range.

	Unbounded, a surface drew each as a stepper a person could push to -0.1 or
	1.3.  #2367 assumed proportions "mostly have a Span already"; these eleven
	did not.  A range makes them sliders, which makes their step moot.
	"""

	for verb, name in (
		("cellular_2d", "density"), ("chord", "legato"), ("strum", "legato"),
		("reaction_diffusion", "threshold"), ("motif", "fit"), ("phrase", "fit"),
	):
		parameter = _parameter(verb, name)
		assert (parameter["min"], parameter["max"]) == (0.0, 1.0), f"{verb}.{name}"

	for verb, name in (
		("dropout", "probability"), ("legato", "ratio"), ("randomize", "velocity"),
		("snap_to_scale", "strength"), ("swing", "strength"),
	):
		parameter = _parameter_of(verb, name, subsequence.describe_transform)
		assert (parameter["min"], parameter["max"]) == (0.0, 1.0), f"{verb}.{name}"


def test_a_quantity_with_no_musical_increment_is_left_alone () -> None:

	"""Better no step than an invented one.

	Lorenz's constants and reaction-diffusion's rates are numbers from a
	system of equations with no musical increment, and a stretch factor is
	already served by a tenth — it reaches 0.5, 1.0 and 2.0 on its own.
	"""

	for verb, name in (("lorenz", "sigma"), ("lorenz", "dt"), ("reaction_diffusion", "feed_rate")):
		assert "step" not in _parameter(verb, name), f"{verb}.{name}"

	assert "step" not in _parameter_of("stretch", "factor", subsequence.describe_transform)


def test_repeat_spacing_is_measured_in_beats () -> None:

	"""The one beats parameter #2437 missed, because it was spelled ``Annotated``.

	That pass matched ``spacing: float``; repeat's spacing already carried a
	span and so was written differently, and went out with no unit.  Found by
	the #2367 sweep, which grouped every unbounded control by its unit.
	"""

	spacing = _parameter("repeat", "spacing")

	assert spacing["unit"] == "beats"
	assert spacing["step"] == 0.25
	assert spacing["min"] == 0.01


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


@pytest.mark.parametrize("generator,name,unit", [
	("hit", "beats", "beats"),
	("hit_steps", "steps", "steps"),
	("sequence", "steps", "steps"),
])
def test_a_placing_verb_offers_the_positions_it_fires_at (generator: str, name: str, unit: str) -> None:

	"""The three verbs that took a list of positions and could not say so.

	All three mean one thing — which positions in the bar fire — and differ
	only in the unit.  Before #2411 the list annotation mapped to no shape, so
	each lost a required parameter and reported itself undrivable: a panel
	could add the block and it would sit there doing nothing.
	"""

	parameter = _parameter(generator, name)

	assert parameter["kind"] == "position"
	assert parameter["unit"] == unit
	assert parameter["multiple"] is True
	assert parameter["required"] is True


def test_a_position_publishes_no_bounds () -> None:

	"""How many positions a pattern has is the composition's to know.

	This is the whole reason it is a kind rather than a bounded number: the
	count is per composition and differs per pattern on a real rig, so any
	ceiling published from here would be wrong for somebody.  The same
	reasoning as a pitch, which is why it is the same shape of join (#1465).
	"""

	for generator, name in (("hit", "beats"), ("hit_steps", "steps"), ("sequence", "steps"), ("ratchet", "steps")):

		parameter = _parameter(generator, name)

		assert "min" not in parameter, f"{generator}.{name} published a floor"
		assert "max" not in parameter, f"{generator}.{name} published a ceiling"
		assert "options" not in parameter, f"{generator}.{name} published an option list"


def test_the_unit_is_what_separates_two_otherwise_identical_shapes () -> None:

	"""``List[float]`` against ``List[int]`` is not something to make a consumer guess.

	Whether a verb counts beats or grid indices is a fact about the verb, and
	it is the one half of this that IS ours to publish.
	"""

	assert _parameter("hit", "beats")["unit"] == "beats"
	assert _parameter("hit_steps", "steps")["unit"] == "steps"


def test_every_published_unit_is_one_the_vocabulary_declares () -> None:

	"""A unit typed by hand rather than chosen would reach a consumer unannounced.

	The published field is a plain string and a consumer is handed a word, not
	a vocabulary — that is the whole of #2435, and it is what lets another app
	say ``"kHz"`` without anything in between knowing what one is.  Closing the
	set on *this* side costs a consumer nothing and buys it the one thing a
	free string cannot give: our words are stable, so it may switch on ours.
	"""

	declared = set(typing.get_args(subsequence.declarations.UnitName))

	for entry in subsequence.generators() + subsequence.transforms():

		for parameter in entry["parameters"]:

			if "unit" in parameter:
				assert parameter["unit"] in declared, f"{entry['name']}.{parameter['name']}"


def test_every_word_in_the_vocabulary_is_one_something_actually_sends () -> None:

	"""The other direction, and the one that keeps the set a promise.

	Superconductor's adapter keys bounds and choices on ``(name, unit)`` since
	Simon settled #2435, so these spellings are a contract rather than a
	caption.  A word nobody publishes makes the vocabulary a wish instead — it
	would satisfy the guard above trivially, while saying nothing about what
	actually crosses the wire.  ``notes`` was dropped by this test's reasoning
	once we agreed ``count`` was better left blank than right five times in six.
	"""

	published = {
		parameter["unit"]
		for entry in subsequence.generators() + subsequence.transforms()
		for parameter in entry["parameters"]
		if "unit" in parameter
	}

	unused = set(typing.get_args(subsequence.declarations.UnitName)) - published

	assert not unused, f"declared but never sent: {sorted(unused)} — reserve nothing, add when used"


def test_the_position_units_are_drawn_from_the_same_vocabulary () -> None:

	"""Both reach a consumer under one ``unit`` key, so two spellings would be a defect.

	``PositionUnit`` is the narrower set — a position is counted in steps or in
	beats and in nothing else — but it is not a *separate* vocabulary, and this
	is what stops it drifting into one.  It caught exactly that: positions were
	published as ``"step"`` and ``"beat"`` while every other unit was plural.
	"""

	assert set(typing.get_args(subsequence.declarations.PositionUnit)) <= set(
		typing.get_args(subsequence.declarations.UnitName)
	)


def test_a_declared_unit_reaches_the_entry () -> None:

	"""The three that a surface most needs to tell apart."""

	assert _parameter("euclidean", "velocity")["unit"] == "MIDI velocity"
	assert _parameter("euclidean", "duration")["unit"] == "beats"
	assert _parameter_of("transpose", "semitones", subsequence.describe_transform)["unit"] == "semitones"


def test_one_name_carries_different_units_in_different_verbs () -> None:

	"""Why the unit rides on the declaration and not on a table keyed by name.

	Three names collide outright, and a lookup table would have been wrong on
	the day it was written — which is what makes this worth a test rather than
	a comment.  ``grid`` is the one a consumer would most likely guess at: it
	is a count of slots everywhere except ``swing``, where it is a note value
	in beats.
	"""

	assert _parameter_of("swing", "grid", subsequence.describe_transform)["unit"] == "beats"
	assert _parameter("hit_steps", "grid")["unit"] == "steps"

	# velocity is MIDI velocity everywhere except randomize, where it scales one.
	assert _parameter("euclidean", "velocity")["unit"] == "MIDI velocity"
	assert "unit" not in _parameter_of("randomize", "velocity", subsequence.describe_transform)


def test_a_dial_that_measures_nothing_declares_no_unit () -> None:

	"""A unit is a unit of measure, not a description of the parameter.

	A 0.0-1.0 dial is measured in nothing and its bounds already say what it
	is, so inventing a word for it would be worse than the silence — and the
	ticket that asked for this said so first.
	"""

	for generator, name in (("euclidean", "probability"), ("lorenz", "sigma"), ("thin", "amount")):
		assert "unit" not in _parameter(generator, name), f"{generator}.{name} invented a unit"


def test_declaring_a_unit_does_not_change_the_control_it_is_attached_to () -> None:

	"""The failure this would have shipped, silently, across thirty parameters.

	Every shape question below the markers reads the arms with
	``typing.get_args``, which on an ``Annotated`` returns the marker instead —
	so wrapping ``VelocityValue`` to name its unit demoted every velocity from
	a ``range`` control to no control at all.  Nothing raised; the entries just
	quietly lost a parameter.  ``_unwrap`` is what sees through the wrapper,
	and this is the guard on it.
	"""

	velocity = _parameter("euclidean", "velocity")

	assert velocity["kind"] == "range", "a unit demoted a range control"
	assert velocity["min"] == 1
	assert velocity["max"] == 127
	assert velocity["unit"] == "MIDI velocity"

	# And the same for the other shapes a marker now sits beside.
	assert _parameter("hit_steps", "grid")["kind"] == "number"
	assert _parameter("hit_steps", "grid")["step"] == 1
	assert _parameter_of("duration", "beats", subsequence.describe_transform)["min"] == 0.01

def test_an_optional_position_says_so_and_keeps_its_default () -> None:

	"""``ratchet(steps=)`` limits ratcheting to named zones, or does the lot.

	It sat in the knowingly-dropped ledger with the note that a step list
	"would be a sixth kind and is not ours to invent alone" — which is the kind
	#2411 asked for, so it comes out of the ledger with the other three.
	``None`` still reaches a consumer as ``null``, because leaving it alone is
	how you tell the function to decide for itself.
	"""

	parameter = _parameter("ratchet", "steps")

	assert parameter["kind"] == "position"
	assert parameter["unit"] == "steps"
	assert parameter["required"] is False
	assert parameter["default"] is None


def test_a_position_reads_as_one_or_several_the_way_a_pitch_does () -> None:

	"""The reader is the pitch reader's twin, and is pinned the same way."""

	step = subsequence.declarations.StepPosition
	arity = subsequence.catalogue._position_arity

	assert arity(typing.List[step])[1] is True		# type: ignore[index]
	assert arity(typing.Sequence[step])[1] is True	# type: ignore[index]
	assert arity(step)[1] is False					# type: ignore[index]
	assert arity(typing.List[int]) is None
	assert arity(int) is None


def test_a_position_that_also_declares_a_span_is_still_a_position () -> None:

	"""Where the branch order is actually load-bearing.

	A *lone* position cannot be mistaken for a number, and this test used to
	claim it could: ``Annotated[int, ...]`` never equals ``int``, so that
	branch was never going to take it and moving the position branch below it
	changes nothing.  Measured, not reasoned — the reordering probe passed,
	which is how the claim was caught.

	The branch that *would* take it is the trailing one reading a ``Span`` off
	the metadata.  A position carrying a declared span would publish as a
	bounded number, which is the single thing this kind exists to avoid: how
	many positions a pattern has belongs to the composition, so any bound
	stated here is wrong for somebody (#2411).

	Nothing declares that combination today, which is exactly why it wants a
	test rather than a reader's attention.
	"""

	annotation = typing.Annotated[
		int,
		subsequence.declarations.Span(0.0, 15.0),
		subsequence.declarations.PositionParameter("steps"),
	]

	described = subsequence.catalogue._describe_parameter(
		"where",
		inspect.Parameter("where", inspect.Parameter.POSITIONAL_OR_KEYWORD),
		annotation,
	)

	assert described is not None
	assert described["kind"] == "position"
	assert described["unit"] == "steps"
	assert "min" not in described, "a position published a bound the composition owns"
	assert "max" not in described, "a position published a bound the composition owns"
	assert "multiple" not in described

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
# required and default — the bit that used to be inferred (#2249)
# ---------------------------------------------------------------------------

def test_every_parameter_says_whether_it_is_required () -> None:

	"""Said outright rather than left to be worked out from position.

	A consumer used to read it from order — Python puts undefaulted parameters
	first — and that is a copy of a fact this module already knows.
	"""

	for entry in _every_entry():

		for parameter in entry["parameters"]:
			assert isinstance(parameter["required"], bool), (entry["name"], parameter["name"])


def test_required_and_default_partition_cleanly () -> None:

	"""Required means no default; optional means there is one, even if it is None."""

	for entry in _every_entry():

		for parameter in entry["parameters"]:

			if parameter["required"]:
				assert "default" not in parameter, (entry["name"], parameter["name"])
			else:
				assert "default" in parameter, (entry["name"], parameter["name"])


def test_a_none_default_is_reported_rather_than_omitted () -> None:

	"""The flagship case: `rotate(steps, grid=None)`.

	Both parameters used to look identical in the JSON, so a consumer marked
	both required and opened `grid` at 0 — and `rotate` returns early on a grid
	of 0, so the first transform anybody reaches for did nothing at all.
	"""

	steps = _parameter_of("rotate", "steps", subsequence.describe_transform)
	grid = _parameter_of("rotate", "grid", subsequence.describe_transform)

	assert steps["required"] is True and "default" not in steps
	assert grid["required"] is False and grid["default"] is None


def test_a_none_default_survives_the_wire () -> None:

	"""It reaches a consumer as JSON null, which is the whole point."""

	wire = json.loads(json.dumps(subsequence.describe_transform("rotate")))
	grid = next(p for p in wire["parameters"] if p["name"] == "grid")

	assert grid["default"] is None


def test_the_verbs_that_refuse_a_voicing_argument_now_ask_for_nothing () -> None:

	"""#2240 made `chord` refuse `root` alongside a plain pitch list — rightly.

	A consumer filling every parameter that looked required then tripped that
	check every cycle.  With `root` reported optional-and-null there is nothing
	to fill.
	"""

	for name in ("chord", "strum", "arpeggio"):
		for field in ("root", "count"):
			parameter = _parameter_of(name, field, subsequence.describe_generator)
			assert parameter["required"] is False, (name, field)
			assert parameter["default"] is None, (name, field)


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


def test_snap_to_scale_is_a_transform_and_offers_its_keys () -> None:

	"""It reshapes notes already placed, so it belonged by the line all along.

	It was out only because it described as nothing: `key` was a bare `str`.
	With the vocabulary written down (#2243) it offers seventeen keys, and
	`mode` — open by design, since `register_scale` extends it — is named in
	`dropped` rather than vanishing.  That pairing is why #2239 came first.
	"""

	entry = subsequence.describe_transform("snap_to_scale")
	key = next(p for p in entry["parameters"] if p["name"] == "key")

	assert entry["partial"] is False
	assert entry["dropped"] == ["mode"]
	assert key["kind"] == "choice"
	assert {option["value"] for option in key["options"]} == set(
		subsequence.chords.NOTE_NAME_TO_PC
	)


def test_scratch_is_in_neither_catalogue () -> None:

	"""It returns *a* builder, not *the* builder — and both guards would miss it.

	`test_every_generator_returns_the_builder` passes for it, because the
	annotation says `PatternBuilder`.  `test_a_transform_never_places_a_note`
	passes too, because what a scratch places lands on its own pattern and
	never on this one.  So the two mechanical tests that catch a miscurated
	name are both blind here, and this is the guard instead.

	It is a factory, not a verb: it makes a context to work in rather than
	changing anything.  Offering it on a surface would hand a person a control
	that appears to do nothing.
	"""

	assert "scratch" not in subsequence.catalogue.GENERATORS
	assert "scratch" not in subsequence.catalogue.TRANSFORMS


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

	Its first argument is declared now (#2375), so `chord_obj` has left
	`dropped` — but `order` is required and has no shape, and giving it a
	default it does not have would report the method complete while dropping
	something it genuinely needs.  So the blocker moved rather than went.
	"""

	entry = subsequence.describe_generator("broken_chord")

	assert entry["partial"] is True
	assert entry["dropped"] == ["order"]


# ---------------------------------------------------------------------------
# The chord arm (#2375)
# ---------------------------------------------------------------------------

CHORD_VERBS = {"arpeggio": "notes", "chord": "chord_obj", "strum": "chord_obj"}


@pytest.fixture
def a_registered_quality () -> typing.Iterator[str]:

	"""Register a quality for one test, then put the tables back.

	The tables are module-global and the catalogue reads them live, so a
	quality left behind would change what every later test is offered.
	"""

	before = (
		dict(subsequence.chords.CHORD_INTERVALS),
		dict(subsequence.chords.CHORD_SUFFIX),
		dict(subsequence.chords._SUFFIX_TO_QUALITY),
	)

	subsequence.chords.register_chord_quality("quartal", [0, 5, 10], suffix="q4")

	yield "q4"

	for table, restored in zip(
		(subsequence.chords.CHORD_INTERVALS, subsequence.chords.CHORD_SUFFIX, subsequence.chords._SUFFIX_TO_QUALITY),
		before,
	):
		table.clear()
		table.update(restored)


@pytest.mark.parametrize("name,parameter", sorted(CHORD_VERBS.items()))
def test_a_chord_verb_says_it_takes_a_chord (name: str, parameter: str) -> None:

	"""The Chord arm used to vanish into the pool arm, so no surface could offer it."""

	entry = subsequence.describe_generator(name)
	first = entry["parameters"][0]

	assert first["name"] == parameter
	assert first["kind"] == "pitch"
	assert first["multiple"] is True
	assert first["accepts"] == ["chord", "pitches"]
	assert first["chord"]["roots"] and first["chord"]["qualities"]


def test_a_pool_only_generator_does_not_claim_a_chord () -> None:

	"""The whole point: the ten that really do take only a list must stay apart.

	If `accepts` appeared on everything with a pitch pool it would carry no
	information at all, which is the state this ticket was filed about.
	"""

	pool_only = [
		entry["name"]
		for entry in subsequence.generators()
		for p in entry["parameters"][:1]
		if p.get("kind") == "pitch" and p.get("multiple") and entry["name"] not in CHORD_VERBS
	]

	assert pool_only, "no pool-only generator left to compare against"

	for name in pool_only:
		first = subsequence.describe_generator(name)["parameters"][0]
		assert "accepts" not in first, name
		assert "chord" not in first, name


def test_broken_chord_declares_a_chord_only_control () -> None:

	"""It indexes chord tones, so there is no pool arm to fall back to.

	Declaring it a pitch pool would have handed a consumer a control that
	raises rather than one that is merely coarse — so it gets a kind of its
	own, and `accepts` says the pool form is not on offer.
	"""

	first = subsequence.describe_generator("broken_chord")["parameters"][0]

	assert first["name"] == "chord_obj"
	assert first["kind"] == "chord"
	assert first["accepts"] == ["chord"]
	assert "multiple" not in first


def _chord_builder () -> "subsequence.pattern_builder.PatternBuilder":

	"""A plain builder for driving a chord verb the way a surface would."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	return subsequence.pattern_builder.PatternBuilder(pattern, cycle=0, key="C", scale="major")


# The extra arguments a verb needs that have nothing to do with the chord form.
# broken_chord's `order` is required and has no control shape, which is why it
# stays partial — it is supplied here so the chord form itself can be exercised.
_BESIDES = {"broken_chord": {"order": [0, 1]}}

# A value a surface could defensibly open each declared need at.  Anything in
# `needs` without one fails the tests below rather than being skipped.
_OPENINGS = {"root": 48}


@pytest.mark.parametrize("name", sorted(list(CHORD_VERBS) + ["broken_chord"]))
def test_the_chord_form_names_what_it_requires (name: str) -> None:

	"""`needs` is a claim about a runtime branch, so it is proved rather than trusted.

	`root` is declared `required: false, default: null`, which under #2249's
	rule means *leave it alone* — and the chord form then refuses the call.
	One field cannot say both, so the chord block names the difference; this
	asserts the difference is real, by omitting each named parameter and
	requiring the failure it promises.
	"""

	first = subsequence.describe_generator(name)["parameters"][0]
	needs = first["chord"]["needs"]

	assert needs, f"{name} declares a chord form that needs nothing — is that true?"

	for need in needs:
		assert need in _OPENINGS, f"no opening value known for {need!r} — teach this test"

	# One at a time, with the others supplied.  Omitting them all together
	# would pass for a `needs` naming something the code does not require: the
	# call fails on a different missing argument and the bogus entry survives.
	for omitted in needs:

		arguments = dict(_BESIDES.get(name, {}))
		arguments.update({need: _OPENINGS[need] for need in needs if need != omitted})

		with pytest.raises(Exception):
			getattr(_chord_builder(), name)("Cmaj7", **arguments)


@pytest.mark.parametrize("name", sorted(list(CHORD_VERBS) + ["broken_chord"]))
def test_the_chord_form_works_once_its_needs_are_met (name: str) -> None:

	"""And `needs` is complete: supply what it names and the call goes through.

	The other half of the contract.  A list that named too much would leave a
	surface unable to open a control it could have opened; this is the test
	that would notice.
	"""

	arguments = dict(_BESIDES.get(name, {}))
	first = subsequence.describe_generator(name)["parameters"][0]

	for need in first["chord"]["needs"]:
		assert need in _OPENINGS, f"no opening value known for {need!r} — teach this test"
		arguments[need] = _OPENINGS[need]

	builder = _chord_builder()
	getattr(builder, name)("Cmaj7", **arguments)

	assert builder._pattern.steps, f"{name} placed nothing with its needs met"


def _moved (parameter: typing.Dict[str, typing.Any]) -> typing.Any:

	"""A value of the declared shape that is **not** the declared default.

	Moved rather than opened, because opening values are exactly the ones that
	do not fail: `inversion` opens at 0, which is the one value the pitch-list
	form tolerates, and that is why nothing blew up until a musician turned a
	dial (#2410).
	"""

	kind, default = parameter["kind"], parameter.get("default")

	if kind == "number":
		for candidate in (parameter.get("min"), 1, 2, 0.5):
			if candidate is not None and candidate != default:
				if parameter.get("max") is None or candidate <= parameter["max"]:
					return candidate
		return None

	if kind == "switch":
		return not bool(default)

	if kind == "choice":
		return next((o["value"] for o in parameter["options"] if o["value"] != default), None)

	if kind == "range":
		return [parameter["min"], parameter["max"]]

	return None


@pytest.mark.parametrize("name", sorted(CHORD_VERBS))
def test_only_names_exactly_what_the_pitch_list_form_refuses (name: str) -> None:

	"""`only` is a claim about a runtime branch, so it is measured, not trusted.

	Every declared parameter is moved off its default beside a pitch list, and
	the set that refuses must be exactly the set `only` names — which catches a
	fourth voicing parameter arriving without a line here, and equally catches
	this list naming something that works perfectly well.
	"""

	entry = subsequence.describe_generator(name)
	declared = entry["parameters"]
	refused = set()

	for parameter in declared[1:]:

		value = _moved(parameter)

		if value is None:
			continue

		try:
			getattr(_chord_builder(), name)([36, 40, 43], **{parameter["name"]: value})
		except Exception:
			refused.add(parameter["name"])

	assert refused == set(declared[0]["chord"]["only"])


@pytest.mark.parametrize("name", sorted(CHORD_VERBS))
def test_what_the_chord_form_requires_is_part_of_what_it_owns (name: str) -> None:

	"""`needs` is a subset of `only`: required *with* a chord, refused *without* one.

	Two different facts about the same parameters, and a `needs` entry missing
	from `only` would mean a surface hid a control it was also told to supply.
	"""

	block = subsequence.describe_generator(name)["parameters"][0]["chord"]

	assert set(block["needs"]) <= set(block["only"])


def test_zero_does_not_excuse_a_chord_only_parameter () -> None:

	"""Only *absence* reads as "not asked for" — which is why `only` is needed.

	A surface drawing a stepper can reach zero and cannot reach unset, so a
	dial that looks harmless at its bottom stop still kills the layer.  Pinned
	because it is the whole reason the declaration has to say so.
	"""

	pool = [36, 40, 43]

	_chord_builder().arpeggio(pool)                     # no voicing arguments — plays
	_chord_builder().arpeggio(pool, inversion=0)        # the one tolerated value
	_chord_builder().arpeggio(pool, count=None)         # absence, not zero

	for refused in ({"count": 0}, {"root": 0}, {"inversion": 1}):
		with pytest.raises(ValueError, match="only apply to the chord form"):
			_chord_builder().arpeggio(pool, **refused)


def test_root_is_a_register_rather_than_a_root () -> None:

	"""The name chooses the pitch classes; `root` only chooses the octave.

	Pinned because the declaration cannot say it and a surface would otherwise
	draw two controls named for the same thing.  A chord voices at the nearest
	instance of its OWN root to the number given, so a range of values collapse
	onto one voicing.
	"""

	def voiced (spec: str, root: int) -> typing.List[int]:
		builder = _chord_builder()
		builder.chord(spec, root=root, duration=1.0)
		return sorted(note.pitch for note in builder._pattern.steps[0].notes)

	assert voiced("Cmaj7", 47) == voiced("Cmaj7", 50) == [48, 52, 55, 59]
	assert voiced("Cmaj7", 55) == [60, 64, 67, 71]
	assert voiced("Dm7", 48) == [50, 53, 57, 60]


def test_the_chord_vocabulary_composes_into_a_name_that_works () -> None:

	"""Every root joined to every quality must parse *and* place.

	Publishing two lists is only useful if joining them gives a value these
	verbs accept — a vocabulary that describes something unusable is the
	failure this ticket was about, one level further in.
	"""

	vocabulary = subsequence.describe_generator("chord")["parameters"][0]["chord"]

	for root in vocabulary["roots"]:
		for quality in vocabulary["qualities"]:

			name = root["value"] + quality["value"]
			pattern = subsequence.pattern.Pattern(channel=0, length=4)
			builder = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0, key="C", scale="major")

			builder.chord(name, root=48, duration=1.0)

			assert pattern.steps[0].notes, name


def test_the_chord_vocabulary_is_read_live (a_registered_quality: str) -> None:

	"""register_chord_quality opens the table, so the catalogue must not freeze it.

	A musician who adds a quality should see it on the glass; a frozen list
	would be a second copy of somebody else's table, which is the thing this
	whole catalogue exists to avoid.
	"""

	offered = {q["value"] for q in subsequence.describe_generator("chord")["parameters"][0]["chord"]["qualities"]}

	assert a_registered_quality in offered


def test_a_quality_with_no_suffix_is_not_offered () -> None:

	"""It has no name, and a name is the only thing this list is for."""

	before = dict(subsequence.chords.CHORD_INTERVALS), dict(subsequence.chords.CHORD_SUFFIX)

	subsequence.chords.register_chord_quality("nameless_stack", [0, 5, 10])

	try:
		offered = subsequence.describe_generator("chord")["parameters"][0]["chord"]["qualities"]
		assert all(q["label"] != "nameless stack" for q in offered)
	finally:
		subsequence.chords.CHORD_INTERVALS.clear()
		subsequence.chords.CHORD_INTERVALS.update(before[0])
		subsequence.chords.CHORD_SUFFIX.clear()
		subsequence.chords.CHORD_SUFFIX.update(before[1])


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


def _every_entry () -> typing.List[typing.Dict[str, typing.Any]]:

	"""Both catalogues, since the describer and its contract are shared."""

	return subsequence.generators() + subsequence.transforms()


def _parameter_of (
	name: str,
	field: str,
	describer: typing.Callable[[str], typing.Dict[str, typing.Any]],
) -> typing.Dict[str, typing.Any]:

	"""One named parameter of one entry, from whichever catalogue it is in."""

	for parameter in describer(name)["parameters"]:

		if parameter["name"] == field:
			return parameter

	raise AssertionError(f"{name} has no parameter {field!r}")


def _parameter (generator: str, name: str) -> typing.Dict[str, typing.Any]:

	"""The named parameter of a generator, for brevity in the tests above."""

	for parameter in subsequence.describe_generator(generator)["parameters"]:

		if parameter["name"] == name:
			return parameter

	raise AssertionError(f"{generator} has no parameter {name!r}")
