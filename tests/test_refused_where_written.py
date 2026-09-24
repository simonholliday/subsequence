"""A value the package cannot use is refused where it is written, not wherever it first fails (#3561).

An infinite tempo was accepted, and hung the loop; OSC could send one.  A key or scale name the
package could not read was accepted by ``Composition`` and ``Section``, and then failed on every
build, logged rather than raised.  A Link quantum of zero was recorded without a word.
"""

import logging
import math
import typing

import pytest

import subsequence
import subsequence.forms
import subsequence.intervals
import subsequence.osc


NOT_A_TEMPO = [math.inf, math.nan]
IDS = ["inf", "nan"]


@pytest.mark.parametrize("bpm", NOT_A_TEMPO, ids = IDS)
def test_set_bpm_refuses_a_tempo_that_is_not_a_finite_number (patch_midi: None, bpm: float) -> None:

	"""set_bpm(inf) was accepted, and it hung the loop (the review's L1)."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)

	with pytest.raises(ValueError, match = "BPM must be positive and finite"):
		composition.set_bpm(bpm)

	assert composition.bpm == 120


@pytest.mark.parametrize("bpm", NOT_A_TEMPO, ids = IDS)
def test_target_bpm_refuses_a_tempo_that_is_not_a_finite_number (patch_midi: None, bpm: float) -> None:

	"""The ramp's target is held to the same rule."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)

	with pytest.raises(ValueError, match = "Target BPM must be positive and finite"):
		composition.target_bpm(bpm, bars = 4)


@pytest.mark.parametrize("bpm", NOT_A_TEMPO, ids = IDS)
def test_a_composition_refuses_a_starting_tempo_that_is_not_a_finite_number (patch_midi: None, bpm: float) -> None:

	"""The starting tempo goes through set_bpm(), so it is refused at construction."""

	with pytest.raises(ValueError, match = "BPM must be positive and finite"):
		subsequence.Composition(output_device = "Dummy MIDI", bpm = bpm)


def test_an_infinite_tempo_over_osc_is_refused_with_a_warning (patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	"""/bpm inf raised OverflowError from int(), which the handler did not catch, so it came out as a traceback."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)
	server = subsequence.osc.OscServer(composition)

	with caplog.at_level(logging.WARNING):
		server._handle_bpm("/bpm", math.inf)

	assert "Invalid OSC BPM argument" in caplog.text
	assert composition.bpm == 120


@pytest.mark.parametrize("kwargs, message", [
	({"key": "H"}, r"Unknown key name: 'H'"),
	({"key": "C", "scale": "dorain"}, r"Unknown mode 'dorain'\. Did you mean 'dorian'\?"),
], ids = ["key", "scale"])
def test_a_composition_refuses_a_name_it_cannot_read (patch_midi: None, kwargs: typing.Dict[str, str], message: str) -> None:

	"""Composition(key="H") and scale="dorain" were accepted, then failed on every build."""

	with pytest.raises(ValueError, match = message):
		subsequence.Composition(output_device = "Dummy MIDI", bpm = 120, **kwargs)


@pytest.mark.parametrize("kwargs, message", [
	({"key": "H"}, r"Unknown key name: 'H'"),
	({"scale": "dorain"}, r"Unknown mode 'dorain'\. Did you mean 'dorian'\?"),
], ids = ["key", "scale"])
def test_a_section_refuses_a_name_it_cannot_read (kwargs: typing.Dict[str, str], message: str) -> None:

	"""A section's override was accepted and failed each time the section built."""

	with pytest.raises(ValueError, match = message):
		subsequence.forms.Section("verse", 8, **kwargs)


@pytest.mark.parametrize("quantum", [0, -4, math.inf], ids = ["zero", "negative", "inf"])
def test_link_refuses_a_quantum_that_is_not_a_positive_number (patch_midi: None, quantum: float) -> None:

	"""Checked before aalink is, so the refusal comes whether or not Link is installed."""

	composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 120)

	with pytest.raises(ValueError, match = "link\\(quantum=\\) is a positive number of beats"):
		composition.link(quantum = quantum)


def test_names_and_tempos_it_can_read_are_accepted (patch_midi: None) -> None:

	"""A guard: every spelling the readers know still constructs, a scale registered first included."""

	name = "refused_where_written_scale"

	try:
		subsequence.register_scale(name, [0, 2, 3, 5, 7, 9, 10])

		for key, scale in (("Eb", "dorian"), ("F#", "minor"), ("Cb", "hirajoshi"), ("C", name)):
			composition = subsequence.Composition(output_device = "Dummy MIDI", bpm = 97.5, key = key, scale = scale)
			assert composition.key == key

		subsequence.forms.Section("verse", 8, key = "Bb", scale = name)

	finally:
		subsequence.intervals.INTERVAL_DEFINITIONS.pop(name, None)
		subsequence.intervals.SCALE_MODE_MAP.pop(name, None)
