import mido
import pytest

import subsequence.midi as midi


def test_cc_returns_control_change() -> None:
	msg = midi.cc(74, 100)
	assert msg.type == 'control_change'
	assert msg.control == 74
	assert msg.value == 100
	assert msg.channel == 0


def test_cc_custom_channel() -> None:
	msg = midi.cc(1, 64, channel=3)
	assert msg.channel == 3


def test_cc_value_clamped_by_mido() -> None:
	# mido raises on out-of-range values — verify our factory passes through
	with pytest.raises(Exception):
		midi.cc(74, 200)


def test_pitchwheel_returns_pitchwheel() -> None:
	msg = midi.pitchwheel(0)
	assert msg.type == 'pitchwheel'
	assert msg.pitch == 0
	assert msg.channel == 0


def test_pitchwheel_min() -> None:
	msg = midi.pitchwheel(-8192)
	assert msg.pitch == -8192


def test_pitchwheel_max() -> None:
	msg = midi.pitchwheel(8191)
	assert msg.pitch == 8191


def test_pitchwheel_custom_channel() -> None:
	msg = midi.pitchwheel(1000, channel=2)
	assert msg.channel == 2


def test_program_change_returns_program_change() -> None:
	msg = midi.program_change(10)
	assert msg.type == 'program_change'
	assert msg.program == 10
	assert msg.channel == 0


def test_program_change_custom_channel() -> None:
	msg = midi.program_change(0, channel=1)
	assert msg.channel == 1


def test_cc_usable_as_cc_forward_transform() -> None:
	"""Verify the factory is usable as a cc_forward lambda."""
	transform = lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch)
	result = transform(127, 0)
	assert result.type == 'control_change'
	assert result.control == 74
	assert result.value == 100
	assert result.channel == 0
