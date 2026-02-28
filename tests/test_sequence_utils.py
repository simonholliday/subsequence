import random

import subsequence.sequence_utils


def test_sequence_to_indices_basic () -> None:

	"""Extract indices from a binary sequence with hits at known positions."""

	sequence = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]

	assert subsequence.sequence_utils.sequence_to_indices(sequence) == [0, 4, 8, 12]


def test_sequence_to_indices_empty () -> None:

	"""An all-zero sequence should return an empty list."""

	assert subsequence.sequence_utils.sequence_to_indices([0, 0, 0, 0]) == []


def test_sequence_to_indices_all_hits () -> None:

	"""An all-ones sequence should return every index."""

	assert subsequence.sequence_utils.sequence_to_indices([1, 1, 1]) == [0, 1, 2]


def test_roll_no_wraparound () -> None:

	"""Rolling indices that stay within bounds should shift correctly."""

	assert subsequence.sequence_utils.roll([0, 8], 4, 16) == [4, 12]


def test_roll_with_wraparound () -> None:

	"""Indices that exceed length should wrap to the beginning."""

	assert subsequence.sequence_utils.roll([12, 14], 4, 16) == [0, 2]


def test_roll_negative_shift () -> None:

	"""A negative shift should move indices backward with wraparound."""

	assert subsequence.sequence_utils.roll([4, 12], -4, 16) == [0, 8]


def test_roll_empty_list () -> None:

	"""Rolling an empty list should return an empty list."""

	assert subsequence.sequence_utils.roll([], 4, 16) == []


def test_roll_zero_shift () -> None:

	"""A zero shift should return the original indices."""

	assert subsequence.sequence_utils.roll([0, 4, 8, 12], 0, 16) == [0, 4, 8, 12]


def test_roll_full_cycle () -> None:

	"""Rolling by the full length should return the original indices."""

	assert subsequence.sequence_utils.roll([0, 4, 8, 12], 16, 16) == [0, 4, 8, 12]


# --- weighted_choice ---


def test_weighted_choice_basic () -> None:

	"""Should return one of the provided options."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.weighted_choice([("a", 1.0), ("b", 1.0)], rng)

	assert result in ("a", "b")


def test_weighted_choice_single_option () -> None:

	"""A single option should always be returned."""

	rng = random.Random(0)
	result = subsequence.sequence_utils.weighted_choice([("only", 1.0)], rng)

	assert result == "only"


def test_weighted_choice_respects_weights () -> None:

	"""Over many trials, heavy-weighted options should appear more often."""

	rng = random.Random(42)
	counts = {"heavy": 0, "light": 0}

	for _ in range(1000):
		result = subsequence.sequence_utils.weighted_choice([("heavy", 0.9), ("light", 0.1)], rng)
		counts[result] += 1

	assert counts["heavy"] > counts["light"]
	assert counts["heavy"] > 800


def test_weighted_choice_empty_raises () -> None:

	"""An empty options list should raise ValueError."""

	import pytest

	rng = random.Random(0)

	with pytest.raises(ValueError):
		subsequence.sequence_utils.weighted_choice([], rng)


def test_weighted_choice_deterministic () -> None:

	"""Same seed should produce the same result."""

	options = [("a", 0.3), ("b", 0.5), ("c", 0.2)]

	result_1 = subsequence.sequence_utils.weighted_choice(options, random.Random(99))
	result_2 = subsequence.sequence_utils.weighted_choice(options, random.Random(99))

	assert result_1 == result_2


# --- shuffled_choices ---


def test_shuffled_choices_correct_length () -> None:

	"""Should return exactly n items."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.shuffled_choices([1, 2, 3], 10, rng)

	assert len(result) == 10


def test_shuffled_choices_no_adjacent_repeats () -> None:

	"""No two adjacent items should be the same."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.shuffled_choices([1, 2, 3, 4], 100, rng)

	for i in range(len(result) - 1):
		assert result[i] != result[i + 1], f"Adjacent repeat at index {i}: {result[i]}"


def test_shuffled_choices_single_item_pool () -> None:

	"""A single-item pool should return that item repeated."""

	rng = random.Random(0)
	result = subsequence.sequence_utils.shuffled_choices(["x"], 5, rng)

	assert result == ["x", "x", "x", "x", "x"]


def test_shuffled_choices_n_less_than_pool () -> None:

	"""Requesting fewer items than pool size should work."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.shuffled_choices([10, 20, 30, 40], 2, rng)

	assert len(result) == 2
	assert all(item in [10, 20, 30, 40] for item in result)


