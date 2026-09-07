"""Report the generators and transforms, and their parameters, as plain data.

A control surface can ask what Subsequence offers and build controls from the
answer, so adding a generator here makes it appear over there with nobody
editing anything.  The point is that no list of parameters exists anywhere but
in the code that owns them.

**This module describes; it does not draw.**  Nothing here knows about any
particular consumer, and the return value is plain dicts and lists — no classes
to import, no protocol to satisfy.  A parameter whose type maps to none of the
five control shapes is simply left out.

The shape is fixed by agreement with the consumer, so treat it as a contract:

    {
      "name": "ghost_fill",
      "summary": "Fill the pattern with probability-biased ghost notes.",
      "partial": False,
      "parameters": [
        {"name": "density", "kind": "number", "label": "density",
         "min": 0.0, "max": 1.0, "default": 0.3},
        ...
      ],
      "dropped": [],
    }

``partial`` says a *required* parameter has no shape — a list, a dict, a
callable — so the generator cannot be fully offered.  It is reported rather
than hidden, because a control that cannot be completed is worse than one that
is absent, and only the caller can decide which to show.

``dropped`` names every parameter left out for want of a shape, required or
not.  ``partial`` alone was not enough: it speaks only for the *required*
ones, so an optional parameter with no shape vanished from an entry that still
said ``"partial": False`` — a consumer told "fully offerable" about something
it could not fully drive (#2239).  Naming them costs nothing and is the
difference between a gap and a silence.  Machine-only parameters are not
listed: they are deliberately not offered, which is a different fact.

There are two catalogues and one describer.  :func:`generators` lists what
*places* notes; :func:`transforms` lists what *reshapes* notes already placed.
The entries have the same shape, because a surface drives both the same way —
``getattr(pattern, name)(**params)`` — so a consumer needs no second code path.

Each list is a curation judgement rather than a category, and each has a
mechanical test that :mod:`tests.test_catalogue` runs rather than eyeballs: a
generator returns the builder and places notes; a transform returns the builder
and never increases the note count.  Curating by reading names is what once put
an accessor among the generators (#2096).  Accessors that return data are out of
both, and so is MIDI plumbing, which emits control events rather than touching
notes.  See :data:`GENERATORS` and :data:`TRANSFORMS` for the lists and the
reasoning.
"""

import collections.abc
import inspect
import typing

import subsequence.declarations
import subsequence.pattern_builder


# Every generator offered, in the order a catalogue lists them.
#
# The line is "does it place notes", so `rotate`, `swing` and `dropout` are out
# as transforms, and `bar_cycle`, `signal` and `capture` are out as accessors.
# Four exclusions are judgement rather than category:
#
#   seq          the mini-notation entry point.  Mini-notation is ratified
#                legacy — nothing new may accept, emit, extend or document it —
#                and offering it here would do exactly that.  Its parameter is
#                a notation string, which maps to no control shape anyway.
#   note_on      raw halves of a pair.  A surface offering note_on with no
#   note_off     matching note_off is a hanging-note generator.
#   drone_off
#   silence      a transport action (All Notes Off), not a generator.
#
# `build_ghost_bias`, `duck_map` and `section_motif` are accessors: they return
# data rather than the builder.  A generator places notes and returns self for
# chaining, which is the mechanical test — see test_catalogue.py.
GENERATORS: typing.Tuple[str, ...] = (
	# subsequence.pattern_algorithmic
	"branch",
	"bresenham",
	"bresenham_poly",
	"cellular_1d",
	"cellular_2d",
	"de_bruijn",
	"euclidean",
	"evolve",
	"fibonacci",
	"ghost_fill",
	"golden",
	"lorenz",
	"lsystem",
	"markov",
	"melody",
	"ratchet",
	"reaction_diffusion",
	"recaman",
	"self_avoiding_walk",
	"thin",
	"thue_morse",
	# subsequence.pattern_builder — the note-placing verbs
	"arpeggio",
	"broken_chord",
	"chord",
	"drone",
	"hit",
	"hit_steps",
	"motif",
	"note",
	"phrase",
	"repeat",
	"sequence",
	"strum",
)

