"""key_pull= is the one name for the pull toward the key, wherever the engine walks (#3524).

f345f16 retired harmony(gravity=) for key_pull=, which reads the natural way round
(key_pull = 1 - gravity).  progression() and Progression.generate() went on taking gravity= the
old way round and refusing key_pull=, though both said they took the engine's parameters exactly
as harmony() does.  Found by the documentation side's pre-tag check (#3521).
"""

import typing

import pytest

import subsequence
import subsequence.harmonic_state


STYLE = {"style": "functional_major", "key": "C", "bars": 4, "seed": 1}


def _blends (monkeypatch: pytest.MonkeyPatch, make: typing.Callable[[], typing.Any]) -> typing.List[typing.Any]:

	"""The key_gravity_blend each engine built by *make* is given."""

	seen: typing.List[typing.Any] = []
	building = subsequence.harmonic_state.HarmonicState.__init__

	def spy (self: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
		seen.append(kwargs.get("key_gravity_blend"))
		building(self, *args, **kwargs)

	monkeypatch.setattr(subsequence.harmonic_state.HarmonicState, "__init__", spy)
	make()

	return seen


@pytest.mark.parametrize("key_pull", [0.0, 0.3, 1.0])
def test_both_factories_take_key_pull_the_way_harmony_does (key_pull: float, monkeypatch: pytest.MonkeyPatch) -> None:

	"""key_pull=1.0 is the strongest pull, which the engine reads as a blend of 0.0, as harmony() gives it."""

	assert _blends(monkeypatch, lambda: subsequence.progression(**STYLE, key_pull=key_pull)) == [1.0 - key_pull]
	assert _blends(monkeypatch, lambda: subsequence.Progression.generate(**STYLE, key_pull=key_pull)) == [1.0 - key_pull]


def test_left_out_it_walks_as_it_always_did (monkeypatch: pytest.MonkeyPatch) -> None:

	"""A guard: the default key_pull=0.0 is the blend of 1.0 that gravity=1.0, the old default, gave.  This held before as well."""

	assert _blends(monkeypatch, lambda: subsequence.progression(**STYLE)) == [1.0]
	assert _blends(monkeypatch, lambda: subsequence.Progression.generate(**STYLE)) == [1.0]


@pytest.mark.parametrize("name", ["progression", "Progression.generate"])
def test_gravity_is_refused_with_its_conversion (name: str) -> None:

	make = subsequence.progression if name == "progression" else subsequence.Progression.generate

	with pytest.raises(TypeError, match=rf"^{name.replace('.', '[.]')}\(\): gravity= has been retired .* Convert with key_pull = 1 - gravity"):
		make(**STYLE, gravity=0.5)


def test_an_unknown_keyword_is_refused_by_name () -> None:

	"""A guard: the catch-all for retired names still refuses a keyword nobody ever took.  Python said the same before."""

	with pytest.raises(TypeError, match=r"progression\(\) got an unexpected keyword argument 'gravitas'"):
		subsequence.progression(**STYLE, gravitas=0.5)


def test_key_pull_outside_its_range_is_refused () -> None:

	with pytest.raises(ValueError, match=r"key_pull=1\.5\) takes 0\.0 to 1\.0"):
		subsequence.progression(**STYLE, key_pull=1.5)


def test_a_written_progression_refuses_key_pull_as_it_refuses_the_other_walk_parameters () -> None:

	with pytest.raises(ValueError, match="key_pull only apply when generating with style="):
		subsequence.progression(["C", "F"], key_pull=0.5)
