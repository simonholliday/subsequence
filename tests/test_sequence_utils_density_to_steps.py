import random

import pytest

import subsequence.sequence_utils


D2S = subsequence.sequence_utils.density_to_steps


def test_matches_hand_idiom_seeded() -> None:
    """A seeded run reproduces [i for i in range(n) if rng.random() < d[i]] exactly."""

    density = [0.9, 0.1, 0.5, 0.2, 0.8, 0.3, 0.6, 0.0]

    expected_rng = random.Random(42)
    expected = [i for i in range(len(density)) if expected_rng.random() < density[i]]

    actual = D2S(density, random.Random(42))

    assert actual == expected


def test_returns_ascending_indices() -> None:
    """Fired indices come back in ascending step order."""

    result = D2S([0.99] * 8, random.Random(1))

    assert result == sorted(result)


def test_all_high_fires_every_step() -> None:
    """Densities at or above 1.0 always fire — the full index list."""

    assert D2S([1.0, 1.5, 1.0, 2.0], random.Random(7)) == [0, 1, 2, 3]


def test_all_zero_fires_nothing() -> None:
    """Densities at or below 0.0 never fire; an empty result is normal, not an error."""

    assert D2S([0.0, -0.5, 0.0], random.Random(7)) == []


def test_empty_density_is_noop() -> None:
    """An empty density list places nothing (no-op)."""

    assert D2S([], random.Random(7)) == []


def test_scalar_requires_length() -> None:
    """A scalar density with no length is the lone meaningless-input raise."""

    with pytest.raises(ValueError) as exc:
        D2S(0.5, random.Random(7))
    assert "length" in str(exc.value)


def test_scalar_with_length_reproduces_idiom() -> None:
    """A scalar density rolls *length* independent draws, matching the hand idiom."""

    expected_rng = random.Random(99)
    expected = [i for i in range(16) if expected_rng.random() < 0.4]

    actual = D2S(0.4, random.Random(99), 16)

    assert actual == expected


def test_scalar_zero_or_negative_length_is_noop() -> None:
    """A zero or negative grid places nothing."""

    assert D2S(0.5, random.Random(7), 0) == []
    assert D2S(0.5, random.Random(7), -3) == []


def test_list_density_ignores_redundant_length() -> None:
    """A redundant length on a list density is ignored (len(density) is the grid)."""

    density = [0.9, 0.1, 0.8, 0.2]

    from_list = D2S(density, random.Random(5))
    with_length = D2S(density, random.Random(5), 99)

    assert from_list == with_length
    assert all(i < len(density) for i in with_length)