# Every transform offered, in the order a catalogue lists them.
#
# The line here is the exact complement of the one above: **does it reshape
# notes already placed?**  That is what keeps this a category rather than a
# leftovers bin, and it is why the tuple is twelve rather than the twenty-odd
# methods that merely happen to describe cleanly.
#
# Out, and why:
#
#   cc, nrpn, rpn      MIDI plumbing.  These emit control events; they do not
#   osc, sysex, bend   reshape notes.  Including them would make transforms()
#   program_change     mean "everything that is not a generator", which is not
#   the *_ramp family  a category and would not survive its first addition.
#   set_length         changes the pattern, not its notes.
#   every, groove      real transforms, but each requires something with no
#   scale_velocities   control shape — a callable, a template, a factor list,
#   apply_tuning       a Tuning.  Not excluded on principle; they can join as
#                      partial entries whenever somebody wants them.
#
# A transform never increases the note count and places nothing on an empty
# pattern.  That is the mechanical form of the line and test_catalogue.py runs
# it — curating by reading names is what once put an accessor among the
# generators (#2096).
TRANSFORMS: typing.Tuple[str, ...] = (
	"rotate",
	"snap_to_scale",
	"swing",
	"dropout",
	"randomize",
	"velocity_shape",
	"transpose",
	"invert",
	"stretch",
	"legato",
	"detached",
	"duration",
	"reverse",
)


# Parameters that exist for the machine, not for a person.  A seed is an int in
# the signature, but what a musician wants is a freeze switch — a control the
# agreed five kinds cannot express without either a sixth kind or per-parameter
# knowledge in the consumer.  Left out until freezing is designed on its own
# terms rather than half-expressed here.
_NOT_FOR_PEOPLE: typing.FrozenSet[str] = frozenset({"self", "rng", "seed"})


def _is_optional (annotation: typing.Any) -> bool:

	"""True when *annotation* is ``Optional[...]`` — a Union including None."""

	return (
		typing.get_origin(annotation) is typing.Union
		and type(None) in typing.get_args(annotation)
	)


def _strip_optional (annotation: typing.Any) -> typing.Any:

	"""Return *annotation* with any ``None`` arm removed."""

	if not _is_optional(annotation):
		return annotation

	remaining = [a for a in typing.get_args(annotation) if a is not type(None)]

	return remaining[0] if len(remaining) == 1 else typing.Union[tuple(remaining)]


def _span_of (annotation: typing.Any) -> typing.Optional[subsequence.declarations.Span]:

	"""The :class:`~subsequence.declarations.Span` attached to *annotation*, if any."""

	for meta in getattr(annotation, "__metadata__", ()):

		if isinstance(meta, subsequence.declarations.Span):
			return meta

	return None


def _is_pitch (annotation: typing.Any) -> bool:

	"""True when *annotation* carries the pitch marker."""

	return any(
		isinstance(meta, subsequence.declarations.PitchParameter)
		for meta in getattr(annotation, "__metadata__", ())
	)


# What "several pitches" can be spelled as.  ``Sequence`` sits beside ``list``
# because ``list`` is invariant: a parameter annotated ``List[Pitch]`` rejects
# the ``List[int]`` that ``held_notes()`` returns, and rejects any homogeneous
# list a caller already holds.  A generator taking a pool the caller supplies
# therefore wants the covariant spelling, and this has to recognise it or the
# generator reads as unofferable (#2155).
_POOL_ORIGINS: typing.Tuple[typing.Any, ...] = (list, collections.abc.Sequence)


def _is_pitch_pool (annotation: typing.Any) -> bool:

	"""True when *annotation* is a container of pitches rather than one pitch."""

	if typing.get_origin(annotation) not in _POOL_ORIGINS:
		return False

	arguments = typing.get_args(annotation)

	return bool(arguments) and _is_pitch(arguments[0])


