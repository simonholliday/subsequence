"""Progressions — chord sequences laid out in time, as a governing value.

The one progression type: a frozen tuple of :class:`ChordSpan` — replacing the
old engine ``Progression`` (the ``freeze()`` capture) and ``ChordTimeline``
(the realised iterable) with a single value that is constructible, queryable,
transformable, and bindable to the harmonic clock.

Construction (the standard form — lists, parsed per element):

	subsequence.progression([1, 6, 3, 7])                    # diatonic degrees
	subsequence.progression([1, 6, 3, "bVII7"])              # romans where chromatic
	subsequence.progression(["Am", "F", "C", "G"])           # chord names
	subsequence.progression([("Am", 4), ("F", 2)])           # per-chord beats
	subsequence.progression(style="aeolian_minor", key="A", bars=8, seed=3)

Key-relative content (ints and romans) stays relative inside the value and
resolves at query time — change the key once, everything follows.  Spice
transforms (``extend``, ``inversions``, ``spread``, ``over``, ``borrow``)
decorate the spans, never the chords: the engine's currency stays the bare
``(root_pc, quality)`` triad, and decoration travels with the span to the
voicing layer.
"""

import dataclasses
import random
import re
import typing
import warnings

import subsequence.chords
import subsequence.harmonic_rhythm
import subsequence.harmonic_state
import subsequence.intervals
import subsequence.sequence_utils
import subsequence.voicings


# A progression source is either a built-in chord-graph style name (generated)
# or an explicit, ordered list of elements — ints, chord names, romans, Chord
# objects, or (element, beats) tuples.
ProgressionSource = typing.Union[str, "Progression", typing.Sequence[typing.Any]]

# A harmonic-rhythm spec is a single length (static), a list of lengths (a shaped
# rhythm, cycled per chord), or a between(...) range (bounded, optionally quantised).
HarmonicRhythmSpec = typing.Union[int, float, typing.List[float], subsequence.harmonic_rhythm.HarmonicRhythm]

# Voicing density: a fixed number of voices, or a (low, high) random range per chord.
VoicingSpec = typing.Union[int, typing.Tuple[int, int]]

# One bar per chord by default.  The value is context-free, so "a bar" is the
# common-time default; pass beats= for anything else.
DEFAULT_SPAN_BEATS: float = 4.0

# Genre preset table — the progression("name") syntax is reserved now; the
# data ships in the presets stage.
_PRESETS: typing.Dict[str, typing.List[typing.Any]] = {}


class ChordEvent (typing.NamedTuple):

	"""One chord on a realised timeline: which chord, when it starts, and how long
	it lasts (in beats from the start of the part).

	A ``NamedTuple``, so it unpacks positionally as ``(chord, start, length)`` — the
	idiom for looping a progression — while also offering ``.chord`` / ``.start`` /
	``.length`` attribute access.
	"""

	chord: typing.Any
	start: float
	length: float


# ---------------------------------------------------------------------------
# Leaf values: PitchSet and RomanChord
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PitchSet:

	"""A nameless sonority — a frozen set of absolute MIDI pitches.

	The escape hatch for chords with no root or quality: clusters, spectral
	stacks, found objects.  It duck-types ``.tones()`` so every placement verb
	and the injected ``chord`` accept it unchanged.  By design it is excluded
	from generation and diatonic spice (there is nothing to transpose
	diatonically), and a progression containing one loops on exhaustion
	rather than falling through to live graph stepping.

	Pitches are absolute: ``tones()`` ignores its ``root`` argument — you
	chose the register when you chose the pitches.
	"""

	pitches: typing.Tuple[int, ...]

	def __init__ (self, pitches: typing.Iterable[int]) -> None:

		"""Normalise any iterable of MIDI pitches into a sorted frozen tuple."""

		values = tuple(sorted(int(p) for p in pitches))

		if not values:
			raise ValueError("PitchSet needs at least one pitch")

		object.__setattr__(self, "pitches", values)

	def tones (self, root: int = 60, inversion: int = 0, count: typing.Optional[int] = None) -> typing.List[int]:

		"""Return the pitches (absolute — *root* is ignored by design).

		``inversion`` rotates pitches up an octave; ``count`` cycles the set
		into higher octaves, matching the ``Chord.tones`` contract.
		"""

		pitches = list(self.pitches)

		if inversion != 0:
			for _ in range(inversion % len(pitches)):
				pitches.append(pitches.pop(0) + 12)

		if count is not None:
			n = len(pitches)
			return [pitches[i % n] + 12 * (i // n) for i in range(count)]

		return pitches

	def intervals (self) -> typing.List[int]:

		"""Semitone offsets from the lowest pitch (the ``Chord`` protocol)."""

		return [p - self.pitches[0] for p in self.pitches]

	def name (self) -> str:

		"""A readable label for describe() output."""

		return "PitchSet(" + ", ".join(str(p) for p in self.pitches) + ")"


@dataclasses.dataclass(frozen=True)
class RomanChord:

	"""A key-relative chord — a scale degree with optional explicit quality.

	Internal: users only ever meet it as an int or roman string element inside
	a progression list.  It stays relative inside the value and resolves to a
	concrete :class:`~subsequence.chords.Chord` at query time against a key
	and scale.

	Attributes:
		degree: 1-based scale degree.
		accidental: -1 for a ``b`` prefix, +1 for ``#``.  An accidental-
			prefixed degree reads against the **major** scale, the universal
			roman convention — ``bVII`` is always the whole step below the
			tonic (Bb in C major, G in A minor); unprefixed degrees read the
			current scale (``VII`` in A minor is already G).
		quality: Explicit quality name, or ``None`` to infer diatonically
			from the key and scale (the bare-int path).
		of: Secondary-function target degree (``V/x`` — one level only).
			The numeral resolves against the major scale on the target's
			root, the common-practice reading.
		borrowed: When True, the degree resolves against the parallel scale
			(modal interchange) — set by :meth:`Progression.borrow`.
		source_text: The element as written, for unbound ``describe()``.
		major_relative: When True, the degree always reads the major scale
			(with the accidental applied), whatever scale ``resolve()`` is
			given — the scale-proof spelling :meth:`Progression.generate`
			emits, where quality is always explicit and the resolve scale
			must not re-interpret the root.
	"""

	degree: int
	accidental: int = 0
	quality: typing.Optional[str] = None
	of: typing.Optional[int] = None
	borrowed: bool = False
	source_text: str = ""
	major_relative: bool = False

	def __post_init__ (self) -> None:

		"""Validate the degree (1-based, like everything a musician counts)."""

		if self.degree < 1:
			raise ValueError(f"scale degree must be 1 or higher, got {self.degree}")

	def label (self) -> str:

		"""The element as written (for unbound describe() output)."""

		return self.source_text or str(self.degree)

	def resolve (self, key_pc: int, scale: str = "ionian") -> subsequence.chords.Chord:

		"""Resolve to a concrete chord against a key and scale.

		Raises:
			ValueError: If the scale is unknown, the degree exceeds the
				scale, or quality inference is needed but the scale has no
				chord qualities registered.
		"""

		mode = "minor" if self.borrowed and scale != "minor" else ("ionian" if self.borrowed else scale)

		if mode not in subsequence.intervals.SCALE_MODE_MAP:
			available = ", ".join(sorted(subsequence.intervals.SCALE_MODE_MAP.keys()))
			raise ValueError(f"Unknown scale: {mode!r}. Available: {available}")

		if self.of is not None:
			# Secondary function: resolve the target degree's root, then read
			# this numeral against the major scale on that root.
			target = RomanChord(degree=self.of)
			target_chord = target.resolve(key_pc, scale)
			return dataclasses.replace(self, of=None).resolve(target_chord.root_pc, "ionian")

		pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)

		if self.degree > len(pcs):
			raise ValueError(
				f"scale degree {self.degree} is out of range for {mode!r} "
				f"({len(pcs)} degrees)"
			)

		if self.accidental != 0 or self.major_relative:
			# Accidental-prefixed degrees read against the major scale — the
			# universal roman convention (bVII is the whole step below tonic
			# in every key, major or minor).  Generated spans set
			# major_relative so their spelling is scale-proof.
			major_pcs = subsequence.intervals.scale_pitch_classes(key_pc, "ionian")
			root_pc = (major_pcs[(self.degree - 1) % len(major_pcs)] + self.accidental) % 12
		else:
			root_pc = pcs[self.degree - 1] % 12

		if self.quality is not None:
			return subsequence.chords.Chord(root_pc=root_pc, quality=self.quality)

		_, qualities = subsequence.intervals.SCALE_MODE_MAP[mode]

		if qualities is None:
			raise ValueError(
				f"Scale {mode!r} has no chord qualities defined, so degree "
				f"{self.degree} cannot be inferred. Use register_scale(..., "
				"qualities=[...]) or write the chord name explicitly."
			)

		return subsequence.chords.Chord(root_pc=root_pc, quality=qualities[self.degree - 1])

	def diatonic_extension_intervals (
		self,
		key_pc: int,
		scale: str,
		extensions: typing.Tuple[typing.Any, ...],
	) -> typing.Tuple[int, ...]:

		"""Stack diatonic thirds above the triad for numeric extensions.

		Only meaningful for inferred-quality degrees (the bare-int path):
		``extend(7)`` on V in C major yields F natural (a dominant seventh),
		where the colour rule on a concrete G chord would yield F#.
		"""

		mode = "minor" if self.borrowed and scale != "minor" else ("ionian" if self.borrowed else scale)
		pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)
		root_pc = (pcs[self.degree - 1] + self.accidental) % 12

		intervals: typing.List[int] = []

		for extension in extensions:

			if not isinstance(extension, int):
				continue	# sus/add forms are scale-independent — the colour path handles them

			# 7 → six scale steps above the root; 9 → eight; 11 → ten; 13 → twelve.
			steps = {7: 6, 9: 8, 11: 10, 13: 12}.get(extension)

			if steps is None:
				continue

			pc = pcs[(self.degree - 1 + steps) % len(pcs)]
			octave = 0 if extension == 7 else 12	# 9ths/11ths/13ths live above the octave
			intervals.append(((pc - root_pc) % 12) + octave)

		return tuple(sorted(set(intervals)))


