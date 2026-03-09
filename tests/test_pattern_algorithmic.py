"""Tests for PatternAlgorithmicMixin — evolve() and branch() methods."""

import subsequence.constants
import subsequence.constants.durations
import subsequence.pattern
import subsequence.pattern_builder


def _make_builder(channel: int = 0, length: float = 4, cycle: int = 0, data: dict = None):
	"""Create a Pattern and PatternBuilder pair for testing."""
	default_grid = round(length / subsequence.constants.durations.SIXTEENTH)
	pattern = subsequence.pattern.Pattern(channel=channel, length=length)
	builder = subsequence.pattern_builder.PatternBuilder(
		pattern=pattern,
		cycle=cycle,
		default_grid=default_grid,
		data=data if data is not None else {},
	)
	return pattern, builder


# ---------------------------------------------------------------------------
# evolve()
# ---------------------------------------------------------------------------

def test_evolve_drift_zero_locks_loop() -> None:
	"""drift=0.0 must produce identical pitch output on every cycle."""
	seed = [60, 62, 64, 67]
	shared_data: dict = {}

	pitches_by_cycle = []
	for cycle in range(5):
		pattern, builder = _make_builder(cycle=cycle, data=shared_data)
		builder.evolve(seed, drift=0.0, spacing=0.25)
		notes = sorted(pattern.steps.values(), key=lambda s: list(pattern.steps.keys())[list(pattern.steps.values()).index(s)])
		pitches = [n.pitch for step in pattern.steps.values() for n in step.notes]
		pitches_by_cycle.append(pitches)

	# All cycles must produce the same pitches.
	for later in pitches_by_cycle[1:]:
		assert later == pitches_by_cycle[0], "drift=0.0 should never change pitches"


def test_evolve_drift_zero_seed_matches() -> None:
	"""On cycle 0 with drift=0 the output matches the seed exactly."""
	seed = [60, 62, 64, 67]
	pattern, builder = _make_builder(cycle=0)
	builder.evolve(seed, drift=0.0, spacing=0.25)

	pitches = [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]
	assert pitches == seed


def test_evolve_steps_truncates_seed() -> None:
	"""steps=2 should produce exactly 2 notes from a longer seed."""
	seed = [60, 62, 64, 67]
	pattern, builder = _make_builder(cycle=0)
	builder.evolve(seed, steps=2, drift=0.0, spacing=0.25)

	count = sum(len(step.notes) for step in pattern.steps.values())
	assert count == 2


def test_evolve_steps_extends_seed() -> None:
	"""steps=6 with a 4-note seed should cycle and produce 6 notes."""
	seed = [60, 62, 64, 67]
	pattern, builder = _make_builder(length=8, cycle=0)
	builder.evolve(seed, steps=6, drift=0.0, spacing=0.5)

	count = sum(len(step.notes) for step in pattern.steps.values())
	assert count == 6

	# The first 4 notes repeat as per cycling.
	pitches = [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]
	assert pitches[:4] == seed
	assert pitches[4:] == seed[:2]


def test_evolve_drift_one_replaces_all() -> None:
	"""drift=1.0 must replace every note on cycle >= 1 (statistically certain)."""
	seed = [60, 62, 64, 67]
	shared_data: dict = {}

	# Cycle 0 — establish seed in data.
	_, builder0 = _make_builder(cycle=0, data=shared_data)
	builder0.evolve(seed, drift=1.0, spacing=0.25)

	# Cycle 1 — all steps replaced, but still drawn from pool.
	pattern1, builder1 = _make_builder(cycle=1, data=shared_data)
	builder1.evolve(seed, drift=1.0, spacing=0.25)
	pitches1 = [n.pitch for step in pattern1.steps.values() for n in step.notes]

	# All pitches must be valid members of the seed pool.
	for p in pitches1:
		assert p in seed, f"pitch {p} not in seed pool"


def test_evolve_deterministic_with_fixed_rng() -> None:
	"""Same seed + same rng seed must produce identical evolution path."""
	seed = [60, 62, 64, 67]
	import random

	results = []
	for _ in range(2):
		shared_data: dict = {}
		all_pitches = []
		for cycle in range(4):
			pattern, builder = _make_builder(cycle=cycle, data=shared_data)
			builder.rng = random.Random(42)
			builder.evolve(seed, drift=0.3, spacing=0.25)
			pitches = [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]
			all_pitches.append(pitches)
		results.append(all_pitches)

	assert results[0] == results[1], "evolve() must be deterministic given the same rng seed"


def test_evolve_buffer_stays_in_pool() -> None:
	"""After many cycles of drift=1.0, all pitches must remain in the seed pool."""
	seed = [60, 62, 64, 67]
	shared_data: dict = {}

	for cycle in range(10):
		pattern, builder = _make_builder(cycle=cycle, data=shared_data)
		builder.evolve(seed, drift=1.0, spacing=0.25)

	pitches = [n.pitch for step in pattern.steps.values() for n in step.notes]
	for p in pitches:
		assert p in seed


