"""Constants for Subsequence.

This package contains three sets of constants:

- ``subsequence.constants.pulses`` - Pulse-based MIDI timing (internal engine use)
- ``subsequence.constants.durations`` - Beat-based durations for pattern lengths and steps
- ``subsequence.constants.gm_drums`` - General MIDI Level 1 drum note map

Pulse constants are re-exported here for backwards compatibility, so
``subsequence.constants.MIDI_QUARTER_NOTE`` continues to work.
"""

# Re-export pulse constants for backwards compatibility.
# These match the values in subsequence.constants.pulses.

MIDI_THIRTYSECOND_NOTE = 3
MIDI_SIXTEENTH_NOTE = 6
MIDI_EIGHTH_NOTE = 12
MIDI_QUARTER_NOTE = 24
MIDI_HALF_NOTE = 48
MIDI_WHOLE_NOTE = 96