def test_shuffled_choices_empty_pool_raises () -> None:

	"""An empty pool should raise ValueError."""

	import pytest

	rng = random.Random(0)

	with pytest.raises(ValueError):
		subsequence.sequence_utils.shuffled_choices([], 5, rng)


def test_shuffled_choices_zero_n () -> None:

	"""n=0 should return an empty list."""

	rng = random.Random(0)
	result = subsequence.sequence_utils.shuffled_choices([1, 2, 3], 0, rng)

	assert result == []


def test_shuffled_choices_deterministic () -> None:

	"""Same seed should produce the same sequence."""

	pool = [1, 2, 3, 4]

	result_1 = subsequence.sequence_utils.shuffled_choices(pool, 20, random.Random(42))
	result_2 = subsequence.sequence_utils.shuffled_choices(pool, 20, random.Random(42))

	assert result_1 == result_2


# --- random_walk ---


def test_random_walk_within_range () -> None:

	"""All values should be within [low, high]."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(100, low=30, high=90, step=10, rng=rng)

	assert all(30 <= v <= 90 for v in result)


def test_random_walk_correct_length () -> None:

	"""Should return exactly n values."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(16, low=0, high=127, step=5, rng=rng)

	assert len(result) == 16


def test_random_walk_step_zero_constant () -> None:

	"""A step of 0 should return all the same value (midpoint)."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(10, low=40, high=80, step=0, rng=rng)

	assert all(v == 60 for v in result)


def test_random_walk_adjacent_step_limit () -> None:

	"""Adjacent values should differ by at most the step size."""

	rng = random.Random(42)
	step = 5
	result = subsequence.sequence_utils.random_walk(50, low=0, high=127, step=step, rng=rng)

	for i in range(len(result) - 1):
		assert abs(result[i + 1] - result[i]) <= step


def test_random_walk_custom_start () -> None:

	"""First value should match the start parameter."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(5, low=0, high=100, step=10, rng=rng, start=20)

	assert result[0] == 20


