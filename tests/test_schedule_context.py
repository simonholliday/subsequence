"""Tests for ScheduleContext injection into composition.schedule() callbacks."""

import subsequence.composition


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

	import asyncio

	received: list = []

	def my_task (p: subsequence.composition.ScheduleContext) -> None:
		received.append(p.cycle)

	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=True)

	async def run () -> None:

		# Fire all three calls first, then drain the event loop.
		for _ in range(3):
			wrapped(0)

		# Multiple yields to let each spawned coroutine run to completion.
		for _ in range(10):
			await asyncio.sleep(0)

	asyncio.run(run())

	assert received == [0, 1, 2]


def test_make_safe_callback_no_context_flag () -> None:

	"""When accepts_context=False the function is called with zero args."""

	import asyncio

	received: list = []

	def my_task () -> None:
		received.append("called")

	wrapped = subsequence.composition._make_safe_callback(my_task, accepts_context=False)

	async def run () -> None:
		wrapped(0)
		await asyncio.sleep(0)

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
