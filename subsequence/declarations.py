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
import math
import typing


logger = logging.getLogger(__name__)


@dataclasses.dataclass (frozen=True)
class Span:

	"""The inclusive range a numeric parameter accepts.

	Attach it with :data:`typing.Annotated`, as in
	``typing.Annotated[float, Span(0.0, 1.0)]``.
	Read it back with :func:`typing.get_type_hints` passing
	``include_extras=True``, which is what keeps the metadata visible.

	``high`` may be left open — ``Span(low=0.01)`` — for a quantity whose only
	real bound is a floor.  A stretch factor or a note duration has a smallest
	useful value and no largest one, and inventing a ceiling to fill the field
	would be a guess a consumer would then draw a slider to.  The catalogue
	omits ``max`` in that case rather than publishing infinity, which is not
	valid JSON.
	"""

	low: float
	high: float = math.inf		# open above: a floor is often the only bound a quantity has


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

# The units this package measures things in.  Deliberately small and closed on
# THIS side while the published field stays a plain string: a consumer is told
# a word, not a vocabulary, so nothing downstream has to know what a beat is —
# but because the set is pinned here and tested, a surface can safely switch on
# ours without us promising a vocabulary to every other app (#2437, #2435).
#
# **These spellings are a published contract, not a caption.**  Simon settled
# #2435 in favour of a closed set per producing app, so Superconductor's
# adapter now KEYS on these words — a bound or a set of choices is looked up by
# ``(name, unit)``.  Renaming one is therefore a break, and a silent one: they
# would not notice, the control would simply stop being bounded.  If a word has
# to move, move it loudly and tell them, the way ``direction`` was retired in
# #2414.  Adding a word is additive and safe; changing or removing one is not.
#
# Every word here is one something actually publishes, and a test says so.  A
# reserved word nobody sends would make the vocabulary a wish rather than a
# promise — ``notes`` was dropped for exactly that reason, once we and
# Superconductor agreed that ``count`` (voices on a chord, notes everywhere
# else) was better left blank than labelled right five times out of six.
#
# A unit is a unit of MEASURE, not a description.  A dial reading 0.0-1.0 has
# no unit and gets none; its bounds already say what it is.
UnitName = typing.Literal[
	"beats",
	"steps",
	"semitones",
	"octaves",
	"MIDI velocity",
	"percent",
]


@dataclasses.dataclass (frozen=True)
class Unit:

	"""What a numeric parameter is measured in, for a surface to draw beside it.

	Attach it with :data:`typing.Annotated`, beside a :class:`Span` where there
	is one.  It carries no bound and implies no conversion — it is a word for a
	person, which is why the same field can say ``"beats"`` here and ``"kHz"``
	from another app without anything in between knowing either.

	It goes on the *declaration* rather than in a table keyed on parameter
	name, because the names genuinely collide: ``length`` is beats on a pattern
	and a count of steps on ``evolve``, ``grid`` is a slot count everywhere
	except ``swing`` where it is beats, and ``velocity`` is MIDI velocity
	everywhere except ``randomize`` where it is a 0-1 scale factor.  A table
	would have been wrong on the day it was written.
	"""

	name: UnitName


# The two that recur often enough to be worth a name, so a signature reads as
# prose and the unit is stated once rather than at each of the fifty-odd sites.
Beats = typing.Annotated[float, Unit("beats")]
StepCount = typing.Annotated[int, Unit("steps")]


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

# Which unit a position is counted in.  Spelled as a vocabulary rather than a
# bare str so a new one cannot be introduced by typing it, and so the catalogue
# publishes a value a consumer can switch on.  Its members are drawn from
# ``UnitName`` and a test pins that, because both reach a consumer under the
# same ``unit`` key and two spellings of one word there would be a defect.
PositionUnit = typing.Literal["steps", "beats"]


@dataclasses.dataclass (frozen=True)
class PositionParameter:

	"""Marks a parameter as naming a position in the pattern.

	The same join as :class:`PitchParameter`, made against the other fact a
	composition owns.  How many positions a pattern has is per-composition — on
	a real rig one pattern runs nine steps where its neighbours run sixteen — so
	a bound published from here would be wrong for somebody.  Subsequence says
	only THAT a parameter is a position, and leaves the count to the consumer
	that knows it (the engine/user boundary, #1465).

	``unit`` is the half that *is* ours.  Whether a verb counts beats or grid
	indices is a fact about the verb, and ``List[int]`` against ``List[float]``
	is not enough for a consumer to tell them apart without guessing (#2411).
	"""

	unit: PositionUnit


# A grid index: which slot of a subdivided bar fires.  How many slots there are
# is the pattern's own business — its ``grid``, or the length it derives one
# from — which is exactly why the bound is not stated here.
StepPosition = typing.Annotated[int, PositionParameter("steps")]

# A position in beats, so a figure is not tied to the grid's resolution.
BeatPosition = typing.Annotated[float, PositionParameter("beats")]

