import asyncio
import typing

import mido
import pytest

import subsequence
import subsequence.sequencer
import conftest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Event loops created by _make_sequencer, closed after each test by the
# autouse fixture below so they don't leak a ResourceWarning per test.
_created_input_loops: typing.List[asyncio.AbstractEventLoop] = []


def _make_sequencer (spy: conftest.SpyMidiOut) -> subsequence.sequencer.Sequencer:
	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
	)
	seq.midi_out = spy
	# _on_midi_input has an early-return guard on these; initialise them
	# so the CC mapping / forwarding code is reachable in unit tests.
	loop = asyncio.new_event_loop()
	_created_input_loops.append(loop)
	seq._midi_input_queue = asyncio.Queue()
	seq._input_loop = loop
	return seq


@pytest.fixture(autouse=True)
def _close_input_loops () -> typing.Iterator[None]:

	"""Close every input loop created during the test."""

	yield

	while _created_input_loops:
		_created_input_loops.pop().close()


def _cc_msg (control: int, value: int, channel: int = 0) -> mido.Message:
	return mido.Message('control_change', channel=channel, control=control, value=value)


# ---------------------------------------------------------------------------
# Composition API — registration
# ---------------------------------------------------------------------------

def test_cc_forward_stores_mapping (patch_midi: None) -> None:
	"""cc_forward() should append one entry to _cc_forwards."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "cc")
	assert len(comp._cc_forwards) == 1
	fwd = comp._cc_forwards[0]
	assert fwd['cc'] == 1
	assert fwd['mode'] == 'instant'
	assert callable(fwd['transform'])


def test_cc_forward_invalid_mode_raises (patch_midi: None) -> None:
	comp = subsequence.Composition(bpm=120)
	with pytest.raises(ValueError, match="mode"):
		comp.cc_forward(1, "cc", mode="realtime")


def test_cc_forward_invalid_cc_raises (patch_midi: None) -> None:
	comp = subsequence.Composition(bpm=120)
	with pytest.raises(ValueError):
		comp.cc_forward(200, "cc")


def test_cc_forward_coexists_with_cc_map (patch_midi: None) -> None:
	"""Same CC can be registered in both cc_map and cc_forward."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "cc")
	comp.cc_map(1, "mod_wheel")
	assert len(comp._cc_forwards) == 1
	assert len(comp._cc_mappings) == 1


# ---------------------------------------------------------------------------
# Transform presets
# ---------------------------------------------------------------------------

def test_preset_cc_identity (patch_midi: None) -> None:
	"""'cc' preset: identity forward, same CC number and value."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(74, "cc")
	transform = comp._cc_forwards[0]['transform']
	msg = transform(64, 0)
	assert msg is not None
	assert msg.type == 'control_change'
	assert msg.control == 74
	assert msg.value == 64


def test_preset_cc_remap (patch_midi: None) -> None:
	"""'cc:N' preset: forward as CC number N."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "cc:74")
	transform = comp._cc_forwards[0]['transform']
	msg = transform(100, 0)
	assert msg is not None
	assert msg.type == 'control_change'
	assert msg.control == 74
	assert msg.value == 100


def test_preset_cc_remap_invalid_raises (patch_midi: None) -> None:
	comp = subsequence.Composition(bpm=120)
	with pytest.raises(ValueError):
		comp.cc_forward(1, "cc:banana")


def test_preset_pitchwheel_min (patch_midi: None) -> None:
	"""'pitchwheel' preset: CC 0 → pitch -8192."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "pitchwheel")
	transform = comp._cc_forwards[0]['transform']
	msg = transform(0, 0)
	assert msg is not None
	assert msg.type == 'pitchwheel'
	assert msg.pitch == -8192


def test_preset_pitchwheel_max (patch_midi: None) -> None:
	"""'pitchwheel' preset: CC 127 → pitch 8191."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "pitchwheel")
	transform = comp._cc_forwards[0]['transform']
	msg = transform(127, 0)
	assert msg is not None
	assert msg.type == 'pitchwheel'
	assert msg.pitch == 8191


def test_preset_pitchwheel_midpoint (patch_midi: None) -> None:
	"""'pitchwheel' preset: CC 64 should be near 0."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "pitchwheel")
	transform = comp._cc_forwards[0]['transform']
	msg = transform(64, 0)
	assert msg is not None
	assert abs(msg.pitch) < 200  # close to 0


def test_callable_transform (patch_midi: None) -> None:
	"""User-supplied callable is stored and invoked correctly."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, lambda v, ch: mido.Message('control_change', channel=ch, control=74, value=v // 2))
	transform = comp._cc_forwards[0]['transform']
	msg = transform(100, 0)
	assert msg is not None
	assert msg.control == 74
	assert msg.value == 50


def test_callable_can_return_none (patch_midi: None) -> None:
	"""Callable returning None suppresses forwarding."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, lambda v, ch: None)
	transform = comp._cc_forwards[0]['transform']
	assert transform(64, 0) is None


def test_unknown_preset_raises (patch_midi: None) -> None:
	comp = subsequence.Composition(bpm=120)
	with pytest.raises(ValueError, match="unknown preset"):
		comp.cc_forward(1, "pitchbend")


# ---------------------------------------------------------------------------
# Sequencer — instant mode
# ---------------------------------------------------------------------------

def test_instant_sends_immediately (patch_midi: None) -> None:
	"""Instant forward should call midi_out.send() from _on_midi_input."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=74, value=v),
	}]
	seq._on_midi_input(_cc_msg(1, 64))
	assert len(spy.sent) == 1
	assert spy.sent[0].type == 'control_change'
	assert spy.sent[0].value == 64


