"""Tests for ``Composition.load_patterns()`` — in-memory string source loading.

``load_patterns`` is the string-input analogue of ``watch()``: same compile +
exec + activate-new + unregister-removed pipeline, but the source arrives as a
Python string instead of being read from a file.  The underlying
``_apply_source_async`` coroutine is shared with the file watcher, so these
tests focus on the new string-input surface (compile-time errors, source label
threading, the post-play blocking behaviour) rather than the swap mechanics
covered by ``test_live_reloader.py``.
"""

import asyncio
import pathlib
import typing

import pytest

import subsequence


# ── Pre-play (no event loop) ────────────────────────────────────────────────


def test_load_patterns_registers_new_pattern_pre_play(patch_midi: None) -> None:
    """Before play(), load_patterns exec's on the caller thread; pattern lands in _pending_patterns."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    source = "@composition.pattern(channel=1, beats=4)\ndef drums (p):\n\tpass\n"
    composition.load_patterns(source)

    # Pre-play, decorators populate _pending_patterns; play() graduates them.
    pending_names = [p.builder_fn.__name__ for p in composition._pending_patterns]
    assert "drums" in pending_names


def test_load_patterns_raises_syntax_error(patch_midi: None) -> None:
    """Bad Python source raises SyntaxError synchronously; no state mutated."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    with pytest.raises(SyntaxError):
        composition.load_patterns("def drums(p): :::")

    assert composition._pending_patterns == []
    assert composition._running_patterns == {}


def test_load_patterns_raises_runtime_error(patch_midi: None) -> None:
    """Exception during exec propagates; no decorator-side state from after the failure."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    source = (
        "@composition.pattern(channel=1, beats=4)\n"
        "def first (p): pass\n"
        "raise ValueError('boom')\n"
    )

    with pytest.raises(ValueError, match="boom"):
        composition.load_patterns(source)


def test_load_patterns_uses_source_label_in_compile_error(patch_midi: None) -> None:
    """SyntaxError's filename attribute carries the user-supplied source_label."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    with pytest.raises(SyntaxError) as exc_info:
        composition.load_patterns(
            "def drums(p): :::", source_label="uploaded-session-abc"
        )

    assert exc_info.value.filename == "uploaded-session-abc"


def test_load_patterns_default_source_label(patch_midi: None) -> None:
    """Default source_label is ``<string>``."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    with pytest.raises(SyntaxError) as exc_info:
        composition.load_patterns("def drums(p): :::")

    assert exc_info.value.filename == "<string>"


def test_load_patterns_safe_builtins(patch_midi: None) -> None:
    """Blocked builtins (input/exit/etc.) raise RuntimeError when called in source."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    for blocked in ("help", "input", "breakpoint", "exit", "quit"):
        with pytest.raises(RuntimeError, match="not available in live mode"):
            composition.load_patterns(f"{blocked}()")


def test_load_patterns_sets_live_mode(patch_midi: None) -> None:
    """load_patterns flips _is_live=True so subsequent re-decorations hot-swap."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    assert composition._is_live is False

    composition.load_patterns("# empty")

    assert composition._is_live is True


def test_load_patterns_injects_live_reload_dunders(patch_midi: None) -> None:
    """The exec namespace exposes __name__='__live_reload__' and __file__=source_label.

    Powers the single-file workflow: a user can write
    ``if __name__ == "__main__": composition = subsequence.Composition(...)``
    at the top of a self-watching file and have it skipped during reload.
    """

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    # Source records the dunder values it saw at exec time on composition.data
    # so the test can read them back.
    composition.load_patterns(
        "composition.data['name']  = __name__\ncomposition.data['file']  = __file__\n",
        source_label="uploaded-session-xyz",
    )

    assert composition.data["name"] == "__live_reload__"
    assert composition.data["file"] == "uploaded-session-xyz"


def test_load_patterns_skips_main_guard(patch_midi: None) -> None:
    """``if __name__ == "__main__":`` blocks in the source are skipped at reload-time."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    composition.load_patterns(
        "composition.data['outside_guard'] = True\n"
        "if __name__ == '__main__':\n"
        "\tcomposition.data['inside_guard'] = True\n"
    )

    assert composition.data.get("outside_guard") is True
    assert "inside_guard" not in composition.data


