
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
