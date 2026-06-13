"""Persistent melodic context for NIR-guided single-note line generation.

Provides :class:`MelodicState`, a stateful object that tracks recent pitch
history across bar rebuilds and applies the Narmour Implication-Realization
(NIR) model to score candidate pitches.  Because pattern builders are
recreated fresh each cycle, this state must live at module level (the same
pattern as :class:`~subsequence.easing.EasedValue`) so melodic continuity
survives bar boundaries.

The NIR rules operate on **absolute MIDI pitches** (direct semitone
subtraction), not pitch-class modular arithmetic, so registral direction is
properly tracked across octaves: a leap from C4 (60) to G4 (67) is +7
upward, not an ambiguous -5.

Scoring follows the CHORAL separation: the **hard** constraint is structural
and singular (the pitch pool — candidates outside it never exist), while
everything *tasteful* is a **soft factor** in :attr:`MelodicState.factors` —
a pluggable list of multipliers (NIR expectation, chord-tone pull, range
gravity, pitch diversity, contour envelope, tessitura regression), every one
a dial and never a law.  Replace or extend the list to reshape the
generator's taste.
"""

import dataclasses
import random
import typing

import subsequence.chords
import subsequence.intervals


@dataclasses.dataclass(frozen=True)
class ScoringContext:

	"""Everything a scoring factor may read about one candidate.

	``beat``, ``position``, and ``contour_target`` are optional threading
	from the caller — ``None`` when the context does not apply (a factor
	that needs them returns 1.0 without them).

	Attributes:
		candidate: The candidate MIDI pitch.
		history: Recent chosen pitches, oldest first (capped at 4).
		chord_tone_pcs: Pitch classes of the current chord tones (empty
			set when no chord context).
		tonic_pc: The key's tonic pitch class (Rule C's landing point).
		low / high: The register bounds of the pitch pool.
		beat: The beat the note will sound on, within its pattern cycle.
		position: Normalised 0–1 position through a generated span.
		contour_target: Normalised 0–1 target height at *position* (the
			contour envelope's value).
	"""

	candidate: int
	history: typing.Tuple[int, ...]
	chord_tone_pcs: typing.FrozenSet[int]
	tonic_pc: int
	low: int
	high: int
	beat: typing.Optional[float] = None
	position: typing.Optional[float] = None
	contour_target: typing.Optional[float] = None


# A scoring factor: reads the state's dials and one candidate's context,
# returns a multiplier (1.0 = neutral; <1 damps; >1 boosts).
ScoringFactor = typing.Callable[["MelodicState", ScoringContext], float]


def nir_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Narmour expectation: reversal after leaps, continuation after steps,
	closure on the tonic, preference for proximity — scaled by ``nir_strength``."""

	if not ctx.history:
		return 1.0

	last_note = ctx.history[-1]

	target_diff = ctx.candidate - last_note
	target_interval = abs(target_diff)
	target_direction = 1 if target_diff > 0 else -1 if target_diff < 0 else 0

	boost = 0.0

	# Rules A & B require an Implication context (prev -> last -> candidate).
	if len(ctx.history) >= 2:
		prev_note = ctx.history[-2]

		prev_diff = last_note - prev_note
		prev_interval = abs(prev_diff)
		prev_direction = 1 if prev_diff > 0 else -1 if prev_diff < 0 else 0

		# Rule A: Reversal (gap fill) — after a large leap, expect direction change.
		if prev_interval > 4:
			if target_direction != prev_direction and target_direction != 0:
				boost += 0.5

			if target_interval < 4:
				boost += 0.3

		# Rule B: Process (continuation) — after a small step, expect more of the same.
		elif 0 < prev_interval < 3:
			if target_direction == prev_direction:
				boost += 0.4

			if abs(target_interval - prev_interval) <= 1:
				boost += 0.2

	# Rule C: Closure — the tonic is a cognitively stable landing point.
	if ctx.candidate % 12 == ctx.tonic_pc:
		boost += 0.2

	# Rule D: Proximity — smaller intervals are generally preferred.
	if 0 < target_interval <= 3:
		boost += 0.3

	return 1.0 + boost * state.nir_strength


def chord_tone_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Boost candidates whose pitch class belongs to the current chord."""

	if ctx.chord_tone_pcs and ctx.candidate % 12 in ctx.chord_tone_pcs:
		return 1.0 + state.chord_weight

	return 1.0


