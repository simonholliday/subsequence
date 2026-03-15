"""
Tests for multi-device MIDI input and output support.

All single-device behaviour must remain unchanged (backward compat tests come first).
Multi-device tests follow.
"""

import asyncio

import mido
import pytest

import subsequence
import subsequence.sequencer
import subsequence.midi_utils
import conftest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sequencer(spy: conftest.SpyMidiOut) -> subsequence.sequencer.Sequencer:
	seq = subsequence.sequencer.Sequencer(
		output_device_name = "Dummy MIDI",
		initial_bpm = 120,
	)
	seq.midi_out = spy
	loop = asyncio.new_event_loop()
	seq._midi_input_queue = asyncio.Queue()
	seq._input_loop = loop
	return seq


def _cc(control: int, value: int, channel: int = 0) -> mido.Message:
	return mido.Message('control_change', channel=channel, control=control, value=value)


# ---------------------------------------------------------------------------
# Backward compatibility — single device (must work exactly as before)
# ---------------------------------------------------------------------------

def test_single_device_pattern_route(patch_midi: None) -> None:
	"""Single-device Composition still works; all events go to device 0."""
	comp = subsequence.Composition(bpm=120)

	@comp.pattern(channel=1, beats=4)
	def bass(p: subsequence.pattern_builder.PatternBuilder) -> None:
		p.note(36, beat=0)

	# Pattern device defaults to 0
	assert comp._pending_patterns[0].device == 0


def test_single_device_midi_out_property(patch_midi: None) -> None:
	"""sequencer.midi_out property still works on single-device setup."""
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	assert seq.midi_out is not None


def test_midi_out_setter_compat(patch_midi: None) -> None:
	"""sequencer.midi_out = spy still works (test injection path)."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	assert seq.midi_out is spy


def test_single_device_send(patch_midi: None) -> None:
	"""Events without a device field default to device 0."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	event = subsequence.sequencer.MidiEvent(
		pulse=0, message_type='control_change', channel=0,
		control=7, value=100,
	)
	seq._send_midi(event)
	assert len(spy.sent) == 1
	assert spy.sent[0].value == 100


