import random

import subsequence.midi_utils
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


# --- generate_cellular_automaton_1d ---


def test_cellular_automaton_length () -> None:

	"""Output length should match the requested step count."""

	for steps in [8, 16, 32]:
		result = subsequence.sequence_utils.generate_cellular_automaton_1d(steps, rule=30, generation=5)
		assert len(result) == steps


def test_cellular_automaton_binary () -> None:

	"""Output should contain only 0s and 1s."""

	result = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=10)
	assert all(v in (0, 1) for v in result)


def test_cellular_automaton_generation_zero () -> None:

	"""Generation 0 with default seed should have a single centre cell."""

	result = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=0)
	assert result[8] == 1
	assert sum(result) == 1


def test_cellular_automaton_evolves () -> None:

	"""Different generations should produce different patterns."""

	gen_0 = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=0)
	gen_5 = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=5)
	gen_10 = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=10)

	assert gen_0 != gen_5
	assert gen_5 != gen_10


def test_cellular_automaton_deterministic () -> None:

	"""Same parameters should always produce the same output."""

	a = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=7)
	b = subsequence.sequence_utils.generate_cellular_automaton_1d(16, rule=30, generation=7)
	assert a == b


def test_cellular_automaton_rule_90_symmetry () -> None:

	"""Rule 90 from a single centre cell should produce symmetric patterns (odd grid)."""

	result = subsequence.sequence_utils.generate_cellular_automaton_1d(17, rule=90, generation=3)
	assert result == list(reversed(result))


def test_cellular_automaton_empty () -> None:

	"""Steps <= 0 should return an empty list."""

	assert subsequence.sequence_utils.generate_cellular_automaton_1d(0, rule=30, generation=5) == []


def test_cellular_automaton_custom_seed () -> None:

	"""A custom seed should set the initial state from its bit pattern."""

	# seed=5 = binary 101 → state[0]=1, state[1]=0, state[2]=1
	result = subsequence.sequence_utils.generate_cellular_automaton_1d(8, rule=30, generation=0, seed=5)
	assert result[0] == 1
	assert result[1] == 0
	assert result[2] == 1
	assert sum(result) == 2


# --- _parse_life_rule ---


def test_parse_life_rule_conway () -> None:

	"""B3/S23 (Conway's Life) should parse to correct birth and survival sets."""

	birth, survival = subsequence.sequence_utils._parse_life_rule("B3/S23")
	assert birth == {3}
	assert survival == {2, 3}


def test_parse_life_rule_morley () -> None:

	"""B368/S245 (Morley) should parse to correct birth and survival sets."""

	birth, survival = subsequence.sequence_utils._parse_life_rule("B368/S245")
	assert birth == {3, 6, 8}
	assert survival == {2, 4, 5}


def test_parse_life_rule_case_insensitive () -> None:

	"""Rule parsing should be case-insensitive."""

	birth, survival = subsequence.sequence_utils._parse_life_rule("b3/s23")
	assert birth == {3}
	assert survival == {2, 3}


def test_parse_life_rule_empty_sets () -> None:

	"""B/S should produce empty birth and survival sets."""

	birth, survival = subsequence.sequence_utils._parse_life_rule("B/S")
	assert birth == set()
	assert survival == set()


def test_parse_life_rule_invalid_format () -> None:

	"""Malformed rule strings should raise ValueError."""

	import pytest

	with pytest.raises(ValueError):
		subsequence.sequence_utils._parse_life_rule("30")

	with pytest.raises(ValueError):
		subsequence.sequence_utils._parse_life_rule("S23/B3")


# --- generate_cellular_automaton_2d ---


def test_2d_ca_dimensions () -> None:

	"""Output grid should be exactly rows × cols."""

	grid = subsequence.sequence_utils.generate_cellular_automaton_2d(rows=4, cols=16)
	assert len(grid) == 4
	assert all(len(row) == 16 for row in grid)


def test_2d_ca_binary_values () -> None:

	"""All grid cells should be 0 or 1."""

	grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=16, rule="B3/S23", generation=5, seed=42
	)
	assert all(v in (0, 1) for row in grid for v in row)


def test_2d_ca_deterministic () -> None:

	"""Same parameters should always produce the same grid."""

	a = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=16, rule="B368/S245", generation=10, seed=99
	)
	b = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=16, rule="B368/S245", generation=10, seed=99
	)
	assert a == b


