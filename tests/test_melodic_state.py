"""Tests for MelodicState — NIR-guided single-note melody generation.

Covers:
- Pitch pool construction (only in-scale tones within [low, high])
- choose_next() determinism, rest probability, empty-pool edge case
- History management (cap at 4, persists across calls)
- _score_candidate() NIR rules A/B/C/D
- Chord-tone boost
- Range gravity
- Pitch diversity penalty
- Full-range distribution (notes within bounds)
"""

import random

import pytest

import subsequence.melodic_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state (
	key: str = "C",
	mode: str = "ionian",
	low: int = 60,
	high: int = 72,
	nir_strength: float = 1.0,
	chord_weight: float = 0.0,
	rest_probability: float = 0.0,
	pitch_diversity: float = 1.0,
) -> subsequence.melodic_state.MelodicState:

	"""Create a MelodicState with sensible test defaults."""

	return subsequence.melodic_state.MelodicState(
		key=key,
		mode=mode,
		low=low,
		high=high,
		nir_strength=nir_strength,
		chord_weight=chord_weight,
		rest_probability=rest_probability,
		pitch_diversity=pitch_diversity,
	)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestMelodicStateInit:

	def test_pitch_pool_in_scale (self) -> None:
		"""Pitch pool should contain only scale tones within [low, high]."""
		ms = _state(key="C", mode="ionian", low=60, high=72)

		# C major pitch classes: 0, 2, 4, 5, 7, 9, 11
		c_major_pcs = {0, 2, 4, 5, 7, 9, 11}

		for p in ms._pitch_pool:
			assert 60 <= p <= 72
			assert p % 12 in c_major_pcs

	def test_pitch_pool_respects_bounds (self) -> None:
		"""No pitch in the pool should fall outside [low, high]."""
		ms = _state(low=48, high=60)

		for p in ms._pitch_pool:
			assert 48 <= p <= 60

	def test_history_starts_empty (self) -> None:
		"""History should be empty on construction."""
		ms = _state()

		assert ms.history == []

	def test_invalid_key_raises (self) -> None:
		"""Unknown key name should raise ValueError."""
		with pytest.raises(ValueError):
			subsequence.melodic_state.MelodicState(key="X")

	def test_invalid_mode_raises (self) -> None:
		"""Unknown mode name should raise ValueError."""
		with pytest.raises(ValueError):
			subsequence.melodic_state.MelodicState(mode="not_a_mode")


# ---------------------------------------------------------------------------
# choose_next — basic behaviour
# ---------------------------------------------------------------------------

class TestChooseNext:

	def test_returns_pitch_in_pool (self) -> None:
		"""Chosen pitch must be a member of the pitch pool."""
		ms = _state()
		rng = random.Random(42)

		for _ in range(20):
			pitch = ms.choose_next(chord_tones=None, rng=rng)
			assert pitch in ms._pitch_pool

	def test_pitch_in_low_high_range (self) -> None:
		"""Chosen pitch must be within [low, high]."""
		ms = _state(low=60, high=72)
		rng = random.Random(99)

		for _ in range(20):
			pitch = ms.choose_next(chord_tones=None, rng=rng)
			assert 60 <= pitch <= 72

	def test_rest_probability_zero_never_rests (self) -> None:
		"""With rest_probability=0.0, choose_next should never return None."""
		ms = _state(rest_probability=0.0)
		rng = random.Random(0)

		results = [ms.choose_next(chord_tones=None, rng=rng) for _ in range(50)]
		assert None not in results

	def test_rest_probability_one_always_rests (self) -> None:
		"""With rest_probability=1.0, choose_next should always return None."""
		ms = _state(rest_probability=1.0)
		rng = random.Random(0)

		results = [ms.choose_next(chord_tones=None, rng=rng) for _ in range(20)]
		assert all(r is None for r in results)

	def test_rest_probability_partial (self) -> None:
		"""With rest_probability=0.5, some but not all calls should return None."""
		ms = _state(rest_probability=0.5)
		rng = random.Random(7)

		results = [ms.choose_next(chord_tones=None, rng=rng) for _ in range(100)]
		rests = sum(1 for r in results if r is None)
		notes = sum(1 for r in results if r is not None)

		assert rests > 0
		assert notes > 0

	def test_deterministic_with_same_seed (self) -> None:
		"""Same seed should produce the same sequence."""
		def _run (seed: int) -> list:
			ms = _state()
			rng = random.Random(seed)
			return [ms.choose_next(chord_tones=None, rng=rng) for _ in range(10)]

		assert _run(42) == _run(42)
		assert _run(42) != _run(99)

	def test_history_grows_and_caps_at_four (self) -> None:
		"""History should grow up to 4 entries then stay at 4."""
		ms = _state(rest_probability=0.0)
		rng = random.Random(0)

		for i in range(1, 7):
			ms.choose_next(chord_tones=None, rng=rng)
			assert len(ms.history) == min(i, 4)

	def test_history_updates_with_chosen_pitch (self) -> None:
		"""History entries should equal the pitches returned by choose_next."""
		ms = _state(rest_probability=0.0)
		rng = random.Random(0)

		pitches = [ms.choose_next(chord_tones=None, rng=rng) for _ in range(4)]
		assert ms.history == pitches

	def test_rests_do_not_update_history (self) -> None:
		"""A rest (None) must not be appended to the history."""
		ms = _state(rest_probability=1.0)
		rng = random.Random(0)

		for _ in range(5):
			ms.choose_next(chord_tones=None, rng=rng)

		assert ms.history == []