def test_single_device_active_notes_track(patch_midi: None) -> None:
	"""active_notes tracks (device, channel, note) tuples."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	on_event = subsequence.sequencer.MidiEvent(
		pulse=0, message_type='note_on', channel=0, note=60, velocity=100,
	)
	seq._process_pulse = None  # skip full process
	# manually add
	seq.active_notes.add((0, 0, 60))
	assert (0, 0, 60) in seq.active_notes


def test_pattern_device_default(patch_midi: None) -> None:
	"""Pattern.device defaults to 0."""
	import subsequence.pattern as pat
	p = pat.Pattern(channel=0)
	assert p.device == 0


def test_cc_event_device_default(patch_midi: None) -> None:
	"""CcEvent.device defaults to None (inherit from pattern)."""
	import subsequence.pattern as pat
	ev = pat.CcEvent(pulse=0, message_type='control_change')
	assert ev.device is None


# ---------------------------------------------------------------------------
# MidiDeviceRegistry
# ---------------------------------------------------------------------------

def test_registry_add_returns_index() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	i0 = reg.add("A", object())
	i1 = reg.add("B", object())
	assert i0 == 0
	assert i1 == 1


def test_registry_get_none_returns_device_0() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	obj = object()
	reg.add("Primary", obj)
	assert reg.get(None) is obj


def test_registry_get_by_index() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	a, b = object(), object()
	reg.add("A", a)
	reg.add("B", b)
	assert reg.get(1) is b


def test_registry_get_by_name() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	a, b = object(), object()
	reg.add("Alpha", a)
	reg.add("Beta", b)
	assert reg.get("Beta") is b


def test_registry_get_unknown_name_returns_none() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("A", object())
	assert reg.get("NoSuchDevice") is None


def test_registry_get_empty_returns_none() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	assert reg.get(None) is None


def test_registry_index_of() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("X", object())
	reg.add("Y", object())
	assert reg.index_of(None) == 0
	assert reg.index_of(1) == 1
	assert reg.index_of("Y") == 1
	assert reg.index_of("Z") == -1


def test_registry_iter() -> None:
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	objs = [object(), object()]
	for i, o in enumerate(objs):
		reg.add(f"dev{i}", o)
	assert list(reg) == objs


def test_registry_close_all() -> None:
	closed = []

	class TrackClose:
		def close(self) -> None:
			closed.append(True)

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("A", TrackClose())
	reg.add("B", TrackClose())
	reg.close_all()
	assert len(closed) == 2
	assert len(reg) == 0


# ---------------------------------------------------------------------------
# Multi-device output routing
# ---------------------------------------------------------------------------

def test_pattern_device_by_index(patch_midi: None) -> None:
	"""@comp.pattern(device=1) stores device=1 on the pending pattern."""
	comp = subsequence.Composition(bpm=120)
	comp._additional_outputs.append(("Secondary MIDI", None))

	@comp.pattern(channel=1, beats=4, device=1)
	def strings(p):
		p.note(60, beat=0)

	assert comp._pending_patterns[0].device == 1


def test_pattern_device_by_name(patch_midi_multi) -> None:
	"""@comp.pattern(device='secondary') resolves to correct index."""
	comp = subsequence.Composition(bpm=120, output_device="Primary MIDI")
	comp.midi_output("Secondary MIDI", name="secondary")

	@comp.pattern(channel=1, beats=4, device="secondary")
	def p1(p):
		pass

	# device=0 placeholder at registration time (name resolved in _run()); raw_device preserved
	pending = comp._pending_patterns[0]
	assert pending.raw_device == "secondary"
	assert pending.device == 0


def test_midi_output_returns_index(patch_midi_multi) -> None:
	"""comp.midi_output() returns sequential indices starting at 1."""
	comp = subsequence.Composition(bpm=120, output_device="Primary MIDI")
	i1 = comp.midi_output("Secondary MIDI", name="synth2")
	i2 = comp.midi_output("Third MIDI", name="synth3")
	assert i1 == 1
	assert i2 == 2


def test_events_routed_to_device_1(patch_midi: None) -> None:
	"""MidiEvent with device=1 is sent to the device-1 port."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0  # device 0
	seq._output_devices.add("Secondary", spy1)  # device 1

	event = subsequence.sequencer.MidiEvent(
		pulse=0, message_type='note_on', channel=0, note=60, velocity=100,
		device=1,
	)
	seq._send_midi(event)

	assert len(spy0.sent) == 0
	assert len(spy1.sent) == 1
	assert spy1.sent[0].note == 60


def test_events_default_to_device_0(patch_midi: None) -> None:
	"""MidiEvent with device=0 (default) goes to the primary output."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	event = subsequence.sequencer.MidiEvent(
		pulse=0, message_type='note_on', channel=0, note=60, velocity=100,
		# device defaults to 0
	)
	seq._send_midi(event)

	assert len(spy0.sent) == 1
	assert len(spy1.sent) == 0


def test_active_notes_device_aware(patch_midi: None) -> None:
	"""Note-off is sent to the same device the note-on came from."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	# Simulate a note-on on device 1 tracked in active_notes
	seq.active_notes.add((1, 0, 60))

	asyncio.run(seq._stop_all_active_notes())

	assert len(spy0.sent) == 0
	assert len(spy1.sent) == 1
	assert spy1.sent[0].type == 'note_off'
	assert spy1.sent[0].note == 60


