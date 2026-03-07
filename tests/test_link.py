"""Tests for Ableton Link integration (link_clock module + Composition.link())."""

import sys
import types
import unittest.mock

import pytest

import subsequence
import subsequence.link_clock
import subsequence.sequencer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_composition(patch_midi: None) -> subsequence.Composition:
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
	result = comp.link(quantum=4.0)

	assert comp._link_quantum == 4.0
	assert result is comp


def test_link_default_quantum (patch_midi: None) -> None:

	"""link() defaults to quantum=4.0 (one bar in 4/4)."""

	comp = _make_composition(patch_midi)
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