# ---------------------------------------------------------------------------
# _score_candidate — NIR rules
# ---------------------------------------------------------------------------

class TestNIRScoring:

	def test_rule_a_reversal_after_large_leap (self) -> None:
		"""After a large upward leap (>4 st), a downward step should score higher than upward continuation."""
		ms = _state(nir_strength=1.0)

		# Implication: C4 (60) -> A4 (69) — leap of +9 semitones upward
		ms.history = [60, 69]

		# Reversal candidate: steps back down to G4 (67) — direction reversal, small interval
		reversal = 67  # 69 -> 67: -2, reversed direction, small

		# Continuation candidate: B4 (71) — same upward direction
		continuation = 71  # 69 -> 71: +2, same direction

		score_reversal = ms._score_candidate(reversal, set())
		score_continuation = ms._score_candidate(continuation, set())

		assert score_reversal > score_continuation

	def test_rule_b_process_after_small_step (self) -> None:
		"""After a small step, continuation in the same direction should score higher than reversal."""
		ms = _state(nir_strength=1.0)

		# Implication: C4 (60) -> D4 (62) — step of +2 semitones upward
		ms.history = [60, 62]

		# Continuation: E4 (64) — same upward direction, similar size
		continuation = 64  # 62 -> 64: +2

		# Reversal: Bb3 (58) — large downward jump
		reversal = 58  # 62 -> 58: -4

		score_continuation = ms._score_candidate(continuation, set())
		score_reversal = ms._score_candidate(reversal, set())

		assert score_continuation > score_reversal

	def test_rule_c_tonic_closure_boost (self) -> None:
		"""The tonic pitch class should receive a closure boost over a non-tonic at same interval."""
		# Use a wide range [48, 84] so range gravity does not dominate: centre is 66.
		# C4 (60) is 6 from centre; E4 (64) is 2 from centre — but C4 gets +0.2 tonic boost
		# which outweighs the small extra range penalty at nir_strength=1.0.
		ms = _state(key="C", mode="ionian", nir_strength=1.0, low=48, high=84)

		# One note in history to trigger Rule C (no Rules A/B with one item)
		ms.history = [62]  # D4

		# C4 (60) is the tonic — should get closure boost
		tonic_c = 60  # D -> C: -2, tonic

		# E4 (64) is non-tonic at same interval
		non_tonic_e = 64  # D -> E: +2, non-tonic

		score_tonic = ms._score_candidate(tonic_c, set())
		score_non_tonic = ms._score_candidate(non_tonic_e, set())

		assert score_tonic > score_non_tonic

	def test_rule_d_proximity_boost (self) -> None:
		"""A close interval (<=3 st) should score higher than a leap from the same last note."""
		ms = _state(nir_strength=1.0)

		# One note in history
		ms.history = [60]  # C4

		# D4 (62) — interval 2, within proximity range
		close = 62

		# A4 (69) — interval 9, outside proximity range
		far = 69

		score_close = ms._score_candidate(close, set())
		score_far = ms._score_candidate(far, set())

		assert score_close > score_far

	def test_nir_strength_zero_no_boost (self) -> None:
		"""With nir_strength=0.0, a candidate at the range centre should score exactly 1.0."""
		# Range [60, 84]: centre = 72.0 exactly, so range_factor = 1.0 for C5 (72).
		# History [60, 69] creates a large leap that would normally trigger Rule A,
		# but nir_strength=0 cancels all NIR boosts.  Diversity is also 1.0 (no history match).
		ms = _state(key="C", mode="ionian", nir_strength=0.0, low=60, high=84, pitch_diversity=1.0)
		ms.history = [60, 69]

		# C5 (72) is the range centre and the tonic — any NIR or closure boost would be cancelled.
		score = ms._score_candidate(72, set())

		assert score == pytest.approx(1.0)

	def test_no_history_returns_valid_score (self) -> None:
		"""With empty history, all candidates should receive a valid positive score."""
		ms = _state()

		for p in ms._pitch_pool:
			score = ms._score_candidate(p, set())
			assert score >= 0.0