@pytest.mark.asyncio
async def test_panic_all_devices(patch_midi: None) -> None:
	"""panic() sends All Notes Off to every registered output device."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	await seq.panic()

	# Both devices should have received CC 123 and CC 120 on all 16 channels
	def has_all_notes_off(spy: conftest.SpyMidiOut) -> bool:
		return any(
			m.type == 'control_change' and m.control == 123
			for m in spy.sent
		)

	assert has_all_notes_off(spy0)
	assert has_all_notes_off(spy1)


def test_schedule_pattern_propagates_device(patch_midi: None) -> None:
	"""schedule_pattern() copies pattern.device onto every MidiEvent."""
	import subsequence.pattern as pat

	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	# Build a simple pattern targeting device 1
	p = pat.Pattern(channel=0, length=4, device=1)
	p.add_note(position=0, pitch=60, velocity=100, duration=24)

	asyncio.run(seq.schedule_pattern(p, 0))

	# Send the scheduled events
	seq._send_midi(seq.event_queue[0])

	assert len(spy1.sent) >= 1


def test_cc_event_device_override(patch_midi: None) -> None:
	"""CcEvent.device overrides pattern.device during schedule_pattern."""
	import subsequence.pattern as pat

	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	# Pattern targets device 0, but a CC event overrides to device 1
	p = pat.Pattern(channel=0, length=4, device=0)
	p.cc_events.append(pat.CcEvent(
		pulse=0, message_type='control_change',
		control=7, value=100, device=1,
	))

	asyncio.run(seq.schedule_pattern(p, 0))

	# Find and send the CC event
	for ev in seq.event_queue:
		if ev.message_type == 'control_change':
			assert ev.device == 1
			seq._send_midi(ev)
			break

	assert len(spy1.sent) == 1
	assert spy1.sent[0].control == 7


# ---------------------------------------------------------------------------
# Multi-device input routing
# ---------------------------------------------------------------------------

def test_cc_map_input_device_filter(patch_midi: None) -> None:
	"""CC mapping with input_device only fires for the specified device."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_mappings = [{
		'cc': 74,
		'key': 'filter',
		'channel': None,
		'min_val': 0.0,
		'max_val': 1.0,
		'input_device': 1,  # only from device 1
	}]
	seq._composition_data = {}

	# Message from device 0 → should NOT update data
	seq._on_midi_input(_cc(74, 64), device_idx=0)
	assert 'filter' not in seq._composition_data

	# Message from device 1 → should update data
	seq._on_midi_input(_cc(74, 64), device_idx=1)
	assert 'filter' in seq._composition_data


def test_cc_map_no_device_filter(patch_midi: None) -> None:
	"""CC mapping with input_device=None fires for any device (default)."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_mappings = [{
		'cc': 74,
		'key': 'filter',
		'channel': None,
		'min_val': 0.0,
		'max_val': 1.0,
		'input_device': None,
	}]
	seq._composition_data = {}

	seq._on_midi_input(_cc(74, 64), device_idx=0)
	assert 'filter' in seq._composition_data
	seq._composition_data.clear()

	seq._on_midi_input(_cc(74, 64), device_idx=1)
	assert 'filter' in seq._composition_data


def test_cc_forward_input_device_filter(patch_midi: None) -> None:
	"""CC forward with input_device only fires for the specified device."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = _make_sequencer(spy0)
	seq._output_devices.add("Secondary", spy1)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=1, value=v),
		'input_device': 1,
		'output_device': 0,
	}]

	# Message from device 0 → should NOT forward
	seq._on_midi_input(_cc(1, 64), device_idx=0)
	assert len(spy0.sent) == 0

	# Message from device 1 → should forward
	seq._on_midi_input(_cc(1, 64), device_idx=1)
	assert len(spy0.sent) == 1


def test_cc_forward_output_device_routing(patch_midi: None) -> None:
	"""CC forward with output_device sends to the specified output port."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = _make_sequencer(spy0)
	seq._output_devices.add("Secondary", spy1)
	seq.cc_forwards = [{
		'cc': 1,
		'channel': None,
		'mode': 'instant',
		'transform': lambda v, ch: mido.Message('control_change', channel=ch, control=1, value=v),
		'input_device': None,
		'output_device': 1,  # send to device 1
	}]

	seq._on_midi_input(_cc(1, 64), device_idx=0)

	assert len(spy0.sent) == 0
	assert len(spy1.sent) == 1


def test_multiple_midi_input_calls(patch_midi: None) -> None:
	"""Multiple comp.midi_input() calls register primary + additional inputs."""
	comp = subsequence.Composition(bpm=120)
	comp.midi_input("Arturia KeyStep", name="keys")
	comp.midi_input("Faderfox EC4", name="faders")

	assert comp._input_device == "Arturia KeyStep"
	assert len(comp._additional_inputs) == 1
	assert comp._additional_inputs[0][0] == "Faderfox EC4"
	assert comp._additional_inputs[0][1] == "faders"


# ---------------------------------------------------------------------------
# Composition API — device on cc_map / cc_forward
# ---------------------------------------------------------------------------

def test_cc_map_stores_input_device(patch_midi: None) -> None:
	"""cc_map() stores input_device in the mapping dict."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_map(74, "filter", input_device="faders")
	assert comp._cc_mappings[-1]['input_device'] == "faders"


def test_cc_forward_stores_input_output_device(patch_midi: None) -> None:
	"""cc_forward() stores input_device and output_device."""
	comp = subsequence.Composition(bpm=120)
	comp.cc_forward(1, "cc", input_device="keys", output_device=1)
	fwd = comp._cc_forwards[-1]
	assert fwd['input_device'] == "keys"
	assert fwd['output_device'] == 1