# A velocity: one value, or a (low, high) pair drawn from per note.
#
# The pair may be a tuple **or a list**, and the list arm is load-bearing rather
# than generous.  The catalogue publishes velocity as a "range" control, a
# person moves both handles, and their choice reaches the verb as a JSON array
# — JSON has no tuple.  A tuple-only velocity made every range control the
# catalogue advertises impossible to drive (#2349).  The Tuple arm stays first
# so catalogue._is_range still recognises the shape.
VelocityValue = typing.Annotated[typing.Union[int, typing.Tuple[int, int], typing.List[int]], Unit("MIDI velocity")]

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

# Deliberately NOT shared: arpeggio has figures a strum cannot make.  One alias
# covering both would let strum("forward_and_back") type-check.
#
# ``forward``/``reverse`` walk the pitches in the order they were given;
# ``low_to_high``/``high_to_low`` sort by pitch first.  The distinction is the
# whole point of the vocabulary: for a chord the two are the same, because a
# chord's tones arrive sorted, and for a list somebody picked they are not
# (#2414).  The old ``up``/``down``/``up_down`` were retired rather than
# redefined — reusing a name would have changed what existing pieces play with
# nothing to notice it, where an unknown name raises.
ArpeggioDirection = typing.Literal[
	"forward",
	"reverse",
	"forward_and_back",
	"low_to_high",
	"high_to_low",
	"low_to_high_and_back",
	"random",
]
StrumDirection = typing.Literal["forward", "reverse", "low_to_high", "high_to_low"]

# What the retired names meant, so the error can name the replacement rather
# than only listing what is valid.  ``forward`` preserves behaviour in every
# case: for a chord it is identical to ``low_to_high``, and for a pool it is
# what ``up`` actually did whatever the docstring claimed.
RETIRED_DIRECTIONS: typing.Dict[str, str] = {
	"up": "forward",
	"down": "reverse",
	"up_down": "forward_and_back",
}

PhraseAlign = typing.Literal["pattern", "section"]

# ratchet(shape=) resolves through easing.get_easing(), which raises on an
# unknown name — so these seven are the whole vocabulary, and a Literal makes
# mypy say so at the call site instead of at run time.
EasingCurve = typing.Literal[
	"linear",
	"ease_in",
	"ease_out",
	"ease_in_out",
	"exponential",
	"logarithmic",
	"s_curve",
]

# The note names a key may be spelled with — chords.NOTE_NAME_TO_PC, which is
# strict: "Cb", "E#", lowercase and "H" all raise.  Written out rather than
# derived, because a Literal needs literals; a test pins it to the table so the
# two cannot drift.
KeyName = typing.Literal[
	"A", "A#", "Ab",
	"B", "Bb",
	"C", "C#",
	"D", "D#", "Db",
	"E", "Eb",
	"F", "F#",
	"G", "G#", "Gb",
]

# Registered Parameter Numbers.  Unlike CC and NRPN names — which come from the
# instrument, through a per-pattern map — these are the MIDI specification's and
# there is no per-pattern RPN map to extend them, so the vocabulary really is
# closed.  It belongs to pymididefs, though, so a test pins this against
# pymididefs.rpn.RPN_MAP rather than trusting a copy made once.
RpnParameter = typing.Literal[
	"channel_coarse_tuning",
	"channel_fine_tuning",
	"modulation_depth_range",
	"null_parameter",
	"pitch_bend_sensitivity",
	"tuning_bank_select",
	"tuning_program_select",
]

# cellular_2d(initial_state=) takes one of these names or an explicit grid.
CellularSeed = typing.Literal["center", "random"]


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


# The decorated function's own type, so the signature survives decoration.
# A bare ``typing.Callable`` return has no parameters and no return type, which
# erases every decorated generator as far as a type checker is concerned — the
# vocabularies above then went unenforced at exactly the fourteen call sites
# they were written for (#2156).  Do not simplify this back to ``Callable``.
_Decorated = typing.TypeVar("_Decorated", bound=typing.Callable[..., typing.Any])


def bounded (fn: _Decorated) -> _Decorated:

	"""Clamp *fn*'s ``Span``-annotated arguments, warning once per parameter.

	Makes the annotation load-bearing: a wrong bound clamps wrongly and shows
	up, where a bound nothing consults could disagree with the code forever.

	Accepts the argument positionally or by keyword, and does nothing at all
	when every value is already inside its span — the common case, which stays
	free of allocation.

	The wrapper is cast back to the decorated function's own type so mypy still
	sees the real signature — the parameters, their vocabularies, and the
	builder it returns for chaining.
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
				# An open span has no ceiling to name, and "0.01–inf" reads as
				# a typo rather than as a bound.
				where = (
					f"below {span.low}" if math.isinf(span.high)
					else f"outside {span.low}–{span.high}"
				)
				_warned.add(key)
				logger.warning(
					f"{fn.__name__}({name}={given}) is {where}; "
					f"using {pinned}. Further overshoots of this parameter are not logged."
				)

			if index < len(args):
				if positional is None:
					positional = list(args)
				positional[index] = pinned
			else:
				kwargs[name] = pinned

		return fn(*(positional if positional is not None else args), **kwargs)

	return typing.cast(_Decorated, wrapper)
