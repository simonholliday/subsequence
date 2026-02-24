import pytest

import subsequence.harmony
import subsequence.intervals


# ── Built-in non-western scales ─────────────────────────────────────

def test_hirajoshi_pitch_classes () -> None:

	"""Hirajōshi scale produces 5 pitch classes."""

	pcs = subsequence.intervals.scale_pitch_classes(2, "hirajoshi")  # D Hirajōshi
	assert len(pcs) == 5
	assert pcs == [2, 4, 5, 9, 10]  # D, E, F, A, Bb


def test_in_sen_pitch_classes () -> None:

	"""In-Sen scale produces 5 pitch classes."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "in_sen")  # C In-Sen
	assert len(pcs) == 5
	assert pcs == [0, 1, 5, 7, 10]


def test_iwato_pitch_classes () -> None:

	"""Iwato scale produces 5 pitch classes."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "iwato")
	assert len(pcs) == 5
	assert pcs == [0, 1, 5, 6, 10]


def test_yo_pitch_classes () -> None:

	"""Yo scale produces 5 pitch classes."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "yo")
	assert len(pcs) == 5
	assert pcs == [0, 2, 5, 7, 9]


def test_egyptian_pitch_classes () -> None:

	"""Egyptian scale produces 5 pitch classes."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "egyptian")
	assert len(pcs) == 5
	assert pcs == [0, 2, 5, 7, 10]


def test_major_pentatonic_pitch_classes () -> None:

	"""Major pentatonic via SCALE_MODE_MAP."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "major_pentatonic")
	assert len(pcs) == 5
	assert pcs == [0, 2, 4, 7, 9]


def test_minor_pentatonic_pitch_classes () -> None:

	"""Minor pentatonic via SCALE_MODE_MAP."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "minor_pentatonic")
	assert len(pcs) == 5
	assert pcs == [0, 3, 5, 7, 10]


# ── quantize_pitch with 5-note scales ───────────────────────────────

def test_quantize_hirajoshi_snaps_correctly () -> None:

	"""Notes outside a 5-note scale snap to the nearest scale tone."""

	pcs = subsequence.intervals.scale_pitch_classes(2, "hirajoshi")  # D: [2,4,5,9,10]

	# D (62) is in scale → unchanged
	assert subsequence.intervals.quantize_pitch(62, pcs) == 62

	# C# (61) is not in scale → snaps to D (62, +1 preferred)
	assert subsequence.intervals.quantize_pitch(61, pcs) == 62

	# G (67) is between F(65) and A(69) → snaps to F (65) at distance 2
	# Actually: pc 7 (G). Scale pcs: 2,4,5,9,10. Nearest up: 9 (A, +2). Nearest down: 5 (F, -2). Up preferred.
	assert subsequence.intervals.quantize_pitch(67, pcs) == 69


def test_quantize_handles_large_gap () -> None:

	"""Hirajōshi has a 4-semitone gap (F→A). Notes in the gap still snap."""

	pcs = subsequence.intervals.scale_pitch_classes(0, "hirajoshi")  # C: [0,2,3,7,8]

	# E (64) is pc 4, not in scale. Nearest: 3 (Eb, -1) or 7 (G, +3). Snaps down to Eb.
	assert subsequence.intervals.quantize_pitch(64, pcs) == 63

	# F (65) is pc 5. Nearest: 3 (Eb, -2) or 7 (G, +2). Up preferred → G (67).
	assert subsequence.intervals.quantize_pitch(65, pcs) == 67


# ── register_scale ──────────────────────────────────────────────────

def test_register_scale_basic () -> None:

	"""A registered custom scale works with scale_pitch_classes."""

	subsequence.intervals.register_scale("test_custom", [0, 3, 6, 9])

	pcs = subsequence.intervals.scale_pitch_classes(0, "test_custom")
	assert pcs == [0, 3, 6, 9]

	# Clean up
	del subsequence.intervals.INTERVAL_DEFINITIONS["test_custom"]
	del subsequence.intervals.SCALE_MODE_MAP["test_custom"]


