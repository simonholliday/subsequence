"""Roland TR-8S drum note map.

Note assignments for the Roland TR-8S drum machine.
These note numbers correspond to the factory default trigger assignments
for the 11 instrument tracks.

Two ways to use this module:

1. **As a drum_note_map** - pass ``ROLAND_TR8S_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use track names like ``"bd"``
   or ``"sd"`` in your pattern builder calls::

       import subsequence.constants.instruments.roland_tr8s_drums as tr8s

       @composition.pattern(channel=9, length=4, drum_note_map=tr8s.ROLAND_TR8S_DRUM_MAP)
       def drums (p):
           p.hit_steps("bd", [0, 4, 8, 12], velocity=127)

2. **As constants** - reference note numbers directly::

       import subsequence.constants.instruments.roland_tr8s_drums as tr8s

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(tr8s.BD, [0, 4, 8, 12], velocity=127)
"""

import typing


# ─── Individual note constants ───────────────────────────────────────

BD = 36          # Bass Drum
SD = 38          # Snare Drum
LT = 43          # Low Tom
MT = 47          # Mid Tom
HT = 50          # High Tom
RS = 37          # Rim Shot
CP = 39          # Hand Clap
CH = 42          # Closed Hi-Hat
OH = 46          # Open Hi-Hat
CC = 49          # Crash Cymbal
RC = 51          # Ride Cymbal


# ─── Complete drum note map ──────────────────────────────────────────

ROLAND_TR8S_DRUM_MAP: typing.Dict[str, int] = {
	"bd": BD,
	"sd": SD,
	"lt": LT,
	"mt": MT,
	"ht": HT,
	"rs": RS,
	"cp": CP,
	"ch": CH,
	"oh": OH,
	"cc": CC,
	"rc": RC,
}
