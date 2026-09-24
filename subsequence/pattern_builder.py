"""``PatternBuilder`` (the ``p`` inside a pattern) - the note-placement surface.

This is the ``p`` handed to every ``@composition.pattern`` function: the verbs
for placing notes, drums, chords, motifs and phrases, plus articulation, the
transforms, and the algorithmic and MIDI mixins it inherits.  It renders into
the plain data types in ``pattern``.
"""

import dataclasses
import functools
import logging
import random
import struct
import time
import typing
import zlib

import pymididefs.cc
import pymididefs.rpn
import subsequence.chords
import subsequence.declarations
import subsequence.constants
import subsequence.constants.pulses
import subsequence.constants.velocity
import subsequence.easing
import subsequence.groove
import subsequence.held_notes
import subsequence.intervals
import subsequence.metre
import subsequence.pattern
import subsequence.motifs
import subsequence.sequence_utils
import subsequence.mini_notation
import subsequence.conductor
import subsequence.pattern_algorithmic
import subsequence.pattern_midi
import subsequence.progressions

logger = logging.getLogger(__name__)

# Read off the declarations rather than repeated, so the runtime check and the
# published vocabulary cannot drift apart — the catalogue derives a surface's
# option list from the same Literal.
_ARPEGGIO_DIRECTIONS: typing.Tuple[str, ...] = typing.get_args(subsequence.declarations.ArpeggioDirection)
_STRUM_DIRECTIONS: typing.Tuple[str, ...] = typing.get_args(subsequence.declarations.StrumDirection)


def _expand_sequence_param (name: str, value: typing.Any, n: int) -> list:

	"""Expand a scalar to a list of length n, or adjust a list to length n.

	Parameters:
		name: The name of the parameter being expanded (used for logging).
		value: A scalar (e.g., int, float, str) or an iterable to expand.
		n: The target length for the returned list.

	Returns:
		A list of length ``n``. If ``value`` is a scalar, returns ``[value] * n``.
		If ``value`` is a list longer than ``n``, truncates it and logs a warning.
		If ``value`` is a list shorter than ``n``, repeats the last value and logs a warning.
	"""

	if isinstance(value, (int, float, str)):
		return [value] * n

	result = list(value)

	if len(result) == 0:
		raise ValueError(f"sequence(): {name} list cannot be empty")

	if len(result) > n:
		logger.warning("sequence(): %s has %d values but only %d steps - truncating", name, len(result), n)
		return result[:n]

	if len(result) < n:
		logger.warning("sequence(): %s has %d values but %d steps - repeating last value", name, len(result), n)
		return result + [result[-1]] * (n - len(result))

	return result


class BarCycle:

	"""Position of the current bar within a repeating cycle of bars.

	Returned by :meth:`PatternBuilder.bar_cycle`. Provides readable, musician-friendly
	properties for bar-position logic without raw modulo arithmetic.

	Attributes:
		bar: Zero-indexed bar within the cycle (0 … length−1).
		length: The cycle length in bars passed to :meth:`PatternBuilder.bar_cycle`.
	"""

	__slots__ = ("bar", "length")

	def __init__ (self, bar: int, length: int) -> None:
		self.bar = bar
		self.length = length

	@property
	def first (self) -> bool:
		"""True on the first bar of the cycle (``bar == 0``)."""
		return self.bar == 0

	@property
	def last (self) -> bool:
		"""True on the last bar of the cycle (``bar == length − 1``)."""
		return self.bar == self.length - 1

	@property
	def progress (self) -> float:
		"""Fractional progress through the cycle: 0.0 on bar 0, rising each bar.

		For a 4-bar cycle: 0.0, 0.25, 0.5, 0.75.
		Useful for gradual intensity curves or as a noise/LFO seed.
		"""
		return self.bar / self.length


