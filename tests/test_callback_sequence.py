"""Tests for Sequencer.schedule_callback_sequence — the variable-interval primitive.

The harmonic clock under a bound progression walks irregular spans, so its
callback decides each hop's length.  These tests pin down the contract:
boundary targeting, per-hop intervals, lookahead timing, stop-on-None,
error isolation, and ordering against fixed callbacks and pattern rebuilds.
"""

import typing

import pytest

import subsequence.pattern
import subsequence.sequencer


def make_sequencer () -> subsequence.sequencer.Sequencer:

	"""A sequencer with a dummy device (patch_midi supplies the backend)."""

	return subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)


@pytest.mark.asyncio
async def test_fires_at_lookahead_before_boundary (patch_midi: None) -> None:

	"""The callback fires exactly lookahead before its boundary, not earlier."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	fired: typing.List[int] = []

	def clock (boundary: int) -> float:
		fired.append(boundary)
		return 4.0

	await sequencer.schedule_callback_sequence(clock, start_pulse=8 * ppb, reschedule_lookahead=1)

	await sequencer._maybe_reschedule_patterns(7 * ppb - 1)
	assert fired == []

	await sequencer._maybe_reschedule_patterns(7 * ppb)
	assert fired == [8 * ppb]


@pytest.mark.asyncio
async def test_receives_boundary_pulse_not_fire_pulse (patch_midi: None) -> None:

	"""The callback argument is the boundary it prepares, not the clock 'now'."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	received: typing.List[int] = []

	def clock (boundary: int) -> typing.Optional[float]:
		received.append(boundary)
		return None

	await sequencer.schedule_callback_sequence(clock, start_pulse=4 * ppb, reschedule_lookahead=2)

	await sequencer._maybe_reschedule_patterns(2 * ppb)

	assert received == [4 * ppb]


@pytest.mark.asyncio
async def test_variable_intervals_walk_irregular_spans (patch_midi: None) -> None:

	"""Each return value sets the next hop: 2 then 4 then 2 beats."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	boundaries: typing.List[int] = []
	spans = iter([2.0, 4.0, 2.0])

	def clock (boundary: int) -> typing.Optional[float]:
		boundaries.append(boundary)
		return next(spans, None)

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=1)

	for pulse in range(0, 10 * ppb):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert boundaries == [0, 2 * ppb, 6 * ppb, 8 * ppb]


@pytest.mark.asyncio
async def test_none_stops_the_sequence (patch_midi: None) -> None:

	"""Returning None drops the sequence — no further fires, queue empties."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	count = [0]

	def clock (boundary: int) -> typing.Optional[float]:
		count[0] += 1
		return None

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=1)

	for pulse in range(0, 8 * ppb):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert count[0] == 1
	assert sequencer.callback_sequence_queue == []


@pytest.mark.asyncio
async def test_backshift_fires_immediately_at_start (patch_midi: None) -> None:

	"""start_pulse=0 with lookahead means the first fire is already due at pulse 0."""

	sequencer = make_sequencer()
	fired: typing.List[int] = []

	def clock (boundary: int) -> typing.Optional[float]:
		fired.append(boundary)
		return None

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=1)

	await sequencer._maybe_reschedule_patterns(0)

	assert fired == [0]


@pytest.mark.asyncio
async def test_async_callback_is_awaited (patch_midi: None) -> None:

	"""Coroutine callbacks work and their return value drives the hop."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	boundaries: typing.List[int] = []

	async def clock (boundary: int) -> typing.Optional[float]:
		boundaries.append(boundary)
		return 2.0 if len(boundaries) < 2 else None

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=1)

	for pulse in range(0, 4 * ppb):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert boundaries == [0, 2 * ppb]


@pytest.mark.asyncio
async def test_failing_callback_is_dropped_and_isolated (patch_midi: None) -> None:

	"""An exception stops that sequence; other sequences keep firing."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	healthy: typing.List[int] = []

	def bad (boundary: int) -> float:
		raise RuntimeError("boom")

	def good (boundary: int) -> typing.Optional[float]:
		healthy.append(boundary)
		return 2.0 if len(healthy) < 3 else None

	await sequencer.schedule_callback_sequence(bad, start_pulse=0, reschedule_lookahead=1)
	await sequencer.schedule_callback_sequence(good, start_pulse=0, reschedule_lookahead=1)

	for pulse in range(0, 8 * ppb):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert healthy == [0, 2 * ppb, 4 * ppb]
	assert sequencer.callback_sequence_queue == []


