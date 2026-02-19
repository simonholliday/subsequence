import asyncio
import threading
import typing

import pytest

import subsequence.composition
import subsequence.sequencer


def test_sequencer_data_store_exists (patch_midi: None) -> None:

	"""Sequencer should have an empty data dict on creation."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	assert isinstance(seq.data, dict)
	assert len(seq.data) == 0


@pytest.mark.asyncio
async def test_safe_callback_catches_exceptions () -> None:

	"""A failing safe callback should log a warning instead of raising."""

	def bad_fn () -> None:
		raise RuntimeError("boom")

	wrapped = subsequence.composition._make_safe_callback(bad_fn)

	# wrapper is sync, fires a background task.
	wrapped(0)

	# Yield control so the background task runs and completes.
	await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_safe_callback_runs_sync_in_executor () -> None:

	"""Sync functions wrapped by _make_safe_callback should run in a thread pool."""

	thread_names: typing.List[str] = []

	def sync_fn () -> None:
		thread_names.append(threading.current_thread().name)

	wrapped = subsequence.composition._make_safe_callback(sync_fn)
	wrapped(0)

	# Yield control so the executor thread completes.
	await asyncio.sleep(0.05)

	assert len(thread_names) == 1
	# The main asyncio thread is typically "MainThread"; executor threads are not.
	assert thread_names[0] != "MainThread"


@pytest.mark.asyncio
async def test_safe_callback_runs_async_directly () -> None:

	"""Async functions wrapped by _make_safe_callback should run on the event loop."""

	thread_names: typing.List[str] = []

	async def async_fn () -> None:
		thread_names.append(threading.current_thread().name)

	wrapped = subsequence.composition._make_safe_callback(async_fn)
	wrapped(0)

	# Yield control so the background task runs.
	await asyncio.sleep(0)

	assert len(thread_names) == 1
	assert thread_names[0] == "MainThread"


@pytest.mark.asyncio
async def test_safe_callback_does_not_block () -> None:

	"""The wrapper should return immediately without blocking the caller."""

	completed = []

	def slow_fn () -> None:
		import time
		time.sleep(0.1)
		completed.append(True)

	wrapped = subsequence.composition._make_safe_callback(slow_fn)

	# Call and immediately check - should not have run yet.
	wrapped(0)
	assert len(completed) == 0

	# Now wait for it to finish in the background.
	await asyncio.sleep(0.2)
	assert len(completed) == 1


@pytest.mark.asyncio
async def test_schedule_task_registers_callback (patch_midi: None) -> None:

	"""schedule_task should register a callback on the sequencer."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	def my_task () -> None:
		pass

	await subsequence.composition.schedule_task(sequencer=seq, fn=my_task, cycle_beats=8)

	assert len(seq.callback_queue) == 1


@pytest.mark.asyncio
async def test_schedule_task_defer_skips_pulse_zero (patch_midi: None) -> None:

	"""schedule_task(defer=True) should set start_pulse to one full cycle."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	def my_task () -> None:
		pass

	await subsequence.composition.schedule_task(sequencer=seq, fn=my_task, cycle_beats=8, defer=True)

	assert len(seq.callback_queue) == 1

	# With defer, start_pulse = 8 beats * 24 ppq = 192.
	# Backshift subtracts lookahead: next_fire = 192 - (1 * 24) = 168.
	_, _, scheduled = seq.callback_queue[0]
	lookahead_pulses = int(1 * seq.pulses_per_beat)
	expected_fire = int(8 * seq.pulses_per_beat) - lookahead_pulses

	assert scheduled.next_fire_pulse == expected_fire


@pytest.mark.asyncio
async def test_schedule_task_no_defer_fires_at_zero (patch_midi: None) -> None:

	"""schedule_task without defer should backshift to fire at pulse 0."""

	seq = subsequence.sequencer.Sequencer(output_device_name="Dummy MIDI", initial_bpm=120)

	def my_task () -> None:
		pass

	await subsequence.composition.schedule_task(sequencer=seq, fn=my_task, cycle_beats=8)

	_, _, scheduled = seq.callback_queue[0]

	# Without defer, backshift puts the first fire at pulse 0 (or close to it).
	# The next_fire_pulse should be less than one full cycle.
	one_cycle = int(8 * seq.pulses_per_beat)

	assert scheduled.next_fire_pulse < one_cycle


@pytest.mark.asyncio
async def test_initial_runs_sync_fn_before_patterns () -> None:

	"""wait_for_initial=True should block on a sync function via run_in_executor."""

	order: typing.List[str] = []

	def populate () -> None:
		order.append("initial")

	# Simulate what _run() does: gather initial tasks.
	async def _run_initial (fn: typing.Callable) -> None:
		if asyncio.iscoroutinefunction(fn):
			await fn()
		else:
			await asyncio.get_running_loop().run_in_executor(None, fn)

	pending = subsequence.composition._PendingScheduled(
		fn=populate, cycle_beats=32, reschedule_lookahead=1, wait_for_initial=True
	)

	await asyncio.gather(*[_run_initial(t.fn) for t in [pending]])

	order.append("patterns")

	assert order == ["initial", "patterns"]


@pytest.mark.asyncio
async def test_initial_runs_async_fn_before_patterns () -> None:

	"""wait_for_initial=True should block on an async function."""

	order: typing.List[str] = []

	async def populate () -> None:
		order.append("initial")

	async def _run_initial (fn: typing.Callable) -> None:
		if asyncio.iscoroutinefunction(fn):
			await fn()
		else:
			await asyncio.get_running_loop().run_in_executor(None, fn)

	pending = subsequence.composition._PendingScheduled(
		fn=populate, cycle_beats=32, reschedule_lookahead=1, wait_for_initial=True
	)

	await asyncio.gather(*[_run_initial(t.fn) for t in [pending]])

	order.append("patterns")

	assert order == ["initial", "patterns"]


@pytest.mark.asyncio
async def test_initial_failure_does_not_raise () -> None:

	"""An initial function that fails should log a warning, not crash."""

	def bad_fn () -> None:
		raise RuntimeError("network error")

	async def _run_initial (fn: typing.Callable) -> None:
		try:
			if asyncio.iscoroutinefunction(fn):
				await fn()
			else:
				await asyncio.get_running_loop().run_in_executor(None, fn)
		except Exception:
			pass  # Mirrors the logger.warning in _run()

	pending = subsequence.composition._PendingScheduled(
		fn=bad_fn, cycle_beats=32, reschedule_lookahead=1, wait_for_initial=True
	)

	# Should not raise.
	await asyncio.gather(*[_run_initial(t.fn) for t in [pending]])
