"""MIDI timing constants.

This module defines pulse-based timing constants for standard MIDI note durations.
The sequencer uses **24 pulses per quarter note** (PPQN = 24) as its time base.

All duration constants represent the number of pulses for each note value:
- `MIDI_QUARTER_NOTE = 24` — one beat (the base unit)
- `MIDI_SIXTEENTH_NOTE = 6` — one sixteenth note (common for step sequencing)
- `MIDI_EIGHTH_NOTE = 12` — one eighth note
- `MIDI_HALF_NOTE = 48` — two beats
- `MIDI_WHOLE_NOTE = 96` — four beats

These constants are used internally for pulse-level timing. Pattern builders work in beats,
and the sequencer converts beat positions to pulses using `MIDI_QUARTER_NOTE`.
"""

# MIDI Standards - number of pulses in each

MIDI_THIRTYSECOND_NOTE = 3
MIDI_SIXTEENTH_NOTE = 6
MIDI_EIGHTH_NOTE = 12
MIDI_QUARTER_NOTE = 24
MIDI_HALF_NOTE = 48
MIDI_WHOLE_NOTE = 96
