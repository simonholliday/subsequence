"""
Stage 0 determinism contract (DESIGN-COMPOSITION.md §7 / §10 stage 0).

Named-stream seeding: build-time consumers draw per-call-salted streams
(freeze:1, harmony:2, ...) so frozen output is reproducible without play()
and adding one call never shifts a neighbour; play-time pattern streams are
name-keyed (crc32 of "seed:name"), so registration order is irrelevant and
live-added patterns derive the same stream they would have had at startup.
"""

import logging
import random
import zlib

import pytest

import subsequence
import subsequence.composition


def _make (seed: int = 42, key: str = "A") -> "subsequence.Composition":

	"""A keyed, seeded composition against the dummy MIDI device."""

	return subsequence.Composition(output_device="Dummy MIDI", bpm=120, key=key, seed=seed)


def _pending (fn, channel: int = 1) -> "subsequence.composition._PendingPattern":

	"""Wrap a builder function as a pending pattern registration."""

	return subsequence.composition._PendingPattern(
		builder_fn = fn,
		channel = channel,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)


# ── seed property ───────────────────────────────────────────────────────────

def test_seed_property_get_set (patch_midi: None) -> None:

	"""comp.seed reads and assigns; the former call form raises TypeError."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	assert composition.seed is None

	composition.seed = 7
	assert composition.seed == 7

	with pytest.raises(TypeError):
		composition.seed(7)  # type: ignore[operator]


# ── seed_for derivation ─────────────────────────────────────────────────────

def test_seed_for_is_crc32_of_seed_and_name (patch_midi: None) -> None:

	"""seed_for(name) == crc32("seed:name") — process-stable, order-free."""

	composition = _make(seed=42)

	assert composition.seed_for("drums") == zlib.crc32(b"42:drums")
	assert composition.seed_for("hook") == zlib.crc32(b"42:hook")


def test_seed_for_unseeded_returns_none (patch_midi: None) -> None:

	"""Without a composition seed there is no derivation."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	assert composition.seed_for("drums") is None


# ── freeze(): reproducible without play() ───────────────────────────────────

def test_freeze_deterministic_without_play (patch_midi: None) -> None:

	"""Two same-seed compositions freeze identical progressions pre-play."""

	first = _make()
	first.harmony(style="functional_major")

	second = _make()
	second.harmony(style="functional_major")

	assert first.freeze(8).chords == second.freeze(8).chords


def test_freeze_differs_across_seeds (patch_midi: None) -> None:

	"""Different seeds produce different frozen journeys."""

	runs = []

	for seed in (42, 99):
		composition = _make(seed=seed)
		composition.harmony(style="functional_major")
		runs.append(tuple(composition.freeze(8).chords))

	assert runs[0] != runs[1]


def test_freeze_stream_independent_of_other_consumers (patch_midi: None) -> None:

	"""A foreign draw on the engine's rng cannot shift freeze() output."""

	clean = _make()
	clean.harmony(style="functional_major")
	expected = clean.freeze(4).chords

	disturbed = _make()
	disturbed.harmony(style="functional_major")
	disturbed._harmonic_state.rng.random()  # someone else consumes the engine stream

	assert disturbed.freeze(4).chords == expected


def test_successive_freezes_are_a_continuing_deterministic_journey (patch_midi: None) -> None:

	"""freeze:1 then freeze:2 reproduce as a pair (state continues, salts differ)."""

	first = _make()
	first.harmony(style="functional_major")
	journey_a = (first.freeze(4).chords, first.freeze(4).chords)

	second = _make()
	second.harmony(style="functional_major")
	journey_b = (second.freeze(4).chords, second.freeze(4).chords)

	assert journey_a == journey_b


def test_freeze_restores_engine_rng (patch_midi: None) -> None:

	"""Swap-and-restore: the engine keeps its own stream for play."""

	composition = _make()
	composition.harmony(style="functional_major")

	engine_rng = composition._harmonic_state.rng
	composition.freeze(4)

	assert composition._harmonic_state.rng is engine_rng


# ── build-time seeding of harmony() and form() ──────────────────────────────

def test_harmony_rng_seeded_at_call_time (patch_midi: None) -> None:

	"""harmony() installs a deterministic per-call stream (harmony:1)."""

	draws = []

	for _ in range(2):
		composition = _make()
		composition.harmony(style="functional_major")
		draws.append(composition._harmonic_state.rng.random())

	assert draws[0] == draws[1]


