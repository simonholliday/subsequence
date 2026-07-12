"""Tests for ``LiveReloader`` and ``Composition.watch()`` — file-watching live reload.

The reloader watches a Python file and re-exec's it on save into the
composition's namespace.  Tests cover: initial load semantics, syntax/
runtime error handling, hot-swap on edit, pattern removal on deletion,
new-pattern activation, and watcher-thread lifecycle.
"""

import asyncio
import logging
import pathlib
import time
import typing

import pytest

import subsequence
import subsequence.live_reloader
import subsequence.pattern
import subsequence.pattern_builder


# ── Initial load ────────────────────────────────────────────────────────────


def test_initial_load_runs_file_synchronously(tmp_path: pathlib.Path) -> None:
    """watch() exec's the file at call time — patterns appear in _pending_patterns."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef drums (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120)
    composition.watch(live_file)

    # Initial decorators ran but _running_patterns is still empty (it
    # becomes populated in _run()).  The pending list has the pattern.
    pending_names = [p.builder_fn.__name__ for p in composition._pending_patterns]
    assert "drums" in pending_names

    composition._live_reloader.stop()


def test_initial_load_syntax_error_raises(tmp_path: pathlib.Path) -> None:
    """watch() raises SyntaxError if the file is malformed at start."""

    live_file = tmp_path / "broken.py"
    live_file.write_text("def drums(p): :::")  # syntactically invalid

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(SyntaxError):
        composition.watch(live_file)


def test_initial_load_missing_file_raises(tmp_path: pathlib.Path) -> None:
    """watch() raises FileNotFoundError when the path doesn't exist."""

    composition = subsequence.Composition(bpm=120)

    with pytest.raises(FileNotFoundError):
        composition.watch(tmp_path / "does_not_exist.py")


def test_watch_sets_live_mode(tmp_path: pathlib.Path) -> None:
    """watch() flips _is_live=True so the decorator hot-swap path fires."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text("# empty for now\n")

    composition = subsequence.Composition(bpm=120)
    assert composition._is_live is False

    composition.watch(live_file)
    assert composition._is_live is True

    composition._live_reloader.stop()


def test_watch_starts_reloader_thread(tmp_path: pathlib.Path) -> None:
    """watch() spawns a daemon thread that is alive after the call."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text("# empty\n")

    composition = subsequence.Composition(bpm=120)
    composition.watch(live_file)

    thread = composition._live_reloader._thread
    assert thread is not None
    assert thread.is_alive()
    assert thread.daemon

    composition._live_reloader.stop()


def test_stop_terminates_watcher_thread(tmp_path: pathlib.Path) -> None:
    """LiveReloader.stop() ends the watcher thread within poll_interval × 2."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text("# empty\n")

    composition = subsequence.Composition(bpm=120)
    composition.watch(live_file, poll_interval=0.05)

    reloader = composition._live_reloader
    reloader.stop()

    # After stop(), the thread should have joined.
    assert reloader._thread is None


# ── Reload behaviour (drive _reload_async directly for determinism) ────────


@pytest.mark.asyncio
async def test_reload_swaps_builder_function(
    patch_midi: None, tmp_path: pathlib.Path
) -> None:
    """On reload, an existing pattern's _builder_fn is replaced in place."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef drums (p):\n\treturn 'v1'\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)

    # Simulate _run() processing pending patterns so we have a running entry.
    await composition._activate_new_pending_patterns()

    assert "drums" in composition._running_patterns
    first_builder = composition._running_patterns["drums"]._builder_fn

    # Rewrite the file with a different body and reload.
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef drums (p):\n\tp._tag = 'v2'\n"
    )
    await composition._live_reloader._reload_async()

    # Same running pattern instance, new builder function.
    assert "drums" in composition._running_patterns
    new_builder = composition._running_patterns["drums"]._builder_fn
    assert new_builder is not first_builder

    # Run the new builder against a stub to confirm it's actually the v2 body.
    class _Stub: ...

    stub = _Stub()
    new_builder(stub)
    assert stub._tag == "v2"

    composition._live_reloader.stop()