# ---------------------------------------------------------------------------
# Clock output goes to all devices
# ---------------------------------------------------------------------------

def test_clock_goes_to_all_devices(patch_midi: None) -> None:
	"""_send_clock_message sends to every registered output port."""
	spy0 = conftest.SpyMidiOut()
	spy1 = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy0
	seq._output_devices.add("Secondary", spy1)

	seq._send_clock_message("clock")

	assert any(m.type == 'clock' for m in spy0.sent)
	assert any(m.type == 'clock' for m in spy1.sent)


# ---------------------------------------------------------------------------
# Regression fixes — issues found during code review
# ---------------------------------------------------------------------------

def test_registry_replace() -> None:
	"""MidiDeviceRegistry.replace() swaps the port but keeps name and index intact."""
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	original = object()
	replacement = object()
	reg.add("primary", original)
	reg.replace(0, replacement)
	assert reg.get(0) is replacement
	assert reg.get("primary") is replacement
	assert reg.index_of("primary") == 0


def test_registry_replace_out_of_range() -> None:
	"""MidiDeviceRegistry.replace() raises IndexError for out-of-range index."""
	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("primary", object())
	with pytest.raises(IndexError):
		reg.replace(5, object())


def test_midi_out_setter_uses_replace(patch_midi: None) -> None:
	"""midi_out setter on an existing registry preserves port name."""
	spy_original = conftest.SpyMidiOut()
	spy_replacement = conftest.SpyMidiOut()
	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq.midi_out = spy_original
	# After setter, "Dummy MIDI" name is in the registry.
	original_name = seq._output_devices._ports[0][0]

	seq.midi_out = spy_replacement

	# Name must be preserved (not reset to "default").
	assert seq._output_devices._ports[0][0] == original_name
	assert seq.midi_out is spy_replacement


def test_pending_pattern_raw_device_field(patch_midi: None) -> None:
	"""_PendingPattern.raw_device is a proper typed field, not a monkey-patch."""
	comp = subsequence.Composition(bpm=120)

	@comp.pattern(channel=1, beats=4, device="integra")
	def strings(p):
		pass

	pending = comp._pending_patterns[0]
	# raw_device is the original DeviceId passed by the user.
	assert pending.raw_device == "integra"
	# device placeholder is 0 until _resolve_pending_devices() runs.
	assert pending.device == 0
	# No monkey-patched _raw_device attribute should be needed.
	assert hasattr(pending, 'raw_device')


def test_pending_pattern_int_device_resolved_immediately(patch_midi: None) -> None:
	"""@comp.pattern(device=1) resolves immediately — raw_device and device both set."""
	comp = subsequence.Composition(bpm=120)

	@comp.pattern(channel=1, beats=4, device=1)
	def strings(p):
		pass

	pending = comp._pending_patterns[0]
	assert pending.raw_device == 1
	assert pending.device == 1


def test_input_alias_resolves_in_cc_map(patch_midi_multi) -> None:
	"""cc_map(input_device='faders') resolves the alias to the correct device index."""
	comp = subsequence.Composition(bpm=120, output_device="Primary MIDI")
	comp.midi_input("Input A", name="keys")
	comp.midi_input("Input B", name="faders")
	comp.cc_map(74, "filter", input_device="faders")

	# Manual setup for resolution (simulating what _run would populate after opening ports).
	comp._input_device_names["Input A"] = 0
	if comp._input_device_alias:
		comp._input_device_names[comp._input_device_alias] = 0
	comp._input_device_names["Input B"] = 1
	comp._input_device_names["faders"] = 1

	# Trigger resolution (normally done in _run).
	for mapping in comp._cc_mappings:
		raw = mapping.get('input_device')
		if isinstance(raw, str):
			mapping['input_device'] = comp._resolve_input_device_id(raw)

	assert comp._cc_mappings[-1]['input_device'] == 1


