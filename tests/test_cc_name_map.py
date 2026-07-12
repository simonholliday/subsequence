"""Tests for the cc_name_map feature — string-based CC name resolution."""

import pytest

import subsequence.constants
import subsequence.constants.durations
import subsequence.pattern
import subsequence.pattern_builder


CC_MAP = {"filter_cutoff": 74, "volume": 7, "expression": 11}


def _make_builder(cc_name_map: dict = None) -> tuple:
    """Create a Pattern and PatternBuilder pair with optional cc_name_map."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4)

    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=0,
        cc_name_map=cc_name_map,
        default_grid=16,
    )

    return pattern, builder


def test_cc_string_resolves_via_cc_name_map() -> None:
    """A string CC name should resolve to the correct CC number via cc_name_map."""

    pattern, builder = _make_builder(cc_name_map=CC_MAP)
    builder.cc("filter_cutoff", 100)

    assert len(pattern.cc_events) == 1
    assert pattern.cc_events[0].control == 74
    assert pattern.cc_events[0].value == 100


def test_cc_int_still_works_with_cc_name_map() -> None:
    """Raw integer CC numbers should still work when a cc_name_map is set."""

    pattern, builder = _make_builder(cc_name_map=CC_MAP)
    builder.cc(74, 100)

    assert len(pattern.cc_events) == 1
    assert pattern.cc_events[0].control == 74


def test_cc_int_works_without_cc_name_map() -> None:
    """Raw integer CC numbers should work when no cc_name_map is provided."""

    pattern, builder = _make_builder()
    builder.cc(74, 100)

    assert len(pattern.cc_events) == 1
    assert pattern.cc_events[0].control == 74


def test_cc_string_without_cc_name_map_raises() -> None:
    """Using a string CC name without a cc_name_map should raise ValueError."""

    _, builder = _make_builder()

    with pytest.raises(ValueError, match="requires a cc_name_map"):
        builder.cc("filter_cutoff", 100)


def test_cc_unknown_name_raises() -> None:
    """An unrecognised CC name should raise ValueError."""

    _, builder = _make_builder(cc_name_map=CC_MAP)

    with pytest.raises(ValueError, match="not found in cc_name_map"):
        builder.cc("nonexistent_param", 100)


def test_cc_ramp_string_resolves() -> None:
    """cc_ramp() should resolve string CC names via cc_name_map."""

    pattern, builder = _make_builder(cc_name_map=CC_MAP)
    builder.cc_ramp("filter_cutoff", 0, 127, beat_start=0, beat_end=1, resolution=24)

    assert len(pattern.cc_events) >= 1
    assert all(e.control == 74 for e in pattern.cc_events)
    assert pattern.cc_events[0].value == 0
    assert pattern.cc_events[-1].value == 127


def test_cc_name_map_passed_through_decorator() -> None:
    """cc_name_map should flow from @composition.pattern() to PatternBuilder."""

    import subsequence

    composition = subsequence.Composition(bpm=120)

    @composition.pattern(channel=1, beats=4, cc_name_map=CC_MAP)
    def sweep(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        p.cc("filter_cutoff", 100)

    # The pattern is registered as pending — verify it carries the cc_name_map
    assert len(composition._pending_patterns) == 1
    assert composition._pending_patterns[0].cc_name_map is CC_MAP


# --- nrpn_name_map (parallel to cc_name_map) ---


NRPN_MAP = {"osc1_freq_fine": 9, "filter_freq": 29, "lfo1_amt": 62}


def test_nrpn_string_resolves_via_nrpn_name_map() -> None:
    """A string NRPN name should resolve via nrpn_name_map."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=0,
        nrpn_name_map=NRPN_MAP,
        default_grid=16,
    )
    builder.nrpn("filter_freq", 100, null_reset=False)

    # CC 99 (NRPN MSB) = 0; CC 98 (NRPN LSB) = 29 (filter_freq)
    assert pattern.cc_events[0].value == 0
    assert pattern.cc_events[1].value == 29


def test_nrpn_name_map_passed_through_decorator() -> None:
    """nrpn_name_map should flow from @composition.pattern() to PatternBuilder."""

    import subsequence

    composition = subsequence.Composition(bpm=120)

    @composition.pattern(channel=1, beats=4, nrpn_name_map=NRPN_MAP)
    def sweep(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        p.nrpn("filter_freq", 500, fine=True)

    # Pattern registered as pending — confirm the map is carried through
    assert len(composition._pending_patterns) == 1
    assert composition._pending_patterns[0].nrpn_name_map is NRPN_MAP


def test_nrpn_unknown_string_with_map_raises() -> None:
    """Strings absent from nrpn_name_map raise ValueError."""

    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    builder = subsequence.pattern_builder.PatternBuilder(
        pattern=pattern,
        cycle=0,
        nrpn_name_map=NRPN_MAP,
        default_grid=16,
    )

    with pytest.raises(ValueError, match="Unknown NRPN name"):
        builder.nrpn("not_in_map", 50)
