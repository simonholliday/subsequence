import dataclasses
import random
import typing

import subsequence.chords
import subsequence.harmonic_rhythm
import subsequence.harmonic_state


# A progression source is either a built-in chord-graph style name (generated)
# or an explicit, ordered list of chords — given as Chord objects or names ("Cm7").
ProgressionSource = typing.Union[str, typing.Sequence[typing.Union[subsequence.chords.Chord, str]]]

# A harmonic-rhythm spec is a single length (static), a list of lengths (a shaped
# rhythm, cycled per chord), or a between(...) range (bounded, optionally quantised).
HarmonicRhythmSpec = typing.Union[int, float, typing.List[float], subsequence.harmonic_rhythm.HarmonicRhythm]

# Voicing density: a fixed number of voices, or a (low, high) random range per chord.
VoicingSpec = typing.Union[int, typing.Tuple[int, int]]


class ChordEvent(typing.NamedTuple):

	"""One chord on a realised timeline: which chord, when it starts, and how long
	it lasts (in beats from the start of the part).

	A ``NamedTuple``, so it unpacks positionally as ``(chord, start, length)`` — the
	idiom for looping a progression — while also offering ``.chord`` / ``.start`` /
	``.length`` attribute access.
	"""

	chord: subsequence.chords.Chord
	start: float
	length: float


@dataclasses.dataclass(frozen=True)
class ChordTimeline:

	"""A chord progression laid out in time — an iterable of :class:`ChordEvent`.

	Returned by :meth:`subsequence.PatternBuilder.progression` (to loop over) and by
	:meth:`subsequence.Composition.chords` (to inspect).  Iterate it to place the
	chords yourself::

		for chord, start, length in timeline:
			p.strum(chord, root=48, beat=start, duration=length - 0.25)

	or ``print(timeline)`` for a readable summary / read the ``events`` tuple.
	"""

	events: typing.Tuple[ChordEvent, ...]
	length: float

	def __iter__ (self) -> typing.Iterator[ChordEvent]:
		return iter(self.events)

	def __len__ (self) -> int:
		return len(self.events)

	def describe (self) -> str:

		"""A readable, one-chord-per-line summary of the timeline."""

		lines = [f"ChordTimeline — {len(self.events)} chords over {self.length:g} beats"]
		for event in self.events:
			lines.append(
				f"  {event.start:6.2f} … {event.start + event.length:6.2f}   "
				f"{event.chord.name():<8} ({event.length:g} beats)"
			)
		return "\n".join(lines)

	def __str__ (self) -> str:
		return self.describe()


def _chord_source (source: ProgressionSource, key: typing.Optional[str], rng: random.Random) -> typing.Iterator[subsequence.chords.Chord]:

	"""Yield chords indefinitely — generated from a graph style, or cycled from a list."""

	if isinstance(source, str):
		if not key:
			raise ValueError(f"progression style {source!r} needs a key — pass key= or set the Composition key")
		state = subsequence.harmonic_state.HarmonicState(key_name=key, graph_style=source, rng=rng)
		yield state.current_chord
		while True:
			yield state.step()
	else:
		chords = [subsequence.chords.parse_chord(item) if isinstance(item, str) else item for item in source]
		if not chords:
			raise ValueError("progression list is empty — pass at least one chord")
		index = 0
		while True:
			yield chords[index % len(chords)]
			index += 1


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
) -> ChordTimeline:

	"""Lay a progression out across *length* beats and return a frozen timeline.

	Walks the chord source, giving each chord a harmonic-rhythm length, until the
	part is full.  The final chord is trimmed so the timeline ends exactly on
	*length* and therefore loops cleanly.  Voicing and articulation are not decided
	here — they belong to whatever places the chords (the verb you call in the loop,
	or :meth:`Composition.chords`).
	"""

	if length <= 0:
		raise ValueError(f"progression length ({length:g}) must be positive")

	stream = _chord_source(source, key, rng)
	events: typing.List[ChordEvent] = []
	cursor = 0.0
	index = 0

	while cursor < length - 1e-9:
		chord = next(stream)
		duration = _resolve_length(harmonic_rhythm, index, rng)
		if duration <= 0:
			raise ValueError(f"harmonic_rhythm produced a non-positive length ({duration:g}) — lengths are in beats and must be > 0")
		duration = min(duration, length - cursor)
		events.append(ChordEvent(chord=chord, start=cursor, length=duration))
		cursor += duration
		index += 1

	return ChordTimeline(events=tuple(events), length=float(length))