def test_register_scale_with_qualities () -> None:

	"""A registered scale with qualities works with diatonic_chords."""

	subsequence.intervals.register_scale(
		"test_with_quals",
		[0, 2, 4, 7, 9],
		qualities=["major", "minor", "minor", "major", "minor"]
	)

	chords = subsequence.harmony.diatonic_chords("C", mode="test_with_quals")
	assert len(chords) == 5

	# Clean up
	del subsequence.intervals.INTERVAL_DEFINITIONS["test_with_quals"]
	del subsequence.intervals.SCALE_MODE_MAP["test_with_quals"]


def test_register_scale_quantize () -> None:

	"""A registered custom scale works with quantize_pitch."""

	subsequence.intervals.register_scale("test_quant", [0, 4, 7])

	pcs = subsequence.intervals.scale_pitch_classes(0, "test_quant")
	# C (0), E (4), G (7) — a major triad
	assert subsequence.intervals.quantize_pitch(61, pcs) == 60  # C# → C
	assert subsequence.intervals.quantize_pitch(62, pcs) == 64  # D → E (up preferred at distance 2)

	# Clean up
	del subsequence.intervals.INTERVAL_DEFINITIONS["test_quant"]
	del subsequence.intervals.SCALE_MODE_MAP["test_quant"]


def test_register_scale_via_package () -> None:

	"""register_scale is accessible from the package level."""

	import subsequence

	subsequence.register_scale("test_pkg", [0, 5, 7])
	pcs = subsequence.intervals.scale_pitch_classes(0, "test_pkg")
	assert pcs == [0, 5, 7]

	# Clean up
	del subsequence.intervals.INTERVAL_DEFINITIONS["test_pkg"]
	del subsequence.intervals.SCALE_MODE_MAP["test_pkg"]


# ── register_scale validation ───────────────────────────────────────

def test_register_scale_must_start_with_zero () -> None:

	"""intervals must start with 0."""

	with pytest.raises(ValueError, match="start with 0"):
		subsequence.intervals.register_scale("bad", [1, 3, 5])


def test_register_scale_values_in_range () -> None:

	"""intervals must be 0-11."""

	with pytest.raises(ValueError, match="between 0 and 11"):
		subsequence.intervals.register_scale("bad", [0, 3, 14])


def test_register_scale_qualities_length_mismatch () -> None:

	"""qualities length must match intervals length."""

	with pytest.raises(ValueError, match="qualities length"):
		subsequence.intervals.register_scale("bad", [0, 3, 7], qualities=["major", "minor"])


# ── diatonic_chords guard for no-qualities modes ────────────────────

def test_diatonic_chords_raises_for_no_qualities () -> None:

	"""Modes without chord qualities raise a clear error."""

	with pytest.raises(ValueError, match="no chord qualities"):
		subsequence.harmony.diatonic_chords("C", mode="hirajoshi")


# ── diatonic_chord_sequence with non-7-note scales ──────────────────

def test_diatonic_chord_sequence_5_note () -> None:

	"""diatonic_chord_sequence works with a 5-note scale that has qualities."""

	subsequence.intervals.register_scale(
		"test_seq_5",
		[0, 2, 4, 7, 9],
		qualities=["major", "minor", "minor", "major", "minor"]
	)

	seq = subsequence.harmony.diatonic_chord_sequence("C", root_midi=60, count=10, mode="test_seq_5")

	# Should wrap after 5 degrees into the next octave
	assert len(seq) == 10
	assert seq[0][1] == 60   # C4
	assert seq[5][1] == 72   # C5 (one octave up)

	# Clean up
	del subsequence.intervals.INTERVAL_DEFINITIONS["test_seq_5"]
	del subsequence.intervals.SCALE_MODE_MAP["test_seq_5"]


# ── Backwards compatibility ─────────────────────────────────────────

def test_diatonic_mode_map_alias () -> None:

	"""DIATONIC_MODE_MAP is a backwards-compatible alias for SCALE_MODE_MAP."""

	assert subsequence.intervals.DIATONIC_MODE_MAP is subsequence.intervals.SCALE_MODE_MAP


def test_western_modes_unchanged () -> None:

	"""All original western modes still return the expected chord counts."""

	western_modes = [
		"ionian", "major", "dorian", "phrygian", "lydian",
		"mixolydian", "aeolian", "minor", "locrian",
		"harmonic_minor", "melodic_minor"
	]
	for mode in western_modes:
		chords = subsequence.harmony.diatonic_chords("C", mode=mode)
		assert len(chords) == 7, f"{mode} should still return 7 chords"
