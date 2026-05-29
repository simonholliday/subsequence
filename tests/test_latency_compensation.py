"""Tests for device-level MIDI latency compensation.

The model: each output device declares a non-negative physical latency in ms.
The slowest device plays at its logical time; every faster device's output is
deferred by ``max_latency − its_latency`` (wall-clock ``call_later``) so all
devices sound together. Recording stays at logical time; render mode and the
no-event-loop path send immediately.
"""

import asyncio
import logging
import pathlib
import typing

import pytest

import conftest

import subsequence
import subsequence.midi_utils
import subsequence.sequencer


# ---------------------------------------------------------------------------
# Registry (pure)
# ---------------------------------------------------------------------------

def test_registry_add_default_latency_zero () -> None:

	"""A device added without a latency reports 0.0."""

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut())
	assert reg.latency_of(0) == 0.0
	assert reg.max_latency() == 0.0


def test_registry_add_with_latency () -> None:

	"""add(latency_ms=) stores per-device latency and feeds max_latency()."""

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("fast", conftest.SpyMidiOut(), latency_ms=0)
	reg.add("slow", conftest.SpyMidiOut(), latency_ms=20)
	assert reg.latency_of(0) == 0.0
	assert reg.latency_of(1) == 20.0
	assert reg.max_latency() == 20.0


def test_registry_set_latency_by_index_and_name () -> None:

	"""set_latency resolves int, name, and None like the rest of the registry."""

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("primary", conftest.SpyMidiOut())
	reg.add("sampler", conftest.SpyMidiOut())
	reg.set_latency(0, 5)
	reg.set_latency("sampler", 25)
	assert reg.latency_of(None) == 5.0   # None → index 0
	assert reg.latency_of("sampler") == 25.0
	assert reg.max_latency() == 25.0


def test_registry_set_latency_negative_raises () -> None:

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut())
	with pytest.raises(ValueError, match="non-negative"):
		reg.set_latency(0, -1)


def test_registry_set_latency_unknown_device_raises () -> None:

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut())
	with pytest.raises(ValueError, match="Unknown output device"):
		reg.set_latency(99, 10)
	with pytest.raises(ValueError, match="Unknown output device"):
		reg.set_latency("nope", 10)


def test_registry_latency_of_unknown_is_zero () -> None:

	"""Defensive: unknown device on the hot path yields 0.0, never raises."""

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut())
	assert reg.latency_of(99) == 0.0
	assert reg.latency_of("nope") == 0.0


def test_registry_replace_preserves_latency () -> None:

	"""replace() is a pure port swap — latency survives test-injection."""

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut(), latency_ms=15)
	new_port = conftest.SpyMidiOut()
	reg.replace(0, new_port)
	assert reg.get(0) is new_port
	assert reg.latency_of(0) == 15.0


def test_registry_close_all_clears_latencies () -> None:

	reg = subsequence.midi_utils.MidiDeviceRegistry()
	reg.add("a", conftest.SpyMidiOut(), latency_ms=15)
	reg.close_all()
	assert reg.max_latency() == 0.0
	assert len(reg) == 0


# ---------------------------------------------------------------------------
# Normalization math (Sequencer)
# ---------------------------------------------------------------------------

def _seq_with_devices (latencies: typing.List[float]) -> subsequence.sequencer.Sequencer:

	"""Build a Sequencer with one spy device per latency (device 0..N-1)."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	# Device 0 already exists (Dummy MIDI). Set its latency and add the rest.
	seq.midi_out = conftest.SpyMidiOut()
	seq.set_device_latency(0, latencies[0])
	for i, lat in enumerate(latencies[1:], start=1):
		seq.add_output_device(f"dev{i}", conftest.SpyMidiOut(), latency_ms=lat)
	return seq


def test_offset_normalization (patch_midi: None) -> None:

	"""offset = (max − latency)/1000, slowest device → 0."""

	seq = _seq_with_devices([20, 0, 5])
	assert seq._send_offset_seconds(0) == pytest.approx(0.0)     # slowest
	assert seq._send_offset_seconds(1) == pytest.approx(0.020)   # fastest, most delayed
	assert seq._send_offset_seconds(2) == pytest.approx(0.015)


def test_max_recomputed_on_set (patch_midi: None) -> None:

	"""The cached max tracks raises and lowers."""

	seq = _seq_with_devices([10, 30])
	assert seq._max_device_latency_ms == 30.0
	seq.set_device_latency(1, 5)              # lower the previous max
	assert seq._max_device_latency_ms == 10.0
	seq.set_device_latency(0, 40)             # raise a new max
	assert seq._max_device_latency_ms == 40.0


def test_all_zero_latency_no_offset (patch_midi: None) -> None:

	"""The common case: nothing configured → every offset 0 (no deferral path)."""

	seq = _seq_with_devices([0, 0, 0])
	assert seq._send_offset_seconds(0) == 0.0
	assert seq._send_offset_seconds(1) == 0.0
	assert seq._send_offset_seconds(2) == 0.0


def test_set_device_latency_negative_raises (patch_midi: None) -> None:

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	with pytest.raises(ValueError, match="non-negative"):
		seq.set_device_latency(0, -1)


# ---------------------------------------------------------------------------
# Dispatch behaviour (async)
# ---------------------------------------------------------------------------

def _push_note (seq: subsequence.sequencer.Sequencer, device: int, note: int = 60, pulse: int = 0) -> None:

	seq._push_event(subsequence.sequencer.MidiEvent(
		pulse=pulse, message_type='note_on', channel=0, note=note, velocity=100, device=device,
	))


@pytest.mark.asyncio
async def test_slow_device_sends_immediately (patch_midi: None) -> None:

	"""The slowest device (offset 0) dispatches synchronously inside _process_pulse."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0                          # fast
	spy1 = conftest.SpyMidiOut(); seq.add_output_device("slow", spy1, latency_ms=20)  # slowest

	_push_note(seq, device=1, note=64)
	await seq._process_pulse(0)

	assert len(spy1.sent) == 1                # slow device sent now
	assert len(seq._pending_sends) == 0


