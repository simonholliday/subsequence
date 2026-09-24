"""Everything the catalogue calls drivable must actually build.

The catalogue makes a promise — *here is a generator, here are its controls,
here is what each one accepts* — and until now nothing checked that a consumer
following it to the letter got music rather than an exception.  Three separate
defects hid in that gap and all three were found from the far side, by
Superconductor running its panel against a real rig:

- a parameter defaulting to ``None`` was indistinguishable from one with no
  default, so a surface supplied a number where the function wanted to be told
  nothing (#2249);
- three required numbers declared no floor, so the only value a surface could
  invent for them was the one value they refused (#2251);
- every ``range`` control was refused outright, because a person's choice
  arrives as a JSON array and the resolver wanted a tuple (#2349).

The shape of this test is Superconductor's own, offered on #2251 and adopted
here rather than left on their side alone: **a guard only one side runs is a
guard that goes stale on the other.**
"""

import typing

import pytest

import subsequence
import subsequence.pattern
import subsequence.pattern_builder


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	"""A builder with the little a surface would have configured for it.

	A drum map, because named voices are how a panel addresses a kit, and a few
	notes already placed, because a transform needs something to reshape.
	"""

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern, cycle=0, drum_note_map={"kick": 36, "snare": 38}, key="C", scale="major",
	)
	builder.hit(36, [0.0, 1.0, 2.0, 3.0])

	return builder


def _opening (parameter: typing.Dict[str, typing.Any]) -> typing.Any:

	"""The value a surface can defensibly open a required control at.

	Declared bounds where there are any; otherwise the least surprising value
	of that shape.  Inventing a range would be a guess, so where the catalogue
	says nothing this falls back to zero — which is exactly what made #2251
	visible, and is the behaviour worth keeping rather than papering over.
	"""

	kind = parameter["kind"]

	if kind == "number":
		return parameter.get("min", 0)
	if kind == "choice":
		return parameter["options"][0]["value"]
	if kind == "switch":
		return False
	if kind == "pitch":
		return [60] if parameter.get("multiple") else 60
	if kind == "position":
		# No bound is published on purpose — how many positions a pattern has
		# belongs to the composition, not to the function (#2411) — so this
		# falls back to zero, which is the one position every pattern has.
		return [0] if parameter.get("multiple") else 0
	if kind == "range":
		# A list, not a tuple: JSON has no tuple, and this is the only shape a
		# consumer can actually send.
		return [parameter["min"], parameter["max"]]
	if kind == "chord":
		# A name, not a Chord: an object does not cross a wire either, so this
		# is built the way a surface builds it — a root joined to a quality.
		return parameter["chord"]["roots"][0]["value"] + parameter["chord"]["qualities"][0]["value"]

	raise AssertionError(f"no opening value for kind {kind!r}")


def _drivable () -> typing.List[typing.Dict[str, typing.Any]]:

	"""Every entry the catalogue says can be fully driven."""

	return [
		entry
		for entry in subsequence.generators() + subsequence.transforms()
		if not entry["partial"]
	]


@pytest.mark.parametrize("entry", _drivable(), ids=lambda entry: str(entry["name"]))
def test_a_drivable_entry_builds_at_its_opening_values (entry: typing.Dict[str, typing.Any]) -> None:

	"""Supply only what is required, from what the catalogue declares.

	Anything optional is left alone — that is what ``required: false`` means,
	and for a ``None`` default it is the whole point: the function decides for
	itself.  If this raises, the catalogue has promised something the code will
	not honour, and a person on a control surface hears silence and has to read
	a log to find out why.
	"""

	arguments = {
		parameter["name"]: _opening(parameter)
		for parameter in entry["parameters"]
		if parameter["required"]
	}

	try:
		getattr(_builder(), entry["name"])(**arguments)
	except Exception as error:		# noqa: BLE001 — the failure is the point
		raise AssertionError(
			f"{entry['name']}({arguments}) is reported drivable but raised "
			f"{type(error).__name__}: {error}"
		) from error


def _declared_edges (parameter: typing.Dict[str, typing.Any]) -> typing.List[typing.Any]:

	"""Each value at an edge of what an optional control declares it accepts.

	A number at whichever bounds it declares; a range at each end and across
	both, as the JSON arrays a surface sends; every option of a choice; both
	positions of a switch.  A number that declares no bounds gives nothing:
	inventing a range would be a guess, so those are listed below instead.
	"""

	kind = parameter["kind"]

	if kind == "number":
		return [parameter[end] for end in ("min", "max") if end in parameter]
	if kind == "range":
		low, high = parameter["min"], parameter["max"]
		return [[low, low], [high, high], [low, high]]
	if kind == "choice":
		return [option["value"] for option in parameter["options"]]
	if kind == "switch":
		return [True, False]

	return []


