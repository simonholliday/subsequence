"""Vermona DRM1 MKIV drum note map.

Note assignments for the Vermona DRM1 analog drum synthesizer.
These note numbers correspond to the factory default trigger assignments.

Two ways to use this module:

1. **As a drum_note_map** - pass ``VERMONA_DRM1_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"kick"``
   or ``"snare"`` in your pattern builder calls::

       import subsequence.constants.instruments.vermona_drm1_drums as drm1

       @composition.pattern(channel=9, length=4, drum_note_map=drm1.VERMONA_DRM1_DRUM_MAP)
       def drums (p):
           p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

2. **As constants** - reference note numbers directly::

       import subsequence.constants.instruments.vermona_drm1_drums as drm1

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(drm1.KICK, [0, 4, 8, 12], velocity=127)
"""

import typing


# ─── Individual note constants ───────────────────────────────────────

KICK = 36                # C2
DRUM_1 = 45              # A2
DRUM_2 = 50              # D3
MULTI = 56               # G#3
SNARE = 38               # D2
HIHAT_1_CLOSED = 44      # G#2
HIHAT_1_OPEN = 46        # A#2 (Cymbal)
HIHAT_2_CLOSED = 49      # C#3
HIHAT_2_OPEN = 51        # D#3 (Cymbal)
CLAP = 39                # D#2


# ─── Complete drum note map ──────────────────────────────────────────

VERMONA_DRM1_DRUM_MAP: typing.Dict[str, int] = {
	"kick": KICK,
	"drum_1": DRUM_1,
	"drum_2": DRUM_2,
	"multi": MULTI,
	"snare": SNARE,
	"hihat_1_closed": HIHAT_1_CLOSED,
	"hihat_1_open": HIHAT_1_OPEN,
	"hihat_2_closed": HIHAT_2_CLOSED,
	"hihat_2_open": HIHAT_2_OPEN,
	"clap": CLAP,
}
