"""General MIDI Level 1 drum note map.

Standard MIDI percussion assignments for channel 10 (0-indexed channel 9).
These note numbers are supported by virtually all GM-compatible instruments,
drum machines, and DAWs.

Two ways to use this module:

1. **As a drum_note_map** - pass ``GM_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"kick_1"``
   or ``"snare_1"`` in your pattern builder calls::

       import subsequence.constants.instruments.gm_drums

       @composition.pattern(channel=9, length=4, drum_note_map=subsequence.constants.instruments.gm_drums.GM_DRUM_MAP)
       def drums (p):
           p.hit_steps("kick_1", [0, 4, 8, 12], velocity=127)

2. **As constants** - reference note numbers directly::

       import subsequence.constants.instruments.gm_drums

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(subsequence.constants.instruments.gm_drums.KICK_1, [0, 4, 8, 12], velocity=127)

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

# Re-export everything from pymididefs.drums — all drum constants and the lookup dict.
from pymididefs.drums import *  # noqa: F401,F403
from pymididefs.drums import GM_DRUM_MAP  # noqa: F401 — explicit re-export for type checkers