def range_gravity_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Penalise notes far from the centre of the register (quadratic)."""

	centre = (ctx.low + ctx.high) / 2.0
	half_range = max(1.0, (ctx.high - ctx.low) / 2.0)
	distance_ratio = abs(ctx.candidate - centre) / half_range

	return 1.0 - 0.3 * (distance_ratio ** 2)


def diversity_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Exponential penalty for recently-heard pitches."""

	recent_occurrences = sum(1 for h in ctx.history if h == ctx.candidate)

	return state.pitch_diversity ** recent_occurrences


def contour_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Pull candidates toward the contour envelope's target height.

	Active only when the caller threads ``position``/``contour_target``
	(the generate path); a melodic walk without an envelope is unshaped.
	"""

	if ctx.contour_target is None or ctx.high <= ctx.low:
		return 1.0

	height = (ctx.candidate - ctx.low) / (ctx.high - ctx.low)

	# Cubic falloff: strong enough to be heard as a shape, soft enough that
	# NIR/diversity still pick the path along it.
	return max(0.04, (1.0 - abs(height - ctx.contour_target)) ** 3)


def tessitura_factor (state: "MelodicState", ctx: ScoringContext) -> float:

	"""Regression toward the tessitura — von Hippel's reading of post-skip reversal.

	The further the line has strayed from the register's centre, the more
	candidates that move back toward it are boosted.  Off by default
	(``tessitura_strength=0``); the generate path turns it on, where it
	buys gap-fill and post-skip reversal without hard rules.
	"""

	if state.tessitura_strength <= 0 or not ctx.history:
		return 1.0

	centre = (ctx.low + ctx.high) / 2.0
	half_range = max(1.0, (ctx.high - ctx.low) / 2.0)
	displacement = (ctx.history[-1] - centre) / half_range

	if abs(displacement) < 1e-9:
		return 1.0

	moves_home = (ctx.candidate - ctx.history[-1]) * (centre - ctx.history[-1]) > 0

	if moves_home:
		return 1.0 + state.tessitura_strength * min(1.0, abs(displacement)) * 0.6

	return 1.0


DEFAULT_FACTORS: typing.Tuple[ScoringFactor, ...] = (
	nir_factor,
	chord_tone_factor,
	range_gravity_factor,
	diversity_factor,
	contour_factor,
	tessitura_factor,
)


class MelodicState:

	"""Persistent melodic context that applies NIR scoring to single-note lines."""


	def __init__ (
		self,
		key: typing.Optional[str] = None,
		mode: typing.Optional[str] = None,
		low: int = 48,
		high: int = 72,
		nir_strength: float = 0.5,
		chord_weight: float = 0.4,
		rest_probability: float = 0.0,
		pitch_diversity: float = 0.6,
		tessitura_strength: float = 0.0,
	) -> None:

		"""Initialise a melodic state for a given key, mode, and MIDI register.

		Parameters:
			key: Root note of the key (e.g. ``"C"``, ``"F#"``, ``"Bb"``).
			    When omitted, the state adopts the **composition's** key the
			    first time ``p.melody()`` uses it (falling back to ``"C"``).
			mode: Scale mode name.  Accepts any mode registered with
			      :func:`~subsequence.intervals.scale_pitch_classes` (e.g.
			      ``"ionian"``, ``"aeolian"``, ``"dorian"``).  When omitted,
			      adopts the composition's scale (falling back to ``"ionian"``).
			low: Lowest MIDI note (inclusive) in the pitch pool.
			high: Highest MIDI note (inclusive) in the pitch pool.
			nir_strength: 0.0–1.0.  Scales how strongly the NIR rules
			    influence candidate scores.  0.0 = uniform; 1.0 = full boost.
			chord_weight: 0.0–1.0.  Additive multiplier bonus for candidates
			    whose pitch class belongs to the current chord tones.
			rest_probability: 0.0–1.0.  Probability of producing a rest
			    (returning ``None``) at any given step.
			pitch_diversity: 0.0–1.0.  Exponential penalty per recent
			    repetition of the same pitch.  Lower values discourage
			    repetition more aggressively.
			tessitura_strength: 0.0–1.0.  Regression pull toward the centre
			    of the register after the line strays (off by default; the
			    generate path enables it).
		"""

		if nir_strength < 0 or nir_strength > 1:
			raise ValueError("NIR strength must be between 0 and 1")

		if rest_probability < 0 or rest_probability > 1:
			raise ValueError("Rest probability must be between 0 and 1")

		if pitch_diversity < 0 or pitch_diversity > 1:
			raise ValueError("Pitch diversity must be between 0 and 1")

		if chord_weight < 0:
			raise ValueError("Chord weight must be non-negative")

		if tessitura_strength < 0 or tessitura_strength > 1:
			raise ValueError("Tessitura strength must be between 0 and 1")

		if low >= high:
			raise ValueError("low must be below high")

		# None defers to the composition (configure_defaults); the fallbacks
		# keep a bare MelodicState() working standalone.
		self._explicit_key = key is not None
		self._explicit_mode = mode is not None
		self._configured = False
		self._explicit_pool = False

		self.key = key if key is not None else "C"
		self.mode = mode if mode is not None else "ionian"
		self.low = low
		self.high = high
		self.nir_strength = nir_strength
		self.chord_weight = chord_weight
		self.rest_probability = rest_probability
		self.pitch_diversity = pitch_diversity
		self.tessitura_strength = tessitura_strength

		# The soft side of the CHORAL separation — replace or extend freely.
		self.factors: typing.List[ScoringFactor] = list(DEFAULT_FACTORS)

		self._rebuild_pool()

		# History of last N absolute MIDI pitches (capped at 4, same as HarmonicState).
		self.history: typing.List[int] = []


	def _rebuild_pool (self) -> None:

		"""Derive the pitch pool (the one hard constraint) from key/mode/register."""

		self._tonic_pc: int = subsequence.chords.key_name_to_pc(self.key)

		self._pitch_pool: typing.List[int] = subsequence.intervals.scale_notes(
			self.key, self.mode, low=self.low, high=self.high
		)


	def configure_defaults (self, key: typing.Optional[str], mode: typing.Optional[str]) -> None:

		"""Adopt the surrounding key/scale where this state left them unset.

		Called by ``p.melody()`` every build.  It **tracks** the builder's
		current key/scale (which is the section's effective key under a form),
		so a state placed across sections follows each section's key — its
		melodic *history* is untouched, only the pitch pool and tonic move.
		An explicit constructor key/scale or an explicit pool always wins and
		is never overridden.
		"""

		if self._explicit_pool:
			return

		self._configured = True
		changed = False

		# Re-track on every call (not just the first): a persistent state used
		# across sections must follow the live key, or the first section to
		# place it would freeze the key forever.
		if not self._explicit_key and key is not None and key != self.key:
			self.key = key
			changed = True

		if not self._explicit_mode and mode is not None and mode != self.mode:
			self.mode = mode
			changed = True

		if changed:
			self._rebuild_pool()


	def set_pool (self, pitches: typing.Sequence[int]) -> None:

		"""Replace the pitch pool with explicit MIDI pitches — the experimental seam.

		Admits sieve output, non-octave organisations, or any hand-picked
		pool; key/mode no longer constrain candidates (the tonic pitch
		class, for Rule C, stays the key's).
		"""

		pool = sorted(int(p) for p in pitches)

		if not pool:
			raise ValueError("set_pool() needs at least one pitch")

		self._pitch_pool = pool
		self._explicit_pool = True
		self.low = pool[0]
		self.high = max(pool[-1], pool[0] + 1)


	def clone (self) -> "MelodicState":

		"""An independent copy — settings, factors, pool, and history.

		Value constructors (``Motif.generate``) copy the state they are
		given and walk the copy, so a module-level live state is never
		mutated by building a value.
		"""

		duplicate = MelodicState(
			key = self.key if self._explicit_key else None,
			mode = self.mode if self._explicit_mode else None,
			low = self.low,
			high = self.high,
			nir_strength = self.nir_strength,
			chord_weight = self.chord_weight,
			rest_probability = self.rest_probability,
			pitch_diversity = self.pitch_diversity,
			tessitura_strength = self.tessitura_strength,
		)

		duplicate.key = self.key
		duplicate.mode = self.mode
		duplicate._configured = self._configured
		duplicate._rebuild_pool()

		if self._explicit_pool:
			duplicate.set_pool(self._pitch_pool)

		duplicate.factors = list(self.factors)
		duplicate.history = list(self.history)

		return duplicate


	def choose_next (
		self,
		chord_tones: typing.Optional[typing.List[int]],
		rng: random.Random,
		beat: typing.Optional[float] = None,
		position: typing.Optional[float] = None,
		contour_target: typing.Optional[float] = None,
	) -> typing.Optional[int]:

		"""Score all pitch-pool candidates and return the chosen pitch, or None for a rest.

		``beat`` (the note's beat within its cycle), ``position`` (0–1
		through a generated span), and ``contour_target`` (the envelope's
		height there) thread caller context into the scoring factors.
		"""

		if self.rest_probability > 0.0 and rng.random() < self.rest_probability:
			return None

		if not self._pitch_pool:
			return None

		# Resolve chord tones to pitch classes for fast membership testing.
		chord_tone_pcs = {t % 12 for t in chord_tones} if chord_tones else set()

		scores = [
			self._score_candidate(candidate, chord_tone_pcs, beat=beat, position=position, contour_target=contour_target)
			for candidate in self._pitch_pool
		]

		# Weighted random choice: select using cumulative score as a probability weight.
		total = sum(scores)

		if total <= 0.0:
			chosen = rng.choice(self._pitch_pool)

		else:
			r = rng.uniform(0.0, total)
			cumulative = 0.0
			chosen = self._pitch_pool[-1]

			for pitch, score in zip(self._pitch_pool, scores):
				cumulative += score
				if r <= cumulative:
					chosen = pitch
					break

		self.record(chosen)

		return chosen


	def _score_candidate (
		self,
		candidate: int,
		chord_tone_pcs: typing.Set[int],
		beat: typing.Optional[float] = None,
		position: typing.Optional[float] = None,
		contour_target: typing.Optional[float] = None,
	) -> float:

		"""Score one candidate: the product of every factor in :attr:`factors`."""

		ctx = ScoringContext(
			candidate = candidate,
			history = tuple(self.history),
			chord_tone_pcs = frozenset(chord_tone_pcs),
			tonic_pc = self._tonic_pc,
			low = self.low,
			high = self.high,
			beat = beat,
			position = position,
			contour_target = contour_target,
		)

		score = 1.0

		for factor in self.factors:
			score *= factor(self, ctx)

		return max(0.0, score)

	def record (self, pitch: int) -> None:

		"""Append a pitch to the melodic history (capped at 4 entries).

		Public so pinned notes — chosen by fiat, not by the walk — still
		enter the NIR context.
		"""

		self.history.append(pitch)
		if len(self.history) > 4:
			self.history.pop(0)