# ---------------------------------------------------------------------------
# _score_candidate — chord tone boost and other factors
# ---------------------------------------------------------------------------

class TestChordToneBoost:

	def test_chord_tone_scored_higher (self) -> None:
		"""A chord tone should score higher than a non-chord-tone at equal NIR distance."""
		ms = _state(key="C", mode="ionian", chord_weight=0.5, nir_strength=0.0)

		# D4 (62) is a chord tone (in C major this is the 2nd — but we treat it as an arbitrary chord tone)
		chord_tone = 62
		non_chord = 64  # E4

		# Both are in C major scale; D is chord tone, E is not in this call
		score_chord = ms._score_candidate(chord_tone, {62 % 12})
		score_non_chord = ms._score_candidate(non_chord, {62 % 12})

		assert score_chord > score_non_chord

	def test_chord_weight_zero_no_boost (self) -> None:
		"""With chord_weight=0.0, chord tones should not receive any bonus."""
		ms = _state(chord_weight=0.0, nir_strength=0.0)

		p = ms._pitch_pool[0]

		score_with = ms._score_candidate(p, {p % 12})
		score_without = ms._score_candidate(p, set())

		assert score_with == pytest.approx(score_without)


class TestPitchDiversity:

	def test_repeated_pitch_penalised (self) -> None:
		"""A pitch that appears in history should score lower than one that does not."""
		ms = _state(pitch_diversity=0.3, nir_strength=0.0, chord_weight=0.0)

		# Load history with the first pool pitch
		repeated = ms._pitch_pool[0]
		fresh = ms._pitch_pool[-1]
		ms.history = [repeated]

		score_repeated = ms._score_candidate(repeated, set())
		score_fresh = ms._score_candidate(fresh, set())

		assert score_repeated < score_fresh

	def test_diversity_one_no_penalty (self) -> None:
		"""With pitch_diversity=1.0, no penalty is applied for repeated pitches."""
		ms = _state(pitch_diversity=1.0, nir_strength=0.0, chord_weight=0.0)

		p = ms._pitch_pool[0]
		ms.history = [p, p, p, p]

		score_with_history = ms._score_candidate(p, set())

		# Fresh state — no history
		ms2 = _state(pitch_diversity=1.0, nir_strength=0.0, chord_weight=0.0)
		score_no_history = ms2._score_candidate(p, set())

		assert score_with_history == pytest.approx(score_no_history, rel=0.01)


class TestRangeGravity:

	def test_edge_pitch_penalised_vs_centre (self) -> None:
		"""A pitch at the edge of the range should score lower than one near the centre."""
		# C ionian over [60, 84]: centre = 72 = C5, which is in the scale.
		# C4 (60) is at the low edge (distance 12 from centre, half_range=12 → penalty 0.3).
		ms = _state(key="C", mode="ionian", low=60, high=84, nir_strength=0.0, chord_weight=0.0, pitch_diversity=1.0)

		# C5 (72) is the exact centre — no range penalty.
		centre_pitch = 72

		# C4 (60) is the bottom edge — maximum range penalty.
		edge_pitch = 60

		score_centre = ms._score_candidate(centre_pitch, set())
		score_edge = ms._score_candidate(edge_pitch, set())

		assert score_centre > score_edge
