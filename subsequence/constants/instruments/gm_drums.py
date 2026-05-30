"""General MIDI Level 1 drum note map.

Standard MIDI percussion assignments for channel 10 (0-indexed channel 9).
These note numbers are supported by virtually all GM-compatible instruments,
drum machines, and DAWs.

Two ways to use this module:

1. **As a drum_note_map** - pass ``GM_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"kick"``,
   ``"snare"``, or the numbered ``"kick_1"`` in your pattern builder calls::

       import subsequence.constants.instruments.gm_drums

       @composition.pattern(channel=9, length=4, drum_note_map=subsequence.constants.instruments.gm_drums.GM_DRUM_MAP)
       def drums (p):
           p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

2. **As constants** - reference note numbers directly::

       import subsequence.constants.instruments.gm_drums

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(subsequence.constants.instruments.gm_drums.KICK, [0, 4, 8, 12], velocity=127)

This map is the canonical GM percussion key map **plus** the unnumbered
"primary" aliases (``"kick"`` / ``"snare"`` / ``"crash"`` / ``"ride"`` → the
``_1`` variant), so a pattern can use either ``"kick"`` or ``"kick_1"``.  The
pure, one-name-per-note spec map is always available upstream as
``pymididefs.drums.GM_DRUM_MAP``.

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

import typing

import pymididefs.drums

# Re-export every GM drum constant and the primary-alias names (KICK, SNARE,
# CRASH, RIDE, GM_DRUM_PRIMARY_ALIASES) so callers can write e.g.
# ``gm_drums.KICK`` or ``gm_drums.KICK_1``.
from pymididefs.drums import *  # noqa: F401,F403

# The composition-facing map: the canonical GM Level 1 percussion key map plus
# the unnumbered primary aliases.  Merged here (not upstream) so the spec map at
# ``pymididefs.drums.GM_DRUM_MAP`` stays one name per note.  The annotated
# assignment deliberately specialises the spec map re-exported by ``import *``
# above (hence the no-redef suppression).
GM_DRUM_MAP: typing.Dict[str, int] = {  # type: ignore[no-redef]
	**pymididefs.drums.GM_DRUM_MAP,
	**pymididefs.drums.GM_DRUM_PRIMARY_ALIASES,
}
