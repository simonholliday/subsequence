"""Tests for composition.render() — limits, safety cap, and validation."""

import pathlib
import pytest

import subsequence


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def test_render_raises_when_both_limits_are_none (patch_midi: None) -> None:

	"""render(bars=None, max_minutes=None) must raise ValueError immediately."""

	composition = subsequence.Composition(bpm=120)

	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	with pytest.raises(ValueError, match="at least one limit"):
		composition.render(bars=None, max_minutes=None)


def test_render_accepts_bars_only (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""render(bars=N, max_minutes=None) completes without error and stops at bar N."""

	filename = str(tmp_path / "out.mid")
	composition = subsequence.Composition(bpm=480)

	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	# Should complete without raising — output file may be empty (no recorded notes
	# with patch_midi) but no exception means the bar limit worked correctly.
	composition.render(bars=4, max_minutes=None, filename=filename)
	assert composition._sequencer.current_bar >= 4


def test_render_accepts_max_minutes_only (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""render(bars=None, max_minutes=M) completes without error and stops at the time cap."""

	filename = str(tmp_path / "out.mid")
	composition = subsequence.Composition(bpm=120)

	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	# A tiny cap (0.001 min = 0.06 s of MIDI) stops quickly without error.
	composition.render(bars=None, max_minutes=0.001, filename=filename)
	# The render stopped, so elapsed time should be very small
	assert composition._sequencer._render_elapsed_seconds <= 0.1


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

def test_render_default_max_minutes_is_60 (patch_midi: None) -> None:

	"""The sequencer receives render_max_seconds = 3600 when max_minutes is unset."""

	composition = subsequence.Composition(bpm=120)

	# Peek at what render() would pass: call the sequencer setup path without
	# actually running the async loop by inspecting the attribute assignment.
	# We trigger the ValueError path to confirm the default is NOT None.
	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	# Monkey-patch asyncio.run to intercept without running
	import asyncio
	import unittest.mock as mock

	with mock.patch("asyncio.run"):
		composition.render(filename="dummy.mid")

	assert composition._sequencer.render_max_seconds == pytest.approx(3600.0)


def test_render_default_bars_is_none (patch_midi: None) -> None:

	"""render() with no arguments sets render_bars = 0 (unlimited) on the sequencer."""

	composition = subsequence.Composition(bpm=120)

	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	import asyncio
	import unittest.mock as mock

	with mock.patch("asyncio.run"):
		composition.render(filename="dummy.mid")

	assert composition._sequencer.render_bars == 0


# ---------------------------------------------------------------------------
# Time cap stops render
# ---------------------------------------------------------------------------

def test_render_stops_at_time_cap (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""A very small max_minutes cap stops the render before reaching many bars."""

	filename = str(tmp_path / "short.mid")
	# At 120 BPM, 1 bar = 2 seconds. A 0.01-minute (0.6 s) cap should stop
	# the render well before bar 100.
	composition = subsequence.Composition(bpm=120)

	@composition.pattern(channel=0, length=4)
	def p (p) -> None:
		pass

	composition.render(bars=100, max_minutes=0.01, filename=filename)

	# The sequencer should have stopped early (elapsed < 100 bars).
	assert composition._sequencer.current_bar < 100
