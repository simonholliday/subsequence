"""Watch a Python file and re-exec it on save into a live composition.

Provides ``LiveReloader``, the engine behind ``Composition.watch(path)``.
Together they enable file-based live coding: edit a Python file in your
normal editor, save, and the running composition picks up the changes
without stopping the clock.

How it works
────────────

``Composition.watch(path)`` constructs a ``LiveReloader`` and calls
``start()``.

``start()`` performs an initial synchronous load — reads the file and
delegates to ``Composition.load_patterns()``, which compiles and execs
the source into a namespace that has ``composition`` and ``subsequence``
in scope.  This is the first chance for ``@composition.pattern``
decorators in the file to register with the composition.  If the initial
load fails (``SyntaxError``, missing file), the exception propagates —
the user should know immediately if their entry point is broken.

A daemon thread is then spawned that polls the file's ``st_mtime`` every
``poll_interval`` seconds.  When the mtime changes, the thread schedules
``_reload_async()`` onto the composition's event loop via
``asyncio.run_coroutine_threadsafe()``, so mutation happens on the event
loop thread (where the rest of the sequencer lives).

``_reload_async()`` reads + compiles the file content, then delegates to
``Composition._apply_source_async()`` for exec, pattern activation, and
diff-and-unregister against the running set.  Errors from any phase are
logged but do not abort the watcher.

Existing patterns hot-swap in place via the decorator path: when the
same function name is re-decorated while ``_is_live=True``, the running
pattern's ``_builder_fn`` is replaced and the next rebuild uses the new
logic.  The pattern's channel, mirrors, device, and cycle counter are
preserved — only the build logic changes.

Error handling
──────────────

``SyntaxError`` during a reload — log a warning and skip the reload
entirely.  Previous state is preserved.  The user fixes the file and
saves again; the next mtime tick retries.

Runtime error during ``exec()`` (e.g. ``NameError``, ``ImportError``)
— treated the same way: log a warning and skip the rest of the reload.
``Composition._apply_source_async`` re-raises exec failures specifically
so this catch can suppress the diff-and-unregister phase, which would
otherwise tear down patterns the broken file failed to reach.  Note
that decorators that already side-effect'd before the error fired
cannot be rolled back — those builders will run their new bodies on
the next reschedule.

File missing or unreadable mid-poll — log a warning, skip, retry next
tick.  Editor "atomic save" (write-temp-then-rename) is handled by
catching ``OSError`` around the read.

Module-level state in the watched file
──────────────────────────────────────

Each reload uses a fresh namespace dict.  Module-level objects in the
watched file (e.g. ``state = MelodicState(...)``) are recreated on every
reload — long-lived state belongs on ``composition.data`` or in the
wrapper script (the file that calls ``composition.watch()``), not in
the live file itself.

Security note
─────────────

This module calls ``exec()`` on arbitrary Python by design.  Treat the watched
file like any other source file in your project; never point it at
untrusted content.
"""

import asyncio
import logging
import os
import pathlib
import threading
import traceback
import typing


if typing.TYPE_CHECKING:
    import subsequence.composition


logger = logging.getLogger(__name__)