def _pitch_arity (annotation: typing.Any) -> typing.Optional[bool]:

	"""Whether *annotation* is a pitch, and if so whether it takes several.

	Returns None when it is not a pitch at all, False for exactly one, True
	when several are accepted.  Eleven generators take a pitch *pool* rather
	than a single pitch, so without this they would all report as unofferable
	for a reason that is really about multiplicity, not about shape.
	"""

	if _is_pitch(annotation):
		return False

	if typing.get_origin(annotation) in _POOL_ORIGINS:
		return True if _is_pitch_pool(annotation) else None

	# Union[Pitch, List[Pitch]], or Union[Chord, Sequence[Pitch]] — one or
	# several, so offer several.
	takes_several = False
	takes_one = False

	for arm in typing.get_args(annotation):

		if _is_pitch(arm):
			takes_one = True
		elif _is_pitch_pool(arm):
			takes_several = True

	if takes_several:
		return True

	return False if takes_one else None


def _is_range (annotation: typing.Any) -> bool:

	"""True when *annotation* offers a ``Tuple[int, int]`` arm — a low/high pair."""

	for arm in typing.get_args(annotation):

		if typing.get_origin(arm) is tuple and typing.get_args(arm) == (int, int):
			return True

	return False


def _literal_options (annotation: typing.Any) -> typing.Optional[typing.List[str]]:

	"""The string options of a ``Literal`` arm, searched one level into a Union."""

	if typing.get_origin(annotation) is typing.Literal:
		return [str(a) for a in typing.get_args(annotation)]

	for arm in typing.get_args(annotation):

		if typing.get_origin(arm) is typing.Literal:
			return [str(a) for a in typing.get_args(arm)]

	return None


def _describe_parameter (
	name: str,
	parameter: inspect.Parameter,
	annotation: typing.Any,
) -> typing.Optional[typing.Dict[str, typing.Any]]:

	"""One parameter as a control, or None when its type maps to no shape."""

	label = name.replace("_", " ")
	default = parameter.default
	has_default = default is not inspect.Parameter.empty

	bare = _strip_optional(annotation)
	entry: typing.Dict[str, typing.Any] = {"name": name, "label": label}

	# Order matters: a pitch is an int-or-str and would otherwise read as a
	# number, and a Literal is a str and would otherwise read as free text.
	several = _pitch_arity(bare)

	if several is not None:
		entry["kind"] = "pitch"
		# An addition to the agreed five kinds rather than a sixth kind:
		# eleven generators take a pitch POOL, and reporting those as
		# unofferable would hide a third of the catalogue over a question
		# of multiplicity.
		# A consumer that ignores this key still renders a usable single-pitch
		# control, so it degrades rather than breaks.
		if several:
			entry["multiple"] = True
		if has_default and default is not None:
			entry["default"] = default
		return entry

	options = _literal_options(bare)

	if options is not None:
		entry["kind"] = "choice"
		entry["options"] = [{"value": o, "label": o.replace("_", " ")} for o in options]
		if has_default and default is not None:
			entry["default"] = default
		return entry

	if _is_range(bare):
		entry["kind"] = "range"
		entry["min"] = 1
		entry["max"] = 127
		if has_default and default is not None:
			entry["default"] = list(default) if isinstance(default, tuple) else default
		return entry

	if bare is bool:
		entry["kind"] = "switch"
		if has_default and default is not None:
			entry["default"] = default
		return entry

	if bare is int or bare is float:
		entry["kind"] = "number"
		span = _span_of(annotation)
		if span is not None:
			entry["min"] = span.low
			entry["max"] = span.high
		# An int steps by one; a float's useful step depends on its range, so
		# it is left for the consumer to choose rather than invented here.
		if bare is int:
			entry["step"] = 1
		if has_default and default is not None:
			entry["default"] = default
		return entry

	span = _span_of(annotation)

	if span is not None:
		entry["kind"] = "number"
		entry["min"] = span.low
		entry["max"] = span.high
		if has_default and default is not None:
			entry["default"] = default
		return entry

	return None