@pytest.mark.parametrize("entry", _drivable(), ids=lambda entry: str(entry["name"]))
def test_a_drivable_entry_builds_at_every_edge_its_optional_controls_declare (entry: typing.Dict[str, typing.Any]) -> None:

	"""Each optional control, one at a time, at each edge it publishes (#3431).

	The opening values leave optional controls alone, so a control a surface
	draws could fail at an edge it publishes and nothing here would say:
	lorenz's ``dt`` silenced its part on every rebuild from about 0.025, and
	only a render found it (#3408).  Required controls open as above, and the
	other optional ones keep their defaults.  An entry whose required count
	publishes no bounds opens it at zero and places nothing, so an edge that
	matters only once notes are placed is not reached there (euclidean,
	bresenham and golden, with the unbounded controls below).
	"""

	required = {
		parameter["name"]: _opening(parameter)
		for parameter in entry["parameters"]
		if parameter["required"]
	}

	failures: typing.List[str] = []

	for parameter in entry["parameters"]:

		if parameter["required"]:
			continue

		for value in _declared_edges(parameter):

			arguments = dict(required, **{parameter["name"]: value})

			try:
				getattr(_builder(), entry["name"])(**arguments)
			except Exception as error:		# noqa: BLE001 - the failure is the point
				failures.append(f"{parameter['name']}={value!r}: {type(error).__name__}: {error}")

	assert failures == [], f"{entry['name']} is reported drivable but raised at an edge it declares"


def test_the_edges_are_driven_for_most_drivable_entries () -> None:

	"""The guard on that guard, as a proportion for the reason given below."""

	with_edges = [
		entry for entry in _drivable()
		if any(not parameter["required"] and _declared_edges(parameter) for parameter in entry["parameters"])
	]

	assert len(with_edges) > len(_drivable()) // 2


# The optional numbers a drivable entry publishes with no bounds, as they stood
# on 2026-09-24 (#3431).  The edge test above cannot drive them, and giving them
# bounds changes what a surface offers, which is Simon's call.  Until then none
# may be added: a new optional number declares its bounds.  When one of these
# gains bounds, take it off this list.
_UNBOUNDED_OPTIONAL_NUMBERS: typing.Dict[str, typing.Set[str]] = {
	"arpeggio": {"beat", "count", "duration", "inversion", "root", "spacing", "span"},
	"branch": {"depth", "duration", "path", "spacing"},
	"bresenham": {"duration"},
	"cellular_1d": {"duration", "generation", "rule"},
	"cellular_2d": {"duration", "generation"},
	"chord": {"beat", "count", "detached", "duration", "inversion", "root"},
	"de_bruijn": {"duration", "spacing", "window"},
	"detached": {"beats"},
	"drone": {"beat"},
	"euclidean": {"duration"},
	"evolve": {"duration", "length", "spacing"},
	"fibonacci": {"a", "b", "count", "duration", "modulus", "spacing"},
	"ghost_fill": {"duration", "grid"},
	"golden": {"duration"},
	"hit": {"duration"},
	"hit_steps": {"duration", "grid"},
	"invert": {"pivot"},
	"lorenz": {"beta", "duration", "rho", "sigma", "spacing", "x0", "y0", "z0"},
	"note": {"duration"},
	"randomize": {"timing"},
	"ratchet": {"grid", "subdivisions"},
	"reaction_diffusion": {"duration"},
	"recaman": {"count", "duration", "octave_span", "skip", "spacing", "start"},
	"repeat": {"duration"},
	"rotate": {"grid"},
	"self_avoiding_walk": {"duration", "spacing"},
	"sequence": {"grid"},
	"strum": {"beat", "count", "detached", "duration", "inversion", "root", "spacing"},
	"swing": {"grid", "percent"},
	"thin": {"grid"},
	"thue_morse": {"duration"},
	"velocity_shape": {"high", "low"},
}


def test_no_optional_number_is_published_unbounded_beyond_those_known () -> None:

	"""A new optional number declares its bounds, so the edge test can drive it (#3431).

	Exactly the list, not within it, so a control that gains bounds leaves
	the list in the same change and the list stays a true account.
	"""

	unbounded: typing.Dict[str, typing.Set[str]] = {}

	for entry in _drivable():
		for parameter in entry["parameters"]:
			if not parameter["required"] and parameter["kind"] == "number" and not _declared_edges(parameter):
				unbounded.setdefault(entry["name"], set()).add(parameter["name"])

	assert unbounded == _UNBOUNDED_OPTIONAL_NUMBERS


def test_every_drivable_entry_is_covered () -> None:

	"""The sweep is worth nothing if it silently stops covering things.

	A parametrised test that collects nothing still passes, so this is the
	guard on the guard.  It is written as a proportion rather than a count: a
	fixed number would churn every time a generator is added or leaves the
	partial list, and churn is how a guard ends up being edited to fit rather
	than read.
	"""

	published = subsequence.generators() + subsequence.transforms()

	assert _drivable(), "nothing was swept — the parametrisation has collapsed"
	assert len(_drivable()) > len(published) // 2
