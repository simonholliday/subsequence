"""The top-level ``Composition`` - the object a whole piece is built on.

``Composition`` is the single entry point: it owns the clock, the patterns,
the harmony and form state, and the MIDI output.  You create one, decorate
pattern functions onto it with ``@composition.pattern``, and call ``play()``.
``HarmonyView`` and ``ScheduleContext`` here are the read-only views handed to
pattern and callback functions at run time.
"""

import asyncio
import builtins
import dataclasses
import inspect
import logging
import math
import os
import pathlib
import random
import re
import signal
import types
import typing
import zlib
import subsequence.cadences
import subsequence.chord_graphs
import subsequence.chords
import subsequence.constants
import subsequence.constants.durations
import subsequence.constants.pulses
import subsequence.constants.velocity
import subsequence.display
import subsequence.harmonic_state
import subsequence.held_notes
import subsequence.keystroke
import subsequence.live_reloader
import subsequence.live_server
import subsequence.metre
import subsequence.midi_utils
import subsequence.osc
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.progressions
import subsequence.sequence_utils
import subsequence.sequencer
import subsequence.voicings
import subsequence.weighted_graph
import subsequence.conductor
import subsequence.form_state
import subsequence.forms
import subsequence.link_clock


logger = logging.getLogger(__name__)


# Above this whole-rig latency (ms), delay compensation is delaying every
# faster device enough that live-input feel may suffer — worth a warning.
_LATENCY_WARN_THRESHOLD_MS = 30.0


# ---------------------------------------------------------------------------
# Hotkey support — dataclasses and label derivation
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class HotkeyBinding:

	"""A registered keyboard shortcut and its associated action.

	Attributes:
		key: The single character that triggers this binding.
		action: Zero-argument callable executed when the key fires.
		quantize: ``0`` = execute immediately; ``N`` = execute on the
			next global bar divisible by *N*.
		label: Human-readable description shown by the ``?`` help key.
	"""

	key:      str
	action:   typing.Callable[[], None]
	quantize: int
	label:    str


@dataclasses.dataclass
class _PendingHotkeyAction:

	"""An action that has been triggered but is waiting for its ``quantize`` boundary."""

	binding: HotkeyBinding


_HOTKEY_RESERVED = "?"
"""Key reserved for listing all active hotkeys."""


def _derive_label (action: typing.Callable[[], None]) -> str:

	"""Auto-derive a display label for *action*.

	Tried in order:

	1. **Named function** - returns ``fn.__name__``.
	2. **Lambda in a ``.py`` file** - uses :func:`inspect.getsource` to extract
	   the lambda body from the source line (works for compositions defined in
	   files; falls back gracefully in REPLs and ``exec()`` contexts).
	3. **Fallback** - returns ``"<action>"``.

	Args:
		action: The callable registered as a hotkey action.

	Returns:
		A short, readable string suitable for the ``?`` help listing.
	"""

	name: typing.Optional[str] = getattr(action, "__name__", None)
	if name and name != "<lambda>":
		return name

	# Lambda — try to extract the body from the source line.
	try:
		source = inspect.getsource(action).strip()
		match = re.search(r"lambda\b[^:]*:\s*(.+)", source)
		if match:
			body = match.group(1).strip()
			# Strip trailing kwargs that belong to the outer hotkey() call.
			body = re.sub(r"[,\s]*(quantize|label)\s*=.*", "", body)
			body = body.rstrip(" ,)")
			if body:
				return body
	except (OSError, TypeError):
		pass

	return "<action>"


# Methods a Composition used to have, and what replaced them.  An AttributeError
# that names only the method leaves an upgrading piece guessing, as a bare
# TypeError would have for harmony(gravity=) (#3530).
_RETIRED_METHODS: typing.Dict[str, str] = {
	"web_ui": (
		"composition.web_ui() was retired in 0.7.0, with the browser dashboard it served. "
		"composition.display() shows the playing state in the terminal (display(grid=True) "
		"adds the pattern grid), and Superconductor, a touchscreen control surface for "
		"Subsequence, is at https://github.com/simonholliday/superconductor."
	),
}


class _Keep:

	"""Sentinel for a ``harmony()`` argument that was not given.

	``None`` cannot serve: ``cycle_beats=None`` already means "a chord a bar",
	and ``progression=None`` is how a bound progression is unbound.  So "keep
	what is configured" needs a value of its own.
	"""

	def __repr__ (self) -> str:
		return "<keep>"


KEEP: typing.Any = _Keep()


def _fn_has_parameter (fn: typing.Callable, name: str) -> bool:

	"""Check whether a callable accepts a parameter with the given name."""

	return name in inspect.signature(fn).parameters


def _fn_requires_parameter (fn: typing.Callable, name: str) -> bool:

	"""Check whether a callable takes a parameter with the given name and gives it no default."""

	parameter = inspect.signature(fn).parameters.get(name)

	return parameter is not None and parameter.default is inspect.Parameter.empty


@dataclasses.dataclass
class ScheduleContext:

	"""
	Context object passed to ``composition.schedule()`` callbacks
	whose signature declares a first parameter (conventionally named ``p``).

	Attributes:
		cycle: How many times this callback has been called so far (0-indexed).
			   0 on the first call, including the blocking ``wait_for_initial`` run.
	"""

	cycle: int


@dataclasses.dataclass
class _AdditionalOutput:

	"""A MIDI output device registered via ``composition.midi_output()``.

	Attributes:
		device: The exact MIDI output port name.
		alias: Optional friendly name for device-id lookups.
		latency_ms: Physical output latency in milliseconds for delay
			compensation (0.0 = no compensation).
	"""

	device: str
	alias: typing.Optional[str] = None
	latency_ms: float = 0.0


# The one progression type (subsequence/progressions.py) — re-exported here
# because freeze() returns it and the clock walks it.  The old engine-side
# Progression dataclass (chords + trailing_history) is absorbed into it.
Progression = subsequence.progressions.Progression