def test_2d_ca_seed_centre () -> None:

	"""seed=1 with generation=0 should place a single live cell at centre."""

	grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=8, generation=0, seed=1
	)
	total = sum(v for row in grid for v in row)
	assert total == 1
	assert grid[4 // 2][8 // 2] == 1


def test_2d_ca_seed_random () -> None:

	"""Integer seed != 1 should produce a roughly density-fraction fill."""

	grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=10, cols=20, generation=0, seed=42, density=0.5
	)
	total = sum(v for row in grid for v in row)
	# Expect between 20% and 80% of 200 cells alive (very loose check)
	assert 40 <= total <= 160


def test_2d_ca_seed_explicit () -> None:

	"""Explicit list seed should be used as the starting grid unchanged."""

	initial = [[1, 0, 0, 1], [0, 1, 1, 0]]
	grid = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=2, cols=4, generation=0, seed=initial
	)
	assert grid == initial


def test_2d_ca_generation_zero_unchanged () -> None:

	"""generation=0 should return the seed state without any evolution."""

	seed_grid = [[1, 0, 1, 0], [0, 0, 1, 1], [1, 1, 0, 0], [0, 1, 0, 1]]
	result = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=4, generation=0, seed=seed_grid
	)
	assert result == seed_grid


def test_2d_ca_evolves_from_seed () -> None:

	"""Grid should change after one or more generations."""

	grid_gen0 = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=6, cols=16, rule="B368/S245", generation=0, seed=42, density=0.4
	)
	grid_gen5 = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=6, cols=16, rule="B368/S245", generation=5, seed=42, density=0.4
	)
	assert grid_gen0 != grid_gen5


def test_2d_ca_conway_blinker () -> None:

	"""Conway blinker (period-2 oscillator) should alternate between horizontal and vertical."""

	# Horizontal blinker at centre of a 5×5 grid: row 2, cols 1–3 live.
	horizontal = [
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
		[0, 1, 1, 1, 0],
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
	]
	# After 1 generation it becomes vertical: col 2, rows 1–3 live.
	expected_vertical = [
		[0, 0, 0, 0, 0],
		[0, 0, 1, 0, 0],
		[0, 0, 1, 0, 0],
		[0, 0, 1, 0, 0],
		[0, 0, 0, 0, 0],
	]
	result = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=5, cols=5, rule="B3/S23", generation=1, seed=horizontal
	)
	assert result == expected_vertical