def test_random_walk_start_clamped () -> None:

	"""Start value outside range should be clamped."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(5, low=50, high=100, step=10, rng=rng, start=10)

	assert result[0] == 50


def test_random_walk_empty () -> None:

	"""n=0 should return an empty list."""

	rng = random.Random(42)
	result = subsequence.sequence_utils.random_walk(0, low=0, high=100, step=10, rng=rng)

	assert result == []


def test_random_walk_deterministic () -> None:

	"""Same seed should produce the same walk."""

	result_1 = subsequence.sequence_utils.random_walk(20, low=0, high=100, step=10, rng=random.Random(42))
	result_2 = subsequence.sequence_utils.random_walk(20, low=0, high=100, step=10, rng=random.Random(42))

	assert result_1 == result_2


# --- probability_gate ---


def test_probability_gate_keep_all () -> None:

	"""Probability 1.0 should keep all hits."""

	rng = random.Random(42)
	seq = [1, 0, 1, 0, 1, 0, 1, 0]

	result = subsequence.sequence_utils.probability_gate(seq, 1.0, rng)

	assert result == seq


def test_probability_gate_remove_all () -> None:

	"""Probability 0.0 should remove all hits."""

	rng = random.Random(42)
	seq = [1, 1, 1, 1, 1, 1, 1, 1]

	result = subsequence.sequence_utils.probability_gate(seq, 0.0, rng)

	assert result == [0, 0, 0, 0, 0, 0, 0, 0]


def test_probability_gate_zeros_never_promoted () -> None:

	"""Zero steps should remain zero regardless of probability."""

	rng = random.Random(42)
	seq = [0, 0, 0, 0]

	result = subsequence.sequence_utils.probability_gate(seq, 1.0, rng)

	assert result == [0, 0, 0, 0]


def test_probability_gate_per_step_list () -> None:

	"""A per-step probability list should apply individual thresholds."""

	rng = random.Random(42)
	seq = [1, 1, 1, 1]
	probs = [1.0, 0.0, 1.0, 0.0]

	result = subsequence.sequence_utils.probability_gate(seq, probs, rng)

	assert result == [1, 0, 1, 0]


def test_probability_gate_partial () -> None:

	"""Intermediate probability should keep some hits but not all."""

	rng = random.Random(42)
	seq = [1] * 100

	result = subsequence.sequence_utils.probability_gate(seq, 0.5, rng)

	kept = sum(result)
	assert 0 < kept < 100


def test_probability_gate_deterministic () -> None:

	"""Same seed should produce the same gated sequence."""

	seq = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

	result_1 = subsequence.sequence_utils.probability_gate(seq, 0.6, random.Random(42))
	result_2 = subsequence.sequence_utils.probability_gate(seq, 0.6, random.Random(42))

	assert result_1 == result_2


# --- generate_bresenham_sequence_weighted ---

def test_bresenham_weighted_length_matches_steps () -> None:

	"""Output length should equal the requested step count."""

	for steps in [1, 8, 16, 32]:
		seq = subsequence.sequence_utils.generate_bresenham_sequence_weighted(steps, [0.3, 0.7])
		assert len(seq) == steps


def test_bresenham_weighted_equal_voices () -> None:

	"""Two equal-weight voices should each get exactly half the steps."""

	seq = subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [0.5, 0.5])
	assert seq.count(0) == 8
	assert seq.count(1) == 8


def test_bresenham_weighted_single_voice () -> None:

	"""A single voice should claim every step."""

	seq = subsequence.sequence_utils.generate_bresenham_sequence_weighted(8, [1.0])
	assert seq == [0] * 8


def test_bresenham_weighted_heavier_voice_gets_more_steps () -> None:

	"""The voice with double the weight should get roughly double the steps."""

	seq = subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [0.5, 0.25])
	assert seq.count(0) > seq.count(1)


def test_bresenham_weighted_three_voices_all_present () -> None:

	"""All three voices should appear when given non-trivial weights."""

	seq = subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [0.4, 0.3, 0.3])
	assert 0 in seq
	assert 1 in seq
	assert 2 in seq


def test_bresenham_weighted_deterministic () -> None:

	"""Same inputs should always produce the same sequence (no randomness)."""

	a = subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [0.3, 0.5, 0.2])
	b = subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [0.3, 0.5, 0.2])
	assert a == b


def test_bresenham_weighted_zero_steps_raises () -> None:

	"""Steps <= 0 should raise ValueError."""

	import pytest
	with pytest.raises(ValueError):
		subsequence.sequence_utils.generate_bresenham_sequence_weighted(0, [0.5])


def test_bresenham_weighted_empty_weights_raises () -> None:

	"""Empty weights list should raise ValueError."""

	import pytest
	with pytest.raises(ValueError):
		subsequence.sequence_utils.generate_bresenham_sequence_weighted(16, [])


# --- perlin_1d ---


def test_perlin_1d_range () -> None:

	"""Output should always be in [0.0, 1.0]."""

	for i in range(200):
		x = i * 0.13 - 5.0
		value = subsequence.sequence_utils.perlin_1d(x, seed=42)
		assert 0.0 <= value <= 1.0, f"perlin_1d({x}) = {value} out of range"


def test_perlin_1d_deterministic () -> None:

	"""Same x and seed should always produce the same result."""

	a = subsequence.sequence_utils.perlin_1d(3.14, seed=7)
	b = subsequence.sequence_utils.perlin_1d(3.14, seed=7)
	assert a == b


def test_perlin_1d_smooth () -> None:

	"""Adjacent samples should be close (no large jumps)."""

	step = 0.01
	prev = subsequence.sequence_utils.perlin_1d(0.0, seed=42)

	for i in range(1, 100):
		x = i * step
		curr = subsequence.sequence_utils.perlin_1d(x, seed=42)
		assert abs(curr - prev) < 0.15, f"Jump too large at x={x}: {prev} -> {curr}"
		prev = curr


def test_perlin_1d_different_seeds () -> None:

	"""Different seeds should produce different noise fields."""

	values_a = [subsequence.sequence_utils.perlin_1d(i * 0.1, seed=0) for i in range(20)]
	values_b = [subsequence.sequence_utils.perlin_1d(i * 0.1, seed=99) for i in range(20)]

	assert values_a != values_b


def test_perlin_1d_varies () -> None:

	"""Output should not be constant — it should vary over the range."""

	values = [subsequence.sequence_utils.perlin_1d(i * 0.3, seed=42) for i in range(50)]

	assert max(values) - min(values) > 0.1


# --- generate_cellular_automaton ---


def test_cellular_automaton_length () -> None:

	"""Output length should match the requested step count."""

	for steps in [8, 16, 32]:
		result = subsequence.sequence_utils.generate_cellular_automaton(steps, rule=30, generation=5)
		assert len(result) == steps


def test_cellular_automaton_binary () -> None:

	"""Output should contain only 0s and 1s."""

	result = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=10)
	assert all(v in (0, 1) for v in result)


def test_cellular_automaton_generation_zero () -> None:

	"""Generation 0 with default seed should have a single centre cell."""

	result = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=0)
	assert result[8] == 1
	assert sum(result) == 1


def test_cellular_automaton_evolves () -> None:

	"""Different generations should produce different patterns."""

	gen_0 = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=0)
	gen_5 = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=5)
	gen_10 = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=10)

	assert gen_0 != gen_5
	assert gen_5 != gen_10


def test_cellular_automaton_deterministic () -> None:

	"""Same parameters should always produce the same output."""

	a = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=7)
	b = subsequence.sequence_utils.generate_cellular_automaton(16, rule=30, generation=7)
	assert a == b


def test_cellular_automaton_rule_90_symmetry () -> None:

	"""Rule 90 from a single centre cell should produce symmetric patterns (odd grid)."""

	result = subsequence.sequence_utils.generate_cellular_automaton(17, rule=90, generation=3)
	assert result == list(reversed(result))


def test_cellular_automaton_empty () -> None:

	"""Steps <= 0 should return an empty list."""

	assert subsequence.sequence_utils.generate_cellular_automaton(0, rule=30, generation=5) == []


def test_cellular_automaton_custom_seed () -> None:

	"""A custom seed should set the initial state from its bit pattern."""

	# seed=5 = binary 101 → state[0]=1, state[1]=0, state[2]=1
	result = subsequence.sequence_utils.generate_cellular_automaton(8, rule=30, generation=0, seed=5)
	assert result[0] == 1
	assert result[1] == 0
	assert result[2] == 1
	assert sum(result) == 2


# --- logistic_map ---


def test_logistic_map_correct_length () -> None:

	"""Should return exactly the requested number of values."""

	result = subsequence.sequence_utils.logistic_map(r=3.5, steps=16)

	assert len(result) == 16


def test_logistic_map_zero_steps_returns_empty () -> None:

	"""steps <= 0 should return an empty list."""

	assert subsequence.sequence_utils.logistic_map(r=3.5, steps=0) == []


def test_logistic_map_deterministic () -> None:

	"""Same r and x0 should always produce the same sequence."""

	a = subsequence.sequence_utils.logistic_map(r=3.7, steps=32, x0=0.4)
	b = subsequence.sequence_utils.logistic_map(r=3.7, steps=32, x0=0.4)

	assert a == b


def test_logistic_map_stable_regime_converges () -> None:

	"""For r < 3.0, the sequence should converge toward a fixed point."""

	result = subsequence.sequence_utils.logistic_map(r=2.5, steps=100, x0=0.4)

	# After many iterations the last few values should be nearly identical.
	assert abs(result[-1] - result[-2]) < 1e-6


def test_logistic_map_periodic_regime () -> None:

	"""For r ≈ 3.2, the sequence should oscillate between two values."""

	result = subsequence.sequence_utils.logistic_map(r=3.2, steps=200, x0=0.5)

	# After settling, even-indexed and odd-indexed tail values should cluster.
	tail = result[150:]
	even = tail[0::2]
	odd = tail[1::2]

	# All even-indexed values should be close to each other (one attractor).
	assert max(even) - min(even) < 0.01

	# The two attractors should be clearly separated.
	assert abs(sum(even) / len(even) - sum(odd) / len(odd)) > 0.1


def test_logistic_map_chaos_regime_varies () -> None:

	"""For r > 3.57, successive values should not converge."""

	result = subsequence.sequence_utils.logistic_map(r=3.9, steps=32, x0=0.5)

	# In the chaotic regime the range of values should be wide.
	assert max(result) - min(result) > 0.5


def test_logistic_map_different_r_different_output () -> None:

	"""Different r values should produce different sequences."""

	a = subsequence.sequence_utils.logistic_map(r=3.2, steps=16, x0=0.5)
	b = subsequence.sequence_utils.logistic_map(r=3.8, steps=16, x0=0.5)

	assert a != b


def test_logistic_map_different_x0_different_output () -> None:

	"""Different starting values should produce different sequences."""

	a = subsequence.sequence_utils.logistic_map(r=3.7, steps=16, x0=0.4)
	b = subsequence.sequence_utils.logistic_map(r=3.7, steps=16, x0=0.7)

	assert a != b
