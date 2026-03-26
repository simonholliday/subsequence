"""General MIDI Level 1 instrument program numbers.

All 128 GM Level 1 instrument assignments, organised into 16 families of 8.
Use these constants with ``p.program_change()`` to select instruments on
GM-compatible synthesizers and sound modules.

Usage::

    import subsequence.constants.instruments.gm_instruments as gm

    @composition.pattern(channel=1, length=4)
    def strings (p):
        p.program_change(gm.VIOLIN)
        p.note(60, beat=0)

    # Lookup by name
    gm.GM_INSTRUMENT_MAP["flute"]        # 73
    gm.GM_INSTRUMENT_NAMES[73]           # "Flute"

    # Family ranges
    gm.GM_FAMILIES["piano"]              # (0, 7)

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

# Re-export everything from pymididefs.gm — all instrument constants and lookup tables.
from pymididefs.gm import *  # noqa: F401,F403
from pymididefs.gm import (  # noqa: F401 — explicit re-exports for type checkers
	GM_FAMILIES,
	GM_INSTRUMENT_MAP,
	GM_INSTRUMENT_NAMES,
)