def test_2d_ca_toroidal_wrapping () -> None:

	"""Cells at the edge should wrap to the opposite side."""

	# Live cell at top-left corner: its neighbours wrap around the edges.
	corner = [[1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
	# Just verify no index error and grid shape is intact.
	result = subsequence.sequence_utils.generate_cellular_automaton_2d(
		rows=4, cols=4, rule="B3/S23", generation=2, seed=corner
	)
	assert len(result) == 4
	assert all(len(row) == 4 for row in result)


def test_2d_ca_invalid_rule () -> None:

	"""An invalid rule string should raise ValueError."""

	import pytest

	with pytest.raises(ValueError):
		subsequence.sequence_utils.generate_cellular_automaton_2d(
			rows=4, cols=8, rule="invalid"
		)


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


# --- pink_noise ---


def test_pink_noise_correct_length () -> None:

	"""Output length should match the requested step count."""

	assert len(subsequence.sequence_utils.pink_noise(16)) == 16
	assert len(subsequence.sequence_utils.pink_noise(100)) == 100


def test_pink_noise_zero_steps_returns_empty () -> None:

	"""steps=0 should return an empty list."""

	assert subsequence.sequence_utils.pink_noise(0) == []


def test_pink_noise_range () -> None:

	"""All output values should be in [0.0, 1.0]."""

	result = subsequence.sequence_utils.pink_noise(1000, seed=7)
	assert all(0.0 <= v <= 1.0 for v in result)


def test_pink_noise_deterministic () -> None:

	"""Same seed should always produce the same sequence."""

	a = subsequence.sequence_utils.pink_noise(64, seed=42)
	b = subsequence.sequence_utils.pink_noise(64, seed=42)
	assert a == b


def test_pink_noise_different_seeds () -> None:

	"""Different seeds should produce different sequences."""

	a = subsequence.sequence_utils.pink_noise(64, seed=0)
	b = subsequence.sequence_utils.pink_noise(64, seed=99)
	assert a != b


def test_pink_noise_varies () -> None:

	"""Output should not be constant."""

	result = subsequence.sequence_utils.pink_noise(100, seed=1)
	assert max(result) - min(result) > 0.1


def test_pink_noise_spectral_character () -> None:

	"""Adjacent samples should be more correlated than white noise (sources=1)."""

	n = 500
	pink = subsequence.sequence_utils.pink_noise(n, sources=16, seed=5)
	white = subsequence.sequence_utils.pink_noise(n, sources=1, seed=5)

	def mean_consecutive_diff (seq: list) -> float:
		return sum(abs(seq[i + 1] - seq[i]) for i in range(len(seq) - 1)) / (len(seq) - 1)

	assert mean_consecutive_diff(pink) < mean_consecutive_diff(white)


# --- lsystem_expand ---


def test_lsystem_expand_zero_generations () -> None:

	"""generations=0 should return the axiom unchanged."""

	assert subsequence.sequence_utils.lsystem_expand("ABC", {"A": "AB"}, 0) == "ABC"


def test_lsystem_expand_deterministic_single_generation () -> None:

	"""One generation of Fibonacci rules should produce the expected string."""

	result = subsequence.sequence_utils.lsystem_expand(
		axiom="A", rules={"A": "AB", "B": "A"}, generations=1
	)
	assert result == "AB"


def test_lsystem_expand_fibonacci_lengths () -> None:

	"""Fibonacci L-system string lengths should follow the Fibonacci sequence."""

	rules = {"A": "AB", "B": "A"}
	expected_lengths = [1, 2, 3, 5, 8, 13, 21]

	for gen, expected_len in enumerate(expected_lengths):
		result = subsequence.sequence_utils.lsystem_expand("A", rules, gen)
		assert len(result) == expected_len, f"generation {gen}: expected length {expected_len}, got {len(result)}"


def test_lsystem_expand_fibonacci_known_strings () -> None:

	"""Fibonacci L-system should produce known strings for generations 0-4."""

	rules = {"A": "AB", "B": "A"}
	expected = ["A", "AB", "ABA", "ABAAB", "ABAABABA"]

	for gen, expected_str in enumerate(expected):
		assert subsequence.sequence_utils.lsystem_expand("A", rules, gen) == expected_str


def test_lsystem_expand_identity_passthrough () -> None:

	"""Characters not in rules should pass through unchanged."""

	result = subsequence.sequence_utils.lsystem_expand(
		axiom="AXB", rules={"A": "AB", "B": "A"}, generations=1
	)
	assert result == "ABXA"


def test_lsystem_expand_empty_axiom () -> None:

	"""An empty axiom should return an empty string."""

	assert subsequence.sequence_utils.lsystem_expand("", {"A": "AB"}, 5) == ""


def test_lsystem_expand_empty_rules () -> None:

	"""Empty rules should leave the string unchanged at any generation."""

	assert subsequence.sequence_utils.lsystem_expand("ABC", {}, 5) == "ABC"


def test_lsystem_expand_stochastic_deterministic () -> None:

	"""Same rng seed should produce the same stochastic expansion."""

	rules: dict = {"A": [("AB", 3), ("BA", 1)], "B": "A"}
	rng_a = random.Random(42)
	rng_b = random.Random(42)
	a = subsequence.sequence_utils.lsystem_expand("A", rules, 4, rng=rng_a)
	b = subsequence.sequence_utils.lsystem_expand("A", rules, 4, rng=rng_b)
	assert a == b


def test_lsystem_expand_stochastic_respects_weights () -> None:

	"""The higher-weight production should be chosen most often."""

	import pytest

	rules: dict = {"A": [("X", 9), ("Y", 1)]}
	counts: dict = {"X": 0, "Y": 0}

	for i in range(200):
		result = subsequence.sequence_utils.lsystem_expand(
			"A", rules, 1, rng=random.Random(i)
		)
		counts[result] = counts.get(result, 0) + 1

	assert counts["X"] > counts["Y"] * 5


def test_lsystem_expand_stochastic_no_rng_raises () -> None:

	"""Stochastic rules without rng should raise ValueError."""

	import pytest

	rules: dict = {"A": [("AB", 1), ("BA", 1)]}
	with pytest.raises(ValueError):
		subsequence.sequence_utils.lsystem_expand("A", rules, 3)


# --- perlin_1d_sequence ---


def test_perlin_1d_sequence_length () -> None:

	"""Should return exactly count values."""

	result = subsequence.sequence_utils.perlin_1d_sequence(start=0.0, step=0.1, count=16, seed=0)

	assert len(result) == 16


def test_perlin_1d_sequence_values_in_range () -> None:

	"""All values should be in [0.0, 1.0]."""

	result = subsequence.sequence_utils.perlin_1d_sequence(start=0.0, step=0.1, count=32, seed=42)

	assert all(0.0 <= v <= 1.0 for v in result)


def test_perlin_1d_sequence_matches_scalar () -> None:

	"""Each value should match the equivalent perlin_1d call."""

	start, step, count, seed = 1.5, 0.07, 8, 10

	seq = subsequence.sequence_utils.perlin_1d_sequence(start, step, count, seed)
	scalar = [subsequence.sequence_utils.perlin_1d(start + i * step, seed) for i in range(count)]

	assert seq == scalar


def test_perlin_1d_sequence_zero_count () -> None:

	"""count=0 should return an empty list."""

	assert subsequence.sequence_utils.perlin_1d_sequence(0.0, 0.1, 0) == []


# --- perlin_2d_grid ---


def test_perlin_2d_grid_shape () -> None:

	"""Should return y_count rows each of length x_count."""

	grid = subsequence.sequence_utils.perlin_2d_grid(0.0, 0.0, 0.1, 0.1, x_count=4, y_count=3)

	assert len(grid) == 3
	assert all(len(row) == 4 for row in grid)


def test_perlin_2d_grid_values_in_range () -> None:

	"""All values should be in [0.0, 1.0]."""

	grid = subsequence.sequence_utils.perlin_2d_grid(0.0, 0.0, 0.1, 0.25, x_count=8, y_count=4, seed=5)

	assert all(0.0 <= v <= 1.0 for row in grid for v in row)


def test_perlin_2d_grid_matches_scalar () -> None:

	"""Each value should match the equivalent perlin_2d call."""

	x_start, y_start, x_step, y_step = 0.5, 0.0, 0.1, 0.25
	x_count, y_count, seed = 4, 3, 7

	grid = subsequence.sequence_utils.perlin_2d_grid(x_start, y_start, x_step, y_step, x_count, y_count, seed)

	for yi in range(y_count):
		for xi in range(x_count):
			expected = subsequence.sequence_utils.perlin_2d(x_start + xi * x_step, y_start + yi * y_step, seed)
			assert grid[yi][xi] == expected


# --- bank_select ---


def test_bank_select_zero () -> None:

	"""Bank 0 → MSB 0, LSB 0."""

	assert subsequence.midi_utils.bank_select(0) == (0, 0)


def test_bank_select_lsb_only () -> None:

	"""Banks 1–127 fit in LSB alone (MSB stays 0)."""

	assert subsequence.midi_utils.bank_select(1) == (0, 1)
	assert subsequence.midi_utils.bank_select(127) == (0, 127)


def test_bank_select_msb_boundary () -> None:

	"""Bank 128 is the first bank requiring MSB=1."""

	assert subsequence.midi_utils.bank_select(128) == (1, 0)


def test_bank_select_mixed () -> None:

	"""Bank 256 → MSB 2, LSB 0; bank 257 → MSB 2, LSB 1."""

	assert subsequence.midi_utils.bank_select(256) == (2, 0)
	assert subsequence.midi_utils.bank_select(257) == (2, 1)


def test_bank_select_max () -> None:

	"""Maximum 14-bit bank (16383) → MSB 127, LSB 127."""

	assert subsequence.midi_utils.bank_select(16383) == (127, 127)


def test_bank_select_clamps_negative () -> None:

	"""Negative values are clamped to bank 0."""

	assert subsequence.midi_utils.bank_select(-1) == (0, 0)


def test_bank_select_clamps_overflow () -> None:

	"""Values above 16383 are clamped to the maximum bank."""

	assert subsequence.midi_utils.bank_select(99999) == (127, 127)


def test_bank_select_roundtrip () -> None:

	"""MSB and LSB reconstruct the original bank number."""

	for bank in [0, 1, 127, 128, 255, 256, 1000, 16383]:
		msb, lsb = subsequence.midi_utils.bank_select(bank)
		assert (msb << 7) | lsb == bank


# --- thue_morse ---


def test_thue_morse_correct_length () -> None:

	"""thue_morse(n) returns a list of exactly n values."""

	assert len(subsequence.sequence_utils.thue_morse(16)) == 16


def test_thue_morse_zero_returns_empty () -> None:

	"""thue_morse(0) returns an empty list."""

	assert subsequence.sequence_utils.thue_morse(0) == []


def test_thue_morse_negative_returns_empty () -> None:

	"""thue_morse with negative n returns an empty list."""

	assert subsequence.sequence_utils.thue_morse(-5) == []


def test_thue_morse_binary_values () -> None:

	"""All values in thue_morse output are 0 or 1."""

	result = subsequence.sequence_utils.thue_morse(32)
	assert all(v in (0, 1) for v in result)


def test_thue_morse_known_prefix () -> None:

	"""First 8 values match the well-known sequence 0 1 1 0 1 0 0 1."""

	assert subsequence.sequence_utils.thue_morse(8) == [0, 1, 1, 0, 1, 0, 0, 1]


def test_thue_morse_deterministic () -> None:

	"""Two calls with the same n produce identical results."""

	assert (
		subsequence.sequence_utils.thue_morse(24)
		== subsequence.sequence_utils.thue_morse(24)
	)


# --- de_bruijn ---


def test_de_bruijn_correct_length () -> None:

	"""de_bruijn(k, n) returns a list of k**n values."""

	assert len(subsequence.sequence_utils.de_bruijn(2, 3)) == 8


def test_de_bruijn_zero_k_returns_empty () -> None:

	"""de_bruijn(0, n) returns an empty list."""

	assert subsequence.sequence_utils.de_bruijn(0, 3) == []


def test_de_bruijn_zero_n_returns_empty () -> None:

	"""de_bruijn(k, 0) returns an empty list."""

	assert subsequence.sequence_utils.de_bruijn(3, 0) == []


def test_de_bruijn_symbol_range () -> None:

	"""All symbols in de_bruijn(k, n) are in [0, k-1]."""

	result = subsequence.sequence_utils.de_bruijn(3, 2)
	assert all(0 <= v <= 2 for v in result)


def test_de_bruijn_all_subsequences_present () -> None:

	"""Every n-gram over k symbols appears in the cyclic de Bruijn sequence."""

	k, n = 2, 3
	seq = subsequence.sequence_utils.de_bruijn(k, n)
	cyclic = seq + seq[:n - 1]

	ngrams = set()
	for i in range(len(seq)):
		ngram = tuple(cyclic[i:i + n])
		ngrams.add(ngram)

	expected = k ** n
	assert len(ngrams) == expected


def test_de_bruijn_deterministic () -> None:

	"""Two calls with the same parameters produce identical results."""

	assert (
		subsequence.sequence_utils.de_bruijn(3, 2)
		== subsequence.sequence_utils.de_bruijn(3, 2)
	)


# --- fibonacci_rhythm ---


def test_fibonacci_rhythm_correct_length () -> None:

	"""fibonacci_rhythm(n) returns a list of exactly n values."""

	assert len(subsequence.sequence_utils.fibonacci_rhythm(8)) == 8


def test_fibonacci_rhythm_zero_returns_empty () -> None:

	"""fibonacci_rhythm(0) returns an empty list."""

	assert subsequence.sequence_utils.fibonacci_rhythm(0) == []


def test_fibonacci_rhythm_within_range () -> None:

	"""All positions are within [0.0, length)."""

	result = subsequence.sequence_utils.fibonacci_rhythm(20, length=4.0)
	assert all(0.0 <= v < 4.0 for v in result)


def test_fibonacci_rhythm_sorted () -> None:

	"""Output is sorted in ascending order."""

	result = subsequence.sequence_utils.fibonacci_rhythm(16)
	assert result == sorted(result)


def test_fibonacci_rhythm_deterministic () -> None:

	"""Two calls with the same arguments produce identical results."""

	assert (
		subsequence.sequence_utils.fibonacci_rhythm(12)
		== subsequence.sequence_utils.fibonacci_rhythm(12)
	)


def test_fibonacci_rhythm_no_duplicates () -> None:

	"""All positions are distinct for a reasonable step count."""

	result = subsequence.sequence_utils.fibonacci_rhythm(16, length=4.0)
	assert len(result) == len(set(result))


# --- lorenz_attractor ---


def test_lorenz_attractor_correct_length () -> None:

	"""lorenz_attractor(n) returns a list of exactly n tuples."""

	assert len(subsequence.sequence_utils.lorenz_attractor(16)) == 16


def test_lorenz_attractor_zero_returns_empty () -> None:

	"""lorenz_attractor(0) returns an empty list."""

	assert subsequence.sequence_utils.lorenz_attractor(0) == []


def test_lorenz_attractor_three_components () -> None:

	"""Each element is a 3-tuple."""

	result = subsequence.sequence_utils.lorenz_attractor(8)
	assert all(len(t) == 3 for t in result)


def test_lorenz_attractor_normalised_range () -> None:

	"""All x, y, z components are in [0.0, 1.0]."""

	result = subsequence.sequence_utils.lorenz_attractor(100)
	for x, y, z in result:
		assert 0.0 <= x <= 1.0
		assert 0.0 <= y <= 1.0
		assert 0.0 <= z <= 1.0


def test_lorenz_attractor_deterministic () -> None:

	"""Same parameters produce identical output."""

	a = subsequence.sequence_utils.lorenz_attractor(20, x0=0.1, y0=0.0, z0=0.0)
	b = subsequence.sequence_utils.lorenz_attractor(20, x0=0.1, y0=0.0, z0=0.0)
	assert a == b


def test_lorenz_attractor_sensitive_to_initial_conditions () -> None:

	"""Different initial conditions eventually produce different output."""

	a = subsequence.sequence_utils.lorenz_attractor(100, x0=0.1)
	b = subsequence.sequence_utils.lorenz_attractor(100, x0=0.2)
	assert a != b


# --- reaction_diffusion_1d ---


def test_reaction_diffusion_1d_correct_length () -> None:

	"""reaction_diffusion_1d(width) returns a list of exactly width values."""

	assert len(subsequence.sequence_utils.reaction_diffusion_1d(16, steps=100)) == 16


def test_reaction_diffusion_1d_zero_returns_empty () -> None:

	"""reaction_diffusion_1d(0) returns an empty list."""

	assert subsequence.sequence_utils.reaction_diffusion_1d(0) == []


def test_reaction_diffusion_1d_normalised_range () -> None:

	"""All values are in [0.0, 1.0]."""

	result = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=500)
	assert all(0.0 <= v <= 1.0 for v in result)


def test_reaction_diffusion_1d_deterministic () -> None:

	"""Same parameters produce identical output."""

	a = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=200)
	b = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=200)
	assert a == b