@pytest.mark.asyncio
async def test_fast_device_deferred_then_fires (patch_midi: None) -> None:

	"""A faster device is deferred: empty right after _process_pulse, sent after the offset."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	loop = asyncio.get_running_loop()
	seq._event_loop = loop
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)   # fast
	spy1 = conftest.SpyMidiOut(); seq.add_output_device("slow", spy1, latency_ms=10)  # slowest

	scheduled_at = loop.time()
	_push_note(seq, device=0, note=60)
	await seq._process_pulse(0)

	# Deferred, not yet sent; one handle pending, scheduled ~10ms out.
	assert len(spy0.sent) == 0
	assert len(seq._pending_sends) == 1
	handle = next(iter(seq._pending_sends))
	assert handle.when() - scheduled_at == pytest.approx(0.010, abs=0.005)

	await asyncio.sleep(0.05)
	assert len(spy0.sent) == 1                # fired
	assert len(seq._pending_sends) == 0       # self-discarded


@pytest.mark.asyncio
async def test_two_devices_same_pulse_split (patch_midi: None) -> None:

	"""Same-pulse events split: slow sends now, fast is deferred."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)
	spy1 = conftest.SpyMidiOut(); seq.add_output_device("slow", spy1, latency_ms=10)

	_push_note(seq, device=0, note=60)
	_push_note(seq, device=1, note=64)
	await seq._process_pulse(0)

	assert len(spy1.sent) == 1   # slow: immediate
	assert len(spy0.sent) == 0   # fast: deferred
	await asyncio.sleep(0.05)
	assert len(spy0.sent) == 1


@pytest.mark.asyncio
async def test_intra_device_order_preserved_through_deferral (patch_midi: None) -> None:

	"""An NRPN-style burst on one deferred device keeps its CC order (99→98→6→38)."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)   # deferred
	seq.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=10)              # sets max

	for control in (99, 98, 6, 38):
		seq._push_event(subsequence.sequencer.MidiEvent(
			pulse=0, message_type='control_change', channel=0, control=control, value=1, device=0,
		))
	await seq._process_pulse(0)
	assert len(seq._pending_sends) == 4

	await asyncio.sleep(0.05)
	assert [m.control for m in spy0.sent if m.type == 'control_change'] == [99, 98, 6, 38]


@pytest.mark.asyncio
async def test_render_mode_sends_immediately (patch_midi: None) -> None:

	"""Render mode never defers (no real clock) — output stays logical/uncompensated."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	seq.render_mode = True
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)
	seq.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=20)

	_push_note(seq, device=0, note=60)
	await seq._process_pulse(0)

	assert len(spy0.sent) == 1                # immediate despite offset
	assert len(seq._pending_sends) == 0


@pytest.mark.asyncio
async def test_no_event_loop_sends_immediately (patch_midi: None) -> None:

	"""With no running loop captured (the unit-test default), dispatch is synchronous."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	# Deliberately leave seq._event_loop = None.
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)
	seq.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=20)

	_push_note(seq, device=0, note=60)
	await seq._process_pulse(0)

	assert len(spy0.sent) == 1
	assert len(seq._pending_sends) == 0


# ---------------------------------------------------------------------------
# Teardown (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_sends_idempotent (patch_midi: None) -> None:

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._cancel_pending_sends()   # empty — no error
	seq._cancel_pending_sends()


@pytest.mark.asyncio
async def test_stop_cancels_deferred_and_panic_silences (patch_midi: None) -> None:

	"""stop() cancels in-flight deferrals (never sent) and panic sweeps notes off."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)   # fast → deferred
	# A very slow second device makes device 0's offset huge (5s), so the deferred
	# note-on cannot fire during the test — "empty + never sent" proves cancellation.
	seq.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=5000)

	_push_note(seq, device=0, note=60)
	await seq._process_pulse(0)
	assert len(seq._pending_sends) == 1
	assert not any(m.type == 'note_on' for m in spy0.sent)

	await seq.stop()

	assert len(seq._pending_sends) == 0                                   # cancelled
	assert not any(m.type == 'note_on' for m in spy0.sent)                # never fired
	# panic() is the silence authority: CC 123 (all-notes-off) swept all channels.
	assert any(m.type == 'control_change' and m.control == 123 for m in spy0.sent)