# ── Post-play (event loop running) ──────────────────────────────────────────
#
# Production callers (web handlers, queue consumers, ...) run on a thread
# different from the event loop, so ``load_patterns`` schedules onto the loop
# via ``run_coroutine_threadsafe`` and blocks on the future.  These tests
# simulate that by setting ``_event_loop`` and dispatching the call through
# ``asyncio.to_thread`` so the test stays on the loop while the call runs on a
# worker — exactly the scenario the public API is designed for.


@pytest.mark.asyncio
async def test_load_patterns_swaps_pattern_post_play(patch_midi: None) -> None:
    """With the composition playing, load_patterns swaps a running pattern's builder in place."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    # Initial setup uses the pre-play path (no event loop attached yet).
    composition.load_patterns(
        "@composition.pattern(channel=1, beats=4)\ndef drums (p):\n\tp._tag = 'v1'\n"
    )

    # Simulate play(): attach the loop reference so subsequent calls take
    # the schedule-on-loop branch, and graduate the pre-play pending pattern.
    composition._sequencer._event_loop = asyncio.get_event_loop()
    await composition._activate_new_pending_patterns()

    first_builder = composition._running_patterns["drums"]._builder_fn

    # A post-play load must originate from a thread OTHER than the loop —
    # realistic call-site is a worker thread (web handler, queue consumer).
    # Calling it from the loop thread itself would deadlock the future wait.
    await asyncio.to_thread(
        composition.load_patterns,
        "@composition.pattern(channel=1, beats=4)\ndef drums (p):\n\tp._tag = 'v2'\n",
    )

    new_builder = composition._running_patterns["drums"]._builder_fn
    assert new_builder is not first_builder

    class _Stub: ...

    stub = _Stub()
    new_builder(stub)
    assert stub._tag == "v2"


@pytest.mark.asyncio
async def test_load_patterns_unregisters_removed_post_play(patch_midi: None) -> None:
    """Patterns absent from the new source are unregistered."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    composition.load_patterns(
        "@composition.pattern(channel=1, beats=4)\n"
        "def a (p): pass\n"
        "@composition.pattern(channel=2, beats=4)\n"
        "def b (p): pass\n"
    )

    composition._sequencer._event_loop = asyncio.get_event_loop()
    await composition._activate_new_pending_patterns()
    assert set(composition._running_patterns) == {"a", "b"}

    # Source v2 declares only ``a``; ``b`` should be torn down.
    await asyncio.to_thread(
        composition.load_patterns,
        "@composition.pattern(channel=1, beats=4)\ndef a (p): pass\n",
    )

    assert set(composition._running_patterns) == {"a"}


@pytest.mark.asyncio
async def test_load_patterns_post_play_runtime_error_propagates(
    patch_midi: None,
) -> None:
    """Runtime error during exec post-play surfaces back to the caller as a real exception."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    composition.load_patterns(
        "@composition.pattern(channel=1, beats=4)\ndef keeper (p): pass\n"
    )

    composition._sequencer._event_loop = asyncio.get_event_loop()
    await composition._activate_new_pending_patterns()
    assert "keeper" in composition._running_patterns

    # Broken upload — exec raises mid-source.  The exception should
    # propagate from the worker thread through future.result() back to
    # the test caller.  Previous state should be preserved (the diff /
    # unregister phase inside _apply_source_async is skipped on exec
    # failure, so 'keeper' is not torn down).
    with pytest.raises(ValueError, match="upload-failure"):
        await asyncio.to_thread(
            composition.load_patterns,
            "raise ValueError('upload-failure')\n",
        )

    assert "keeper" in composition._running_patterns


@pytest.mark.asyncio
async def test_load_patterns_refuses_on_loop_thread(patch_midi: None) -> None:
    """Calling from inside the composition's own loop raises rather than deadlocking."""

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()

    # This test is itself running on the loop, so a direct call is the
    # deadlock scenario the safety check exists to prevent.
    with pytest.raises(RuntimeError, match="event loop thread"):
        composition.load_patterns("# empty")
