"""Tests for the annotation vocabulary and its load-bearing bounds.

A Span that nothing consults could drift out of step with the code exactly as a
docstring can, so the generators clamp to their own declared bounds.  Clamping
rather than raising is deliberate: a rebuild runs every bar and a failing one
costs its pattern that cycle, so validation would silence a part mid-performance
every time a control overshot.
"""

import logging
import typing

import pytest

import subsequence.declarations
import subsequence.pattern
import subsequence.pattern_builder


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	"""A PatternBuilder over a bare 4-beat pattern (no MIDI required)."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)

	return subsequence.pattern_builder.PatternBuilder(pattern, cycle=0)


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

def test_span_clamps_both_ends_and_passes_the_middle () -> None:

	"""Values inside the span come back untouched; outside ones are pinned."""

	span = subsequence.declarations.Span(0.0, 1.0)

	assert span.clamp(0.5) == 0.5
	assert span.clamp(1.5) == 1.0
	assert span.clamp(-0.5) == 0.0
	assert span.clamp(0.0) == 0.0
	assert span.clamp(1.0) == 1.0


# ---------------------------------------------------------------------------
# The vocabularies
# ---------------------------------------------------------------------------

def test_thin_strategy_is_the_bias_vocabulary_plus_strength () -> None:

	"""ThinStrategy is spelled flat, so a test has to keep it in step with BiasCurve.

	thin() reuses build_ghost_bias()'s curves and adds "strength", which is
	thin-only — a weakest-first hierarchy with no ghost_fill equivalent.  The
	alias is written out in full so the catalogue can read its options without
	unwrapping a nested Union, and this is what stops the two drifting apart.
	"""

	bias = set(typing.get_args(subsequence.declarations.BiasCurve))
	thin = set(typing.get_args(subsequence.declarations.ThinStrategy))

	assert thin == bias | {"strength"}


def test_arpeggio_and_strum_directions_are_deliberately_different () -> None:

	"""strum only reverses; arpeggio also ping-pongs and shuffles.

	One shared alias would let strum(direction="up_down") type-check, and strum
	has no such mode.
	"""

	arpeggio = set(typing.get_args(subsequence.declarations.ArpeggioDirection))
	strum = set(typing.get_args(subsequence.declarations.StrumDirection))

	assert strum == {"up", "down"}
	assert arpeggio == {"up", "down", "up_down", "random"}
	assert strum < arpeggio


def test_bias_vocabulary_matches_what_the_code_accepts () -> None:

	"""Every name in BiasCurve is one build_ghost_bias() actually implements.

	The alias is only worth having if it agrees with the branch that consumes
	it; a name here that the code rejects would be a lie mypy enforced.
	"""

	builder = _builder()

	for name in typing.get_args(subsequence.declarations.BiasCurve):
		weights = builder.build_ghost_bias(16, name)
		assert len(weights) == 16


# ---------------------------------------------------------------------------
# The bounds, enforced
# ---------------------------------------------------------------------------

def test_density_above_its_span_is_clamped_not_rejected () -> None:

	"""density=1.5 behaves as 1.0 rather than raising.

	Raising would cost the pattern its cycle on every rebuild — silence, mid
	performance, for a control nudged past its end.
	"""

	over = _builder().ghost_fill(60, density=1.5)
	full = _builder().ghost_fill(60, density=1.0)

	assert len(over._pattern.steps) == len(full._pattern.steps)


def test_density_below_its_span_is_clamped_to_zero () -> None:

	"""A negative density places nothing, exactly as 0.0 does."""

	under = _builder().ghost_fill(60, density=-0.5)

	assert len(under._pattern.steps) == 0


def test_a_clamped_value_is_warned_about_once () -> None:

	"""The overshoot is logged, and not on every subsequent rebuild.

	A pattern rebuilds every bar, so warning per call would fill the log for as
	long as a control sat past its bound.  The first one is the useful one.
	"""

	subsequence.declarations._warned.clear()
	logger = logging.getLogger("subsequence.declarations")

	with _capture(logger) as records:
		_builder().ghost_fill(60, density=1.5)
		_builder().ghost_fill(60, density=2.5)
		_builder().ghost_fill(60, density=9.0)

	assert len(records) == 1
	assert "density" in records[0]


def test_clamping_a_positional_argument_works_too () -> None:

	"""The bound applies whether the value arrives positionally or by keyword."""

	positional = _builder().ghost_fill(60, 1.5)
	keyword = _builder().ghost_fill(60, density=1.0)

	assert len(positional._pattern.steps) == len(keyword._pattern.steps)


def test_values_inside_the_span_are_untouched () -> None:

	"""The common case changes nothing and warns about nothing."""

	subsequence.declarations._warned.clear()
	logger = logging.getLogger("subsequence.declarations")

	with _capture(logger) as records:
		result = _builder().euclidean(60, 4, probability=1.0)

	assert records == []
	assert len(result._pattern.steps) == 4


def test_ratchet_velocity_multipliers_allow_up_to_two () -> None:

	"""velocity_start/end are 0.0-2.0, not 0.0-1.0 — the docstring says so.

	Pinned because it is the bound most easily assumed wrong: every other
	float here is a unit interval, and clamping these at 1.0 would silently
	remove the accent half of a crescendo roll.
	"""

	hints = typing.get_type_hints(
		subsequence.pattern_builder.PatternBuilder.ratchet, include_extras=True,
	)

	for name in ("velocity_start", "velocity_end"):
		spans = [m for m in hints[name].__metadata__ if isinstance(m, subsequence.declarations.Span)]
		assert spans and (spans[0].low, spans[0].high) == (0.0, 2.0)

	assert [
		m for m in hints["gate"].__metadata__
		if isinstance(m, subsequence.declarations.Span)
	][0].high == 1.0


# ---------------------------------------------------------------------------
# The decorator's own signature
# ---------------------------------------------------------------------------

def test_bounded_hands_back_the_signature_it_was_given () -> None:

	"""``bounded`` must be typed as an identity, or it erases what it decorates.

	Declared ``(fn: typing.Callable) -> typing.Callable`` it type-checked fine
	and silently threw the signature away: a bare ``Callable`` has no
	parameters and no return type, so mypy stopped checking anything passed to
	the fourteen decorated generators — including the very ``Literal``
	vocabularies this module exists to enforce, and including whether the call
	returned a builder at all (#2156).

	Nothing at run time notices, because ``functools.wraps`` keeps
	``inspect.signature`` honest either way.  The annotation on ``bounded``
	itself is the only place the mistake is visible from in here, so this is
	the guard.
	"""

	hints = typing.get_type_hints(subsequence.declarations.bounded)

	assert isinstance(hints["fn"], typing.TypeVar)
	assert hints["return"] is hints["fn"]


def test_a_decorated_generator_still_reports_its_parameters () -> None:

	"""The wrapper must not hide the vocabulary a caller is being held to.

	``functools.wraps`` is what makes this true, and it is worth pinning
	beside the annotation test: the catalogue reads these hints, so losing
	them would empty a generator's controls as surely as the erasure emptied
	its type checking.
	"""

	hints = typing.get_type_hints(
		subsequence.pattern_builder.PatternBuilder.ghost_fill, include_extras=True,
	)

	# bias is Union[BiasCurve, List[float]] — an explicit weight list is the
	# other way to ask for one, so the vocabulary is an arm rather than the
	# whole annotation.
	curves = next(
		arm for arm in typing.get_args(hints["bias"])
		if typing.get_origin(arm) is typing.Literal
	)

	assert typing.get_args(curves) == typing.get_args(subsequence.declarations.BiasCurve)


# ---------------------------------------------------------------------------

class _capture:

	"""Collect warning-level messages from *logger* for the duration of a block."""

	def __init__ (self, logger: logging.Logger) -> None:

		self.logger = logger
		self.records: typing.List[str] = []


	def __enter__ (self) -> typing.List[str]:

		outer = self

		class _Handler (logging.Handler):

			def emit (self, record: logging.LogRecord) -> None:

				if record.levelno >= logging.WARNING:
					outer.records.append(record.getMessage())

		self.handler = _Handler()
		self.logger.addHandler(self.handler)
		self.previous = self.logger.level
		self.logger.setLevel(logging.WARNING)

		return self.records


	def __exit__ (self, *exc: typing.Any) -> None:

		self.logger.removeHandler(self.handler)
		self.logger.setLevel(self.previous)
