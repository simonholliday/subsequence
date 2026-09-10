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