@pytest.mark.asyncio
async def test_tiny_interval_clamps_and_stays_monotonic (patch_midi: None) -> None:

	"""A near-zero interval advances at least one pulse — no same-pulse spin."""

	sequencer = make_sequencer()
	boundaries: typing.List[int] = []

	def clock (boundary: int) -> typing.Optional[float]:
		boundaries.append(boundary)
		return 0.0 if len(boundaries) < 3 else None

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=0)

	for pulse in range(0, 10):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert boundaries == [0, 1, 2]


@pytest.mark.asyncio
async def test_fixed_callbacks_fire_before_sequences_at_same_pulse (patch_midi: None) -> None:

	"""Registration-independent ordering: fixed (the form clock) before sequences (harmony)."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	order: typing.List[str] = []

	def harmony_clock (boundary: int) -> typing.Optional[float]:
		order.append("harmony")
		return None

	def form_clock (pulse: int) -> None:
		order.append("form")

	# Deliberately register the sequence FIRST — ordering must not depend on it.
	await sequencer.schedule_callback_sequence(harmony_clock, start_pulse=4 * ppb, reschedule_lookahead=1)
	await sequencer.schedule_callback_repeating(form_clock, interval_beats=4, start_pulse=4 * ppb, reschedule_lookahead=1)

	await sequencer._maybe_reschedule_patterns(3 * ppb)

	assert order == ["form", "harmony"]


@pytest.mark.asyncio
async def test_sequences_fire_before_pattern_rebuilds_at_same_pulse (patch_midi: None) -> None:

	"""The clock must publish the window before patterns rebuild against it."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	order: typing.List[str] = []

	class Recorder (subsequence.pattern.Pattern):

		"""Pattern that records when it rebuilds."""

		def __init__ (self) -> None:
			super().__init__(channel=0, length=4, reschedule_lookahead=1)
			self.add_note(position=0, pitch=60, velocity=100, duration=6)

		def on_reschedule (self) -> None:
			order.append("pattern")

	def harmony_clock (boundary: int) -> typing.Optional[float]:
		order.append("harmony")
		return None

	pattern = Recorder()
	await sequencer.schedule_pattern_repeating(pattern, start_pulse=0)
	await sequencer.schedule_callback_sequence(harmony_clock, start_pulse=4 * ppb, reschedule_lookahead=1)

	# Both are due at 3 beats: pattern reschedules at length - lookahead,
	# the clock fires at boundary - lookahead.
	await sequencer._maybe_reschedule_patterns(3 * ppb)

	assert order == ["harmony", "pattern"]


@pytest.mark.asyncio
async def test_negative_lookahead_raises (patch_midi: None) -> None:

	"""A negative lookahead is a hard error."""

	sequencer = make_sequencer()

	with pytest.raises(ValueError):
		await sequencer.schedule_callback_sequence(lambda boundary: None, reschedule_lookahead=-1)


@pytest.mark.asyncio
async def test_fractional_beat_intervals_convert_to_pulses (patch_midi: None) -> None:

	"""Half-beat spans land on exact pulse boundaries."""

	sequencer = make_sequencer()
	ppb = sequencer.pulses_per_beat
	boundaries: typing.List[int] = []

	def clock (boundary: int) -> typing.Optional[float]:
		boundaries.append(boundary)
		return 0.5 if len(boundaries) < 3 else None

	await sequencer.schedule_callback_sequence(clock, start_pulse=0, reschedule_lookahead=0)

	for pulse in range(0, 2 * ppb):
		await sequencer._maybe_reschedule_patterns(pulse)

	assert boundaries == [0, ppb // 2, ppb]