# ---------------------------------------------------------------------------
# branch()
# ---------------------------------------------------------------------------

def test_branch_depth_zero_plays_seed() -> None:
	"""depth=0 must play the seed unchanged (no transforms applied)."""
	seed = [60, 64, 67, 72]
	pattern, builder = _make_builder(cycle=0)
	builder.branch(seed, depth=0, path=0, mutation=0.0, spacing=0.5)

	pitches = [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]
	assert pitches == seed


def test_branch_path_zero_and_one_differ() -> None:
	"""path=0 and path=1 at depth=1 must produce different sequences."""
	seed = [60, 64, 67, 72]

	pattern0, builder0 = _make_builder(cycle=0)
	builder0.branch(seed, depth=1, path=0, mutation=0.0, spacing=0.5)
	pitches0 = [n.pitch for step in sorted(pattern0.steps.items()) for n in step[1].notes]

	pattern1, builder1 = _make_builder(cycle=0)
	builder1.branch(seed, depth=1, path=1, mutation=0.0, spacing=0.5)
	pitches1 = [n.pitch for step in sorted(pattern1.steps.items()) for n in step[1].notes]

	assert pitches0 != pitches1, "path=0 and path=1 should produce different variations"


def test_branch_deterministic() -> None:
	"""Same seed + depth + path must always produce the same output."""
	seed = [60, 64, 67, 72]

	def _get_pitches(path):
		pattern, builder = _make_builder(cycle=0)
		builder.branch(seed, depth=3, path=path, mutation=0.0, spacing=0.5)
		return [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]

	# Call twice with same path — must produce identical result.
	assert _get_pitches(2) == _get_pitches(2)
	assert _get_pitches(5) == _get_pitches(5)


def test_branch_path_wraps() -> None:
	"""path=0 and path=2**depth should produce the same result (wrapping)."""
	seed = [60, 64, 67, 72]
	depth = 3
	num_variations = 2 ** depth

	def _get_pitches(path):
		pattern, builder = _make_builder(cycle=0)
		builder.branch(seed, depth=depth, path=path, mutation=0.0, spacing=0.5)
		return [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]

	assert _get_pitches(0) == _get_pitches(num_variations)
	assert _get_pitches(1) == _get_pitches(num_variations + 1)


def test_branch_note_count_matches_seed() -> None:
	"""Output should have the same number of notes as the seed."""
	seed = [60, 64, 67, 72]
	for depth in range(4):
		for path in range(2 ** depth):
			pattern, builder = _make_builder(cycle=0)
			builder.branch(seed, depth=depth, path=path, mutation=0.0, spacing=0.5)
			count = sum(len(s.notes) for s in pattern.steps.values())
			assert count == len(seed), f"depth={depth}, path={path}: expected {len(seed)} notes, got {count}"


def test_branch_mutation_zero_is_deterministic() -> None:
	"""mutation=0.0 must produce purely deterministic output (no rng involvement)."""
	seed = [60, 64, 67, 72]
	import random

	results = []
	for rng_seed in [1, 99, 12345]:
		pattern, builder = _make_builder(cycle=0)
		builder.rng = random.Random(rng_seed)
		builder.branch(seed, depth=2, path=3, mutation=0.0, spacing=0.5)
		pitches = [n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes]
		results.append(pitches)

	# All three rng seeds should produce identical output since mutation=0.
	assert results[0] == results[1] == results[2]


def test_branch_mutation_one_draws_from_seed_pool() -> None:
	"""mutation=1.0 must still draw only from the seed pool."""
	seed = [60, 64, 67, 72]
	pattern, builder = _make_builder(cycle=0)
	builder.branch(seed, depth=2, path=0, mutation=1.0, spacing=0.5)

	pitches = [n.pitch for step in pattern.steps.values() for n in step.notes]
	for p in pitches:
		assert p in seed, f"pitch {p} not in seed pool"


def test_branch_cycle_path_advances() -> None:
	"""Using path=cycle should step through unique variations."""
	seed = [60, 64, 67, 72]
	depth = 3
	variations = set()

	for cycle in range(2 ** depth):
		pattern, builder = _make_builder(cycle=cycle)
		builder.branch(seed, depth=depth, path=cycle, mutation=0.0, spacing=0.5)
		pitches = tuple(n.pitch for step in sorted(pattern.steps.items()) for n in step[1].notes)
		variations.add(pitches)

	# Each path should produce a unique sequence.
	assert len(variations) == 2 ** depth, f"Expected {2**depth} unique variations, got {len(variations)}"
