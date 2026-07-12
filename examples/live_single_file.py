"""Single-file live coding — one file watches itself.

Run this file with ``python examples/live_single_file.py``.  Edit and
save it in your editor — patterns reload on the next bar without
stopping the clock, exactly like the two-file watch workflow.

Why two phases in one file work
───────────────────────────────

The file is exec'd twice over its lifetime:

1. **At startup** by Python's normal script execution.  ``__name__`` is
   ``"__main__"`` and the ``if __name__ == "__main__":`` blocks run —
   that's where we build the ``Composition``, open MIDI ports, attach
   the watcher and call ``play()``.

2. **On every save** by the watcher's re-exec.  ``__name__`` is
   ``"__live_reload__"`` (injected by the live namespace builder), so
   the same ``if __name__ == "__main__":`` blocks are *skipped*.  Only
   the unguarded top-level code re-runs: form, scales, constants, and
   the ``@composition.pattern`` decorators (which hot-swap in place).

Rule of thumb
─────────────

* **Inside ``if __name__ == "__main__":``** — anything that should run
  once: MIDI ports, harmony engine, ``composition.watch(__file__)``,
  ``composition.display(...)``, ``composition.play()``.
* **Outside the guard** — anything you want to iterate on live:
  patterns, scales, constants, and form structure if you want to tweak
  it without restarting.

The two-file workflow (``examples/live_init.py`` + ``examples/live_patterns.py``)
is still supported and recommended if you prefer the misuse-impossible
separation — see the README "Live coding via file watching" section.
"""

import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums


# ── One-time setup ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    composition = subsequence.Composition(bpm=120, key="E")
    composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

    # Self-watch — ``__file__`` is this file's path when run as a script.
    composition.watch(__file__)


# ── Re-runs on every save ───────────────────────────────────────────────────

DRUMS_CHANNEL = 10


@composition.pattern(channel=DRUMS_CHANNEL, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
    p.hit_steps("snare_1", [4, 12], velocity=90)
    p.hit_steps("hi_hat_closed", range(16), velocity=70)


# ── Start playing ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    composition.play()
