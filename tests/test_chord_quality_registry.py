"""Tests for register_chord_quality(), the diminished_7th builtin, and Chord.name() fallback."""

import pytest

import subsequence.chords


@pytest.fixture(autouse=True)
def _clean_registry():
    """Restore the quality tables after each test — registration is module-global."""

    intervals_before = dict(subsequence.chords.CHORD_INTERVALS)
    suffix_before = dict(subsequence.chords.CHORD_SUFFIX)
    parse_before = dict(subsequence.chords._SUFFIX_TO_QUALITY)

    yield

    subsequence.chords.CHORD_INTERVALS.clear()
    subsequence.chords.CHORD_INTERVALS.update(intervals_before)
    subsequence.chords.CHORD_SUFFIX.clear()
    subsequence.chords.CHORD_SUFFIX.update(suffix_before)
    subsequence.chords._SUFFIX_TO_QUALITY.clear()
    subsequence.chords._SUFFIX_TO_QUALITY.update(parse_before)


# ---------------------------------------------------------------------------
# diminished_7th builtin
# ---------------------------------------------------------------------------


def test_diminished_7th_builtin() -> None:
    """The full diminished seventh is a shipped quality with parseable suffixes."""

    chord = subsequence.chords.Chord(root_pc=11, quality="diminished_7th")

    assert chord.intervals() == [0, 3, 6, 9]
    assert chord.name() == "Bdim7"
    assert subsequence.chords.parse_chord("Bdim7") == chord
    assert subsequence.chords.parse_chord("B°7") == chord
    assert subsequence.chords.parse_chord("Bo7") == chord


def test_half_diminished_seven_alias() -> None:
    """The explicit ø7 spelling parses to half_diminished_7th."""

    assert subsequence.chords.parse_chord("Aø7").quality == "half_diminished_7th"


# ---------------------------------------------------------------------------
# register_chord_quality()
# ---------------------------------------------------------------------------


def test_register_quality_with_suffix_round_trips() -> None:
    """A registered quality parses by suffix and prints it back."""

    subsequence.chords.register_chord_quality(
        "minor_9th", [0, 3, 7, 10, 14], suffix="m9"
    )

    chord = subsequence.chords.parse_chord("Am9")

    assert chord == subsequence.chords.Chord(root_pc=9, quality="minor_9th")
    assert chord.intervals() == [0, 3, 7, 10, 14]
    assert chord.name() == "Am9"
    assert subsequence.chords.parse_chord(chord.name()) == chord


def test_register_quality_without_suffix_prints_parenthesised() -> None:
    """A suffix-less quality never masquerades as a major chord."""

    subsequence.chords.register_chord_quality("quartal", [0, 5, 10])

    chord = subsequence.chords.Chord(root_pc=0, quality="quartal")

    assert chord.tones(60) == [60, 65, 70]
    assert chord.name() == "C(quartal)"


def test_register_quality_is_idempotent() -> None:
    """Re-registering a custom quality must not raise (live reload re-runs it)."""

    subsequence.chords.register_chord_quality("quartal", [0, 5, 10], suffix="q4")
    subsequence.chords.register_chord_quality("quartal", [0, 5, 10], suffix="q4")

    assert subsequence.chords.parse_chord("Fq4").quality == "quartal"


def test_reregistration_drops_stale_suffix() -> None:
    """Renaming a quality's suffix removes the old alias."""

    subsequence.chords.register_chord_quality("quartal", [0, 5, 10], suffix="q4")
    subsequence.chords.register_chord_quality("quartal", [0, 5, 10], suffix="quar")

    assert subsequence.chords.parse_chord("Cquar").quality == "quartal"

    with pytest.raises(ValueError):
        subsequence.chords.parse_chord("Cq4")


def test_register_quality_rejects_builtin_name() -> None:
    """Built-in qualities cannot be overwritten."""

    with pytest.raises(ValueError, match="built-in"):
        subsequence.chords.register_chord_quality("minor", [0, 3, 7])


def test_register_quality_rejects_builtin_suffix() -> None:
    """Built-in suffixes cannot be reused for a custom quality."""

    with pytest.raises(ValueError, match="built-in"):
        subsequence.chords.register_chord_quality("my_minor", [0, 3, 7], suffix="m")


def test_register_quality_validates_intervals() -> None:
    """Interval rules: non-empty, ints, start at 0, strictly ascending, 0–24."""

    with pytest.raises(ValueError):
        subsequence.chords.register_chord_quality("bad", [])
    with pytest.raises(ValueError):
        subsequence.chords.register_chord_quality("bad", [1, 4, 7])
    with pytest.raises(ValueError):
        subsequence.chords.register_chord_quality("bad", [0, 7, 7])
    with pytest.raises(ValueError):
        subsequence.chords.register_chord_quality("bad", [0, 4, 25])
    with pytest.raises(ValueError):
        subsequence.chords.register_chord_quality("bad", [0, 4.5, 7])  # type: ignore[list-item]


def test_register_quality_rejects_ambiguous_suffix() -> None:
    """A suffix starting with a note letter or digit would garble parsing."""

    with pytest.raises(ValueError, match="ambiguous"):
        subsequence.chords.register_chord_quality("weird", [0, 1, 2], suffix="A1")
    with pytest.raises(ValueError, match="ambiguous"):
        subsequence.chords.register_chord_quality("weird", [0, 1, 2], suffix="9th")