class PatternBuilder(
	subsequence.pattern_algorithmic.PatternAlgorithmicMixin,
	subsequence.pattern_midi.PatternMidiMixin,
):

	"""
	The musician's 'palette' for creating musical content.

	A ``PatternBuilder`` instance (commonly named ``p``) is passed to every
	pattern function. It provides methods for placing notes, generating rhythms,
	and transforming the resulting sequence (e.g., swinging, reversing, or transposing).

	Rhythm in Subsequence is typically expressed in **beats** (where 1.0 is a
	quarter note) or **steps** (subdivisions of a pattern).
	"""

	def __init__ (self, pattern: subsequence.pattern.Pattern, cycle: int, conductor: typing.Optional[subsequence.conductor.Conductor] = None, drum_note_map: typing.Optional[typing.Dict[str, int]] = None, cc_name_map: typing.Optional[typing.Dict[str, int]] = None, nrpn_name_map: typing.Optional[typing.Dict[str, int]] = None, section: typing.Any = None, bar: int = 0, rng: typing.Optional[random.Random] = None, tweaks: typing.Optional[typing.Dict[str, typing.Any]] = None, default_grid: int = 16, data: typing.Optional[typing.Dict[str, typing.Any]] = None, key: typing.Optional[str] = None, scale: typing.Optional[str] = None, time_signature: typing.Tuple[int, int] = (4, 4), held_notes: typing.Optional[subsequence.held_notes.HeldNotes] = None, harmony: typing.Optional[typing.Any] = None, section_motifs: typing.Optional[typing.Dict[typing.Tuple[str, typing.Optional[str]], typing.Any]] = None, energy: float = 0.5, stream_seed: typing.Optional[int] = None, repeating: bool = False, zero_indexed_channels: bool = False) -> None:

		"""Initialise the builder with pattern context, cycle count, and optional section info.

		Parameters:
			pattern: The ``Pattern`` instance this builder populates.
			cycle: Zero-based rebuild counter.
			conductor: Optional ``Conductor`` for time-varying signals.
			drum_note_map: Optional mapping of drum names to MIDI notes.
			cc_name_map: Optional mapping of CC names to MIDI CC numbers.
			nrpn_name_map: Optional mapping of NRPN parameter names to 14-bit
				parameter numbers (0–16383).  Used by ``p.nrpn()`` and
				``p.nrpn_ramp()`` for symbolic access - typically a
				device-specific dictionary (e.g. Sequential Take 5's
				``Osc1FreqFine`` → 9).
			section: Current ``SectionInfo`` (or ``None``).
			bar: Global bar count.
			rng: Optional seeded ``Random`` for reproducibility.
			tweaks: Per-pattern overrides set via ``composition.tweak()``.
			default_grid: Number of grid slots used by ``hit_steps()``,
				``sequence()``, and ``rotate()`` when no explicit ``grid``
				is passed.  Normally set automatically from the decorator's
				``beats``/``bars``/``steps`` and ``step_duration`` parameters.
			data: Shared state dict from the parent ``Composition``
				(same object as ``composition.data``).  Read and write
				via ``p.data`` for cross-pattern communication and
				external data access.  Patterns rebuild in definition
				order; when two patterns share the same ``length``,
				a writer defined earlier in source is guaranteed to
				run before a reader defined later in the same cycle.
			key: The composition's key (e.g. ``"C"``), used by ``p.progression()``
				to generate chords from a graph style and by ``p.motif()`` to
				resolve scale degrees.  ``None`` when the composition has no
				key set.
			scale: The composition's scale/mode name (e.g. ``"minor"``),
				read via ``p.scale`` and used to resolve scale degrees in
				``p.motif()``.  ``None`` means ionian/major.
			time_signature: The composition's time signature, read via
				``p.time_signature``; sets ``p.bar_beats`` and powers the
				metric-weight table.
			section_motifs: Optional reference to the composition's
				section-motif registry, read by ``p.section_motif()``.
			harmony: Optional read-only harmony window view for this cycle
				(``p.harmony``) - ``p.harmony.chord``, ``chord_at(beat)``,
				``next_chord``, ``until_change``.  ``None`` until the
				harmonic clock has published a window.
			held_notes: Optional live held-note tracker from ``composition.note_input()``.
				Read via ``p.held_notes()``.  ``None`` when no note input was declared
				(and when rendering headlessly), so the accessor returns an empty list.
			energy: The current section's energy level (0.0–1.0), read via
				``p.energy`` - the arranging dial.  0.5 when no energy source
				is configured.
			stream_seed: This pattern's derived stream seed, which
				``p.scratch()`` takes a child stream of.  ``None`` when the
				composition is unseeded.
			repeating: True when the pattern is rebuilt and rescheduled every
				cycle, so ``set_length()`` refuses a length its
				``reschedule_lookahead`` would run past.  One-shots -
				``trigger()`` and transition fills - leave it False: they never
				reschedule, so their lookahead means nothing.
			zero_indexed_channels: Whether the composition numbers channels
				from 0, so a channel pool given to ``apply_tuning()`` is read
				the way every other channel is.
		"""

		self._pattern = pattern
		self.cycle = cycle
		self.conductor = conductor
		self._drum_note_map = drum_note_map
		self._cc_name_map = cc_name_map
		self._nrpn_name_map = nrpn_name_map
		self.section = section
		self.bar = bar
		self.rng: random.Random = rng or random.Random()
		self._tweaks: typing.Dict[str, typing.Any] = tweaks or {}
		self._default_grid: int = default_grid
		# One step's size in beats, which set_length(steps=) counts in.  A
		# composition pattern carries it from its declaration; anything else
		# takes it from the length and grid it arrives with.
		declared_step: typing.Optional[float] = getattr(pattern, "_step_beats", None)
		self._step_beats: typing.Optional[float] = (
			declared_step if declared_step is not None
			else pattern.length / default_grid if default_grid > 0
			else None
		)
		self.data: typing.Dict[str, typing.Any] = data if data is not None else {}
		self.key: typing.Optional[str] = key  # composition key, for p.progression() chord generation
		self.scale: typing.Optional[str] = scale  # composition scale/mode, for degree resolution
		self.time_signature: typing.Tuple[int, int] = subsequence.metre.check(time_signature)
		self.harmony: typing.Optional[typing.Any] = harmony  # HarmonyView for this cycle, or None
		self.energy: float = energy  # current section's energy (the arranging dial)
		self._section_motifs: typing.Optional[typing.Dict[typing.Tuple[str, typing.Optional[str]], typing.Any]] = section_motifs
		self._held_notes: typing.Optional[subsequence.held_notes.HeldNotes] = held_notes
		self._tuning_applied: bool = False  # set by apply_tuning() to prevent double-apply
		# Glides and tunings wait for the build to finish, so they are laid
		# against the notes where they finally sit — see _finish_build().
		self._pending_glides: typing.List[typing.Callable[[], None]] = []
		self._pending_tunings: typing.List[typing.Callable[[], object]] = []
		# chord(legato=) and strum(legato=) likewise wait, so they measure
		# against every attack the build placed, before or after them (#3463).
		self._pending_legatos: typing.List[typing.Callable[[], None]] = []
		self._legato_groups: int = 0
		# This pattern's derived stream seed, so scratch() can take a child
		# stream of it rather than drawing from self.rng — see scratch().
		# None when the composition is unseeded.
		self._stream_seed: typing.Optional[int] = stream_seed
		# Where that stream stood as this build began, so a scratch varies
		# exactly when this pattern does: an unlocked stream has run on since
		# the last cycle, and lock() re-deals a locked one to the same place
		# (#2962).  Only a seeded stream is worth the copy.
		self._stream_at_start: typing.Optional[typing.Tuple[typing.Any, ...]] = self.rng.getstate() if stream_seed is not None else None
		self._repeating: bool = repeating
		self._zero_indexed_channels: bool = zero_indexed_channels
		# How many cellular_2d() calls this build has made, so each keeps the
		# grid seed it drew on its pattern (#3072).
		self._cellular_2d_calls: int = 0
		# And self_avoiding_walk() calls, so each goes on from where it left off (#3500).
		self._self_avoiding_walk_calls: int = 0

	@property
	def grid (self) -> int:
		"""Number of grid slots in this pattern (e.g. 16 for a 4-beat sixteenth-note pattern).

		Follows ``set_length(steps=…)``, which changes how many steps there are.
		"""
		return self._default_grid

	def _wrapped_beat (self, beat: float) -> float:

		"""A beat position inside the pattern: a negative one counts from the end.

		``beat=-1`` is one beat before the end, whatever the pattern's length,
		and any magnitude wraps.  Every verb that places something at a beat
		goes through here, notes and controls alike - the controls used to
		convert a negative beat straight to a negative pulse, which scheduled
		the event before its own cycle and shifted a whole recording (#3005).
		"""

		return beat % self._pattern.length if beat < 0 else beat

	def _wrapped_pulse (self, beat: float) -> int:

		"""The pulse a beat position lands on, wrapping a negative beat from the end."""

		return subsequence.constants.pulses.beats_to_pulses(self._wrapped_beat(beat))

	def _has_pitch_at_beat (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats) -> bool:
		"""Helper to check if a pitch is already sounding at a specific beat.

		Tolerant of unmappable drum names: a name absent from this pattern's
		``drum_note_map`` can't already be sounding here, so it returns False
		(the placement itself handles the drop/warn) rather than raising."""
		if isinstance(pitch, str):
			if self._drum_note_map is None or pitch not in self._drum_note_map:
				return False
			midi_pitch = self._drum_note_map[pitch]
		else:
			midi_pitch = pitch
		pulse = subsequence.constants.pulses.beats_to_pulses(beat)
		if pulse in self._pattern.steps:
			return any(n.pitch == midi_pitch for n in self._pattern.steps[pulse].notes)
		return False


	@property
	def bar_beats (self) -> float:

		"""How many beats (quarter notes) one bar lasts: ``beats × 4 / unit``, so 3.5 in 7/8.

		Pass it wherever a bar size is asked for without a composition to
		read it from, such as ``sentence(beats_per_bar=p.bar_beats)``.
		"""

		return subsequence.metre.bar_beats(self.time_signature)

	@property
	def c (self) -> typing.Optional[subsequence.conductor.Conductor]:

		"""Alias for self.conductor."""

		return self.conductor

	def signal (self, name: str) -> float:

		"""Read a conductor signal at the current bar.

		Shorthand for ``p.c.get(name, p.bar * p.bar_beats)``, so the signal
		is read at the beat this bar actually starts on, in any metre.
		Returns 0.0 if no conductor is attached or the signal is not
		defined.
		"""

		if self.conductor is None:
			return 0.0

		return self.conductor.get(name, self.bar * self.bar_beats)

	def held_notes (self) -> typing.List[int]:

		"""Return the MIDI notes currently held on the ``note_input`` keyboard.

		The notes are sorted ascending.  Pass the result straight to
		``p.arpeggio()`` to arpeggiate whatever the player is holding -
		``p.arpeggio(p.held_notes())`` rests when no keys are down.  Returns
		an empty list when no ``note_input()`` source was declared and when
		rendering headlessly (so seeded output stays deterministic).

		The set is sampled once per rebuild; ``note_input(release_ms=…)``
		smooths the gap during hand-position changes so the arp does not drop
		out, and ``note_input(latch=True)`` holds the chord until you play a
		new one.
		"""

		if self._held_notes is None:
			return []

		return self._held_notes.snapshot(time.perf_counter())

	def param (self, name: str, default: typing.Any = None) -> typing.Any:

		"""Read a tweakable parameter for this pattern.

		Returns the value set via ``composition.tweak()`` if one
		exists, otherwise returns ``default``.

		Parameters:
			name: The parameter name.
			default: The value to return if no tweak is active.

		Example::

			@composition.pattern(channel=1, beats=4)
			def bass (p):
				pitches = p.param("pitches", [60, 64, 67, 72])
				p.sequence(steps=[0, 4, 8, 12], pitches=pitches)
		"""

		return self._tweaks.get(name, default)

	def set_length (self, length: typing.Optional[subsequence.declarations.Beats] = None, *, steps: typing.Optional[subsequence.declarations.StepCount] = None) -> "PatternBuilder":

		"""
		Change how long the pattern is, in beats or in its own steps.

		**In beats**, the pattern keeps its number of steps and they stretch or
		squeeze to fit: ``set_length(3)`` on a sixteen-step bar is still sixteen
		steps, each now three sixteenths of a beat.

		**In steps**, every step keeps its size and the pattern gains or loses
		steps: ``set_length(steps=12)`` on a sixteen-step bar is twelve
		sixteenths - three beats - and ``p.grid`` becomes 12, so ``euclidean()``
		and every other method that counts steps spreads over those twelve.  A
		step is the size the pattern was declared with, whatever lengths it has
		been given since.

		Notes already placed in this build keep their positions; anything placed
		after the call sees the new length.  The sequencer plays it from the next
		cycle, which starts where the current one ends, and it stays in force for
		later cycles until it is set again - so a pattern left shorter than its
		neighbours drifts against them, which is the polyrhythm.

		```python
		p.set_length(steps=12)   # twelve sixteenths against a sixteen-step kick
		p.euclidean(42, pulses=5)
		```

		Parameters:
			length: The new length in beats (e.g. ``4.0`` for a bar of 4/4).
			steps: The new length as a count of the pattern's steps.

		Raises:
			ValueError: If both or neither are given, if ``steps`` is not a whole
				number of at least 1, or if the length would be shorter than the
				``reschedule_lookahead`` of a pattern that repeats - which would
				leave it silent.

		Returns ``self`` for fluent chaining.
		"""

		if length is not None and steps is not None:
			raise ValueError("Give set_length() a length in beats or steps=, not both")

		if steps is not None:

			if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
				raise ValueError(f"steps= must be a whole number of steps, 1 or more - got {steps!r}")

			if self._step_beats is None:
				raise ValueError("This pattern has no step size to count in - give set_length() a length in beats")

			length = steps * self._step_beats

		if length is None:
			raise ValueError("set_length() needs a length in beats, or steps=")

		if length <= 0:
			raise ValueError("Pattern length must be positive")

		length_pulses = subsequence.constants.pulses.beats_to_pulses(length)

		if length_pulses < 1:
			raise ValueError(f"A length of {length:g} beats is shorter than one pulse (1/24 of a beat)")

		# Refused here rather than stored: the sequencer cannot reschedule a
		# pattern whose lookahead runs past its end, so the length would silence
		# it on every cycle after until something set a longer one.  A one-shot
		# never reschedules, so its lookahead is no limit.
		lookahead = self._pattern.reschedule_lookahead

		if self._repeating and length_pulses < subsequence.constants.pulses.beats_to_pulses(lookahead):
			raise ValueError(
				f"A length of {length:g} beats is shorter than this pattern's "
				f"reschedule_lookahead of {lookahead:g} beats, which would silence it - "
				f"keep it at least that long, or declare a shorter lookahead"
			)

		self._pattern.length = length

		if steps is not None:
			self._default_grid = steps

			# A composition pattern hands its grid to every rebuild; move it
			# there too, or the next cycle would count the declared steps again.
			if hasattr(self._pattern, "_default_grid"):
				setattr(self._pattern, "_default_grid", steps)

		return self

	def _resolve_pitch (self, pitch: subsequence.declarations.Pitch) -> int:

		"""
		Resolve a pitch value to a MIDI note number (strict).

		Raises on an unknown drum name - the strict counterpart of
		:meth:`_resolve_pitch_lenient`.  Note-placement and transform methods use
		the lenient variant, so a device may legitimately lack a voice others
		have; this strict primitive is retained for parity with the sibling
		``_resolve_cc`` / ``_resolve_nrpn`` / ``_resolve_rpn`` name resolvers,
		where an unknown name is always a configuration error.
		"""

		if isinstance(pitch, int):
			return pitch

		if self._drum_note_map is None:
			raise ValueError(f"String pitch '{pitch}' requires a drum_note_map, but none was provided")

		if pitch not in self._drum_note_map:
			raise ValueError(f"Unknown drum name '{pitch}' - not found in drum_note_map")

		return self._drum_note_map[pitch]

	def _resolve_hit_pitch (self, pitch: subsequence.declarations.Pitch) -> typing.Optional[typing.Tuple[int, typing.Optional[str], bool]]:

		"""Resolve a step-note pitch for placement, leniently for named drums.

		Returns ``(midi_pitch, origin, primary_unmapped)``, or ``None`` to drop
		the hit entirely.

		Unlike :meth:`_resolve_pitch`, an unknown drum *name* does not raise:
		faithful-core device maps legitimately lack voices other devices have,
		so a name a device can't voice is dropped rather than crashing the
		pattern.  The cases:

		- Integer pitch → ``(pitch, None, False)``.
		- String in this pattern's ``drum_note_map`` → ``(note, name, False)``.
		- String absent here but present in a mirror's map →
		  ``(placeholder, name, True)``: the primary can't voice it, but a
		  symbolic mirror can (the placeholder pitch is used only by transforms
		  and display, never for playback - see ``Note.primary_unmapped``).
		- String absent everywhere → warn once and return ``None`` (drop).
		- String with **no** ``drum_note_map`` at all → still a configuration
		  error; raises (you forgot the map, this is not a capability gap).
		"""

		if isinstance(pitch, int):
			return (pitch, None, False)

		if self._drum_note_map is None:
			raise ValueError(f"String pitch '{pitch}' requires a drum_note_map, but none was provided")

		if pitch in self._drum_note_map:
			return (self._drum_note_map[pitch], pitch, False)

		mirror_pitch = self._first_mirror_pitch(pitch)
		if mirror_pitch is not None:
			return (mirror_pitch, pitch, True)

		self._warn_unknown_drum(pitch)
		return None

	def _first_mirror_pitch (self, name: str) -> typing.Optional[int]:

		"""Return the first mirror ``drum_note_map`` value for *name*, or None.

		Lets a named hit absent from the primary map still be placed (as a
		``primary_unmapped`` Note) when a symbolic (3-tuple) mirror can voice it.
		"""

		for entry in getattr(self._pattern, 'mirrors', []):
			if len(entry) == 3 and entry[2] is not None and name in entry[2]:
				return typing.cast(int, entry[2][name])
		return None

	def _warn_unknown_drum (self, name: str, include_mirrors: bool = True) -> None:

		"""Warn once (per pattern, per name) that a drum name maps to nothing.

		Deduplicated via the Pattern's ``_warned_drum_names`` set so the per-bar
		rebuild does not spam; a hot-reload builds a fresh Pattern and
		re-surfaces the warning.

		``include_mirrors`` tailors the wording: step-note placement checks the
		mirror maps too (the name maps to *no* device), whereas the methods that
		resolve against the primary map only - drones, ``arpeggio``, ``evolve``,
		``branch``, and the ``thin``/``ratchet`` pitch filter - report just this
		device.
		"""

		warned = getattr(self._pattern, '_warned_drum_names', None)
		if warned is not None:
			if name in warned:
				return
			warned.add(name)

		fn = getattr(self._pattern, '_builder_fn', None)
		label = getattr(fn, '__name__', None)
		where = f"pattern '{label}'" if label else f"device {self._pattern.device} channel {self._pattern.channel}"
		if include_mirrors:
			scope  = f"the drum_note_map for {where} or any of its mirror destinations"
			reason = "no device maps this voice"
		else:
			scope  = f"the drum_note_map for {where}"
			reason = "this device has no such voice"
		logger.warning(f"Drum name '{name}' is not in {scope} - the note is dropped ({reason}). Check the spelling, or add it to a map.")

	def _resolve_pitch_lenient (self, pitch: subsequence.declarations.Pitch) -> typing.Optional[int]:

		"""Resolve a pitch against this pattern's own ``drum_note_map``, leniently.

		Like :meth:`_resolve_pitch`, but an unknown drum *name* (a map is present
		yet lacks the voice) is **dropped** - warned once, returns ``None`` -
		instead of raising, so a device may legitimately lack a voice that other
		devices have.  Used by the methods that do NOT carry the drum name to
		mirror destinations (``note_on``/``note_off``/``drone``, ``evolve``,
		``branch``, and the ``thin``/``ratchet`` pitch filter), so resolution
		is against the primary map only.  ``arpeggio``/``chord``/``strum`` left
		that list in #2395: resolving to a bare int threw away the name a
		surface needs, so they place through :meth:`_resolve_hit_pitch` now.
		A string with **no** ``drum_note_map`` at all is still a configuration
		error and raises.
		"""

		if isinstance(pitch, int):
			return pitch

		if self._drum_note_map is None:
			raise ValueError(f"String pitch '{pitch}' requires a drum_note_map, but none was provided")

		if pitch in self._drum_note_map:
			return self._drum_note_map[pitch]

		self._warn_unknown_drum(pitch, include_mirrors=False)
		return None

	def _resolve_cc (self, control: typing.Union[int, str]) -> int:

		"""Resolve a CC name or number to a MIDI CC number."""

		if isinstance(control, int):
			# NRPN and RPN numbers were range-checked and CC numbers were not,
			# although cc()'s own docstring says 0–127.  `p.cc(200, 64)` was
			# stored and then rejected by mido on every cycle (#3004).
			return subsequence.pattern.check_midi_range(control, "CC number", "cc")

		if self._cc_name_map is None:
			raise ValueError(f"String CC name '{control}' requires a cc_name_map, but none was provided")

		if control not in self._cc_name_map:
			raise ValueError(f"Unknown CC name '{control}' - not found in cc_name_map")

		return subsequence.pattern.check_midi_range(
			self._cc_name_map[control], "CC number", f"cc_name_map[{control!r}]",
		)

	def _resolve_nrpn (self, parameter: typing.Union[int, str]) -> int:

		"""Resolve an NRPN parameter name or number to a 14-bit parameter number.

		Strings require an ``nrpn_name_map`` on the pattern decorator -
		NRPN parameter numbers are vendor-specific, so subsequence does not
		ship a default mapping.  Integer parameters must be in the 14-bit
		range 0–16383.
		"""

		if isinstance(parameter, int):
			if not 0 <= parameter <= 16383:
				raise ValueError(f"NRPN parameter number must be 0–16383, got {parameter}")
			return parameter

		if self._nrpn_name_map is None:
			raise ValueError(f"String NRPN name '{parameter}' requires an nrpn_name_map, but none was provided")

		if parameter not in self._nrpn_name_map:
			raise ValueError(f"Unknown NRPN name '{parameter}' - not found in nrpn_name_map")

		return self._nrpn_name_map[parameter]

	def _resolve_rpn (self, parameter: typing.Union[int, str]) -> int:

		"""Resolve an RPN parameter name or number to a 14-bit parameter number.

		Strings fall back to ``pymididefs.rpn.RPN_MAP`` - the standardised
		set of MIDI Registered Parameter Numbers (``pitch_bend_sensitivity``,
		``channel_fine_tuning``, ...).  No per-pattern map needed.  Integer
		parameters must be in the 14-bit range 0–16383.
		"""

		if isinstance(parameter, int):
			if not 0 <= parameter <= 16383:
				raise ValueError(f"RPN parameter number must be 0–16383, got {parameter}")
			return parameter

		if parameter not in pymididefs.rpn.RPN_MAP:
			raise ValueError(f"Unknown RPN name '{parameter}' - not a standard Registered Parameter Number")

		return pymididefs.rpn.RPN_MAP[parameter]

	def note (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.25) -> "PatternBuilder":

		"""
		Place a single MIDI note at a specific beat position.

		A drum name is carried through to the mirror fan-out so each device can
		re-resolve it through its own ``drum_note_map``.  A name no destination
		maps (not in the pattern's own map nor any mirror's) is dropped and
		warned once - it does not raise - so device maps can legitimately lack
		voices others have.  (A string pitch with **no** ``drum_note_map`` at all
		is still a configuration error and raises.)

		Parameters:
			pitch: MIDI note number (0-127) or a drum name string from
				the pattern's ``drum_note_map``.
			beat: The beat position (0.0 is the start). Negative values
				wrap from the end (e.g., -1.0 is one beat before the end).
			velocity: MIDI velocity (0-127, default 100), or a
				``(low, high)`` tuple for a single random draw.
			duration: Note duration in beats (default 0.25).

		Example:
			```python
			p.note(60, beat=0, velocity=110)      # Middle C on beat 1
			p.note("kick", beat=1.0)               # Kick on beat 2
			p.note(67, beat=-0.5, duration=0.5)  # G on the 'and' of the last beat
			```
		"""

		# Resolve leniently: a named drum the target can't voice is dropped (and
		# warned once) rather than raising, and the drum name is carried so each
		# destination can re-resolve it through its own drum_note_map.
		resolution = self._resolve_hit_pitch(pitch)
		if resolution is None:
			return self	# unknown drum name, mapped by no destination — dropped
		midi_pitch, origin, primary_unmapped = resolution

		resolved_velocity = self._resolve_velocity(velocity)

		beat = self._wrapped_beat(beat)

		self._pattern.add_note_beats(
			beat_position = beat,
			pitch = midi_pitch,
			velocity = resolved_velocity,
			duration_beats = duration,
			origin = origin,
			primary_unmapped = primary_unmapped
		)
		return self

	def note_on (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY) -> "PatternBuilder":

		"""
		Place an explicit Note On event without a duration.
		Useful for drones or infinite sustains. Must be paired with
		a ``note_off()`` later to silence the note.

		Parameters:
			pitch: MIDI note number (0-127) or a drum name string.
			beat: The beat position (0.0 is the start).
			velocity: MIDI velocity (0-127, default 100), or a
				``(low, high)`` tuple for a single random draw.

		A drum name this device's ``drum_note_map`` lacks is dropped (warned
		once) rather than raising - consistent with the step-note methods.  A
		string pitch with no ``drum_note_map`` at all is still a configuration
		error and raises.
		"""

		midi_pitch = self._resolve_pitch_lenient(pitch)
		if midi_pitch is None:
			return self	# drum name this device can't voice — dropped (warned once)
		resolved_velocity = self._resolve_velocity(velocity)
		beat = self._wrapped_beat(beat)

		self._pattern.add_raw_note_beats(
			message_type = 'note_on',
			beat_position = beat,
			pitch = midi_pitch,
			velocity = resolved_velocity,
			origin = pitch if isinstance(pitch, str) else None
		)
		return self

	def note_off (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats) -> "PatternBuilder":

		"""
		Place an explicit Note Off event to silence a drone.
		
		Parameters:
			pitch: MIDI note number (0-127) or a drum name string.
			beat: The beat position (0.0 is the start).

		A drum name this device's ``drum_note_map`` lacks is dropped (warned
		once) rather than raising; with no ``drum_note_map`` at all it raises.
		"""

		midi_pitch = self._resolve_pitch_lenient(pitch)
		if midi_pitch is None:
			return self	# nothing to silence — this device can't voice the name
		beat = self._wrapped_beat(beat)

		self._pattern.add_raw_note_beats(
			message_type = 'note_off',
			beat_position = beat,
			pitch = midi_pitch,
			velocity = 0,
			origin = pitch if isinstance(pitch, str) else None
		)
		return self

	def drone (self, pitch: subsequence.declarations.Pitch, beat: subsequence.declarations.GridBeats = 0.0, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY) -> "PatternBuilder":

		"""
		A musical alias for ``note_on``. Places a raw Note On event without a duration,
		typically used for sustained notes that span multiple cycles.
		Must be silenced later using ``drone_off()``.

		Parameters:
			pitch: MIDI note number (0-127) or a drum name string.
			beat: The beat position (0.0 is the start).
			velocity: MIDI velocity (0-127, default 100), or a
				``(low, high)`` tuple for a single random draw.
		"""

		self.note_on(pitch, beat=beat, velocity=velocity)
		return self

	def drone_off (self, pitch: subsequence.declarations.Pitch) -> "PatternBuilder":

		"""
		A musical alias for ``note_off``. Places a raw Note Off event at beat 0.0.
		Used to stop a sequence started by ``drone()``.
		
		Parameters:
			pitch: MIDI note number (0-127) or a drum name string.
		"""

		self.note_off(pitch, beat=0.0)
		return self

	def silence (self, beat: subsequence.declarations.GridBeats = 0.0) -> "PatternBuilder":

		"""
		Sends an 'All Notes Off' (CC 123) and 'All Sound Off' (CC 120) message
		on the pattern's channel to immediately silence any ringing notes or drones.
		
		Parameters:
			beat: The beat position (0.0 is the start).
		"""

		self.cc(control=123, value=0, beat=beat)
		self.cc(control=120, value=0, beat=beat)
		return self

	def hit (self, pitch: subsequence.declarations.Pitch, beats: typing.List[subsequence.declarations.BeatPosition], velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.1) -> "PatternBuilder":

		"""
		Place multiple short 'hits' at a list of beat positions.

		Parameters:
			pitch: MIDI note number or drum name.
			beats: List of beat positions.
			velocity: MIDI velocity (0-127), or a ``(low, high)`` tuple
				for a fresh random draw per hit.
			duration: Note duration in beats.

		Example:
			```python
			p.hit("snare", [1, 3])                      # Standard backbeat
			p.hit("snare", [1, 3], velocity=(80, 110))  # Human velocity range
			```
		"""

		for beat in beats:
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)
		return self

	@subsequence.declarations.bounded
	def hit_steps (self, pitch: subsequence.declarations.Pitch, steps: typing.Sequence[subsequence.declarations.StepPosition], velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.1, grid: typing.Optional[subsequence.declarations.StepCount] = None, probability: subsequence.declarations.UnitInterval = 1.0, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "PatternBuilder":

		"""
		Place short hits at specific step (grid) positions.

		Parameters:
			pitch: MIDI note number or drum name.
			steps: A list of grid indices (0 to ``grid - 1``), or a range such
				as ``range(0, 16, 4)``.
			velocity: MIDI velocity (0-127), or a ``(low, high)`` tuple
				for a fresh random draw per step.
			duration: Note duration in beats.
			grid: How many grid slots the pattern is divided into.
				Defaults to the pattern's ``default_grid`` (set from the
				decorator's ``steps``/``step_duration``, or sixteenth-note
				resolution when ``unit`` is omitted).
			probability: Chance (0.0 to 1.0) that each hit will play.
			seed: Fix the probability gating for this call (an int); omit to
				use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Typical sixteenth-note hi-hats with some probability variation
			p.hit_steps("hh", range(16), velocity=70, probability=0.8)

			# Humanised hi-hats - each step gets a fresh random velocity.
			p.hit_steps("hh", range(16), velocity=(40, 90))
			```
		"""

		rng = self._rng_from(seed, rng)

		if grid is None:
			grid = self._default_grid

		if grid <= 0:
			return self

		step_duration = self._pattern.length / grid

		for i in steps:

			if probability < 1.0 and rng.random() >= probability:
				continue

			beat = i * step_duration
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)
		return self

	def motif (
		self,
		m: "subsequence.motifs.Motif",
		beat: subsequence.declarations.GridBeats = 0.0,
		span: typing.Optional[subsequence.declarations.GridBeats] = None,
		root: int = 60,
		velocity: typing.Optional[subsequence.declarations.VelocityValue] = None,
		fit: typing.Optional[subsequence.declarations.UnitInterval] = None,
		fit_weights: typing.Optional[typing.List[float]] = None,
		resolution: typing.Optional[int] = None,
	) -> "PatternBuilder":

		"""
		Place an immutable :class:`~subsequence.motifs.Motif` onto the pattern.

		Note events route through the universal ``note()`` funnel (drum names,
		mirrors, velocity tuples all work); control gestures emit through the
		same machinery as ``cc()`` / ``cc_ramp()`` / ``pitch_bend()`` /
		``nrpn()`` / ``osc()``.  Pitch specs resolve here, late: ints are MIDI,
		strings are drum names, scale degrees resolve against the composition
		key + scale anchored near ``root=``.  Per-event probabilities roll
		fresh each cycle against the pattern's seeded stream.

		Parameters:
			m: The motif value (anything exposing ``.events`` / ``.length``
				places; ``.controls`` is read when present).
			beat: Where the motif starts within the pattern.
			span: Clamp - events whose onset falls at or beyond *span* beats
				into the motif are dropped (the ``arpeggio()`` convention).
			root: Register anchor for scale-degree resolution: the tonic
				lands at its nearest instance to this MIDI note (ties resolve
				upward) and the melody keeps its written contour from there.
			velocity: Optional override applied to every note (otherwise each
				event's own velocity is used).
			fit: The chord-tones-on-strong-beats dial, 0.0–1.0: resolved
				Degree/int pitches landing on strong beats (metric weight
				>= 0.5) snap to the nearest chord tone with this
				probability.  Defaults to each note's own ``fit`` (0.7 on
				the notes ``Motif.generate()`` makes, none on hand-written
				ones - typed degrees are sacred), so a written line beside a
				generated one still plays as written; inactive without a
				chord context.  ChordTone
				and Approach events never snap - their harmony reading is
				inherent (an Approach's chromaticism is the point).
			fit_weights: Custom per-step metric weight list (the
				``build_ghost_bias`` precedent) for additive or
				non-isochronous meters; defaults to the time signature's
				table.
			resolution: Pulses between control-ramp messages (defaults to
				each control verb's own default).  Kept out of the value by
				design: beats and shapes are music, traffic density is wire.
		"""

		events = getattr(m, "events", None)

		if events is None or not hasattr(m, "length"):
			raise TypeError(f"motif() places Motif-like values (.events/.length) - got {type(m).__name__}")

		# The dial is each note's own (#3458): generate() gives the notes it
		# makes 0.7 and a written note has none, so a written note beside a
		# generated one plays as written.  fit= sets it for every note.
		def note_fit (event: typing.Any) -> typing.Optional[float]:
			return fit if fit is not None else getattr(event, "fit", None)

		fit_table: typing.Optional[typing.List[float]] = None

		if any(note_fit(event) for event in events):
			fit_table = list(fit_weights) if fit_weights is not None else subsequence.sequence_utils.build_metric_weights(
				self.time_signature, grid = self._default_grid
			)

		for event in events:

			if span is not None and event.beat >= span:
				continue
			if event.probability < 1.0 and self.rng.random() >= event.probability:
				continue

			resolved = self._resolve_motif_pitch(event.pitch, root, beat + event.beat)

			# A captured drum carries the name it was placed by, so place it by
			# that name: this kit resolves its own number, a mirror carrying
			# its own map sounds its own voice, and a kit with no such voice
			# drops it rather than playing a number that means something else
			# there (#2372).  A named drum has no pitch to snap either.
			if isinstance(resolved, int) and getattr(event, "origin", None) is not None:
				resolved = event.origin

			# The fit dial reads only Degree/int content: drums have no
			# pitch to snap, ChordTones already are chord tones, and an
			# Approach's chromaticism is the point.
			snap_probability = note_fit(event)

			if (
				fit_table is not None
				and snap_probability
				and isinstance(resolved, int)
				and isinstance(event.pitch, (int, subsequence.motifs.Degree))
			):
				resolved = self._fit_snap(resolved, beat + event.beat, float(snap_probability), fit_table)

			self.note(
				pitch = resolved,
				beat = beat + event.beat,
				velocity = velocity if velocity is not None else event.velocity,
				duration = event.duration,
			)

		for control in getattr(m, "controls", ()):

			if span is not None and control.beat >= span:
				continue
			if control.probability < 1.0 and self.rng.random() >= control.probability:
				continue

			self._emit_control(control, beat, resolution)

		return self

	def _resolve_motif_pitch (self, pitch: typing.Any, root: int, event_beat: float = 0.0) -> typing.Union[int, str]:

		"""Resolve one stored pitch spec to a MIDI int or drum name, late.

		``event_beat`` is the event's position within this cycle - chord-
		relative specs resolve against the chord sounding *under the event*
		(``p.harmony.chord_at``), not the cycle-start snapshot.
		"""

		if pitch is None:
			raise ValueError(
				"This motif is a rhythm skeleton (pitches stripped) - "
				"re-pitch it with .pitched() before placing"
			)

		if isinstance(pitch, (int, str)):
			return pitch

		if isinstance(pitch, subsequence.motifs.Degree):
			return self._resolve_degree_pitch(pitch, root)

		if isinstance(pitch, subsequence.motifs.ChordTone):
			return self._resolve_chord_tone_pitch(pitch, root, event_beat)

		if isinstance(pitch, subsequence.motifs.Approach):
			return self._resolve_approach_pitch(pitch, root, event_beat)

		raise TypeError(f"Unknown pitch spec: {type(pitch).__name__}")

	def _resolve_approach_pitch (self, approach: "subsequence.motifs.Approach", root: int, event_beat: float) -> int:

		"""Resolve an Approach: one semitone below its target's pitch.

		A ``ChordTone`` target reads the chord at the NEXT boundary after the
		event (the harmony window's anticipation data) - the approach is the
		tension, the target is where the harmony lands.  When the window
		holds no committed next chord (the live mode horizon's edge), the
		sounding chord stands in.  ``Degree``/``int`` targets resolve as
		usual (no harmony needed).
		"""

		target = approach.target

		if isinstance(target, subsequence.motifs.ChordTone):

			if self.harmony is None:
				raise ValueError(
					"an Approach at a chord tone needs the harmonic clock - "
					"call composition.harmony(...) (a style or a bound progression)"
				)

			chord = self.harmony.next_chord_at(event_beat)

			if chord is None:
				chord = self.harmony.chord_at(event_beat)
			if chord is None:
				raise ValueError(
					f"No chord is known around beat {event_beat:g} of this cycle - "
					"the harmony window does not cover it"
				)

			tones = chord.tones(root, count = target.index)
			resolved = int(tones[target.index - 1]) + 12 * target.octave

		elif isinstance(target, subsequence.motifs.Degree):
			resolved = self._resolve_degree_pitch(target, root)

		elif isinstance(target, int):
			resolved = target

		else:
			raise TypeError(f"cannot approach {type(target).__name__} content")

		pitch = resolved - 1

		if not 0 <= pitch <= 127:
			raise ValueError(
				f"Approach resolves to MIDI {pitch}, outside 0–127 - adjust root= or the target's octave"
			)

		return pitch

	def _fit_snap (self, pitch: int, event_beat: float, fit: float, weights: typing.List[float]) -> int:

		"""The fit dial: snap a strong-beat pitch to the nearest chord tone, with probability *fit*.

		Strong beats are the metric-weight table's >= 0.5 positions
		(downbeats and beats); off-grid events take the nearest grid
		position's weight.  Inactive without a chord context.
		"""

		if self.harmony is None:
			return pitch

		bar_beats = self.bar_beats
		grid = len(weights)
		step = (event_beat % bar_beats) * grid / bar_beats
		weight = weights[int(round(step)) % grid]

		if weight < 0.5:
			return pitch
		if self.rng.random() >= fit:
			return pitch

		chord = self.harmony.chord_at(event_beat)

		if chord is None:
			return pitch

		chord_pcs = {tone % 12 for tone in chord.tones(pitch)}

		if pitch % 12 in chord_pcs:
			return pitch

		# Nearest chord tone, ties upward.
		for delta in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6):
			if (pitch + delta) % 12 in chord_pcs and 0 <= pitch + delta <= 127:
				return pitch + delta

		return pitch

	def _resolve_chord_tone_pitch (self, tone: "subsequence.motifs.ChordTone", root: int, event_beat: float) -> int:

		"""Resolve a 1-based chord-tone index against the chord under the event.

		Reads the harmony window (``p.harmony.chord_at(event_beat)``): indices
		walk the sounding chord's tones nearest ``root``, cycling into higher
		octaves past the chord's natural size, plus whole-octave shifts.
		"""

		if self.harmony is None:
			raise ValueError(
				"ChordTone pitches resolve against the harmonic clock - "
				"call composition.harmony(...) (a style or a bound progression)"
			)

		chord = self.harmony.chord_at(event_beat)

		if chord is None:
			raise ValueError(
				f"No chord is known at beat {event_beat:g} of this cycle - "
				"the harmony window does not cover it"
			)

		tones = chord.tones(root, count = tone.index)
		midi = int(tones[tone.index - 1]) + 12 * tone.octave

		if not 0 <= midi <= 127:
			raise ValueError(
				f"Chord tone {tone.index} resolves to MIDI {midi}, outside 0–127 - "
				"adjust root= or the tone's octaves"
			)

		return midi

	def _resolve_degree_pitch (self, degree: "subsequence.motifs.Degree", root: int) -> int:

		"""
		Resolve a 1-based scale degree against the composition key + scale.

		The tonic anchors at its nearest instance to ``root`` (ties resolve
		upward); the degree then builds from the anchored tonic, so a written
		melody keeps its contour.  Steps beyond the scale length carry into
		higher octaves (8 = tonic an octave up in seven-note scales), and
		steps of 0 and below into lower ones (0 = the step under the tonic).
		"""

		if self.key is None:
			raise ValueError("Scale degrees resolve against a key - set Composition(key=...)")

		mode = self.scale or "ionian"
		pcs = subsequence.intervals.scale_pitch_classes(subsequence.chords.key_name_to_pc(self.key), mode)

		idx = (degree.step - 1) % len(pcs)
		carry = (degree.step - 1) // len(pcs)

		diff = (pcs[0] - root) % 12
		tonic = root + diff if diff <= 6 else root + diff - 12
		offset = (pcs[idx] - pcs[0]) % 12

		midi = tonic + offset + 12 * (carry + degree.octave) + degree.chroma

		if not 0 <= midi <= 127:
			raise ValueError(
				f"Degree {degree.step} resolves to MIDI {midi}, outside 0–127 - "
				f"adjust root= or the degree's octaves"
			)

		return midi

	def _emit_control (self, control: "subsequence.motifs.ControlEvent", beat: subsequence.declarations.GridBeats, resolution: typing.Optional[int]) -> None:

		"""Emit one stored control gesture through the matching builder verb."""

		signal = control.signal
		onset = beat + control.beat
		extra: typing.Dict[str, typing.Any] = {} if resolution is None else {"resolution": resolution}

		# A ramp a window caught part of keeps the WHOLE gesture's start and
		# end, and plays the piece of the curve it actually covers — so the
		# endpoints below are the gesture's own and only the shape changes.
		# Handing the verb the piece's own endpoints instead would round them
		# to ints and bend everything after by up to a whole step (#3010).
		curve = control._emission_shape()

		if isinstance(signal, subsequence.motifs.CC):
			if control.end is None:
				self.cc(signal.control, int(round(control.start)), beat=onset)
			else:
				self.cc_ramp(signal.control, int(round(control.start)), int(round(control.end)), beat_start=onset, beat_end=onset + control.span, shape=curve, **extra)

		elif isinstance(signal, subsequence.motifs.PitchBend):
			if control.end is None:
				self.pitch_bend(control.start, beat=onset)
			else:
				self.pitch_bend_ramp(control.start, control.end, beat_start=onset, beat_end=onset + control.span, shape=curve, **extra)

		elif isinstance(signal, subsequence.motifs.NRPN):
			if control.end is None:
				self.nrpn(signal.parameter, int(round(control.start)), beat=onset, fine=signal.fine, null_reset=signal.null_reset)
			else:
				self.nrpn_ramp(signal.parameter, int(round(control.start)), int(round(control.end)), beat_start=onset, beat_end=onset + control.span, shape=curve, fine=signal.fine, null_reset=signal.null_reset, **extra)

		elif isinstance(signal, subsequence.motifs.RPN):
			if control.end is None:
				self.rpn(signal.parameter, int(round(control.start)), beat=onset, fine=signal.fine, null_reset=signal.null_reset)
			else:
				self.rpn_ramp(signal.parameter, int(round(control.start)), int(round(control.end)), beat_start=onset, beat_end=onset + control.span, shape=curve, fine=signal.fine, null_reset=signal.null_reset, **extra)

		elif isinstance(signal, subsequence.motifs.OSC):
			if control.end is None:
				self.osc(signal.address, control.start, beat=onset)
			else:
				self.osc_ramp(signal.address, control.start, control.end, beat_start=onset, beat_end=onset + control.span, shape=curve, **extra)

		else:
			raise TypeError(f"Unknown control signal: {type(signal).__name__}")

	def phrase (
		self,
		value: typing.Any,
		root: int = 60,
		velocity: typing.Optional[subsequence.declarations.VelocityValue] = None,
		fit: typing.Optional[subsequence.declarations.UnitInterval] = None,
		resolution: typing.Optional[int] = None,
		align: subsequence.declarations.PhraseAlign = "pattern",
		offset: subsequence.declarations.GridBeats = 0.0,
	) -> "PatternBuilder":

		"""Place this cycle's window of a Phrase - position computed, never stored.

		The playback position is stateless arithmetic over the engine's own
		counters: ``pos = (p.cycle * pattern_length + offset) % phrase.length`` -
		deterministic under live reload, ``form_jump``, and render, with
		zero new state.  A pattern shorter than the phrase walks through it
		cycle by cycle; deliberately mismatched lengths are phase drift
		(polymeter against the phrase).  When the cycle window crosses the
		phrase's end, the phrase loops.

		Patterns that should own the phrase's length call
		``p.set_length(phrase.length)`` once instead.

		Parameters:
			value: A Phrase (or any value with ``.length``/``.slice``; a
				Motif places its window directly).
			root: Register anchor for degree resolution (see ``motif()``).
			velocity: Optional override applied to every note.
			fit: Passed through to ``motif()`` (active with the melody
				engine stage).
			resolution: Control-ramp pulse density (see ``motif()``).
			align: ``"pattern"`` (default) counts pattern cycles;
				``"section"`` uses the bar within the current form section,
				so the phrase restarts when the section does.
			offset: Beats added to the computed position (a phase shift).

		Example:
			```python
			@comp.pattern(channel=4, bars=2)
			def lead (p):
				p.phrase(lead_line, root=72)
			```
		"""

		length = getattr(value, "length", None)

		if length is None or not hasattr(value, "slice"):
			raise TypeError(f"phrase() places Phrase-like values (.length/.slice) - got {type(value).__name__}")
		if length <= 0:
			raise ValueError("cannot place an empty phrase")

		if align == "pattern":
			position = (self.cycle * float(self._pattern.length) + offset) % length
		elif align == "section":
			if self.section is None:
				raise ValueError('phrase(align="section") needs a form - call composition.form(...)')
			position = (self.section.bar * self.bar_beats + offset) % length
		else:
			raise ValueError(f'align must be "pattern" or "section" - got {align!r}')

		window_beats = float(self._pattern.length)
		placed = 0.0

		while placed < window_beats - 1e-9:

			take = min(window_beats - placed, length - position)
			piece = value.slice(position, position + take)
			fragment = piece.flatten() if hasattr(piece, "flatten") else piece

			self.motif(fragment, beat=placed, root=root, velocity=velocity, fit=fit, resolution=resolution)

			placed += take
			position = 0.0	# crossed the phrase end — loop to its start

		return self

	def section_motif (self, part: typing.Optional[str] = None) -> typing.Optional[typing.Any]:

		"""The Motif/Phrase bound to the current section (and part), or ``None``.

		Reads the ``composition.section_motifs()`` registry for the section
		currently playing.  A section with no binding returns ``None`` -
		bind material or rest; no fallback guessing::

			@comp.pattern(channel=4, bars=2)
			def lead (p):
				line = p.section_motif("lead")
				if line is not None:
					p.phrase(line, root=72)
		"""

		if self.section is None or self._section_motifs is None:
			return None

		return self._section_motifs.get((self.section.name, part))

	def scratch (self, name: str = "scratch") -> "PatternBuilder":

		"""An empty builder sharing this pattern's musical context.

		Everything a generator reads is carried over - key, scale, harmony,
		section, bar, cycle, conductor, tweaks, shared data, drum and control
		name maps, held notes, time signature and energy - so a generator
		behaves the same on a scratch as it does here.  A composition can build
		one by hand, and then it holds a dozen copied fields that go stale the
		day a thirteenth is added.

		The scratch has its own empty pattern of the same length, so nothing it
		places sounds.  Read the result back with :meth:`capture` or
		:meth:`placed`, and place it here with :meth:`motif`.

		**The random stream is a child, not the same one.**  Sharing this
		builder's would advance it, so how the parent's later draws come out
		would depend on how many scratches were made - and ``lock()`` promises
		a pattern realises identically each cycle, which would then be true
		only for a fixed number of them.  A fresh unseeded stream would be
		worse: it would break reproducibility outright.  So the child is
		derived by name, the same ``crc32`` way ``Composition`` derives a
		pattern's stream from the composition seed, and from where this
		pattern's stream stood when the build began.  Set a seed once at the
		top and every scratch under it is reproducible, and it changes from
		cycle to cycle exactly when this pattern does: under ``lock()`` it
		repeats, as the pattern does.  Two scratches with different names never
		draw the same numbers.

		Parameters:
			name: Names this scratch's stream.  Give each one its own name if
				you make several, or they draw identically.

		Example:
			```python
			@composition.pattern(channel=10, beats=4)
			def drums (p):
				p.hit("kick", [0, 2])
				layer = p.scratch("hats").euclidean("hihat_closed", pulses=7)
				p.motif(layer.capture(0.0, 4.0))
			```
		"""

		child = subsequence.pattern.Pattern(
			channel = self._pattern.channel,
			length = self._pattern.length,
			device = self._pattern.device,
			# The same destinations, so a voice only a mirror's kit has still
			# resolves here: without them a scratch dropped it, and the layer
			# lost a part of the kit that plays perfectly well (#2968).
			mirrors = self._pattern.mirrors,
		)

		# One pattern as far as warnings go: a drum name nothing maps is
		# reported once across the pattern and its scratches, naming the
		# pattern rather than a channel.
		child._warned_drum_names = self._pattern._warned_drum_names
		builder_fn = getattr(self._pattern, "_builder_fn", None)

		if builder_fn is not None:
			child._builder_fn = builder_fn		# type: ignore[attr-defined]

		# The harmony window is anchored on the absolute beat axis, so a
		# scratch has to sit at the same place in the bar or a degree would
		# resolve against a different chord than it does here.
		child._cycle_start_pulse = self._pattern._cycle_start_pulse

		derived = (
			None if self._stream_seed is None
			else zlib.crc32(f"{self._stream_seed}:{name}:{self._stream_position()}".encode())
		)

		return PatternBuilder(
			pattern = child,
			cycle = self.cycle,
			conductor = self.conductor,
			drum_note_map = self._drum_note_map,
			cc_name_map = self._cc_name_map,
			nrpn_name_map = self._nrpn_name_map,
			section = self.section,
			bar = self.bar,
			rng = random.Random(derived),
			tweaks = self._tweaks,
			default_grid = self._default_grid,
			data = self.data,
			key = self.key,
			scale = self.scale,
			time_signature = self.time_signature,
			held_notes = self._held_notes,
			harmony = self.harmony,
			section_motifs = self._section_motifs,
			energy = self.energy,
			stream_seed = derived,
			zero_indexed_channels = self._zero_indexed_channels,
		)


	def _stream_position (self) -> int:

		"""A fingerprint of where this pattern's stream stood as the build began: the same on every platform, and 0 unseeded."""

		if self._stream_at_start is None:
			return 0

		words = self._stream_at_start[1]

		return zlib.crc32(struct.pack(f"<{len(words)}I", *words))

	def placed (self) -> typing.List[subsequence.pattern.PlacedNote]:

		"""Read back every note placed on this pattern so far.

		Answers "which notes did that generator put there" without reaching
		into the pattern: call it either side of a verb and take the
		difference.  A control surface uses it to draw a generated layer in a
		different style from the steps somebody tapped by hand.

		Returns a list of :class:`~subsequence.pattern.PlacedNote` - a frozen,
		hashable copy of each note, carrying ``origin`` so a named drum voice
		can be matched back to the panel row that asked for it.  Positions and
		durations are in pulses; a drone's ``duration`` is None.

		Only this cycle's placements are reported: the pattern is emptied at
		the start of every rebuild, so a drone still sounding from an earlier
		cycle is not here.  Note Offs are not reported either - ``note_off()``
		and ``drone_off()`` end a note rather than placing one, and drawing a
		release as a hit would show a step that never sounds.

		Ordered by position, hand-placed notes before drones at the same
		pulse.  The order is fixed only so two reads agree; nothing should
		depend on it.

		Example::

			@composition.pattern(channel=10, beats=4)
			def drums (p):
				p.hit("kick", [0, 2])
				before = set(p.placed())
				p.euclidean("hihat_closed", pulses=7)
				generated = set(p.placed()) - before
		"""

		found: typing.List[subsequence.pattern.PlacedNote] = []

		for pulse in self._pattern.steps:

			for index, note in enumerate(self._pattern.steps[pulse].notes):
				found.append(subsequence.pattern.PlacedNote(
					position = pulse,
					pitch = note.pitch,
					origin = note.origin,
					index = index,
					velocity = note.velocity,
					duration = note.duration,
					primary_unmapped = note.primary_unmapped,
				))

		# Drones live in a second collection and would otherwise report as
		# having placed nothing — a layer that sounds and does not draw.  Their
		# index counts within that collection, which is append-only for the
		# life of the build exactly as a step's note list is, so a record made
		# now still matches itself after more notes arrive.
		for index, event in enumerate(self._pattern.raw_note_events):

			if event.message_type != 'note_on':
				continue

			found.append(subsequence.pattern.PlacedNote(
				position = event.pulse,
				pitch = event.pitch,
				origin = event.origin,
				index = index,
				velocity = event.velocity,
				duration = None,
				primary_unmapped = event.primary_unmapped,
			))

		# Stable, so the steps stay ahead of the drones sharing their pulse.
		found.sort(key = lambda entry: entry.position)

		return found


	def capture (self, beat: subsequence.declarations.GridBeats = 0.0, span: float = 4.0) -> "subsequence.motifs.Motif":

		"""
		Read the notes placed so far back out as a :class:`~subsequence.motifs.Motif`.

		The captured motif is **absolute MIDI and lossy by design**: relative
		specs (degrees, chord tones) do not survive resolution, timing is
		pulse-truncated, probabilities have already rolled, and control
		gestures are not captured.  The round trip is generate → place →
		capture → hand-edit → rebind.

		A named drum is the exception: its name rides along beside the number
		as the event's ``origin``, so :meth:`~subsequence.motifs.Motif.vary`,
		:meth:`~subsequence.motifs.Motif.transpose` and
		:meth:`~subsequence.motifs.Motif.invert` go on refusing it - a varied
		kick is a different instrument, not a variation.

		**A captured drum stays a named drum when it is placed** (#2372).
		:meth:`motif` puts it back by name, so the kit it is placed on
		resolves its own number for it, a mirror carrying its own map sounds
		its own voice, and a kit with no such voice drops it with the usual
		one-time warning.  Placed back where it came from, nothing changes.

		Parameters:
			beat: Window start within the pattern.
			span: Window length in beats (also the captured motif's length).
		"""

		ppq = subsequence.constants.MIDI_QUARTER_NOTE
		lo, hi = subsequence.constants.pulses.beats_to_pulses(beat), subsequence.constants.pulses.beats_to_pulses(beat + span)
		events = []

		for pulse in sorted(self._pattern.steps):

			if not lo <= pulse < hi:
				continue

			for placed in self._pattern.steps[pulse].notes:
				events.append(subsequence.motifs.MotifEvent(
					beat = pulse / ppq - beat,
					pitch = placed.pitch,
					velocity = placed.velocity,
					duration = max(placed.duration, 1) / ppq,
					origin = placed.origin,
				))

		return subsequence.motifs.Motif(events=tuple(events), length=span)

	@subsequence.declarations.bounded
	def sequence (self, steps: typing.Sequence[subsequence.declarations.StepPosition], pitches: typing.Union[subsequence.declarations.Pitch, typing.Sequence[subsequence.declarations.Pitch]], velocities: typing.Union[int, typing.Tuple[int, int], typing.List[int]] = subsequence.constants.velocity.DEFAULT_VELOCITY, velocity: typing.Optional[subsequence.declarations.VelocityValue] = None, durations: typing.Union[float, typing.List[float]] = 0.1, grid: typing.Optional[subsequence.declarations.StepCount] = None, probability: subsequence.declarations.UnitInterval = 1.0, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "PatternBuilder":

		"""
		A multi-parameter step sequencer.

		Define which grid steps fire, and then provide a list of pitches,
		velocities, and durations. If you provide a list for any parameter,
		Subsequence will step through it as it places each note.

		Parameters:
			steps: List of grid indices to trigger. An empty list is a
				no-op - no notes are placed and the builder is returned
				unchanged (handy when probabilistic gating rejects every step).
			pitches: Pitch or list of pitches.
			velocities: Velocity (default 100), ``(low, high)`` tuple for
				a fresh random draw per step, or a list of velocities
				matched to the steps one-to-one (a short list repeats its
				final value, a long list is truncated - both warn).
			velocity: The same as ``velocities`` for a single value or a
				``(low, high)`` range, and the name every other verb uses -
				which is what a control surface drives, since a two-element
				list here means one value per step.  Pass one or the other.
			durations: Duration or list of durations (default 0.1).
			grid: Grid resolution. Defaults to the pattern's
				``default_grid`` (derived from the decorator's ``beats``/``steps``
				and ``unit``).
			probability: Chance (0.0 to 1.0) that each step will play.
			seed: Fix the probability gating for this call (an int); omit to
				use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).
		"""

		if not steps:
			return self

		if velocity is not None:

			if velocities != subsequence.constants.velocity.DEFAULT_VELOCITY:
				raise ValueError("sequence() takes velocity= or velocities=, not both: velocity= is one value or a (low, high) range, velocities= is one value per step")

			# A list here is the range a surface sends, never one value per
			# step: that is what velocities= is for (#2963).
			if isinstance(velocity, list):

				if len(velocity) != 2:
					raise ValueError(f"velocity= takes one value or a (low, high) range; for one value per step use velocities=, got {velocity!r}")

				velocities = (int(velocity[0]), int(velocity[1]))

			else:
				velocities = velocity

		rng = self._rng_from(seed, rng)

		if grid is None:
			grid = self._default_grid

		if grid <= 0:
			return self

		n = len(steps)
		pitches_list = _expand_sequence_param("pitches", pitches, n)
		# Treat a (low, high) tuple as a single random-range descriptor
		# rather than a 2-element list to cycle through.
		if isinstance(velocities, tuple):
			velocities_list = [velocities] * n
		else:
			velocities_list = _expand_sequence_param("velocities", velocities, n)
		durations_list = _expand_sequence_param("durations", durations, n)

		step_duration = self._pattern.length / grid

		for i, step_idx in enumerate(steps):

			if probability < 1.0 and rng.random() >= probability:
				continue

			beat = step_idx * step_duration
			self.note(pitch=pitches_list[i], beat=beat, velocity=velocities_list[i], duration=durations_list[i])
		return self

	def seq (self, notation: str, pitch: typing.Union[str, int, None] = None, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "PatternBuilder":

		"""
		Build a pattern using an expressive string-based 'mini-notation'.

		The notation distributes events evenly across the current pattern length.

		**Syntax:**

		- ``x y z``: Items separated by spaces are distributed across the bar.
		- ``[a b]``: Groups items into a single subdivided step.
		- ``~`` or ``.``: A rest.
		- ``_``: Extends the previous note (sustain).
		- ``x?0.6``: Probability suffix - fires with the given probability (0.0–1.0).

		Parameters:
			notation: The mini-notation string.
			pitch: If provided, all symbols in the string are triggers for
				this specific pitch. If ``None``, symbols are interpreted as
				pitches (e.g., "60" or "kick").
			velocity: MIDI velocity (default 100), or a ``(low, high)``
				tuple for a fresh random draw per event.
			seed: Fix the ``?`` probability gating for this call (an int);
				omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Simple kick rhythm
			p.seq("kick . [kick kick] .")

			# Subdivided melody
			p.seq("60 [62 64] 67 60")

			# Ghost snare: snare on 2 and 4, ghost note 50% of the time
			p.seq(". snare?0.5 . snare")
			```
		"""

		rng = self._rng_from(seed, rng)

		events = subsequence.mini_notation.parse(notation, total_duration=float(self._pattern.length))

		for event in events:

			# Apply probability before placing the note.
			if event.probability < 1.0 and rng.random() >= event.probability:
				continue

			current_pitch = pitch

			# If no global pitch provided, use the symbol as the pitch
			if current_pitch is None:
				# Try converting to int if it looks like a number
				if event.symbol.isdigit():
					current_pitch = int(event.symbol)
				else:
					current_pitch = event.symbol

			self.note(
				pitch = current_pitch,
				beat = event.time,
				duration = event.duration,
				velocity = velocity
			)
		return self

	@subsequence.declarations.bounded
	def repeat (self, pitch: subsequence.declarations.Pitch, spacing: typing.Annotated[float, subsequence.declarations.Span(low=0.01), subsequence.declarations.Unit("beats"), subsequence.declarations.Step(0.25)], velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY, duration: subsequence.declarations.GateBeats = 0.25) -> "PatternBuilder":

		"""
		Repeat a note at a fixed beat interval for the whole pattern.

		The classic 'Note Repeat' of MPC, Push, and Maschine fame: one
		pitch firing at a steady rate - running hi-hats, a pulsing bass
		note, a metronome click.

		Parameters:
			pitch: MIDI note number or drum name.
			spacing: Time between each note in beats (0.25 = sixteenth notes).
			velocity: MIDI velocity (default 100), or a ``(low, high)``
				tuple for a fresh random draw per note.
			duration: Note duration in beats.

		Example:
			```python
			p.repeat("hh", spacing=0.25)                       # sixteenth notes
			p.repeat("hh", spacing=0.25, velocity=(40, 80))    # humanised
			```
		"""

		if spacing <= 0:
			raise ValueError("Spacing must be positive")

		for beat in subsequence.pattern.spaced_onsets(0.0, self._pattern.length, spacing):
			self.note(pitch=pitch, beat=beat, velocity=velocity, duration=duration)
		return self

	def arpeggio (
		self,
		notes: typing.Union[
			subsequence.chords.Chord,
			str,
			typing.Sequence[subsequence.declarations.Pitch],
		],
		root: typing.Optional[int] = None,
		velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_VELOCITY,
		count: typing.Optional[int] = None,
		inversion: int = 0,
		beat: subsequence.declarations.GridBeats = 0.0,
		span: typing.Optional[subsequence.declarations.GridBeats] = None,
		spacing: subsequence.declarations.GridBeats = 0.25,
		duration: typing.Optional[subsequence.declarations.GateBeats] = None,
		direction: subsequence.declarations.ArpeggioDirection = "forward",
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None
	) -> "PatternBuilder":

		"""
		Arpeggiate a chord (or a list of pitches) - cycle the notes one at a time
		at regular beat intervals.

		Like ``chord()`` and ``strum()``, the first argument can be a chord - the
		``chord`` passed to your pattern function, or any chord from
		``p.progression()`` - and ``root`` / ``count`` / ``inversion`` voice it
		exactly as they do.  So "play this as a chord, a strum, or an arpeggio" is a
		one-word verb swap::

			for chord, start, length in p.progression("phrygian_minor", harmonic_rhythm=...):
				p.arpeggio(chord, root=48, beat=start, span=length, spacing=0.25, count=4)

		Pass a list of pitches instead to arpeggiate something that isn't a chord (a
		scale fragment, a custom voicing).  Unlike a held ``chord()``, an arpeggio is
		a stream of single notes, so it has no ``sustain`` / ``legato`` / ``detached`` -
		use ``duration`` for how long each note rings and ``span`` for how much of
		the bar the figure fills.

		An empty pitch list rests (places nothing), so a live arpeggiator over
		``p.held_notes()`` is simply silent when no keys are held::

			p.arpeggio(p.held_notes(), direction="forward")

		Parameters:
			notes: A chord to arpeggiate - anything with a ``.tones()`` method (the
				pattern's ``chord``, or a chord from ``p.progression()``), or a
				chord *name* like ``"Cmaj7"``, which is the form a control
				surface can send - or a list of MIDI note numbers (e.g. ``60``)
				/ drum-name strings when the
				pattern has a ``drum_note_map``.  For pitched note *names* use the
				integer constants in ``subsequence.constants.midi_notes`` (e.g.
				``notes.C4``).  In the list form, a drum name the map lacks is
				dropped (warned once); a string with no map at all still raises.
			root: MIDI root note for the chord form (e.g. 48), exactly as ``chord()``.
				Required for a chord; not used for a plain pitch list.
			velocity: MIDI velocity for all notes (default 100 - arpeggios sit in the
				melodic-line velocity bucket, not the softened-chord bucket; pass
				``velocity=90`` to match ``chord()``), or a ``(low, high)`` tuple for
				a fresh random draw per note.
			count: Number of voices for the chord form (cycles tones into higher
				octaves if larger than the chord's natural size).  Chord form only.
			inversion: Chord inversion for the chord form (ignored when voice leading
				is on).  Chord form only.
			beat: Beat to start the figure at (default 0.0 = the start of the
				pattern).  Use it to place an arpeggio over one progression chord.
			span: How many beats the figure fills, starting at ``beat`` (default: to
				the end of the pattern).  Pass the chord's ``length`` from a
				progression loop to confine the arpeggio to its slot.
			spacing: Time between each note in beats (default 0.25 = 16th note).
			duration: Note duration in beats.  Defaults to ``spacing`` (each note
				fills its slot exactly).
			direction: Order in which the notes are cycled.

				``forward`` and ``reverse`` walk the pitches **in the order
				they were given**.  For a chord that is ascending, because a
				chord's tones arrive sorted; for a list somebody chose it is
				the order they chose, which is musically real - ``G, C, E``
				is a different figure from ``C, E, G``.  The ``low_to_high``
				pair sorts by pitch first, whatever order they arrived in.

				- ``"forward"`` - as given, then wrap (default).
				- ``"reverse"`` - as given, backwards.
				- ``"forward_and_back"`` - as given, there and back (ping-pong).
				- ``"low_to_high"`` - sorted, ascending.
				- ``"high_to_low"`` - sorted, descending.
				- ``"low_to_high_and_back"`` - sorted, there and back: the
				  figure a hardware arpeggiator calls up-down.
				- ``"random"`` - shuffled once per call using *rng*.

			seed: Fix the ``direction="random"`` shuffle for this call (an
				int); omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			# Arpeggiate the pattern's current chord, four voices ascending
			p.arpeggio(chord, root=60, count=4, spacing=0.25)

			# A list you chose, there and back: C E G E C E G E ...
			p.arpeggio([60, 64, 67], spacing=0.25, direction="forward_and_back")

			# One chord of a progression, confined to its slot, humanised
			p.arpeggio(chord, root=48, beat=start, span=length, velocity=(60, 95))
			```
		"""

		if beat < 0:
			raise ValueError("arpeggio beat must be >= 0 - use a positive start within the pattern")

		if spacing <= 0:
			raise ValueError("Spacing must be positive")

		# A chord — an object with .tones(), or a name like "Cmaj7" — is voiced via
		# root/count/inversion; anything else is an explicit list of pitches.
		resolved = self._pitches_from("arpeggio", notes, root, inversion, count)

		if not resolved:
			# Nothing held (p.arpeggio(p.held_notes()) with no keys down), or every
			# named voice was one this device lacks — either way, a rest.
			return self

		self._check_direction("arpeggio", direction, _ARPEGGIO_DIRECTIONS)

		if direction in ("low_to_high", "high_to_low", "low_to_high_and_back"):
			resolved = sorted(resolved, key=lambda entry: entry[0])

		if direction in ("reverse", "high_to_low"):
			resolved = list(reversed(resolved))
		elif direction in ("forward_and_back", "low_to_high_and_back"):
			# There and back without repeating either end, so the figure reads
			# as one gesture rather than a stutter at the turns.
			if len(resolved) > 1:
				resolved = resolved + list(reversed(resolved[1:-1]))
		elif direction == "random":
			rng = self._rng_from(seed, rng)
			resolved = list(resolved)
			rng.shuffle(resolved)

		if duration is None:
			duration = spacing

		# Window the figure to [beat, beat + span), clamped to the pattern end so a
		# positioned arpeggio (e.g. one chord of a progression) stays in its slot.
		pattern_length = float(self._pattern.length)

		if span is None:
			end = pattern_length
		else:
			if span <= 0:
				raise ValueError(f"span must be positive, got {span:g}")
			end = beat + span

		end = min(end, pattern_length)

		# Place notes one at a time via self.note() so a (low, high)
		# velocity tuple produces a fresh random draw per arp note.
		for i, position in enumerate(subsequence.pattern.spaced_onsets(beat, end, spacing)):
			midi, origin, _ = resolved[i % len(resolved)]
			self.note(
				# The name where there is one, so note() resolves and carries it
				# exactly as a hand-written p.note("kick") would.
				pitch = midi if origin is None else origin,
				beat = position,
				velocity = velocity,
				duration = duration,
			)
		return self

	def _warn_positioned_articulation (self, method: str, beat: subsequence.declarations.GridBeats) -> None:

		"""Warn (once per pattern) that ``sustain``/``detached`` ring from the pattern
		length, not from ``beat``.

		``chord``/``strum`` size ``sustain``/``detached`` against the whole pattern (the
		one-chord-fills-the-bar model).  With a non-zero ``beat`` - e.g. placing several
		chords across a progression - that almost always rings the chord far past its
		slot, so we flag it.  Deduped on the pattern so a hot-reloading builder warns once.
		"""

		if self._pattern._warned_positioned_articulation:
			return
		self._pattern._warned_positioned_articulation = True
		logger.warning(
			"%s(beat=%g, …) was called with sustain= or detached= set - those size the ring "
			"from the pattern length, not from beat, so the chord can sustain past its slot.  "
			"For a positioned chord (e.g. over a progression) set duration= explicitly instead.",
			method, beat,
		)

	def _as_chord (self, value: typing.Any) -> typing.Optional[subsequence.chords.Chord]:

		"""The chord *value* is or names, or None when it is a list of pitches.

		A name like ``"Cmaj7"`` is the form a control surface can send - a
		``Chord`` is a Python object and does not cross a wire - so a string
		here is read as a chord name rather than as a sequence of pitches.  It
		could not honestly be the latter: every character would have to be a
		drum voice, and a one-character voice name is not a thing anybody has.
		"""

		if isinstance(value, str):
			return subsequence.chords.parse_chord(value)

		if hasattr(value, "tones"):
			return typing.cast(subsequence.chords.Chord, value)

		return None


	def _pitches_from (
		self,
		method: str,
		value: typing.Union[subsequence.chords.Chord, str, typing.Sequence[subsequence.declarations.Pitch]],
		root: typing.Optional[int],
		inversion: int,
		count: typing.Optional[int],
	) -> typing.List[typing.Tuple[int, typing.Optional[str], bool]]:

		"""Voice a chord, or resolve a plain pitch list - the shared first argument.

		``chord()``, ``strum()``, ``broken_chord()`` and ``arpeggio()`` all take
		"a chord, or the pitches themselves".  A chord - an object with
		``.tones()``, or a name like ``"Cmaj7"`` - is voiced through
		``root``/``inversion``/``count``; a sequence is resolved as pitches,
		leniently, so a drum name no destination can voice is dropped rather
		than raising, and those three voicing arguments are refused because
		they would mean nothing for a list somebody has already chosen.

		Each entry is ``(midi_pitch, origin, primary_unmapped)`` - the same
		triple :meth:`_resolve_hit_pitch` returns, so a named voice keeps its
		name all the way to the ``Note``.  Without that these three verbs
		placed notes no surface could match to the row that sounds them, where
		``hit_steps``, ``note``, ``euclidean`` and ``de_bruijn`` all carried it
		(#2395).  A chord's tones are numbers nobody named, so their origin is
		``None``.

		May return an empty list - an empty pool, or every named voice was one
		this device lacks.  The caller decides what that means; for a placing
		verb it is a rest.
		"""

		chord = self._as_chord(value)

		if chord is None:
			self._refuse_voicing_arguments(method, root, inversion, count)
			resolved = (self._resolve_hit_pitch(p) for p in typing.cast(typing.Sequence[typing.Any], value))
			return [r for r in resolved if r is not None]

		if root is None:
			raise ValueError(
				f"{method}(<chord>, …) needs a root - e.g. {method}(chord, root=48); "
				"pass a root MIDI note, or hand a list of pitches instead"
			)

		return [(tone, None, False) for tone in chord.tones(root=root, inversion=inversion, count=count)]


	def _check_direction (self, method: str, direction: str, allowed: typing.Tuple[str, ...]) -> None:

		"""Refuse an unknown cycling direction, naming the replacement for a retired one.

		``up``, ``down`` and ``up_down`` were retired rather than redefined
		(#2414).  They walked the pitches in the order they were given while
		the docstring promised lowest to highest, and a name that quietly
		changed meaning would have altered what existing pieces play with
		nothing to notice it - where an unknown name stops the call and says so.
		"""

		if direction in allowed:
			return

		replacement = subsequence.declarations.RETIRED_DIRECTIONS.get(direction)

		if replacement is not None and replacement in allowed:
			raise ValueError(
				f"{method} direction '{direction}' was retired because it never sorted - "
				f"'{replacement}' plays exactly what it played, and 'low_to_high' is what "
				"its documentation described"
			)

		raise ValueError(f"{method} direction must be one of {', '.join(allowed)} - got '{direction}'")


	def _refuse_voicing_arguments (self, method: str, root: typing.Optional[int], inversion: int, count: typing.Optional[int] = None) -> None:

		"""Reject root/inversion/count when the caller passed plain pitches.

		They voice a chord and mean nothing for a list somebody has already
		chosen - silently ignoring them would look like they had been applied.
		"""

		if root is not None or count is not None or inversion != 0:
			raise ValueError(
				f"{method} root=, count=, and inversion= only apply to the chord form - "
				f"{method}(chord, root=48); with a plain pitch list, drop them"
			)


	def chord (self, chord_obj: typing.Union[subsequence.chords.Chord, str, typing.Sequence[subsequence.declarations.Pitch]], root: typing.Optional[int] = None, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, sustain: bool = False, duration: subsequence.declarations.GateBeats = 1.0, inversion: int = 0, count: typing.Optional[int] = None, legato: typing.Optional[subsequence.declarations.UnitInterval] = None, detached: typing.Optional[subsequence.declarations.GateBeats] = None, beat: subsequence.declarations.GridBeats = 0.0) -> "PatternBuilder":

		"""
		Place a chord at ``beat`` (the start of the pattern by default).

		Note: If the pattern was registered with ``voice_leading=True``,
		this method automatically chooses the best inversion.

		Parameters:
			chord_obj: The chord to play (usually the ``chord`` parameter
				passed to your pattern function, or a name like
				``"Cmaj7"``) - or, exactly as ``arpeggio()`` takes it, a
				plain list of pitches to voice as written: MIDI note
				numbers, or drum names when the pattern has a
				``drum_note_map``.  A name is carried to the mirror
				fan-out so each device re-resolves it through its own
				map; one no destination maps at all is dropped (warned
				once), and an empty list rests.
			root: MIDI root note (e.g., 60 for Middle C).  Required for a
				chord, and not used for a plain pitch list - passing it
				with one raises, rather than looking as though it applied.
			velocity: MIDI velocity (default 90), or a ``(low, high)``
				tuple for a fresh random draw per chord tone (each
				voice gets a slightly different velocity - useful for
				humanising the "fingers" feel).
			sustain: If True, the notes last for the entire pattern duration.
				Mutually exclusive with ``legato`` and ``detached``.
			duration: Note duration in beats (default 1.0). Ignored when
				``legato`` or ``detached`` is set, since those recalculate
				durations.
			inversion: Specific chord inversion (ignored if voice leading is on).
			count: Number of notes to play (cycles tones if higher than
				the chord's natural size).
			legato: If given, the chord rings for ``ratio`` of the gap to
				the next attack after it (round the cycle, where it plays
				again, if nothing comes sooner), measured once the build is
				done - so a chord placed later still cuts it, and nothing
				else in the pattern is resized.  Mutually exclusive with
				``sustain`` and ``detached``.
			detached: If given, the chord rings until ``detached`` beats
				before the next cycle - equivalent to setting
				``duration = pattern.length - detached``.  Use this for a
				declarative polyphony-safety margin so the chord always
				releases before the next chord begins.  Mutually exclusive
				with ``sustain`` and ``legato``.
			beat: Beat offset to place the chord at (default 0.0 = the start of the
				pattern).  ``sustain`` and ``detached`` still measure their ring from the
				pattern length, not from ``beat`` - when placing several positioned chords
				(e.g. over a progression) set ``duration`` explicitly instead.

		Example::

			# Ring each chord for 90% of the way to the next one
			p.chord(chord, root=root, velocity=85, count=4, legato=0.9)

			# Hold the chord almost the full cycle, releasing 0.25 beats
			# before the next chord begins.
			p.chord(chord, root=root, velocity=85, count=5, detached=0.25)
		"""

		set_count = (1 if sustain else 0) + (1 if legato is not None else 0) + (1 if detached is not None else 0)
		if set_count > 1:
			raise ValueError("sustain=, legato=, and detached= are mutually exclusive - use one or the other")

		if beat != 0.0 and (sustain or detached is not None):
			self._warn_positioned_articulation("chord", beat)

		pitches = self._pitches_from("chord", chord_obj, root, inversion, count)

		if not pitches:
			return self	# an empty pool, or every named voice missing here — rest

		if sustain:
			duration = float(self._pattern.length)
		elif detached is not None:
			duration = float(self._pattern.length) - detached
			if duration <= 0:
				raise ValueError(f"detached ({detached}) must be less than the pattern length ({self._pattern.length:g} beats) so the chord keeps a positive duration")

		placed_before = self._note_ids() if legato is not None else set()

		for pitch, origin, unmapped in pitches:
			self._pattern.add_note_beats(
				beat_position = beat,
				pitch = pitch,
				velocity = self._resolve_velocity(velocity),
				duration_beats = duration,
				origin = origin,
				primary_unmapped = unmapped,
			)

		if legato is not None:
			self._legato_own_notes(placed_before, legato)
		return self

	def strum (self, chord_obj: typing.Union[subsequence.chords.Chord, str, typing.Sequence[subsequence.declarations.Pitch]], root: typing.Optional[int] = None, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, sustain: bool = False, duration: subsequence.declarations.GateBeats = 1.0, inversion: int = 0, count: typing.Optional[int] = None, spacing: subsequence.declarations.GateBeats = 0.05, direction: subsequence.declarations.StrumDirection = "forward", legato: typing.Optional[subsequence.declarations.UnitInterval] = None, detached: typing.Optional[subsequence.declarations.GateBeats] = None, beat: subsequence.declarations.GridBeats = 0.0) -> "PatternBuilder":

		"""
		Play a chord with a small time offset between each note (strum effect).

		Works exactly like ``chord()`` but staggers the notes instead of
		playing them simultaneously. The first note lands on ``beat`` (0 by default);
		subsequent notes are delayed by ``spacing`` beats each.

		Parameters:
			chord_obj: The chord to play (usually the ``chord`` parameter
				passed to your pattern function, or a name like
				``"Cmaj7"``) - or, exactly as ``arpeggio()`` takes it, a
				plain list of pitches to voice as written: MIDI note
				numbers, or drum names when the pattern has a
				``drum_note_map``.  A name is carried to the mirror
				fan-out so each device re-resolves it through its own
				map; one no destination maps at all is dropped (warned
				once), and an empty list rests.
			root: MIDI root note (e.g., 60 for Middle C).  Required for a
				chord, and not used for a plain pitch list - passing it
				with one raises, rather than looking as though it applied.
			velocity: MIDI velocity (default 90), or a ``(low, high)``
				tuple for a fresh random draw per strum note.
			sustain: If True, the notes last for the entire pattern duration.
				Mutually exclusive with ``legato`` and ``detached``.
			duration: Note duration in beats (default 1.0). Ignored when
				``legato`` or ``detached`` is set, since those recalculate
				durations.
			inversion: Specific chord inversion (ignored if voice leading is on).
			count: Number of notes to play (cycles tones if higher than
				the chord's natural size).
			spacing: Time in beats between each note onset (default 0.05).
				Onsets fall on whole pulses, 24 to a beat, so a spacing
				below about 0.04 puts some strings together.
			direction: ``"forward"`` staggers the pitches in the order they were
				given (ascending for a chord, whose tones arrive sorted) and
				``"reverse"`` staggers them backwards; ``"low_to_high"`` and
				``"high_to_low"`` sort by pitch first.  A guitarist's downstroke
				is ``"low_to_high"`` whatever order the notes were handed over in.
			beat: Beat offset for the first note (default 0.0); the stagger is added
				on top.  ``sustain``/``detached`` ring from the pattern length, not from
				``beat`` - set ``duration`` explicitly when placing positioned strums.
			legato: If given, the strum rings as one attack: every string
				lasts the same, so the last lets go at ``ratio`` of the gap
				from the first string to the next attack after the last,
				and the earlier strings sooner - the shape
				``detached`` gives.  Measured once the build is done, and
				nothing else in the pattern is resized.  Mutually exclusive
				with ``sustain`` and ``detached``.
			detached: If given, every strum note rings with a uniform
				duration of ``pattern.length - detached - (count - 1) * spacing``.
				The last note ends exactly ``detached`` beats before the
				next cycle; earlier notes end proportionally sooner, so
				releases are staggered in the same shape as the placements
				(the hand lifts the way it landed).  Polyphony-safe:
				guarantees nothing from this strum is still sounding when
				the next chord begins.  Mutually exclusive with ``sustain``
				and ``legato``.

		Example::

			# Gentle upward strum with legato
			p.strum(chord, root=52, velocity=85, spacing=0.06, legato=0.95)

			# Fast downward strum
			p.strum(chord, root=52, direction="reverse", spacing=0.03)

			# Five-voice strum with a 0.25-beat safety gap before the
			# next chord - won't exhaust polyphony on a 5-voice synth.
			p.strum(chord, root=48, count=5, spacing=0.1, detached=0.25)
		"""

		set_count = (1 if sustain else 0) + (1 if legato is not None else 0) + (1 if detached is not None else 0)
		if set_count > 1:
			raise ValueError("sustain=, legato=, and detached= are mutually exclusive - use one or the other")

		if beat != 0.0 and (sustain or detached is not None):
			self._warn_positioned_articulation("strum", beat)

		if spacing <= 0:
			raise ValueError("spacing must be positive")

		self._check_direction("strum", direction, _STRUM_DIRECTIONS)

		pitches = self._pitches_from("strum", chord_obj, root, inversion, count)

		if not pitches:
			return self	# an empty pool, or every named voice missing here — rest

		if direction in ("low_to_high", "high_to_low"):
			pitches = sorted(pitches, key=lambda entry: entry[0])

		if direction in ("reverse", "high_to_low"):
			pitches = list(reversed(pitches))

		if sustain:
			duration = float(self._pattern.length)
		elif detached is not None:
			duration = float(self._pattern.length) - detached - (len(pitches) - 1) * spacing
			if duration <= 0:
				raise ValueError(f"detached ({detached}) plus the strum stagger exceeds the pattern length ({self._pattern.length:g} beats) - reduce detached, spacing, or count")

		placed_before = self._note_ids() if legato is not None else set()

		for i, (pitch, origin, _) in enumerate(pitches):
			# The name where there is one, so note() carries it as a named hit does.
			self.note(pitch=pitch if origin is None else origin, beat=beat + i * spacing, velocity=velocity, duration=duration)

		if legato is not None:
			self._legato_own_notes(placed_before, legato)
		return self

	def progression (self, source: subsequence.progressions.ProgressionSource, harmonic_rhythm: subsequence.progressions.HarmonicRhythmSpec, key: typing.Optional[str] = None, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> subsequence.progressions.Progression:

		"""Realise a chord progression across the pattern, returning it to place yourself.

		Returns a freshly realised :class:`~subsequence.progressions.Progression` -
		an iterable of ``(chord, start, length)`` events laying a progression
		end-to-end across the pattern's length, each chord given a length drawn
		from *harmonic_rhythm* (the musical term for how often the chords
		change).  You loop over it and play each chord however you like -
		block, strummed, or arpeggiated::

			for chord, start, length in p.progression("phrygian_minor",
					harmonic_rhythm=between(WHOLE, 3 * WHOLE, step=WHOLE), seed=7):
				p.strum(chord, root=48, beat=start, duration=length - 0.25, spacing=0.04, count=4)

		This is the **part-level** progression seam: it re-realises a fresh
		value each rebuild (the breathing behaviour), runs entirely outside
		the global harmonic clock - so a part can inhabit its own harmonic
		world (polytonality) or move faster than the clock's span floor -
		and never advances engine state.

		For a one-call block-chord part with no loop, use ``composition.chords()``.

		Parameters:
			source: A built-in chord-graph style name (e.g. ``"phrygian_minor"``) to
				*generate* a progression; an explicit element list - ints where
				diatonic, name or roman strings (``["Cm7", 6, "bVII"]``), ``Chord``
				objects - cycled to fill the pattern; or a
				:class:`~subsequence.progressions.Progression` value (its spans
				cycled, decoration preserved).
			harmonic_rhythm: How long each chord lasts, in beats.  One of: a single
				number (static); a list of lengths (a shaped rhythm such as
				``[WHOLE, HALF, HALF]``, cycled per chord); or ``between(low, high,
				step=...)`` for a bounded, optionally-quantised random length.
			key: Key for styles and key-relative elements (degrees/romans);
				defaults to the composition's key.
			seed: If given, the progression is realised from a fresh ``Random(seed)``
				so it is identical on every cycle (a fixed phrase).  When omitted, the
				pattern's own RNG is used, so it can vary per cycle (still reproducible
				under a composition seed).
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Returns:
			A ``Progression`` you can iterate as ``(chord, start, length)`` tuples
			(or read via ``.events()`` / ``print()``).
		"""

		rng = self._rng_from(seed, rng)
		resolved_key = key if key is not None else self.key
		return subsequence.progressions.realize(
			source = source,
			harmonic_rhythm = harmonic_rhythm,
			key = resolved_key,
			length = float(self._pattern.length),
			rng = rng,
			scale = self.scale or "ionian",
		)

	def broken_chord (self, chord_obj: typing.Union[subsequence.chords.Chord, str], root: int, order: typing.List[int], spacing: subsequence.declarations.GridBeats = 0.25, velocity: subsequence.declarations.VelocityValue = subsequence.constants.velocity.DEFAULT_CHORD_VELOCITY, duration: typing.Optional[subsequence.declarations.GateBeats] = None, inversion: int = 0, beat: subsequence.declarations.GridBeats = 0.0, span: typing.Optional[subsequence.declarations.GridBeats] = None) -> "PatternBuilder":

		"""
		Play a chord as an arpeggio in a specific or random order.

		This generates the chord tones and maps them according to the provided
		``order`` list of indices, then delegates to ``arpeggio()``. It is ideal
		for broken chords or random chord-tone melodies.

		Because the order is a list of node indices, the number of generated tones
		is automatically set to ``max(order) + 1`` to ensure all indices are valid.
		Higher indices will cycle into the next octave.

		Parameters:
			chord_obj: The chord to play (usually from ``p.section.chord``), or a
				chord name like ``"Cmaj7"``.
			root: MIDI root note (e.g., 60 for Middle C).
			order: List of indices into the chord tones array, dictating playback order.
			spacing: Time between each note in beats (default 0.25 = 16th note).
			velocity: MIDI velocity for all notes (default 90 - broken_chord is a
				chord voice, so it sits in the softer chord velocity bucket like
				``chord()`` and ``strum()``), or a ``(low, high)`` tuple for a
				fresh random draw per note.
			duration: Note duration in beats. Defaults to ``spacing``.
			inversion: Specific chord inversion (ignored if voice leading is on).
			beat: Beat to start the broken chord at (default 0.0).
			span: How many beats to fill from ``beat`` (default: to the end of the
				pattern).  Like ``arpeggio()``, use it to place a broken chord over
				one chord of a progression.

		Example::

			# A 5-note broken chord using a predefined pattern
			p.broken_chord(chord, root=60, order=[4, 0, 2, 1, 3], spacing=0.25)

			# A fully random broken chord using the pattern's deterministic RNG
			order = list(range(5))
			p.rng.shuffle(order)
			p.broken_chord(chord, root=60, order=order)
		"""

		if not order:
			raise ValueError("order list cannot be empty")

		for idx in order:
			if not isinstance(idx, int) or idx < 0:
				raise ValueError("order must contain only non-negative integers")

		required_count = max(order) + 1
		tones = [midi for midi, _, _ in self._pitches_from("broken_chord", chord_obj, root, inversion, required_count)]
		pitches = [tones[i] for i in order]

		self.arpeggio(notes=pitches, spacing=spacing, velocity=velocity, duration=duration, direction="forward", beat=beat, span=span)
		return self

	def swing (self, percent: typing.Annotated[float, subsequence.declarations.Unit("percent"), subsequence.declarations.Step(1.0)] = 57.0, grid: subsequence.declarations.GridBeats = 0.25, strength: subsequence.declarations.UnitInterval = 1.0) -> "PatternBuilder":

		"""
		Apply swing feel to all notes in the pattern, in steps of a whole pulse (a 24th of a beat).

		A shortcut for ``p.groove(Groove.swing(percent, grid), strength)``. Swing is a
		groove where every other grid note is delayed - the simplest way to
		give a mechanical pattern a pushed, human feel.

		50% is perfectly straight (no swing). 57% is the Ableton default
		(a gentle shuffle). 67% is classic triplet swing.

		**A swung note moves by whole pulses**, 24 to a beat, so neighbouring
		percentages often sound the same.  On sixteenths (``grid=0.25``) a
		swung pair lasts 12 pulses: 50–54 play straight, 55–62 all sound as
		about 58%, 63–70 as 67% and 71–79 as 75%.  On eighths (``grid=0.5``)
		each pulse is about 4%: 53–56 sound as 54%, 57–60 as 58%, 61–64 as
		62.5%, 65–68 as 67% and 69–72 as 71%.  ``strength`` scales the delay
		before it is rounded, so it moves in the same whole pulses.

		Swing is counted from the start of the piece rather than the start of
		this pattern, so a three-sixteenth hat line and a one-bar kick given
		the same percentage swing together.

		Parameters:
			percent: Swing amount as a percentage (50-75 is the useful range).
				50 = straight, 57 = moderate shuffle, 67 ≈ triplet swing.
			grid: Grid size in beats (0.25 = 16th notes, 0.5 = 8th notes).
			strength: How much swing to apply (0.0-1.0). 0.0 = no effect,
				1.0 = full swing at the given percent. Useful for dialling
				back the feel without changing the swing percentage.

		Example::

			p.hit_steps("hh", range(16), velocity=80)
			p.swing(57)                # gentle 16th-note shuffle
			p.swing(57, strength=0.5)  # half-strength - subtler feel
		"""

		self.groove(subsequence.groove.Groove.swing(percent=percent, grid=grid), strength=strength)
		return self


	def groove (self, template: subsequence.groove.Groove, strength: float = 1.0) -> "PatternBuilder":

		"""
		Apply a groove template to all notes in the pattern.

		A groove is a repeating pattern of per-step timing offsets and
		optional velocity adjustments. It gives a pattern its characteristic
		rhythmic feel - swing, shuffle, MPC pocket, or any custom shape.

		Construct a groove with one of the factory methods:

		- ``Groove.swing(percent)`` - simple swing by percentage
		  (or use the ``p.swing()`` shortcut for common cases)
		- ``Groove.from_agr(path)`` - import timing from an Ableton .agr file
		- ``Groove(offsets=[...], grid=0.25, velocities=[...])`` - fully custom

		``p.groove()`` is a post-build transform - call it after all notes
		have been placed. It pairs well with ``p.randomize()`` for
		structured feel plus organic micro-variation.

		A groove's slots are counted from the start of the piece, not from the
		start of each pattern, so one ``Groove`` given to every part swings
		them all together whatever their lengths. A pattern shorter than the
		groove's cycle (``grid × len(offsets)``) therefore plays a different
		stretch of the groove each time round, which is how a long custom
		groove shapes a short pattern.

		Nothing plays before its own cycle begins, so a groove cannot pull a
		note earlier than the pattern's first pulse: in a groove that pulls
		notes early, a note on that first pulse stays where it is.

		The verbs that read the grid - ``thin()``, ``scale_velocities()`` and
		``ratchet(steps=)`` - still count each note as the step it was placed
		on, so they can come before the groove or after it.

		Parameters:
			template: A ``Groove`` instance defining the timing/velocity template.
			strength: How much of the groove to apply (0.0-1.0). 0.0 = no
				effect, 1.0 = full groove. Blends timing offsets and velocity
				deviation proportionally - equivalent to Ableton's
				TimingAmount and VelocityAmount dials.

		Example::

			groove = subsequence.Groove.swing(percent=57)

			@composition.pattern(channel=10, beats=4)
			def drums (p):
				p.hit_steps("kick", [0, 8], velocity=100)
				p.hit_steps("hh", range(16), velocity=80)
				p.groove(groove)               # full strength
				p.groove(groove, strength=0.5) # half-strength blend
		"""

		self._pattern.steps = subsequence.groove.apply_groove(
			self._pattern.steps, template, strength=strength,
			origin_pulse=self._pattern._cycle_start_pulse,
		)
		return self

	# These methods transform existing notes after they have been placed.
	# Call them at the end of your builder function, after all notes are
	# in position. They operate on self._pattern.steps (the pulse-position
	# dict) and can be chained in any order.

	def dropout (self, probability: subsequence.declarations.UnitInterval, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "PatternBuilder":

		"""
		Randomly remove notes from the pattern.

		This operates on all notes currently placed in the builder.

		Parameters:
			probability: The chance (0.0 to 1.0) of each pulse POSITION being
				removed - all notes sharing that position (a chord's voices,
				layered drums) live or die together.
			seed: Fix the dropout for this call (an int); omit to use the
				pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).
		"""

		rng = self._rng_from(seed, rng)

		positions_to_remove = []

		for position in list(self._pattern.steps.keys()):

			if rng.random() < probability:
				positions_to_remove.append(position)

		for position in positions_to_remove:
			del self._pattern.steps[position]
		return self

	def velocity_shape (self, low: int = subsequence.constants.velocity.VELOCITY_SHAPE_LOW, high: int = subsequence.constants.velocity.VELOCITY_SHAPE_HIGH) -> "PatternBuilder":


		"""
		Apply organic velocity variation to all notes in the pattern.

		Uses a van der Corput sequence to distribute velocities evenly
		across the specified range, which often sounds more 'human' than
		purely random velocity variation.

		Parameters:
			low: Minimum velocity (default 64).
			high: Maximum velocity (default 127).
		"""

		positions = sorted(self._pattern.steps.keys())

		if not positions:
			return self

		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(len(positions))

		for position, vdc_value in zip(positions, vdc_values):

			step = self._pattern.steps[position]

			for note in step.notes:
				note.velocity = int(low + (high - low) * vdc_value)
		return self

	def duck_map (
		self,
		steps: typing.Iterable[int],
		floor: float = 0.0,
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
	) -> typing.List[float]:

		"""
		Build a per-step velocity multiplier list for sidechain-style ducking.

		Returns a list of floats, one per grid step: ``floor`` at each trigger
		step in ``steps``, ``1.0`` everywhere else. Pass the result to
		``p.data`` for another pattern to read, then apply with
		``p.scale_velocities()``.

		Parameters:
			steps: Grid indices that trigger ducking (e.g. kick hit positions).
			floor: Multiplier written at trigger steps. ``0.0`` = full silence,
				``1.0`` = no effect. Values in between give partial ducking.
			grid: Grid resolution (defaults to ``p.grid``).

		Returns:
			``List[float]`` of length ``grid``.

		Example::

			# Full duck on kick hits
			p.data["kick_sc"] = p.duck_map(kick_steps)

			# Softer duck
			p.data["kick_sc"] = p.duck_map(kick_steps, floor=0.3)

			# Velocity-proportional: deeper duck for harder kicks
			p.data["kick_sc"] = p.duck_map(kick_steps, floor=1.0 - (velocity / 127))
		"""

		if grid is None:
			grid = self._default_grid

		trigger = set(steps)
		return [floor if s in trigger else 1.0 for s in range(grid)]

	def build_velocity_ramp (
		self,
		low: int,
		high: int,
		shape: subsequence.declarations.EasingCurve = "linear",
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
	) -> typing.List[int]:

		"""
		Build a per-step velocity list that ramps from *low* to *high*.

		A musician-friendly shortcut for the common pattern of generating
		a fixed-length velocity sweep using an easing curve. Returns
		``List[int]`` ready to pass directly to ``velocities=`` parameters.

		Parameters:
			low: Velocity at the first step (0–127).
			high: Velocity at the last step (0–127).
			shape: Easing curve name (see ``subsequence.easing``). Common
				values: ``"linear"``, ``"ease_in"``, ``"ease_out"``,
				``"ease_in_out"``. Defaults to ``"linear"``.
			grid: Number of steps (defaults to ``p.grid``).

		Returns:
			``List[int]`` of length ``grid``, values clamped to 0–127.

		Example::

			# Snare roll that swells into a downbeat
			p.sequence(
				steps=range(16),
				pitches="snare_1",
				durations=0.1,
				velocities=p.build_velocity_ramp(25, 100, "ease_in"),
			)

			# Fade-out ghost fill
			p.ghost_fill("snare_1", 1,
				velocity=p.build_velocity_ramp(80, 20, "ease_out"),
				bias="sixteenths", no_overlap=True)
		"""

		if grid is None:
			grid = self._default_grid

		return [
			max(0, min(127, int(v)))
			for v in subsequence.easing.ramp(grid, float(low), float(high), shape)
		]

	def scale_velocities (
		self,
		factors: typing.Sequence[float],
		grid: typing.Optional[subsequence.declarations.StepCount] = None,
	) -> "PatternBuilder":

		"""
		Scale note velocities by a per-step multiplier list.

		Each note's velocity is multiplied by the factor at the corresponding
		grid step index. A factor of ``1.0`` leaves the velocity unchanged;
		``0.0`` silences the note; ``0.5`` halves it.

		A note takes the factor of the step it was placed on, however far
		``swing()``, ``groove()`` or ``randomize()`` has since moved it, so a
		duck map lands on the same notes whether it comes before the feel or
		after it.

		Parameters:
			factors: Per-step multipliers, one float per grid step.
				Values outside ``[0.0, 1.0]`` are valid - result is clamped to
				``[0, 127]`` after scaling.
			grid: Grid resolution (defaults to ``p.grid``). Must match the
				length of ``factors``.

		Returns:
			``self`` for fluent chaining.

		Example::

			# Sidechain ducking: silence bass on kick steps, full volume elsewhere.
			kick_steps = {0, 4, 8, 12}
			p.data["kick_sc"] = [0.0 if s in kick_steps else 1.0 for s in range(p.grid)]

			# In the bass pattern:
			p.scale_velocities(p.data.get("kick_sc", [1.0] * p.grid))
		"""

		if grid is None:
			grid = self._default_grid

		if grid <= 0:
			return self

		step_duration = self._pattern.length / grid
		pulses_per_step = step_duration * subsequence.constants.MIDI_QUARTER_NOTE

		for pulse, step in self._pattern.steps.items():

			for note in step.notes:

				# By the step the note was placed on, however far swing, a
				# groove or randomize() has moved it: read where it plays, a
				# sixteenth swung half a step late took the next step's factor
				# (#3447).  A note placed in the last half-step rounds up to
				# idx == grid, which is really the wrap back to step 0 of the
				# next cycle (patterns are cyclic), so it takes factors[0].
				idx = int(round(self._pattern._placed_pulse(pulse, note) / pulses_per_step)) % grid

				if 0 <= idx < len(factors):
					note.velocity = max(0, min(127, int(note.velocity * factors[idx])))

		return self

	def randomize (
		self,
		timing: typing.Annotated[subsequence.declarations.Beats, subsequence.declarations.Step(0.01)] = 0.03,
		velocity: subsequence.declarations.UnitInterval = 0.0,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None
	) -> "PatternBuilder":

		"""
		Add random variations to note timing and velocity.

		Introduces small imperfections - the micro-variations that distinguish
		a played performance from a perfectly quantised sequence.

		Called with no arguments, only timing variation is applied
		(velocity defaults to 0.0 - no change). Pass a velocity value
		to also randomise dynamics:

		    # Timing only (default)
		    p.randomize()

		    # Both axes
		    p.randomize(timing=0.04, velocity=0.08)

		    # Stronger feel
		    p.randomize(timing=0.08, velocity=0.15)

		Resolution note: the sequencer runs at 24 PPQN. At 120 BPM, one
		pulse ≈ 20ms. Timing shifts smaller than roughly 0.04 beats may
		have no audible effect because they round to zero pulses.
		Recommended range: timing=0.02–0.08, velocity=0.05–0.15.

		When the composition has a seed set, ``p.rng`` is deterministic,
		so ``p.randomize()`` produces the same result on every run.

		Parameters:
			timing: Maximum timing offset in beats (e.g. 0.05 = ±1.2
				pulses at 24 PPQN). Notes shift by a random amount
				within ``[-timing, +timing]`` beats. Clamped to
				pulse 0 at the lower bound.
			velocity: Maximum velocity scale factor (0.0 to 1.0). Each
				note's velocity is multiplied by a random value in
				``[1 - velocity, 1 + velocity]``, clamped to 1–127.
			seed: Fix the variations for this call (an int); omit to use the
				pattern's RNG (seeded when the composition has a seed).
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).
		"""

		rng = self._rng_from(seed, rng)

		max_timing_pulses = timing * subsequence.constants.MIDI_QUARTER_NOTE
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for pulse, step in self._pattern.steps.items():

			if timing != 0.0:
				offset = rng.uniform(-max_timing_pulses, max_timing_pulses)
				new_pulse = max(0, int(round(pulse + offset)))
			else:
				new_pulse = pulse

			if new_pulse not in new_steps:
				new_steps[new_pulse] = subsequence.pattern.Step()

			# Process notes: randomise velocity once per note, then place in new bucket.
			for note in step.notes:
				if velocity != 0.0:
					scale = rng.uniform(1.0 - velocity, 1.0 + velocity)
					note.velocity = max(1, min(127, int(round(note.velocity * scale))))

				# Recorded, so the grid-reading transforms still count the note
				# as the step it was placed on (#3447).
				note.nudge += new_pulse - pulse

				new_steps[new_pulse].notes.append(note)

		self._pattern.steps = new_steps
		return self

	def legato (self, ratio: subsequence.declarations.UnitInterval = 1.0) -> "PatternBuilder":

		"""
		Adjust note durations to fill the gap until the next note.

		Parameters:
			ratio: How much of the gap to fill (0.0 to 1.0).
				1.0 is full legato, < 1.0 is staccato.
		"""

		if not self._pattern.steps:
			return self

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)

		for i, position in enumerate(sorted_positions):

			# Calculate gap to next note
			if i < len(sorted_positions) - 1:
				gap = sorted_positions[i + 1] - position
			else:
				# Wrap around: gap is distance to end + distance to first note
				gap = (total_pulses - position) + sorted_positions[0]

			# Apply ratio and enforce minimum duration
			new_duration = max(1, int(gap * ratio))

			step = self._pattern.steps[position]
			for note in step.notes:
				note.duration = new_duration
		return self

	@subsequence.declarations.bounded
	def duration (self, beats: typing.Annotated[float, subsequence.declarations.Span(low=0.01), subsequence.declarations.Unit("beats"), subsequence.declarations.Step(0.05)]) -> "PatternBuilder":

		"""
		Set every note's duration to a fixed length in beats.

		This overrides any existing note durations, acting as a global
		'gate time' relative to the beat (1.0 = a quarter note).  Short
		values clip notes tight; long values let them ring.  For a
		guaranteed gap before each next onset regardless of note spacing,
		use :meth:`detached`; for a classic staccato articulation, either
		a short fixed value (``p.duration(0.1)``) or ``p.detached()`` works.

		Parameters:
			beats: Fixed note duration in beats (relative to a quarter note).
				0.5 = eighth-note length, 0.25 = sixteenth-note length.  Must be positive.
		"""

		if beats <= 0:
			raise ValueError("Note duration (beats) must be positive")

		duration_pulses = subsequence.constants.pulses.beats_to_pulses(beats)
		duration_pulses = max(1, duration_pulses)

		for step in self._pattern.steps.values():
			for note in step.notes:
				note.duration = duration_pulses
		return self

	def detached (self, beats: subsequence.declarations.GateBeats = 0.05) -> "PatternBuilder":

		"""
		Shorten note durations so a guaranteed silence precedes the next onset.

		The complement of :meth:`legato`.  For every placed note, the duration
		is shrunk so that at least ``beats`` beats of silence remain before
		the next note begins (wrapping around to the first note for the last
		one).  Use this when you want a clean detached articulation, or as a
		polyphony-safety margin between chord transitions on a monophonic or
		voice-limited synth.

		Parameters:
			beats: Minimum gap in beats before the next onset (default 0.05 -
				roughly 25 ms at 120 BPM).  Must be positive.

		Example::

			# Bassline on a mono synth: each 16th note ends 0.05 beats
			# before the next, so the synth never retriggers mid-note.
			p.arpeggio(chord.tones(36, count=4), spacing=0.25).detached()

			# Explicit larger gap for a longer release tail.
			p.melody(state, spacing=0.25).detached(0.1)
		"""

		if beats <= 0:
			raise ValueError("detached beats must be positive")

		if not self._pattern.steps:
			return self

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses    = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
		detached_pulses = subsequence.constants.pulses.beats_to_pulses(beats)

		for i, position in enumerate(sorted_positions):

			# Calculate gap to next note (wrap-around for the last one)
			if i < len(sorted_positions) - 1:
				gap = sorted_positions[i + 1] - position
			else:
				gap = (total_pulses - position) + sorted_positions[0]

			new_duration = max(1, gap - detached_pulses)

			for note in self._pattern.steps[position].notes:
				note.duration = new_duration
		return self

	def snap_to_scale (self, key: subsequence.declarations.KeyName, mode: str = "ionian", strength: subsequence.declarations.UnitInterval = 1.0, seed: typing.Optional[int] = None, rng: typing.Optional[random.Random] = None) -> "PatternBuilder":

		"""
		Snap all notes in the pattern to the nearest pitch in a scale.

		Useful after generative or sensor-driven pitch work (random walks,
		mapping data values to note numbers, etc.) to ensure every note lands
		on a musically valid scale degree.  The snap is applied in
		place; notes already on a scale degree are left unchanged.

		When a note falls equidistant between two scale tones, the upward
		direction is preferred.

		Parameters:
			key: Root note name (e.g. ``"C"``, ``"F#"``, ``"Bb"``).
			mode: Scale mode.  Any mode :func:`scale_notes` accepts, including one added
			      with :func:`register_scale`: ``"ionian"`` (default), ``"dorian"``,
			      ``"minor"``, ``"harmonic_minor"``, etc.
			strength: Probability that each note is snapped (0.0–1.0).
			      At 1.0 (default), every note snaps to the scale.
			      At 0.0, no notes are affected.
			      Values in between create melodies that are mostly in key
			      with occasional chromatic passing tones.  Uses the
			      pattern's seeded RNG for reproducibility.
			seed: Fix the partial-strength snapping for this call (an int);
			      omit to use the pattern's RNG.
			rng: Advanced determinism form - a ``random.Random`` (wins over ``seed=``).

		Example:
			```python
			@composition.pattern(channel=1, beats=4)
			def melody (p):
			    for beat in range(16):
			        pitch = 60 + random.randint(-5, 5)
			        p.note(pitch, beat=beat * 0.25)
			    p.snap_to_scale("G", "dorian", strength=0.8)
			```
		"""

		rng = self._rng_from(seed, rng)

		key_pc = subsequence.chords.key_name_to_pc(key)
		scale_pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)

		for step in self._pattern.steps.values():
			for note in step.notes:
				if strength >= 1.0 or rng.random() < strength:
					note.pitch = subsequence.intervals.quantize_pitch(note.pitch, scale_pcs)
		return self

	def apply_tuning (
		self,
		tuning: "subsequence.tuning.Tuning",
		bend_range: float = 2.0,
		channels: typing.Optional[typing.List[int]] = None,
		reference_note: int = 60,
	) -> "PatternBuilder":

		"""Apply a microtonal tuning to this pattern via pitch bend injection.

		For each note in the pattern, the nearest 12-TET MIDI pitch is
		computed and a pitchwheel ``CcEvent`` is injected at the note's onset
		to shift the synthesiser to the exact tuned frequency.  Other pitch
		bends (from ``p.portamento()``, ``p.slide()``, etc.) are shifted
		additively so they still work correctly within the tuned pitch space.

		The tuning is applied when the build finishes, after the notes have
		reached their final places and any glides have been laid, so it can be
		called anywhere in the builder: before or after ``p.groove()``,
		``p.slide()`` or anything else.

		For polyphonic patterns, supply a ``channels`` pool.  Notes will be
		spread across those channels so each can carry an independent pitch
		bend.  For monophonic patterns, leave ``channels=None``.

		The synthesiser's pitch-bend range must match ``bend_range``.  Most
		synths default to ±2 semitones.  For tunings that deviate more than
		one semitone from 12-TET, increase ``bend_range`` (e.g., 12 or 24)
		and configure the synth to match.

		Parameters:
			tuning: The :class:`~subsequence.tuning.Tuning` to apply.
			bend_range: Synth pitch-bend range in semitones (default ±2).
			channels: Channel pool for polyphonic rotation, numbered like
			    every other channel: 1-16, or 0-15 when the composition was
			    made with ``zero_indexed_channels=True``.  The part plays
			    through the pool, its notes rotating when they overlap and
			    otherwise sitting on the pool's first channel.  ``None`` keeps
			    all notes on the pattern's own channel.
			reference_note: MIDI note number that maps to scale degree 0.
			    Default 60 (middle C).

		Example:
			```python
			from subsequence import Tuning

			meantone = Tuning.from_scl("meanquar.scl")

			@composition.pattern(channel=1, beats=4)
			def melody (p):
			    p.seq("x x x x", pitch=60)
			    p.apply_tuning(meantone, bend_range=2.0)
			```
		"""
		import subsequence.tuning

		# Read the pool now, so a channel it cannot be is refused on this line.
		pool = None if channels is None else subsequence.tuning.resolve_channel_pool(channels, zero_indexed=self._zero_indexed_channels)

		self._defer(self._pending_tunings, functools.partial(
			subsequence.tuning.apply_tuning_to_pattern,
			self._pattern,
			tuning,
			bend_range=bend_range,
			channels=pool,
			reference_note=reference_note,
		))
		self._tuning_applied = True
		return self

	def _finish_build (self) -> None:

		"""Lay what depends on where the notes finally sit: glides, then tunings.

		The engine calls this once the builder function has returned, so a
		glide ends on its target's actual onset and a tuned note's bend lands
		with the note, whatever transforms ran after them (#2792).  Glides go
		first because a tuning shifts every pitch bend already present.
		"""

		# Legato first: it sets the lengths a glide may then extend.
		for size in self._pending_legatos:
			size()

		for lay in self._pending_glides:
			lay()

		for tune in self._pending_tunings:
			tune()

		self._keep_parameter_selections_honest()

		self._abandon_build()

	def _keep_parameter_selections_honest (self) -> None:

		"""Re-select an NRPN/RPN parameter wherever something else has taken it.

		A ramp selects its parameter once and then sends only Data Entry, which
		is correct MIDI and cheap - a synth holds the last parameter selected on
		a channel.  Nothing defended it, though, so any other NRPN or RPN write
		inside the ramp's window silently redirected the rest of it.  Measured
		before this (#3070): with two ramps over one window, the first reached
		its own parameter on **1 of 5** steps; with a one-shot ``p.nrpn()``
		inside the window, whose default ``null_reset`` deselects, **three of
		five** steps went to the NULL parameter and did nothing at all.

		This walks the events in the order the engine will send them and
		re-selects only where the selection has drifted, so a ramp on its own
		still emits exactly what it always did.

		A plain ``p.cc(6, …)`` carries no parameter and is left alone: that is
		the user addressing whatever they selected themselves, which the
		docstrings have always said is theirs to keep track of.  Nor can this
		see another *pattern* writing to the same channel.
		"""

		events = self._pattern.cc_events

		if not any(event.parameter is not None for event in events):
			return

		selects = {
			pymididefs.cc.NRPN_MSB: ("nrpn", "msb"),
			pymididefs.cc.NRPN_LSB: ("nrpn", "lsb"),
			pymididefs.cc.RPN_MSB: ("rpn", "msb"),
			pymididefs.cc.RPN_LSB: ("rpn", "lsb"),
		}

		# The engine sends same-pulse events in the order they were appended
		# (_push_event stamps a rising sequence), so the index is the tie-break.
		order = sorted(range(len(events)), key = lambda index: (events[index].pulse, index))

		half: typing.Dict[str, typing.Dict[str, int]] = {"nrpn": {}, "rpn": {}}
		selected: typing.Optional[typing.Tuple[str, int]] = None

		repaired: typing.List[subsequence.pattern.CcEvent] = []

		for index in order:

			event = events[index]

			if event.message_type == 'control_change' and event.control in selects:

				kind, part = selects[event.control]
				half[kind][part] = event.value

				if "msb" in half[kind] and "lsb" in half[kind]:
					selected = (kind, (half[kind]["msb"] << 7) | half[kind]["lsb"])

				repaired.append(event)
				continue

			if (
				event.message_type == 'control_change'
				and event.control == pymididefs.cc.DATA_ENTRY_MSB
				and event.parameter is not None
				and event.parameter != selected
			):
				kind, number = event.parameter
				msb_cc = pymididefs.cc.NRPN_MSB if kind == "nrpn" else pymididefs.cc.RPN_MSB
				lsb_cc = pymididefs.cc.NRPN_LSB if kind == "nrpn" else pymididefs.cc.RPN_LSB
				param_msb, param_lsb = pymididefs.cc.pack_14bit(number)

				for control, value in ((msb_cc, param_msb), (lsb_cc, param_lsb)):
					repaired.append(subsequence.pattern.CcEvent(
						pulse = event.pulse,
						message_type = 'control_change',
						control = control,
						value = value,
						channel = event.channel,
						device = event.device,
						priority = event.priority,
					))

				half[kind] = {"msb": param_msb, "lsb": param_lsb}
				selected = event.parameter

			repaired.append(event)

		self._pattern.cc_events[:] = repaired

	def _note_ids (self) -> typing.Set[int]:

		"""The identity of every note placed so far, to tell a call's own notes from the rest."""

		return {id(note) for step in self._pattern.steps.values() for note in step.notes}

	def _legato_own_notes (self, placed_before: typing.Set[int], ratio: float) -> None:

		"""Mark the notes placed since *placed_before* as one attack, and size them when the build is done (#3463)."""

		self._legato_groups += 1
		group = self._legato_groups

		for step in self._pattern.steps.values():
			for note in step.notes:
				if id(note) not in placed_before:
					note.legato_group = group

		self._defer(self._pending_legatos, functools.partial(self._lay_legato, group, ratio))

	def _lay_legato (self, group: int, ratio: float) -> None:

		"""Ring one chord's or strum's notes for *ratio* of the gap to the next attack outside it.

		A strum is one attack: the gap runs from its first string to the next
		attack after its last string, wrapping round the cycle, and every
		string rings the same length, so the last lets go at
		*ratio* of the gap and the earlier ones sooner, as ``detached=`` shapes
		them.  Measured once the build is done, so a chord placed later still
		cuts one placed earlier, and each call keeps its own ratio.  Applied
		pattern-wide at the call, every string rang until the next string and
		a strum's lower strings lasted one pulse (#3463).
		"""

		own = [(position, note) for position, step in self._pattern.steps.items() for note in step.notes if note.legato_group == group]

		if not own:
			return

		attack = min(position for position, _ in own)
		last = max(position for position, _ in own)
		onsets = sorted(self._pattern.steps)
		later = [position for position in onsets if position > last]

		# Round the cycle, the next attack is the next cycle's first, which may
		# be this call's own: it plays again there.
		following = later[0] if later else onsets[0] + subsequence.constants.pulses.beats_to_pulses(self._pattern.length)

		ring = max(1, int((following - attack) * ratio) - (last - attack))

		for _, note in own:
			note.duration = ring

	def _will_need_finishing (self) -> None:

		"""Register this build so :meth:`_finish_build` runs, deferring nothing.

		For closing work that reads what the build laid rather than adding to
		it - the NRPN/RPN re-select pass (#3070).  :meth:`_defer` does the same
		registration for work that *does* have something to lay later.
		"""

		if self._finish_build not in self._pattern._unfinished_builds:
			self._pattern._unfinished_builds.append(self._finish_build)

	def _defer (self, pending: typing.List[typing.Any], lay: typing.Callable[[], object]) -> None:

		"""Keep *lay* for the end of the build, and make sure the build will be finished.

		The engine finishes its own builders.  A builder made by hand (the
		Direct Pattern API) is not, so the first deferral registers the build
		on its pattern, and the sequencer finishes it when it schedules the
		pattern (#2959).
		"""

		self._will_need_finishing()

		pending.append(lay)

	def _abandon_build (self) -> None:

		"""Forget what this build deferred: after laying it, or after the builder raised and its pattern was emptied."""

		self._pending_legatos.clear()
		self._pending_glides.clear()
		self._pending_tunings.clear()

		if self._finish_build in self._pattern._unfinished_builds:
			self._pattern._unfinished_builds.remove(self._finish_build)

	def reverse (self) -> "PatternBuilder":

		"""
		Flip the pattern backwards in time (retrograde).
		"""

		total_pulses = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			# Reflect around the bar so onsets stay on the grid and the downbeat
			# is fixed — a true retrograde reverses the inter-onset intervals
			# (e.g. [0, 24] → [0, 72] in a 96-pulse bar, not the off-grid
			# [71, 95] the old (total-1)-position produced).
			new_position = (total_pulses - position) % total_pulses

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			# The step a note was placed on reflects with it, so a note the
			# feel moved late now sits that far early of its step (#3447).
			new_steps[new_position].notes.extend(
				dataclasses.replace(note, nudge = -note.nudge) if note.nudge else note
				for note in step.notes
			)

		self._pattern.steps = new_steps
		return self

	@subsequence.declarations.bounded
	def stretch (self, factor: typing.Annotated[float, subsequence.declarations.Span(low=0.01)]) -> "PatternBuilder":

		"""
		Stretch the pattern in time, scaling note positions and durations.

		``stretch(2.0)`` makes everything twice as long (half speed) - what
		theorists call *augmentation*; ``stretch(0.5)`` squeezes the pattern
		into half the time (double speed) - *diminution*.  Any positive
		factor works: ``stretch(2/3)`` compresses a dotted feel into
		straight time, for example.

		Notes whose start lands past the end of the pattern are dropped,
		and compression leaves the freed space empty - the pattern is not
		tiled to fill it.  Durations scale without clipping, so a stretched
		note may ring past the pattern's end exactly like a legato note,
		and ``stretch(1.0)`` is a true no-op.  Positions and durations
		truncate to the pulse grid (matching ``note()``'s beat-to-pulse
		truncation).

		Parameters:
			factor: Time multiplier.  Greater than 1.0 slows the pattern
				down, less than 1.0 speeds it up.  Must be positive.
		"""

		if factor <= 0:
			raise ValueError("Stretch factor must be positive")

		total_pulses = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = int(position * factor)

			if new_position >= total_pulses:
				continue

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			new_steps[new_position].notes.extend(
				dataclasses.replace(
					note,
					duration = max(1, int(note.duration * factor)),
					# The pulse it was placed on stretches with it, so the
					# feel's nudge scales too (#3447).
					nudge = new_position - int((position - note.nudge) * factor),
				)
				for note in step.notes
			)

		self._pattern.steps = new_steps
		return self

	def rotate (self, steps: subsequence.declarations.StepCount, grid: typing.Optional[subsequence.declarations.StepCount] = None) -> "PatternBuilder":

		"""
		Rotate the pattern by a number of grid steps, wrapping around.

		Notes pushed past the end of the pattern re-enter at the start
		(and vice versa for negative values) - the step-sequencer rotation
		familiar from Euclidean rhythm tools.

		Parameters:
			steps: Positive values rotate later in time, negative values earlier.
			grid: The grid resolution. Defaults to the pattern's
				``default_grid`` (derived from the decorator's ``beats``/``steps``
				and ``step_duration``).
		"""

		if grid is None:
			grid = self._default_grid

		if grid <= 0:
			return self

		total_pulses = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
		pulses_per_step = total_pulses / grid
		shift_pulses = int(steps * pulses_per_step)

		old_steps = self._pattern.steps
		new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

		for position, step in old_steps.items():
			new_position = (position + shift_pulses) % total_pulses

			if new_position not in new_steps:
				new_steps[new_position] = subsequence.pattern.Step()

			# Each note's nudge stands as it is: the step it was placed on
			# rotates by the same amount (#3447).
			new_steps[new_position].notes.extend(step.notes)

		self._pattern.steps = new_steps
		return self

	def transpose (self, semitones: typing.Annotated[int, subsequence.declarations.Unit("semitones")], within: typing.Optional[subsequence.declarations.PitchRange] = None) -> "PatternBuilder":

		"""
		Shift all note pitches up or down.

		Parameters:
			semitones: Positive for up, negative for down.
			within: ``(low, high)`` - notes moved outside this range are
				**removed** rather than pinned to its edge.  Omit it and
				pitches clamp to 0-127 as they always have.

		An instrument's reach is usually narrower than MIDI's.  A Minitaur
		sounds notes 0-72, and a note transposed past that is silent on the
		instrument - so clamping it to 72 sounds a note nobody asked for,
		piling voices onto the top note (#2464).  Dropping is the honest
		answer, and a position left with no notes goes with them.

		Example:
			```python
			# Move the part up an octave, losing whatever the synth cannot reach
			p.transpose(12, within=(0, 72))
			```
		"""

		if within is not None:

			low, high = within

			if low > high:
				raise ValueError(f"transpose(within=) needs (low, high) - got ({low}, {high}), which is empty")

		emptied: typing.List[int] = []

		for pulse, step in list(self._pattern.steps.items()):

			kept = []

			for note in step.notes:

				moved = note.pitch + semitones

				if within is None:
					note.pitch = max(0, min(127, moved))
					kept.append(note)
				elif low <= moved <= high:
					note.pitch = moved
					kept.append(note)
				# else: dropped, along with the position if it empties.

			if kept:
				step.notes = kept
			else:
				emptied.append(pulse)

		for pulse in emptied:
			del self._pattern.steps[pulse]
		return self

	def invert (self, pivot: int = 60) -> "PatternBuilder":

		"""
		Invert all pitches around a pivot note.
		"""

		for step in self._pattern.steps.values():

			for note in step.notes:
				note.pitch = max(0, min(127, pivot + (pivot - note.pitch)))
		return self

	def every (self, n: int, fn: typing.Callable[["PatternBuilder"], None]) -> "PatternBuilder":

		"""
		Apply a transformation every Nth cycle.

		A *cycle* is one pass of this pattern, which is the same thing as a bar
		only when the pattern is one bar long: a two-bar pattern calling
		``every(4, ...)`` fires every eight bars.  To count bars, use
		:meth:`bar_cycle`.

		Parameters:
			n: How many cycles between applications (e.g. 4 = every 4th cycle).
			fn: A function (often a lambda) that receives the builder and
				calls further methods.

		Example:
			```python
			# Reverse every 4th cycle
			p.every(4, lambda p: p.reverse())
			```
		"""

		if n < 1:
			raise ValueError(f"every() cycle length must be at least 1 cycle - got {n} (every(1, ...) applies the change every cycle)")

		if self.cycle % n == 0:
			fn(self)
		return self

	def bar_cycle (self, length: int) -> BarCycle:

		"""Return the current bar's position within a repeating cycle of bars.

		A thin wrapper around ``p.bar % length`` that replaces opaque modulo
		arithmetic with readable, musician-friendly properties.

		Parameters:
			length: The cycle length in bars (e.g., 4, 8, 16).

		Returns:
			A :class:`BarCycle` with ``.bar``, ``.first``, ``.last``,
			and ``.progress`` properties.

		Example:
			```python
			# Every 4 bars (replaces: if p.bar % 4 == 0)
			if p.bar_cycle(4).first:
			    p.hit_steps("snare_1", [0, 8], velocity=110)

			# Last bar of every 16-bar cycle (replaces: if p.bar % 16 == 15)
			if p.bar_cycle(16).last:
			    p.euclidean("hi_hat_open", 3)

			# Build intensity over an 8-bar arc
			intensity = p.bar_cycle(8).progress   # 0.0 → 0.875
			p.velocity_shape(low=int(40 + 40 * intensity), high=100)
			```
		"""

		if length < 1:
			raise ValueError(f"bar_cycle() cycle length must be at least 1 bar - got {length}")

		return BarCycle(bar=self.bar % length, length=length)