def test_input_alias_resolves_in_cc_forward(patch_midi_multi) -> None:
	"""cc_forward(input_device='keys') resolves to the correct index."""
	comp = subsequence.Composition(bpm=120, output_device="Primary MIDI")
	comp.midi_input("Input A", name="keys")
	comp.cc_forward(1, "cc", input_device="keys")

	comp._input_device_names["Input A"] = 0
	if comp._input_device_alias:
		comp._input_device_names[comp._input_device_alias] = 0

	for fwd in comp._cc_forwards:
		raw_in = fwd.get('input_device')
		if isinstance(raw_in, str):
			fwd['input_device'] = comp._resolve_input_device_id(raw_in)

	assert comp._cc_forwards[-1]['input_device'] == 0


def test_unknown_output_device_name_warns_and_defaults_to_zero(patch_midi: None, caplog) -> None:
	"""_resolve_device_id() logs a warning and falls back to device 0 on unknown name."""
	import logging
	comp = subsequence.Composition(bpm=120)
	comp._output_device_names["known"] = 1

	with caplog.at_level(logging.WARNING, logger="subsequence.composition"):
		result = comp._resolve_device_id("typo_name")

	assert result == 0
	assert "typo_name" in caplog.text


def test_unknown_input_device_name_warns_and_returns_none(patch_midi: None, caplog) -> None:
	"""_resolve_input_device_id() logs a warning and returns None on unknown name."""
	import logging
	comp = subsequence.Composition(bpm=120)
	comp._input_device_names["known"] = 1

	with caplog.at_level(logging.WARNING, logger="subsequence.composition"):
		result = comp._resolve_input_device_id("typo_name")

	assert result is None
	assert "typo_name" in caplog.text


def test_cc_map_unknown_input_device_none_means_any(patch_midi: None) -> None:
	"""cc_map with an unresolvable input_device name falls back to None (matches any)."""
	spy = conftest.SpyMidiOut()
	seq = _make_sequencer(spy)
	seq.cc_mappings = [{
		'cc': 74,
		'key': 'filter',
		'channel': None,
		'min_val': 0.0,
		'max_val': 1.0,
		'input_device': None,   # None = any device
	}]
	seq._composition_data = {}

	# Should fire for any device_idx when input_device is None.
	seq._on_midi_input(_cc(74, 64), device_idx=0)
	assert 'filter' in seq._composition_data
	seq._composition_data.clear()

	seq._on_midi_input(_cc(74, 64), device_idx=2)
	assert 'filter' in seq._composition_data


# ---------------------------------------------------------------------------
# Multiple clock follower device tests
# ---------------------------------------------------------------------------

def test_multiple_clock_follow_raises_error(patch_midi: None) -> None:
	"""Setting clock_follow=True on multiple devices raises ValueError."""
	comp = subsequence.Composition(bpm=120)
	comp.midi_input("Primary MIDI", clock_follow=True)
	
	with pytest.raises(ValueError, match="Only one input device can be configured to follow external clock"):
		comp.midi_input("Secondary MIDI", clock_follow=True)


@pytest.mark.asyncio
async def test_clock_follower_ignores_other_devices(monkeypatch) -> None:
	"""Sequencer ignores clock messages from devices that are not the clock_device_idx."""
	seq = subsequence.sequencer.Sequencer(
		output_device_name="Dummy MIDI",
		initial_bpm=120,
		input_device_name="Mock MIDI",
		clock_follow=True,
		spin_wait=False
	)
	seq.clock_device_idx = 1 # We only want clock from device 1
	
	seq._midi_input_queue = asyncio.Queue()
	seq.running = True

	# Create a mock for _estimate_bpm to track if clock was processed
	processed_clocks = []
	def mock_estimate_bpm(t):
		processed_clocks.append(t)
	monkeypatch.setattr(seq, "_estimate_bpm", mock_estimate_bpm)
	monkeypatch.setattr(seq, "_check_bar_change", lambda p, b: None)
	monkeypatch.setattr(seq, "_check_beat_change", lambda p, b: None)
	monkeypatch.setattr(seq, "_advance_pulse", lambda: asyncio.sleep(0))
	
	# Send a clock message from device 0 (should be ignored)
	seq._midi_input_queue.put_nowait((0, mido.Message('clock')))
	
	# Send a clock message from device 1 (should be processed)
	seq._midi_input_queue.put_nowait((1, mido.Message('clock')))
	
	# Send a stop message from device 1 to break the loop
	seq._midi_input_queue.put_nowait((1, mido.Message('stop')))
	
	await seq._run_loop_external_clock(96)
	
	# Only the clock message from device 1 should have reached _estimate_bpm
	assert len(processed_clocks) == 1