class LiveReloader:
    """Watch a Python file and re-exec it on save into a live composition.

    Constructed by ``Composition.watch(path)``; users do not instantiate
    this class directly.  Owns a daemon thread that polls the file's
    modification time and a reference back to the composition for
    scheduling reloads onto its event loop.
    """

    def __init__(
        self,
        composition: "subsequence.composition.Composition",
        path: typing.Union[str, pathlib.Path],
        poll_interval: float = 0.25,
        skip_initial_exec: bool = False,
    ) -> None:
        """Initialise the reloader in a stopped state.

        Parameters:
                composition: The live ``Composition`` instance to reload into.
                path: Path to the Python file to watch.
                poll_interval: Seconds between ``st_mtime`` polls.  Default
                        0.25 s gives a responsive feel for editor saves without
                        busy-waiting.
                skip_initial_exec: When ``True``, ``start()`` skips the
                        compile + exec phase of the initial load and only records
                        ``_last_mtime``.  Set by ``Composition.watch()`` when it
                        detects a self-watch (the file calling ``watch()`` is the
                        file being watched), since the outer Python script execution
                        will already run the patterns at the module level — a second
                        exec via ``_load_initial`` would double-register every one.
        """

        self._composition = composition
        self._path: pathlib.Path = pathlib.Path(path)
        self._poll_interval = poll_interval
        self._skip_initial_exec = skip_initial_exec

        # Last known mtime; set by the initial load and updated on each
        # detected change.  Used by the watcher loop to skip unchanged ticks.
        self._last_mtime: typing.Optional[float] = None

        # Daemon thread state — created on start().
        self._thread: typing.Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Perform the initial synchronous load, then spawn the watcher thread.

        Raises :exc:`SyntaxError` or :exc:`FileNotFoundError` if the file
        cannot be loaded — better to fail loudly here than to leave the
        user wondering why no patterns are running.

        Safe to call once.  A second call while the watcher is already
        running is a no-op.
        """

        if self._thread is not None and self._thread.is_alive():
            logger.debug(f"LiveReloader.start() no-op: already watching {self._path}")
            return

        # Initial load — synchronous, on the calling thread.  Raises on failure.
        self._load_initial()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name=f"subsequence-live-reloader-{self._path.name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"LiveReloader watching {self._path} (poll {self._poll_interval}s)")

    def stop(self) -> None:
        """Signal the watcher thread to exit; safe to call multiple times.

        Joins the thread with a short timeout so shutdown is bounded.
        """

        self._stop_event.set()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval * 2 + 0.5)

        self._thread = None

    # ── Internals ──────────────────────────────────────────────────────────

    def _load_initial(self) -> None:
        """Synchronous first load; raises on failure.

        Reads, compiles and execs the file on the calling thread.  Doesn't
        go through ``Composition.load_patterns()`` because that method
        schedules onto the event loop when one is running and waits via
        ``future.result()`` — which would deadlock if ``watch()`` happens
        to be called from inside the event loop (e.g. in tests).  The
        ``_load_initial`` contract is pre-play setup, so direct exec is
        correct here: decorators populate ``_pending_patterns`` and the
        composition's ``play()`` graduates them.

        When ``self._skip_initial_exec`` is ``True`` (single-file self-watch),
        the compile+exec step is skipped — the outer Python script will run
        the decorators itself.  We still stat for ``_last_mtime`` so the
        watcher loop doesn't immediately re-trigger on the first poll.
        """

        if not self._skip_initial_exec:
            content = self._path.read_text(encoding="utf-8")
            compiled = compile(content, str(self._path), "exec")

            namespace = self._composition._build_live_namespace(
                source_label=str(self._path)
            )

            # Mirror _apply_source_async's bookkeeping so the FIRST save can
            # already diff against what this file declares now — recording
            # only this file's names, not the wrapper script's.
            self._composition._declared_names = set()
            exec(compiled, namespace)
            self._composition._source_declared[str(self._path)] = set(
                self._composition._declared_names
            )

        try:
            self._last_mtime = os.stat(self._path).st_mtime
        except OSError:
            self._last_mtime = None

    def _watch_loop(self) -> None:
        """Polling loop running in the daemon thread.

        Stats the file every ``poll_interval`` seconds; on detected mtime
        change, schedules :meth:`_reload_async` onto the composition's
        event loop via :func:`asyncio.run_coroutine_threadsafe`.
        """

        while not self._stop_event.is_set():
            logger.debug("polling file %s", self._path)

            try:
                mtime = os.stat(self._path).st_mtime
            except OSError:
                # File disappeared or became unreadable — wait it out.
                # Editors that save via write-temp-then-rename can produce
                # brief windows like this.
                self._stop_event.wait(self._poll_interval)
                continue

            # != rather than >: a timestamp-preserving replacement (mv backup.py
            # watched.py) can legitimately have an OLDER mtime.
            if self._last_mtime is None or mtime != self._last_mtime:
                loop = self._composition._sequencer._event_loop

                if loop is None:
                    # Event loop isn't running yet (watch() called before play(),
                    # or play() not called).  Don't advance _last_mtime — the
                    # next poll will pick up the same change and try again.
                    logger.debug("LiveReloader: no event loop yet, deferring reload")
                else:
                    self._last_mtime = mtime
                    asyncio.run_coroutine_threadsafe(self._reload_async(), loop=loop)

            # Use the stop event's wait() so shutdown is instantaneous instead
            # of having to wait out the full poll interval.
            self._stop_event.wait(self._poll_interval)

    async def _reload_async(self) -> None:
        """Read, compile, apply — runs on the event loop thread.

        Delegates the exec + activate + diff-and-unregister phases to
        ``Composition._apply_source_async``.  We do the compile step here
        (rather than via ``Composition.load_patterns``) so SyntaxError can
        be reported with a watcher-specific log message, and so the apply
        coroutine runs directly on the loop without re-scheduling through
        ``run_coroutine_threadsafe``.

        Errors are logged but do not abort the watcher.
        """

        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"LiveReloader: could not read {self._path}: {exc}")
            return

        # Syntax check — bail early without touching state.
        try:
            compiled = compile(content, str(self._path), "exec")
        except SyntaxError:
            logger.warning(
                f"LiveReloader: SyntaxError in {self._path}, skipping reload:\n{traceback.format_exc()}"
            )
            return

        namespace = self._composition._build_live_namespace(
            source_label=str(self._path)
        )

        try:
            await self._composition._apply_source_async(
                compiled, namespace, source_key=str(self._path)
            )
        except Exception:
            # Apply re-raises on exec failure; suppress here so the watcher
            # keeps running.  The diff-and-unregister phase inside
            # _apply_source_async is skipped automatically when exec raises,
            # so previous state is preserved.
            logger.warning(
                f"LiveReloader: error executing {self._path}, skipping reload:\n{traceback.format_exc()}"
            )
            return