class _InjectedChord:

	"""
	Wraps a Chord with key context so tones() transposes correctly.
	"""

	def __init__ (
		self,
		chord: typing.Any,
		voice_leading_state: typing.Optional[subsequence.voicings.VoiceLeadingState] = None,
		next_chord: typing.Optional[typing.Any] = None,
		beats_remaining: typing.Optional[float] = None,
	) -> None:

		"""
		Store the chord, optional voice leading state, and the harmony
		window's anticipation data (the chord after this one and the beats
		until it arrives), when known.
		"""

		self._chord = chord
		self._voice_leading_state = voice_leading_state
		self._next_chord = next_chord
		self._beats_remaining = beats_remaining

	@property
	def next (self) -> typing.Optional["_InjectedChord"]:

		"""The chord after the current one - planned and revocable.

		Sugar over the harmony window (``p.harmony.next_chord``), so
		two-parameter builders get anticipation without learning a new
		object.  ``None`` when the window has no committed next chord.
		Voice leading is not applied (the voicing belongs to the chord
		that is actually sounding).
		"""

		if self._next_chord is None:
			return None

		return _InjectedChord(self._next_chord)

	@property
	def beats_remaining (self) -> typing.Optional[float]:

		"""Beats until the next chord boundary (from this cycle's start), when known."""

		return self._beats_remaining

	def root_midi (self, base: int) -> int:

		"""
		Return the MIDI note for this chord's root that is closest to ``base``.
		"""

		root_note = getattr(self._chord, "root_note", None)

		if root_note is None:
			# A PitchSet has no root and no quality — a cluster or a spectral
			# stack — so its lowest pitch is what a root-seeking caller gets.
			# Its register was chosen with its pitches (#3007).
			return int(min(self._chord.tones(base)))

		# Delegate to the chord's own root_note() rather than reimplementing
		# the pitch-class offset arithmetic.
		return int(root_note(base))

	def tones (self, root: int, inversion: int = 0, count: typing.Optional[int] = None) -> typing.List[int]:

		"""Return the chord's MIDI notes, as the chord itself voices them.

		The wrapped chord does the voicing, so a span's decoration arrives
		intact: its extensions, inversion, spread and slash bass (#3007).
		Rebuilding the voicing here from intervals and a root played a plain
		triad under a name that said ``C/G``.

		When voice leading is active, the smoothest rotation of that voicing
		is chosen automatically and the ``inversion`` parameter is ignored.
		Every voice is led, the slash bass among them, so it may move inward
		rather than staying the lowest note.  A PitchSet is left where it is:
		its pitches are absolute, and its register was chosen with them.

		When ``count`` is set, the voicing cycles into higher octaves until
		``count`` notes are produced.
		"""

		underlying = getattr(self._chord, "base", self._chord)

		if self._voice_leading_state is not None and not isinstance(underlying, subsequence.progressions.PitchSet):

			# One voice per pitch class, lowest first.  A pedal on a chord
			# tone doubles it at the octave, and rotating a pool that holds
			# both a note and its octave lands two voices on one pitch.
			pool: typing.List[int] = []
			classes: typing.Set[int] = set()

			for pitch in sorted(self._chord.tones(root)):
				if pitch % 12 not in classes:
					classes.add(pitch % 12)
					pool.append(pitch)

			anchor = pool[0]
			base = self._voice_leading_state.next([pitch - anchor for pitch in pool], anchor)

			if count is not None:
				n = len(base)
				base_intervals = [p - base[0] for p in base]
				return [base[0] + base_intervals[i % n] + 12 * (i // n) for i in range(count)]

			return base

		return list(self._chord.tones(root, inversion = inversion, count = count))

	def root_note (self, root_midi: int) -> int:

		"""Return the MIDI note number for the chord root nearest to *root_midi*."""

		# Delegate to root_midi(), NOT tones(): under voice leading, tones()
		# returns the smoothest INVERSION (whose bass is often not the root)
		# and advances the voicing state — a read must do neither.
		return self.root_midi(root_midi)

	def bass_note (self, root_midi: int, octave_offset: int = -1) -> int:

		"""Return the chord's bass, shifted by a number of octaves.

		A span's slash bass is the bass - ``C/G`` gives G, not C - so a bass
		line over a mix of plain and slash chords follows the changes it is
		written under (#3007).  Without a root to shift, a PitchSet gives its
		lowest pitch.
		"""

		bass_note = getattr(self._chord, "bass_note", None)

		if bass_note is None:
			return int(min(self._chord.tones(root_midi))) + (12 * octave_offset)

		return int(bass_note(root_midi, octave_offset))

	def intervals (self) -> typing.List[int]:

		"""
		Forward to the underlying chord's intervals.
		"""

		return self._chord.intervals()  # type: ignore[no-any-return]

	def name (self) -> str:

		"""
		Forward to the underlying chord's name.
		"""

		return self._chord.name()  # type: ignore[no-any-return]


class _HarmonyHorizon:

	"""The published harmony window - realised chord spans on the absolute beat axis.

	The harmonic clock commits one span per chord boundary (decorated chords
	where the source span is spiced) and, where the future is data (a bound
	or section progression), installs a *future* lookup so ``chord_at`` can
	answer arbitrarily far ahead.  In live graph mode the window is
	``[current, next]`` - one pre-committed step - and queries beyond it
	clamp to the last known chord with a one-time warning.

	All beats are absolute (from playback start).  Read through
	:class:`HarmonyView` inside patterns, or :meth:`Composition.current_chord`
	for the chord sounding at the playhead.
	"""

	def __init__ (self) -> None:

		"""Start with an empty window."""

		self._spans: typing.List[typing.Tuple[float, float, typing.Any]] = []
		self._future: typing.Optional[typing.Callable[[float], typing.Optional[typing.Tuple[float, float, typing.Any]]]] = None
		self._planned: typing.Optional[typing.Tuple[float, float, typing.Any]] = None
		self._warned_beyond = False

	@property
	def is_empty (self) -> bool:

		"""True when nothing has been committed yet (no harmony configured)."""

		return not self._spans

	def reset (self) -> None:

		"""Clear everything (a fresh playback)."""

		self._spans = []
		self._future = None
		self._planned = None
		self._warned_beyond = False

	def commit (self, start: float, end: float, chord: typing.Any) -> None:

		"""Commit a realised span.  A commit at an earlier start truncates the tail."""

		while self._spans and self._spans[-1][0] >= start - 1e-9:
			self._spans.pop()

		if self._spans and self._spans[-1][1] > start:
			previous_start, _, previous_chord = self._spans[-1]
			self._spans[-1] = (previous_start, start, previous_chord)

		self._spans.append((start, end, chord))

		if self._planned is not None and self._planned[0] < end:
			self._planned = None

		# Keep a bounded history so long sessions don't grow without limit.
		while len(self._spans) > 64:
			self._spans.pop(0)

	def set_planned (self, start: float, end: float, chord: typing.Any) -> None:

		"""Publish the live engine's pre-committed next step."""

		self._planned = (start, end, chord)

	def set_future (self, fn: typing.Optional[typing.Callable[[float], typing.Optional[typing.Tuple[float, float, typing.Any]]]]) -> None:

		"""Install (or clear) the data-source lookup for beats beyond the committed spans."""

		self._future = fn

	def invalidate_future (self) -> None:

		"""Drop everything not yet sounding - the next clock fire recomputes it.

		Called on every supported intervention: a ``harmony()`` re-call,
		``form_jump``/``form_next``, a re-bind, a new pin.  ``next_chord``
		is planned and revocable; this is the revocation.
		"""

		self._future = None
		self._planned = None

	def span_at (self, beat: float) -> typing.Optional[typing.Tuple[float, float, typing.Any]]:

		"""The realised ``(start, end, chord)`` covering *beat*, or None if unknown."""

		for start, end, chord in reversed(self._spans):
			if start - 1e-9 <= beat < end - 1e-9:
				return (start, end, chord)

		if self._spans and beat >= self._spans[-1][1] - 1e-9:

			if self._future is not None:
				found = self._future(beat)
				if found is not None:
					return found

			if self._planned is not None and self._planned[0] - 1e-9 <= beat < self._planned[1] - 1e-9:
				return self._planned

		return None

	def chord_at (self, beat: float) -> typing.Optional[typing.Any]:

		"""The chord sounding at *beat* - clamping to the last known chord beyond the window."""

		span = self.span_at(beat)

		if span is not None:
			return span[2]

		if not self._spans:
			return None

		if beat < self._spans[0][0]:
			return self._spans[0][2]

		if not self._warned_beyond:
			self._warned_beyond = True
			logger.warning(
				"chord_at(%.2f) is beyond the harmony window - clamping to the last known chord. "
				"In live graph mode only [current, next] is committed; bind a progression for a data future.",
				beat,
			)

		if self._planned is not None and beat >= self._planned[1] - 1e-9:
			return self._planned[2]

		return self._spans[-1][2]

	def boundary_after (self, beat: float) -> typing.Optional[float]:

		"""The absolute beat of the next chord boundary after *beat*, when known."""

		span = self.span_at(beat)

		return None if span is None else span[1]

	def next_chord_after (self, beat: float) -> typing.Optional[typing.Any]:

		"""The chord that follows the one sounding at *beat* - None when unknown (no clamping)."""

		boundary = self.boundary_after(beat)

		if boundary is None:
			return None

		following = self.span_at(boundary)

		return None if following is None else following[2]

	def latest_chord (self) -> typing.Optional[typing.Any]:

		"""The most recently committed chord (compatibility accessor)."""

		return self._spans[-1][2] if self._spans else None


class HarmonyView:

	"""Read-only harmony context for one pattern cycle (``p.harmony``).

	Anchored at the cycle's start beat, so all beat arguments are
	cycle-relative - ``chord_at(0)`` is the chord at the cycle's first beat
	(what the two-parameter ``chord`` convention injects), ``chord_at(3.5)``
	the chord sounding under beat 3.5 of this cycle.

	Under bound/frozen progressions the future is data and any beat
	answers; in live graph mode the window is the current chord plus one
	pre-committed step, and ``next_chord`` is *planned and revocable*.
	"""

	def __init__ (self, horizon: _HarmonyHorizon, origin_beat: float) -> None:

		"""Anchor the view at a cycle-start beat."""

		self._horizon = horizon
		self._origin = origin_beat

	@property
	def chord (self) -> typing.Optional[typing.Any]:

		"""The chord at this cycle's start (the cycle-start snapshot)."""

		return self._horizon.chord_at(self._origin)

	def chord_at (self, beat: float) -> typing.Optional[typing.Any]:

		"""The chord sounding at *beat* of THIS cycle (0-based beats)."""

		return self._horizon.chord_at(self._origin + beat)

	@property
	def next_chord (self) -> typing.Optional[typing.Any]:

		"""The chord after the current one - for anticipation and approach tones."""

		return self._horizon.next_chord_after(self._origin)

	def next_chord_at (self, beat: float) -> typing.Optional[typing.Any]:

		"""The chord following the one sounding at *beat* of THIS cycle, when known."""

		return self._horizon.next_chord_after(self._origin + beat)

	@property
	def until_change (self) -> typing.Optional[float]:

		"""Beats from the cycle start until the next chord boundary, when known."""

		boundary = self._horizon.boundary_after(self._origin)

		return None if boundary is None else boundary - self._origin


def _span_chord (span: subsequence.progressions.ChordSpan) -> typing.Any:

	"""The chord a span presents to patterns - decorated where spiced, bare otherwise."""

	if span.is_decorated:
		return subsequence.progressions.DecoratedChord(span)

	return span.chord


def _bare_chord (chord_like: typing.Any) -> typing.Any:

	"""The engine-currency chord under a possibly-decorated chord."""

	if isinstance(chord_like, subsequence.progressions.DecoratedChord):
		return chord_like.base

	return chord_like


async def schedule_harmonic_clock (
	sequencer: subsequence.sequencer.Sequencer,
	get_harmonic_state: typing.Callable[[], typing.Optional[subsequence.harmonic_state.HarmonicState]],
	horizon: typing.Optional[_HarmonyHorizon] = None,
	bar_beats: typing.Optional[float] = None,
	cycle_beats: typing.Optional[float] = None,
	get_cycle_beats: typing.Optional[typing.Callable[[], float]] = None,
	get_bound_progression: typing.Optional[typing.Callable[[], typing.Optional["Progression"]]] = None,
	get_section_progression: typing.Optional[
		typing.Callable[[], typing.Optional[typing.Tuple[str, typing.Any, int, typing.Optional["Progression"]]]]
	] = None,
	get_section_progression_at: typing.Optional[
		typing.Callable[[int], typing.Optional["Progression"]]
	] = None,
	get_following_section_progression: typing.Optional[
		typing.Callable[[typing.Any], typing.Optional["Progression"]]
	] = None,
	get_pinned: typing.Optional[typing.Callable[[int], typing.Optional[typing.Any]]] = None,
	cadence_requests: typing.Optional[typing.Dict[int, str]] = None,
	resolve_cadence: typing.Optional[typing.Callable[[str], typing.List[subsequence.chords.Chord]]] = None,
	get_section_cadence: typing.Optional[typing.Callable[[str], typing.Optional[str]]] = None,
	reschedule_lookahead: float = 1,
	start_beat: float = 0.0,
	on_stop: typing.Optional[typing.Callable[[], None]] = None,
	register_rewind: typing.Optional[typing.Callable[[typing.Callable[[], None]], None]] = None,
) -> None:

	"""Schedule the harmonic clock - a span walker over the bound harmony sources.

	Generalises the old fixed-cycle clock: chords last as long as their
	spans say, the clock fires at ``min(next span boundary, next bar
	boundary)`` (so section bookkeeping stays bar-aligned under variable
	harmonic rhythm), and every realised span is published to *horizon*
	(the harmony window patterns read through ``p.harmony``).

	Priority chain per chord boundary: **section progression >
	composition-bound progression > live ``step()``**.  A bound progression
	loops on exhaustion when no live engine is configured (or when it
	contains a :class:`~subsequence.progressions.PitchSet`); with a live
	engine, exhaustion falls through to live stepping - the frozen-replay
	bridge.  In live mode the engine pre-commits one step so the window
	always holds ``[current, next]``.

	``get_harmonic_state``, ``get_bound_progression``, and ``get_pinned``
	are evaluated on every tick so mid-playback calls to ``harmony()``,
	re-binds, and new pins take effect immediately.  ``get_section_progression``
	returns ``(name, entry, bars, Progression|None)`` for the current section
	or ``None`` when no form is active.  *entry* is any value that differs
	between one entry and the next - it is only ever compared for inequality -
	so verse→verse re-entry resets, and so does a mid-playback ``form()``
	re-bind, where one form's section 0 would otherwise look like another's
	(#3084).  ``get_section_progression_at``
	answers the same question for the section owning a 1-based global bar, and
	is what lets the window see one chord past a section's edge (#3086).  It
	returns ``None`` for graph and generator forms, which have no layout ahead
	of the playhead; for those, ``get_following_section_progression`` takes the
	entry of the section whose edge it is and answers with the section the form
	has picked to follow it, the one ``p.section.next_section`` names, for as
	long as the form is still in that section (#3526).

	``cadence_requests`` is the request-hook seam: a mutable ``{bar: name}``
	dict (shared with ``Composition.request_cadence``) the live walk steers
	toward - at the first boundary with a pending request, the remaining
	changes up to its bar are planned as a constrained walk pinned to the
	cadence formula (resolved by ``resolve_cadence``) and then committed
	one boundary at a time.  ``get_section_cadence`` turns a section entry
	into a request arriving at that section's final bar (live sections
	only).  Requests whose bar passes unserved expire with a warning.

	The clock fires ``reschedule_lookahead`` beats before each boundary -
	raised by the caller to the maximum pattern lookahead, so the window
	always covers a pattern's next cycle before it rebuilds.

	``horizon`` may be omitted for direct use without a :class:`Composition`
	(a private window is created - ``p.harmony`` inside a Composition needs
	the composition's own horizon).  ``get_cycle_beats``, when given, is
	re-read at every boundary so a mid-playback ``harmony(cycle_beats=…)``
	re-call takes effect like the other getter-based parameters; the plain
	``cycle_beats`` value is the fixed fallback.  ``bar_beats`` defaults to
	the sequencer's bar, and ``cycle_beats`` to ``bar_beats``: a chord a bar.
	"""

	if horizon is None:
		horizon = _HarmonyHorizon()

	if bar_beats is None:
		bar_beats = subsequence.metre.bar_beats(sequencer.time_signature)

	if cycle_beats is None:
		cycle_beats = bar_beats

	def _cycle_beats_now () -> float:
		return float(get_cycle_beats() if get_cycle_beats is not None else cycle_beats)

	pulses_per_beat = sequencer.pulses_per_beat

	state: typing.Dict[str, typing.Any] = {
		"next_change": start_beat,	# absolute beat of the next chord boundary
		"last_section_index": None,
		"section_anchor": start_beat,	# beat the current section entered
		"section_end": None,		# beat the current section ends (None = unbounded)
		"section_exhausted": False,
		"bound_anchor": start_beat,	# beat the bound progression was first walked from
		"bound_seen": None,			# identity of the bound progression last walked
		"bound_exhausted": False,
		"planned": None,			# the live engine's pre-committed next chord
		"engine_seen": None,		# identity of the engine "planned" was drawn from
		"last_chord": None,			# what is sounding, to hold when no source applies
		"held_once": False,			# the hold is said once, not every bar
		"cadence_queue": [],		# planned approach chords (None = step live at that boundary)
		"cadence_target": None,		# (bar, name) the queued approach is walking toward
	}

	def _plan_cadence_request (beat: float, hs: subsequence.harmonic_state.HarmonicState) -> None:

		"""Compile the nearest pending cadence request into the approach queue.

		A live freeze-ahead: a constrained walk from the engine's current
		chord to the request's bar, pinned to the cadence formula at the
		tail, drawn through the engine's real weights on the play stream.
		The engine's state is snapshot-restored - chords commit one by one
		as their boundaries actually sound.  An unwalkable formula falls
		back to fiat (live steps up to the approach, the formula committed
		at its bars), loudly.
		"""

		if not cadence_requests or resolve_cadence is None:
			return

		cb = _cycle_beats_now()
		target_bar = min(cadence_requests)
		target_beat = (target_bar - 1) * bar_beats

		if target_beat < beat - 1e-9:
			return		# stale; the expiry pass warns and drops it

		name = cadence_requests.pop(target_bar)

		try:
			formula = resolve_cadence(name)
		except (ValueError, TypeError) as error:
			logger.warning(f"cadence request {name!r} at bar {target_bar} cannot resolve: {error}")
			return

		remaining = (target_beat - beat) / cb
		steps = int(remaining + 1e-9) + 1		# chord changes from here to the arrival, inclusive

		if abs(remaining - round(remaining)) > 1e-9:
			logger.warning(
				f"cadence request {name!r}: bar {target_bar} does not land on a chord "
				f"boundary ({cb:g}-beat cycles) - the arrival sounds at the boundary before it"
			)

		tail = list(formula[-steps:])

		if steps < len(formula):
			logger.warning(
				f"cadence request {name!r} at bar {target_bar}: only {steps} chord change(s) "
				f"before the arrival - approaching with the formula's tail alone"
			)

		length = steps + 1		# walk position 1 is the chord sounding now
		pins = {length - len(tail) + 1 + index: chord for index, chord in enumerate(tail)}

		saved_history = list(hs.history)
		saved_current = hs.current_chord

		def _commit (chosen: subsequence.chords.Chord) -> None:
			hs.current_chord = chosen

		try:
			walked = subsequence.sequence_utils.constrained_walk(
				hs.graph,
				hs.current_chord,
				length,
				rng = hs.rng,
				pins = pins,
				weight_modifier = hs._transition_weight,
				before_choice = hs._record_transition_source,
				after_choice = _commit,
			)
		except ValueError as error:
			logger.warning(
				f"cadence request {name!r} at bar {target_bar} is not walkable from "
				f"{saved_current.name()} ({error}) - the arrival lands by fiat"
			)
			state["cadence_queue"] = [None] * (steps - len(tail)) + tail
			state["cadence_target"] = (target_bar, name)
			return
		finally:
			hs.history = saved_history
			hs.current_chord = saved_current

		state["cadence_queue"] = list(walked[1:])
		state["cadence_target"] = (target_bar, name)

	def _data_future (
		progression: "Progression",
		anchor: float,
		loops: bool,
	) -> typing.Callable[[float], typing.Optional[typing.Tuple[float, float, typing.Any]]]:

		"""A horizon future fn computing spans arithmetically from a data source."""

		def future (beat: float) -> typing.Optional[typing.Tuple[float, float, typing.Any]]:

			offset = beat - anchor

			if offset < -1e-9:
				return None

			if not loops and offset >= progression.length - 1e-9:
				return None

			span, span_start, span_end = progression.span_at(offset)
			cycle_base = anchor + (offset // progression.length) * progression.length
			start = cycle_base + span_start
			end = cycle_base + span_end

			chord = _span_chord(span)

			if get_pinned is not None:
				pinned = get_pinned(int(start // bar_beats) + 1)
				if pinned is not None:
					chord = pinned

			return (start, end, chord)

		return future

	def _section_future (
		progression: "Progression",
		anchor: float,
		loops: bool,
		section_end: typing.Optional[float],
		entry: typing.Any = None,
	) -> typing.Callable[[float], typing.Optional[typing.Tuple[float, float, typing.Any]]]:

		"""A section's spans, stopping at the section's own edge (#3086).

		``_data_future`` alone wraps a short progression inside its own length
		for ever.  That is right INSIDE a section - a two-chord progression in
		a four-bar section repeats - and wrong AT its end, where the chord that
		follows is the next section's first, not a wrap back to this one's.
		Unbounded, the window's ``next_chord`` said C at the verse's last bar
		where Am, the chorus's first chord, actually followed.

		Past the edge this reports the next section's FIRST span and nothing
		further: that is what anticipation needs, and it is the most the clock
		can honestly claim.  Where nothing follows (the end of a finite form) or
		the next section plays live chords, it reports ``None`` - the caller then
		says "not known" rather than something false.  A graph or generator form
		has no layout to look the next section up in, but it has picked it: past
		the edge of the section entered as *entry*, the window reads that pick,
		as ``p.section.next_section`` does.  It used to report ``None`` there, and
		a part anticipating the next chord went silent at every edge (#3526).
		"""

		inner = _data_future(progression, anchor, loops)

		def future (beat: float) -> typing.Optional[typing.Tuple[float, float, typing.Any]]:

			if section_end is None:
				return inner(beat)

			if beat >= section_end - 1e-9:

				following = (
					get_section_progression_at(int(section_end // bar_beats) + 1)
					if get_section_progression_at is not None else None
				)

				if following is None and get_following_section_progression is not None:
					following = get_following_section_progression(entry)

				if following is None:
					return None

				span, span_start, span_end = following.span_at(0.0)
				start = section_end + span_start
				end = section_end + span_end

				if not (start - 1e-9 <= beat < end - 1e-9):
					return None		# further than its first chord: not claimed

				chord = _span_chord(span)

				if get_pinned is not None:
					pinned = get_pinned(int(start // bar_beats) + 1)
					if pinned is not None:
						chord = pinned

				return (start, end, chord)

			span_here = inner(beat)

			if span_here is None:
				return None

			start, end, chord = span_here

			return (start, min(end, section_end), chord)

		return future

	def advance (beat: float) -> typing.Optional[float]:

		"""Prepare the boundary at *beat*; return beats to the next fire (or None to stop)."""

		hs = get_harmonic_state()
		initial = beat == start_beat and horizon.is_empty

		# A mid-song style switch replaces the engine.  A chord the old one had
		# already drawn is not the new style's to play — it came out of a graph
		# that is gone, and it outlived the switch (#2992).
		if hs is not state["engine_seen"]:
			state["engine_seen"] = hs
			state["planned"] = None

		# --- Section bookkeeping (every fire is bar-aligned or a span boundary,
		# and the form clock fired first at this pulse, so the info is current).
		section_progression: typing.Optional["Progression"] = None

		if get_section_progression is not None:
			info = get_section_progression()
			if info is not None:
				_section_name, section_index, section_bars, section_progression = info

				if section_index != state["last_section_index"]:
					state["last_section_index"] = section_index
					state["section_anchor"] = beat
					state["section_end"] = (
						beat + section_bars * bar_beats if section_bars > 0 else None
					)
					state["section_exhausted"] = False
					state["next_change"] = beat		# a section entry forces a chord decision
					horizon.invalidate_future()
					state["planned"] = None

					# A planned cadence approach belongs to the section it was
					# walked in: it starts from the chord sounding then and
					# counts boundaries to a bar.  A section change — a
					# form_jump especially — invalidates both, so the approach
					# is discarded rather than replayed here (#3085).  Where
					# its arrival is still ahead, the REQUEST goes back so it
					# re-plans from where the harmony now stands; the musician
					# asked for a cadence at a bar, not for these chords.
					if state["cadence_queue"]:
						stale_target = state["cadence_target"]
						state["cadence_queue"] = []
						state["cadence_target"] = None

						if stale_target is not None and cadence_requests is not None:
							stale_bar, stale_name = stale_target
							if (stale_bar - 1) * bar_beats > beat + 1e-9:
								cadence_requests.setdefault(stale_bar, stale_name)

					# Restore the NIR context that was current when this
					# progression was frozen, so every replay starts alike.
					if section_progression is not None and section_progression.trailing_history and hs is not None:
						hs.history = list(section_progression.trailing_history)

					# A registered section cadence becomes a bar request: the
					# arrival lands on this section's final bar.  Live sections
					# only — bound chords are data and cannot be steered.
					if (
						get_section_cadence is not None
						and cadence_requests is not None
						and section_progression is None
						and section_bars > 0
					):
						section_cadence_name = get_section_cadence(_section_name)
						if section_cadence_name is not None:
							entry_bar = int(beat // bar_beats) + 1
							cadence_requests.setdefault(entry_bar + section_bars - 1, section_cadence_name)

		# Cadence requests expire when their bar passes unserved — harmony was
		# data-bound the whole approach, or the request arrived too late.
		if cadence_requests:
			for expired_bar in [b for b in cadence_requests if (b - 1) * bar_beats < beat - 1e-9]:
				expired_name = cadence_requests.pop(expired_bar)
				logger.warning(
					f"cadence request {expired_name!r} at bar {expired_bar} expired unserved - "
					"the bar passed while harmony was data-bound, or the request arrived too late"
				)

		bound_progression = get_bound_progression() if get_bound_progression is not None else None

		if bound_progression is None:
			# Unbound (harmony(progression=None), #3088).  Forget what was
			# seen, or re-binding the SAME Progression object later would
			# match on identity and carry on from its old anchor.
			state["bound_seen"] = None

		elif state["bound_seen"] is not bound_progression:
			# First sighting (or a re-bind): anchor the walk here and forget exhaustion.
			state["bound_seen"] = bound_progression
			state["bound_anchor"] = beat
			state["bound_exhausted"] = False
			horizon.invalidate_future()

		chord_boundary = beat >= state["next_change"] - 1e-9

		if not chord_boundary and get_pinned is not None:

			# Fiat inside a longer span: a pinned bar forces its chord at the
			# bar line, overriding the sounding span until the next change.
			pinned_now = get_pinned(int(beat // bar_beats) + 1)

			if pinned_now is not None and horizon.chord_at(beat) is not pinned_now:

				bare_pin = _bare_chord(pinned_now)

				if hs is not None and isinstance(bare_pin, subsequence.chords.Chord):
					hs.commit_chord(bare_pin)

				horizon.commit(beat, state["next_change"], pinned_now)

		if chord_boundary:

			chord_like: typing.Optional[typing.Any] = None
			span_beats: typing.Optional[float] = None
			from_live = False

			# Priority 1: the current section's progression.
			if section_progression is not None and not state["section_exhausted"]:

				offset = beat - state["section_anchor"]
				loops = hs is None or section_progression.loops_on_exhaustion

				if offset >= section_progression.length - 1e-9 and not loops:
					state["section_exhausted"] = True	# fall through to live stepping
				else:
					span, span_start, span_end = section_progression.span_at(offset)
					chord_like = _span_chord(span)
					span_beats = span_end - (offset % section_progression.length)

					# A chord whose span outlasts its section must not carry
					# the boundary past the edge with it (#3086): the section
					# ends there whatever the harmonic rhythm says, and a
					# committed span running beyond it makes the window read
					# the wrong place.  Three bars of 4/4 walked by 8-beat
					# spans is the case — the second span runs 8 to 16 and the
					# section ends at 12.
					if state["section_end"] is not None:
						span_beats = min(span_beats, state["section_end"] - beat)

					horizon.set_future(_section_future(
						section_progression, state["section_anchor"], loops, state["section_end"],
						state["last_section_index"],
					))

			# Priority 2: the composition-bound progression.
			if chord_like is None and bound_progression is not None and not state["bound_exhausted"]:

				offset = beat - state["bound_anchor"]
				loops = hs is None or bound_progression.loops_on_exhaustion

				if offset >= bound_progression.length - 1e-9 and not loops:
					state["bound_exhausted"] = True	# the frozen-replay bridge: live from here
				else:
					span, span_start, span_end = bound_progression.span_at(offset)
					chord_like = _span_chord(span)
					span_beats = span_end - (offset % bound_progression.length)
					horizon.set_future(_data_future(bound_progression, state["bound_anchor"], loops))

			# Priority 3: live graph stepping.
			if chord_like is None:

				if hs is None:

					# A section with no chords of its own, in a piece that
					# never called harmony().  Hold what is sounding and keep
					# the clock running: returning None here dropped the
					# callback for good, so the bridge silenced every verse
					# after it too, and a later harmony() could not restart it
					# (#2998, decision 2 of #2991).
					if state["last_chord"] is None:
						return None		# nothing has ever sounded; there is no clock to keep

					if not state["held_once"]:
						state["held_once"] = True
						logger.info(
							"No chords for this part of the form and no harmony() to generate them - "
							"holding the last chord until a section that has some."
						)

					chord_like = state["last_chord"]
					span_beats = _cycle_beats_now()
					horizon.set_future(None)

				else:

					if initial:
						chord_like = hs.current_chord	# the tonic sounds first; no step at beat 0
					else:
						if not state["cadence_queue"]:
							_plan_cadence_request(beat, hs)

						queued: typing.Optional[typing.Any] = None

						if state["cadence_queue"]:
							queued = state["cadence_queue"].pop(0)

							if not state["cadence_queue"]:
								# The approach has arrived; it is no longer
								# walking toward anything (#3085).
								state["cadence_target"] = None

						if queued is not None:
							# A planned approach supersedes the pre-committed step.
							state["planned"] = None
							chord_like = queued
						else:
							if state["planned"] is None:
								state["planned"] = hs.plan_next()
							chord_like = state["planned"]
							state["planned"] = None

					span_beats = _cycle_beats_now()
					from_live = True
					horizon.set_future(None)

			# Pins are fiat — they override whatever the source produced.
			if get_pinned is not None:
				pinned = get_pinned(int(beat // bar_beats) + 1)
				if pinned is not None:
					chord_like = pinned

			assert span_beats is not None	# every branch above either set it or returned

			# Sync the engine so freeze()/NIR/live fall-through stay coherent.
			bare = _bare_chord(chord_like)

			if hs is not None and isinstance(bare, subsequence.chords.Chord):
				if initial:
					hs.current_chord = bare
				elif from_live or bare is not hs.current_chord:
					hs.commit_chord(bare)

			horizon.commit(beat, beat + span_beats, chord_like)
			state["next_change"] = beat + span_beats
			state["last_chord"] = chord_like

			# Live mode pre-commits one step so the window holds [current, next].
			# A planned cadence approach already knows its next chord — publish
			# it without drawing (a fiat gap, queue head None, plans normally).
			if from_live and hs is not None:
				if state["cadence_queue"] and state["cadence_queue"][0] is not None:
					horizon.set_planned(state["next_change"], state["next_change"] + _cycle_beats_now(), state["cadence_queue"][0])
				else:
					state["planned"] = hs.plan_next()
					horizon.set_planned(state["next_change"], state["next_change"] + _cycle_beats_now(), state["planned"])

		# Fire again at the earlier of the next chord change and the next bar
		# line — bar fires keep section bookkeeping aligned under long spans.
		next_bar = (beat // bar_beats) * bar_beats + bar_beats
		if next_bar <= beat + 1e-9:
			next_bar = beat + bar_beats

		next_fire = min(float(state["next_change"]), next_bar)

		return max(next_fire - beat, 1.0 / pulses_per_beat)

	def advance_pulse (boundary_pulse: int) -> typing.Optional[float]:

		"""The sequencer-facing callback: pulses in, beats out."""

		# Nothing to guard here: start_beat is always a chord boundary
		# (next_change starts there) and a boundary either declines to start at
		# all or commits a chord, so once the clock is running it has one to hold.
		return advance(boundary_pulse / pulses_per_beat)

	# Populate the window for start_beat synchronously, BEFORE patterns first
	# build, then schedule the walker from the first boundary it reported.
	first_interval = advance(start_beat)

	if first_interval is None:
		# No source, and nothing sounding to hold: this clock never starts.
		# Say so, or the Composition goes on believing it has one and a
		# harmony() arriving later registers nothing (#2998).
		if on_stop is not None:
			on_stop()
		return

	await sequencer.schedule_callback_sequence(
		callback = advance_pulse,
		start_pulse = subsequence.constants.pulses.beats_to_pulses(start_beat + first_interval, pulses_per_beat),
		reschedule_lookahead = reschedule_lookahead,
	)

	if register_rewind is not None:

		def _rewind () -> None:

			"""Put the walk back where it started - an external Start (#3089).

			The walk's whole position lives in this closure, so nothing outside
			can reset it: the anchors, what the engine last saw, the planned
			step and any cadence approach in flight all have to go back
			together, or the piece resumes its old harmony over its new bar 1.
			"""

			state.update({
				"next_change": start_beat,
				"last_section_index": None,
				"section_anchor": start_beat,
				"section_end": None,
				"section_exhausted": False,
				"bound_anchor": start_beat,
				"bound_seen": None,
				"bound_exhausted": False,
				"planned": None,
				"engine_seen": None,
				"last_chord": None,
				"held_once": False,
				"cadence_queue": [],
				"cadence_target": None,
			})

			horizon.reset()

			hs_now = get_harmonic_state()

			if hs_now is not None:
				hs_now.history = []
				hs_now.current_chord = hs_now.home_chord

			# Re-populate the window for the opening bar, exactly as the
			# registration above does.
			advance(start_beat)

		register_rewind(_rewind)


def _make_safe_callback (
	fn: typing.Callable,
	accepts_context: bool = False,
	start_cycle: int = 0,
	wait: typing.Optional[typing.Callable[[], bool]] = None,
) -> typing.Callable[[int], typing.Optional[typing.Awaitable[None]]]:

	"""Wrap a user function as a fire-and-forget callback that never blocks the clock.

	If *accepts_context* is True, ``fn`` is called with a :class:`ScheduleContext`
	whose ``cycle`` field increments on every invocation.

	When *wait* is given and returns True at a call, the wrapper hands the run
	back for the clock to await instead of spawning it.  A render passes one
	(#2793): its time is simulated, so nothing is lost by waiting, and a plain
	function feeding patterns from a thread otherwise raced the render and
	changed the file from run to run.
	"""

	is_async = inspect.iscoroutinefunction(fn)
	cycle_count: typing.List[int] = [start_cycle]  # mutable cell so the closure can mutate it

	async def _execute (cycle: int) -> None:

		"""Run the user function with error handling and optional threading."""

		ctx = ScheduleContext(cycle=cycle)

		try:

			if is_async:
				await (fn(ctx) if accepts_context else fn())

			else:
				loop = asyncio.get_running_loop()
				call = (lambda: fn(ctx)) if accepts_context else fn
				await loop.run_in_executor(None, call)

		except Exception as exc:
			logger.warning(f"Scheduled task {getattr(fn, '__name__', repr(fn))!r} failed: {exc}")

	def wrapper (pulse: int) -> typing.Optional[typing.Awaitable[None]]:

		"""Spawn the task in the background, or hand it to the clock to await when *wait* says so."""

		# Capture the cycle number synchronously before any async yield so that
		# even if multiple pulses fire before the event loop runs, each task
		# receives the correct cycle value it was triggered at.
		current_cycle = cycle_count[0]
		cycle_count[0] += 1

		if wait is not None and wait():
			return _execute(current_cycle)

		asyncio.create_task(_execute(current_cycle))
		return None

	return wrapper


async def schedule_task (
	sequencer: subsequence.sequencer.Sequencer,
	fn: typing.Callable,
	cycle_beats: int,
	reschedule_lookahead: int = 1,
	defer: bool = False
) -> None:

	"""Schedule a non-blocking repeating task on the sequencer's beat clock.

	If ``fn`` declares a first parameter named ``p``, it is called with a
	:class:`ScheduleContext` on every invocation (same behaviour as
	``composition.schedule()``).

	When *defer* is True the backshift fire at pulse 0 is skipped; the first
	call happens one full *cycle_beats* later.  Direct API users who need the
	equivalent of ``initial=True`` can simply ``await fn()`` themselves before
	calling this function.
	"""

	accepts_ctx = _fn_has_parameter(fn, "p")
	wrapped = _make_safe_callback(fn, accepts_context=accepts_ctx, wait=lambda: sequencer.render_mode)
	start_pulse = subsequence.constants.pulses.beats_to_pulses(cycle_beats, sequencer.pulses_per_beat) if defer else 0

	await sequencer.schedule_callback_repeating(
		callback = wrapped,
		interval_beats = cycle_beats,
		start_pulse = start_pulse,
		reschedule_lookahead = reschedule_lookahead
	)


async def schedule_form (
	sequencer: subsequence.sequencer.Sequencer,
	form_state: subsequence.form_state.FormState,
	reschedule_lookahead: float = 1,
	on_bar: typing.Optional[typing.Callable[[int, bool], None]] = None,
	get_form_state: typing.Optional[typing.Callable[[], typing.Optional[subsequence.form_state.FormState]]] = None,
	start_pulse: typing.Optional[int] = None,
) -> None:

	"""Schedule the form state to advance each bar.

	Emits a ``"section"`` event on the sequencer's emitter at play start
	and on every section change (one lookahead-beat early, like every form
	decision), carrying the new :class:`~subsequence.form_state.SectionInfo`
	(``None`` when the form finishes).  ``on_bar`` is the boundary hook -
	called once per bar with ``(boundary_pulse, section_changed)`` after the
	form advances; the transition machinery rides it.

	``get_form_state``, when given, is re-read every bar - so a mid-playback
	``form()`` re-bind advances the NEW form state from the next bar instead
	of silently driving the abandoned object forever.  ``form_state`` is the
	fixed fallback for direct use.
	"""

	lookahead_pulses = subsequence.constants.pulses.beats_to_pulses(reschedule_lookahead, sequencer.pulses_per_beat)

	def _current_form_state () -> typing.Optional[subsequence.form_state.FormState]:
		return get_form_state() if get_form_state is not None else form_state

	# Log and announce the initial section.
	initial_form = _current_form_state()
	initial_section = initial_form.get_section_info() if initial_form is not None else None
	if initial_section:
		logger.info(f"Form: {initial_section.name}")
	sequencer.events.emit_sync("section", initial_section)

	if on_bar is not None:
		on_bar(0, True)		# the first bar is a boundary too (a 1-bar opener can end)

	seen_form: typing.Dict[str, typing.Any] = {"state": initial_form}

	def advance_form (pulse: int) -> None:

		"""Advance the form by one bar, logging and announcing section changes."""

		fs = _current_form_state()

		if fs is None:
			seen_form["state"] = None
			if on_bar is not None:
				on_bar(pulse + lookahead_pulses, False)
			return

		# A mid-playback form() re-bind IS a section change, however the two
		# forms' indices happen to line up (#3084).  Entry detection keyed on
		# the index alone stayed silent going from one form's section 0 to
		# another's, so on_section never fired for the new form's first
		# section and transition mutes were never lifted.
		#
		# The bar count is NOT this function's problem: the new state is read
		# through the getter from the moment it is bound, so it advances
		# normally from here and each section gets the bars it declares.
		swapped = fs is not seen_form["state"]
		seen_form["state"] = fs

		section_changed = fs.advance()

		if swapped or section_changed:
			section = fs.get_section_info()
			if section:
				logger.info(f"Form: {section.name}")
			else:
				logger.info("Form: finished")
			sequencer.events.emit_sync("section", section)

		if on_bar is not None:
			# Fixed callbacks fire lookahead-early; the bar line itself is
			# lookahead pulses ahead of the fire pulse.
			on_bar(pulse + lookahead_pulses, swapped or section_changed)

	# Form advances once per bar based on the global time signature.
	bar_beats = subsequence.metre.bar_beats(sequencer.time_signature)

	if start_pulse is None:
		# The form is announced above for the bar it starts on, and advances
		# at every bar line after it.  Before playback that is bar 2; a form
		# arriving mid-playback passes the bar after the one it starts on.
		start_pulse = subsequence.constants.pulses.beats_to_pulses(bar_beats, sequencer.pulses_per_beat)

	await sequencer.schedule_callback_repeating(
		callback = advance_form,
		interval_beats = bar_beats,
		start_pulse = start_pulse,
		reschedule_lookahead = reschedule_lookahead
	)


async def schedule_patterns (
	sequencer: subsequence.sequencer.Sequencer,
	patterns: typing.Iterable[subsequence.pattern.Pattern],
	start_pulse: int = 0
) -> None:

	"""
	Schedule a collection of repeating patterns from a shared start pulse.
	"""

	for pattern in patterns:
		await sequencer.schedule_pattern_repeating(pattern, start_pulse=start_pulse)


async def run_until_stopped (sequencer: subsequence.sequencer.Sequencer) -> None:

	"""
	Run the sequencer until a stop signal is received.
	"""

	# A render plays nothing live, and Ctrl+C is not how it ends (#3530).
	if not sequencer.render_mode:
		logger.info("Playing sequence. Press Ctrl+C to stop.")

	await sequencer.start()

	stop_event = asyncio.Event()
	loop = asyncio.get_running_loop()

	def _request_stop () -> None:

		"""
		Signal handler to request a clean shutdown.
		"""

		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):

		try:
			loop.add_signal_handler(sig, _request_stop)
			continue
		except NotImplementedError:
			# Windows: add_signal_handler is Unix-only.
			pass
		except RuntimeError:
			# Off the main thread, where the interpreter will not hand this
			# thread the process's signals ("set_wakeup_fd only works in main
			# thread").  Only NotImplementedError used to be caught, so a
			# render on a worker thread died here rather than rendering.
			pass

		# Fall back to signal.signal() for SIGINT (Ctrl+C); skip SIGTERM.
		# That is main-thread-only too, and raises ValueError elsewhere.
		try:
			if sig == signal.SIGINT:
				signal.signal(sig, lambda s, f: _request_stop())
		except ValueError:
			logger.debug(
				"No handler installed for %s on this thread - stop(), the bar limit and "
				"the time cap still end the run.",
				sig.name,
			)

	assert sequencer.task is not None, "Sequencer task should exist after start()"

	try:
		await asyncio.wait(
			[asyncio.create_task(stop_event.wait()), sequencer.task],
			return_when = asyncio.FIRST_COMPLETED
		)

	finally:
		# Every way out stops the sequencer, which releases what is sounding
		# and writes the recording.  A SystemExit from a pattern or a scheduled
		# function leaves the loop and has this run cancelled, and the stop that
		# followed the wait never ran: a held note kept sounding (#3551).
		await sequencer.stop()


@dataclasses.dataclass
class _Transition:

	"""One declarative boundary rule registered by ``Composition.transition()``.

	Attributes:
		before: The incoming section name the rule fires before, or ``"*"``
			for any *different* section.
		fill: A Motif (anything with ``.events``/``.length``) to play in the
			final bar.
		channel: Resolved 0-indexed channel for the fill.
		beat: Beat offset of the fill within the final bar.
		mute: Pattern names to mute over the boundary approach.
		beats: Mute window in beats (rounded UP to whole bars - muting is
			bar-granular).
		drum_note_map: Explicit drum map for the fill (otherwise borrowed
			from a registered pattern on the same channel).
		device: Output device (index, name, or None) for the fill - kept raw and
			resolved when the fill fires, since device names are not known until
			play() opens the ports.
	"""

	before: str
	fill: typing.Optional[typing.Any] = None
	channel: typing.Optional[int] = None
	beat: float = 0.0
	mute: typing.Optional[typing.List[str]] = None
	beats: typing.Optional[float] = None
	drum_note_map: typing.Optional[typing.Dict[str, int]] = None
	device: subsequence.midi_utils.DeviceId = None


class _PendingPattern:

	"""
	Holds decorator arguments and builder function until play() is called.
	"""

	def __init__ (
		self,
		builder_fn: typing.Callable,
		channel: int,
		length: float,
		default_grid: int,
		drum_note_map: typing.Optional[typing.Dict[str, int]],
		cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
		nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: float = 1,
		voice_leading: bool = False,
		device: int = 0,
		raw_device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
		min_energy: typing.Optional[float] = None,
	) -> None:

		"""
		Store pattern registration details for deferred scheduling.

		*raw_device* holds the original ``DeviceId`` passed to ``pattern()``
		(``None``, ``int``, or ``str``).  When it is a string, ``device``
		starts at 0 as a placeholder and ``_resolve_pending_devices()`` in
		``_run()`` replaces it with the correct integer index once all output
		devices have been opened.  When it is ``None`` or an ``int``, ``device``
		is already final and ``raw_device`` is not consulted again.

		*mirrors* is the list of additional ``(device_idx, channel_0_indexed)``
		destinations resolved at decoration time.  Empty list = no mirroring.
		"""

		self.builder_fn = builder_fn
		self.channel = channel
		self.length = length
		self.default_grid = default_grid
		self.drum_note_map = drum_note_map
		self.cc_name_map = cc_name_map
		self.nrpn_name_map = nrpn_name_map
		self.reschedule_lookahead = reschedule_lookahead
		self.voice_leading = voice_leading
		self.device = device
		self.raw_device: subsequence.midi_utils.DeviceId = raw_device
		self.mirrors: typing.List[subsequence.pattern.MirrorSpec] = list(mirrors) if mirrors else []
		self.min_energy = min_energy


class _PendingScheduled:

	"""Holds a user function and cycle interval for deferred scheduling."""

	def __init__ (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int, wait_for_initial: bool = False, defer: bool = False) -> None:

		"""Store the function and scheduling parameters."""

		self.fn = fn
		self.cycle_beats = cycle_beats
		self.reschedule_lookahead = reschedule_lookahead
		self.wait_for_initial = wait_for_initial
		self.defer = defer


def _live_blocked (name: str) -> typing.Callable:

	"""Return a function that raises ``RuntimeError`` when called.

	Substituted for built-ins that would block the async event loop
	(``help``, ``input``, ``breakpoint``, ``exit``, ``quit``).  Used by
	``Composition._build_live_namespace`` to populate the safe builtins
	dict for both the file watcher and the TCP eval server.
	"""

	def _raise (*args: typing.Any, **kwargs: typing.Any) -> None:
		raise RuntimeError(f"{name}() is not available in live mode - it would block the sequencer.")

	_raise.__name__ = name
	_raise.__qualname__ = name

	return _raise


class Composition:

	"""
	The top-level controller for a musical piece.
	
	The ``Composition`` object manages the global clock (Sequencer), the harmonic
	progression (HarmonicState), the song structure (subsequence.form_state.FormState), and all MIDI patterns.
	It serves as the main entry point for defining your music.
	
	Typical workflow:

	1. Initialise ``Composition`` with BPM and Key.
	2. Define harmony and form (optional).
	3. Register patterns using the ``@composition.pattern`` decorator.
	4. Call ``composition.play()`` to start the music.
	"""

	def __init__ (
		self,
		output_device: typing.Optional[str] = None,
		bpm: float = 120,
		time_signature: typing.Tuple[int, int] = (4, 4),
		key: typing.Optional[str] = None,
		scale: typing.Optional[str] = None,
		seed: typing.Optional[int] = None,
		record: bool = False,
		record_filename: typing.Optional[str] = None,
		zero_indexed_channels: bool = False,
		latency_ms: float = 0.0
	) -> None:

		"""
		Initialise a new composition.

		Parameters:
			output_device: Which MIDI output port to use, matched against
				``mido.get_output_names()``.  The name is treated as a
				pattern: ``*`` stands for any run of characters and ``?``
				for exactly one, matching is case-insensitive, and a name
				with no wildcards is simply a substring - so a plain
				``"Scarlett"`` finds the port without typing the rest.
				An exact name always wins outright.

				Wildcards matter on Linux/ALSA, where names carry the
				client and port ids (e.g.
				``"Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"``).  The
				client id - ``16`` here - is handed out in connection order
				and moves between reboots or when a virtual port is
				recreated, while the port index after it (``0``) stays put.
				Wildcard the one that moves and keep the one that does not::

				    "*Scarlett 2i4 USB *:0"

				Keep that trailing port index.  A multi-port interface
				reports one name per port, so ``"*U6MIDI Pro*"`` matches
				all three ports of a 3-port unit and asks which you meant
				at every launch, while ``"*U6MIDI Pro *:0"`` names one for
				good.  Prefer ``*`` to ``?`` - ``?`` matches a single
				character, so a pattern written for ``16:0`` quietly stops
				matching once ids reach three digits.  To look up the
				current names::

				    import mido
				    for n in mido.get_output_names(): print(n)

				If ``None``, Subsequence auto-discovers - uses the only
				available device, or prompts to choose if several exist.
			bpm: Initial tempo in beats per minute (default 120).
			time_signature: The metre as ``(beats, unit)``, default ``(4, 4)``.
				A bar lasts ``beats × 4 / unit`` quarter notes, so ``(6, 8)`` is
				three and ``(7, 8)`` three and a half; read it back as
				``composition.bar_beats`` or ``p.bar_beats``.  That bar sets
				``bars=`` lengths, ``p.bar`` and ``p.signal()``, the form and
				transitions, pinned-chord bar numbers, how often ``harmony()``
				changes chord, and the ``link()`` quantum.  The beat counter
				counts the unit (six to a bar of 6/8), accents follow the
				metre's groups, and a recorded or rendered file states the
				metre as declared.  Every ``beat=`` and ``beats=`` is still a
				quarter note.  The unit must be 1, 2, 4, 8, 16 or 32.
			key: The root key of the piece (e.g., "C", "F#", "Bb").
				Required if you plan to use ``harmony()``.
			scale: The scale/mode of the piece (e.g. "minor", "dorian",
				or any registered scale name).  Used to resolve scale
				degrees in motifs; defaults to major (ionian) when unset.
			seed: An optional integer for deterministic randomness. When set,
				every random decision (chord choices, drum probability, etc.)
				will be identical on every run.
			record: When True, record all MIDI events to a file, which opens
				with the time signature and starting tempo as ``render()``'s does,
				and ends where playback stopped with every sounding note released.
			record_filename: Optional filename for the recording (defaults to timestamp).
			zero_indexed_channels: When False (default), MIDI channels use
				1-based numbering (1-16) matching instrument labelling.
				MIDI channel 10 is drums, the way musicians and hardware panels
				show it. When True, MIDI channels use 0-based numbering (0-15)
				matching the raw MIDI protocol.
			latency_ms: Physical output latency of the primary device in
				milliseconds, for delay compensation (default 0.0, must be
				non-negative). Set this when the primary output sounds late
				(e.g. a software sampler) so Subsequence delays faster
				devices to line everything up. See ``midi_output()`` for
				additional devices.

		Example:
			```python
			comp = subsequence.Composition(bpm=128, key="Eb", seed=123)
			```
		"""

		if latency_ms < 0:
			raise ValueError(f"latency_ms must be non-negative - got {latency_ms}")

		self.output_device = output_device
		self.bpm = bpm
		self.time_signature = subsequence.metre.check(time_signature)
		self.key = key
		self.scale = scale
		self._seed: typing.Optional[int] = seed
		self._zero_indexed_channels: bool = zero_indexed_channels
		self._output_latency_ms: float = latency_ms

		# Determinism plumbing: named-stream derivation state.  Build-time
		# consumers draw per-call-salted streams (freeze:1, harmony:2, ...) so
		# adding one call never shifts another's stream; play-time pattern
		# streams are name-keyed in _build_pattern_from_pending.
		self._freeze_count: int = 0
		self._harmony_count: int = 0
		self._form_count: int = 0
		# Which form() call the current form came from.  Paired with a
		# section's own entry count it makes a token that differs across a
		# mid-playback re-bind, where both forms sit on section 0 (#3084).
		self._form_generation: int = 0
		self._form_clock_started: bool = False
		# What form() was last given, so a MIDI Start can rebuild the walk from
		# its opening rather than from wherever it had got to (#3089).  The
		# stream salt is kept too, so a seeded piece replays the same path.
		self._form_spec: typing.Optional[typing.Tuple[typing.Any, bool, typing.Optional[str], str, int]] = None
		self._rewind_harmony: typing.Optional[typing.Callable[[], None]] = None
		# How many times each trigger function has fired, so a one-shot's
		# stream differs from its own last one as well as from its neighbours.
		self._trigger_counts: typing.Dict[str, int] = {}
		self._reroll_nonces: typing.Dict[str, int] = {}
		# Seeds given back with reroll(name, seed=), which a stream keeps until
		# the next plain reroll(name).
		self._given_seeds: typing.Dict[str, int] = {}
		self._locked_names: typing.Set[str] = set()

		self._sequencer = subsequence.sequencer.Sequencer(
			output_device_name = output_device,
			initial_bpm = bpm,
			time_signature = time_signature,
			record = record,
			record_filename = record_filename
		)

		self._harmonic_state: typing.Optional[subsequence.harmonic_state.HarmonicState] = None
		self._harmony_cycle_beats: typing.Optional[float] = None
		self._harmony_style: typing.Optional[str] = None
		# The style (name or ChordGraph) from the most recent style-configuring
		# harmony() call — reused by parameter-only re-calls.
		self._last_harmony_style: typing.Optional[typing.Union[str, subsequence.chord_graphs.ChordGraph]] = None
		self._harmony_reschedule_lookahead: float = 1
		# What the most recent harmony() call configured, so a later re-call
		# naming one parameter keeps the rest instead of silently defaulting
		# them (#3088).  The style has its own home in _last_harmony_style.
		self._harmony_settings: typing.Dict[str, typing.Any] = {
			"cycle_beats": None,
			"dominant_7th": True,
			"key_pull": 0.0,
			"nir_strength": 0.5,
			"minor_turnaround_weight": 0.0,
			"root_diversity": subsequence.harmonic_state.DEFAULT_ROOT_DIVERSITY,
			"reschedule_lookahead": 1.0,
		}
		self._section_progressions: typing.Dict[str, Progression] = {}
		self._bound_progression: typing.Optional[Progression] = None
		self._pinned_chords: typing.Dict[int, typing.Any] = {}
		self._cadence_requests: typing.Dict[int, str] = {}
		self._section_cadences: typing.Dict[str, str] = {}
		self._harmony_horizon = _HarmonyHorizon()
		# True once the span-walking clock is registered for this playback —
		# lets a first mid-playback harmony() call start it exactly once.
		self._harmonic_clock_started: bool = False
		self._section_motifs: typing.Dict[typing.Tuple[str, typing.Optional[str]], typing.Any] = {}
		self._energy_map: typing.Dict[str, typing.Union[float, typing.Tuple[float, float]]] = {}
		self._form_has_payload: bool = False
		self._form_key: typing.Optional[str] = None
		self._form_scale: typing.Optional[str] = None
		# Cache of section progressions resolved against an effective key/scale
		# (key-relative section harmony re-keys per occurrence; resolution is a
		# pure function of (content, key, scale), so this is just memoisation).
		self._resolved_section_cache: typing.Dict[typing.Tuple[str, typing.Optional[str], typing.Optional[str]], Progression] = {}
		self._transitions: typing.List[_Transition] = []
		self._transition_muted: typing.Set[str] = set()
		self._pending_patterns: typing.List[_PendingPattern] = []
		# Names of patterns declared by the most recent live-reload exec (added by
		# pattern()/layer() as they run); the deletion diff in _apply_source_async
		# compares this against the same source's PREVIOUS exec.
		self._declared_names: typing.Set[str] = set()
		# Per-source declaration history: source label/path → the names it
		# declared last time it was exec'd.  The deletion diff unregisters only
		# names a source used to declare and no longer does — never patterns
		# registered by the wrapper script or by another watched source.
		self._source_declared: typing.Dict[str, typing.Set[str]] = {}
		self._pending_scheduled: typing.List[_PendingScheduled] = []
		self._form_state: typing.Optional[subsequence.form_state.FormState] = None
		self._builder_bar: int = 0
		self._display: typing.Optional[subsequence.display.Display] = None
		self._live_server: typing.Optional[subsequence.live_server.LiveServer] = None
		self._live_reloader: typing.Optional[subsequence.live_reloader.LiveReloader] = None
		self._is_live: bool = False
		self._running_patterns: typing.Dict[str, typing.Any] = {}
		self._input_device: typing.Optional[str] = None
		self._input_device_alias: typing.Optional[str] = None
		# What the primary output was asked for by, which a wildcard or partial
		# name loses once the port opens under its own full name (#2964).
		self._requested_output_device: typing.Optional[str] = output_device
		# One take per Composition: play() and render() both refuse a second
		# run rather than quietly producing nothing (#2994).
		self._has_run: bool = False
		self._clock_follow: bool = False
		self._clock_output: bool = False
		self._cc_mappings: typing.List[typing.Dict[str, typing.Any]] = []
		self._cc_forwards: typing.List[typing.Dict[str, typing.Any]] = []
		# Held-note input config from note_input() (None = not declared).
		self._note_input: typing.Optional[typing.Dict[str, typing.Any]] = None
		# Additional output devices registered with midi_output() after construction.
		self._additional_outputs: typing.List[_AdditionalOutput] = []
		# Additional input devices: (device_name: str, alias: Optional[str], clock_follow: bool)
		self._additional_inputs: typing.List[typing.Tuple[str, typing.Optional[str], bool]] = []
		# Maps alias/name → output device index (populated in _run after all devices are opened).
		self._output_device_names: typing.Dict[str, int] = {}
		# Maps alias/name → input device index (populated in _run after all input devices are opened).
		self._input_device_names: typing.Dict[str, int] = {}
		self.data: typing.Dict[str, typing.Any] = {}
		self._osc_server: typing.Optional[subsequence.osc.OscServer] = None
		self.conductor = subsequence.conductor.Conductor()
		self._link_quantum: typing.Optional[float] = None

		# Hotkey state — populated by hotkeys() and hotkey().
		self._hotkeys_enabled: bool = False
		self._hotkey_bindings: typing.Dict[str, HotkeyBinding] = {}
		self._pending_hotkey_actions: typing.List[_PendingHotkeyAction] = []
		self._keystroke_listener: typing.Optional[subsequence.keystroke.KeystrokeListener] = None

		# Tuning state — populated by tuning().
		self._tuning: typing.Optional[typing.Any] = None       # subsequence.tuning.Tuning
		self._tuning_bend_range: float = 2.0
		self._tuning_channels: typing.Optional[typing.List[int]] = None
		# Parts whose overlapping notes have rotated through the pool, in the
		# order they joined it, so a second one can be named (#2798).
		self._tuning_pool_parts: typing.List[str] = []
		# Other parts already told they sit on a pool channel.
		self._tuning_pool_named: typing.Set[str] = set()
		self._tuning_reference_note: int = 60
		self._tuning_exclude_drums: bool = True

	def _resolve_device_id (self, device: subsequence.midi_utils.DeviceId) -> int:
		"""Resolve an output device id (None/int/str) to an integer index.

		``None`` → 0 (primary device).  ``int`` → returned as-is.
		``str`` → looked up in ``_output_device_names``; logs a warning and
		returns 0 if the name is unknown (called after all devices are opened
		in ``_run()``).
		"""
		if device is None:
			return 0
		if isinstance(device, int):
			return device
		idx = self._output_device_names.get(device)
		if idx is None:
			logger.warning(
				f"Unknown output device name '{device}' - routing to device 0. "
				f"Available names: {list(self._output_device_names.keys())}"
			)
			return 0
		return idx

	def _resolve_input_device_id (self, device: subsequence.midi_utils.DeviceId) -> typing.Optional[int]:
		"""Resolve an input device id (None/int/str) to an integer index.

		``None`` → ``None`` (matches any input device - existing behaviour).
		``int`` → returned as-is.  ``str`` → looked up in ``_input_device_names``;
		logs a warning and returns ``-1`` if the name is unknown - an index no
		real device carries, so the mapping matches NOTHING (returning None
		here would silently fail OPEN and listen to every device).
		Called after all input devices are opened in ``_run()``.
		"""
		if device is None:
			return None
		if isinstance(device, int):
			return device
		idx = self._input_device_names.get(device)
		if idx is None:
			logger.warning(
				f"Unknown input device name '{device}' - mapping will be ignored. "
				f"Available names: {list(self._input_device_names.keys())}"
			)
			return -1
		return idx

	def _resolve_pending_devices (self) -> None:
		"""Resolve name-based device ids on pending patterns now that all output devices are open."""
		for pending in self._pending_patterns:
			if isinstance(pending.raw_device, str):
				pending.device = self._resolve_device_id(pending.raw_device)

	def _next_start_pulse (self, pending: "_PendingPattern", now: int) -> int:

		"""Where a part added mid-flight comes in: the next whole multiple of its own length.

		Counted on the song's timeline, the same counting a groove's slot uses
		(#2788) - a one-bar part starts on the next bar, a four-bar part on
		the next four-bar line - so a part added by a save, ``load_patterns``
		or the REPL sits on the grid instead of wherever the save landed, for
		ever after (#3000, decision 4 of #2991).

		A boundary already inside the pattern's own lookahead is too close to
		build for, so the one after it is used.
		"""

		length_pulses, lookahead_pulses = self._sequencer._get_schedule_timing(
			pending.length,
			pending.reschedule_lookahead,
		)

		if length_pulses <= 0:
			return now

		start = ((now // length_pulses) + 1) * length_pulses

		if start - now < lookahead_pulses:
			start += length_pulses

		return start

	def _pending_snapshot (self) -> typing.List[_PendingPattern]:

		"""The parts waiting to start, for a declaration pass to roll back to if it fails (#3377).

		The list holds the entries themselves, so none can be collected and have
		its identity reused while the pass runs.
		"""

		return list(self._pending_patterns)

	def _roll_back_pending (self, snapshot: typing.List[_PendingPattern]) -> None:

		"""Forget every part a failed declaration pass added to those waiting to start (#3377).

		A decorator puts a new part into ``_pending_patterns`` the moment it
		runs, so a save, a typed line or a ``load_patterns()`` that raised
		partway left the parts it had reached waiting - and the next pass to
		finish, or ``play()``, started them, with no source to own them and so
		no later save able to remove them.  Parts pending before the pass stay,
		and one the pass removed stays removed; a running part the pass
		hot-swapped before it raised cannot be undone, and plays its new body.
		"""

		kept = {id(pending) for pending in snapshot}
		self._pending_patterns = [pending for pending in self._pending_patterns if id(pending) in kept]

	async def _activate_new_pending_patterns (self) -> None:

		"""Build and schedule any pending patterns whose names are not yet running.

		Used by ``LiveReloader._reload_async`` to bring NEW patterns added
		in a live reload into rotation mid-flight.  Existing patterns
		hot-swap via the decorator (their ``_builder_fn`` is replaced in
		place); only patterns whose names are not yet in ``_running_patterns``
		need this graduation step.

		A new pattern comes in on the next whole multiple of its own length
		(see :meth:`_next_start_pulse`), not at the pulse the save happened to
		land on - so a bar-long part starts on a bar line and a four-bar part
		on a four-bar line, however the timing of the save fell (#3000).
		"""

		# Resolve any deferred string-device names against the now-open
		# device registry (no-op for int/None devices).
		self._resolve_pending_devices()

		# Dedupe by name, last declaration wins — re-declaring a pattern in a
		# reloaded source must not schedule two copies.
		new_by_name: typing.Dict[str, _PendingPattern] = {}

		for pending in self._pending_patterns:
			if pending.builder_fn.__name__ not in self._running_patterns:
				new_by_name[pending.builder_fn.__name__] = pending

		new_pending = list(new_by_name.values())

		if not new_pending:
			return

		current_pulse = self._sequencer.pulse_count

		for pending in new_pending:

			start_pulse = self._next_start_pulse(pending, current_pulse)

			pattern = self._build_pattern_from_pending(pending, start_pulse = start_pulse)
			await self._sequencer.schedule_pattern_repeating(pattern, start_pulse = start_pulse)
			self._running_patterns[pending.builder_fn.__name__] = pattern

			logger.info(
				"Live-reload: scheduled new pattern '%s' from pulse %d (in %.2f beats)",
				pending.builder_fn.__name__,
				start_pulse,
				(start_pulse - current_pulse) / self._sequencer.pulses_per_beat,
			)

		# Prune graduated (and stale duplicate) declarations: leaving them in
		# _pending_patterns resurrected deleted patterns on every later reload.
		self._pending_patterns = [
			pending for pending in self._pending_patterns
			if pending.builder_fn.__name__ not in self._running_patterns
		]

	def _resolve_channel (self, channel: int) -> int:

		"""
		Convert a user-supplied MIDI channel to the 0-indexed value used internally.

		When ``zero_indexed_channels`` is False (default), the channel is
		validated as 1-16 and decremented by one. When True (0-indexed), the
		channel is validated as 0-15 and returned unchanged.
		"""

		if self._zero_indexed_channels:
			if not 0 <= channel <= 15:
				raise ValueError(f"MIDI channel must be 0-15 (zero_indexed_channels=True), got {channel}")
			return channel
		else:
			if not 1 <= channel <= 16:
				raise ValueError(f"MIDI channel must be 1-16, got {channel}")
			return channel - 1

	def _resolve_mirrors (
		self,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]],
		primary: typing.Optional[typing.Tuple[int, int]] = None,
	) -> typing.List[subsequence.pattern.MirrorSpec]:

		"""
		Validate and normalise a list of mirror destinations.

		Each entry is a 2- or 3-element sequence - ``(device_idx, channel)`` or
		``(device_idx, channel, drum_note_map)`` - as a tuple, list, or any such
		iterable.  ``channel`` is expressed in the user's channel-numbering
		convention (1-16 by default, 0-15 when ``zero_indexed_channels=True``);
		this method converts it to canonical 0-indexed form and rejects
		malformed entries.  The optional ``drum_note_map`` is preserved verbatim
		so the sequencer can re-resolve mirrored drum names per device.

		String device names are NOT supported here; users wanting a named
		device should pass the integer index returned from ``midi_output()``.

		If ``primary=(device, channel)`` is supplied (canonical 0-indexed
		form), a mirror entry whose ``(device, channel)`` matches it triggers a
		``logger.warning`` - this is almost always a user error (every event
		would double-fire on the same destination).  The optional map is ignored
		for this comparison.  Skipped when ``primary`` is ``None``, since the
		runtime API call site supplies its own check.
		"""

		if mirrors is None:
			return []

		resolved: typing.List[subsequence.pattern.MirrorSpec] = []

		for entry in mirrors:

			# Accept any 2- or 3-element iterable (tuple, list, etc.) — config
			# files and JSON sources naturally produce lists.  Validate shape at
			# decoration time so bad inputs surface here instead of producing
			# inscrutable failures inside the sequencer.
			try:
				items = list(entry)
			except TypeError:
				raise ValueError(f"Mirror entry must be a (device, channel[, drum_note_map]) tuple - got {entry!r}")

			if len(items) not in (2, 3):
				raise ValueError(f"Mirror entry must have 2 or 3 elements (device, channel[, drum_note_map]) - got {entry!r}")

			device = items[0]
			channel = items[1]
			drum_map = items[2] if len(items) == 3 else None

			if not isinstance(device, int) or isinstance(device, bool):
				raise ValueError(f"Mirror device must be an integer index - got {type(device).__name__} ({device!r})")

			if not isinstance(channel, int) or isinstance(channel, bool):
				raise ValueError(f"Mirror channel must be an integer - got {type(channel).__name__} ({channel!r})")

			if drum_map is not None and not isinstance(drum_map, dict):
				raise ValueError(f"Mirror drum_note_map must be a dict or None - got {type(drum_map).__name__} ({drum_map!r})")

			resolved_channel = self._resolve_channel(channel)

			if primary is not None and (device, resolved_channel) == primary:
				logger.warning(
					f"Mirror destination {(device, resolved_channel)} matches the pattern's primary destination "
					f"- every event will double-fire on this (device, channel).  This is almost "
					f"certainly unintended."
				)

			resolved_entry: subsequence.pattern.MirrorSpec = (
				(device, resolved_channel)
				if drum_map is None
				else (device, resolved_channel, drum_map)
			)
			resolved.append(resolved_entry)

		return resolved

	@property
	def harmonic_state (self) -> typing.Optional[subsequence.harmonic_state.HarmonicState]:
		"""The active ``HarmonicState``, or ``None`` if ``harmony()`` has not been called."""
		return self._harmonic_state

	def current_chord (self) -> typing.Optional[typing.Any]:

		"""The chord sounding at the playhead, or ``None`` without harmony.

		Reads the harmony window at the current pulse, so it stays accurate
		under variable harmonic rhythm and clock lookahead (the engine's
		``current_chord`` flips *lookahead* beats early - this does not).
		Falls back to the engine's chord before playback starts.  The chord
		may be a decorated wrapper (``Am9``, ``C/G``) when the sounding span
		is spiced; it duck-types the ``Chord`` voicing protocol either way.
		"""

		beat = self._sequencer.pulse_count / self._sequencer.pulses_per_beat

		return self._chord_sounding_at(beat)

	def _chord_sounding_at (self, beat: float) -> typing.Optional[typing.Any]:

		"""The chord sounding at an absolute *beat*, or ``None`` without harmony.

		:meth:`current_chord` is this read at the playhead.  A *quantised*
		one-shot needs it where the one-shot lands instead, which is a bar or
		a beat ahead of the call (#3087).
		"""

		if not self._harmony_horizon.is_empty:
			chord = self._harmony_horizon.chord_at(beat)
			if chord is not None:
				return chord

		if self._harmonic_state is not None:
			return self._harmonic_state.get_current_chord()

		return None

	def _effective_key_scale (
		self,
		section_info: typing.Optional["subsequence.form_state.SectionInfo"],
	) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:

		"""Resolve the key and scale in force, by the key-source precedence.

		The layered chain, key and scale resolved **independently** so a
		section can move the tonic, the mode, or both:
		``Section.key`` > form key (``form(key=)`` / ``Form(key=)``) >
		``Composition.key``, and likewise for scale.  This is the one place
		the tier order lives; every placement site routes through it so the
		section key reaches every compositional element uniformly (the
		three-intent model: only *key-relative* content reads this - absolute
		content ignores it, chord-relative content tracks the chord).
		"""

		key: typing.Optional[str] = None
		scale: typing.Optional[str] = None

		if section_info is not None:
			key = section_info.key
			scale = section_info.scale

		if key is None:
			key = self._form_key
		if key is None:
			key = self.key

		if scale is None:
			scale = self._form_scale
		if scale is None:
			scale = self.scale

		return key, scale

	def _following_section_progression (self, entry: typing.Any) -> typing.Optional[Progression]:

		"""The progression of the section the form has picked to follow the one entered as *entry*.

		What the harmony window reads past a section's edge in a graph or
		generator form, which has no layout to look the next section up in but
		has picked it, as each section starts: ``p.section.next_section`` names it
		(#3526).  *entry* is the ``(form generation, section index)`` the clock
		entered the section with, and the pick is given only while the form is
		still there.  After a live jump or a re-bind, until the clock next fires,
		the window made in the old section could be read, and the new section's
		pick would be a chord for somewhere else.
		"""

		if self._form_state is None:
			return None

		info = self._form_state.get_section_info()

		if info is None or (self._form_generation, info.index) != entry:
			return None

		following = self._form_state.next_section_info()

		return None if following is None else self._resolve_section_progression(following)

	def _resolve_section_progression (
		self,
		info: "subsequence.form_state.SectionInfo",
	) -> typing.Optional[Progression]:

		"""Resolve a section's bound progression against its effective key/scale.

		Concrete progressions (names, ``PitchSet``, frozen captures) are
		returned unchanged.  Key-relative ones resolve against the section's
		effective key+scale - memoised per ``(name, key, scale)`` so a stable
		section reuses one realisation and span identity is stable across
		ticks.  If no key is resolvable at this moment the section is skipped
		(returns ``None`` → falls through to the bound/live source) with a
		warning; the authoritative check runs at :meth:`play`/:meth:`render`.
		"""

		raw = self._section_progressions.get(info.name)

		if raw is None or raw.is_concrete:
			return raw

		key, scale = self._effective_key_scale(info)

		if key is None:
			logger.warning(
				"section_chords(%r) is key-relative but no key resolves for this section - "
				"skipping (the chords fall through to the live/bound source)",
				info.name,
			)
			return None

		cache_key = (info.name, key, scale)
		cached = self._resolved_section_cache.get(cache_key)

		if cached is not None:
			return cached

		try:
			resolved = raw.resolve(key, scale or "ionian")
		except ValueError as error:
			# A degree out of range for the effective scale, or an unknown
			# scale — never let it escape the clock callback (that would kill
			# harmony for the rest of playback).  Skip the section; the _run
			# pre-flight catches the common case far earlier.
			logger.warning(
				"section_chords(%r) cannot resolve against %s %s (%s) - skipping; "
				"the chords fall through to the live/bound source",
				info.name, key, scale or "ionian", error,
			)
			return None

		self._resolved_section_cache[cache_key] = resolved
		return resolved

	@property
	def form_state (self) -> typing.Optional["subsequence.form_state.FormState"]:
		"""The active ``subsequence.form_state.FormState``, or ``None`` if ``form()`` has not been called."""
		return self._form_state

	@property
	def sequencer (self) -> subsequence.sequencer.Sequencer:
		"""The underlying ``Sequencer`` instance."""
		return self._sequencer

	@property
	def running_patterns (self) -> typing.Dict[str, typing.Any]:
		"""The currently active patterns, keyed by name."""
		return self._running_patterns

	@property
	def builder_bar (self) -> int:
		"""Current bar index used by pattern builders."""
		return self._builder_bar

	@property
	def bar_beats (self) -> float:
		"""How many beats (quarter notes) one bar lasts: ``beats × 4 / unit``, so 3.0 in 6/8."""
		return subsequence.metre.bar_beats(self.time_signature)

	def _require_harmonic_state (self) -> subsequence.harmonic_state.HarmonicState:
		"""Return the active HarmonicState, raising ValueError if none is configured."""
		if self._harmonic_state is None:
			raise ValueError(
				"harmony() must be called before this action - "
				"no harmonic state has been configured."
			)
		return self._harmonic_state

	def _coerce_progression (self, source: typing.Any, what: str) -> Progression:

		"""Coerce a Progression / element list / preset name and resolve it against the key.

		Binding freezes one realisation (the value type's identity), so
		key-relative content resolves here, at bind time, against the
		composition's key and scale.  Used by the *global* bound progression
		(``harmony(progression=)``) - which is not section-scoped, so it has
		nothing to re-key against.
		"""

		value = source if isinstance(source, Progression) else subsequence.progressions.progression(source)

		if not value.is_concrete:
			if self.key is None:
				raise ValueError(
					f"{what} contains key-relative chords (degrees/romans) - "
					"set key= on the Composition so they can resolve"
				)
			value = value.resolve(self.key, self.scale or "ionian")

		return value

	def _coerce_section_progression (self, source: typing.Any) -> Progression:

		"""Coerce a section progression, keeping key-relative content UNRESOLVED.

		Section harmony re-keys per occurrence (the section/form/composition
		key in force when the section plays), so a key-relative progression is
		stored relative and resolved late, in the clock, against the section's
		effective key+scale - unlike the global bound progression, which
		freezes at bind.  Concrete content (chord names, frozen captures,
		``PitchSet``) is already absolute and never moves.
		"""

		return source if isinstance(source, Progression) else subsequence.progressions.progression(source)

	def harmony (
		self,
		style: typing.Optional[typing.Union[str, subsequence.chord_graphs.ChordGraph]] = None,
		cycle_beats: typing.Optional[float] = KEEP,
		dominant_7th: bool = KEEP,
		key_pull: float = KEEP,
		nir_strength: float = KEEP,
		minor_turnaround_weight: float = KEEP,
		root_diversity: float = KEEP,
		reschedule_lookahead: float = KEEP,
		progression: typing.Optional[typing.Any] = KEEP,
		**retired: typing.Any,
	) -> None:

		"""
		Configure the harmonic logic and chord change intervals.

		Two sources, combinable: a **bound progression** (``progression=`` - a
		:class:`Progression` value, an element list like ``[1, 6, 3, "bVII7"]``,
		or chord names) walked span by span on the global clock; and/or a
		**graph style** stepping live chords.  With only a progression bound,
		it loops on exhaustion; with a style configured too, exhaustion falls
		through to live stepping (the frozen-replay bridge).  Calling with
		neither argument keeps today's default live engine
		(``style="functional_major"``).

		**A re-call changes only what it names.**  Anything left out keeps the
		value the last call gave it, so ``harmony(key_pull=0.4)`` after
		``harmony(style="aeolian_minor", cycle_beats=8, nir_strength=0.9)``
		leaves the style, the harmonic rhythm and the inertia where they were.
		Pass ``progression=None`` to **unbind** a bound progression - the walk
		falls back to live stepping at the next chord boundary.

		Parameters:
			style: The harmonic style to use, by name or as a ``ChordGraph``.
				Built-in: ``"functional_major"`` (alias ``"diatonic_major"``),
				the standard major key; ``"hooktheory_major"`` (alias
				``"pop_major"``), the same chords weighted by how often pop and
				rock songs make each move; ``"turnaround"``, ii–V–I turnarounds
				modulating through all twelve keys, with minor ones as far as
				``minor_turnaround_weight`` allows; ``"aeolian_minor"``,
				natural minor with Phrygian and harmonic-minor colours;
				``"phrygian_minor"``, a dark palette of four minor chords (i,
				bii, iv, v); ``"lydian_major"``, bright and floating, from the
				raised fourth; ``"dorian_minor"``, minor with a major IV (soul,
				funk); ``"chromatic_mediant"``, film-score shifts between roots
				a third apart; ``"suspended"``, open sus2 and sus4 chords with
				no thirds; ``"mixolydian"``, major with a flat seventh, open and
				unresolved; ``"whole_tone"``, augmented chords in symmetrical,
				dreamlike drift; ``"diminished"``, minor-third symmetry, angular
				and disorienting.
			cycle_beats: How many beats each live chord lasts.  Defaults to
				one bar (``composition.bar_beats``): 4 in 4/4, 3 in 3/4.
				Bound progressions carry their own harmonic rhythm in their
				spans, so this applies to live stepping only.  A re-call
				during playback takes effect from the next chord boundary;
				a FIRST harmony() call mid-playback starts the clock itself.
			dominant_7th: Whether to include V7 chords (default True).
			key_pull: How strongly the walk is drawn to the key's own centres -
				I, ii and V (0.0 to 1.0).  ``0.0`` (the default) leaves the
				style's own weights alone, which is what every piece written
				so far sounds like; ``1.0`` is the strongest pull.  Replaces
				``gravity=``, which ran the other way round and did nothing at
				its own default: ``key_pull = 1 - gravity``.
			nir_strength: Melodic inertia (0.0 to 1.0). Influences chord movement
				expectations.
			minor_turnaround_weight: For "turnaround" style, influences major vs minor feel.
			root_diversity: Root-repetition damping (0.0 to 1.0). Each recent
				chord sharing a candidate's root reduces the weight to 40% at
				the default (0.4). Set to 1.0 to disable.
			reschedule_lookahead: How many beats in advance to calculate the
				next chord.
			progression: A progression to bind to the global clock.  Key-
				relative content resolves now, against the composition key
				and scale (binding freezes one realisation).  ``None``
				unbinds whatever is bound, handing the harmony back to the
				live engine at the next chord boundary.

		Example:
			```python
			# A moody minor progression that changes every 8 beats
			comp.harmony(style="aeolian_minor", cycle_beats=8, key_pull=0.6)

			# Manual harmony driving everything - loops forever
			comp.harmony(progression=subsequence.progression([1, 6, 3, 7]))
			```
		"""

		if retired:
			subsequence.harmonic_state._refuse_retired_parameters("harmony", retired)

		# Resolve each parameter against what the last call configured, so a
		# re-call naming one of them keeps the rest (#3088).  Before this, the
		# signature's own defaults won every time: after
		# harmony(style="aeolian_minor", cycle_beats=8, nir_strength=0.9), a
		# later harmony(key_pull=0.4) silently reset cycle_beats, the
		# lookahead, nir_strength and root_diversity.
		def _resolve (name: str, given: typing.Any) -> typing.Any:
			if given is KEEP:
				return self._harmony_settings[name]
			self._harmony_settings[name] = given
			return given

		cycle_beats = _resolve("cycle_beats", cycle_beats)
		dominant_7th = _resolve("dominant_7th", dominant_7th)
		key_pull = _resolve("key_pull", key_pull)
		nir_strength = _resolve("nir_strength", nir_strength)
		minor_turnaround_weight = _resolve("minor_turnaround_weight", minor_turnaround_weight)
		root_diversity = _resolve("root_diversity", root_diversity)
		reschedule_lookahead = _resolve("reschedule_lookahead", reschedule_lookahead)

		if not 0.0 <= key_pull <= 1.0:
			raise ValueError(f"harmony(key_pull={key_pull!r}) takes 0.0 to 1.0")

		if style is None and progression is KEEP:
			# A parameter-only re-call (key_pull=, cycle_beats=, ...) keeps the
			# configured style — defaulting unconditionally here would silently
			# replace e.g. aeolian_minor with functional_major.
			style = self._last_harmony_style if self._last_harmony_style is not None else "functional_major"

		if style is not None:

			if self.key is None:
				raise ValueError("Cannot configure harmony without a key - set key in the Composition constructor")

			preserved_history: typing.List[subsequence.chords.Chord] = []
			preserved_current: typing.Optional[subsequence.chords.Chord] = None

			if self._harmonic_state is not None:
				preserved_history = self._harmonic_state.history.copy()
				preserved_current = self._harmonic_state.current_chord

			# Per-call salted build stream (harmony:1, harmony:2, ...): a re-call
			# gets its own deterministic stream while history and current chord
			# are preserved above, and adding a re-call never shifts any other
			# consumer's stream.
			self._harmony_count += 1

			self._harmonic_state = subsequence.harmonic_state.HarmonicState(
				key_name = self.key,
				graph_style = style,
				include_dominant_7th = dominant_7th,
				# The engine still blends from the other end: 1.0 means
				# "every diatonic chord equally", which is no pull at all.
				key_gravity_blend = 1.0 - key_pull,
				nir_strength = nir_strength,
				minor_turnaround_weight = minor_turnaround_weight,
				root_diversity = root_diversity,
				rng = self._stream(f"harmony:{self._harmony_count}")
			)

			if preserved_history:
				self._harmonic_state.history = preserved_history
			if preserved_current is not None and self._harmonic_state.graph.get_transitions(preserved_current):
				self._harmonic_state.current_chord = preserved_current

			self._harmony_style = style if isinstance(style, str) else None
			self._last_harmony_style = style

		if progression is not KEEP:
			# An explicit None unbinds.  The clock reads the binding through a
			# getter on every tick, so clearing it here is enough to fall back
			# to live stepping at the next boundary (#3088).
			self._bound_progression = (
				None if progression is None
				else self._coerce_progression(progression, "harmony(progression=)")
			)

		self._harmony_cycle_beats = cycle_beats
		self._harmony_reschedule_lookahead = reschedule_lookahead

		# A re-call invalidates whatever the horizon had planned.
		self._harmony_horizon.invalidate_future()

		# A FIRST harmony() call mid-playback must start the clock itself —
		# _run() only schedules clocks for sources it can see at play() time.
		# (Re-calls need nothing here: the clock reads its sources through
		# getters on every tick.)
		loop = self._sequencer._event_loop

		if loop is not None and loop.is_running() and not self._harmonic_clock_started:
			try:
				on_loop = asyncio.get_running_loop() is loop
			except RuntimeError:
				on_loop = False

			if on_loop:
				loop.create_task(self._start_harmonic_clock())
			else:
				asyncio.run_coroutine_threadsafe(self._start_harmonic_clock(), loop)

	def _remember_harmony_rewind (self, rewind: typing.Callable[[], None]) -> None:

		"""Keep the harmonic clock's own rewind, for an external Start (#3089)."""

		self._rewind_harmony = rewind

	async def _rewind_to_the_top (self) -> None:

		"""Put the composition back to its opening - an external MIDI Start.

		Decision of 2026-09-21: a Start rewinds the **whole piece**, not only
		the transport.  The MIDI specification is the argument - Start means
		"start at the beginning of the song", and Continue is the message that
		resumes where a Stop left off - and it is what a DAW does.  Before
		this, a Start put every part back on bar 1 while the harmony and the
		form carried on, so the piece was heard from the top over whatever
		chord happened to be sounding, in whatever section it had reached.

		The form is rebuilt from what ``form()`` was given, on the same stream
		salt, so a seeded graph walks the same path it walked the first time -
		a restart is the same piece again, not a different one.
		"""

		if self._form_spec is not None:

			sections, loop, start, at_end, count = self._form_spec

			self._form_state = subsequence.form_state.FormState(
				sections,
				loop = loop,
				start = start,
				rng = self._stream(f"form:{count}"),
				at_end = at_end,
			)

			# The new state is a different object, so the form clock sees the
			# swap and announces section 0 (#3084).
			self._resolved_section_cache = {}

		if self._rewind_harmony is not None:
			self._rewind_harmony()

	async def _start_form_clock (self, clock_lookahead: typing.Optional[float] = None) -> None:

		"""Register the bar-by-bar form clock (idempotent per playback).

		Called from ``_run()`` when a form exists at play time, and from
		:meth:`form` when the FIRST form arrives mid-playback (#3084).
		Without the second path the clock was never registered at all, and
		the form simply never advanced: measured at ``('verse', 0)`` for
		seven bars after a ``form()`` call in bar 3.

		Registered BEFORE the harmonic clock, which matters: same-pulse fixed
		callbacks fire in registration order, and on a section-boundary bar
		the harmonic clock reads the current section to decide whether to walk
		that section's chords.  The other way round it reads the OLD section
		on every boundary, shifting section_chords() replays by a bar and
		bleeding them across sections.
		"""

		if self._form_clock_started or self._form_state is None:
			return

		self._form_clock_started = True

		bar_beats = self.bar_beats

		if clock_lookahead is None:
			lookaheads = [pattern.reschedule_lookahead for pattern in self._running_patterns.values()]
			clock_lookahead = min(bar_beats, max(1.0, float(max(lookaheads, default = 1))))

		per_beat = self._sequencer.pulses_per_beat
		bar_pulses = subsequence.constants.pulses.beats_to_pulses(bar_beats, per_beat)
		now_pulse = self._sequencer.pulse_count

		# The form is announced for the bar it starts on and advances at every
		# bar line after that.  Before playback the playhead is 0, so this is
		# the usual "first advance at bar 2"; arriving mid-playback it is the
		# bar after the one the form starts on, rather than a pulse already
		# gone by (the same trap as #3083).
		start_pulse = ((now_pulse // bar_pulses) + 2) * bar_pulses if now_pulse else bar_pulses

		await schedule_form(
			sequencer = self._sequencer,
			form_state = self._form_state,
			reschedule_lookahead = clock_lookahead,
			on_bar = self._check_transitions,
			# Re-read every bar so a mid-playback form() re-bind advances
			# the NEW state instead of the abandoned object.
			get_form_state = lambda: self._form_state,
			start_pulse = start_pulse,
		)

	async def _start_harmonic_clock (self, bar_beats: typing.Optional[float] = None, clock_lookahead: typing.Optional[float] = None) -> None:

		"""Register the span-walking harmonic clock (idempotent per playback).

		Called from ``_run()`` when a harmony source exists at play time, and
		from ``harmony()`` when the FIRST source arrives mid-playback.
		``bar_beats``/``clock_lookahead`` default to a fresh computation for
		the mid-playback path; ``_run()`` passes the values it validated.
		"""

		if self._harmonic_clock_started:
			return

		self._harmonic_clock_started = True

		if bar_beats is None:
			bar_beats = self.bar_beats

		# Where the walk begins.  _run() registers the clock before playback,
		# so this is 0 and nothing changes; a FIRST harmony() arriving
		# mid-playback starts at the next BAR LINE instead of replaying the
		# piece from beat 0 (#3083).  Chord changes are bar-aligned everywhere
		# else in the engine, and a chord appearing mid-bar under a pattern
		# that has already rendered its bar would clash with it.
		now_beat = self._sequencer.pulse_count / self._sequencer.pulses_per_beat
		start_beat = math.ceil(now_beat / bar_beats - 1e-9) * bar_beats

		if clock_lookahead is None:
			lookaheads = [pattern.reschedule_lookahead for pattern in self._running_patterns.values()]
			clock_lookahead = min(bar_beats, max(1.0, float(self._harmony_reschedule_lookahead), float(max(lookaheads, default = 1))))

		def _get_section_progression () -> typing.Optional[typing.Tuple[str, typing.Any, int, typing.Optional[Progression]]]:
			"""Return (section_name, section_index, bars, Progression|None) for the current section, or None.

			The progression is resolved against the section's effective
			key/scale here (key-relative section harmony re-keys per
			occurrence); concrete content passes through unchanged.
			"""
			if self._form_state is None:
				return None
			info = self._form_state.get_section_info()
			if info is None:
				return None
			prog = self._resolve_section_progression(info)
			# The entry token pairs the form's generation with the section's
			# own entry count, so a re-bind is a section change even when both
			# forms are on their section 0 (#3084).
			return (info.name, (self._form_generation, info.index), info.bars, prog)

		def _get_section_progression_at (bar: int) -> typing.Optional[Progression]:
			"""The progression bound to the section owning a 1-based global bar.

			``section_info_at_bar`` answers for sequence forms only and returns
			``None`` for graphs and generators, which have no layout past the
			playhead; _following_section_progression answers for those.
			"""
			if self._form_state is None:
				return None
			info = self._form_state.section_info_at_bar(bar)
			if info is None:
				return None
			return self._resolve_section_progression(info)

		def _resolve_cadence_formula (name: str) -> typing.List[subsequence.chords.Chord]:
			"""Resolve a cadence formula against the composition key and scale, at plan time."""
			hs = self._harmonic_state
			key_pc = subsequence.chords.key_name_to_pc(self.key) if self.key is not None else (hs.key_root_pc if hs is not None else 0)
			spec = subsequence.cadences.cadence_formula(name)
			return [
				subsequence.progressions.resolve_constraint(element, key_pc, self._constraint_scale(), f"cadence {name!r}")
				for element in spec.formula
			]

		await schedule_harmonic_clock(
			sequencer = self._sequencer,
			get_harmonic_state = lambda: self._harmonic_state,
			horizon = self._harmony_horizon,
			bar_beats = bar_beats,
			cycle_beats = self._harmony_cycle_beats or bar_beats,
			get_cycle_beats = lambda: self._harmony_cycle_beats or self.bar_beats,
			get_bound_progression = lambda: self._bound_progression,
			get_section_progression = _get_section_progression,
			get_section_progression_at = _get_section_progression_at,
			get_following_section_progression = self._following_section_progression,
			get_pinned = self._resolve_pin,
			cadence_requests = self._cadence_requests,
			resolve_cadence = _resolve_cadence_formula,
			get_section_cadence = self._section_cadences.get,
			reschedule_lookahead = clock_lookahead,
			start_beat = start_beat,
			on_stop = self._harmonic_clock_stopped,
			register_rewind = self._remember_harmony_rewind,
		)

	def _warn_about_sections_with_no_chords (self) -> None:

		"""Say once, at the top, which sections of the form will have no chords.

		With ``section_chords()`` on some sections and no ``harmony()`` at
		all, the sections left out have nothing to play and nothing to
		generate.  They hold the last chord (decision 2 of #2991), which is a
		reasonable sound and almost never the intended one - so it is worth a
		line naming them rather than leaving somebody to wonder why the
		bridge is a held F.
		"""

		if self._harmonic_state is not None or not self._section_progressions:
			return

		if self._form_state is None:
			return

		if self._form_state._section_bars is not None:
			named = set(self._form_state._section_bars)			# a graph form
		elif self._form_state._sequence is not None:
			named = {section.name for section in self._form_state._sequence}	# a list form
		else:
			return		# a generator form names its sections as it goes

		unbound = sorted(named - set(self._section_progressions))

		if not unbound:
			return

		logger.warning(
			"These sections have no chords of their own and there is no harmony() to "
			"generate any, so each will hold the chord before it for its whole length: %s. "
			"Give them a section_chords(), or call harmony() once for the piece.",
			", ".join(unbound),
		)

	def _harmonic_clock_stopped (self) -> None:

		"""The clock gave up its slot - let a later harmony() start a new one.

		The sequencer drops a callback sequence that returns None, so without
		this the flag stayed True for the rest of the performance and a
		``harmony()`` arriving mid-piece registered nothing (#2998).
		"""

		self._harmonic_clock_started = False

	def _constraint_scale (self) -> str:

		"""The scale that hybrid-constraint ints resolve against.

		The composition's own scale when set; otherwise inferred from the
		harmony style (``aeolian_minor`` → minor, matching
		:meth:`Progression.generate`'s documented inference), falling back
		to ionian.  Roman strings carry their quality and never need it.
		"""

		if self.scale is not None:
			return self.scale

		return subsequence.progressions._STYLE_SCALES.get(self._harmony_style or "", "ionian")

	def freeze (
		self,
		bars: int,
		end: typing.Optional[typing.Any] = None,
		pins: typing.Optional[typing.Dict[int, typing.Any]] = None,
		avoid: typing.Optional[typing.Sequence[typing.Any]] = None,
		cadence: typing.Optional[str] = None,
	) -> "Progression":

		"""Capture a chord progression from the live harmony engine.

		Runs the harmony engine forward by *bars* chord changes, records each
		chord, and returns it as a :class:`Progression` that can be bound to a
		form section with :meth:`section_chords`.

		The engine state **advances** - successive ``freeze()`` calls produce a
		continuing compositional journey so section progressions feel like parts
		of a whole rather than isolated islands.

		The hybrid constraints compile into the walk: ``end=`` fixes the last
		bar ("end on V at bar 8"), ``pins=`` fix any 1-based bar, ``avoid=``
		excludes chords throughout.  Specs follow the progression-element
		grammar (ints where diatonic, roman/name strings where chromatic) and
		resolve against the composition key and scale.  A backward
		feasibility pass guarantees satisfiability before any chord is drawn;
		the forward walk keeps the engine's real history-dependent weighting.
		Bar 1 is always the engine's current chord - the journey continues -
		so ``pins={1: ...}`` may only name it redundantly.

		Parameters:
			bars: Number of chords to capture (one per harmony cycle).
			end: The chord at the final bar - ``end="V"`` is the cadential
				major dominant in minor.
			pins: ``{bar: chord}`` - 1-based fiat positions.
			avoid: Chords excluded from the walk.
			cadence: A cadence name (``"strong"``/``"soft"``/``"open"``/
				``"fakeout"``, theory aliases accepted) - its formula pins
				the final bars, so the walk approaches the close.
				Conflicts with ``end=`` or pins on those bars.

		Returns:
			A :class:`Progression` with the captured chords and trailing
			history for NIR continuity.

		Raises:
			ValueError: If :meth:`harmony` has not been called first, or the
				constraints are contradictory or unsatisfiable.

		Example::

			composition.harmony(style="functional_major", cycle_beats=4)
			verse  = composition.freeze(8, end="V")   # the verse sets up the chorus
			chorus = composition.freeze(4)            # next 4 chords, continuing on
			composition.section_chords("verse",  verse)
			composition.section_chords("chorus", chorus)
		"""

		hs = self._require_harmonic_state()

		if bars < 1:
			raise ValueError("bars must be at least 1")

		if cadence is not None:
			pins = subsequence.progressions.cadence_pins(cadence, bars, pins, end)
			end = None

		scale = self._constraint_scale()
		key_pc = subsequence.chords.key_name_to_pc(self.key) if self.key is not None else hs.key_root_pc

		resolved_pins = {
			position: subsequence.progressions.resolve_constraint(spec, key_pc, scale, f"pins[{position}]")
			for position, spec in (pins or {}).items()
		}
		resolved_end = subsequence.progressions.resolve_constraint(end, key_pc, scale, "end") if end is not None else None
		resolved_avoid = [subsequence.progressions.resolve_constraint(spec, key_pc, scale, "avoid") for spec in (avoid or [])]

		if 1 in resolved_pins and resolved_pins[1] != hs.current_chord:
			raise ValueError(
				f"pins[1]={resolved_pins[1].name()} conflicts with the engine's current chord "
				f"({hs.current_chord.name()}) - bar 1 of a freeze continues the journey; "
				"pin a later bar, or use pin_chord() for playback fiat"
			)

		# Per-call salted stream (freeze:1, freeze:2, ...): each call's draws
		# are independent of every other consumer, so frozen progressions are
		# reproducible WITHOUT play() and adding a call cannot shift a
		# neighbour's output.  Engine state still advances normally — chord
		# continuity comes from current_chord/history, randomness from the
		# salted stream (swap-and-restore keeps hs.rng for play untouched).
		self._freeze_count += 1
		stream = self._stream(f"freeze:{self._freeze_count}")
		saved_rng = hs.rng

		if stream is not None:
			hs.rng = stream

		try:
			# The kernel with the engine's own hooks is draw-for-draw the old
			# step() loop when unconstrained — one walk path for both.
			def _commit (chosen: subsequence.chords.Chord) -> None:
				hs.current_chord = chosen

			collected = subsequence.sequence_utils.constrained_walk(
				hs.graph,
				hs.current_chord,
				bars,
				rng = hs.rng,
				pins = resolved_pins,
				end = resolved_end,
				avoid = resolved_avoid,
				weight_modifier = hs._transition_weight,
				before_choice = hs._record_transition_source,
				after_choice = _commit,
			)

			# Advance past the last captured chord so the next freeze() call or
			# live playback does not duplicate it.
			hs.step()

		finally:
			hs.rng = saved_rng

		span_beats = float(self._harmony_cycle_beats or self.bar_beats)

		return Progression(
			spans = tuple(
				subsequence.progressions.ChordSpan(chord = chord, beats = span_beats)
				for chord in collected
			),
			trailing_history = tuple(hs.history),
		)

	def section_chords (self, section_name: str, progression: typing.Any) -> None:

		"""Bind a :class:`Progression` to a named form section.

		Every time *section_name* plays, the harmonic clock walks the
		progression's spans instead of calling the live engine.  Sections
		without a bound progression generate live chords - **when there is a
		live engine to generate them**.  With no :meth:`harmony` on the piece
		there is nothing to generate from, so a section left out holds the
		chord before it for its whole length, and a line at startup names
		which sections those are.  Give every section its own chords, or call
		:meth:`harmony` once for the piece.

		Accepts a :class:`Progression` value (from :meth:`freeze`, the
		``progression()`` factory, or hand-built) or anything the factory
		accepts - an element list like ``[1, 6, 3, "bVII7"]`` or chord
		names.

		**Key-relative content re-keys per occurrence.**  A progression
		written in degrees or romans is *key-relative* content: it resolves
		late, each time the section plays, against that section's effective
		key and scale (``Section.key`` > form key > composition key, with
		mode following the same chain).  So a ``Section(key="A")`` plays the
		same numbered progression a tone higher - its chords and its degrees
		share one tonic.  *Absolute* content - chord names (``"Am"``),
		:class:`~subsequence.progressions.PitchSet`, and frozen captures from
		:meth:`freeze` - names exact chords and is never transposed by a key.

		On exhaustion mid-section the progression loops when no graph style
		is configured (and always when it contains a ``PitchSet``); with a
		live engine, exhaustion **falls through to live stepping in the
		COMPOSITION key** - the live graph engine does not transpose for a
		section (a stateful walk does not modulate mid-stream), so a
		re-keyed section that runs out of written chords hands off to
		composition-key harmony.  Bind a full-length progression (or set
		``at_end``/loop intent) if you need the whole section in its key.

		Parameters:
			section_name: Name of the section as defined in :meth:`form`.
			progression: The progression to bind.

		Raises:
			ValueError: If a graph-based form has been configured and
				*section_name* is not one of its sections.  List and generator
				forms yield names lazily, so they cannot be validated here.
				(A key-relative progression with no resolvable key for the
				section is caught at :meth:`play`/:meth:`render`, once the
				form's keys are known.)

		Example::

			composition.section_chords("verse",  verse_progression)
			composition.section_chords("chorus", [1, 6, 3, 7])
			# "bridge" is not bound - it generates live chords
		"""

		if (
			self._form_state is not None
			and self._form_state._section_bars is not None
			and section_name not in self._form_state._section_bars
		):
			known = ", ".join(sorted(self._form_state._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._section_progressions[section_name] = self._coerce_section_progression(progression)
		self._resolved_section_cache = {}
		self._harmony_horizon.invalidate_future()

	def pin_chord (self, bar: int, chord: typing.Optional[typing.Any]) -> None:

		"""Force the chord sounding at a bar - fiat over live generation.

		Whatever the harmonic source (live walk, bound progression, section
		progression) produces for *bar*, the pinned chord overrides it.
		Pass ``None`` to remove a pin.

		Pin a chord the style would never reach and the walk carries on from
		the style's own chord on that root - ``E7`` continues the way ``Em``
		does.  Where the style has nothing on that root at all, the bar after
		the pin is the tonic.  Either way the pin sounds, and one bar later
		the piece is walking again.

		Parameters:
			bar: 1-based bar number (the musician count).
			chord: A chord name, int degree, roman string, ``Chord``,
				``PitchSet``, or ``None`` to unpin.  A **key-relative** spec
				(int degree, roman) re-keys like section harmony: it resolves
				late, against the effective key of the section sounding at
				that bar (so ``pin_chord(8, "V")`` is the dominant of
				wherever bar 8 lands).  A **concrete** spec (name, ``Chord``,
				``PitchSet``) is absolute and never moves.

		Example::

			composition.pin_chord(8, "E7")    # the turnaround lands on E7
			composition.pin_chord(8, "V")     # the dominant of bar 8's section
			composition.pin_chord(8, None)    # let it walk again
		"""

		if not isinstance(bar, int) or isinstance(bar, bool) or bar < 1:
			raise ValueError(f"bars are 1-based ints, got {bar!r}")

		if chord is None:
			self._pinned_chords.pop(bar, None)
		else:
			# Store the parsed span — relative pins resolve late (per section)
			# at the clock; concrete pins are absolute.
			span = subsequence.progressions.parse_element(chord, beats = self.bar_beats)

			if not span.is_concrete:
				# Raise early only when no key is resolvable for this bar — the
				# bar's own section (sequence forms) may supply one even with no
				# composition/form key.
				probe_info = self._form_state.section_info_at_bar(bar) if self._form_state is not None else None
				probe_key, probe_scale = self._effective_key_scale(probe_info)
				if probe_key is None:
					raise ValueError(
						"pin_chord with a key-relative spec (degree/roman) needs a key - set key= on "
						"the Composition, a form key, or a Section.key for that bar (the pin re-keys "
						"to the section's effective key)"
					)

				# Say so here, where the musician wrote it, rather than at the
				# bar it was written for: an unresolvable degree raised out of
				# the clock mid-performance and took the whole harmonic clock
				# down with it (#2998).  A pin that stops resolving later,
				# because a section re-keyed under it, is warned and skipped.
				try:
					span.resolve(subsequence.chords.key_name_to_pc(probe_key), probe_scale or "ionian")
				except (ValueError, IndexError, KeyError) as error:
					raise ValueError(
						f"pin_chord({bar}, {chord!r}) does not name a chord in "
						f"{probe_key} {probe_scale or 'ionian'}: {error}"
					) from error

			self._pinned_chords[bar] = span

		self._harmony_horizon.invalidate_future()

	def _resolve_pin (self, bar: int) -> typing.Optional[typing.Any]:

		"""Resolve a stored pin to a chord-like, re-keying relative pins per section.

		Concrete pins return their chord directly; key-relative pins resolve
		against the effective key of the section sounding now (the clock
		reads this as it reaches each bar).  Returns ``None`` (no pin / a
		relative pin with no resolvable key, warned) so the clock falls
		through to its normal source.
		"""

		span = self._pinned_chords.get(bar)

		if span is None:
			return None

		if span.is_concrete:
			return _span_chord(span)

		# Key the pin to the section that OWNS this bar (the clock's lookahead
		# can project a pin into a later, differently-keyed section while the
		# playhead is still earlier) — fall back to the playhead section where
		# a per-bar section is not computable (graph/generator forms).
		info: typing.Optional["subsequence.form_state.SectionInfo"] = None
		if self._form_state is not None:
			info = self._form_state.section_info_at_bar(bar)
			if info is None:
				info = self._form_state.get_section_info()

		key, scale = self._effective_key_scale(info)

		if key is None:
			logger.warning(
				"pin_chord(%d, ...) is key-relative but no key resolves for that bar - ignoring the pin",
				bar,
			)
			return None

		try:
			return _span_chord(span.resolve(subsequence.chords.key_name_to_pc(key), scale or "ionian"))
		except (ValueError, IndexError, KeyError) as error:
			# A pin that resolved when it was written can stop resolving when a
			# section re-keys under it.  Warn and fall through — letting this
			# escape killed the harmonic clock for the rest of the piece, and
			# silenced the pinned bar and the one before it (#2998).
			logger.warning(
				"pin_chord(%d, ...) does not resolve in %s %s - ignoring the pin: %s",
				bar, key, scale or "ionian", error,
			)
			return None

	def request_cadence (self, cadence: str = "strong", bar: typing.Optional[int] = None) -> None:

		"""Ask the live engine to approach a cadence arriving at a bar.

		The request hook: where :meth:`pin_chord` is fiat, this is a
		*steered approach* - at the next chord boundary the clock plans the
		remaining changes up to *bar* as a constrained walk through the
		engine's real weights, pinned to the cadence formula at the tail
		(``"strong"`` arrives V→I, ``"soft"`` IV→I, ``"open"`` IV→V,
		``"fakeout"`` V→vi; theory aliases accepted).  The chords still
		commit one boundary at a time, so the journey continues through the
		close.

		One-shot: the request is consumed when planned.  Live harmony only -
		bound/section progressions are data and cannot be steered; a request
		whose bar passes unserved expires with a warning.  If the formula is
		not walkable from where the harmony stands, the arrival lands by
		fiat (loudly).  Ask at least a pattern-lookahead ahead: patterns may
		already have rendered against the previously planned chord.

		Parameters:
			cadence: The cadence name.
			bar: The 1-based bar the cadence's final chord arrives at
				(required; in practice ≥ 2 - bar 1 cannot be approached).

		Example::

			composition.request_cadence("open", bar=16)    # hang on V at bar 16
		"""

		spec = subsequence.cadences.cadence_formula(cadence)

		if bar is None or not isinstance(bar, int) or isinstance(bar, bool) or bar < 1:
			raise ValueError(f"request_cadence needs bar= - the 1-based bar the cadence arrives at (got {bar!r})")

		self._cadence_requests[bar] = spec.name
		self._harmony_horizon.invalidate_future()

	def section_cadence (self, section_name: str, cadence: typing.Optional[str] = "strong") -> None:

		"""Close every pass of a section with a cadence - the standing request.

		Each time *section_name* is entered, the clock registers a
		:meth:`request_cadence` arriving at the section's final bar, so the
		harmony approaches the close as the section ends.  Live harmony
		only: a section with bound chords (:meth:`section_chords`) is data
		and ignores the registration - its closes are written, not steered.
		Pass ``None`` to unregister.

		Example::

			composition.form([("verse", 8), ("chorus", 8)])
			composition.section_cadence("verse", "open")     # every verse hangs on V
			composition.section_cadence("chorus", "strong")  # every chorus lands home
		"""

		if cadence is None:
			self._section_cadences.pop(section_name, None)
			return

		spec = subsequence.cadences.cadence_formula(cadence)
		self._section_cadences[section_name] = spec.name

	def section_motifs (self, section_name: str, value: typing.Any, part: typing.Optional[str] = None) -> None:

		"""Bind a Motif or Phrase to a named form section (per optional part).

		Patterns read the binding back with ``p.section_motif(part)`` (or use
		the one-call :meth:`phrase_part`); a section with no binding for the
		part is silent for that part - bind material or don't, no fallback
		guessing.  Re-binding is idempotent, so the call is safe in a live
		file: re-executing on save is the desired rebind.

		Parameters:
			section_name: Name of the section as defined in :meth:`form`.
			value: A ``Motif`` or ``Phrase`` (anything exposing
				``.length``/``.slice`` places).
			part: Optional part label, so one section can carry several
				bindings (``"lead"``, ``"bass"``, ...).

		Raises:
			ValueError: If a graph-based form has been configured and
				*section_name* is not one of its sections.

		Example::

			composition.section_motifs("verse",  verse_line,  part="lead")
			composition.section_motifs("chorus", chorus_line, part="lead")
		"""

		if not hasattr(value, "length") or not hasattr(value, "slice"):
			raise TypeError(
				f"section_motifs() binds Motif/Phrase values (.length/.slice) - got {type(value).__name__}"
			)

		if (
			self._form_state is not None
			and self._form_state._section_bars is not None
			and section_name not in self._form_state._section_bars
		):
			known = ", ".join(sorted(self._form_state._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._section_motifs[(section_name, part)] = value

	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a sequencer event (e.g., "bar", "start", "stop").

		``"bar"`` passes the bar's index from 0.  ``"beat"`` passes the beat's
		index within its bar, counted in the time signature's unit: 0–3 in
		4/4, 0–5 in 6/8, 0–6 in 7/8.  That counter is the one place a beat is
		not a quarter note.
		"""

		self._sequencer.on_event(event_name, callback)


	# -----------------------------------------------------------------------
	# Hotkey API
	# -----------------------------------------------------------------------

	def hotkeys (self, enabled: bool = True) -> None:

		"""Enable or disable the global hotkey listener.

		Must be called **before** :meth:`play` to take effect.  When enabled, a
		background thread reads single keystrokes from stdin without requiring
		Enter.  The ``?`` key is always reserved and lists all active bindings.

		Hotkeys have zero impact on playback when disabled - the listener
		thread is never started.

		Args:
		    enabled: ``True`` (default) to enable hotkeys; ``False`` to disable.

		Example::

		    composition.hotkeys()
		    composition.hotkey("a", lambda: composition.form_jump("chorus"))
		    composition.play()
		"""

		self._hotkeys_enabled = enabled


	def hotkey (
		self,
		key:      str,
		action:   typing.Callable[[], None],
		quantize: int = 0,
		label:    typing.Optional[str] = None,
	) -> None:

		"""Register a single-key shortcut that fires during playback.

		The listener must be enabled first with :meth:`hotkeys`.

		Most actions - form jumps, ``composition.data`` writes, and
		:meth:`tweak` calls - should use ``quantize=0`` (the default).  Their
		musical effect is naturally delayed to the next pattern rebuild cycle,
		which provides automatic musical quantisation without extra configuration.

		Use ``quantize=N`` for actions where you want an explicit bar-boundary
		guarantee, such as :meth:`mute` / :meth:`unmute`.

		The ``?`` key is reserved and cannot be overridden.

		Args:
		    key: A single character trigger (e.g. ``"a"``, ``"1"``, ``" "``).
		    action: Zero-argument callable to execute.
		    quantize: ``0`` = execute immediately (default).  ``N`` = execute
		        on the next global bar number divisible by *N*.
		    label: Display name for the ``?`` help listing.  Auto-derived from
		        the function name or lambda body if omitted.

		Raises:
		    ValueError: If ``key`` is the reserved ``?`` character, or if
		        ``key`` is not exactly one character.

		Example::

		    composition.hotkeys()

		    # Immediate - musical effect happens at next pattern rebuild
		    composition.hotkey("a", lambda: composition.form_jump("chorus"))
		    composition.hotkey("1", lambda: composition.data.update({"mode": "chill"}))

		    # Explicit 4-bar phrase boundary
		    composition.hotkey("s", lambda: composition.mute("drums"), quantize=4)

		    # Named function - label is derived automatically
		    def drop_to_breakdown ():
		        composition.form_jump("breakdown")
		        composition.mute("lead")

		    composition.hotkey("d", drop_to_breakdown)

		    composition.play()
		"""

		if len(key) != 1:
			raise ValueError(f"hotkey key must be a single character, got {key!r}")

		if key == _HOTKEY_RESERVED:
			raise ValueError(f"'{_HOTKEY_RESERVED}' is reserved for listing active hotkeys.")

		derived = label if label is not None else _derive_label(action)

		self._hotkey_bindings[key] = HotkeyBinding(
			key      = key,
			action   = action,
			quantize = quantize,
			label    = derived,
		)


	def form_jump (self, section_name: str) -> None:

		"""Jump the form to a named section immediately.

		Delegates to :meth:`subsequence.form_state.FormState.jump_to`.  Works with a graph form (a dict
		passed to :meth:`form`), a list, or a :class:`~subsequence.forms.Form` -
		in list and ``Form`` modes the jump lands on the next occurrence of
		the name, searching forward and wrapping.  Only a generator form cannot
		be navigated.

		The musical effect is heard at the *next pattern rebuild cycle* - already-
		queued MIDI notes are unaffected.  This natural delay means ``form_jump``
		is effective without needing explicit quantisation.  During playback a
		jump is a section change like any other: ``on_section`` callbacks hear
		the section it lands on, and parts muted by ``transition()`` for the
		boundary it skipped play again.  A jump part-way
		through a bar gives the rest of that bar to the new section as its bar 0,
		so its first full bar is bar 1 - see
		:meth:`subsequence.form_state.FormState.jump_to` (#2484).

		Args:
		    section_name: The section to jump to.

		Raises:
		    ValueError: If no form is configured, or the form is a generator,
		        or *section_name* is unknown.

		Example::

		    composition.hotkey("c", lambda: composition.form_jump("chorus"))
		"""

		if self._form_state is None:
			raise ValueError("form_jump() requires a form to be configured via composition.form().")

		# The name is checked here, so the caller hears a bad one at once; the
		# jump itself is made on the clock's loop.  Made on another thread, it
		# could land inside the form's own advance() and be lost (#3382).
		self._form_state.check_navigable(section_name, "jump_to")
		self._sequencer._on_the_clock(self._jump, section_name)

	def _jump (self, section_name: str) -> None:

		"""Make a jump: on the clock's loop, or before it runs."""

		assert self._form_state is not None
		self._form_state.jump_to(section_name)

		# The harmony horizon planned against the old section — revoke it.
		self._harmony_horizon.invalidate_future()

		# A jump is a section change like any other (#2800): the approach mutes
		# for the boundary it skipped are lifted, and on_section hears the
		# section it landed on.  Before play() there is nothing to do: play()
		# announces the section it starts in.
		loop = self._sequencer._event_loop

		if loop is not None and loop.is_running() and self._sequencer.running:
			self._announce_jump()

	def _announce_jump (self) -> None:

		"""Treat a form jump as a section change: lift transition mutes, then tell on_section where it landed."""

		self._lift_transition_mutes()

		if self._form_state is not None:
			self._sequencer.events.emit_sync("section", self._form_state.get_section_info())


	def form_next (self, section_name: str) -> None:

		"""Queue the next section - takes effect when the current section ends.

		Unlike :meth:`form_jump`, this does not interrupt the current section.
		The queued section replaces the automatically pre-decided next section
		and takes effect at the natural section boundary.  The performer can
		change their mind by calling ``form_next`` again before the boundary.

		Delegates to :meth:`subsequence.form_state.FormState.queue_next`.  Works with a graph form (a dict
		passed to :meth:`form`), a list, or a :class:`~subsequence.forms.Form` -
		in list and ``Form`` modes the queued section lands on the next occurrence of
		the name, searching forward and wrapping.  Only a generator form cannot
		be navigated.

		Args:
		    section_name: The section to queue.

		Raises:
		    ValueError: If no form is configured, or the form is a generator,
		        or *section_name* is unknown.

		Example::

		    composition.hotkey("c", lambda: composition.form_next("chorus"))
		"""

		if self._form_state is None:
			raise ValueError("form_next() requires a form to be configured via composition.form().")

		# Checked here, made on the clock's loop, as a jump is (#3382).
		self._form_state.check_navigable(section_name, "queue_next")
		self._sequencer._on_the_clock(self._queue_next_section, section_name)

	def _queue_next_section (self, section_name: str) -> None:

		"""Queue a section: on the clock's loop, or before it runs."""

		assert self._form_state is not None
		self._form_state.queue_next(section_name)

		# The harmony horizon planned against the old continuation — revoke it.
		self._harmony_horizon.invalidate_future()


	def _list_hotkeys (self) -> None:

		"""Log all active hotkey bindings (triggered by the ``?`` key).

		Output appears via the standard logger so it scrolls cleanly above
		the :class:`~subsequence.display.Display` status line.
		"""

		lines = ["Active hotkeys:"]
		for key in sorted(self._hotkey_bindings):
			b = self._hotkey_bindings[key]
			quant_str = "immediate" if b.quantize == 0 else f"quantize={b.quantize}"
			lines.append(f"  {key}  \u2192  {b.label}  ({quant_str})")
		lines.append(f"  ?  \u2192  list hotkeys")
		logger.info("\n".join(lines))


	def _keys_arrived (self) -> None:

		"""Hand newly typed keys to the clock's loop, to be taken at once.

		The keystroke listener calls this on its own thread, so it only hands
		the work over.  Keys used to be taken on the bar event alone, so an
		immediate hotkey waited for the next bar line (#3480).  Before the
		sequencer has a loop there is nowhere to hand them: the first bar takes
		them instead.
		"""

		loop = self._sequencer._event_loop

		if loop is None:
			return

		try:
			loop.call_soon_threadsafe(self._take_typed_hotkeys)
		except RuntimeError:
			# The loop has closed: the piece is over, and so are its hotkeys.
			pass

	def _take_typed_hotkeys (self) -> None:

		"""Take the keys the listener has just announced - unless the piece has stopped.

		Runs on the clock's loop.  A key that arrives as the piece stops runs
		nothing, as it never could when only the bar event took keys.
		"""

		if self._sequencer.running:
			self._take_hotkeys()

	def _take_hotkeys (self) -> None:

		"""Take the keys typed since the last look: run immediate actions, queue quantised ones.

		Runs on the clock's loop, whether as keys arrive or on a bar, so every
		action runs where it is safe for all mutation methods: the keystroke
		listener's thread only queues keypresses (``drain()``), it never runs
		actions.
		"""

		if self._keystroke_listener is None:
			return

		for key in self._keystroke_listener.drain():

			if key == _HOTKEY_RESERVED:
				self._list_hotkeys()
				continue

			binding = self._hotkey_bindings.get(key)
			if binding is None:
				continue

			if binding.quantize == 0:
				# Immediate: execute now.
				try:
					binding.action()
					logger.info(f"Hotkey '{key}' \u2192 {binding.label}")
				except Exception as exc:
					logger.warning(f"Hotkey '{key}' action raised: {exc}")
			else:
				# Defer until the next quantize boundary.
				self._pending_hotkey_actions.append(
					_PendingHotkeyAction(binding=binding)
				)

	def _process_hotkeys (self, bar: int) -> None:

		"""Take any keys still waiting, then run the quantised actions whose bar has come.

		Called on every ``"bar"`` event by the sequencer when hotkeys are
		enabled.  Keys are taken as they arrive (:meth:`_take_hotkeys`); this
		takes any the listener's wake-up did not reach, and it is where a
		quantised action waits for its boundary.

		Args:
		    bar: The current global bar number from the sequencer.
		"""

		if self._keystroke_listener is None:
			return

		self._take_hotkeys()

		# Fire any pending actions whose bar boundary has arrived.
		still_pending: typing.List[_PendingHotkeyAction] = []

		for pending in self._pending_hotkey_actions:
			if bar % pending.binding.quantize == 0:
				try:
					pending.binding.action()
					logger.info(
						f"Hotkey '{pending.binding.key}' \u2192 {pending.binding.label} "
						f"(bar {bar})"
					)
				except Exception as exc:
					logger.warning(
						f"Hotkey '{pending.binding.key}' action raised: {exc}"
					)
			else:
				still_pending.append(pending)

		self._pending_hotkey_actions = still_pending

	@property
	def seed (self) -> typing.Optional[int]:

		"""
		The composition's random seed, or None when unseeded.

		When set, every random decision derives deterministically from this
		value through named streams (see ``seed_for()``), so the same script
		produces the same music on every run.  Assign to set it::

			comp.seed = 42

		(Formerly the method ``comp.seed(42)`` - the call form is a hard
		break per the pre-1.0 rename policy.)
		"""

		return self._seed

	@seed.setter
	def seed (self, value: typing.Optional[int]) -> None:

		"""Set the composition seed (``comp.seed = 42``).

		Warns when something has already dealt its stream.  ``harmony()``,
		``form()`` and ``freeze()`` draw at the moment they are called, so a
		seed set after one of them never reaches it - and the piece is then
		reproducible in some parts and not in others, which is worse than
		either.  Nothing can be un-drawn, so the honest answer is to say so
		rather than to appear to work.
		"""

		already_dealt = [
			name
			for name, count in (
				("harmony()", self._harmony_count),
				("form()",    self._form_count),
				("freeze()",  self._freeze_count),
			)
			if count
		]

		if value is not None and already_dealt:
			logger.warning(
				"seed set after %s - those have already dealt their streams and will not "
				"follow it. Pass seed= to Composition(...) for a piece that renders the "
				"same twice.",
				", ".join(already_dealt),
			)

		self._seed = value

	def _stream_seed (self, name: str) -> typing.Optional[int]:

		"""
		Derive the effective integer seed for a named random stream.

		The derivation is ``zlib.crc32(f"{seed}:{name}")`` - crc32 rather
		than ``hash()`` because it is stable across processes - plus the
		per-name nonce when ``reroll()`` has been called.  A seed given back
		with ``reroll(name, seed=)`` takes the place of all of that, seeded
		composition or not.  Otherwise returns None when the composition is
		unseeded.
		"""

		given = self._given_seeds.get(name)

		if given is not None:
			return given

		if self._seed is None:
			return None

		nonce = self._reroll_nonces.get(name, 0)
		key = f"{self._seed}:{name}" if nonce == 0 else f"{self._seed}:{name}:{nonce}"
		return zlib.crc32(key.encode())

	def _stream (self, name: str) -> typing.Optional[random.Random]:

		"""A fresh ``random.Random`` for a named stream, or None when unseeded."""

		stream_seed = self._stream_seed(name)
		return None if stream_seed is None else random.Random(stream_seed)

	def seed_for (self, name: str) -> typing.Optional[int]:

		"""
		Surface the effective derived seed for a named stream.

		Works for pattern names and equally for any name you invent for a
		standalone value generator (``seed=composition.seed_for("hook")``),
		so its randomness keys off the composition seed without sharing any
		other consumer's stream.  Reflects ``reroll()``, including a seed
		given back with ``seed=``.  Returns None when the composition is
		unseeded and the stream was given no seed.

		Example:
			```python
			hook_seed = composition.seed_for("hook")
			```
		"""

		return self._stream_seed(name)

	def reroll (self, name: str, seed: typing.Optional[int] = None) -> None:

		"""
		Deal a named stream a fresh deterministic seed to try a new variation,
		or give it back one you noted.

		Prints the stream's new effective seed.  A variation you like survives
		a restart either way round: keep the ``reroll()`` calls in your
		script, which deal the same seeds in the same order on every run, or
		pass the printed seed back with ``seed=``, which gives the stream
		exactly that seed until the next plain ``reroll(name)``.  ``lock()``
		pins a stream for the session.  Refuses on locked names.

		Parameters:
			name: The stream name - usually a pattern name.
			seed: A seed ``reroll()`` printed, to bring that variation back.

		Example:
			```python
			comp.reroll("lead")                   # prints: reroll('lead') -> effective seed 2994986849 ...
			comp.reroll("lead", seed=2994986849)  # that variation again, on any run
			```
		"""

		if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
			raise TypeError(f"reroll() seed must be a whole number, like the one reroll() printed - got {seed!r}")

		if name in self._locked_names:
			print(f"reroll('{name}') refused: '{name}' is locked - call unlock('{name}') first")
			return

		if seed is not None:
			self._given_seeds[name] = seed
			self._reseat(name, seed)
			print(f"reroll('{name}', seed={seed}) -> effective seed {seed}")
			return

		self._given_seeds.pop(name, None)
		self._reroll_nonces[name] = self._reroll_nonces.get(name, 0) + 1
		effective = self._stream_seed(name)

		if effective is None:
			print(f"reroll('{name}'): composition has no seed - randomness is unseeded")
			return

		self._reseat(name, effective)
		print(f"reroll('{name}') -> effective seed {effective} (nonce {self._reroll_nonces[name]})")

	def _reseat (self, name: str, seed: int) -> None:

		"""Give a running pattern of this name a stream dealt from *seed*."""

		running = self._running_patterns.get(name)

		if running is not None and hasattr(running, "_rng"):
			running._rng = random.Random(seed)

	def lock (self, name: str) -> None:

		"""
		Pin a named stream: keep its current effective seed and realisation.

		Engine-side state, so it survives live reload (it is never a builder
		swap): a locked pattern re-deals its stream from the same effective
		seed on every rebuild, so every cycle realises identically, and
		``reroll()`` refuses with a message until ``unlock()``.

		Parameters:
			name: The stream name - usually a pattern name.
		"""

		self._locked_names.add(name)

	def unlock (self, name: str) -> None:

		"""Release a ``lock()``: the stream runs free and ``reroll()`` works again."""

		self._locked_names.discard(name)

	def tuning (
		self,
		source: typing.Optional[typing.Union[str, "os.PathLike"]] = None,
		*,
		cents: typing.Optional[typing.List[float]] = None,
		ratios: typing.Optional[typing.List[float]] = None,
		equal: typing.Optional[int] = None,
		bend_range: float = 2.0,
		channels: typing.Optional[typing.List[int]] = None,
		reference_note: int = 60,
		exclude_drums: bool = True,
	) -> None:

		"""Set a global microtonal tuning for the composition.

		The tuning is applied automatically after each pattern rebuild (before
		the pattern is scheduled), and to every ``trigger()`` one-shot and
		transition fill as it is built.  Drum patterns (those registered with a
		``drum_note_map``) are excluded by default.

		Supply exactly one of the source parameters:

		- ``source``: path to a Scala ``.scl`` file.
		- ``cents``: list of cent offsets for degrees 1..N (degree 0 = 0.0 is implicit).
		- ``ratios``: list of frequency ratios for degrees 1..N, the last one
		  the octave (e.g., ``[16/15, 9/8, 6/5, 5/4, ..., 15/8, 2]``).
		- ``equal``: integer for N-tone equal temperament (e.g., ``equal=19``).

		A MIDI note plays the degree it lands on, counting up from
		``reference_note``.  With twelve degrees each note keeps its name, so
		ordinary music is retuned note for note: under the just table below,
		E is 14 cents flat and G 2 cents sharp.  With fewer, consecutive notes
		step through the scale - under a seven-degree table MIDI 60, 61 and 62
		play its first three degrees, C, D and E - so write such a part in
		degrees, one MIDI number to each (#3474).

		For polyphonic parts, supply a ``channels`` pool.  Notes are spread
		across those MIDI channels so each can carry an independent pitch bend.
		The synth must be configured to match ``bend_range`` (its pitch-bend range
		setting in semitones).

		Only a part whose notes overlap plays through the pool.  A part that
		plays one note at a time keeps its own MIDI channel, and its own pitch
		wheel.  Once a part has played overlapping notes through the pool it
		stays there, so a bar where it plays a single note sits on the pool's
		first MIDI channel rather than moving its instrument.  Two parts that both
		need the pool would retune each other, so
		that is warned about, naming them; give one of them a pool of its own
		with ``p.apply_tuning(channels=...)``.

		Parameters:
			source: Path to a ``.scl`` file.
			cents: Cent offsets for scale degrees 1..N.
			ratios: Frequency ratios for scale degrees 1..N.
			equal: Number of equal divisions of the period.
			bend_range: Synth pitch-bend range in semitones (default ±2).
			channels: MIDI channel pool for polyphonic rotation, numbered like every
			    other MIDI channel: 1-16, or 0-15 with ``zero_indexed_channels=True``.
			reference_note: MIDI note mapped to scale degree 0 (default 60 = C4).
			exclude_drums: When True (default), skip patterns that have a
			    ``drum_note_map`` (they use fixed GM pitches, not tuned ones).

		Example:
			```python
			# Quarter-comma meantone from a Scala file
			comp.tuning("meanquar.scl")

			# Just intonation in C: each of the twelve notes at its just ratio
			comp.tuning(ratios=[16/15, 9/8, 6/5, 5/4, 4/3, 45/32, 3/2, 8/5, 5/3, 9/5, 15/8, 2])

			# A seven-degree just scale: consecutive notes step through it
			comp.tuning(ratios=[9/8, 5/4, 4/3, 3/2, 5/3, 15/8, 2])

			# 19-TET, monophonic
			comp.tuning(equal=19, bend_range=2.0)

			# 31-TET with channel rotation for polyphony
			comp.tuning("31tet.scl", channels=[1, 2, 3, 4, 5, 6])
			```
		"""
		import subsequence.tuning as _tuning_mod

		given = sum(x is not None for x in [source, cents, ratios, equal])
		if given == 0:
			raise ValueError("composition.tuning() requires one of: source, cents, ratios, or equal")
		if given > 1:
			raise ValueError("composition.tuning() accepts only one source parameter")

		if source is not None:
			t = _tuning_mod.Tuning.from_scl(source)
		elif cents is not None:
			t = _tuning_mod.Tuning.from_cents(cents)
		elif ratios is not None:
			t = _tuning_mod.Tuning.from_ratios(ratios)
		else:
			t = _tuning_mod.Tuning.equal(equal)  # type: ignore[arg-type]

		# Read the pool now, so a channel it cannot be is refused on this line.
		pool = None if channels is None else _tuning_mod.resolve_channel_pool(channels, zero_indexed=self._zero_indexed_channels)

		self._tuning = t
		self._tuning_bend_range = bend_range
		self._tuning_channels = pool
		self._tuning_pool_parts = []
		self._tuning_pool_named = set()
		self._tuning_reference_note = reference_note
		self._tuning_exclude_drums = exclude_drums

	def _apply_composition_tuning (
		self,
		pattern: subsequence.pattern.Pattern,
		builder: subsequence.pattern_builder.PatternBuilder,
		drum_note_map: typing.Optional[typing.Dict[str, int]],
		part: typing.Optional[str],
	) -> None:

		"""Tune a pattern just built with the composition's tuning, whichever way it was built (#2926).

		Nothing happens when the composition has no tuning, when the builder
		tuned the pattern itself with ``p.apply_tuning()``, or for a drum map
		while ``exclude_drums`` holds.  ``part`` names a repeating pattern: once
		its notes rotate through the pool it joins it, stays on it (#2925), and
		is named if it shares it (#2798).  A one-shot, from ``trigger()`` or a
		transition fill, passes ``None``: its chord still rotates through the
		pool and its single note keeps its channel, but it neither joins the
		pool nor is named.
		"""

		if self._tuning is None or builder._tuning_applied:
			return

		if self._tuning_exclude_drums and drum_note_map:
			return

		import subsequence.tuning as _tuning_mod

		rotated = _tuning_mod.apply_tuning_to_pattern(
			pattern,
			self._tuning,
			bend_range = self._tuning_bend_range,
			channels = self._tuning_channels,
			reference_note = self._tuning_reference_note,
			# A part that has played chords through the pool stays on it, so a
			# bar of single notes does not move its instrument (#2925).
			shared_pool = part is None or part not in self._tuning_pool_parts,
		)

		if rotated and part is not None:
			self._join_tuning_pool(part)

	def _join_tuning_pool (self, name: str) -> None:

		"""A part's overlapping notes rotated through the composition's pool: name whatever it would retune (#2798).

		Two parts rotating through one pool share its pitch wheels, and so
		does any part playing on a channel inside the pool.  Each is named
		once.  Parts are listed once playback has begun, so a part sitting on
		a pool channel is named from the rotating part's second cycle.
		"""

		pool = self._tuning_channels or []
		shown = [channel if self._zero_indexed_channels else channel + 1 for channel in pool]

		if name not in self._tuning_pool_parts:
			self._tuning_pool_parts.append(name)

			if len(self._tuning_pool_parts) > 1:
				names = [f"'{part}'" for part in self._tuning_pool_parts]
				parts = ", ".join(names[:-1]) + " and " + names[-1]
				logger.warning(
					f"Parts {parts} play overlapping notes through the tuning's channel pool {shown}, so they share its "
					f"pitch wheels and retune each other. Give each its own pool with p.apply_tuning(channels=...)."
				)

		for other_name, other in self._running_patterns.items():

			if other_name in self._tuning_pool_parts or other_name in self._tuning_pool_named or other.channel not in pool:
				continue

			self._tuning_pool_named.add(other_name)
			channel = other.channel if self._zero_indexed_channels else other.channel + 1
			logger.warning(
				f"Part '{other_name}' plays on channel {channel}, inside the tuning's channel pool {shown} that '{name}' "
				f"plays its overlapping notes through, so the pool's pitch bends retune it. Move it to a channel outside the pool."
			)

	def display (self, enabled: bool = True, grid: bool = False, grid_scale: float = 1.0) -> None:

		"""
		Enable or disable the live terminal dashboard.

		When enabled, Subsequence uses a safe logging handler that allows a
		persistent status line (BPM, Key, Bar, Section, Chord) to stay at
		the bottom of the terminal while logs scroll above it.

		Parameters:
			enabled: Whether to show the display (default True).
			grid: When True, render an ASCII grid visualisation of all
				running patterns above the status line. The grid updates
				once per bar, showing which steps have notes and at what
				velocity.
			grid_scale: Horizontal zoom factor for the grid (default
				``1.0``).  Higher values add visual columns between
				grid steps, revealing micro-timing from swing and groove.
				Snapped to the nearest integer internally for uniform
				marker spacing.
		"""

		if enabled:
			self._display = subsequence.display.Display(self, grid=grid, grid_scale=grid_scale)
		else:
			self._display = None

	def midi_input (self, device: str, clock_follow: bool = False, name: typing.Optional[str] = None) -> None:

		"""
		Configure a MIDI input device for external sync and MIDI messages.

		May be called multiple times to register additional input devices.
		The first call sets the primary input (device 0).  Subsequent calls
		add additional input devices (device 1, 2, …).  Only one device may
		have ``clock_follow=True``.

		Parameters:
			device: Which MIDI input port to use, matched against
				``mido.get_input_names()``.  Treated as a pattern - ``*``
				and ``?`` are wildcards, matching is case-insensitive, and a
				name without wildcards is a substring.  See
				``Composition.__init__`` for why a pattern like
				``"*Launchpad *:0"`` survives an ALSA client id changing
				between runs.  Because a wrong input would desynchronise or
				mis-record a performance, a pattern matching nothing raises,
				and one matching several asks which you meant rather than
				guessing.
			clock_follow: If True, Subsequence will slave its clock to incoming
				MIDI Ticks. It will also follow MIDI Start/Stop/Continue
				commands. Only one device can have this enabled at a time.
			name: Optional alias for use with ``cc_map(input_device=…)`` and
				``cc_forward(input_device=…)``.  When omitted, the raw device
				name is used.

		Example:
			```python
			# Single controller (unchanged usage)
			comp.midi_input("Scarlett 2i4", clock_follow=True)

			# Multiple controllers
			comp.midi_input("Arturia KeyStep", name="keys")
			comp.midi_input("Faderfox EC4", name="faders")
			```
		"""

		if clock_follow:
			if self.is_clock_following:
				raise ValueError("Only one input device can be configured to follow external clock (clock_follow=True)")

		if self._input_device is None:
			# First call: set primary input device (device 0)
			self._input_device = device
			self._input_device_alias = name
			self._clock_follow = clock_follow
		else:
			# Subsequent calls: register additional input devices
			self._additional_inputs.append((device, name, clock_follow))

	def midi_output (self, device: str, name: typing.Optional[str] = None, latency_ms: float = 0.0) -> int:

		"""
		Register an additional MIDI output device.

		The first output device is always the one passed to
		``Composition(output_device=…)`` - that is device 0.
		Each call to ``midi_output()`` adds the next device (1, 2, …).

		Parameters:
			device: Which MIDI output port to add, matched against
				``mido.get_output_names()``.  Treated as a pattern -
				``*`` and ``?`` are wildcards, matching is
				case-insensitive, and a name without wildcards is a
				substring.  See ``Composition.__init__`` for the lookup
				snippet and why a pattern like ``"*U6MIDI Pro *:0"``
				survives an ALSA client id changing between runs.
			name: Optional alias for use with ``pattern(device=…)``,
				``cc_forward(output_device=…)``, etc.  When omitted, the raw
				device name is used.
			latency_ms: Physical output latency of this device in
				milliseconds, for delay compensation (default 0.0, must be
				non-negative). Set this when the device sounds late (e.g. a
				software sampler) so Subsequence delays faster devices to
				line everything up.

		Returns:
			The integer device index assigned (1, 2, 3, …).

		Example:
			```python
			comp = subsequence.Composition(bpm=120, output_device="MOTU Express")

			# Returns 1 - use as device=1 or device="integra"
			comp.midi_output("Roland Integra", name="integra")

			# A software sampler that sounds 20ms late
			comp.midi_output("Subsample", name="sampler", latency_ms=20)

			@comp.pattern(channel=1, beats=4, device="integra")
			def strings (p):
				p.note(60, beat=0)
			```
		"""

		if latency_ms < 0:
			raise ValueError(f"latency_ms must be non-negative - got {latency_ms}")

		idx = 1 + len(self._additional_outputs)  # device 0 is always the primary
		self._additional_outputs.append(_AdditionalOutput(device=device, alias=name, latency_ms=latency_ms))
		return idx

	def _warn_if_high_latency (self) -> None:

		"""Warn if delay compensation adds a large whole-rig latency.

		The slowest device defines the alignment point - every faster device is
		delayed up to that amount - so a large maximum means the whole rig
		responds late to live input.  Emitted once at startup.
		"""

		candidates: typing.List[typing.Tuple[str, float]] = [("primary output", self._output_latency_ms)]
		candidates += [(out.alias or out.device, out.latency_ms) for out in self._additional_outputs]

		slow_name, max_ms = max(candidates, key=lambda c: c[1])

		if max_ms > _LATENCY_WARN_THRESHOLD_MS:
			logger.warning(
				"Device latency compensation: '%s' is the slowest at %.0fms, so faster "
				"devices are delayed up to %.0fms to stay aligned - live-input feel may suffer.",
				slow_name, max_ms, max_ms,
			)

	def clock_output (self, enabled: bool = True) -> None:

		"""
		Send MIDI timing clock to connected hardware.

		When enabled, Subsequence acts as a MIDI clock master and sends
		standard clock messages on the output port: a Start message (0xFA)
		when playback begins, a Clock tick (0xF8) on every pulse (24 PPQN),
		and a Stop message (0xFC) when playback ends.

		This allows hardware synthesisers, drum machines, and effect units to
		slave their tempo to Subsequence automatically.

		**Note:** Clock output is automatically disabled when ``midi_input()``
		is called with ``clock_follow=True``, to prevent a clock feedback loop.

		Parameters:
			enabled: Whether to send MIDI clock (default True).

		Example:
			```python
			comp = subsequence.Composition(bpm=120, output_device="...")
			comp.clock_output()   # hardware will follow Subsequence tempo
			```
		"""

		self._clock_output = enabled


	def link (self, quantum: typing.Optional[float] = None) -> "Composition":

		"""
		Enable Ableton Link tempo and phase synchronisation.

		When enabled, Subsequence joins the local Link session and slaves its
		clock to the shared network tempo and beat phase.  All other Link-enabled
		apps on the same LAN - Ableton Live, iOS synths, other Subsequence
		instances - will automatically stay in time.

		Playback starts on the next bar boundary aligned to the Link quantum,
		so downbeats stay in sync across all participants.

		Requires the ``link`` optional extra:

		```shell
		pip install subsequence[link]
		```

		Parameters:
			quantum: Beat cycle length in quarter notes.  Defaults to one bar
			         (``composition.bar_beats``), so peers align on bar lines
			         in any metre: 4.0 in 4/4, 3.5 in 7/8.

		Example::

		    comp = subsequence.Composition(bpm=120, key="C")
		    comp.link()          # join the Link session
		    comp.play()

		    # On another machine / instance:
		    comp2 = subsequence.Composition(bpm=120)
		    comp2.link()         # tempo and phase will lock to comp
		    comp2.play()

		Note:
		    ``set_bpm()`` proposes the new tempo to the Link network when Link
		    is active.  The network-authoritative tempo is applied on the next
		    pulse, so there may be a brief lag before the change is visible.
		"""

		# Eagerly check that aalink is installed — fail early with a clear message.
		subsequence.link_clock._require_aalink()

		self._link_quantum = float(quantum) if quantum is not None else self.bar_beats
		return self


	def cc_map (
		self,
		cc: int,
		data_key: str,
		channel: typing.Optional[int] = None,
		min_val: float = 0.0,
		max_val: float = 1.0,
		input_device: subsequence.midi_utils.DeviceId = None,
	) -> None:

		"""
		Map an incoming MIDI CC to a ``composition.data`` key.

		When the composition receives a CC message on the configured MIDI
		input port, the value is scaled from the CC range (0–127) to
		*[min_val, max_val]* and stored in ``composition.data[data_key]``.

		This lets hardware knobs, faders, and expression pedals control live
		parameters without writing any callback code.

		**Requires** ``midi_input()`` to be called first to open an input port.

		Parameters:
			cc: MIDI Control Change number (0–127).
			data_key: The ``composition.data`` key to write.
			channel: If given, only respond to CC messages on this MIDI channel.
				Uses the same numbering convention as ``pattern()`` (1-16
				by default, or 0-15 with ``zero_indexed_channels=True``).
				``None`` matches any MIDI channel (default).
			min_val: Scaled minimum - written when CC value is 0 (default 0.0).
			max_val: Scaled maximum - written when CC value is 127 (default 1.0).
			input_device: Only respond to CC messages from this input device
				(index or name).  ``None`` responds to any input device (default).

		Example:
			```python
			comp.midi_input("Arturia KeyStep")
			comp.cc_map(74, "filter_cutoff")           # knob → 0.0–1.0
			comp.cc_map(7, "volume", min_val=0, max_val=127)  # volume fader

			# Multi-device: only listen to CC 74 from the "faders" controller
			comp.cc_map(74, "filter", input_device="faders")
			```
		"""

		resolved_channel = self._resolve_channel(channel) if channel is not None else None

		self._cc_mappings.append({
			'cc': cc,
			'data_key': data_key,
			'channel': resolved_channel,
			'min_val': min_val,
			'max_val': max_val,
			'input_device': input_device,  # resolved to int index in _run()
		})


	def note_input (
		self,
		channel: typing.Optional[int] = None,
		release_ms: float = 30.0,
		latch: bool = False,
		input_device: subsequence.midi_utils.DeviceId = None,
	) -> None:

		"""Track notes held on a MIDI keyboard for live arpeggiation.

		Incoming note-on/note-off messages build a live "currently held" set
		that any pattern reads via ``p.held_notes()`` - typically fed straight
		to ``p.arpeggio()``.  The composition still authors the rhythm and
		motion; the player's hands supply the pitch set.  This is a live
		*performance* layer over the deterministic, seeded composition: when
		rendering headlessly there is no input, so ``p.held_notes()`` is empty
		and seeded output is unchanged.

		**Requires** ``midi_input()`` to be called first to open an input port.

		Parameters:
			channel: If given, only track notes on this MIDI channel.  Uses the same
				numbering convention as ``pattern()`` (1-16 by default, or 0-15
				with ``zero_indexed_channels=True``).  ``None`` tracks any
				MIDI channel (default).
			release_ms: How long (milliseconds) a released note keeps counting
				as held.  This smooths the momentary all-keys-up gap during a
				hand-position change so the arp does not drop to silence.
				Default 30.0; set 0.0 to release instantly.  Ignored when
				``latch`` is True.
			latch: When True, the held set persists after you lift your hands
				until you play a new chord (the first key after every key is up
				replaces it) - like a hardware arp's latch.
			input_device: Only track notes from this input device (index or
				name).  ``None`` tracks any input device (default).

		Example:
			```python
			comp.midi_input("Arturia KeyStep")
			comp.note_input(channel=1, release_ms=30)

			@comp.pattern(channel=6, beats=4)
			def arp (p):
			    p.arpeggio(p.held_notes(), direction="forward")  # rests when silent
			```
		"""

		if self._note_input is not None:
			raise RuntimeError("only one note_input source is supported - named multi-source is not yet available")

		resolved_channel = self._resolve_channel(channel) if channel is not None else None

		self._note_input = {
			'channel': resolved_channel,
			'release_ms': release_ms,
			'latch': latch,
			'input_device': input_device,  # resolved to int index in _run()
		}


	@staticmethod
	def _make_cc_forward_transform (
		output: typing.Union[str, typing.Callable],
		cc: int,
		output_channel: typing.Optional[int],
	) -> typing.Callable:

		"""Build a transform callable from a preset string or user-supplied callable.

		The returned callable has signature ``(value: int, channel: int) -> Optional[mido.Message]``
		where ``channel`` is the 0-indexed incoming channel.
		"""

		import mido as _mido

		def _out_ch (incoming: int) -> int:
			return output_channel if output_channel is not None else incoming

		if callable(output):
			if output_channel is None:
				return output
			def _wrapped (value: int, channel: int) -> typing.Optional[typing.Any]:
				msg = output(value, channel)

				if msg is None:
					return None

				# copy() re-channels without rebuilding: reconstructing from
				# __dict__ passed 'type' twice and raised TypeError on every
				# message, so callable+output_channel never forwarded anything.
				return msg.copy(channel=output_channel)
			return _wrapped

		if output == 'cc':
			def _cc_identity (value: int, channel: int) -> typing.Any:
				return _mido.Message('control_change', channel=_out_ch(channel), control=cc, value=value)
			return _cc_identity

		if output.startswith('cc:'):
			try:
				target_cc = int(output[3:])
			except ValueError:
				raise ValueError(f"cc_forward(): invalid preset '{output}' - expected 'cc:N' where N is 0–127")
			if not 0 <= target_cc <= 127:
				raise ValueError(f"cc_forward(): CC number {target_cc} out of range 0–127")
			def _cc_remap (value: int, channel: int) -> typing.Any:
				return _mido.Message('control_change', channel=_out_ch(channel), control=target_cc, value=value)
			return _cc_remap

		if output == 'pitchwheel':
			def _pitchwheel (value: int, channel: int) -> typing.Any:
				pitch = int(value / 127 * 16383) - 8192
				return _mido.Message('pitchwheel', channel=_out_ch(channel), pitch=pitch)
			return _pitchwheel

		raise ValueError(
			f"cc_forward(): unknown preset '{output}'. "
			"Use 'cc', 'cc:N' (e.g. 'cc:74'), 'pitchwheel', or a callable."
		)


	def cc_forward (
		self,
		cc: int,
		output: typing.Union[str, typing.Callable],
		*,
		channel: typing.Optional[int] = None,
		output_channel: typing.Optional[int] = None,
		mode: str = "instant",
		input_device: subsequence.midi_utils.DeviceId = None,
		output_device: subsequence.midi_utils.DeviceId = None,
	) -> None:

		"""
		Forward an incoming MIDI CC to the MIDI output in real-time.

		Unlike ``cc_map()`` which writes incoming CC values to ``composition.data``
		for use at pattern rebuild time, ``cc_forward()`` routes the signal
		directly to the MIDI output - bypassing the pattern cycle entirely.

		Both ``cc_map()`` and ``cc_forward()`` may be registered for the same CC
		number; they operate independently.

		Parameters:
			cc: Incoming CC number to listen for (0–127).
			output: What to send. Either a **preset string**:

				- ``"cc"`` - identity forward, same CC number and value.
				- ``"cc:N"`` - forward as CC number N (e.g. ``"cc:74"``).
				- ``"pitchwheel"`` - scale 0–127 to -8192..8191 and send as pitch bend.

				Or a **callable** with signature
				``(value: int, channel: int) -> Optional[mido.Message]``.
				Return a fully formed ``mido.Message`` to send, or ``None`` to suppress.
				``channel`` is 0-indexed (the incoming MIDI channel).
			channel: If given, only respond to CC messages on this MIDI channel.
				Uses the same numbering convention as ``cc_map()``.
				``None`` matches any MIDI channel (default).
			output_channel: Override the output MIDI channel. ``None`` uses the
				incoming MIDI channel. Uses the same numbering convention as ``pattern()``.
			input_device: Only respond to CC from this input device - an index,
				a registered name, or ``None`` for any input (default), the
				same convention as ``cc_map()``.
			output_device: Send to this output device - an index, a registered
				name, or ``None`` for the primary output (default).
			mode: Dispatch mode:

				- ``"instant"`` *(default)* - send immediately on the MIDI input
				  callback thread. Lowest latency (~1–5 ms). Instant forwards are
				  **not** recorded when recording is enabled.
				- ``"queued"`` - inject into the sequencer event queue and send at
				  the next pulse boundary (~0–20 ms at 120 BPM). Queued forwards
				  **are** recorded when recording is enabled.

		Example:
			```python
			comp.midi_input("Arturia KeyStep")

			# CC 1 → CC 1 (identity, instant)
			comp.cc_forward(1, "cc")

			# CC 1 → pitch bend on channel 1, queued (recordable)
			comp.cc_forward(1, "pitchwheel", output_channel=1, mode="queued")

			# CC 1 → CC 74, custom channel
			comp.cc_forward(1, "cc:74", output_channel=2)

			# Custom transform - remap CC range 0–127 to CC 74 range 40–100
			import subsequence.midi as midi
			comp.cc_forward(1, lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch))

			# Forward AND map to data simultaneously - both active on the same CC
			comp.cc_map(1, "mod_wheel")
			comp.cc_forward(1, "cc:74")
			```
		"""

		if not 0 <= cc <= 127:
			raise ValueError(f"cc_forward(): cc {cc} out of range 0–127")

		if mode not in ('instant', 'queued'):
			raise ValueError(f"cc_forward(): mode must be 'instant' or 'queued', got '{mode}'")

		resolved_in_channel = self._resolve_channel(channel) if channel is not None else None
		resolved_out_channel = self._resolve_channel(output_channel) if output_channel is not None else None

		transform = self._make_cc_forward_transform(output, cc, resolved_out_channel)

		self._cc_forwards.append({
			'cc': cc,
			'channel': resolved_in_channel,
			'output_channel': resolved_out_channel,
			'mode': mode,
			'transform': transform,
			'input_device': input_device,   # resolved to int index in _run()
			'output_device': output_device, # resolved to int index in _run()
		})


	def live (self, port: int = 5555) -> None:

		"""
		Enable the live coding eval server.

		This allows you to connect to a running composition using the
		``subsequence.live_client`` REPL and hot-swap pattern code or
		modify variables in real-time.

		What you type is a declaration, and the piece takes it as one.  A new
		``@composition.pattern`` comes in at the next whole multiple of its own
		length, so a one-bar part lands on a bar line and a four-bar part on a
		four-bar line, however the typing fell.  Re-declaring a part that is
		already playing swaps its body in without disturbing its cycle count,
		its tweaks or its mirrors.  What you add this way is yours: a save of a
		watched file removes only what that file stopped declaring, and
		``unregister()`` is how you take a typed part out again.

		Security:
			The server executes arbitrary Python in this process - it is **not** a
			sandbox.  It binds to localhost only and is opt-in, but any process on
			the same machine that can reach the port gains full code execution here.
			Do not enable it on shared or multi-user hosts, and never expose the
			port to a network.

		Parameters:
			port: The TCP port to listen on (default 5555).
		"""

		self._live_server = subsequence.live_server.LiveServer(self, port=port)
		self._is_live = True

	def watch (self, path: typing.Union[str, pathlib.Path], poll_interval: float = 0.25) -> None:

		"""Watch a Python file and reload it into the composition on every save.

		The watched file is exec'd into a namespace with ``composition`` and
		``subsequence`` available.  ``@composition.pattern`` decorators inside
		the file hot-swap their corresponding running patterns in place;
		patterns whose function bodies have been deleted from the file are
		unregistered automatically on the next reload (notes stopped,
		removed from the running-pattern set).

		An **initial synchronous load** happens here - if the file has a
		``SyntaxError`` or doesn't exist at this moment, the exception
		propagates so the user knows immediately.  Subsequent reloads
		happen on the composition's event loop and tolerate transient
		errors (logged, skipped).

		Call BEFORE ``composition.play()``.  Reloads happen on the
		composition's event loop, so all mutations are thread-safe.

		The watched file runs in a fresh namespace on every save, holding only
		``composition`` and ``subsequence``: a name defined in the script that
		calls ``watch()`` cannot be seen there, and whatever the file creates at
		its top level is created again.  State that must outlive a save goes on
		``composition.data``, set up once before ``watch()`` and read back in the
		watched file.  One-time setup (devices, ``harmony()``, ``form()``) belongs
		in that calling script too, or every save runs it again.

		A save replaces a running pattern's body, and any decorator argument
		the save changed (``channel``, ``beats``/``bars``,
		``reschedule_lookahead``, ``min_energy``, ``mirrors``, the maps), all
		heard from its next cycle.  An argument the save left alone keeps what
		the performance did to it, such as a ``mirror()``.  ``device`` is the
		exception, because opening a port while the clock runs would be heard:
		a pattern moves to a new device when the composition restarts.

		A part the save *adds* comes in on the next whole multiple of its own
		length - a one-bar part on the next bar, a four-bar part on the next
		four-bar line - so it sits on the grid however the timing of the save
		fell, and stays there.

		Parameters:
			path: Path to the Python file to watch.
			poll_interval: Seconds between looks at the file (default 0.25 s).
				A save is applied once it has held still for one of them, so
				one caught half-written is never taken for the new version.

		Example::

			# live_init.py - runs once
			composition = subsequence.Composition(bpm=120, key="E")
			composition.harmony(style="aeolian_minor")
			composition.watch("live_patterns.py")
			composition.play()
		"""

		# Required for the decorator hot-swap path to fire on re-decoration.
		self._is_live = True

		# Detect the single-file workflow: if watch() is called from inside
		# the very file being watched, the outer Python script execution will
		# already register the patterns (the decorators sit at module level
		# below ``watch(__file__)``).  In that case, _load_initial's re-exec
		# would double-register every pattern, so skip it.  For the two-file
		# workflow (path != caller's __file__) the initial exec is essential
		# — it's the only way the watched file's patterns ever reach the
		# composition.
		caller_file = self._caller_module_file()
		self_watch = False
		if caller_file is not None:
			try:
				self_watch = pathlib.Path(caller_file).resolve() == pathlib.Path(path).resolve()
			except OSError:
				self_watch = False

		self._live_reloader = subsequence.live_reloader.LiveReloader(
			composition = self,
			path = path,
			poll_interval = poll_interval,
			skip_initial_exec = self_watch,
		)
		self._live_reloader.start()

	@staticmethod
	def _caller_module_file () -> typing.Optional[str]:

		"""Return ``__file__`` of the module that invoked the caller, if available.

		Walks one frame up the call stack - the immediate caller is
		``watch()``, so ``f_back`` is the user's code.  Returns the
		module-level ``__file__`` of that frame's globals; ``None`` when
		the caller has no ``__file__`` (REPL, exec'd context, etc.).
		"""

		frame = inspect.currentframe()
		if frame is None or frame.f_back is None or frame.f_back.f_back is None:
			return None
		# f_back = watch(); f_back.f_back = user code calling watch().
		return frame.f_back.f_back.f_globals.get("__file__")

	def load_patterns (
		self,
		source:       str,
		source_label: str = "<string>",
	) -> None:

		"""Compile and apply a pattern-source string to the composition.

		Equivalent to one ``watch()`` reload triggered by save, but with the
		source presented in-memory rather than on disk.  Useful for web /
		REST handlers that accept pattern uploads from a trusted contributor,
		or for one-shot session loads with no file backing.

		Behaviour mirrors ``watch()``:

		* The source is exec'd into a fresh namespace with ``composition``
		  and ``subsequence`` in scope.
		* ``@composition.pattern`` decorators in the source hot-swap their
		  corresponding running patterns in place.
		* Patterns currently running but **not** declared in the source are
		  unregistered - the source is treated as the full new truth.
		* If the composition is already playing, the swap happens on the
		  event loop thread; the call blocks until it completes.
		* If the composition has not yet called ``play()``, the source runs
		  on the caller's thread; decorators populate ``_pending_patterns``
		  and ``play()`` picks them up in the usual way.

		Errors are raised so the caller can act on them:

		* ``SyntaxError`` if ``source`` fails to compile.
		* The exception raised inside ``exec()`` for any runtime error.
		* ``RuntimeError`` if the source calls ``sys.exit()`` while the
		  composition plays: a live source cannot end the performance.
		* ``RuntimeError`` if called from inside the composition's own
		  event loop thread (would deadlock - see Threading below).

		In either failure case, existing composition state is preserved -
		the diff-and-unregister phase is skipped if exec raised, so a
		half-broken upload cannot tear down working patterns.

		Threading:
			Designed to be called from a thread DIFFERENT from the
			composition's event loop - typically a web-handler worker.
			Cannot be called from inside the loop itself (a pattern
			callback, an asyncio task spawned by the composition).  From
			there, ``await composition._apply_source_async(...)`` directly.

		SECURITY WARNING: ``exec()`` is not sandboxed.  The source has full
		Python access in this process.  Only pass source from trusted
		senders.  The built-in blocklist (``help``, ``input``, ``breakpoint``,
		``exit``, ``quit``) prevents calls that would stall the event loop;
		it is not a security boundary.

		Parameters:
			source:       Python source declaring ``@composition.pattern``
				functions.
			source_label: Identifier used in compile errors and tracebacks
				(appears as the filename in ``SyntaxError`` and ``__file__``-
				style traceback lines).  Default ``"<string>"``.
		"""

		# Required for the decorator hot-swap path to fire on re-decoration.
		self._is_live = True

		# Compile on the caller's thread so SyntaxError comes back fast,
		# before any cross-thread scheduling.
		compiled = compile(source, source_label, "exec")
		namespace = self._build_live_namespace(source_label = source_label)

		loop = self._sequencer._event_loop

		if loop is not None and loop.is_running():

			# Refuse to deadlock: calling load_patterns() from inside the
			# composition's own event loop (e.g. from a pattern callback or
			# an asyncio task spawned by the composition) would have us
			# block waiting for a coroutine that can only run when this
			# thread yields.  Tell the caller exactly what to do instead.
			try:
				current_loop: typing.Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
			except RuntimeError:
				current_loop = None

			if current_loop is loop:
				raise RuntimeError(
					"load_patterns() cannot be called from inside the composition's "
					"event loop thread - it would deadlock waiting for the "
					"scheduled coroutine to run on the very thread that's blocked. "
					"From a worker thread, call it normally.  From an async "
					"coroutine already on the loop, "
					"`await composition._apply_source_async(compile(source, label, 'exec'), "
					"composition._build_live_namespace())` instead."
				)

			# Composition is playing — mutation must happen on the loop thread.
			# future.result() blocks the caller until the coroutine finishes
			# and re-raises any exception it threw.
			future = asyncio.run_coroutine_threadsafe(
				self._apply_source_async(compiled, namespace, source_key = source_label),
				loop = loop,
			)
			future.result()

		else:
			# Pre-play: no event loop yet.  Decorators populate
			# _pending_patterns; play() graduates them in the usual way.
			# Diff-and-unregister is unnecessary here — nothing is running,
			# but RECORD what this source declares so a later post-play
			# reload under the same label can tear down its deletions.
			self._declared_names = set()
			before = self._pending_snapshot()

			try:
				exec(compiled, namespace)
			except BaseException:
				self._roll_back_pending(before)
				raise

			self._source_declared[source_label] = set(self._declared_names)

	async def _apply_source_async (
		self,
		compiled:  types.CodeType,
		namespace: typing.Dict[str, typing.Any],
		source_key: str = "<live>",
	) -> None:

		"""Execute pre-compiled live source against the running composition.

		Runs on the event loop thread.  Performs ``exec()``, graduates any
		newly-decorated patterns into ``_running_patterns``, then unregisters
		any patterns that *this source* declared on its previous exec but no
		longer declares (keyed by ``source_key`` - a watched file's path or a
		``load_patterns`` label).  Patterns registered by the wrapper script
		or by another source are never this source's to tear down.

		Raises whatever ``exec()`` raises.  When that happens, the diff-and-
		unregister phase is skipped - the namespace is incomplete, so any
		patterns the source failed to reach would be misinterpreted as
		deletions and torn down.

		Called from two places:

		* ``Composition.load_patterns()`` via ``run_coroutine_threadsafe``.
		* ``LiveReloader._reload_async`` directly (already on the loop).
		"""

		# Track which patterns the source declares this exec.  pattern() and
		# layer() add their (resolved) names to _declared_names as they run, so
		# this covers decorated patterns AND layer()/merged patterns — the latter
		# have no module-level callable to match against by name, which is why the
		# old namespace-based diff tore layers down on every reload.
		self._declared_names = set()

		# Bail before any state mutation if exec raises — propagates to
		# the caller (load_patterns re-raises; LiveReloader catches + logs).
		# The source runs on the loop the performance hears Ctrl+C and SIGTERM
		# on, so it is lent them while it runs, as typed code is: a save whose
		# top level never finished stopped the music and left the process deaf
		# to both (#3378).
		# A pass that raised starts none of the parts it added, now or later
		# (#3377).
		before = self._pending_snapshot()

		try:
			with subsequence.live_server.stop_signals_reach_the_code():
				exec(compiled, namespace)
		except SystemExit as exit_request:
			# A live source cannot end the performance, any more than a line typed
			# at the REPL can: its sys.exit() is its own failure.  Let through, it
			# left the loop with notes sounding (#3551).
			self._roll_back_pending(before)
			raise RuntimeError(
				f"{source_key} called sys.exit(), which a live source cannot do: it would end "
				"the performance.  Stop the piece with Ctrl+C."
			) from exit_request
		except BaseException:
			self._roll_back_pending(before)
			raise

		# Graduate newly-decorated patterns from _pending_patterns into
		# _running_patterns so they start firing on the next reschedule.
		# Patterns that hot-swapped via the decorator/layer path don't appear
		# in _pending_patterns and don't need this step.
		await self._activate_new_pending_patterns()

		# Detect deletions: a name THIS source declared last time but not this
		# time has been removed by the user and should be torn down.  (An
		# unknown source — first exec — tears down nothing: patterns running
		# from the wrapper script or another source are not ours to remove.)
		# Decorators/layer() do NOT remove from _running_patterns when a
		# definition disappears from the source.
		previous = self._source_declared.get(source_key)

		if previous is not None:
			for name in previous - self._declared_names:
				if name in self._running_patterns:
					self.unregister(name)

		self._source_declared[source_key] = set(self._declared_names)

	def _build_live_namespace (self, source_label: str = "<live>") -> typing.Dict[str, typing.Any]:

		"""Build a fresh namespace dict for exec'ing live source.

		Provides ``composition`` (this Composition), ``subsequence`` (the
		package), and a safe builtins set with ``help``, ``input``,
		``breakpoint``, ``exit``, ``quit`` blocked.

		Also injects two dunder globals that make the single-file live-coding
		workflow ergonomic:

		* ``__name__ = "__live_reload__"`` - so ``if __name__ == "__main__":``
		  blocks in the watched file are *skipped* during live reload.  The
		  same file run directly with ``python my_session.py`` sees
		  ``__name__ == "__main__"`` and runs setup; saves trigger reload
		  with ``__name__ == "__live_reload__"``, skipping setup and only
		  re-running pattern definitions.
		* ``__file__ = source_label`` - so ``composition.watch(__file__)``
		  and any user code referencing ``__file__`` works inside the live
		  namespace.  Set to the file path for ``LiveReloader``, the
		  user-supplied ``source_label`` for ``Composition.load_patterns``,
		  and ``"<live>"`` for ``LiveServer``.

		Single source of truth: ``live_reloader`` (file watching),
		``live_server`` (TCP REPL), and ``load_patterns`` (string source)
		all call this so live source sees the same environment from any
		entry point.

		The blocklist prevents calls that would stall the async event loop
		running the sequencer.  It is **not** a security sandbox - exec'd
		code can still do anything Python allows.

		Parameters:
			source_label: Value to bind to ``__file__`` in the namespace.
				Defaults to ``"<live>"``.
		"""

		import subsequence  # local import: this module is imported during subsequence init

		safe_builtins = {name: getattr(builtins, name) for name in dir(builtins)}

		blocked = {"help", "input", "breakpoint", "exit", "quit"}

		for name in blocked:
			safe_builtins[name] = _live_blocked(name)

		return {
			"__builtins__": safe_builtins,
			"__name__":     "__live_reload__",
			"__file__":     source_label,
			"composition":  self,
			"subsequence":  subsequence,
		}

	def osc (self, receive_port: int = 9000, send_port: int = 9001, send_host: str = "127.0.0.1", receive_host: str = "127.0.0.1") -> None:

		"""
		Enable bi-directional Open Sound Control (OSC).

		Subsequence will listen for commands (like ``/bpm`` or ``/mute``) and
		broadcast its internal state (like ``/chord`` or ``/bar``) over UDP.

		Parameters:
			receive_port: Port to listen for incoming OSC messages (default 9000).
			send_port: Port to send state updates to (default 9001).
			send_host: The IP address to send updates to (default "127.0.0.1").
			receive_host: Interface to listen on (default "127.0.0.1" - this
				machine only, as for ``live()``).  Pass
				``receive_host="0.0.0.0"`` to let an OSC controller elsewhere
				on the network reach it.  A listener can change tempo, mute
				parts and write data, so that is worth doing deliberately
				rather than by default; the startup log says which it chose.
		"""

		self._osc_server = subsequence.osc.OscServer(
			self,
			receive_port = receive_port,
			send_port = send_port,
			send_host = send_host,
			receive_host = receive_host
		)

	def osc_map (self, address: str, handler: typing.Callable) -> None:

		"""
		Register a custom OSC handler.

		Must be called after :meth:`osc` has been configured.

		Parameters:
			address: OSC address pattern to match (e.g. ``"/my/param"``).
			handler: Callable invoked with ``(address, *args)`` when a
				matching message arrives.

		Example::

			composition.osc()

			def on_intensity (address, value):
				composition.data["intensity"] = float(value)

			composition.osc_map("/intensity", on_intensity)
		"""

		if self._osc_server is None:
			raise RuntimeError("Call composition.osc() before composition.osc_map()")

		self._osc_server.map(address, handler)

	def set_bpm (self, bpm: float) -> None:

		"""
		Instantly change the tempo.

		Parameters:
			bpm: The new tempo in beats per minute.

		When Ableton Link is active, this proposes the new tempo to the Link
		network instead of applying it locally.  The network-authoritative tempo
		is picked up on the next pulse.
		"""

		self._sequencer.set_bpm(bpm)

		if not self.is_clock_following and self._link_quantum is None:
			self.bpm = bpm

	def target_bpm (self, bpm: float, bars: int, shape: str = "linear") -> None:

		"""
		Smoothly ramp the tempo to a target value over a number of bars.

		Parameters:
			bpm: Target tempo in beats per minute.
			bars: Duration of the transition in bars.
			shape: Easing curve name.  Defaults to ``"linear"``.
			       ``"ease_in_out"`` or ``"s_curve"`` are recommended for natural-
			       sounding tempo changes.  See :mod:`subsequence.easing` for all
			       available shapes.

		Example:
			```python
			# Accelerate to 140 BPM over the next 8 bars with a smooth S-curve
			comp.target_bpm(140, bars=8, shape="ease_in_out")
			```

		Note:
			Ignored while Ableton Link is active - the shared session tempo is
			authoritative.  Use ``set_bpm()`` to propose a tempo to the Link network.
		"""

		self._sequencer.set_target_bpm(bpm, bars, shape)

	def live_info (self) -> typing.Dict[str, typing.Any]:

		"""
		Return a dictionary containing the current state of the composition.
		
		Includes BPM, key, current bar, active section, current chord, 
		running patterns, and custom data.
		"""

		section_info = None
		if self._form_state is not None:
			section = self._form_state.get_section_info()
			if section is not None:
				section_info = {
					"name": section.name,
					"bar": section.bar,
					"bars": section.bars,
					"progress": section.progress
				}

		chord_name = None
		sounding_chord = self.current_chord()
		if sounding_chord is not None:
			chord_name = sounding_chord.name()

		pattern_list = []
		channel_offset = 0 if self._zero_indexed_channels else 1
		for name, pat in self._running_patterns.items():
			pattern_list.append({
				"name": name,
				"channel": pat.channel + channel_offset,
				"length": pat.length,
				"cycle": pat._cycle_count,
				"muted": pat._muted,
				"tweaks": dict(pat._tweaks)
			})

		return {
			"bpm": self._sequencer.current_bpm,
			"key": self.key,
			"bar": self._builder_bar,
			"section": section_info,
			"chord": chord_name,
			"patterns": pattern_list,
			"input_device": self._input_device,
			"clock_follow": self.is_clock_following,
			"data": self.data
		}

	def pause (self) -> None:

		"""
		Hold playback where it is, keeping the composition's place.

		The clock stops advancing, sounding notes are released, and MIDI Stop
		is sent to any hardware following the clock output.  :meth:`resume`
		continues from the same pulse, beat and bar - where stopping and
		playing again would start the piece over.

		Bar and cycle counters hold too, so patterns resume mid-phrase rather
		than jumping.  A note cut short by the pause is not re-struck on
		resume; it returns on its pattern's next cycle.

		Idempotent and safe to call from any thread.  Ignored, with a log line,
		when the transport is not ours to hold - under ``clock_follow=True`` or
		an active Ableton Link session.
		"""

		self._sequencer.pause()

	def resume (self) -> None:

		"""
		Continue playback from where :meth:`pause` held it.

		Sends MIDI Continue rather than Start, so downstream hardware picks up
		where it left off instead of resetting to the top of its own pattern.
		Idempotent.
		"""

		self._sequencer.resume()

	@property
	def is_paused (self) -> bool:

		"""True while playback is held by :meth:`pause`."""

		return self._sequencer.paused

	def mute (self, name: str) -> None:

		"""
		Mute a running pattern by name.

		The pattern continues to 'run' and increment its cycle count in
		the background, but it will not produce any MIDI notes until unmuted.

		**A drone it is holding is released** at the start of its first silent
		cycle, on every destination it plays to.  It has to be: its builder is
		what would have turned the drone off, and a muted builder does not run,
		so the note used to ring until the performance stopped.  Unmuting does
		not strike it again - what sounds is the builder's decision, and it
		will place a fresh one if it wants one.  The same goes for a part the
		energy gate closes or a transition holds quiet.

		Parameters:
			name: The function name of the pattern to mute.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		# The performer takes ownership: if a transition's approach window had
		# muted this pattern, drop it from that set so the section boundary
		# does not silently unmute it ("performer mutes win").
		self._transition_muted.discard(name)

		self._running_patterns[name]._muted = True
		logger.info(f"Muted pattern: {name}")

	def unmute (self, name: str) -> None:

		"""
		Unmute a previously muted pattern.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		# Symmetric ownership claim: an explicit unmute means the transition
		# machinery should no longer manage this pattern at the boundary.
		self._transition_muted.discard(name)

		self._running_patterns[name]._muted = False
		logger.info(f"Unmuted pattern: {name}")

	def unregister (self, name: str) -> None:

		"""Fully remove a running pattern from rotation.

		Unlike ``mute()`` (which keeps the pattern alive but silent),
		``unregister()`` tears the pattern down entirely.  It sets
		``pattern._removed = True`` so the sequencer's reschedule loop
		skips re-adding it on the next pulse; sends ``note_off`` for
		**this pattern's** currently-sounding notes on the primary
		destination AND on every mirror destination (so drones and
		sustaining notes stop immediately); and removes the entry from
		``_running_patterns`` so it no longer appears in ``live_info()``,
		the terminal grid, or any other consumer that enumerates running
		patterns.

		Another pattern sharing the MIDI channel keeps playing.  Its notes are
		its own to end, and cutting them is what used to happen - a pad's
		four-beat note stopped 0.08 of a beat in when an arp beside it was
		unregistered (#2996).  A note with no pattern behind it, from
		``trigger()`` or sent straight to a port, is still released: nothing
		else is coming to end it.

		Its own note-ons still waiting in the queue are dropped, so a drone
		struck inside the reschedule lookahead does not play after the
		release pass and ring for the rest of the piece.  Everything else
		queued plays out - note_offs are paired with their note_ons at queue
		time, so ordinary notes end at their natural duration.

		Idempotent: silently logs a ``debug`` and returns if the pattern
		is already absent.  Useful from both the live REPL
		(``composition.live()``) and the file watcher
		(``composition.watch()``), which calls this for any pattern
		removed from the watched file between reloads.

		Parameters:
			name: Function name of the pattern to remove.
		"""

		if name not in self._running_patterns:
			logger.debug(f"unregister() no-op: pattern '{name}' not running")
			return

		pattern = self._running_patterns[name]

		# Mark for removal first so the reschedule loop sees the flag even if
		# it fires concurrently with the note-off pass below.
		pattern._removed = True

		# Stop sustaining notes (including drones) on every destination this
		# pattern outputs to.  Fire-and-forget across threads via the event
		# loop; ``_stop_pattern_notes`` acquires the queue lock internally.
		if self._sequencer._event_loop is not None:
			asyncio.run_coroutine_threadsafe(
				self._sequencer._stop_pattern_notes(pattern),
				loop = self._sequencer._event_loop,
			)

		def _finalise_removal () -> None:
			self._running_patterns.pop(name, None)

			# Forget any pending (not-yet-graduated) declaration too, so a
			# later live reload cannot resurrect the pattern.
			self._pending_patterns = [
				pending for pending in self._pending_patterns
				if pending.builder_fn.__name__ != name
			]

			logger.info(f"Unregistered pattern: {name}")

		# The running-patterns dict is iterated by the display and the
		# reschedule loop on the event loop thread - mutate it there when this
		# call arrives from another thread (e.g. a scheduled function's).
		self._sequencer._on_the_clock(_finalise_removal)

	def mirror (self, name: str, device: int, channel: int, drum_note_map: typing.Optional[typing.Dict[str, int]] = None) -> None:

		"""
		Add a mirror destination to a running pattern.

		Every note, CC, pitch bend, NRPN/RPN, program change, SysEx, and drone
		event the pattern emits will also be sent to ``(device, channel)``,
		starting from the next cycle rebuild.  Idempotent on ``(device, channel)`` -
		calling with the same destination twice does not double-fan; calling
		again with a different ``drum_note_map`` re-points it in place.

		Parameters:
			name: Function name of the pattern to mirror.
			device: Output device index (the integer returned from
				``midi_output()``; 0 = primary device).
			channel: MIDI channel using this composition's numbering convention
				(1-16 by default; 0-15 if ``zero_indexed_channels=True``).
			drum_note_map: Optional per-destination drum map.  When set, mirrored
				drum hits are re-resolved by name through it, so a named voice
				lands on this device's own note number.  Without it the mirror
				copies the raw note number, which may be a different voice on a
				device with another drum map.

		Trade-offs: each mirror adds another full copy of the pattern's events,
		which can crowd a slow DIN-MIDI link.  A tuned part's rotation across a
		MIDI channel pool collapses onto the mirror's one MIDI channel, so the mirror
		cannot play it in tune.  OSC events are not mirrored.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		resolved_channel = self._resolve_channel(channel)
		prefix = (device, resolved_channel)
		entry: subsequence.pattern.MirrorSpec = prefix if drum_note_map is None else (device, resolved_channel, drum_note_map)

		pattern = self._running_patterns[name]

		# Mirror-to-self check: comparing the (device, channel) prefix against the
		# live pattern's resolved destination.  Unlike the decorator path this is
		# always concrete.
		if prefix == (pattern.device, pattern.channel):
			logger.warning(
				f"Mirror destination {prefix} matches '{name}'s primary destination "
				f"- every event will double-fire on this (device, channel).  This is almost "
				f"certainly unintended."
			)

		# Idempotent on (device, channel): replace any existing entry for the same
		# destination (so its map can be re-pointed), else append.
		existing_index = next((idx for idx, e in enumerate(pattern.mirrors) if (e[0], e[1]) == prefix), None)
		if existing_index is None:
			pattern.mirrors.append(entry)
			logger.info(f"Mirror added: {name} -> device={device}, channel={resolved_channel}")
		elif pattern.mirrors[existing_index] != entry:
			pattern.mirrors[existing_index] = entry
			logger.info(f"Mirror updated: {name} -> device={device}, channel={resolved_channel}")
		else:
			logger.debug(f"Mirror already present on {name}: device={device}, channel={resolved_channel}")

	def unmirror (self, name: str, device: int, channel: int) -> None:

		"""
		Remove a single mirror destination from a running pattern.

		Matches on ``(device, channel)`` only - any attached ``drum_note_map`` is
		ignored.  Idempotent: silently does nothing if the destination is not
		currently mirrored.  The change applies on the next cycle rebuild.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		resolved_channel = self._resolve_channel(channel)
		prefix = (device, resolved_channel)

		pattern = self._running_patterns[name]

		filtered = [e for e in pattern.mirrors if (e[0], e[1]) != prefix]
		if len(filtered) != len(pattern.mirrors):
			pattern.mirrors[:] = filtered
			logger.info(f"Mirror removed: {name} -> device={device}, channel={resolved_channel}")
		else:
			logger.debug(f"unmirror() no-op on {name}: device={device}, channel={resolved_channel} not in mirrors")

	def unmirror_all (self, name: str) -> None:

		"""
		Remove every mirror destination from a running pattern.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		pattern = self._running_patterns[name]

		if pattern.mirrors:
			pattern.mirrors.clear()
			logger.info(f"All mirrors cleared on pattern: {name}")

	def tweak (self, name: str, **kwargs: typing.Any) -> None:

		"""Override parameters for a running pattern.

		Values set here are available inside the pattern's builder
		function via ``p.param()``.  They persist across rebuilds
		until explicitly changed or cleared.  Changes take effect
		on the next rebuild cycle.

		Parameters:
			name: The function name of the pattern.
			``**kwargs``: Parameter names and their new values.

		Example (from the live REPL)::

			composition.tweak("bass", pitches=[48, 52, 55, 60])
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		self._running_patterns[name]._tweaks.update(kwargs)
		logger.info(f"Tweaked pattern '{name}': {list(kwargs.keys())}")

	def clear_tweak (self, name: str, *param_names: str) -> None:

		"""Remove tweaked parameters from a running pattern.

		If no parameter names are given, all tweaks for the pattern
		are cleared and every ``p.param()`` call reverts to its
		default.

		Parameters:
			name: The function name of the pattern.
			*param_names: Specific parameter names to clear.  If
				omitted, all tweaks are removed.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		if not param_names:
			self._running_patterns[name]._tweaks.clear()
			logger.info(f"Cleared all tweaks for pattern '{name}'")
		else:
			for param_name in param_names:
				self._running_patterns[name]._tweaks.pop(param_name, None)
			logger.info(f"Cleared tweaks for pattern '{name}': {list(param_names)}")

	def get_tweaks (self, name: str) -> typing.Dict[str, typing.Any]:

		"""Return a copy of the current tweaks for a running pattern.

		Parameters:
			name: The function name of the pattern.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		return dict(self._running_patterns[name]._tweaks)

	def schedule (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int = 1, wait_for_initial: bool = False, defer: bool = False) -> None:

		"""
		Register a custom function to run on a repeating beat-based cycle.

		Subsequence automatically runs synchronous functions in a thread pool
		so they don't block the timing-critical MIDI clock. Async functions
		are run directly on the event loop.  In ``render()`` each call finishes
		before the render moves on, plain or async, so a function that feeds
		the patterns renders the same file on every run with the same seed.

		Parameters:
			fn: The function to call.
			cycle_beats: How often to call it, in beats (e.g. 4 = every bar of 4/4).
			reschedule_lookahead: How far in advance to schedule the next call.
			wait_for_initial: If True, run the function once during startup
				and wait for it to complete before playback begins. This
				ensures ``composition.data`` is populated before patterns
				first build. Implies ``defer=True`` for the repeating
				schedule.
			defer: If True, skip the pulse-0 fire and defer the first
				repeating call to just before the second cycle boundary.

		Raises:
			RuntimeError: If called after ``play()`` has started - scheduled
				tasks register at startup, so a late registration would be
				silently ignored otherwise.
		"""

		if self._sequencer.running:
			raise RuntimeError("schedule() must be called before play() - scheduled tasks register at startup")

		self._pending_scheduled.append(_PendingScheduled(fn, cycle_beats, reschedule_lookahead, wait_for_initial, defer))

	def form (
		self,
		sections: typing.Union[
			"subsequence.forms.Form",
			typing.List[typing.Any],
			typing.Iterator[typing.Tuple[str, int]],
			typing.Dict[str, typing.Tuple[int, typing.Optional[typing.List[typing.Tuple[str, int]]]]]
		],
		loop: bool = False,
		start: typing.Optional[str] = None,
		at_end: str = "stop",
		key: typing.Optional[str] = None,
		scale: typing.Optional[str] = None,
	) -> None:

		"""
		Define the structure (sections) of the composition.

		You can define form in four ways:

		1. **Form value**: a frozen :class:`~subsequence.forms.Form` of
		   :class:`~subsequence.forms.Section` values - the payload home
		   (energy, key per section); editable, navigable.
		2. **Sequence (List)**: a fixed order of ``(name, bars)`` tuples
		   or Sections (lists coerce - they are the same form).
		3. **Graph (Dict)**: dynamic transitions based on weights.
		4. **Generator**: a Python generator that yields ``(name, bars)`` pairs.

		Form-value and list forms are **navigable**: ``form_jump()`` and
		``form_next()`` work on them (the jump lands on the next occurrence
		of the name, wrapping).

		Re-binding ``form()`` during playback takes effect at the next bar -
		the clock reads the current form state on every bar, so the new form
		advances from there (its first section plays from its first bar).

		Parameters:
			sections: The form definition (Form, List, Dict, or Generator).
			loop: Sugar for ``at_end="loop"``.
			start: The section to start with (Graph mode only).
			at_end: What happens when a sequence form runs out -
				``"stop"`` (the form finishes and patterns see no section;
				default), ``"hold"`` (the final section repeats until
				navigated away from), or ``"loop"`` (start over).  Graphs
				end via their terminal sections instead.
			key: A form-level key - the **form tier** of the key-source
				chain (``Section.key`` overrides it; it overrides the
				composition key).  Re-anchors key-relative content for the
				whole form.  When *sections* is a ``Form`` value carrying its
				own ``key``, that value is used unless this argument overrides.
			scale: A form-level scale/mode, paired with ``key``.

		Example:
			```python
			# A simple pop structure
			comp.form([
				("verse", 8),
				("chorus", 8),
				("verse", 8),
				("chorus", 16)
			])

			# The same structure with payloads, held open at the end
			S = subsequence.Section
			comp.form(subsequence.Form([
				S("verse", 8, energy=0.5), S("chorus", 8, energy=0.9),
			]), at_end="hold")
			```
		"""

		# Seed FormState at form() time (per-call salt) so build-time walks —
		# the frozen clones form_freeze will take — are deterministic without
		# play(); the play-time stream is re-dealt name-keyed in _run().
		self._form_count += 1

		self._form_state = subsequence.form_state.FormState(
			sections,
			loop = loop,
			start = start,
			rng = self._stream(f"form:{self._form_count}"),
			at_end = at_end,
		)

		self._form_spec = (sections, loop, start, at_end, self._form_count)

		# Bumped on every form() call so the harmonic clock can tell one form's
		# section 0 from another's (#3084).
		self._form_generation += 1

		# A Form value carries energy payloads — that counts as an energy
		# source for the min_energy registration check in _run().
		self._form_has_payload = isinstance(sections, subsequence.forms.Form) or (
			isinstance(sections, list) and any(isinstance(element, subsequence.forms.Section) for element in sections)
		)

		# Form-tier key/scale: an explicit argument wins; otherwise a Form
		# value's own key/scale seeds the tier.  Re-binding the form drops any
		# stale per-section resolution cache.
		if isinstance(sections, subsequence.forms.Form):
			self._form_key = key if key is not None else sections.key
			self._form_scale = scale if scale is not None else sections.scale
		else:
			self._form_key = key
			self._form_scale = scale

		self._resolved_section_cache = {}

		# A FIRST form() call mid-playback must start the clock itself —
		# _run() only registers clocks for sources it can see at play() time,
		# so without this the form never advanced at all (#3084).  A re-bind
		# needs nothing here: the clock reads the form through a getter on
		# every bar.
		# NOT `loop`: form() already takes a loop= argument (the at_end sugar),
		# and shadowing it here would be a trap for the next edit.
		event_loop = self._sequencer._event_loop

		if event_loop is not None and event_loop.is_running() and not self._form_clock_started:

			try:
				on_loop = asyncio.get_running_loop() is event_loop
			except RuntimeError:
				on_loop = False

			if on_loop:
				event_loop.create_task(self._start_form_clock())
			else:
				asyncio.run_coroutine_threadsafe(self._start_form_clock(), event_loop)

	def form_freeze (self, sections: typing.Optional[int] = None) -> "subsequence.forms.Form":

		"""Freeze the graph form's walk into an editable :class:`~subsequence.forms.Form`.

		Walks a **clone** of the live form state - the same RNG state, so the
		frozen path is exactly the path the live graph would have played -
		and returns it as a Form value: inspect it, edit it
		(``path.replace(3, bars=16)``), and rebind it with
		``composition.form(path, at_end=...)``.  The live form state is
		untouched (rebinding replaces it).

		Parameters:
			sections: Number of sections to freeze.  Without it, the walk
				runs until a terminal section; a graph with no terminal
				sections requires ``sections=`` explicitly.

		Raises:
			ValueError: If no graph form is bound (a list form is already a
				frozen sequence), the form has already finished, or the walk
				cannot terminate.

		Example::

			composition.form({...}, start="intro")
			path = composition.form_freeze()          # the walk, frozen
			composition.form(path, at_end="stop")     # rebind the editable value
		"""

		fs = self._form_state

		if fs is None or fs._graph is None or fs._section_bars is None:
			raise ValueError(
				"form_freeze() freezes a graph form's walk - call form() with a dict first "
				"(a list form is already a frozen sequence)"
			)

		if fs._current is None:
			raise ValueError("the form has already finished - nothing left to freeze")

		if sections is not None and sections < 1:
			raise ValueError("sections must be at least 1")

		if sections is None and not fs._terminal_sections:
			raise ValueError(
				"this graph has no terminal section, so the walk would never end - "
				"pass sections=n to bound it"
			)

		# Clone the RNG state: the frozen walk reproduces the live form's
		# future draws without consuming them.
		rng = random.Random()
		rng.setstate(fs._rng.getstate())

		walked = [fs._current]
		next_name = fs._next_section_name		# already decided by the live state

		while next_name is not None:
			if sections is not None and len(walked) >= sections:
				break
			if sections is None and len(walked) >= 10000:
				raise ValueError(
					"form_freeze() walked 10000 sections without reaching a terminal - "
					"the terminals look unreachable; pass sections=n to bound the walk"
				)

			walked.append(subsequence.forms.Section(name = next_name, bars = fs._section_bars[next_name]))
			next_name = None if next_name in fs._terminal_sections else fs._graph.choose_next(next_name, rng)

		# Carry the form-tier key/scale onto the frozen value so a freeze →
		# rebind round-trip is lossless (an explicit form(key=) on rebind
		# still overrides).
		return subsequence.forms.Form(walked, key = self._form_key, scale = self._form_scale)

	def energy (self, energies: typing.Dict[str, typing.Union[float, typing.Tuple[float, float]]]) -> None:

		"""Set per-section energy - the arranging dial, as one plain dict.

		``{"verse": 0.5, "chorus": 0.9, "build": (0.3, 1.0)}`` - a float is
		the section's level; a ``(start, end)`` tuple interpolates across the
		section (a build).  Patterns read ``p.energy`` (0.5 when nothing is
		configured) and gate themselves, or declare ``min_energy=`` on
		``pattern()`` for automatic muting.

		The dict **overrides** any energy payload carried by bound
		:class:`~subsequence.forms.Section` values - it is the later,
		performance-level dial.  Re-calling replaces the whole mapping
		(idempotent, live-reload friendly).

		Example::

			composition.energy({"intro": 0.2, "verse": 0.55, "drop": 0.95})
		"""

		validated: typing.Dict[str, typing.Union[float, typing.Tuple[float, float]]] = {}

		for name, value in energies.items():
			if isinstance(value, tuple):
				if len(value) != 2:
					raise ValueError(f"energy ramp for {name!r} must be (start, end), got {value!r}")
				start_level, end_level = float(value[0]), float(value[1])
				for level in (start_level, end_level):
					if not 0.0 <= level <= 1.0:
						raise ValueError(f"energy for {name!r} must be 0.0–1.0, got {value!r}")
				validated[name] = (start_level, end_level)
			else:
				level = float(value)
				if not 0.0 <= level <= 1.0:
					raise ValueError(f"energy for {name!r} must be 0.0–1.0, got {value!r}")
				validated[name] = level

		self._energy_map = validated

	def _current_energy (self, info: typing.Optional[subsequence.form_state.SectionInfo]) -> float:

		"""Resolve the energy for a section snapshot.

		Priority: the ``energy()`` dict (ramps interpolate by section
		progress) > the bound Section payload > 0.5.
		"""

		if info is None:
			return 0.5

		spec = self._energy_map.get(info.name)

		if spec is None:
			return info.energy

		if isinstance(spec, tuple):
			start_level, end_level = spec

			# A build reaches its declared end ON the final bar, so the ramp spans
			# bar 0 → bar (bars-1).  (info.progress is bar/bars, which would top
			# out one bar short and never deliver end.)  A one-bar section sits at
			# the destination level.
			span = info.bars - 1
			fraction = info.bar / span if span > 0 else 1.0

			return start_level + (end_level - start_level) * fraction

		return spec

	def on_section (self, callback: typing.Callable[..., typing.Any]) -> None:

		"""Register a callback fired on every section change.

		The callback receives the new :class:`~subsequence.form_state.SectionInfo`
		(or ``None`` when the form finishes).  It fires from the form clock,
		one lookahead-beat **early** - in time to affect the new section's
		first patterns - once at play start for the opening section, and when
		``form_jump()`` moves to a section.

		Because it fires *from* the clock, it must be an ordinary ``def``: an
		``async def`` is refused here, when you write it.  To start async work
		from a section change, hand it to the running loop::

			def on_section (info):
			    asyncio.get_running_loop().create_task(tell_the_lighting_desk(info))

		A callback that raises is logged and the others still run - one broken
		listener never stops the music.

		Example::

			composition.on_section(lambda info: print(f"now: {info.name if info else 'end'}"))
		"""

		self.on_event("section", callback)

	def transition (
		self,
		before: str,
		fill: typing.Optional[typing.Any] = None,
		channel: typing.Optional[int] = None,
		beat: float = 0.0,
		mute: typing.Optional[typing.List[str]] = None,
		beats: typing.Optional[float] = None,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		device: subsequence.midi_utils.DeviceId = None,
	) -> None:

		"""Declare boundary material - the automatic fill or mute, one line.

		``before`` names the incoming section (``"chorus"``), or ``"*"`` for
		any *different* section (repeats don't fire it).  Two actions,
		combinable:

		- ``fill=`` (+ ``channel=``, ``beat=``): a Motif played in the last
		  bar before the boundary, starting at ``beat`` of that bar.  Drum
		  names resolve through ``drum_note_map=`` if given, otherwise the
		  map is borrowed from a registered pattern on the same MIDI channel.
		- ``mute=`` (+ ``beats=``): pattern names muted over the approach
		  and unmuted at the boundary.  Muting is **bar-granular** (the
		  existing rule), so ``beats`` rounds up to whole bars.  Performer
		  mutes win: a pattern you muted yourself stays muted.

		Transitions stack - call once per rule.  Registration is additive
		and idempotent per identical rule.

		Example::

			composition.transition(before="*", fill=FILL, channel=10, beat=2.0)
			composition.transition(before="drop", mute=["pads"], beats=4)
		"""

		if fill is None and mute is None:
			raise ValueError("transition() needs fill= and/or mute= - it declares what happens at the boundary")

		if fill is not None:
			if channel is None:
				raise ValueError("transition(fill=) needs channel= - the fill must land somewhere")
			if not hasattr(fill, "events") or not hasattr(fill, "length"):
				raise TypeError(f"fill must be a Motif-like value with .events/.length, got {type(fill).__name__}")

		if mute is not None and beats is None:
			beats = self.bar_beats		# one bar by default

		rule = _Transition(
			before = before,
			fill = fill,
			channel = self._resolve_channel(channel) if channel is not None else None,
			beat = float(beat),
			mute = list(mute) if mute is not None else None,
			beats = beats,
			drum_note_map = drum_note_map,
			device = device,			# resolved at fire time — names aren't known until play()
		)

		if rule not in self._transitions:
			self._transitions.append(rule)

	def _transition_drum_map (self, channel: typing.Optional[int]) -> typing.Optional[typing.Dict[str, int]]:

		"""Borrow a drum map from a registered pattern on the same channel."""

		if channel is None:
			return None

		for pending in self._pending_patterns:
			if pending.channel == channel and pending.drum_note_map:
				return pending.drum_note_map

		for running in self._running_patterns.values():
			candidate = getattr(running, "_drum_note_map", None)
			if running.channel == channel and candidate:
				return typing.cast(typing.Dict[str, int], candidate)

		return None

	def _fire_fill (self, rule: _Transition, start_pulse: int) -> None:

		"""Build a transition fill as a one-shot pattern and schedule it."""

		assert rule.fill is not None and rule.channel is not None

		drum_map = rule.drum_note_map if rule.drum_note_map is not None else self._transition_drum_map(rule.channel)

		pattern = subsequence.pattern.Pattern(
			channel = rule.channel,
			length = float(rule.fill.length),
			device = self._resolve_device_id(rule.device),
		)

		harmony_view: typing.Optional[HarmonyView] = None
		if not self._harmony_horizon.is_empty:
			harmony_view = HarmonyView(self._harmony_horizon, start_pulse / self._sequencer.pulses_per_beat)

		# The fill sounds in the outgoing section's final bar, so a degree-
		# bearing fill resolves against THAT section's effective key/scale —
		# previously it took the composition key, ignoring the section.
		fill_section = self._form_state.get_section_info() if self._form_state else None
		fill_key, fill_scale = self._effective_key_scale(fill_section)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			drum_note_map = drum_map,
			section = fill_section,
			bar = self._builder_bar,
			conductor = self.conductor,
			rng = self._stream(f"transition:{rule.before}:{start_pulse}") or random.Random(),
			tweaks = {},
			default_grid = 16,
			data = self.data,
			key = fill_key,
			scale = fill_scale,
			time_signature = self.time_signature,
			harmony = harmony_view,
		)

		try:
			builder.motif(rule.fill)
			builder._finish_build()
			self._apply_composition_tuning(pattern, builder, drum_map, part = None)
		except Exception:
			logger.exception("transition fill failed to build - the boundary plays without it")
			return

		self._schedule_one_shot(pattern, start_pulse)

	def _lift_transition_mutes (self) -> None:

		"""A section has changed: unmute what the transitions muted for its approach, and nothing a performer muted."""

		for name in self._transition_muted:
			running = self._running_patterns.get(name)
			if running is not None:
				running._muted = False

		self._transition_muted.clear()

	def _check_transitions (self, boundary_pulse: int, section_changed: bool) -> None:

		"""The form clock's boundary hook: fire fills, manage approach mutes.

		Called once per bar (lookahead-early, with the bar-line pulse).
		Fill rules fire when the current bar is the section's last before a
		matching boundary; mute rules close over the approach window
		(rounded up to whole bars - muting is bar-granular) and reopen at
		the boundary.  Performer mutes are never touched.
		"""

		if section_changed:
			self._lift_transition_mutes()

		if not self._transitions or self._form_state is None:
			return

		info = self._form_state.get_section_info()

		if info is None or info.next_section is None:
			return

		bar_beats = self.bar_beats
		bars_remaining = info.bars - info.bar

		for rule in self._transitions:

			if rule.before == "*":
				if info.next_section == info.name:
					continue		# a repeat is not a boundary
			elif info.next_section != rule.before:
				continue

			if rule.fill is not None and bars_remaining == 1:
				self._fire_fill(rule, boundary_pulse + int(round(rule.beat * self._sequencer.pulses_per_beat)))

			if rule.mute:
				window_beats = rule.beats if rule.beats is not None else bar_beats
				window_bars = max(1, int((window_beats + bar_beats - 1e-9) // bar_beats))

				if bars_remaining <= window_bars:
					for name in rule.mute:
						running = self._running_patterns.get(name)
						if running is None or name in self._transition_muted:
							continue
						if running._muted:
							continue		# the performer's mute — not ours to manage
						running._muted = True
						self._transition_muted.add(name)

	@staticmethod
	def _resolve_length (
		beats: typing.Optional[float],
		bars: typing.Optional[float],
		steps: typing.Optional[float],
		step_duration: typing.Optional[float],
		default: float = 4.0,
		beats_per_bar: float = 4,
	) -> typing.Tuple[float, int]:

		"""
		Resolve the beat_length and default_grid from the duration parameters.

		Two modes:

		- **Duration mode** (no ``step_duration``): specify ``beats=`` or ``bars=``.
		  ``beats=4`` = 4 quarter notes; ``bars=2`` = 8 beats.
		- **Step mode** (with ``step_duration``): specify ``steps=`` and ``step_duration=``.
		  ``steps=6, step_duration=dur.SIXTEENTH`` = 6 sixteenth notes = 1.5 beats.

		Constraints:

		- ``beats`` and ``bars`` are mutually exclusive.
		- ``steps`` requires ``step_duration``; ``step_duration`` requires ``steps``.
		- ``steps`` cannot be combined with ``beats`` or ``bars``.

		Returns:
			(beat_length, default_grid) - beat_length in beats (quarter notes);
			default_grid the number of grid steps (16th-notes in beat mode, or the
			explicit ``steps`` value directly in step mode).
		"""

		if beats is not None and bars is not None:
			raise ValueError("Specify only one of beats= or bars=")

		if steps is not None and (beats is not None or bars is not None):
			raise ValueError("steps= cannot be combined with beats= or bars=")

		if step_duration is not None and steps is None:
			raise ValueError("step_duration= requires steps= (e.g. steps=6, step_duration=dur.SIXTEENTH)")

		if steps is not None:
			if step_duration is None:
				raise ValueError("steps= requires step_duration= (e.g. step_duration=dur.SIXTEENTH)")
			return steps * step_duration, int(steps)

		if bars is not None:
			raw = bars * beats_per_bar
		elif beats is not None:
			raw = beats
		else:
			raw = default

		return raw, round(raw / subsequence.constants.durations.SIXTEENTH)

	def pattern (
		self,
		channel: int,
		beats: typing.Optional[float] = None,
		bars: typing.Optional[float] = None,
		steps: typing.Optional[float] = None,
		step_duration: typing.Optional[float] = None,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
		nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: float = 1,
		voice_leading: bool = False,
		device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
		min_energy: typing.Optional[float] = None,
	) -> typing.Callable:

		"""
		Register a function as a repeating MIDI pattern.

		The decorated function will be called once per cycle to 'rebuild' its
		content. This allows for generative logic that evolves over time.

		Two ways to specify pattern length:

		- **Duration mode** (default): use ``beats=`` or ``bars=``.
		  The grid defaults to sixteenth-note resolution.
		- **Step mode**: use ``steps=`` paired with ``step_duration=``.
		  The grid equals the step count, so ``p.hit_steps()`` indices map
		  directly to steps.

		Parameters:
			channel: MIDI channel. By default uses 1-based numbering (1-16).
				Set ``zero_indexed_channels=True`` on the ``Composition`` to use
				0-based numbering (0-15), matching the raw MIDI protocol, instead.
			beats: Duration in beats (quarter notes). ``beats=4`` = 1 bar.
			bars: Duration in bars (a bar is ``composition.bar_beats`` - 4 beats in 4/4, 3 in 6/8). ``bars=2`` = 8 beats in 4/4.
			steps: Step count for step mode. Requires ``step_duration=``.
			step_duration: Duration of one step in beats (e.g. ``dur.SIXTEENTH``).
				Requires ``steps=``.
			drum_note_map: Optional mapping for drum instruments.
			cc_name_map: Optional mapping of CC names to MIDI CC numbers.
				Enables string-based CC names in ``p.cc()`` and ``p.cc_ramp()``.
			nrpn_name_map: Optional mapping of NRPN parameter names (strings) to
				14-bit parameter numbers (0–16383).  Enables string-based names
				in ``p.nrpn()`` and ``p.nrpn_ramp()`` - typically a
				device-specific dictionary (e.g. Sequential Take 5's
				``Osc1FreqFine`` → 9).
			reschedule_lookahead: Beats in advance to compute the next cycle.
				At ``0`` each cycle is built on its own first beat, so it hears
				the very latest state (a held chord, a just-moved control) and
				its downbeat sounds late by however long that build takes.
			voice_leading: If True, chords in this pattern will automatically
				use inversions that minimise voice movement.
			mirrors: Optional list of additional ``(device, channel)`` destinations
				to duplicate every event from this pattern onto.  Notes, CCs, pitch
				bend, NRPN/RPN bursts, program changes, SysEx, and drone events are
				all mirrored; OSC events are not (OSC is not bound to a MIDI port).
				``device`` is the integer index returned by ``midi_output()`` (0 =
				primary).  ``channel`` follows this composition's MIDI channel numbering
				convention.  See also ``mirror()`` / ``unmirror()`` for live toggling.
			min_energy: Automatic energy gating - the pattern is silent while
				the current section's energy (``composition.energy()`` dict,
				or the bound Section payload) is below this threshold.
				Composes with ``mute()``: a performer mute always wins.

		Example:
			```python
			@comp.pattern(channel=1, beats=4)
			def chords (p):
				p.chord([60, 64, 67], beat=0, velocity=80, duration=3.9)

			@comp.pattern(channel=1, bars=2)
			def long_phrase (p):
				...

			@comp.pattern(channel=1, steps=6, step_duration=dur.SIXTEENTH)
			def riff (p):
				p.sequence(steps=[0, 1, 3, 5], pitches=60)
			```
		"""

		channel = self._resolve_channel(channel)

		beat_length, default_grid = self._resolve_length(beats, bars, steps, step_duration, beats_per_bar=self.bar_beats)

		# Resolve device string name to index if possible now; otherwise store
		# the raw DeviceId and resolve it in _run() once all devices are open.
		resolved_device: subsequence.midi_utils.DeviceId = device

		# Mirror-to-self check is only reliable when the primary device is a
		# concrete integer at decoration time.  ``None`` resolves to device 0
		# downstream, so we treat it as 0 here too.  Strings are deferred to
		# ``_run()`` and we skip the check for them.
		primary: typing.Optional[typing.Tuple[int, int]]
		if isinstance(resolved_device, str):
			primary = None
		else:
			primary = (resolved_device if resolved_device is not None else 0, channel)
		resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

		def decorator (fn: typing.Callable) -> typing.Callable:

			"""
			Wrap the builder function and register it as a pending pattern.
			During live sessions, hot-swap an existing pattern's builder instead.
			"""

			# Record this declaration so the live-reload deletion diff knows the
			# pattern is still present in the source (see _apply_source_async).
			self._declared_names.add(fn.__name__)

			pending = _PendingPattern(
				builder_fn = fn,
				channel = channel,  # already resolved to 0-indexed
				length = beat_length,
				default_grid = default_grid,
				drum_note_map = drum_note_map,
				cc_name_map = cc_name_map,
				nrpn_name_map = nrpn_name_map,
				reschedule_lookahead = reschedule_lookahead,
				voice_leading = voice_leading,
				# For int/None: resolve immediately.  For str: store 0 as
				# placeholder; _resolve_pending_devices() fixes it in _run().
				device = 0 if (resolved_device is None or isinstance(resolved_device, str)) else resolved_device,
				raw_device = resolved_device,
				mirrors = resolved_mirrors,
				min_energy = min_energy,
			)

			# Live, with a pattern of this name running: this is a save.  Swap
			# in the new body and apply what the declaration changed.
			if self._is_live and fn.__name__ in self._running_patterns:
				self._redeclare(self._running_patterns[fn.__name__], pending, "pattern", _fn_has_parameter(fn, "chord"))
				return fn

			# Names key the seeded stream, mutes, tweaks, and reroll/lock — a
			# duplicate means two scheduled copies sharing one stream with
			# only one reachable by name.  Warn loudly at registration.
			if any(existing.builder_fn.__name__ == fn.__name__ for existing in self._pending_patterns):
				logger.warning(
					f"Duplicate pattern name '{fn.__name__}': both copies will be "
					f"scheduled, they share one seeded stream, and only one is "
					f"reachable by name - rename one of them."
				)

			self._pending_patterns.append(pending)

			return fn

		return decorator

	def _redeclare (self, running: typing.Any, pending: _PendingPattern, kind: str, wants_chord: bool) -> None:

		"""A live save declared a running pattern again: swap in its body and apply what the declaration changed (#2905).

		Only arguments that differ from the last declaration are applied, so a
		save that leaves one alone keeps what the performance did to it: a
		``mirror()``, an ``unmirror()``, a ``set_length()``.  All of it is heard
		from the pattern's next rebuild.  The length, grid and lookahead reach
		the sequencer as ``set_length()``'s do, re-read after each rebuild; the
		channel and mirrors take effect when the next cycle is scheduled, where
		a drone left sounding on a channel the pattern has moved from is
		released.

		The device is the exception.  Opening a MIDI port is slow, and a stall
		where the clock runs is heard, so a changed device waits for a restart
		and says so.  A length the lookahead cannot fit is refused before
		anything changes, so a refused save leaves the pattern as it was.
		"""

		before = running._declared
		name = pending.builder_fn.__name__

		length_changed = (pending.length, pending.default_grid) != (before.length, before.default_grid)
		lookahead_changed = pending.reschedule_lookahead != before.reschedule_lookahead

		length = pending.length if length_changed else running.length
		lookahead = pending.reschedule_lookahead if lookahead_changed else running.reschedule_lookahead

		# The sequencer's own check, so a save is refused as a declaration is.
		if length_changed or lookahead_changed:
			self._sequencer._get_schedule_timing(length, lookahead)

		running._builder_fn = pending.builder_fn
		running._wants_chord = wants_chord
		running._said_no_chord = False

		# In the order that keeps the pair valid at every step, since a rebuild
		# on the clock's thread may read them between the two.
		if lookahead <= running.reschedule_lookahead:
			running.reschedule_lookahead = lookahead
			running.length = length
		else:
			running.length = length
			running.reschedule_lookahead = lookahead

		if length_changed:
			running._default_grid = pending.default_grid
			running._step_beats = pending.length / pending.default_grid if pending.default_grid > 0 else None

		if pending.channel != before.channel:
			running.channel = pending.channel

		if pending.mirrors != before.mirrors:
			running.mirrors[:] = pending.mirrors

		if pending.min_energy != before.min_energy:
			running._min_energy = pending.min_energy

		if pending.drum_note_map != before.drum_note_map:
			running._drum_note_map = pending.drum_note_map

		if pending.cc_name_map != before.cc_name_map:
			running._cc_name_map = pending.cc_name_map

		if pending.nrpn_name_map != before.nrpn_name_map:
			running._nrpn_name_map = pending.nrpn_name_map

		if pending.voice_leading != before.voice_leading:
			running._voice_leading_state = subsequence.voicings.VoiceLeadingState() if pending.voice_leading else None

		if pending.raw_device != before.raw_device:
			logger.warning(
				f"{kind.capitalize()} '{name}' now names a different device, which it moves to when the piece "
				f"restarts: opening a port while the clock runs would be heard. Until then it plays where it was."
			)

		running._declared = pending
		logger.info(f"Hot-swapped {kind}: {name}")

	def layer (
		self,
		*builder_fns: typing.Callable,
		channel: int,
		beats: typing.Optional[float] = None,
		bars: typing.Optional[float] = None,
		steps: typing.Optional[float] = None,
		step_duration: typing.Optional[float] = None,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
		nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: float = 1,
		voice_leading: bool = False,
		device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
	) -> None:

		"""
		Combine multiple functions into a single MIDI pattern.

		This is useful for composing complex patterns out of reusable
		building blocks (e.g., a 'kick' function and a 'snare' function).

		See ``pattern()`` for the full description of ``beats``, ``bars``,
		``steps``, and ``step_duration``.

		Parameters:
			builder_fns: One or more pattern builder functions.
			channel: MIDI channel (1-16, or 0-15 with ``zero_indexed_channels=True``).
			beats: Duration in beats (quarter notes).
			bars: Duration in bars (a bar is ``composition.bar_beats`` - 4 beats in 4/4, 3 in 6/8).
			steps: Step count for step mode. Requires ``step_duration=``.
			step_duration: Duration of one step in beats. Requires ``steps=``.
			drum_note_map: Optional mapping for drum instruments.
			cc_name_map: Optional mapping of CC names to MIDI CC numbers.
			nrpn_name_map: Optional mapping of NRPN parameter names to 14-bit
				parameter numbers.
			reschedule_lookahead: Beats in advance to compute the next cycle.
				At ``0`` each cycle is built on its own first beat, so it hears
				the very latest state (a held chord, a just-moved control) and
				its downbeat sounds late by however long that build takes.
			voice_leading: If True, chords use smooth voice leading.
			mirrors: Optional list of additional ``(device, channel)`` destinations
				to duplicate every event onto.  See ``pattern()`` for details.
		"""

		beat_length, default_grid = self._resolve_length(beats, bars, steps, step_duration, beats_per_bar=self.bar_beats)

		# Resolve channel up-front so the mirror-to-self check has the canonical
		# primary form to compare against.
		resolved_channel = self._resolve_channel(channel)

		# See pattern() for the same comment about None / str handling.
		primary: typing.Optional[typing.Tuple[int, int]]
		if isinstance(device, str):
			primary = None
		else:
			primary = (device if device is not None else 0, resolved_channel)
		resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

		wants_chord = any(_fn_has_parameter(fn, "chord") for fn in builder_fns)

		if wants_chord:

			def merged_builder (p: subsequence.pattern_builder.PatternBuilder, chord: _InjectedChord) -> None:

				for fn in builder_fns:
					if _fn_has_parameter(fn, "chord"):
						fn(p, chord)
					else:
						fn(p)

		else:

			def merged_builder (p: subsequence.pattern_builder.PatternBuilder) -> None:  # type: ignore[misc]

				for fn in builder_fns:
					fn(p)

		# Give the merged builder a stable, unique name derived from its
		# components so multiple layer() calls don't all register under
		# "merged_builder" and collide in _running_patterns (which made
		# mute/tweak/unregister/live_info reach only the LAST layer).  "+" can't
		# appear in a Python identifier, so this never clashes with a real
		# pattern function's name.
		base_name = ("+".join(fn.__name__ for fn in builder_fns) or "layer") + f"@ch{resolved_channel}"
		merged_name = base_name
		suffix = 2

		# Two layers with the same components (e.g. on different saves of a
		# live file) must map to the same names pass-over-pass, while two
		# DIFFERENT layers sharing components in one pass must not collide.
		while merged_name in self._declared_names:
			merged_name = f"{base_name}#{suffix}"
			suffix += 1

		merged_builder.__name__ = merged_name

		# Record the declaration for the live-reload deletion diff, and hot-swap
		# in place when this layer is already running so a reload picks up edits
		# to the component functions without losing the pattern's cycle count,
		# tweaks, or mirrors (mirrors the pattern() decorator's hot-swap).
		self._declared_names.add(merged_builder.__name__)

		pending = _PendingPattern(
			builder_fn = merged_builder,
			channel = resolved_channel,  # already resolved to 0-indexed above
			length = beat_length,
			default_grid = default_grid,
			drum_note_map = drum_note_map,
			cc_name_map = cc_name_map,
			nrpn_name_map = nrpn_name_map,
			reschedule_lookahead = reschedule_lookahead,
			voice_leading = voice_leading,
			mirrors = resolved_mirrors,
			device = 0 if (device is None or isinstance(device, str)) else device,
			raw_device = device,
		)

		if self._is_live and merged_builder.__name__ in self._running_patterns:
			self._redeclare(self._running_patterns[merged_builder.__name__], pending, "layer", wants_chord)
			return

		self._pending_patterns.append(pending)

	def chords (
		self,
		*,
		channel: int,
		progression: subsequence.progressions.ProgressionSource,
		harmonic_rhythm: subsequence.progressions.HarmonicRhythmSpec,
		bars: typing.Optional[float] = None,
		beats: typing.Optional[float] = None,
		voicing: subsequence.progressions.VoicingSpec = (3, 4),
		velocity: typing.Union[int, typing.Tuple[int, int]] = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY,
		detached: typing.Optional[float] = None,
		root: int = 60,
		key: typing.Optional[str] = None,
		seed: typing.Optional[int] = None,
		device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
	) -> subsequence.progressions.Progression:

		"""Declare a self-contained chord part: a progression at a chosen harmonic rhythm.

		The one-call form of ``p.progression()`` - it registers a pattern on
		MIDI channel ``channel`` that plays ``progression`` across ``bars`` (or ``beats``), each chord
		lasting a length drawn from ``harmonic_rhythm`` (the musical term for how often
		the chords change).  It needs no ``composition.harmony()`` call and, with an
		explicit chord list or a ``key=``, no composition key either - so a
		drums-plus-one-chord-part sketch stays simple.

		The progression is realised once, up front, and the same timeline plays every
		cycle (a stable phrase).  That timeline is returned so you can see exactly what
		was chosen - ``print(comp.chords(...))``.

		Parameters:
			channel: MIDI channel for the chord part.
			progression: A chord-graph style name to generate from, or an explicit list
				of chords (``Chord`` objects or names like ``["Cm7", "Dbmaj7"]``).
			harmonic_rhythm: How long each chord lasts - a number, a list of lengths,
				or ``between(low, high, step=...)``.  See ``p.progression()``.
			bars / beats: Length of the part (defaults to 4 beats if neither is given).  ``bars`` uses the
				composition's time signature.
			voicing: Notes per chord - an int, or a ``(low, high)`` range (e.g. ``(3, 4)``).
			velocity: MIDI velocity, or a ``(low, high)`` tuple for per-voice humanisation.
			detached: Beats of silence before each next chord (``duration = length - detached``).
			root: MIDI root the voicings are centred on (e.g. 48 = C3).
			key: Key for a generated progression; defaults to the composition key.
			seed: Seed for the (otherwise fixed) realisation; defaults to the
				composition seed, so the part is reproducible.
			device: Optional output-device override.
			mirrors: Optional additional ``(device, channel)`` destinations.

		Returns:
			The realised :class:`~subsequence.progressions.Progression`.
		"""

		beat_length, default_grid = self._resolve_length(beats, bars, None, None, beats_per_bar=self.bar_beats)
		resolved_channel = self._resolve_channel(channel)
		resolved_key = key if key is not None else self.key

		rng = random.Random(seed if seed is not None else self._seed)
		timeline = subsequence.progressions.realize(
			source = progression,
			harmonic_rhythm = harmonic_rhythm,
			key = resolved_key,
			length = beat_length,
			rng = rng,
			scale = self.scale or "ionian",
		)

		captured_root = root
		captured_velocity = velocity
		captured_detached = detached
		captured_voicing = voicing

		def chords_builder (p: subsequence.pattern_builder.PatternBuilder) -> None:

			"""Replay the realised timeline as block chords each cycle (voicing per chord)."""

			for chord, start, length in timeline:
				ring = length - captured_detached if (captured_detached and captured_detached < length) else length
				voices = subsequence.progressions.resolve_voices(captured_voicing, p.rng)
				p.chord(chord, root=captured_root, beat=start, duration=ring, count=voices, velocity=captured_velocity)

		# Unique, stable name so multiple chord parts don't collide in
		# _running_patterns — including two parts on the SAME channel, which
		# get a deterministic #2/#3 suffix in declaration order.
		base_name = f"chords@ch{resolved_channel}"
		chords_name = base_name
		suffix = 2

		while chords_name in self._declared_names:
			chords_name = f"{base_name}#{suffix}"
			suffix += 1

		chords_builder.__name__ = chords_name
		self._declared_names.add(chords_name)

		primary: typing.Optional[typing.Tuple[int, int]]
		if isinstance(device, str):
			primary = None
		else:
			primary = (device if device is not None else 0, resolved_channel)
		resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

		pending = _PendingPattern(
			builder_fn = chords_builder,
			channel = resolved_channel,
			length = beat_length,
			default_grid = default_grid,
			drum_note_map = None,
			reschedule_lookahead = 1,
			voice_leading = False,
			mirrors = resolved_mirrors,
			device = 0 if (device is None or isinstance(device, str)) else device,
			raw_device = device,
		)

		if self._is_live and chords_builder.__name__ in self._running_patterns:
			self._redeclare(self._running_patterns[chords_builder.__name__], pending, "chords", False)
			return timeline
		self._pending_patterns.append(pending)
		return timeline

	def phrase_part (
		self,
		*,
		channel: int,
		part: typing.Optional[str] = None,
		root: int = 60,
		bars: typing.Optional[float] = None,
		beats: typing.Optional[float] = None,
		velocity: typing.Optional[typing.Union[int, typing.Tuple[int, int]]] = None,
		fit: typing.Optional[float] = None,
		device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
	) -> None:

		"""Declare a part that plays each section's bound Motif/Phrase.

		The one-call consumer for :meth:`section_motifs` - it registers a
		pattern on MIDI channel ``channel`` that walks whatever value is bound to the
		current section for ``part`` (stateless position from the cycle
		counter, via ``p.phrase()``).  A section with no binding for the
		part is **silent** for that part - bind material or don't; no
		fallback guessing.

		Parameters:
			channel: MIDI channel for the part.
			part: The part label to read from the registry (``None`` = the
				unlabelled binding).
			root: Register anchor for degree resolution.
			bars / beats: Cycle length of the part (defaults to 4 beats);
				the phrase is sliced one cycle window at a time.
			velocity: Optional override applied to every note.
			fit: Passed through (active with the melody engine stage).
			device: Optional output-device override.
			mirrors: Optional additional ``(device, channel)`` destinations.

		Example::

			composition.section_motifs("verse",  verse_line,  part="lead")
			composition.section_motifs("chorus", chorus_line, part="lead")
			composition.phrase_part(channel=4, part="lead", root=72, bars=2)
		"""

		beat_length, default_grid = self._resolve_length(beats, bars, None, None, beats_per_bar=self.bar_beats)
		resolved_channel = self._resolve_channel(channel)

		captured_part = part
		captured_root = root
		captured_velocity = velocity
		captured_fit = fit

		def phrase_builder (p: subsequence.pattern_builder.PatternBuilder) -> None:

			"""Walk the current section's bound value (silent when unbound)."""

			value = p.section_motif(captured_part)

			if value is None:
				return	# unbound section: silence for this part, by design

			p.phrase(value, root=captured_root, velocity=captured_velocity, fit=captured_fit)

		# Unique, stable name so multiple phrase parts don't collide —
		# including two parts on the SAME channel (deterministic #2/#3
		# suffixes in declaration order, the chords() convention).
		base_name = f"phrase@{captured_part}@ch{resolved_channel}" if captured_part else f"phrase@ch{resolved_channel}"
		phrase_name = base_name
		suffix = 2

		while phrase_name in self._declared_names:
			phrase_name = f"{base_name}#{suffix}"
			suffix += 1

		phrase_builder.__name__ = phrase_name
		self._declared_names.add(phrase_name)

		primary: typing.Optional[typing.Tuple[int, int]]
		if isinstance(device, str):
			primary = None
		else:
			primary = (device if device is not None else 0, resolved_channel)
		resolved_mirrors = self._resolve_mirrors(mirrors, primary=primary)

		pending = _PendingPattern(
			builder_fn = phrase_builder,
			channel = resolved_channel,
			length = beat_length,
			default_grid = default_grid,
			drum_note_map = None,
			reschedule_lookahead = 1,
			voice_leading = False,
			mirrors = resolved_mirrors,
			device = 0 if (device is None or isinstance(device, str)) else device,
			raw_device = device,
		)

		# A live save applies what it changed, as every declaration does (#2961).
		if self._is_live and phrase_builder.__name__ in self._running_patterns:
			self._redeclare(self._running_patterns[phrase_builder.__name__], pending, "phrase part", False)
			return

		self._pending_patterns.append(pending)

	def trigger (
		self,
		fn: typing.Callable,
		channel: int,
		beats: typing.Optional[float] = None,
		bars: typing.Optional[float] = None,
		steps: typing.Optional[float] = None,
		step_duration: typing.Optional[float] = None,
		quantize: float = 0,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		cc_name_map: typing.Optional[typing.Dict[str, int]] = None,
		nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None,
		chord: bool = False,
		device: subsequence.midi_utils.DeviceId = None,
		mirrors: typing.Optional[typing.Iterable[subsequence.pattern.MirrorSpec]] = None,
	) -> None:

		"""
		Trigger a one-shot pattern immediately or on a quantised boundary.

		This is useful for real-time response to sensors, OSC messages, or other
		external events. The builder function is called immediately with a fresh
		PatternBuilder, and the generated events are injected into the queue at
		the boundary ``quantize`` names.

		The builder function has the same API as a ``@composition.pattern``
		decorated function and can use all PatternBuilder methods: ``p.note()``,
		``p.euclidean()``, ``p.arpeggio()``, and so on.

		See ``pattern()`` for the full description of ``beats``, ``bars``,
		``steps``, and ``step_duration``. Default is 1 beat.

		Parameters:
			fn: The pattern builder function (same signature as ``@comp.pattern``).
			channel: MIDI channel (1-16, or 0-15 with ``zero_indexed_channels=True``).
			beats: Duration in beats (quarter notes, default 1).
			bars: Duration in bars (a bar is ``composition.bar_beats`` - 4 beats in 4/4, 3 in 6/8).
			steps: Step count for step mode. Requires ``step_duration=``.
			step_duration: Duration of one step in beats. Requires ``steps=``.
			quantize: Snap the trigger to a beat boundary: ``0`` = immediate (default),
				``1`` = next beat (quarter note), ``4`` = the next multiple of four
				beats, which is the next bar in 4/4.  ``composition.bar_beats`` is
				the next bar in any metre.  Use ``dur.*`` constants from
				``subsequence.constants.durations``.
			drum_note_map: Optional drum name mapping for this pattern.
			cc_name_map: Optional mapping of CC names to MIDI CC numbers.
			nrpn_name_map: Optional mapping of NRPN parameter names to
				14-bit parameter numbers.
			chord: If ``True``, the builder function receives the current chord as
				a second parameter (same as ``@composition.pattern``).
			mirrors: Optional list of additional ``(device, channel)`` destinations
				to fire this one-shot onto in parallel with the primary destination.

		Example:
			```python
			# Immediate single note (channels are 1-16 by default)
			composition.trigger(
				lambda p: p.note(60, beat=0, velocity=100, duration=0.5),
				channel=1
			)

			# Quantized fill, on the next bar in any metre - channel 10 is
			# the GM drum channel
			import subsequence.constants.durations as dur
			composition.trigger(
				lambda p: p.euclidean("snare", pulses=7, velocity=90),
				channel=10,
				drum_note_map=gm_drums.GM_DRUM_MAP,
				quantize=composition.bar_beats
			)

			# With chord context - the builder receives the chord as a second
			# argument when chord=True.
			composition.trigger(
				lambda p, chord: p.arpeggio(chord.tones(root=60), spacing=dur.SIXTEENTH),
				channel=1,
				quantize=dur.QUARTER,
				chord=True
			)
			```
		"""

		# Resolve channel numbering
		resolved_channel = self._resolve_channel(channel)

		beat_length, default_grid = self._resolve_length(beats, bars, steps, step_duration, default=1.0, beats_per_bar=self.bar_beats)

		# Resolve device index — for trigger() this is always concrete by call time,
		# so the mirror-to-self check has the full primary tuple available.
		resolved_device_idx = self._resolve_device_id(device)
		resolved_mirrors = self._resolve_mirrors(mirrors, primary=(resolved_device_idx, resolved_channel))

		# Everything from here reads or changes what the clock reads - the pulse
		# count, the form, the harmony plan, the seeded streams, the held notes -
		# and runs the performer's builder, which every pattern runs on the loop.
		# From another thread it ran there instead (#3383), so it is made on the
		# clock; the checks above are not, so a bad argument is heard at once.
		def _fire () -> None:

			# A one-shot's randomness follows the composition's seed, so a seeded
			# piece renders the same file twice (decision 13 of #2991). The stream
			# is named for the function and for how many times it has fired, so
			# two triggers in a bar differ from each other and the tenth differs
			# from the first — while an unseeded composition keeps fresh
			# randomness, as it does everywhere else.
			trigger_name = getattr(fn, "__name__", "trigger")
			self._trigger_counts[trigger_name] = self._trigger_counts.get(trigger_name, 0) + 1
			trigger_rng = self._stream(
				f"trigger:{trigger_name}:{self._trigger_counts[trigger_name]}"
			) or random.Random()

			# Create a temporary Pattern
			pattern = subsequence.pattern.Pattern(channel=resolved_channel, length=beat_length, device=resolved_device_idx, mirrors=resolved_mirrors)

			# Calculate the start pulse based on quantize, before the build, so the
			# builder knows where on the song's timeline it will play (a groove
			# counts its slots from there, #2788).
			current_pulse = self._sequencer.pulse_count
			pulses_per_beat = subsequence.constants.MIDI_QUARTER_NOTE

			if quantize == 0:
				# Immediate: use current pulse
				start_pulse = current_pulse

			else:
				# Quantize to the next multiple of (quantize * pulses_per_beat)
				quantize_pulses = subsequence.constants.pulses.beats_to_pulses(quantize, pulses_per_beat)
				start_pulse = ((current_pulse // quantize_pulses) + 1) * quantize_pulses

			pattern._cycle_start_pulse = start_pulse

			# Resolve the section context once: the one-shot inherits the section's
			# effective key/scale (so a triggered degree resolves like everywhere
			# else) and a harmony view at the current playhead (so ChordTone /
			# Approach resolve too).
			trigger_section = self._form_state.get_section_info() if self._form_state else None
			trigger_key, trigger_scale = self._effective_key_scale(trigger_section)

			# Anchor the view where the one-shot LANDS, not where trigger() was
			# called (#3087).  start_pulse is already computed above for exactly
			# this reason - the builder is meant to know where on the song's
			# timeline it will play - and the harmony was the one thing still
			# reading the playhead.  Quantized to the next bar, every one-shot was
			# built against the bar before its own.
			start_beat = start_pulse / pulses_per_beat

			trigger_harmony: typing.Optional[HarmonyView] = None
			if not self._harmony_horizon.is_empty:
				trigger_harmony = HarmonyView(self._harmony_horizon, start_beat)

			# Create a PatternBuilder
			builder = subsequence.pattern_builder.PatternBuilder(
				pattern=pattern,
				cycle=0,  # One-shot patterns don't rebuild, so cycle is always 0
				drum_note_map=drum_note_map,
				cc_name_map=cc_name_map,
				nrpn_name_map=nrpn_name_map,
				section=trigger_section,
				bar=self._builder_bar,
				conductor=self.conductor,
				rng=trigger_rng,
				tweaks={},
				default_grid=default_grid,
				data=self.data,
				# A one-shot resolves key-relative content against the same
				# effective key/scale as the section it fires into (previously
				# omitted entirely — degrees raised even in a keyed composition).
				key=trigger_key,
				scale=trigger_scale,
				time_signature=self.time_signature,
				held_notes=self._sequencer._held_notes,
				harmony=trigger_harmony,
				energy=self._current_energy(trigger_section),
				zero_indexed_channels=self._zero_indexed_channels,
			)

			# Call the builder function
			try:

				current_chord = self._chord_sounding_at(start_beat) if chord else None

				if current_chord is not None:
					injected = _InjectedChord(current_chord, None)  # No voice leading for one-shots
					fn(builder, injected)

				else:
					fn(builder)

				builder._finish_build()
				self._apply_composition_tuning(pattern, builder, drum_note_map, part = None)

			except Exception:
				logger.exception("Error in trigger builder - pattern will be silent")
				return

			self._schedule_one_shot(pattern, start_pulse)

		self._sequencer._on_the_clock(_fire)

	def _schedule_one_shot (self, pattern: subsequence.pattern.Pattern, start_pulse: int) -> None:

		"""Schedule a one-shot pattern at an absolute pulse, thread-safely."""

		try:
			# Probe only: raises RuntimeError when not on the event loop.
			asyncio.get_running_loop()
			asyncio.create_task(self._sequencer.schedule_pattern(pattern, start_pulse))

		except RuntimeError:
			# Not on the event loop — hand the coroutine to the loop thread.
			if self._sequencer._event_loop is not None:
				asyncio.run_coroutine_threadsafe(
					self._sequencer.schedule_pattern(pattern, start_pulse),
					loop=self._sequencer._event_loop
				)
			else:
				logger.warning("trigger() called before playback started; pattern ignored")

	@property
	def is_clock_following (self) -> bool:

		"""True if either the primary or any additional device is following external clock."""

		return self._clock_follow or any(cf for _, _, cf in self._additional_inputs)


	# Hidden from mypy on purpose: a __getattr__ it could see would make any
	# attribute name valid on a Composition, typos included.
	if not typing.TYPE_CHECKING:

		def __getattr__ (self, name: str) -> typing.Any:

			"""Say what replaced a retired method, not only that it is missing (#3530)."""

			if name in _RETIRED_METHODS:
				raise AttributeError(_RETIRED_METHODS[name])

			raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

	def play (self) -> None:

		"""
		Start the composition.

		This call blocks until the program is interrupted (e.g., via Ctrl+C).
		It initialises the MIDI hardware, launches the background sequencer,
		and begins playback.

		A Composition runs once: the performance closes its ports and takes
		its patterns with it, so a second ``play()`` or ``render()`` raises.
		Build a new Composition per take - see :meth:`render` for the shape.

		Raises:
			RuntimeError: If this Composition has already played or rendered.
		"""

		try:
			subsequence.sequencer.run(self._run())

		except KeyboardInterrupt:
			pass


	def render (self, bars: typing.Optional[int] = None, filename: str = "render.mid", max_minutes: typing.Optional[float] = 60.0) -> None:

		"""Render the composition to a MIDI file without real-time playback.

		Runs the sequencer as fast as possible (no timing delays) and stops
		when the first active limit is reached.  The result is saved as a
		standard MIDI file that can be imported into any DAW: it opens with the
		composition's time signature and starting tempo, and a tempo change is
		written where it happens, so the DAW's bar lines fall where the music's do.
		The file lasts exactly as long as the render, and a note still sounding at
		its end is released there.

		All patterns, scheduled callbacks, and harmony logic run exactly as
		they would during live playback - BPM transitions, generative fills,
		and probabilistic gates all work in render mode.  The only differences
		are that time is simulated rather than wall-clock driven, and that each
		call of a function given to ``schedule()`` finishes before the render
		moves on, so a seeded render is the same file every time.

		A render reaches no MIDI device.  It sends nothing and opens no input,
		and it keeps its own clock whatever ``clock_follow`` or ``link()`` asked
		for.  So a piece written for a controller renders without it, as though
		no control had moved.

		Parameters:
			bars: Number of bars to render, or ``None`` for no bar limit
			      (default ``None``).  When both *bars* and *max_minutes* are
			      active, playback stops at whichever limit is reached first.
			filename: Output MIDI filename (default ``"render.mid"``).
			max_minutes: Safety cap on the length of rendered MIDI in minutes
			             (default ``60.0``).  Pass ``None`` to disable the time
			             cap - you must then provide an explicit *bars* value.

		Raises:
			ValueError: If both *bars* and *max_minutes* are ``None``, which
			            would produce an infinite render.

		Examples:
			```python
			# Default: renders up to 60 minutes of MIDI content.
			composition.render()

			# Render exactly 64 bars (time cap still active as backstop).
			composition.render(bars=64, filename="demo.mid")

			# Render up to 5 minutes of an infinite generative composition.
			composition.render(max_minutes=5, filename="five_min.mid")

			# Remove the time cap - must supply bars instead.
			composition.render(bars=128, max_minutes=None, filename="long.mid")
			```

			A Composition renders once.  For several takes, build one each
			time - a function that returns a fresh Composition is the whole
			trick, and it keeps each take's seed honest:

			```python
			def take (seed):
				composition = subsequence.Composition(bpm=120, key="A", scale="minor", seed=seed)
				# … patterns, harmony, form …
				return composition

			for seed in (1, 2, 3):
				take(seed).render(bars=32, filename=f"take_{seed}.mid")
			```

		Raises:
			RuntimeError: If this Composition has already played or rendered.
		"""

		if bars is None and max_minutes is None:
			raise ValueError(
				"render() requires at least one limit: provide bars=, max_minutes=, or both. "
				"Passing both as None would produce an infinite render."
			)

		# Zero and below used to reach the engine as its own "no bar limit"
		# sentinel, so render(bars=0, max_minutes=None) never returned and
		# filled memory while it did not.  A bar count is a number of bars.
		if bars is not None and (not isinstance(bars, int) or isinstance(bars, bool) or bars < 1):
			raise ValueError(
				f"render(bars={bars!r}) needs a whole number of bars, 1 or more. "
				f"For no bar limit, leave bars out and give max_minutes= instead."
			)

		if max_minutes is not None and (max_minutes <= 0 or max_minutes != max_minutes):
			raise ValueError(
				f"render(max_minutes={max_minutes!r}) needs a length above zero. "
				f"For no time limit, pass max_minutes=None and give bars= instead."
			)

		self._sequencer.recording = True
		self._sequencer.record_filename = filename
		self._sequencer.render_mode = True
		self._sequencer.render_bars = bars if bars is not None else 0
		self._sequencer.render_max_seconds = max_minutes * 60.0 if max_minutes is not None else None
		subsequence.sequencer.run(self._run())

	def _broadcast_osc_status (self, bar: int) -> None:

		"""
		Send the per-bar OSC status snapshot: bar number, current tempo,
		and (when active) the current chord name and form section.
		"""

		if self._osc_server:
			self._osc_server.send("/bar", bar)
			self._osc_server.send("/bpm", self._sequencer.current_bpm)

			sounding = self.current_chord()
			if sounding is not None:
				self._osc_server.send("/chord", sounding.name())

			if self._form_state:
				info = self._form_state.get_section_info()
				if info:
					self._osc_server.send("/section", info.name)

	def _open_output_devices (self) -> None:

		"""Open every output device, the primary first so it holds device 0.

		A render opens nothing at all: it writes a file, and the rig is usually
		playing something else (#2995).  Every device is registered as a silent
		placeholder instead, so ``device=``, aliases and mirrors resolve exactly
		as they would in a performance, and the rendered file carries what each
		part plays (#2964, #2997).

		A device that will not open keeps its number the same way, which is what
		holds the numbering together for everything after it (#2997).
		"""

		if self._sequencer.render_mode:

			self._sequencer.add_output_device(
				self._sequencer.output_device_name or self._requested_output_device or "render",
				None,
				self._output_latency_ms,
			)

			for out in self._additional_outputs:
				idx = self._sequencer.add_output_device(out.device, None, out.latency_ms)
				self._output_device_names.setdefault(out.device, idx)

				if out.alias is not None:
					self._output_device_names[out.alias] = idx

			logger.info("Rendering: no MIDI port is opened, and nothing is sent to a device.")

			to_open: typing.List[_AdditionalOutput] = []

		else:

			self._sequencer._init_midi_output()
			to_open = list(self._additional_outputs)

		# The primary answers to the name it was opened under and to the string
		# that asked for it — a partial or wildcard name opens a port under the
		# port's own full name, and `device="what I asked for"` used to route to
		# device 0 (#2964).  Its latency needs the device to exist, which it now
		# does either way.
		if self._sequencer.output_device_name:
			self._output_device_names[self._sequencer.output_device_name] = 0

		if self._requested_output_device:
			self._output_device_names.setdefault(self._requested_output_device, 0)

		if self._output_latency_ms and len(self._sequencer._output_devices):
			self._sequencer.set_device_latency(0, self._output_latency_ms)

		for out in to_open:
			open_name, port = subsequence.midi_utils.select_output_device(out.device)
			if open_name and port is not None:
				idx = self._sequencer.add_output_device(open_name, port, out.latency_ms)
				self._output_device_names[open_name] = idx
				# As for the primary: the name midi_output() was given keeps
				# addressing it, wildcards and partial names included (#2964).
				self._output_device_names.setdefault(out.device, idx)
				if out.alias is not None:
					self._output_device_names[out.alias] = idx
			else:
				# A device that will not open keeps its number as a silent
				# placeholder, so `device=2` still means the third device the
				# composition declared and no part is quietly re-routed to a
				# neighbour or dropped for an index that no longer exists
				# (#2997).  Its name and alias resolve here too, so a part
				# addressed by name is silent rather than landing on device 0.
				idx = self._sequencer.add_output_device(out.device, None, out.latency_ms)
				self._output_device_names.setdefault(out.device, idx)

				if out.alias is not None:
					self._output_device_names[out.alias] = idx

				logger.warning(
					"Could not open additional output device '%s' - it keeps device %d and stays silent, "
					"so every other device keeps its own number.",
					out.device, idx,
				)

	async def _run (self) -> None:

		"""
		Async entry point that schedules all patterns and runs the sequencer.
		"""

		# A Composition is a take, not a machine you can restart: the first run
		# closes and clears the port registry, empties _pending_patterns and
		# leaves the render flags set, so a second one used to do nothing at
		# all — and once stop() was fixed it would have written the first
		# take's notes again, because recorded_events are never cleared.
		# Say so instead (#2994, decision 5 of #2991).
		if self._has_run:
			raise RuntimeError(
				"this Composition has already played or rendered - a Composition runs once. "
				"Build a new one per take: put the setup in a function and call it again "
				"(the render() docstring shows one)."
			)

		self._has_run = True

		# 1. Pre-calculate MIDI input indices and configure sequencer clock follow.
		if self._input_device is not None:
			self._sequencer.input_device_name = self._input_device
			self._sequencer.clock_follow = self._clock_follow
			self._sequencer.clock_device_idx = 0

			if not self._clock_follow:
				# Find first additional input that wants to be the clock master.
				for idx, (_, _, cf) in enumerate(self._additional_inputs, start=1):
					if cf:
						self._sequencer.clock_follow = True
						self._sequencer.clock_device_idx = idx
						break

		# Populate input device name mapping early (before opening ports) so we can
		# resolve CC mappings to integer device indices immediately.
		if self._sequencer.input_device_name:
			self._input_device_names[self._sequencer.input_device_name] = 0
			if self._input_device_alias is not None:
				self._input_device_names[self._input_device_alias] = 0

		for idx, (dev_name, alias, _) in enumerate(self._additional_inputs, start=1):
			self._input_device_names[dev_name] = idx
			if alias:
				self._input_device_names[alias] = idx

		# 2. The primary's name and latency are wired in step 6 instead, where
		# the port is opened — it is no longer open by now, because building a
		# Composition must not touch a device (#2995).

		# 3. Resolve name-based INPUT device ids in cc_map/cc_forward early — the
		# input-names map is fully populated above, and the callback thread needs
		# integer indices as soon as ports open.  OUTPUT names (cc_forward
		# output_device=, pattern device=) resolve after the additional outputs
		# are opened below; resolving them here matched against a map containing
		# only the primary and silently routed everything to device 0.
		for mapping in self._cc_mappings:
			raw = mapping.get('input_device')
			if isinstance(raw, str):
				mapping['input_device'] = self._resolve_input_device_id(raw)
		for fwd in self._cc_forwards:
			raw_in = fwd.get('input_device')
			if isinstance(raw_in, str):
				fwd['input_device'] = self._resolve_input_device_id(raw_in)

		# 4. Share CC input mappings, forwards, and a reference to composition.data
		# with the sequencer BEFORE opening the ports. This ensures that any initial
		# messages in the OS buffer are correctly mapped as soon as the port opens.
		self._sequencer.cc_mappings = self._cc_mappings
		self._sequencer.cc_forwards = self._cc_forwards
		self._sequencer._composition_data = self.data

		# Held-note input: create the tracker and resolve its channel/device
		# filter so the callback thread can buffer matching note events.
		if self._note_input is not None:
			if self._input_device is None and not self._additional_inputs:
				raise RuntimeError("note_input() requires a MIDI input - call composition.midi_input(device) first")
			raw_dev = self._note_input.get('input_device')
			if isinstance(raw_dev, str):
				raw_dev = self._resolve_input_device_id(raw_dev)
			self._sequencer._note_input_channel = self._note_input['channel']
			self._sequencer._note_input_device = raw_dev
			self._sequencer._held_notes = subsequence.held_notes.HeldNotes(
				release_ms = self._note_input['release_ms'],
				latch = self._note_input['latch'],
			)

		# 5. Open MIDI input ports early. Even without a deliberate sleep, opening
		# them before pattern building minimizes the window for missed messages.
		# A render opens none (#3485): see Sequencer._open_midi_inputs().
		# Primary input
		self._sequencer._open_midi_inputs()

		# Additional inputs
		additional_inputs = [] if self._sequencer.render_mode else self._additional_inputs

		for idx, (dev_name, alias, cf) in enumerate(additional_inputs, start=1):
			# Use the pre-calculated index
			callback = self._sequencer._make_input_callback(idx)
			open_name, port = subsequence.midi_utils.select_input_device(dev_name, callback)
			if open_name and port is not None:
				self._sequencer.add_input_device(open_name, port)
			else:
				logger.warning(f"Could not open additional input device '{dev_name}'")

		# 6. Open the output devices.  See _open_output_devices().
		self._open_output_devices()

		# Warn if latency compensation adds noticeable whole-rig delay: the
		# slowest device defines the alignment point, so every faster device is
		# delayed up to that amount and live-input feel suffers.
		self._warn_if_high_latency()

		# Resolve any name-based output device IDs on patterns that may have been added
		# for additional output devices.
		self._resolve_pending_devices()

		# Resolve cc_forward output-device names now that every output port and
		# alias is registered (resolving earlier silently routed to device 0).
		for fwd in self._cc_forwards:
			raw_out = fwd.get('output_device')
			if isinstance(raw_out, str):
				fwd['output_device'] = self._resolve_device_id(raw_out)

		# Pass clock output flag (suppressed automatically when clock_follow=True).
		self._sequencer.clock_output = self._clock_output and not self.is_clock_following

		# A render runs on its own simulated clock, whatever the piece asked
		# for: following an external clock would wait for ticks that never
		# come, and a Link session would put the render in the room's tempo —
		# and in the room (#2995).  Said once, because it changes what the
		# file is.
		if self._sequencer.render_mode:

			ignored = [
				name
				for name, asked in (("clock_follow", self.is_clock_following), ("link()", self._link_quantum is not None))
				if asked
			]

			if ignored:
				logger.info(
					"Rendering on the internal clock: %s %s ignored for this render.",
					" and ".join(ignored),
					"is" if len(ignored) == 1 else "are",
				)

			self._sequencer.clock_follow = False
			self._sequencer.clock_output = False

		# Create Ableton Link clock if comp.link() was called.
		elif self._link_quantum is not None:
			self._sequencer._link_clock = subsequence.link_clock.LinkClock(
				bpm = self.bpm,
				quantum = self._link_quantum,
				loop = asyncio.get_running_loop(),
			)

		# Deal play-time streams.  Every stream is NAME-keyed (crc32 of
		# "seed:name", see _stream_seed) rather than dealt from one master in
		# registration order: adding or removing one consumer can never shift
		# another's stream, and patterns added live derive identically in
		# _build_pattern_from_pending.  When no seed is set, components keep
		# their own unseeded RNGs (existing behaviour).
		if self._seed is not None:

			harmony_stream = self._stream("play:harmony")
			if self._harmonic_state is not None and harmony_stream is not None:
				self._harmonic_state.rng = harmony_stream

			form_stream = self._stream("play:form")
			if self._form_state is not None and form_stream is not None:
				self._form_state._rng = form_stream

		# The clocks fire BEFORE pattern rebuilds at the same pulse, and their
		# lookahead is RAISED to the maximum pattern lookahead (never patterns
		# clamped down): when a pattern rebuilds for its next cycle, the form
		# state and the harmony window already describe that cycle.
		bar_beats = self.bar_beats

		pattern_lookaheads = [pending.reschedule_lookahead for pending in self._pending_patterns]
		pattern_lookaheads += [pattern.reschedule_lookahead for pattern in self._running_patterns.values()]
		max_pattern_lookahead = max(pattern_lookaheads, default = 0)

		clock_lookahead = max(1.0, float(self._harmony_reschedule_lookahead), float(max_pattern_lookahead))

		# Only a pattern's own lookahead is worth a warning.  The clocks' one-beat
		# floor and harmony()'s lookahead simply fit a bar shorter than a beat
		# (3/16, 1/8), where no pattern is at risk.
		if max_pattern_lookahead > bar_beats:
			logger.warning(
				"A pattern's reschedule_lookahead (%.2g beats) exceeds the bar length (%.2g) - "
				"the harmony/form clocks fire at most one bar ahead, so that pattern may "
				"rebuild before the window covers its cycle start.",
				max_pattern_lookahead, bar_beats,
			)

		clock_lookahead = min(clock_lookahead, bar_beats)

		# Minimum span >= maximum lookahead: the clock cannot prepare a chord
		# boundary that arrives sooner than it fires.  Harmonic motion faster
		# than this floor stays available at the part level (p.progression),
		# where placement is not clock-bound.
		def _check_span_floor (progression: typing.Optional[Progression], label: str) -> None:
			if progression is None:
				return
			shortest = min(span.beats for span in progression.spans)
			if shortest < clock_lookahead - 1e-9:
				raise ValueError(
					f"{label}: shortest chord span ({shortest:g} beats) is below the clock "
					f"lookahead ({clock_lookahead:g} beats - the largest pattern lookahead). "
					"Lengthen the span, lower the pattern lookaheads, or place fast harmony "
					"at the part level with p.progression()."
				)

		_check_span_floor(self._bound_progression, "harmony(progression=)")
		for section_name, section_progression in self._section_progressions.items():
			_check_span_floor(section_progression, f"section_chords({section_name!r})")

		# Key-relative section progressions resolve late, per occurrence — so
		# verify they WILL resolve now, before playback, rather than surfacing
		# a silent skip (or a dead clock) mid-render.  For each occurrence's
		# effective key+scale: a missing key, or a degree/scale that does not
		# resolve, is raised here with an actionable message.
		fs = self._form_state

		for section_name, section_progression in self._section_progressions.items():
			if section_progression.is_concrete:
				continue

			# The (key, scale) contexts this section may be resolved against.
			contexts: typing.List[typing.Tuple[typing.Optional[str], typing.Optional[str]]] = []
			if fs is not None and fs._sequence is not None and any(s.name == section_name for s in fs._sequence):
				for section in fs._sequence:
					if section.name != section_name:
						continue
					ctx = (section.key or self._form_key or self.key, section.scale or self._form_scale or self.scale)
					if ctx not in contexts:
						contexts.append(ctx)
			else:
				contexts.append((self._form_key or self.key, self._form_scale or self.scale))

			for ctx_key, ctx_scale in contexts:
				if ctx_key is None:
					raise ValueError(
						f"section_chords({section_name!r}) is key-relative (degrees/romans) but no key "
						"resolves for it - set key= on the Composition, a form key (form(key=...)), or "
						f"a Section.key on every {section_name!r} section."
					)
				try:
					section_progression.resolve(ctx_key, ctx_scale or "ionian")
				except ValueError as error:
					raise ValueError(
						f"section_chords({section_name!r}) does not resolve against its effective key "
						f"{ctx_key} {ctx_scale or 'ionian'}: {error}"
					)

		# min_energy with nothing feeding p.energy is a silent no-op — warn loudly.
		energy_gated = [p.builder_fn.__name__ for p in self._pending_patterns if p.min_energy is not None]

		if energy_gated and not self._energy_map and not self._form_has_payload:
			logger.warning(
				f"min_energy is set on {', '.join(energy_gated)} but no energy source is "
				"configured - p.energy is always 0.5 (call composition.energy() or bind a "
				"Form whose Sections carry energy)"
			)

		# The form clock MUST be registered before the harmonic clock: same-pulse
		# fixed callbacks fire in registration order (and all fixed callbacks fire
		# before callback sequences), and on a section-boundary bar the harmonic
		# clock reads the current section (via _get_section_progression) to decide
		# whether to walk that section's chords.  Registering harmony first would
		# make it read the OLD section on every boundary, shifting section_chords()
		# replays by one bar and bleeding them across sections.
		self._form_clock_started = False

		# An external Start rewinds the whole piece, not only the transport
		# (#3089).  The Sequencer cannot know what a composition's opening is,
		# so it asks.
		self._sequencer.on_restart = self._rewind_to_the_top

		await self._start_form_clock(clock_lookahead)

		self._harmony_horizon.reset()
		self._harmonic_clock_started = False

		if self._harmonic_state is not None or self._bound_progression is not None or self._section_progressions:
			self._warn_about_sections_with_no_chords()
			await self._start_harmonic_clock(bar_beats, clock_lookahead)

		# Bar counter - always active so p.bar is available to all builders.
		def _advance_builder_bar (pulse: int) -> None:
			self._builder_bar += 1

		first_bar_pulse = subsequence.constants.pulses.beats_to_pulses(bar_beats, self._sequencer.pulses_per_beat)

		await self._sequencer.schedule_callback_repeating(
			callback = _advance_builder_bar,
			interval_beats = bar_beats,
			start_pulse = first_bar_pulse,
			# Same raised lookahead as the form/harmony clocks: a pattern
			# rebuilding lookahead-early for its next cycle must read the bar
			# that cycle starts in, not the previous one.
			reschedule_lookahead = clock_lookahead
		)

		# Run wait_for_initial=True scheduled functions and block until all complete.
		# This ensures composition.data is populated before patterns build.
		initial_tasks = [t for t in self._pending_scheduled if t.wait_for_initial]

		if initial_tasks:

			names = ", ".join(getattr(t.fn, '__name__', repr(t.fn)) for t in initial_tasks)
			logger.info(f"Waiting for initial scheduled {'function' if len(initial_tasks) == 1 else 'functions'} before start: {names}")

			async def _run_initial (fn: typing.Callable) -> None:

				accepts_ctx = _fn_has_parameter(fn, "p")
				ctx = ScheduleContext(cycle=0)

				try:
					if inspect.iscoroutinefunction(fn):
						await (fn(ctx) if accepts_ctx else fn())
					else:
						loop = asyncio.get_running_loop()
						call = (lambda: fn(ctx)) if accepts_ctx else fn
						await loop.run_in_executor(None, call)
				except Exception as exc:
					logger.warning(f"Initial run of {getattr(fn, '__name__', repr(fn))!r} failed: {exc}")

			await asyncio.gather(*[_run_initial(t.fn) for t in initial_tasks])

		for pending_task in self._pending_scheduled:

			accepts_ctx = _fn_has_parameter(pending_task.fn, "p")

			# A wait_for_initial task already ran once as cycle 0 (the blocking
			# pre-roll above), so its repeating wrapper starts at cycle 1 — keeping
			# ScheduleContext.cycle monotonic across the initial and repeating runs.
			wrapped = _make_safe_callback(
				pending_task.fn,
				accepts_context = accepts_ctx,
				start_cycle = 1 if pending_task.wait_for_initial else 0,
				# A render waits for each call, so what it feeds the patterns
				# lands at the same point on every run (#2793).
				wait = lambda: self._sequencer.render_mode,
			)

			# wait_for_initial=True implies defer — no point firing at pulse 0
			# after the blocking run just completed.  defer=True skips the
			# backshift fire so the first repeating call happens one full cycle
			# later.
			if pending_task.wait_for_initial or pending_task.defer:
				start_pulse = subsequence.constants.pulses.beats_to_pulses(pending_task.cycle_beats, self._sequencer.pulses_per_beat)
			else:
				start_pulse = 0

			await self._sequencer.schedule_callback_repeating(
				callback = wrapped,
				interval_beats = pending_task.cycle_beats,
				start_pulse = start_pulse,
				reschedule_lookahead = pending_task.reschedule_lookahead
			)

		# Build Pattern objects from pending registrations.
		patterns: typing.List[subsequence.pattern.Pattern] = []

		for i, pending in enumerate(self._pending_patterns):

			pattern = self._build_pattern_from_pending(pending)
			patterns.append(pattern)

		await schedule_patterns(
			sequencer = self._sequencer,
			patterns = patterns,
			start_pulse = 0
		)

		# Populate the running patterns dict for live hot-swap and mute/unmute.
		for i, pending in enumerate(self._pending_patterns):
			name = pending.builder_fn.__name__
			self._running_patterns[name] = patterns[i]

		# Everything pending is running now; drop the declarations so a later
		# live reload cannot graduate stale copies.
		self._pending_patterns = []

		# Every service starts INSIDE this try, so one that fails to start
		# still tears down the ones already up.  They used to start before it,
		# and a single busy port - the web dashboard's, most often, until it was
		# retired (#3052) - skipped the whole teardown below and handed the
		# musician back a terminal with no echo and no line editing (#3035).
		try:
			if self._display is not None and not self._sequencer.render_mode:
				self._display.start()
				self._sequencer.on_event("bar",  self._display.update)
				self._sequencer.on_event("beat", self._display.update)

			# A file that watches itself declared its parts through Python's own
			# run of it, so nothing recorded them as the file's: record them now,
			# before anything typed can run, so its first save can delete (#3376).
			if self._live_reloader is not None:
				self._live_reloader.claim_what_the_script_declared()

			# Neither server belongs in a render: a render writes a file and
			# ends, and opening a socket for it invites a control surface to
			# drive something that is not playing (#2995).
			if self._live_server is not None and not self._sequencer.render_mode:
				await self._live_server.start()

			if self._osc_server is not None and not self._sequencer.render_mode:
				await self._osc_server.start()
				self._sequencer.osc_server = self._osc_server
				self._sequencer.on_event("bar", self._broadcast_osc_status)

			# Start keystroke listener if hotkeys are enabled and not in render mode.
			if self._hotkeys_enabled and not self._sequencer.render_mode:
				self._keystroke_listener = subsequence.keystroke.KeystrokeListener(on_key = self._keys_arrived)
				self._keystroke_listener.start()

				if self._keystroke_listener.active:
					# Listener started successfully: keys are taken as they
					# arrive, and the bar handler runs quantised actions on
					# their bar.  Show all bindings so the user knows what's
					# available.
					self._sequencer.on_event("bar", self._process_hotkeys)
					self._list_hotkeys()
				# If not active, KeystrokeListener.start() already logged a warning.

			await run_until_stopped(self._sequencer)
		finally:
			# Tear down every service even if run_until_stopped (or an earlier
			# stop) raised, and guard each individually, so one failure can't
			# strand the rest — most importantly the keystroke listener's
			# terminal restore.
			if self._live_server is not None:
				try:
					await self._live_server.stop()
				except Exception:
					logger.exception("Error stopping live server")

			if self._live_reloader is not None:
				try:
					self._live_reloader.stop()
				except Exception:
					logger.exception("Error stopping live reloader")

			if self._osc_server is not None:
				try:
					await self._osc_server.stop()
				except Exception:
					logger.exception("Error stopping OSC server")
				self._sequencer.osc_server = None

			if self._display is not None:
				try:
					self._display.stop()
				except Exception:
					logger.exception("Error stopping display")

			if self._keystroke_listener is not None:
				try:
					self._keystroke_listener.stop()
				except Exception:
					logger.exception("Error stopping keystroke listener")
				self._keystroke_listener = None

	def _build_pattern_from_pending (self, pending: _PendingPattern, start_pulse: int = 0) -> subsequence.pattern.Pattern:

		"""
		Create a Pattern from a pending registration using a temporary subclass.

		The pattern's play stream is dealt here, keyed by NAME (crc32 of
		"seed:name" plus any reroll nonce), so registration order is
		irrelevant and a pattern added live gets exactly the stream it would
		have had at startup.  ``start_pulse`` anchors the first cycle on the
		beat axis so the initial build reads the harmony window at the right
		place (the sequencer keeps the anchor current on every reschedule).
		"""

		composition_ref = self
		rng = self._stream(pending.builder_fn.__name__)

		class _DecoratorPattern (subsequence.pattern.Pattern):

			"""
			Pattern subclass that delegates to a builder function on each reschedule.
			"""

			def __init__ (self, pending: _PendingPattern, pattern_rng: typing.Optional[random.Random] = None) -> None:

				"""
				Initialise the decorator pattern from pending registration details.
				"""

				super().__init__(
					channel = pending.channel,
					length = pending.length,
					reschedule_lookahead = pending.reschedule_lookahead,
					device = pending.device,
					mirrors = pending.mirrors,
				)

				# What the source last declared, so a save can apply only what
				# it changed (#2905).
				self._declared = pending
				self._builder_fn = pending.builder_fn
				self._drum_note_map = pending.drum_note_map
				self._cc_name_map = pending.cc_name_map
				self._nrpn_name_map = pending.nrpn_name_map
				self._default_grid: int = pending.default_grid
				# One step's size in beats, as declared.  set_length(steps=)
				# counts in it; kept apart from length / grid because a plain
				# set_length(beats) keeps the grid and so changes that ratio.
				self._step_beats: typing.Optional[float] = (
					pending.length / pending.default_grid if pending.default_grid > 0 else None
				)
				self._wants_chord = _fn_has_parameter(pending.builder_fn, "chord")
				self._said_no_chord = False
				self._cycle_count = 0
				self._rng = pattern_rng
				self._muted = False
				self._min_energy = pending.min_energy
				self._energy_gated = False
				self._voice_leading_state: typing.Optional[subsequence.voicings.VoiceLeadingState] = (
					subsequence.voicings.VoiceLeadingState() if pending.voice_leading else None
				)
				self._tweaks: typing.Dict[str, typing.Any] = {}

				# Anchor of the cycle being built, on the absolute pulse axis.
				# The sequencer updates this on every reschedule; the initial
				# value is the pattern's first scheduled start.
				self._cycle_start_pulse = start_pulse

				self._rebuild()

			def _rebuild (self) -> None:

				"""
				Clear steps and call the builder function to repopulate.
				"""

				self.steps = {}
				self.cc_events = []
				self.osc_events = []
				self.raw_note_events = []
				current_cycle = self._cycle_count
				self._cycle_count += 1

				# lock(): re-deal the stream from its effective seed every
				# rebuild so a locked pattern realizes identically each cycle.
				# Checked here (engine-side) so it survives live reload.
				if self._builder_fn.__name__ in composition_ref._locked_names:
					locked_seed = composition_ref._stream_seed(self._builder_fn.__name__)
					if locked_seed is not None:
						self._rng = random.Random(locked_seed)

				if self._muted:
					return

				section_info = composition_ref._form_state.get_section_info() if composition_ref._form_state else None
				energy = composition_ref._current_energy(section_info)
				effective_key, effective_scale = composition_ref._effective_key_scale(section_info)

				# Automatic energy gating: below the threshold the pattern is
				# silent this cycle (composing with _muted — a performer mute
				# always wins).  Gate flips log once.
				if self._min_energy is not None:
					gated = energy < self._min_energy

					if gated != self._energy_gated:
						state_word = "closed" if gated else "open"
						logger.info(
							f"Pattern '{self._builder_fn.__name__}': energy gate {state_word} "
							f"(energy {energy:.2f}, min_energy {self._min_energy:g})"
						)
						self._energy_gated = gated

					if gated:
						return

				# The harmony view for this cycle, anchored at its start beat —
				# under variable harmonic rhythm the window, not the engine's
				# mutating singleton, is the source of truth.
				harmony_view: typing.Optional[HarmonyView] = None

				if not composition_ref._harmony_horizon.is_empty:
					origin_beat = self._cycle_start_pulse / composition_ref._sequencer.pulses_per_beat
					harmony_view = HarmonyView(composition_ref._harmony_horizon, origin_beat)

				builder = subsequence.pattern_builder.PatternBuilder(
					pattern = self,
					cycle = current_cycle,
					drum_note_map = self._drum_note_map,
					cc_name_map = self._cc_name_map,
					nrpn_name_map = self._nrpn_name_map,
					section = section_info,
					bar = composition_ref._builder_bar,
					conductor = composition_ref.conductor,
					rng = self._rng,
					tweaks = self._tweaks,
					default_grid = self._default_grid,
					data = composition_ref.data,
					# The effective key/scale re-anchors key-relative content
					# (degrees, romans, generated material) to the section /
					# form / composition tier in force — mode travels too.
					key = effective_key,
					scale = effective_scale,
					time_signature = composition_ref.time_signature,
					held_notes = composition_ref._sequencer._held_notes,
					harmony = harmony_view,
					section_motifs = composition_ref._section_motifs,
					energy = energy,
					# So p.scratch() can take a child stream keyed off this
					# pattern's, rather than drawing from the pattern's own.
					stream_seed = composition_ref._stream_seed(self._builder_fn.__name__),
					# It rebuilds and reschedules every cycle, so set_length() must
					# keep it at least as long as its reschedule lookahead.
					repeating = True,
					zero_indexed_channels = composition_ref._zero_indexed_channels,
				)

				try:

					if self._wants_chord:

						# The two-parameter convention: the injected chord is
						# the cycle-start snapshot from the window (falling
						# back to the engine before the clock has run).
						chord = harmony_view.chord if harmony_view is not None else (
							composition_ref._harmonic_state.get_current_chord()
							if composition_ref._harmonic_state is not None else None
						)

						if chord is not None:
							injected = _InjectedChord(
								chord,
								self._voice_leading_state,
								next_chord = harmony_view.next_chord if harmony_view is not None else None,
								beats_remaining = harmony_view.until_change if harmony_view is not None else None,
							)
							self._builder_fn(builder, injected)
						elif not _fn_requires_parameter(self._builder_fn, "chord"):
							# chord=None, or any default: the builder decides.
							self._builder_fn(builder)
						elif not self._said_no_chord:
							# Called with one argument, a builder that needs its
							# chord raised TypeError on every cycle, with a
							# traceback naming Python's argument count rather
							# than the missing harmony (#3019).  Say it once, and
							# stay silent until there is a chord.
							self._said_no_chord = True
							logger.warning(
								"Pattern '%s' takes a chord, and there is none to give it, so it plays nothing until "
								"there is: a pattern with a chord parameter needs composition.harmony(...), or a "
								"progression from composition.section_chords(...).",
								self._builder_fn.__name__,
							)

					else:
						self._builder_fn(builder)

					# Glides and tunings are laid against the notes' final places.
					builder._finish_build()

				except Exception:
					# Discard whatever the builder placed before it raised —
					# otherwise a half-built pattern plays and the log lies.
					# That includes the glides and tunings it had deferred.
					self.steps = {}
					self.cc_events = []
					self.osc_events = []
					self.raw_note_events = []
					builder._abandon_build()
					logger.exception("Error in pattern builder '%s' (cycle %d) - pattern will be silent this cycle", self._builder_fn.__name__, current_cycle)

				composition_ref._apply_composition_tuning(self, builder, self._drum_note_map, part = self._builder_fn.__name__)

			@property
			def is_silenced (self) -> bool:

				"""True while something is holding this part quiet.

				A performer mute, a transition mute (which sets the same flag)
				or a closed energy gate.  The sequencer reads it to let go of
				any drone the part is holding, because its builder is not
				running to turn one off (#2996).
				"""

				return self._muted or self._energy_gated

			def on_reschedule (self) -> None:

				"""
				Rebuild the pattern from the builder function before the next cycle.
				"""

				self._rebuild()

		return _DecoratorPattern(pending, rng)
