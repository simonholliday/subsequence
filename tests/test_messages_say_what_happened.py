"""A message says what really happened (#3530, from the documentation side's pre-tag check #3521).

composition.web_ui() failed as a bare AttributeError, naming nothing, after #3052 retired it.  A
render logged "Playing sequence. Press Ctrl+C to stop." and "Panic: sending all notes off.",
though it plays nothing live and sends nothing.  And the velocity floor said MIDI cannot carry a
0, which it can: a note-on at velocity 0 is a note-off.
"""

import asyncio
import logging
import pathlib
import typing

import pytest

import subsequence
import subsequence.composition
import subsequence.pattern
import subsequence.pattern_builder


def _builder () -> subsequence.pattern_builder.PatternBuilder:

	pattern = subsequence.pattern.Pattern(channel=0, length=4)

	return subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=16)


def test_web_ui_says_what_replaced_it () -> None:

	with pytest.raises(AttributeError, match=r"web_ui\(\) was retired in 0\.7\.0.*display\(\).*Superconductor"):
		subsequence.Composition(bpm=120).web_ui()		# type: ignore[attr-defined]


def test_any_other_missing_attribute_is_the_error_python_gives () -> None:

	"""A guard: only a retired name is given its story, and hasattr() still says no.  This held before as well."""

	composition = subsequence.Composition(bpm=120)

	with pytest.raises(AttributeError, match=r"^'Composition' object has no attribute 'web_uii'$"):
		composition.web_uii		# type: ignore[attr-defined]

	assert not hasattr(composition, "web_ui")


def test_a_render_says_neither_that_it_plays_nor_that_it_sends (tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:

	composition = subsequence.Composition(bpm=480)
	composition.pattern(channel=1, beats=4)(lambda p: p.note(60, beat=0))

	with caplog.at_level(logging.INFO):
		composition.render(bars=1, filename=str(tmp_path / "render.mid"))

	said = [record.getMessage() for record in caplog.records]

	assert any("Rendering" in line for line in said), f"nothing was captured to judge: {said}"
	assert [line for line in said if "Ctrl+C" in line or "Panic" in line] == []


class _Finished:

	"""A sequencer whose run is over as soon as it starts: enough to hear what run_until_stopped() says."""

	def __init__ (self, render_mode: bool) -> None:

		self.render_mode = render_mode
		self.task: typing.Optional[asyncio.Future] = None

	async def start (self) -> None:

		self.task = asyncio.get_running_loop().create_future()
		self.task.set_result(None)

	async def stop (self) -> None:

		return None


async def test_playing_live_still_says_how_to_stop (caplog: pytest.LogCaptureFixture) -> None:

	"""A guard: the live run keeps its instruction; only a render lost it.  This held before as well."""

	with caplog.at_level(logging.INFO):
		await subsequence.composition.run_until_stopped(_Finished(render_mode=False))		# type: ignore[arg-type]

	assert "Playing sequence. Press Ctrl+C to stop." in [record.getMessage() for record in caplog.records]


def test_a_zero_velocity_floor_is_refused_for_what_it_is () -> None:

	with pytest.raises(ValueError, match="A note-on at velocity 0 is a note-off, so the note would never sound") as refused:
		_builder().hit_steps(60, [0], velocity=(0, 100))

	assert "cannot carry" not in str(refused.value)


def test_a_number_midi_cannot_carry_still_says_so () -> None:

	"""A guard: above 127 MIDI really cannot carry it.  This held before as well."""

	with pytest.raises(ValueError, match="MIDI cannot carry it"):
		_builder().hit_steps(60, [0], velocity=(1, 160))
