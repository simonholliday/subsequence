"""Live-coding entry point - runs once and watches the live pattern file.

Workflow: run ``python examples/live_init.py``, then open
``examples/live_patterns.py`` in your editor and edit + save - patterns
hot-swap on the next bar without stopping the clock.

The split is intentional: anything that should run once at startup
(MIDI device selection, harmony engine, form definition, tempo) lives
in this wrapper file.  Anything you want to iterate on at runtime
(``@composition.pattern`` definitions) lives in ``live_patterns.py``.

Things worth knowing
────────────────────

Module-level state in the live file (e.g. a ``MelodicState``) is
recreated on every reload, and the live file cannot see names defined
here.  For long-lived state, create it in this file before the
``watch()`` call, put it on ``composition.data``, and read it back from
``composition.data`` in the live file.

A save replaces each pattern's body, and any decorator argument you
changed (``channel``, ``beats``, ``min_energy`` and the rest), heard from
its next cycle.  Only a changed ``device`` waits until you restart.

Syntax errors are caught before exec and skipped - your previous
patterns keep running until you fix and save again.  Runtime errors
during reload are also caught and skip the rest of the reload, so a
half-broken save won't tear down working patterns.

Patterns deleted from the live file are automatically unregistered on
the next save: sounding notes are stopped (including drones, and notes
on every mirror destination) and the pattern is dropped from rotation.
"""

import pathlib

import subsequence


LIVE_FILE = pathlib.Path(__file__).parent / "live_patterns.py"


composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, key_pull=0.2)

# Watch the live file - changes are picked up on save.
composition.watch(LIVE_FILE)


if __name__ == "__main__":
	composition.play()