# Major-relative spelling of every pitch-class offset from the tonic — the
# pop/rock roman convention (b3, b6, b7; b2 and b5 for the rest).  Used by
# generation to emit scale-proof RomanChords.
_OFFSET_SPELLING: typing.Dict[int, typing.Tuple[int, int]] = {
	0: (1, 0), 1: (2, -1), 2: (2, 0), 3: (3, -1), 4: (3, 0), 5: (4, 0),
	6: (5, -1), 7: (5, 0), 8: (6, -1), 9: (6, 0), 10: (7, -1), 11: (7, 0),
}

_ROMAN_NUMERALS: typing.Tuple[str, ...] = ("I", "II", "III", "IV", "V", "VI", "VII")

# The scale each built-in graph style implies — used to infer qualities for
# int constraints (end=1) and as generation's default resolve scale.  Styles
# without diatonic quality rows fall back to ionian.
_STYLE_SCALES: typing.Dict[str, str] = {
	"functional_major": "ionian",
	"diatonic_major": "ionian",
	"turnaround": "ionian",
	"turnaround_global": "ionian",
	"aeolian_minor": "minor",
	"phrygian_minor": "phrygian",
	"lydian_major": "lydian",
	"dorian_minor": "dorian",
	"mixolydian": "mixolydian",
}

# Quality → (prints lowercase, printable suffix).  Qualities outside the
# table print as an explicit parenthesised tail.
_ROMAN_QUALITY_TEXT: typing.Dict[str, typing.Tuple[bool, str]] = {
	"major": (False, ""),
	"minor": (True, ""),
	"dominant_7th": (False, "7"),
	"minor_7th": (True, "7"),
	"major_7th": (False, "maj7"),
	"diminished": (True, "°"),
	"diminished_7th": (True, "°7"),
	"half_diminished_7th": (True, "ø7"),
	"augmented": (False, "+"),
}


def resolve_constraint (spec: typing.Any, key_pc: int, scale: str, what: str) -> subsequence.chords.Chord:

	"""Parse one hybrid-constraint spec (pin/end/avoid) into a concrete chord.

	Specs follow the progression-element grammar: ints are diatonic degrees
	(quality inferred from *scale*), strings are chord names or romans,
	``Chord`` objects pass through.  ``PitchSet``s are rejected — generation
	needs rooted chords.
	"""

	parsed = parse_element(spec).chord

	if isinstance(parsed, PitchSet):
		raise ValueError(f"{what}: generation needs rooted chords — a PitchSet cannot constrain the walk")
	if isinstance(parsed, RomanChord):
		return parsed.resolve(key_pc, scale)

	return typing.cast(subsequence.chords.Chord, parsed)


def _roman_from_chord (chord: subsequence.chords.Chord, tonic_pc: int) -> RomanChord:

	"""Spell a concrete chord relative to a tonic, scale-proof.

	The inverse of resolution for generated values: the root becomes a
	major-relative degree (accidentals for the chromatic offsets), the
	quality stays explicit, and ``source_text`` carries a printable roman
	for unbound ``describe()``.
	"""

	offset = (chord.root_pc - tonic_pc) % 12
	degree, accidental = _OFFSET_SPELLING[offset]

	lowercase, suffix = _ROMAN_QUALITY_TEXT.get(chord.quality, (False, f"({chord.quality})"))
	numeral = _ROMAN_NUMERALS[degree - 1]
	text = ("b" if accidental < 0 else "#" if accidental > 0 else "") + (numeral.lower() if lowercase else numeral) + suffix

	return RomanChord(
		degree = degree,
		accidental = accidental,
		quality = chord.quality,
		source_text = text,
		major_relative = True,
	)


# ---------------------------------------------------------------------------
# ChordSpan — the unit the clock walks
# ---------------------------------------------------------------------------


_EXTENSION_NAMES: typing.FrozenSet[str] = frozenset({"sus2", "sus4", "add9", "6"})
_NUMERIC_EXTENSIONS: typing.FrozenSet[int] = frozenset({7, 9, 11, 13})
_SPREAD_STYLES: typing.FrozenSet[str] = frozenset({"close", "open", "wide"})