def test_instant_channel_filter_match (patch_midi: None) -> None:
	"""Instant forward with channel filter should fire on matching channel."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': 2,  # 0-indexed
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=1, value=v),
	}]
	seq._on_midi_input(_cc_msg(1, 64, channel=2))
	assert len(spy.sent) == 1


def test_instant_channel_filter_no_match (patch_midi: None) -> None:
	"""Instant forward with channel filter should not fire on non-matching channel."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': 2,
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=1, value=v),
	}]
	seq._on_midi_input(_cc_msg(1, 64, channel=3))
	assert len(spy.sent) == 0


def test_instant_cc_filter (patch_midi: None) -> None:
	"""Instant forward should not fire on non-matching CC number."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 74,
		'channel': None,
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=74, value=v),
	}]
	seq._on_midi_input(_cc_msg(1, 64))  # CC 1, not 74
	assert len(spy.sent) == 0


def test_instant_transform_exception_does_not_crash (patch_midi: None) -> None:
	"""A broken transform should log but not raise from _on_midi_input."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)

	def _bad_transform (v: int, ch: int) -> int:
		raise RuntimeError("transform error")

	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'instant',
		'transform': _bad_transform,
	}]
	# Should not raise
	seq._on_midi_input(_cc_msg(1, 64))
	assert len(spy.sent) == 0


def test_instant_transform_none_suppresses (patch_midi: None) -> None:
	"""Instant forward with transform returning None should not call send."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'instant',
		'transform': lambda v, ch: None,
	}]
	seq._on_midi_input(_cc_msg(1, 64))
	assert len(spy.sent) == 0


# ---------------------------------------------------------------------------
# Sequencer — queued mode
# ---------------------------------------------------------------------------

def test_queued_enters_buffer (patch_midi: None) -> None:
	"""Queued forward should append to _forward_buffer."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'queued',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=74, value=v),
	}]
	seq._on_midi_input(_cc_msg(1, 64))
	assert len(seq._forward_buffer) == 1
	assert len(spy.sent) == 0  # not sent immediately


@pytest.mark.asyncio
async def test_queued_drained_in_process_pulse (patch_midi: None) -> None:
	"""_process_pulse() should drain _forward_buffer and send the messages."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq._event_loop = asyncio.get_event_loop()

	out_msg = mido.Message('control_change', channel=0, control=74, value=64)
	seq._forward_buffer.append((0, out_msg, 0))

	await seq._process_pulse(0)

	assert len(seq._forward_buffer) == 0
	assert any(m.control == 74 and m.value == 64 for m in spy.sent)


def test_midi_event_from_mido_cc (patch_midi: None) -> None:
	"""from_mido should correctly convert a CC message."""
	msg = mido.Message('control_change', channel=1, control=74, value=100)
	event = subsequence.sequencer.MidiEvent.from_mido(10, msg)
	assert event.pulse == 10
	assert event.message_type == 'control_change'
	assert event.channel == 1
	assert event.control == 74
	assert event.value == 100


def test_midi_event_from_mido_pitchwheel (patch_midi: None) -> None:
	"""from_mido should correctly convert a pitchwheel message."""
	msg = mido.Message('pitchwheel', channel=0, pitch=-4096)
	event = subsequence.sequencer.MidiEvent.from_mido(5, msg)
	assert event.pulse == 5
	assert event.message_type == 'pitchwheel'
	assert event.value == -4096

@pytest.mark.asyncio
async def test_queued_forward_routes_to_output_device (patch_midi: None) -> None:

	"""Queued forwards must reach their configured output device, not device 0.

	Regression: the queued buffer dropped the output device, so every queued
	forward was sent to the primary output.
	"""

	spy_primary = conftest.SpyMidiOut()
	spy_extra = conftest.SpyMidiOut()
	seq = _make_sequencer(spy_primary)
	seq.add_output_device("Extra", spy_extra)
	seq._event_loop = asyncio.get_event_loop()

	seq.cc_forwards = [{
		'cc': 74,
		'channel': None,
		'mode': 'queued',
		'transform': lambda value, channel: mido.Message('control_change', channel=0, control=74, value=value),
		'input_device': None,
		'output_device': 1,
	}]

	seq._on_midi_input(mido.Message('control_change', channel=0, control=74, value=99), device_idx=0)

	await seq._process_pulse(seq.pulse_count)

	assert any(m.type == 'control_change' and m.value == 99 for m in spy_extra.sent)
	assert not any(m.type == 'control_change' and m.value == 99 for m in spy_primary.sent)

def test_callable_with_output_channel_rechannels (patch_midi: None) -> None:

	"""A callable transform combined with output_channel= must re-channel, not crash.

	Regression: the wrapper rebuilt the message passing 'type' twice, raising
	TypeError on every incoming CC so nothing was ever forwarded.
	"""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	comp.midi_input("Dummy MIDI")
	comp.cc_forward(
		1,
		lambda value, channel: mido.Message('control_change', channel=channel, control=10, value=value),
		output_channel=5,
	)

	transform = comp._cc_forwards[0]['transform']
	result = transform(64, 2)

	assert result is not None
	assert result.type == 'control_change'
	assert result.value == 64
	assert result.channel == 4		# user channel 5 -> 0-indexed 4


def test_callable_with_output_channel_passes_none_through (patch_midi: None) -> None:

	"""A callable returning None (filter) must stay None under output_channel=."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	comp.midi_input("Dummy MIDI")
	comp.cc_forward(1, lambda value, channel: None, output_channel=5)

	assert comp._cc_forwards[0]['transform'](64, 2) is None