@pytest.mark.asyncio
async def test_no_send_after_close (patch_midi: None) -> None:

	"""Cancel-before-close: a deferred send never fires once ports are closed."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)
	seq._event_loop = asyncio.get_running_loop()
	spy0 = conftest.SpyMidiOut(); seq.midi_out = spy0; seq.set_device_latency(0, 0)
	seq.add_output_device("slow", conftest.SpyMidiOut(), latency_ms=5)

	_push_note(seq, device=0, note=60)
	await seq._process_pulse(0)
	seq._cancel_pending_sends()
	seq._output_devices.close_all()

	await asyncio.sleep(0.03)
	assert not any(m.type == 'note_on' for m in spy0.sent)


# ---------------------------------------------------------------------------
# Composition wiring
# ---------------------------------------------------------------------------

def test_composition_latency_param_validation (patch_midi: None) -> None:

	with pytest.raises(ValueError, match="non-negative"):
		subsequence.Composition(bpm=120, latency_ms=-1)

	comp = subsequence.Composition(bpm=120)
	with pytest.raises(ValueError, match="non-negative"):
		comp.midi_output("Synth", latency_ms=-5)


def test_additional_output_carries_latency (patch_midi: None) -> None:

	comp = subsequence.Composition(bpm=120)
	idx = comp.midi_output("Synth", name="s", latency_ms=12)
	assert idx == 1
	entry = comp._additional_outputs[0]
	assert entry.device == "Synth"
	assert entry.alias == "s"
	assert entry.latency_ms == 12


def test_warn_if_high_latency_fires (patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	"""A whole-rig latency above the threshold logs a warning naming the slowest device."""

	caplog.set_level(logging.WARNING, logger="subsequence.composition")
	comp = subsequence.Composition(bpm=120, latency_ms=50)
	comp.midi_output("Sampler", name="sampler", latency_ms=10)

	comp._warn_if_high_latency()

	warnings = [r.getMessage() for r in caplog.records if "latency compensation" in r.getMessage().lower()]
	assert len(warnings) == 1
	assert "primary output" in warnings[0]   # 50ms primary is the slowest
	assert "50" in warnings[0]


def test_warn_if_high_latency_silent_below_threshold (patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	caplog.set_level(logging.WARNING, logger="subsequence.composition")
	comp = subsequence.Composition(bpm=120, latency_ms=20)   # below 30ms threshold
	comp._warn_if_high_latency()
	assert not [r for r in caplog.records if "latency compensation" in r.getMessage().lower()]


def test_render_wires_device_latencies (tmp_path: pathlib.Path, patch_midi_multi: typing.Dict[str, conftest.NamedSpyMidiOut]) -> None:

	"""_run applies the configured latencies to the sequencer's devices.

	stop() clears the registry at the end of render, so we capture the wiring
	calls as they happen rather than inspecting post-run registry state.
	Uses patch_midi_multi so the additional device actually opens.
	"""

	filename = str(tmp_path / "out.mid")
	comp = subsequence.Composition(bpm=480, output_device="Primary MIDI", latency_ms=20)
	comp.midi_output("Secondary MIDI", name="sampler", latency_ms=15)

	set_calls: typing.List[typing.Tuple[typing.Any, float]] = []
	add_calls: typing.List[typing.Tuple[str, float]] = []
	orig_set = comp._sequencer.set_device_latency
	orig_add = comp._sequencer.add_output_device

	def spy_set (device: typing.Any, latency_ms: float) -> None:
		set_calls.append((device, latency_ms)); orig_set(device, latency_ms)

	def spy_add (name: str, port: typing.Any, latency_ms: float = 0.0) -> int:
		add_calls.append((name, latency_ms)); return orig_add(name, port, latency_ms)

	comp._sequencer.set_device_latency = spy_set        # type: ignore[method-assign]
	comp._sequencer.add_output_device = spy_add         # type: ignore[method-assign]

	@comp.pattern(channel=1, beats=4)
	def p (p) -> None:
		pass

	comp.render(bars=4, max_minutes=None, filename=filename)

	assert (0, 20.0) in set_calls                       # primary device 0 → 20ms
	assert any(lat == 15.0 for _, lat in add_calls)     # additional device → 15ms
