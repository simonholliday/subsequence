"""Load patterns from an in-memory string instead of a file.

Shows ``composition.load_patterns(source)`` — useful when patterns arrive
from somewhere other than the local filesystem.  A typical use case is a
small web service that accepts pattern uploads from a trusted contributor:
the HTTP handler takes the request body, calls ``load_patterns`` with it,
and returns the SyntaxError message (or 200) to the uploader.

Two ways to use it:

1. **One-shot session load (this example).**  Call ``load_patterns()``
   before ``play()`` to register an initial set of patterns from a string.
   No watcher thread, no file required.

2. **Hot-swap mid-composition.**  After ``play()``, call ``load_patterns()``
   from a worker thread (e.g. a web handler) to swap patterns in.  Behaves
   exactly like one ``watch()`` reload — same diff-and-unregister semantics.

The source can declare ``@composition.pattern`` decorators just as a
watched file would.  ``composition`` and ``subsequence`` are available
inside the source's namespace.

SECURITY WARNING: ``load_patterns`` ``exec()``s the source with full
Python access in this process.  Only call it with source from trusted
senders.
"""

import subsequence


SOURCE = """
import subsequence.constants.instruments.gm_drums as gm_drums


DRUMS_CHANNEL = 10


@composition.pattern(channel=DRUMS_CHANNEL, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	p.hit_steps("kick_1",        [0, 4, 8, 12], velocity=100)
	p.hit_steps("snare_1",       [4, 12],       velocity=90)
	p.hit_steps("hi_hat_closed", range(16),     velocity=70)
"""


composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

composition.load_patterns(SOURCE, source_label="initial_patterns")


if __name__ == "__main__":
	composition.play()
