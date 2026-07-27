"""Tests for glob-based MIDI device name matching.

Device names carry a number that moves between runs (the ALSA sequencer client
id), so patterns need to pin the stable part and wildcard the volatile one.
These use realistic names rather than toy strings — the bugs worth catching only
show up against names with the real shape.
"""

import logging
import sys
import typing

import pytest

import subsequence.midi_utils


MATCH = subsequence.midi_utils.match_device_names


# Realistic ALSA output names: "<client>:<port> <CLIENT_ID>:<PORT_INDEX>".
# The client id moves between runs; the port index after it does not.
OUTPUTS = [
	"Midi Through:Midi Through Port-0 14:0",
	"U6MIDI Pro:U6MIDI Pro Port 1 16:0",
	"U6MIDI Pro:U6MIDI Pro Port 2 16:1",
	"U6MIDI Pro:U6MIDI Pro Port 3 16:2",
	"SC-U:SC-U MIDI 1 24:0",
	"RtMidiOut Client:Subsample Virtual MIDI 129:0",
]


def _names_of (indices: typing.List[int], names: typing.List[str]) -> typing.List[str]:

	"""Resolve match indices back to names, for readable assertions."""

	return [names[i] for i in indices]


class _FakeStdin:

	"""Stand-in for sys.stdin with a fixed isatty(), so tests don't depend on -s."""

	def __init__ (self, tty: bool) -> None:
		self._tty = tty

	def isatty (self) -> bool:
		return self._tty


# --- the matcher ---


def test_wildcard_free_pattern_is_a_substring () -> None:

	"""A pattern with no wildcards behaves as a substring — existing calls keep working."""

	assert _names_of(MATCH("SC-U", OUTPUTS), OUTPUTS) == ["SC-U:SC-U MIDI 1 24:0"]


def test_matching_is_case_insensitive () -> None:

	"""Case in the pattern is irrelevant."""

	assert MATCH("sc-u", OUTPUTS) == MATCH("SC-U", OUTPUTS)


def test_no_match_returns_empty () -> None:

	"""Nothing matching is an empty list, not an error."""

	assert MATCH("Prophet", OUTPUTS) == []


def test_multiport_interface_needs_the_port_index () -> None:

	"""The mistake users make: without a port index, a 3-port unit matches three times."""

	assert len(MATCH("*U6MIDI Pro*", OUTPUTS)) == 3
	assert _names_of(MATCH("*U6MIDI Pro *:0", OUTPUTS), OUTPUTS) == ["U6MIDI Pro:U6MIDI Pro Port 1 16:0"]


def test_wildcard_survives_a_moving_client_id () -> None:

	"""The whole point: one pattern matches the same port whatever id it lands on."""

	pattern = "*Subsample Virtual MIDI *:0"

	for client_id in ("128", "129", "145", "1290"):
		names = [f"RtMidiOut Client:Subsample Virtual MIDI {client_id}:0"]
		assert MATCH(pattern, names) == [0], f"failed for client id {client_id}"


def test_question_mark_stops_matching_at_an_extra_digit () -> None:

	"""Pins why the docs say to use ``*``: ``?`` is one character, so ids outgrow it."""

	two_digit = ["U6MIDI Pro:U6MIDI Pro Port 1 16:0"]
	three_digit = ["U6MIDI Pro:U6MIDI Pro Port 1 160:0"]

	assert MATCH("*Port 1 ??:0", two_digit) == [0]
	assert MATCH("*Port 1 ??:0", three_digit) == []


def test_square_bracket_is_literal_not_a_character_class () -> None:

	"""``[Pro]`` means the text "[Pro]", not "any of P, r, o"."""

	names = [
		"Some Synth [Pro] 20:0",
		"Corrode 21:0",	 # contains r and o — would match a character class
	]

	assert _names_of(MATCH("*[Pro]*", names), names) == ["Some Synth [Pro] 20:0"]


# --- exact match wins ---


def test_exact_name_wins_over_a_longer_name_containing_it () -> None:

	"""A full device name stays unambiguous even when another name contains it.

	Without this, adding a device called "Prophet Rev2" would make an existing
	pinned "Prophet" ambiguous and start prompting.
	"""

	names = ["Prophet", "Prophet Rev2"]

	assert _names_of(MATCH("Prophet", names), names) == ["Prophet"]


def test_exact_match_is_case_insensitive_too () -> None:

	"""The exact-wins shortcut does not become case-sensitive by accident."""

	names = ["Prophet", "Prophet Rev2"]

	assert _names_of(MATCH("prophet", names), names) == ["Prophet"]


def test_substring_still_matches_both_when_not_exact () -> None:

	"""Exact-wins is a tie-break, not a general narrowing — a partial still matches both."""

	names = ["Prophet", "Prophet Rev2"]

	assert len(MATCH("Proph", names)) == 2


# --- rtmidi direction prefix ---


