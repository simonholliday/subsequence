"""Types that let a generator's signature carry what its docstring says.

A bare ``float`` cannot say "between 0.0 and 1.0", and a bare ``str`` cannot say
"one of these eight names".  Both facts live in docstring prose today, which
means nothing checks them and nothing can read them back.  The aliases here move
those facts onto the annotation, where mypy enforces the vocabularies and
:func:`subsequence.catalogue.generators` can report the bounds.

**The bounds are load-bearing, not documentation.**  A generator that declares
one clamps its argument to it (see :func:`bounded`), so a ``Span`` that drifts
out of step with the code misbehaves audibly instead of quietly lying to a
control surface.  mypy ignores ``Annotated`` metadata, so a bound nothing
enforces could drift exactly as a docstring can.

Clamping rather than raising is deliberate.  A rebuild runs every bar, and a
failing one costs its pattern that cycle (see ``Sequencer._reschedule_due``), so
validation would silence a part mid-performance every time a control overshot.
Clamping keeps the music playing and logs the overshoot once.
"""

import dataclasses
import functools
import inspect
import logging
import typing


logger = logging.getLogger(__name__)


@dataclasses.dataclass (frozen=True)
class Span:

	"""The inclusive range a numeric parameter accepts.

	Attach it with :data:`typing.Annotated`, as in
	``typing.Annotated[float, Span(0.0, 1.0)]``.
	Read it back with :func:`typing.get_type_hints` passing
	``include_extras=True``, which is what keeps the metadata visible.
	"""

	low: float
	high: float


	def clamp (self, value: float) -> float:

		"""Return *value* pinned inside the span."""

		if value < self.low:
			return self.low

		if value > self.high:
			return self.high

		return value


# The two ranges that recur.  Named so a signature reads as prose and so the
# bound is stated once rather than at each of the twenty-odd call sites.
UnitInterval = typing.Annotated[float, Span(0.0, 1.0)]
VelocityScale = typing.Annotated[float, Span(0.0, 2.0)]

@dataclasses.dataclass (frozen=True)
class PitchParameter:

	"""Marks a parameter as naming a pitch.

	A bare ``typing.Union[int, str]`` alias would not survive introspection —
	``get_type_hints`` resolves an alias to its target and the name is gone, so
	a pitch would be indistinguishable from any other int-or-string.  The
	marker is what makes it readable back.
	"""


# A pitch: a MIDI note number, or a name the caller's drum map or note-name
# table resolves.  Subsequence says only THAT a parameter is a pitch — which
# values are legal is rig-specific and belongs to the composition file, never
# here (the engine/user boundary, #1465).
Pitch = typing.Annotated[typing.Union[int, str], PitchParameter()]

# Probability-curve names.  ghost_fill(bias=) and thin(strategy=) share this
# vocabulary because they share build_ghost_bias(); thin's docstring already
# promises they match, and one alias turns that promise into something mypy
# keeps true.
BiasCurve = typing.Literal[
	"uniform",
	"offbeat",
	"sixteenths",
	"before",
	"after",
	"downbeat",
	"upbeat",
	"e_and_a",
]

# thin() takes the same curves plus one of its own.  "strength" expresses a
# weakest-first thinning hierarchy, which has no meaningful ghost_fill
# equivalent — the code says so at the branch that handles it.  Spelled flat
# rather than as Union[BiasCurve, Literal["strength"]] so the catalogue can read
# the options without unwrapping nested unions; a test pins the two together so
# they cannot drift.
ThinStrategy = typing.Literal[
	"strength",
	"uniform",
	"offbeat",
	"sixteenths",
	"before",
	"after",
	"downbeat",
	"upbeat",
	"e_and_a",
]

# Deliberately NOT shared: arpeggio cycles four ways and strum only reverses.
# One alias covering both would let strum("up_down") type-check.
ArpeggioDirection = typing.Literal["up", "down", "up_down", "random"]
StrumDirection = typing.Literal["up", "down"]

PhraseAlign = typing.Literal["pattern", "section"]


# Which (function, parameter) pairs have already been warned about.  A rebuild
# runs every bar, so warning per call would flood the log for the whole time a
# control sat past its bound — the first one is the useful one.
_warned: typing.Set[typing.Tuple[str, str]] = set()


def _spans_of (fn: typing.Callable) -> typing.Dict[str, typing.Tuple[int, Span]]:

	"""Map each bounded parameter of *fn* to its positional index and span.

	Resolved once per decorated function and cached by :func:`bounded`, because
	``get_type_hints`` is far too slow to call on every rebuild.
	"""

	try:
		hints = typing.get_type_hints(fn, include_extras=True)
	except Exception:
		# A forward reference that cannot be resolved at decoration time must
		# not stop the module importing; the parameter simply goes unbounded.
		logger.debug(f"Could not resolve type hints for {fn.__name__}; bounds not enforced")
		return {}

	order = list(inspect.signature(fn).parameters)
	found: typing.Dict[str, typing.Tuple[int, Span]] = {}

	for name, hint in hints.items():

		for meta in getattr(hint, "__metadata__", ()):

			if isinstance(meta, Span):
				found[name] = (order.index(name), meta)
				break

	return found


def bounded (fn: typing.Callable) -> typing.Callable:

	"""Clamp *fn*'s ``Span``-annotated arguments, warning once per parameter.

	Makes the annotation load-bearing: a wrong bound clamps wrongly and shows
	up, where a bound nothing consults could disagree with the code forever.

	Accepts the argument positionally or by keyword, and does nothing at all
	when every value is already inside its span — the common case, which stays
	free of allocation.
	"""

	spans: typing.Optional[typing.Dict[str, typing.Tuple[int, Span]]] = None

	@functools.wraps(fn)
	def wrapper (*args: typing.Any, **kwargs: typing.Any) -> typing.Any:

		nonlocal spans

		if spans is None:
			spans = _spans_of(fn)

		positional: typing.Optional[typing.List[typing.Any]] = None

		for name, (index, span) in spans.items():

			if index < len(args):
				given = args[index]
			elif name in kwargs:
				given = kwargs[name]
			else:
				continue

			# A None or a non-number is somebody else's error to report.
			if not isinstance(given, (int, float)) or isinstance(given, bool):
				continue

			pinned = span.clamp(given)

			if pinned == given:
				continue

			key = (fn.__qualname__, name)

			if key not in _warned:
				_warned.add(key)
				logger.warning(
					f"{fn.__name__}({name}={given}) is outside {span.low}–{span.high}; "
					f"using {pinned}. Further overshoots of this parameter are not logged."
				)

			if index < len(args):
				if positional is None:
					positional = list(args)
				positional[index] = pinned
			else:
				kwargs[name] = pinned

		return fn(*(positional if positional is not None else args), **kwargs)

	return wrapper