def test_reaction_diffusion_1d_has_structure () -> None:

	"""Not all values are identical for default parameters."""

	result = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=500)
	assert len(set(result)) > 1


def test_reaction_diffusion_1d_different_rates_differ () -> None:

	"""Different feed/kill rates produce different patterns."""

	a = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=300, feed_rate=0.055, kill_rate=0.062)
	b = subsequence.sequence_utils.reaction_diffusion_1d(16, steps=300, feed_rate=0.037, kill_rate=0.060)
	assert a != b


# --- self_avoiding_walk ---


def test_self_avoiding_walk_correct_length () -> None:

	"""self_avoiding_walk(n) returns a list of exactly n values."""

	rng = random.Random(1)
	assert len(subsequence.sequence_utils.self_avoiding_walk(16, 0, 7, rng)) == 16


def test_self_avoiding_walk_zero_returns_empty () -> None:

	"""self_avoiding_walk(0) returns an empty list."""

	rng = random.Random(1)
	assert subsequence.sequence_utils.self_avoiding_walk(0, 0, 7, rng) == []


def test_self_avoiding_walk_within_range () -> None:

	"""All values are within [low, high]."""

	rng = random.Random(1)
	result = subsequence.sequence_utils.self_avoiding_walk(16, 2, 8, rng)
	assert all(2 <= v <= 8 for v in result)


def test_self_avoiding_walk_no_immediate_repeat () -> None:

	"""No two consecutive values are identical (walk always moves)."""

	rng = random.Random(1)
	result = subsequence.sequence_utils.self_avoiding_walk(20, 0, 9, rng)
	for i in range(len(result) - 1):
		assert result[i] != result[i + 1]


def test_self_avoiding_walk_step_size_one () -> None:

	"""Each step changes the value by exactly 1."""

	rng = random.Random(1)
	result = subsequence.sequence_utils.self_avoiding_walk(16, 0, 9, rng)
	for i in range(len(result) - 1):
		assert abs(result[i + 1] - result[i]) == 1


def test_self_avoiding_walk_deterministic () -> None:

	"""Same seed produces identical output."""

	a = subsequence.sequence_utils.self_avoiding_walk(16, 0, 7, random.Random(99))
	b = subsequence.sequence_utils.self_avoiding_walk(16, 0, 7, random.Random(99))
	assert a == b


def test_self_avoiding_walk_custom_start () -> None:

	"""First value equals the start parameter."""

	rng = random.Random(1)
	result = subsequence.sequence_utils.self_avoiding_walk(8, 0, 9, rng, start=3)
	assert result[0] == 3
