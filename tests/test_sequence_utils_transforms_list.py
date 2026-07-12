import pytest

import subsequence.sequence_utils


TILE = subsequence.sequence_utils.tile
MASK = subsequence.sequence_utils.mask
CHOKE = subsequence.sequence_utils.choke
DISPLACE = subsequence.sequence_utils.displace


# --- tile ---


def test_tile_non_multiple() -> None:
    """Cycling to a non-multiple length truncates mid-pattern."""

    assert TILE([1, 0, 0], 8) == [1, 0, 0, 1, 0, 0, 1, 0]


def test_tile_exact_multiple() -> None:
    """An exact multiple repeats whole cells."""

    assert TILE([1, 0, 0], 6) == [1, 0, 0, 1, 0, 0]


def test_tile_shorter_than_pattern() -> None:
    """A length below the pattern length truncates it."""

    assert TILE([1, 2, 3, 4], 2) == [1, 2]


def test_tile_preserves_type() -> None:
    """tile is type-agnostic (works on any element type)."""

    assert TILE(["a", "b"], 3) == ["a", "b", "a"]


def test_tile_zero_length() -> None:
    """length <= 0 yields an empty list."""

    assert TILE([1, 0], 0) == []


def test_tile_negative_length() -> None:
    """A negative length yields an empty list."""

    assert TILE([1, 0], -4) == []


def test_tile_empty_raises() -> None:
    """Tiling an empty sequence to a positive length is an error."""

    with pytest.raises(ValueError) as exc:
        TILE([], 8)
    assert "cannot tile an empty sequence" in str(exc.value)


def test_tile_empty_zero_length_ok() -> None:
    """An empty sequence with length 0 is a clean empty list (no raise)."""

    assert TILE([], 0) == []


# --- mask (keep where active) ---


def test_mask_against_parallel() -> None:
    """A parallel part keeps where it is truthy."""

    assert MASK([9, 9, 9, 9], against=[1, 0, 1, 0]) == [9, 0, 9, 0]


def test_mask_against_truthy_density() -> None:
    """Non-zero density values count as active."""

    assert MASK([5, 6, 7], against=[0.3, 0.0, 0.9]) == [5, 0, 7]


def test_mask_steps_indices() -> None:
    """An index collection keeps only those positions."""

    assert MASK([9, 9, 9, 9], steps=[0, 2]) == [9, 0, 9, 0]


def test_mask_custom_zero() -> None:
    """The off-value is configurable."""

    assert MASK([9, 9, 9], against=[1, 0, 1], zero=-1) == [9, -1, 9]


def test_mask_zero_default_vs_float() -> None:
    """Default off-value is 0; pass zero=0.0 to keep floats float."""

    assert MASK([0.5, 0.5], against=[1, 0]) == [0.5, 0]
    assert MASK([0.5, 0.5], against=[1, 0], zero=0.0) == [0.5, 0.0]


def test_mask_against_shorter_repeats_last() -> None:
    """A short parallel part repeats its last value."""

    assert MASK([9, 9, 9, 9], against=[1, 0]) == [9, 0, 0, 0]


def test_mask_against_longer_truncates() -> None:
    """A long parallel part is bounded by the sequence length."""

    assert MASK([9, 9], against=[1, 1, 1, 1]) == [9, 9]


def test_mask_against_empty_inactive() -> None:
    """An empty parallel part is inactive everywhere."""

    assert MASK([9, 9], against=[]) == [0, 0]


def test_mask_steps_out_of_range_ignored() -> None:
    """Indices outside the sequence are ignored."""

    assert MASK([9, 9], steps=[0, 5, -3]) == [9, 0]


def test_mask_empty_sequence() -> None:
    """An empty sequence yields an empty list."""

    assert MASK([], against=[1]) == []


def test_mask_type_agnostic() -> None:
    """mask preserves arbitrary element types and off-values."""

    assert MASK(["x", "y"], against=[1, 0], zero=None) == ["x", None]


def test_mask_both_raises() -> None:
    """Passing both against and steps is an error."""

    with pytest.raises(ValueError) as exc:
        MASK([1], against=[1], steps=[0])
    assert "exactly one of against= or steps=" in str(exc.value)