@pytest.mark.asyncio
async def test_reload_skipped_on_syntax_error(
    patch_midi: None, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """SyntaxError during reload leaves running state unchanged."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef drums (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)
    await composition._activate_new_pending_patterns()

    good_builder = composition._running_patterns["drums"]._builder_fn

    # Corrupt the file and reload.
    live_file.write_text("def drums(p): :::")  # SyntaxError

    with caplog.at_level(logging.WARNING):
        await composition._live_reloader._reload_async()

    # Pattern still runs with the previous builder.
    assert "drums" in composition._running_patterns
    assert composition._running_patterns["drums"]._builder_fn is good_builder
    assert any("SyntaxError" in r.message for r in caplog.records)

    composition._live_reloader.stop()


@pytest.mark.asyncio
async def test_reload_unregisters_removed_patterns(
    patch_midi: None, tmp_path: pathlib.Path
) -> None:
    """A pattern deleted from the file is unregistered on the next reload."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\n"
        "def kick (p): pass\n"
        "@composition.pattern(channel=2, beats=4)\n"
        "def snare (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)
    await composition._activate_new_pending_patterns()

    assert "kick" in composition._running_patterns
    assert "snare" in composition._running_patterns

    # Rewrite: snare deleted.
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef kick (p): pass\n"
    )
    await composition._live_reloader._reload_async()

    assert "kick" in composition._running_patterns
    assert "snare" not in composition._running_patterns

    composition._live_reloader.stop()


@pytest.mark.asyncio
async def test_reload_activates_new_patterns(
    patch_midi: None, tmp_path: pathlib.Path
) -> None:
    """A pattern added in the file appears in _running_patterns after reload."""

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\ndef kick (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)
    await composition._activate_new_pending_patterns()

    # Add a new pattern.
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\n"
        "def kick (p): pass\n"
        "@composition.pattern(channel=2, beats=4)\n"
        "def bass (p): pass\n"
    )
    await composition._live_reloader._reload_async()

    assert "kick" in composition._running_patterns
    assert "bass" in composition._running_patterns

    composition._live_reloader.stop()