def test_form_state_seeded_at_call_time (patch_midi: None) -> None:

	"""form() installs a deterministic per-call stream (form:1)."""

	graph = {
		"a": (4, [("b", 1)]),
		"b": (4, [("a", 1)]),
	}
	draws = []

	for _ in range(2):
		composition = _make()
		composition.form(dict(graph), start="a")
		draws.append(composition._form_state._rng.random())

	assert draws[0] == draws[1]


# ── name-keyed pattern streams ──────────────────────────────────────────────

def test_pattern_stream_keyed_by_name_not_order (patch_midi: None) -> None:

	"""A pattern's stream derives from its name; registration order is irrelevant."""

	def observe (name: str, build_first: bool) -> float:

		composition = _make(seed=42)
		seen = []

		def lead (p) -> None:
			seen.append(p.rng.random())

		def drums (p) -> None:
			p.rng.random()

		order = [lead, drums] if build_first else [drums, lead]

		for fn in order:
			composition._build_pattern_from_pending(_pending(fn))

		return seen[0]

	expected = random.Random(zlib.crc32(b"42:lead")).random()

	assert observe("lead", build_first=True) == expected
	assert observe("lead", build_first=False) == expected


def test_live_added_pattern_gets_seeded_stream (patch_midi: None) -> None:

	"""Building a pending pattern at any time deals its seeded stream (live-add fix)."""

	composition = _make(seed=42)

	def late (p) -> None:
		pass

	pattern = composition._build_pattern_from_pending(_pending(late))

	assert pattern._rng is not None
	assert random.Random(zlib.crc32(b"42:late")).random() == random.Random(composition.seed_for("late")).random()


def test_unseeded_pattern_stream_is_none (patch_midi: None) -> None:

	"""No composition seed → patterns keep unseeded randomness (existing behaviour)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)

	def free (p) -> None:
		pass

	pattern = composition._build_pattern_from_pending(_pending(free))

	assert pattern._rng is None


def test_duplicate_pattern_name_warns (patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	"""Registering two patterns with one name warns at registration."""

	composition = _make()

	def clash (p) -> None:
		pass

	with caplog.at_level(logging.WARNING):
		composition.pattern(channel=1, beats=4)(clash)
		composition.pattern(channel=2, beats=4)(clash)

	assert any("Duplicate pattern name 'clash'" in record.message for record in caplog.records)


# ── reroll / lock / unlock ──────────────────────────────────────────────────

def test_reroll_bumps_nonce_and_prints_effective_seed (patch_midi: None, capsys: pytest.CaptureFixture) -> None:

	"""reroll() changes the derived seed and prints the new effective value."""

	composition = _make(seed=42)
	original = composition.seed_for("lead")

	composition.reroll("lead")
	bumped = composition.seed_for("lead")

	assert bumped != original
	assert bumped == zlib.crc32(b"42:lead:1")
	assert f"effective seed {bumped}" in capsys.readouterr().out

	composition.reroll("lead")
	assert composition.seed_for("lead") == zlib.crc32(b"42:lead:2")


def test_reroll_unseeded_explains (patch_midi: None, capsys: pytest.CaptureFixture) -> None:

	"""reroll() on an unseeded composition says so instead of pretending."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	composition.reroll("lead")

	assert "no seed" in capsys.readouterr().out


def test_lock_refuses_reroll_until_unlock (patch_midi: None, capsys: pytest.CaptureFixture) -> None:

	"""A locked name keeps its effective seed; unlock() restores reroll()."""

	composition = _make(seed=42)
	composition.lock("lead")

	before = composition.seed_for("lead")
	composition.reroll("lead")

	assert composition.seed_for("lead") == before
	assert "refused" in capsys.readouterr().out

	composition.unlock("lead")
	composition.reroll("lead")

	assert composition.seed_for("lead") != before


def test_locked_pattern_realizes_identically_each_rebuild (patch_midi: None) -> None:

	"""lock() re-deals the stream per rebuild: every cycle realizes the same."""

	composition = _make(seed=42)
	draws = []

	def wobble (p) -> None:
		draws.append(p.rng.random())

	pattern = composition._build_pattern_from_pending(_pending(wobble))

	pattern._rebuild()
	assert draws[0] != draws[1]  # free-running: the stream continues across rebuilds

	composition.lock("wobble")
	pattern._rebuild()
	pattern._rebuild()

	assert draws[2] == draws[3]  # locked: identical realization every rebuild
	assert draws[2] == random.Random(composition.seed_for("wobble")).random()