def test_mask_neither_raises() -> None:
    """Passing neither against nor steps is an error."""

    with pytest.raises(ValueError) as exc:
        MASK([1])
    assert "exactly one of against= or steps=" in str(exc.value)


# --- choke (suppress where active) ---


def test_choke_against_parallel() -> None:
    """A parallel part suppresses where it is truthy."""

    assert CHOKE([9, 9, 9, 9], against=[1, 0, 1, 0]) == [0, 9, 0, 9]


def test_choke_steps_indices() -> None:
    """An index collection suppresses those positions."""

    assert CHOKE([9, 9, 9, 9], steps=[0, 2]) == [0, 9, 0, 9]


def test_choke_custom_floor() -> None:
    """The suppressed value is configurable."""

    assert CHOKE([9, 9], against=[1, 0], floor=-1) == [-1, 9]


def test_choke_against_shorter_repeats_last() -> None:
    """A short parallel part repeats its last value."""

    assert CHOKE([9, 9, 9, 9], against=[1, 0]) == [0, 9, 9, 9]


def test_choke_steps_out_of_range_ignored() -> None:
    """Indices outside the sequence are ignored."""

    assert CHOKE([9, 9], steps=[5]) == [9, 9]


def test_choke_both_raises() -> None:
    """Passing both against and steps is an error."""

    with pytest.raises(ValueError):
        CHOKE([1], against=[1], steps=[0])


def test_choke_neither_raises() -> None:
    """Passing neither against nor steps is an error."""

    with pytest.raises(ValueError):
        CHOKE([1])


# --- the complementarity law ---


def test_choke_is_mask_of_complement() -> None:
    """choke(seq, against=x) equals mask(seq, against=NOT x)."""

    seq = [3, 5, 7, 9, 2, 4]
    sel = [1, 0, 1, 0, 1, 1]
    not_sel = [0 if v else 1 for v in sel]
    assert CHOKE(seq, against=sel) == MASK(seq, against=not_sel)


def test_mask_choke_partition() -> None:
    """At each step exactly one of mask/choke keeps the original value."""

    seq = [3, 5, 7, 9, 2, 4]
    sel = [1, 0, 1, 0, 1, 1]
    masked = MASK(seq, against=sel)
    choked = CHOKE(seq, against=sel)

    for original, m, c in zip(seq, masked, choked):
        assert (m == original) != (c == original)


# --- displace (phase-shift a pattern, wrapping) ---


def test_displace_positive_moves_later() -> None:
    """A positive amount pushes content later (right), wrapping the tail to the front."""

    assert DISPLACE([1, 0, 0, 0], 1) == [0, 1, 0, 0]
    assert DISPLACE([1, 2, 3, 4], 1) == [4, 1, 2, 3]


def test_displace_negative_moves_earlier() -> None:
    """A negative amount pulls content earlier (left)."""

    assert DISPLACE([0, 1, 0, 0], -1) == [1, 0, 0, 0]


def test_displace_zero_is_unchanged_copy() -> None:
    """amount 0 returns an equal but fresh list (never the same object)."""

    original = [1, 2, 3, 4]
    result = DISPLACE(original, 0)

    assert result == original
    assert result is not original


def test_displace_full_revolution() -> None:
    """A whole-length shift is a full revolution — unchanged."""

    assert DISPLACE([1, 2, 3, 4], 4) == [1, 2, 3, 4]


def test_displace_over_length_wraps() -> None:
    """An over-length amount wraps modulo the length."""

    assert DISPLACE([1, 0, 0, 0], 5) == DISPLACE([1, 0, 0, 0], 1)


def test_displace_empty() -> None:
    """An empty sequence is a no-op (and the divide-by-zero guard)."""

    assert DISPLACE([], 3) == []


def test_displace_single_element() -> None:
    """A single-element list is unchanged for any amount."""

    assert DISPLACE([9], 7) == [9]


def test_displace_type_agnostic() -> None:
    """displace reorders any element type."""

    assert DISPLACE(["a", "b", "c"], 1) == ["c", "a", "b"]


def test_displace_does_not_mutate_input() -> None:
    """The original sequence is left untouched."""

    original = [1, 0, 1, 0]
    DISPLACE(original, 2)

    assert original == [1, 0, 1, 0]
