"""MIDI note number constants.

Maps note names to their MIDI note numbers (0–127). Convention: **C4 = 60** (Middle C),
matching the MIDI Manufacturers Association standard and most DAWs (Ableton, Logic, Reaper).

Notes are named ``<Pitch><Octave>`` for naturals and ``<Pitch>S<Octave>`` for sharps::

    import subsequence.constants.midi_notes as notes

    p.note(notes.A4, velocity=100)       # 69
    p.arpeggio(chord.tones(notes.E2))    # 40
    root = notes.C3                      # 48

Range: C_NEG1 (0) through G9 (127). Sharps are provided (e.g. ``CS4`` for C♯4);
flats are enharmonic equivalents (Db4 == CS4 == 61).

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

# Re-export everything from pymididefs.notes — all note constants (C_NEG1..G9),
# lookup tables, and conversion functions.
from pymididefs.notes import *  # noqa: F401,F403
from pymididefs.notes import (  # noqa: F401 — explicit re-exports for type checkers
	NOTE_CLASSES,
	NOTE_NAMES,
	SEMITONE_MAP,
	name_to_note,
	note_to_name,
)
