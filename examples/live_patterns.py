"""Live-editable pattern file — change me while the composition is running.

The ``composition`` and ``subsequence`` names are provided by the watcher;
do not redefine them here.  Save to apply changes — syntax errors are
skipped, valid edits hot-swap on the next bar.

Try while it's running.

Change the kick to ``[0, 6, 8, 14]`` for a syncopated feel.

Add a ``hi_hat_open`` line at every offbeat: ``[2, 6, 10, 14]``.

Delete the ``drums`` function entirely — drums stop within one bar.

Add a second pattern (e.g. a bass line on ``channel=6``).
"""

import subsequence.constants.instruments.gm_drums as gm_drums


DRUMS_CHANNEL = 10


@composition.pattern(channel=DRUMS_CHANNEL, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
    p.hit_steps("snare_1", [4, 12], velocity=90)
    p.hit_steps("hi_hat_closed", range(16), velocity=70)