def _describe (name: str) -> typing.Dict[str, typing.Any]:

	"""Describe one method's parameters as plain data — generator or transform.

	The two catalogues differ only in which names they list; what a control
	looks like is the same question either way, so it is answered once here.
	"""

	function = getattr(subsequence.pattern_builder.PatternBuilder, name)
	signature = inspect.signature(function)

	try:
		hints = typing.get_type_hints(function, include_extras=True)
	except Exception:
		hints = {}

	summary = (inspect.getdoc(function) or "").strip().split("\n")[0]

	parameters: typing.List[typing.Dict[str, typing.Any]] = []
	dropped: typing.List[str] = []
	partial = False

	for parameter_name, parameter in signature.parameters.items():

		if parameter_name in _NOT_FOR_PEOPLE:
			continue

		annotation = hints.get(parameter_name, parameter.annotation)
		described = _describe_parameter(parameter_name, parameter, annotation)

		if described is None:
			# Name it either way.  A required one also sets partial, because a
			# surface could otherwise offer a control that can never be
			# completed; an optional one used to leave no trace at all, which
			# is how a generator came to report itself fully offerable while
			# quietly missing a parameter.
			dropped.append(parameter_name)
			if parameter.default is inspect.Parameter.empty:
				partial = True
			continue

		parameters.append(described)

	return {
		"name": name,
		"summary": summary,
		"partial": partial,
		"parameters": parameters,
		"dropped": dropped,
	}


def describe_generator (name: str) -> typing.Dict[str, typing.Any]:

	"""Describe one generator's parameters as plain data.

	Parameters:
		name: The generator's method name on ``PatternBuilder``, e.g.
			``"ghost_fill"``.

	Returns:
		A dict with ``name``, ``summary``, ``partial``, ``parameters`` and
		``dropped`` — see this module's contract.

	Raises:
		ValueError: if *name* is not a declared generator.  A transform is
			named as such rather than reported missing, since the two
			catalogues are easy to confuse and the answer is one call away.

	Example:
		```python
		import subsequence

		shape = subsequence.describe_generator("euclidean")
		shape["parameters"][0]["kind"]     # 'pitch'
		```
	"""

	if name not in GENERATORS:

		if name in TRANSFORMS:
			raise ValueError(
				f"{name!r} is a transform, not a generator — "
				f"use subsequence.describe_transform({name!r})."
			)

		raise ValueError(
			f"{name!r} is not a declared generator. "
			f"Use subsequence.generators() to see the {len(GENERATORS)} available."
		)

	return _describe(name)


def describe_transform (name: str) -> typing.Dict[str, typing.Any]:

	"""Describe one transform's parameters as plain data.

	Parameters:
		name: The transform's method name on ``PatternBuilder``, e.g.
			``"rotate"``.

	Returns:
		The same shape :func:`describe_generator` returns.  A transform is
		applied the same way a generator is, so a caller that can drive one
		can drive the other without a second code path.

	Raises:
		ValueError: if *name* is not a declared transform.

	Example:
		```python
		import subsequence

		shape = subsequence.describe_transform("rotate")
		shape["parameters"][0]["name"]     # 'steps'
		```
	"""

	if name not in TRANSFORMS:

		if name in GENERATORS:
			raise ValueError(
				f"{name!r} is a generator, not a transform — "
				f"use subsequence.describe_generator({name!r})."
			)

		raise ValueError(
			f"{name!r} is not a declared transform. "
			f"Use subsequence.transforms() to see the {len(TRANSFORMS)} available."
		)

	return _describe(name)


def generators () -> typing.List[typing.Dict[str, typing.Any]]:

	"""Describe every generator Subsequence offers, as plain data.

	The whole catalogue in one call, so a caller never has to hold its own list
	of what exists.  Each entry is exactly what :func:`describe_generator`
	returns for that name.

	Example:
		```python
		import subsequence

		for shape in subsequence.generators():
			print(shape["name"], len(shape["parameters"]))
		```
	"""

	return [describe_generator(name) for name in GENERATORS]


def transforms () -> typing.List[typing.Dict[str, typing.Any]]:

	"""Describe every transform Subsequence offers, as plain data.

	The companion to :func:`generators`: those *place* notes, these *reshape*
	notes already placed.  A surface that wants to roll a rhythm off the
	downbeat asks here rather than holding its own list of method names.

	Example:
		```python
		import subsequence

		for shape in subsequence.transforms():
			print(shape["name"], len(shape["parameters"]))
		```
	"""

	return [_describe(name) for name in TRANSFORMS]