def test_direction_prefix_means_patterns_should_start_with_a_wildcard () -> None:

	"""Virtual ports are prefixed per direction, so an anchored pattern misses one side."""

	out_name = ["RtMidiOut Client:Subsample Virtual MIDI 129:0"]

	assert MATCH("RtMidiIn Client:Subsample*", out_name) == []
	assert MATCH("*Subsample Virtual MIDI *:0", out_name) == [0]


# --- resolution: output logs and returns (None, None) ---


def test_ambiguous_output_without_a_terminal_names_only_the_candidates (
	monkeypatch: pytest.MonkeyPatch,
	caplog: pytest.LogCaptureFixture,
) -> None:

	"""An unattended ambiguous match fails usably, listing the matches and nothing else."""

	import mido

	monkeypatch.setattr(mido, "get_output_names", lambda: OUTPUTS)
	monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

	with caplog.at_level(logging.ERROR, logger="subsequence.midi_utils"):
		result = subsequence.midi_utils.select_output_device("*U6MIDI Pro*")

	assert result == (None, None)

	message = " ".join(record.getMessage() for record in caplog.records)
	assert "U6MIDI Pro Port 1 16:0" in message
	assert "U6MIDI Pro Port 3 16:2" in message
	# Only the matches — an unrelated device must not be listed as a candidate.
	assert "SC-U" not in message


def test_output_pattern_matching_one_device_opens_it (monkeypatch: pytest.MonkeyPatch) -> None:

	"""The ordinary case: a pattern naming one port opens that port."""

	import mido

	opened: typing.List[str] = []

	monkeypatch.setattr(mido, "get_output_names", lambda: OUTPUTS)
	monkeypatch.setattr(mido, "open_output", lambda name: opened.append(name) or object())

	name, port = subsequence.midi_utils.select_output_device("*U6MIDI Pro *:1")

	assert name == "U6MIDI Pro:U6MIDI Pro Port 2 16:1"
	assert opened == ["U6MIDI Pro:U6MIDI Pro Port 2 16:1"]


def test_output_pattern_matching_nothing_is_the_documented_failure (
	monkeypatch: pytest.MonkeyPatch,
	caplog: pytest.LogCaptureFixture,
) -> None:

	"""No match logs the available devices and returns (None, None) — it does not raise."""

	import mido

	monkeypatch.setattr(mido, "get_output_names", lambda: OUTPUTS)

	with caplog.at_level(logging.ERROR, logger="subsequence.midi_utils"):
		result = subsequence.midi_utils.select_output_device("Prophet")

	assert result == (None, None)
	assert any("not found" in record.getMessage() for record in caplog.records)


def test_ambiguous_output_prompts_when_a_terminal_is_present (monkeypatch: pytest.MonkeyPatch) -> None:

	"""With a terminal, the choice is put to the user and the answer is honoured."""

	import mido

	monkeypatch.setattr(mido, "get_output_names", lambda: OUTPUTS)
	monkeypatch.setattr(mido, "open_output", lambda name: object())
	monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))
	monkeypatch.setattr("builtins.input", lambda prompt = "": "2")

	name, _ = subsequence.midi_utils.select_output_device("*U6MIDI Pro*")

	# Choice 2 of the three matches, not of the full device list.
	assert name == "U6MIDI Pro:U6MIDI Pro Port 2 16:1"


# --- resolution: input raises ---


def test_ambiguous_input_without_a_terminal_raises (monkeypatch: pytest.MonkeyPatch) -> None:

	"""Input fails closed — listening to the wrong device would mis-record a performance."""

	import mido

	monkeypatch.setattr(mido, "get_input_names", lambda: OUTPUTS)
	monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

	with pytest.raises(subsequence.midi_utils.DeviceSelectionError) as exc:
		subsequence.midi_utils.select_input_device("*U6MIDI Pro*")

	assert "U6MIDI Pro Port 1 16:0" in str(exc.value)
	assert "U6MIDI Pro Port 3 16:2" in str(exc.value)


def test_input_pattern_matching_nothing_still_raises_value_error (monkeypatch: pytest.MonkeyPatch) -> None:

	"""A typo matches nothing and raises, rather than falling back to another input."""

	import mido

	monkeypatch.setattr(mido, "get_input_names", lambda: OUTPUTS)

	with pytest.raises(ValueError, match="not found"):
		subsequence.midi_utils.select_input_device("U6MIDI Prot")


def test_input_pattern_matching_one_device_opens_it (monkeypatch: pytest.MonkeyPatch) -> None:

	"""A pattern naming one input port opens that port."""

	import mido

	monkeypatch.setattr(mido, "get_input_names", lambda: OUTPUTS)
	monkeypatch.setattr(mido, "open_input", lambda name, callback = None: object())

	name, port = subsequence.midi_utils.select_input_device("*U6MIDI Pro *:2")

	assert name == "U6MIDI Pro:U6MIDI Pro Port 3 16:2"