@dataclasses.dataclass(frozen=True)
class ChordSpan:

	"""One chord with a duration and its decoration — the unit of harmonic time.

	Decoration (extensions, slash bass, inversion, spread) lives HERE, never
	on :class:`~subsequence.chords.Chord`: the engine's graph identity stays
	the bare triad, and the decorated voicing is what patterns hear.

	Attributes:
		chord: A concrete ``Chord``, a key-relative :class:`RomanChord`, or a
			:class:`PitchSet`.
		beats: Span length in beats.
		extensions: Extension markers — ints (``7``, ``9``, ``11``, ``13``)
			or names (``"sus2"``, ``"sus4"``, ``"add9"``, ``"6"``).
		bass: Slash/pedal bass — a pitch class int, a note name, or
			``"tonic"`` (resolved against the key at query time).
		inversion: Chord inversion for the voicing (0 = root position).
		spread: Voicing spread — ``"close"`` (default), ``"open"`` (drop-2),
			or ``"wide"`` (drop-2-and-4).
		extension_intervals: Pre-computed semitone offsets for the
			extensions, set by :meth:`Progression.resolve` for diatonic
			degrees.  ``None`` means "derive from the chord's own colour".
	"""

	chord: typing.Any
	beats: float
	extensions: typing.Tuple[typing.Any, ...] = ()
	bass: typing.Optional[typing.Union[int, str]] = None
	inversion: int = 0
	spread: typing.Optional[str] = None
	extension_intervals: typing.Optional[typing.Tuple[int, ...]] = None

	def __post_init__ (self) -> None:

		"""Validate beats, extensions, and spread."""

		if self.beats <= 0:
			raise ValueError(f"a chord span must last at least one beat-fraction, got {self.beats:g}")

		for extension in self.extensions:
			if isinstance(extension, bool) or not (
				(isinstance(extension, int) and extension in _NUMERIC_EXTENSIONS)
				or (isinstance(extension, str) and extension in _EXTENSION_NAMES)
			):
				known = ", ".join(["7", "9", "11", "13"] + sorted(_EXTENSION_NAMES))
				raise ValueError(f"unknown extension {extension!r} — expected one of: {known}")

		if self.spread is not None and self.spread not in _SPREAD_STYLES:
			raise ValueError(f"unknown spread {self.spread!r} — expected one of: " + ", ".join(sorted(_SPREAD_STYLES)))

	@property
	def is_concrete (self) -> bool:

		"""True when the chord needs no key context to sound."""

		return not isinstance(self.chord, RomanChord)

	@property
	def is_decorated (self) -> bool:

		"""True when the span carries any decoration beyond the bare chord."""

		return bool(self.extensions) or self.bass is not None or self.inversion != 0 or self.spread is not None

	def resolve (self, key_pc: int, scale: str = "ionian") -> "ChordSpan":

		"""Return a concrete span: romans resolved, bass resolved to a pitch class."""

		chord = self.chord
		extension_intervals = self.extension_intervals

		if isinstance(chord, RomanChord):
			if chord.quality is None and any(isinstance(e, int) for e in self.extensions):
				extension_intervals = chord.diatonic_extension_intervals(key_pc, scale, self.extensions)
			chord = chord.resolve(key_pc, scale)

		bass: typing.Optional[typing.Union[int, str]] = self.bass

		if isinstance(bass, str):
			if bass == "tonic":
				bass = key_pc
			else:
				bass = subsequence.chords.key_name_to_pc(bass)

		return dataclasses.replace(
			self,
			chord = chord,
			bass = bass,
			extension_intervals = extension_intervals,
		)

	def label (self, key_pc: typing.Optional[int] = None, scale: str = "ionian") -> str:

		"""A printable chord label: roman text when relative, decorated name when concrete."""

		if isinstance(self.chord, RomanChord):
			if key_pc is None:
				text = self.chord.label()
				return text + self._decoration_suffix(resolved=False)
			return self.resolve(key_pc, scale).label()

		base = str(self.chord.name())
		return base + self._decoration_suffix(resolved=True)

	def _decoration_suffix (self, resolved: bool) -> str:

		"""The printable decoration tail (extensions and slash bass)."""

		parts = ""
		numeric = sorted(e for e in self.extensions if isinstance(e, int))

		# 9 implies 7 (and so on up): print only the highest stacked extension.
		stacked = [e for e in numeric if e in (7, 9, 11, 13)]
		if stacked:
			parts += str(stacked[-1])

		for name in (e for e in self.extensions if isinstance(e, str)):
			parts += name

		if self.bass is not None:
			if isinstance(self.bass, int):
				parts += "/" + subsequence.chords.PC_TO_NOTE_NAME[self.bass % 12]
			else:
				parts += "/" + str(self.bass)

		return parts

	def decorated_intervals (self) -> typing.List[int]:

		"""Semitone offsets of the decorated voicing (before inversion/spread/bass).

		Numeric extensions deepen the chord in its own colour — a minor third
		gets a minor seventh, a major third a major seventh, a diminished
		triad a diminished seventh.  Diatonic degrees extended with
		``extend(...)`` carry pre-computed scale-true intervals instead (so V
		gets its dominant seventh).  Write ``"G7"``/``"V7"`` when you want the
		dominant colour on a concrete major chord.
		"""

		if isinstance(self.chord, RomanChord):
			raise ValueError("cannot voice a key-relative span — resolve(key=...) it first")

		intervals = list(self.chord.intervals())

		sus = [e for e in self.extensions if e in ("sus2", "sus4")]
		if sus and len(intervals) >= 2:
			intervals[1] = 2 if sus[0] == "sus2" else 5

		numeric = sorted(e for e in self.extensions if isinstance(e, int))

		if self.extension_intervals is not None:
			added: typing.List[int] = list(self.extension_intervals)
		else:
			added = []
			third = intervals[1] if len(intervals) >= 2 else None
			has_seventh = any(i in (9, 10, 11) for i in intervals)
			stacked = [e for e in numeric if e in _NUMERIC_EXTENSIONS]

			if stacked and not has_seventh:
				if third == 3 and len(intervals) >= 3 and intervals[2] == 6:
					added.append(9)		# diminished colour
				elif third == 3:
					added.append(10)	# minor colour
				elif third == 4:
					added.append(11)	# major colour
				else:
					added.append(10)	# sus / no third: the dominant-leaning seventh

			for extension in stacked:
				if extension == 9:
					added.append(14)
				elif extension == 11:
					added.append(17)
				elif extension == 13:
					added.append(21)

		if "add9" in self.extensions:
			added.append(14)
		if "6" in self.extensions:
			added.append(9)

		return sorted(set(intervals) | set(added))

	def tones (self, root: int = 60, count: typing.Optional[int] = None) -> typing.List[int]:

		"""MIDI notes of the decorated voicing nearest *root* (concrete spans only).

		Applies, in order: extensions, inversion, spread, then the slash/pedal
		bass below the voicing.  ``PitchSet`` spans return their absolute
		pitches (decoration other than ``count`` does not apply).
		"""

		if isinstance(self.chord, RomanChord):
			raise ValueError("cannot voice a key-relative span — resolve(key=...) it first")

		if isinstance(self.chord, PitchSet):
			return self.chord.tones(root, inversion=self.inversion, count=count)

		intervals = self.decorated_intervals()

		if self.inversion != 0:
			intervals = subsequence.voicings.invert_chord(intervals, self.inversion)

		if self.spread == "open" and len(intervals) >= 3:
			intervals = sorted(intervals[:-2] + [intervals[-2] - 12] + intervals[-1:])
		elif self.spread == "wide" and len(intervals) >= 3:
			dropped = [i - 12 if position in (len(intervals) - 2, len(intervals) - 4) else i for position, i in enumerate(intervals)]
			intervals = sorted(dropped)

		offset = (self.chord.root_pc - root) % 12
		if offset > 6:
			offset -= 12
		effective_root = root + offset

		if count is not None:
			n = len(intervals)
			span_octave = max(12, ((max(intervals) // 12) + 1) * 12)
			pitches = [effective_root + intervals[i % n] + span_octave * (i // n) for i in range(count)]
		else:
			pitches = [effective_root + interval for interval in intervals]

		if self.bass is not None and isinstance(self.bass, int):
			lowest = min(pitches)
			bass_note = lowest - ((lowest - self.bass) % 12)
			if bass_note == lowest:
				bass_note -= 12
			pitches = [bass_note] + pitches

		return pitches


class DecoratedChord:

	"""Duck-types the ``Chord`` voicing protocol over a decorated span.

	What patterns and the injected ``chord`` receive when a span carries
	decoration: ``tones()`` voices the extensions/inversion/spread/bass,
	``intervals()`` reports the decorated intervals (so per-pattern voice
	leading works over them), and ``name()`` prints the decorated name
	(``Am9``, ``C/G``).  The engine itself never sees this — graph identity
	stays the bare triad underneath (:attr:`base`).
	"""

	def __init__ (self, span: ChordSpan) -> None:

		"""Wrap a concrete, decorated span."""

		if not span.is_concrete:
			raise ValueError("DecoratedChord needs a concrete span — resolve(key=...) first")

		self._span = span

	@property
	def base (self) -> typing.Any:

		"""The undecorated chord (the engine's currency)."""

		return self._span.chord

	@property
	def span (self) -> ChordSpan:

		"""The wrapped span (decoration and all)."""

		return self._span

	@property
	def root_pc (self) -> int:

		"""The root pitch class of the underlying chord."""

		return int(self._span.chord.root_pc) if hasattr(self._span.chord, "root_pc") else self._span.chord.pitches[0] % 12

	@property
	def quality (self) -> str:

		"""The quality of the underlying chord."""

		return str(getattr(self._span.chord, "quality", "pitch_set"))

	def intervals (self) -> typing.List[int]:

		"""Decorated semitone offsets from the root."""

		if isinstance(self._span.chord, PitchSet):
			return self._span.chord.intervals()

		return self._span.decorated_intervals()

	def tones (self, root: int = 60, inversion: int = 0, count: typing.Optional[int] = None) -> typing.List[int]:

		"""Decorated voicing nearest *root*; an explicit *inversion* overrides the span's."""

		span = self._span if inversion == 0 else dataclasses.replace(self._span, inversion=inversion)

		return span.tones(root, count=count)

	def root_note (self, root_midi: int) -> int:

		"""The MIDI note of the (undecorated) chord root nearest *root_midi*."""

		if isinstance(self._span.chord, PitchSet):
			return self._span.chord.pitches[0]

		return int(self._span.chord.root_note(root_midi))

	def bass_note (self, root_midi: int, octave_offset: int = -1) -> int:

		"""The chord root shifted by octaves (the slash bass pc when one is set)."""

		if isinstance(self._span.bass, int):
			lowest = self.root_note(root_midi)
			bass = lowest - ((lowest - self._span.bass) % 12)
			return bass + 12 * (octave_offset + 1)

		return self.root_note(root_midi) + (12 * octave_offset)

	def name (self) -> str:

		"""The decorated chord name (``Am9``, ``C/G``)."""

		return self._span.label()


# ---------------------------------------------------------------------------
# The roman / name / degree element parser
# ---------------------------------------------------------------------------

_ROMAN_VALUES: typing.Dict[str, int] = {
	"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
}

_ROMAN_RE = re.compile(
	r"^(?P<accidental>[b#])?"
	r"(?P<numeral>[ivIV]+)"
	r"(?P<modifier>°|o|ø|\+|aug|dim)?"
	r"(?P<maj7>maj7|M7)?"
	r"(?P<figure>65|64|43|42|7|6|2)?"
	r"(?:/(?P<of>.+))?$"
)

# Figure → (adds a seventh, inversion).
_FIGURES: typing.Dict[typing.Optional[str], typing.Tuple[bool, int]] = {
	None: (False, 0),
	"6": (False, 1),
	"64": (False, 2),
	"7": (True, 0),
	"65": (True, 1),
	"43": (True, 2),
	"42": (True, 3),
	"2": (True, 3),
}


def parse_roman (text: str) -> typing.Tuple[RomanChord, int]:

	"""Parse a roman numeral element into a (RomanChord, inversion) pair.

	The ~music21 semantics grammar: case is quality (``IV`` major, ``iv``
	minor), ``°``/``o``/``dim`` diminished, ``ø`` half-diminished, ``+``/
	``aug`` augmented; ``maj7`` forces the major seventh; figured-bass
	suffixes give sevenths and inversions (``7``/``65``/``43``/``42``;
	``6``/``64`` for triads); ``b``/``#`` prefixes shift the degree; one
	level of ``/x`` secondary function (``V7/IV``).

	Raises ``ValueError`` for anything it can't read.
	"""

	stripped = text.strip()
	match = _ROMAN_RE.match(stripped)

	if not match:
		raise ValueError(f"Cannot parse roman numeral {text!r} — expected e.g. 'V7', 'bVII', 'ii65', 'V/V'")

	numeral = match.group("numeral")
	lowered = numeral.lower()

	if lowered not in _ROMAN_VALUES or numeral not in (lowered, numeral.upper()):
		raise ValueError(f"Cannot parse roman numeral {text!r} — {numeral!r} is not a degree numeral (I–VII)")

	degree = _ROMAN_VALUES[lowered]
	is_upper = numeral == numeral.upper()
	accidental = {"b": -1, "#": 1}.get(match.group("accidental") or "", 0)

	modifier = match.group("modifier")
	has_maj7 = match.group("maj7") is not None
	has_seventh, inversion = _FIGURES[match.group("figure")]

	if modifier in ("°", "o", "dim"):
		quality = "diminished_7th" if has_seventh else "diminished"
	elif modifier == "ø":
		quality = "half_diminished_7th"
	elif modifier in ("+", "aug"):
		quality = "augmented"
	elif has_maj7:
		if not is_upper:
			raise ValueError(f"Cannot parse roman numeral {text!r} — maj7 needs an uppercase numeral")
		quality = "major_7th"
	elif has_seventh:
		quality = "dominant_7th" if is_upper else "minor_7th"
	else:
		quality = "major" if is_upper else "minor"

	of: typing.Optional[int] = None
	of_text = match.group("of")

	if of_text is not None:
		if "/" in of_text:
			raise ValueError(f"Cannot parse roman numeral {text!r} — only one level of secondary function (/x) is supported")
		if of_text.lower() in _ROMAN_VALUES:
			of = _ROMAN_VALUES[of_text.lower()]
		elif of_text.isdigit():
			of = int(of_text)
		else:
			raise ValueError(f"Cannot parse roman numeral {text!r} — secondary target {of_text!r} is not a degree")

	roman = RomanChord(
		degree = degree,
		accidental = accidental,
		quality = quality,
		of = of,
		source_text = stripped,
	)

	return roman, inversion


def parse_element (element: typing.Any, beats: float = DEFAULT_SPAN_BEATS) -> ChordSpan:

	"""Parse one progression-list element into a :class:`ChordSpan`.

	Elements mix freely and are parsed per element (decision 16): ints are
	diatonic degrees (1-based, quality inferred from key+scale at query
	time); strings are chord names where they start with a note letter
	(``"Am"``) and romans otherwise (``"VI"``, ``"bVII7"``); ``Chord``,
	``PitchSet``, and ``ChordSpan`` values pass through; an
	``(element, beats)`` tuple sets the span length.
	"""

	if isinstance(element, ChordSpan):
		return element

	if isinstance(element, tuple):
		if len(element) != 2:
			raise ValueError(f"a progression tuple element must be (chord, beats), got {element!r}")
		inner, span_beats = element
		return parse_element(inner, beats=float(span_beats))

	if isinstance(element, bool):
		raise TypeError(f"cannot parse progression element {element!r} (bool)")

	if isinstance(element, int):
		return ChordSpan(chord=RomanChord(degree=element, source_text=str(element)), beats=beats)

	if isinstance(element, (subsequence.chords.Chord, PitchSet, RomanChord)):
		return ChordSpan(chord=element, beats=beats)

	if isinstance(element, str):
		stripped = element.strip()
		if stripped and stripped[0] in "ABCDEFG":
			return ChordSpan(chord=subsequence.chords.parse_chord(stripped), beats=beats)
		roman, inversion = parse_roman(stripped)
		return ChordSpan(chord=roman, beats=beats, inversion=inversion)

	raise TypeError(
		f"cannot parse progression element {element!r} — expected an int degree, "
		"a chord name or roman string, a Chord, a PitchSet, or an (element, beats) tuple"
	)


# ---------------------------------------------------------------------------
# The Progression value
# ---------------------------------------------------------------------------


def _check_slot (slot: int, count: int) -> int:

	"""Validate a 1-based chord slot and return its 0-based index."""

	if not isinstance(slot, int) or isinstance(slot, bool):
		raise TypeError(f"chord slots are 1-based ints, got {slot!r}")
	if slot < 1 or slot > count:
		raise ValueError(f"chord slot {slot} is out of range (1–{count})")

	return slot - 1


@dataclasses.dataclass(frozen=True)
class Progression:

	"""A frozen sequence of :class:`ChordSpan` — the governing harmony value.

	Always a realised value: binding it to the clock freezes one realisation;
	``p.progression()`` keeps its breathing behaviour by re-realising a fresh
	one each rebuild.  Iterating yields ``(chord, start, length)``
	:class:`ChordEvent` tuples (the old ``ChordTimeline`` contract), so
	placement loops keep working unchanged.

	The governing family supports ``+`` (concatenate) and ``*`` (tile) but
	never ``&`` — there is one current chord (P1, the type law).

	Attributes:
		spans: The chord spans, in order.
		trailing_history: Engine continuity metadata set by
			:meth:`Composition.freeze` — the NIR history at capture time,
			restored on each frozen replay.  Empty for hand-built values.
	"""

	spans: typing.Tuple[ChordSpan, ...]
	trailing_history: typing.Tuple[subsequence.chords.Chord, ...] = ()

	def __post_init__ (self) -> None:

		"""Normalise span containers to tuples."""

		object.__setattr__(self, "spans", tuple(self.spans))
		object.__setattr__(self, "trailing_history", tuple(self.trailing_history))

		if not self.spans:
			raise ValueError("a Progression needs at least one chord span")

	# -- queries ------------------------------------------------------------

	@property
	def length (self) -> float:

		"""Total length in beats (the sum of span lengths)."""

		return float(sum(span.beats for span in self.spans))

	@property
	def is_concrete (self) -> bool:

		"""True when every span is key-independent (no romans/degrees)."""

		return all(span.is_concrete for span in self.spans)

	@property
	def chords (self) -> typing.Tuple[typing.Any, ...]:

		"""The bare chords, one per span (concrete progressions only)."""

		self._require_concrete("read .chords")

		return tuple(span.chord for span in self.spans)

	@property
	def loops_on_exhaustion (self) -> bool:

		"""True when the clock must loop rather than fall through to live stepping."""

		return any(isinstance(span.chord, PitchSet) for span in self.spans)

	def _require_concrete (self, action: str) -> None:

		"""Raise with a resolution hint when key-relative spans remain."""

		if not self.is_concrete:
			relative = ", ".join(span.label() for span in self.spans if not span.is_concrete)
			raise ValueError(
				f"cannot {action} on a key-relative progression (contains {relative}) — "
				"call .resolve(key=...) first, or bind it where a key is known"
			)

	def __iter__ (self) -> typing.Iterator[ChordEvent]:

		"""Yield ``(chord, start, length)`` events — decorated chords where spiced."""

		self._require_concrete("iterate")

		cursor = 0.0

		for span in self.spans:
			chord = DecoratedChord(span) if span.is_decorated else span.chord
			yield ChordEvent(chord=chord, start=cursor, length=span.beats)
			cursor += span.beats

	def __len__ (self) -> int:

		"""The number of chord spans."""

		return len(self.spans)

	def events (self) -> typing.Tuple[ChordEvent, ...]:

		"""The realised timeline as a tuple (iteration, materialised)."""

		return tuple(self)

	def span_at (self, beat: float) -> typing.Tuple[ChordSpan, float, float]:

		"""Return ``(span, start, end)`` for the span sounding at *beat*.

		*beat* wraps modulo the progression length, so the lookup also
		serves looped playback.
		"""

		position = beat % self.length
		cursor = 0.0

		for span in self.spans:
			if cursor <= position < cursor + span.beats:
				return span, cursor, cursor + span.beats
			cursor += span.beats

		final = self.spans[-1]
		return final, self.length - final.beats, self.length

	def resolve (self, key: typing.Union[str, int], scale: str = "ionian") -> "Progression":

		"""Resolve every key-relative span against a key (name or pitch class)."""

		key_pc = key if isinstance(key, int) else subsequence.chords.key_name_to_pc(key)

		return dataclasses.replace(
			self,
			spans = tuple(span.resolve(key_pc, scale) for span in self.spans),
		)

	@classmethod
	def generate (
		cls,
		style: typing.Union[str, typing.Any] = "functional_major",
		bars: int = 8,
		beats: typing.Union[float, typing.List[float]] = DEFAULT_SPAN_BEATS,
		*,
		key: typing.Optional[str] = None,
		scale: typing.Optional[str] = None,
		seed: typing.Optional[int] = None,
		rng: typing.Optional[random.Random] = None,
		pins: typing.Optional[typing.Dict[int, typing.Any]] = None,
		end: typing.Optional[typing.Any] = None,
		avoid: typing.Optional[typing.Sequence[typing.Any]] = None,
		dominant_7th: bool = True,
		gravity: float = 1.0,
		nir_strength: float = 0.5,
		minor_turnaround_weight: float = 0.0,
		root_diversity: float = subsequence.harmonic_state.DEFAULT_ROOT_DIVERSITY,
	) -> "Progression":

		"""Generate a progression from a chord-graph walk — the hybrid generator.

		Full parameter pass-through to the engine (no more throwaway default
		engines), plus the hybrid constraints: ``pins`` fix chords at 1-based
		bars, ``end`` fixes the last bar, ``avoid`` excludes chords
		everywhere.  Constraints compile into the walk — a backward
		feasibility pass guarantees satisfiability before any chord is
		drawn (unsatisfiable constraints raise immediately), then a forward
		walk samples through the engine's real history-dependent weights
		(NIR, gravity, diversity keep their character).

		**Without** ``key=`` the result is key-relative — the walk runs
		against a reference tonic and the spans store scale-proof
		major-relative romans, so the value prints meaningfully unbound and
		resolves wherever it is bound (the walk itself is key-invariant).
		**With** ``key=`` the result is concrete.

		Parameters:
			style: A chord-graph style name (or ``ChordGraph`` instance).
			bars: How many chords to generate.
			beats: Span length per chord — a scalar, or a list cycled.
			key: Key for a concrete result; omit for a key-relative value.
			scale: Scale for int constraints' quality inference (e.g.
				``end=1``).  Defaults from the style (aeolian_minor →
				minor); explicit strings (``"V"``, ``"bVII7"``) never
				need it.
			seed: Seed for the walk.  A standalone generated value without
				a seed warns — module-level nondeterminism breaks live
				reload.
			rng: An explicit random stream (overrides ``seed``).
			pins: ``{bar: chord}`` — 1-based; values parse like progression
				elements (ints, romans, names, ``Chord``).
			end: The chord at the final bar — ``end="V"`` is the cadential
				major dominant in minor (a string because it is chromatic;
				no int can ask for it).
			avoid: Chords excluded from the walk.  Naming a chord outside
				the style's vocabulary is allowed (trivially satisfied).
			dominant_7th / gravity / nir_strength / minor_turnaround_weight /
				root_diversity: The engine parameters, exactly as
				:meth:`Composition.harmony` takes them.

		Example:
			```python
			chorus = subsequence.Progression.generate(
				style="aeolian_minor", bars=4, end="V", seed=7,
			)
			print(chorus)        # romans until bound
			```
		"""

		if bars < 1:
			raise ValueError("bars must be at least 1")

		if rng is None:
			if seed is None:
				warnings.warn(
					"Progression.generate without seed= is nondeterministic — "
					"pass seed= so the value survives live reload",
					stacklevel = 2,
				)
				rng = random.Random()
			else:
				rng = random.Random(seed)

		resolved_scale = scale if scale is not None else _STYLE_SCALES.get(style if isinstance(style, str) else "", "ionian")
		relative = key is None
		reference = key if key is not None else "C"

		state = subsequence.harmonic_state.HarmonicState(
			key_name = reference,
			graph_style = style,
			include_dominant_7th = dominant_7th,
			key_gravity_blend = gravity,
			nir_strength = nir_strength,
			minor_turnaround_weight = minor_turnaround_weight,
			root_diversity = root_diversity,
			rng = rng,
		)

		resolved_pins = {
			position: resolve_constraint(spec, state.key_root_pc, resolved_scale, f"pins[{position}]")
			for position, spec in (pins or {}).items()
		}
		resolved_end = resolve_constraint(end, state.key_root_pc, resolved_scale, "end") if end is not None else None
		resolved_avoid = [resolve_constraint(spec, state.key_root_pc, resolved_scale, "avoid") for spec in (avoid or [])]

		if 1 in resolved_pins:
			if resolved_pins[1] not in state.graph.nodes():
				raise ValueError(
					f"pins[1]={resolved_pins[1].name()} is not in style {style!r}'s vocabulary"
				)
			state.current_chord = resolved_pins[1]

		def commit (chosen: subsequence.chords.Chord) -> None:
			state.current_chord = chosen

		walked = subsequence.sequence_utils.constrained_walk(
			state.graph,
			state.current_chord,
			bars,
			rng = state.rng,
			pins = resolved_pins,
			end = resolved_end,
			avoid = resolved_avoid,
			weight_modifier = state._transition_weight,
			before_choice = state._record_transition_source,
			after_choice = commit,
		)

		lengths = _span_lengths(beats, bars)

		if relative:
			return cls(spans = tuple(
				ChordSpan(chord = _roman_from_chord(chord, state.key_root_pc), beats = lengths[index])
				for index, chord in enumerate(walked)
			))

		return cls(spans = tuple(
			ChordSpan(chord = chord, beats = lengths[index])
			for index, chord in enumerate(walked)
		))

	# -- algebra ------------------------------------------------------------

	def __add__ (self, other: "Progression") -> "Progression":

		"""Concatenate two progressions (the governing ``+``)."""

		if not isinstance(other, Progression):
			return NotImplemented

		return Progression(spans = self.spans + other.spans)

	def __mul__ (self, count: int) -> "Progression":

		"""Tile the spans *count* times."""

		if not isinstance(count, int) or isinstance(count, bool):
			return NotImplemented
		if count < 1:
			raise ValueError("a progression must repeat at least once (n >= 1)")

		return Progression(spans = self.spans * count)

	def __and__ (self, other: typing.Any) -> "Progression":

		"""Parallel merge is a type error for governing values — by design."""

		raise TypeError(
			"Progressions cannot be merged with & — there is one current chord. "
			"Sequence them with +, or give a pattern its own part-level progression."
		)

	# -- spice (the five operators) and editing ------------------------------

	def extend (self, *extensions: typing.Any, only: typing.Optional[typing.List[int]] = None) -> "Progression":

		"""Add chord extensions (``7``/``9``/``11``/``13``/``"sus4"``/...) to every span.

		``only=`` restricts the spice to the given 1-based chord slots.
		"""

		slots = set(range(len(self.spans))) if only is None else {_check_slot(s, len(self.spans)) for s in only}

		spans = tuple(
			dataclasses.replace(span, extensions = tuple(dict.fromkeys(span.extensions + extensions)))
			if index in slots else span
			for index, span in enumerate(self.spans)
		)

		return dataclasses.replace(self, spans=spans)

	def inversions (self, spec: typing.Union[int, typing.List[int]]) -> "Progression":

		"""Set chord inversions — a single int for all spans, or a list cycled per span."""

		values = [spec] if isinstance(spec, int) else list(spec)

		if not values:
			raise ValueError("inversions list is empty — pass at least one inversion")

		spans = tuple(
			dataclasses.replace(span, inversion = int(values[index % len(values)]))
			for index, span in enumerate(self.spans)
		)

		return dataclasses.replace(self, spans=spans)

	def spread (self, style: str) -> "Progression":

		"""Set the voicing spread: ``"close"``, ``"open"`` (drop-2), or ``"wide"``."""

		spans = tuple(dataclasses.replace(span, spread = None if style == "close" else style) for span in self.spans)

		return dataclasses.replace(self, spans=spans)

	def over (self, bass: typing.Union[int, str], only: typing.Optional[typing.List[int]] = None) -> "Progression":

		"""Put the progression over a slash/pedal bass — *the* trance/techno move.

		*bass* is a pitch class int, a note name (``"G"``), or ``"tonic"``
		(resolved against the key at query time).  ``only=`` restricts it to
		the given 1-based slots (slash chords rather than a full pedal).
		"""

		if isinstance(bass, str) and bass != "tonic":
			subsequence.chords.key_name_to_pc(bass)	# validate early; resolution stays late
		elif isinstance(bass, int) and not 0 <= bass <= 11:
			raise ValueError(f"a bass pitch class must be 0–11, got {bass}")

		slots = set(range(len(self.spans))) if only is None else {_check_slot(s, len(self.spans)) for s in only}

		spans = tuple(
			dataclasses.replace(span, bass=bass) if index in slots else span
			for index, span in enumerate(self.spans)
		)

		return dataclasses.replace(self, spans=spans)

	def borrow (self, slot: typing.Union[int, typing.List[int]]) -> "Progression":

		"""Borrow the chord(s) at the given 1-based slot(s) from the parallel scale.

		Modal interchange for key-relative content: the degree re-resolves
		against the parallel mode (minor under a major scale and vice
		versa).  Concrete chords raise — there is nothing relative to borrow.
		"""

		slots = {_check_slot(s, len(self.spans)) for s in ([slot] if isinstance(slot, int) else slot)}

		spans = list(self.spans)

		for index in slots:
			chord = spans[index].chord
			if not isinstance(chord, RomanChord):
				raise ValueError(
					f"slot {index + 1} holds a concrete chord ({spans[index].label()}) — "
					"borrow() needs key-relative content (an int degree or roman)"
				)
			spans[index] = dataclasses.replace(spans[index], chord = dataclasses.replace(chord, borrowed = not chord.borrowed))

		return dataclasses.replace(self, spans=tuple(spans))

	def replace (self, slot: int, chord: typing.Any) -> "Progression":

		"""Replace the chord at a 1-based slot (the span keeps its beats)."""

		index = _check_slot(slot, len(self.spans))
		parsed = parse_element(chord, beats = self.spans[index].beats)

		spans = self.spans[:index] + (parsed,) + self.spans[index + 1:]

		return dataclasses.replace(self, spans=spans)

	def with_rhythm (self, beats: typing.Union[float, typing.List[float]]) -> "Progression":

		"""Reshape the harmonic rhythm — a scalar for all spans, or a list cycled per span."""

		if isinstance(beats, bool):
			raise TypeError(f"with_rhythm takes beats or a list of beats, got bool: {beats!r}")

		values = [float(beats)] if isinstance(beats, (int, float)) else [float(b) for b in beats]

		if not values:
			raise ValueError("with_rhythm list is empty — pass at least one length")

		spans = tuple(
			dataclasses.replace(span, beats = float(values[index % len(values)]))
			for index, span in enumerate(self.spans)
		)

		return dataclasses.replace(self, spans=spans)

	# -- description ----------------------------------------------------------

	def describe (self, key: typing.Optional[typing.Union[str, int]] = None, scale: str = "ionian") -> str:

		"""A readable, one-chord-per-line summary.

		Key-relative spans print as written (romans/degrees) when unbound,
		and as concrete chord names under a *key*.
		"""

		key_pc = None if key is None else (key if isinstance(key, int) else subsequence.chords.key_name_to_pc(key))

		lines = [f"Progression — {len(self.spans)} chords over {self.length:g} beats"]
		cursor = 0.0

		for span in self.spans:
			lines.append(
				f"  {cursor:6.2f} … {cursor + span.beats:6.2f}   "
				f"{span.label(key_pc, scale):<8} ({span.beats:g} beats)"
			)
			cursor += span.beats

		return "\n".join(lines)

	def __str__ (self) -> str:

		"""Same as :meth:`describe` with no key bound."""

		return self.describe()


# ---------------------------------------------------------------------------
# Construction: the factory, generation, and the breathing realise() path
# ---------------------------------------------------------------------------


def _span_lengths (beats: typing.Union[float, typing.List[float]], count: int) -> typing.List[float]:

	"""Resolve a beats= spec into per-span lengths — a scalar for all, or a list cycled."""

	if isinstance(beats, bool):
		raise TypeError(f"beats takes a number or a list of lengths, got bool: {beats!r}")

	if isinstance(beats, (int, float)):
		return [float(beats)] * count

	values = [float(b) for b in beats]

	if not values:
		raise ValueError("beats list is empty — pass at least one length")

	return [values[index % len(values)] for index in range(count)]


def progression (
	source: typing.Optional[typing.Any] = None,
	beats: typing.Union[float, typing.List[float]] = DEFAULT_SPAN_BEATS,
	*,
	style: typing.Optional[str] = None,
	bars: int = 8,
	key: typing.Optional[str] = None,
	scale: typing.Optional[str] = None,
	seed: typing.Optional[int] = None,
	rng: typing.Optional[random.Random] = None,
	pins: typing.Optional[typing.Dict[int, typing.Any]] = None,
	end: typing.Optional[typing.Any] = None,
	avoid: typing.Optional[typing.Sequence[typing.Any]] = None,
	dominant_7th: bool = True,
	gravity: float = 1.0,
	nir_strength: float = 0.5,
	minor_turnaround_weight: float = 0.0,
	root_diversity: float = subsequence.harmonic_state.DEFAULT_ROOT_DIVERSITY,
) -> Progression:

	"""Build a :class:`Progression` — the lowercase factory.

	Dispatch by argument type: a **list** parses per element (ints where
	diatonic, name/roman strings where nominal/chromatic, ``(element,
	beats)`` tuples for per-chord durations); a bare **string** names a
	preset from the curated table; ``style=`` generates *bars* chords from a
	chord-graph walk (requires ``key=``).

	Parameters:
		source: The element list, preset name, or an existing Progression
			(returned unchanged).
		beats: Span length per chord — a scalar, or a list cycled per chord
			(``beats=[4, 4, 2, 6]`` shapes the harmonic rhythm).
		style: A chord-graph style name to generate from (e.g.
			``"aeolian_minor"``).
		bars: How many chords to generate (style mode only).
		key: Key for style generation.
		seed: Seed for style generation.  A standalone generated value
			without a seed warns — module-level nondeterminism breaks live
			reload.
		rng: An explicit random stream (overrides ``seed``; used by
			engine-mediated calls).
		dominant_7th / gravity / nir_strength: Graph-walk parameters,
			matching :meth:`Composition.harmony` (style mode only; full
			pass-through arrives with ``Progression.generate``).

	Example:
		```python
		verse = subsequence.progression([1, 6, 3, 7])           # i–VI–III–VII in A minor
		blues = subsequence.progression(["I7"] * 4 + ["IV7", "IV7", "I7", "I7", "V7", "IV7", "I7", "I7"])
		walk  = subsequence.progression(style="aeolian_minor", key="A", bars=8, seed=3)
		```
	"""

	if style is not None:
		if source is not None:
			raise ValueError("pass either source or style=, not both")
		return Progression.generate(
			style = style,
			bars = bars,
			beats = beats,
			key = key,
			scale = scale,
			seed = seed,
			rng = rng,
			pins = pins,
			end = end,
			avoid = avoid,
			dominant_7th = dominant_7th,
			gravity = gravity,
			nir_strength = nir_strength,
			minor_turnaround_weight = minor_turnaround_weight,
			root_diversity = root_diversity,
		)

	if isinstance(source, Progression):
		return source

	if isinstance(source, str):
		if source in _PRESETS:
			return progression(_PRESETS[source], beats=beats)
		raise ValueError(
			f"Unknown progression preset {source!r} (the preset table ships in a later release). "
			"A progression is a list — pass the chords as elements, e.g. progression([1, 6, 3, 7]) "
			"or progression(['Am', 'F', 'C', 'G'])."
		)

	if source is None:
		raise ValueError("progression() needs a source list (or style=...)")

	elements = list(source)

	if not elements:
		raise ValueError("progression list is empty — pass at least one chord")

	lengths = _span_lengths(beats, len(elements))

	return Progression(spans = tuple(
		parse_element(element, beats=lengths[index])
		for index, element in enumerate(elements)
	))


def _chord_source (source: ProgressionSource, key: typing.Optional[str], rng: random.Random, scale: str = "ionian") -> typing.Iterator[typing.Any]:

	"""Yield chords indefinitely — generated from a graph style, or cycled from a list."""

	if isinstance(source, str):
		if not key:
			raise ValueError(f"progression style {source!r} needs a key — pass key= or set the Composition key")
		state = subsequence.harmonic_state.HarmonicState(key_name=key, graph_style=source, rng=rng)
		yield state.current_chord
		while True:
			yield state.step()

	elif isinstance(source, Progression):
		resolved = source if source.is_concrete else source.resolve(
			subsequence.chords.key_name_to_pc(_require_key(source, key)), scale
		)
		index = 0
		while True:
			span = resolved.spans[index % len(resolved.spans)]
			yield DecoratedChord(span) if span.is_decorated else span.chord
			index += 1

	else:
		spans = [parse_element(item) for item in source]
		if not spans:
			raise ValueError("progression list is empty — pass at least one chord")
		chords = []
		for span in spans:
			if not span.is_concrete:
				span = span.resolve(subsequence.chords.key_name_to_pc(_require_key(span, key)), scale)
			chords.append(DecoratedChord(span) if span.is_decorated else span.chord)
		index = 0
		while True:
			yield chords[index % len(chords)]
			index += 1


def _require_key (what: typing.Any, key: typing.Optional[str]) -> str:

	"""Return the key or raise the standard relative-content error."""

	if not key:
		raise ValueError(
			"this progression contains key-relative chords (degrees/romans) — "
			"pass key= or set the Composition key"
		)

	return key


def _resolve_length (spec: HarmonicRhythmSpec, index: int, rng: random.Random) -> float:

	"""Resolve one chord length in beats from a harmonic-rhythm spec.

	Accepts a scalar (static), a list/tuple of lengths (a shaped rhythm, cycled by
	``index``), or a :class:`~subsequence.harmonic_rhythm.HarmonicRhythm` from
	``between(...)``.  Mirrors the ``(low, high)``-tuple house idiom used for
	velocity — except a range here is spelled ``between(...)`` so a bare list can
	mean a *sequence* of lengths.
	"""

	if isinstance(spec, subsequence.harmonic_rhythm.HarmonicRhythm):
		return spec.resolve(rng)
	if isinstance(spec, tuple):  # type: ignore  # the hint says list, but users pass a tuple anyway — guard for it
		# A (low, high) tuple means a random range everywhere else in the API (e.g.
		# velocity); here it would silently cycle.  Reject it so the intent is explicit.
		raise ValueError(
			f"harmonic_rhythm tuple {spec!r} is ambiguous — use between{spec!r} for a random "
			f"range, or a list {list(spec)!r} for a repeating sequence of lengths"
		)
	if isinstance(spec, list):
		if not spec:
			raise ValueError("harmonic_rhythm sequence is empty — pass at least one length")
		return float(spec[index % len(spec)])
	if isinstance(spec, bool):
		raise TypeError(f"harmonic_rhythm must be a number, a list of lengths, or between(...), got bool: {spec!r}")
	if isinstance(spec, (int, float)):
		return float(spec)
	raise TypeError(f"harmonic_rhythm must be a number, a list of lengths, or between(...), got {type(spec).__name__}")


def resolve_voices (voicing: VoicingSpec, rng: random.Random) -> int:

	"""Resolve the voice count for one chord — a fixed int, or a ``(low, high)`` draw."""

	if isinstance(voicing, bool):
		raise TypeError(f"voicing must be an int or a (low, high) tuple, got bool: {voicing!r}")
	if isinstance(voicing, int):
		count = voicing
	elif isinstance(voicing, tuple):
		if len(voicing) != 2:
			raise ValueError(f"voicing tuple must be (low, high), got {voicing!r}")
		count = rng.randint(int(voicing[0]), int(voicing[1]))
	else:
		raise TypeError(f"voicing must be an int or a (low, high) tuple, got {type(voicing).__name__}")
	if count < 1:
		raise ValueError(f"voicing must be at least 1 voice, got {count}")
	return count


def realize (
	source: ProgressionSource,
	harmonic_rhythm: HarmonicRhythmSpec,
	key: typing.Optional[str],
	length: float,
	rng: random.Random,
	scale: str = "ionian",
) -> Progression:

	"""Lay a progression out across *length* beats and return a frozen value.

	Walks the chord source, giving each chord a harmonic-rhythm length, until the
	part is full.  The final chord is trimmed so the timeline ends exactly on
	*length* and therefore loops cleanly.  Voicing and articulation are not decided
	here — they belong to whatever places the chords (the verb you call in the loop,
	or :meth:`Composition.chords`).
	"""

	if length <= 0:
		raise ValueError(f"progression length ({length:g}) must be positive")

	stream = _chord_source(source, key, rng, scale)
	spans: typing.List[ChordSpan] = []
	cursor = 0.0
	index = 0

	while cursor < length - 1e-9:
		chord = next(stream)
		duration = _resolve_length(harmonic_rhythm, index, rng)
		if duration <= 0:
			raise ValueError(f"harmonic_rhythm produced a non-positive length ({duration:g}) — lengths are in beats and must be > 0")
		duration = min(duration, length - cursor)
		if isinstance(chord, DecoratedChord):
			spans.append(dataclasses.replace(chord.span, beats=duration))
		else:
			spans.append(ChordSpan(chord=chord, beats=duration))
		cursor += duration
		index += 1

	return Progression(spans = tuple(spans))
