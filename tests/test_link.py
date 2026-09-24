"""Tests for Ableton Link integration (link_clock module + Composition.link())."""

import asyncio
import contextlib
import math
import sys
import types
import typing
import unittest.mock
import warnings

import pytest

import subsequence
import subsequence.link_clock
import subsequence.sequencer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_composition (patch_midi: None) -> subsequence.Composition:
	return subsequence.Composition(output_device="Dummy MIDI", bpm=120)


# ---------------------------------------------------------------------------
# _require_aalink()
# ---------------------------------------------------------------------------

def test_require_aalink_raises_when_not_installed () -> None:

	"""_require_aalink() raises RuntimeError with install instructions when aalink is absent."""

	with unittest.mock.patch.dict(sys.modules, {"aalink": None}):
		with pytest.raises(RuntimeError) as exc_info:
			subsequence.link_clock._require_aalink()

	assert "pip install subsequence[link]" in str(exc_info.value)


def test_require_aalink_succeeds_when_installed () -> None:

	"""_require_aalink() returns the aalink module when it is available."""

	fake_aalink = types.ModuleType("aalink")
	with unittest.mock.patch.dict(sys.modules, {"aalink": fake_aalink}):
		result = subsequence.link_clock._require_aalink()

	assert result is fake_aalink


# ---------------------------------------------------------------------------
# Composition.link()
# ---------------------------------------------------------------------------

def test_link_quantum_default_is_none (patch_midi: None) -> None:

	"""_link_quantum should be None when link() has not been called."""

	comp = _make_composition(patch_midi)
	assert comp._link_quantum is None


def test_link_sets_quantum (patch_midi: None) -> None:

	"""link() stores the quantum and returns self for method chaining."""

	comp = _make_composition(patch_midi)

	# link() eagerly requires aalink; mock its presence so this test exercises
	# quantum storage regardless of whether the optional extra is installed.
	fake_aalink = types.ModuleType("aalink")
	with unittest.mock.patch.dict(sys.modules, {"aalink": fake_aalink}):
		result = comp.link(quantum=4.0)

	assert comp._link_quantum == 4.0
	assert result is comp


def test_link_default_quantum (patch_midi: None) -> None:

	"""link() defaults to quantum=4.0 (one bar in 4/4)."""

	comp = _make_composition(patch_midi)

	# link() eagerly requires aalink; mock its presence (see test_link_sets_quantum).
	fake_aalink = types.ModuleType("aalink")
	with unittest.mock.patch.dict(sys.modules, {"aalink": fake_aalink}):
		comp.link()

	assert comp._link_quantum == 4.0


def test_link_raises_when_aalink_not_installed (patch_midi: None) -> None:

	"""link() raises RuntimeError with install instructions when aalink is missing."""

	comp = _make_composition(patch_midi)

	with unittest.mock.patch.dict(sys.modules, {"aalink": None}):
		with pytest.raises(RuntimeError) as exc_info:
			comp.link()

	assert "pip install subsequence[link]" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Sequencer._link_clock default and set_bpm() delegation
# ---------------------------------------------------------------------------

def test_sequencer_link_clock_default_is_none (patch_midi: None) -> None:

	"""_link_clock should be None on a freshly constructed Sequencer."""

	comp = _make_composition(patch_midi)
	assert comp._sequencer._link_clock is None


def test_set_bpm_delegates_to_link_when_active (patch_midi: None) -> None:

	"""set_bpm() on the Sequencer proposes tempo to Link and returns early when running with Link."""

	comp = _make_composition(patch_midi)
	seq = comp._sequencer

	mock_link_clock = unittest.mock.Mock()
	seq._link_clock = mock_link_clock
	seq.running = True  # simulate active playback

	seq.set_bpm(140.0)

	mock_link_clock.request_tempo.assert_called_once_with(140.0)
	# Local BPM should NOT be updated — Link is authoritative
	assert seq.current_bpm == 120.0  # unchanged from construction


def test_set_bpm_does_not_delegate_when_not_running (patch_midi: None) -> None:

	"""set_bpm() should update locally (not delegate to Link) when the sequencer is not running."""

	comp = _make_composition(patch_midi)
	seq = comp._sequencer

	mock_link_clock = unittest.mock.Mock()
	seq._link_clock = mock_link_clock
	# seq.running is False by default

	seq.set_bpm(140.0)

	mock_link_clock.request_tempo.assert_not_called()
	assert seq.current_bpm == 140.0  # updated locally


def test_set_target_bpm_ignored_under_link (patch_midi: None) -> None:

	"""A tempo ramp is a no-op under Ableton Link — the network tempo is authoritative."""

	comp = _make_composition(patch_midi)
	seq = comp._sequencer

	mock_link_clock = unittest.mock.Mock()
	seq._link_clock = mock_link_clock
	seq.running = True  # simulate active playback under Link

	seq.set_target_bpm(160.0, bars=8)

	# No local ramp is created, and Link is not asked to ramp.
	assert seq._bpm_transition is None
	mock_link_clock.request_tempo.assert_not_called()


@pytest.mark.asyncio
async def test_a_link_session_hands_aalink_no_loop (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""aalink 0.2 and later take the running loop themselves, and warn whenever Link() is handed one (#3555).

	The stand-in warns as aalink's own source does (``src/aalink.cpp`` in 0.2 and 0.2.3), and the
	composition joins the session through its real path, ``_run()``.
	"""

	made: typing.List[typing.Any] = []

	class Link:

		enabled = False
		quantum = 4.0
		num_peers = 0
		playing = False

		def __init__ (self, bpm: float, loop: typing.Any = None) -> None:

			if loop is not None:
				warnings.warn(
					"The 'loop' parameter is deprecated and will be removed in future versions of aalink",
					DeprecationWarning,
					stacklevel = 2,
				)

			self.loop = loop if loop is not None else asyncio.get_running_loop()
			self.tempo = float(bpm)
			self.beat = 0.0
			made.append(self)

		def __setattr__ (self, name: str, value: typing.Any) -> None:

			if name == "enabled":
				self.__dict__.setdefault("enabled_history", []).append(value)

			object.__setattr__(self, name, value)

		async def sync (self, period: float) -> float:

			await asyncio.sleep(0.001)
			self.beat = (math.floor(self.beat / period + 1e-9) + 1) * period

			return self.beat

	fake_aalink = types.ModuleType("aalink")
	fake_aalink.Link = Link		# type: ignore[attr-defined]
	monkeypatch.setitem(sys.modules, "aalink", fake_aalink)

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 132)
	composition.link(quantum = 4)

	with warnings.catch_warnings(record = True) as caught:

		warnings.simplefilter("always")

		with contextlib.suppress(asyncio.TimeoutError):
			await asyncio.wait_for(composition._run(), timeout = 0.3)

	assert made, "the run never joined the session"
	assert made[0].loop is asyncio.get_running_loop()
	assert made[0].enabled_history == [True, False], "it should join the session, then leave it at the stop"
	assert [str(warning.message) for warning in caught if issubclass(warning.category, DeprecationWarning)] == []
