import pytest

import subsequence.pattern
import subsequence.pattern_builder


def test_duration_fixed_value() -> None:
    """Test duration() sets a fixed note length relative to a quarter note."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    # Place notes with different durations
    builder.note(pitch=60, beat=0.0, duration=1.0)  # Long note
    builder.note(pitch=62, beat=1.0, duration=0.1)  # Short note

    # Apply duration(0.5) -> duration should be 0.5 * 24 = 12 pulses
    builder.duration(0.5)

    assert pat.steps[0].notes[0].duration == 12
    assert pat.steps[24].notes[0].duration == 12


def test_duration_short_value() -> None:
    """Test a very short fixed duration."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    builder.note(60, 0.0)

    # 0.1 beats -> 2.4 pulses -> truncated to 2 pulses
    builder.duration(0.1)

    assert pat.steps[0].notes[0].duration == int(24 * 0.1)


def test_duration_long_value() -> None:
    """Test a value > 1.0 (a ringing, tenuto-like length but valid parameter)."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    builder.note(60, 0.0)

    # 2.0 beats -> 48 pulses
    builder.duration(2.0)

    assert pat.steps[0].notes[0].duration == 48


def test_duration_minimum_one_pulse() -> None:
    """Ensure duration is at least 1 pulse."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    builder.note(60, 0.0)

    # Tiny value
    builder.duration(0.0001)

    assert pat.steps[0].notes[0].duration == 1


def test_duration_invalid_value() -> None:
    """Test that negative/zero duration raises ValueError."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    builder.note(60, 0.0)

    with pytest.raises(ValueError):
        builder.duration(0)

    with pytest.raises(ValueError):
        builder.duration(-0.5)


def test_staccato_name_removed() -> None:
    """The old staccato() name is gone — a hard break, not an alias."""

    pat = subsequence.pattern.Pattern(channel=0, length=4.0)
    builder = subsequence.pattern_builder.PatternBuilder(pattern=pat, cycle=0)

    assert not hasattr(builder, "staccato")
