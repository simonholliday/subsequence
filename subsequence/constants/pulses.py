"""Pulse-based MIDI timing constants.

The sequencer uses **24 pulses per quarter note** (PPQN = 24) as its internal time base.
These constants represent the number of pulses for each standard note duration.

These are used internally by the sequencer engine. Pattern builders work in beats
(see ``subsequence.constants.durations`` for beat-based constants).
"""

# MIDI Standards - number of pulses in each

MIDI_THIRTYSECOND_NOTE = 3
MIDI_SIXTEENTH_NOTE = 6
MIDI_EIGHTH_NOTE = 12
MIDI_QUARTER_NOTE = 24
MIDI_HALF_NOTE = 48
MIDI_WHOLE_NOTE = 96
