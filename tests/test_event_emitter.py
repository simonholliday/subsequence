
import pytest
import subsequence.event_emitter


def test_on_and_emit_sync () -> None:

	"""Registered sync callbacks are called on emit_sync."""

	emitter = subsequence.event_emitter.EventEmitter()
	received: list[int] = []

	emitter.on("tick", lambda v: received.append(v))
	emitter.emit_sync("tick", 42)

	assert received == [42]


def test_off_removes_callback () -> None:

	"""off() prevents a previously registered callback from being called."""

	emitter = subsequence.event_emitter.EventEmitter()
	received: list[int] = []

	def cb (v: int) -> None:
		received.append(v)

	emitter.on("tick", cb)
	emitter.off("tick", cb)
	emitter.emit_sync("tick", 1)

	assert received == []


def test_off_only_removes_target_callback () -> None:

	"""off() leaves other callbacks for the same event intact."""

	emitter = subsequence.event_emitter.EventEmitter()
	a: list[int] = []
	b: list[int] = []

	def cb_a (v: int) -> None:
		a.append(v)

	def cb_b (v: int) -> None:
		b.append(v)

	emitter.on("tick", cb_a)
	emitter.on("tick", cb_b)
	emitter.off("tick", cb_a)
	emitter.emit_sync("tick", 7)

	assert a == []
	assert b == [7]


def test_off_raises_for_unregistered_callback () -> None:

	"""off() raises ValueError when the callback was never registered."""

	emitter = subsequence.event_emitter.EventEmitter()

	with pytest.raises(ValueError, match="tick"):
		emitter.off("tick", lambda: None)


def test_off_raises_after_already_removed () -> None:

	"""off() raises ValueError when called twice for the same callback."""

	emitter = subsequence.event_emitter.EventEmitter()
	received: list[int] = []

	def cb (v: int) -> None:
		received.append(v)

	emitter.on("tick", cb)
	emitter.off("tick", cb)

	with pytest.raises(ValueError):
		emitter.off("tick", cb)

@pytest.mark.asyncio
async def test_emit_async_isolates_raising_sync_listener () -> None:

	"""A raising sync listener must not silence later listeners or async tasks."""

	emitter = subsequence.event_emitter.EventEmitter()
	calls = []

	def bad () -> None:
		raise RuntimeError("boom")

	def good () -> None:
		calls.append("sync")

	async def good_async () -> None:
		calls.append("async")

	emitter.on("x", bad)
	emitter.on("x", good)
	emitter.on("x", good_async)

	await emitter.emit_async("x")

	assert calls == ["sync", "async"]


@pytest.mark.asyncio
async def test_emit_async_awaits_async_callable_objects () -> None:

	"""An object with async __call__ must be awaited, not silently dropped."""

	emitter = subsequence.event_emitter.EventEmitter()
	calls = []

	class Handler:

		async def __call__ (self) -> None:
			calls.append("handled")

	emitter.on("x", Handler())

	await emitter.emit_async("x")

	assert calls == ["handled"]


@pytest.mark.asyncio
async def test_emit_async_logs_raising_async_listener () -> None:

	"""A raising async listener is logged, never propagated to the emit site."""

	emitter = subsequence.event_emitter.EventEmitter()
	calls = []

	async def bad () -> None:
		raise RuntimeError("boom")

	async def good () -> None:
		calls.append("ok")

	emitter.on("x", bad)
	emitter.on("x", good)

	# Must not raise.
	await emitter.emit_async("x")

	assert calls == ["ok"]
