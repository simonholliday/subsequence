"""Tests for ScheduleContext injection into composition.schedule() callbacks."""

import asyncio
import typing

import subsequence.composition


async def _wait_for (condition: typing.Callable[[], bool], deadline: float = 2.0, poll: float = 0.01) -> None:

	"""Poll until `condition()` is true or the deadline passes.

	Sync callbacks complete on executor threads, so a fixed number of
	zero-sleeps can flake under load — polling a condition is deterministic.
	"""

	loop = asyncio.get_running_loop()
	end = loop.time() + deadline

	while not condition():
		if loop.time() >= end:
			return

		await asyncio.sleep(poll)


# ---------------------------------------------------------------------------
# Unit tests for _make_safe_callback directly (synchronous wrappers)
# ---------------------------------------------------------------------------

def test_schedule_context_dataclass () -> None:

	"""ScheduleContext is a plain dataclass with a cycle field."""

	ctx = subsequence.composition.ScheduleContext(cycle=3)
	assert ctx.cycle == 3


def test_make_safe_callback_no_context_zero_args () -> None:

	"""A zero-arg callback should still be wrapped without error."""

	called: list = []

	def my_task () -> None:
		called.append(True)

	# Creating the wrapper should not raise
	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=False)
	assert callable(wrapped)


def test_make_safe_callback_context_increments () -> None:

	"""Each _execute() call should increment cycle_count inside the closure."""

	received: list = []

	def my_task (p: subsequence.composition.ScheduleContext) -> None:
		received.append(p.cycle)

	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=True)

	async def run () -> None:

		# Fire all three calls first, then wait for every spawned task to finish.
		for _ in range(3):
			wrapped(0)

		await _wait_for(lambda: len(received) == 3)

	asyncio.run(run())

	# Sync callbacks run via loop.run_in_executor (a thread pool), so completion
	# order across the three fire-and-forget tasks is not guaranteed — under load
	# they can finish out of order.  The real invariant is that each trigger ran
	# exactly once with its own captured cycle, i.e. the multiset {0, 1, 2}.
	assert sorted(received) == [0, 1, 2]


def test_make_safe_callback_start_cycle_offset () -> None:

	"""start_cycle seeds the cycle counter so cycles stay monotonic after a pre-roll.

	Regression: a wait_for_initial task runs once as cycle 0 (blocking pre-roll),
	then its repeating wrapper must start at cycle 1 — previously it restarted at 0,
	yielding a non-monotonic 0, 0, 1, 2… contradicting ScheduleContext's docstring.
	"""

	received: list = []

	def my_task (p: subsequence.composition.ScheduleContext) -> None:
		received.append(p.cycle)

	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=True, start_cycle=1)

	async def run () -> None:

		for _ in range(3):
			wrapped(0)

		await _wait_for(lambda: len(received) == 3)

	asyncio.run(run())

	assert sorted(received) == [1, 2, 3]


def test_make_safe_callback_no_context_flag () -> None:

	"""When accepts_context=False the function is called with zero args."""

	received: list = []

	def my_task () -> None:
		received.append("called")

	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=False)

	async def run () -> None:
		wrapped(0)
		await _wait_for(lambda: len(received) == 1)

	asyncio.run(run())

	assert received == ["called"]


def test_fn_has_parameter_detects_p () -> None:

	"""_fn_has_parameter correctly identifies 'p' in the signature."""

	def with_p (p) -> None: ...        # noqa: E704
	def without_p () -> None: ...      # noqa: E704
	def wrong_name (ctx) -> None: ...  # noqa: E704

	assert subsequence.composition._fn_has_parameter(with_p, "p") is True
	assert subsequence.composition._fn_has_parameter(without_p, "p") is False
	assert subsequence.composition._fn_has_parameter(wrong_name, "p") is False