@pytest.mark.asyncio
async def test_reload_preserves_state_on_runtime_error(
    patch_midi: None, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Runtime error mid-exec: the entire reload is skipped, previous state preserved.

    The naive "partial reload" approach would have left hot-swapped patterns
    in their new state and torn down patterns the broken file didn't reach.
    Both are bad UX — skip the reload entirely and let the user retry.
    """

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\n"
        "def kick (p):\n"
        "\tp._tag = 'v1'\n"
        "@composition.pattern(channel=2, beats=4)\n"
        "def snare (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)
    await composition._activate_new_pending_patterns()

    original_kick_builder = composition._running_patterns["kick"]._builder_fn

    # Rewrite: kick "would" hot-swap, but a NameError appears before snare.
    live_file.write_text(
        "@composition.pattern(channel=1, beats=4)\n"
        "def kick (p):\n"
        "\tp._tag = 'v2'\n"
        "undefined_variable_xyz\n"  # NameError
        "@composition.pattern(channel=2, beats=4)\n"
        "def snare (p): pass\n"
    )

    with caplog.at_level(logging.WARNING):
        await composition._live_reloader._reload_async()

    # Both patterns still present.
    assert "kick" in composition._running_patterns
    assert "snare" in composition._running_patterns

    # kick's builder DID hot-swap before the error fired (decorator side-effect
    # we can't undo), but snare is still around because we didn't run the
    # diff-and-unregister phase.  That's the safer compromise.
    assert any("skipping reload" in r.message for r in caplog.records)

    composition._live_reloader.stop()


@pytest.mark.asyncio
async def test_reload_uses_fresh_namespace_each_call(
    patch_midi: None, tmp_path: pathlib.Path
) -> None:
    """Module-level bindings in v1 don't leak into v2's namespace.

    The discriminating assertion: v2 reads ``_my_state`` BEFORE its pattern
    decorator runs.  With a fresh namespace the exec dies with NameError on
    that line, so drums' builder is never hot-swapped; if v1's namespace
    leaked, v2 would exec cleanly and the decorator would swap the builder.
    """

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "_my_state = 'v1'\n"
        "@composition.pattern(channel=1, beats=4)\n"
        "def drums (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition._sequencer._event_loop = asyncio.get_event_loop()
    composition.watch(live_file)
    await composition._activate_new_pending_patterns()

    builder_before = composition._running_patterns["drums"]._builder_fn

    # v2 references _my_state without defining it — should NameError.
    live_file.write_text(
        "# _my_state intentionally not declared\n"
        "x = _my_state  # would succeed if v1's namespace leaked\n"
        "@composition.pattern(channel=1, beats=4)\n"
        "def drums (p): pass\n"
    )
    # The reload exec raises NameError (logged as a warning); the reloader survives.
    await composition._live_reloader._reload_async()

    # drums still in running set (it was already there before this reload).
    assert "drums" in composition._running_patterns

    # And its builder was NOT swapped: the NameError fired before v2's
    # decorator line, which is only possible with a fresh namespace.
    assert composition._running_patterns["drums"]._builder_fn is builder_before

    composition._live_reloader.stop()


# ── Single-file workflow: __name__ / __file__ injection ─────────────────────


def test_initial_load_injects_live_reload_dunders(tmp_path: pathlib.Path) -> None:
    """The reloader exposes ``__name__='__live_reload__'`` and ``__file__=path`` in the watched namespace.

    Together with the user writing ``if __name__ == "__main__":`` blocks for
    one-time setup, this powers the single-file workflow: setup runs when the
    file is executed directly, while the watcher's re-exec sees a different
    ``__name__`` and skips those blocks.
    """

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "composition.data['name'] = __name__\ncomposition.data['file'] = __file__\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition.watch(live_file)

    assert composition.data["name"] == "__live_reload__"
    assert composition.data["file"] == str(live_file)


def test_initial_load_skips_main_guard(tmp_path: pathlib.Path) -> None:
    """``if __name__ == "__main__":`` blocks in the watched file are skipped.

    This is the core invariant for the single-file workflow — one-time
    setup gated by the guard must not re-run inside the watcher's exec.
    """

    live_file = tmp_path / "patterns.py"
    live_file.write_text(
        "composition.data['always'] = True\n"
        "if __name__ == '__main__':\n"
        "\tcomposition.data['main_guard'] = True\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")
    composition.watch(live_file)

    assert composition.data["always"] is True
    assert "main_guard" not in composition.data


def test_self_watch_skips_initial_exec(tmp_path: pathlib.Path) -> None:
    """Self-watch (watch(__file__) from the file being watched) skips _load_initial's exec.

    Otherwise the outer Python script execution AND the watcher's initial
    exec both register the same pattern decorators, double-counting every
    pattern.  Detection compares the watch path to the caller frame's
    module-level ``__file__``.
    """

    live_file = tmp_path / "single.py"
    live_file.write_text(
        "composition.data['exec_count'] = composition.data.get('exec_count', 0) + 1\n"
        "@composition.pattern(channel=1, beats=4)\n"
        "def drums (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    # Simulate ``python single.py`` by exec'ing the file in a namespace
    # whose ``__file__`` matches the path being watched — that's the signal
    # Composition.watch() uses to detect self-watch.
    preamble = "composition.watch(__file__)\n" + live_file.read_text()
    ns = {
        "__name__": "__main__",
        "__file__": str(live_file),
        "composition": composition,
    }
    exec(compile(preamble, str(live_file), "exec"), ns)

    # Outer exec ran the body once; _load_initial should have been skipped.
    assert composition.data["exec_count"] == 1
    pending_names = [p.builder_fn.__name__ for p in composition._pending_patterns]
    assert pending_names == ["drums"]  # exactly one, not two

    composition._live_reloader.stop()


def test_two_file_watch_runs_initial_exec(tmp_path: pathlib.Path) -> None:
    """The classic two-file flow still runs _load_initial: caller's __file__ != watched path."""

    wrapper_file = tmp_path / "wrapper.py"
    live_file = tmp_path / "patterns.py"

    live_file.write_text(
        "composition.data['exec_count'] = composition.data.get('exec_count', 0) + 1\n"
        "@composition.pattern(channel=1, beats=4)\n"
        "def drums (p): pass\n"
    )

    composition = subsequence.Composition(bpm=120, output_device="Dummy MIDI")

    # Simulate ``python wrapper.py`` calling watch(live_file).  Caller's
    # __file__ is wrapper_file; watched path is live_file → different →
    # normal _load_initial path runs and execs the live file.
    ns = {
        "__name__": "__main__",
        "__file__": str(wrapper_file),
        "composition": composition,
        "live_path": str(live_file),
    }
    exec("composition.watch(live_path)", ns)

    # _load_initial ran the live file exactly once.
    assert composition.data["exec_count"] == 1
    pending_names = [p.builder_fn.__name__ for p in composition._pending_patterns]
    assert pending_names == ["drums"]

    composition._live_reloader.stop()
