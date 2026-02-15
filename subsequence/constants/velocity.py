"""MIDI velocity constants.

Velocity is the MIDI attack strength (0-127). These constants define sensible
defaults for different musical contexts.
"""

# Primary defaults
DEFAULT_VELOCITY = 100          # Most notes, hits, arpeggios
DEFAULT_CHORD_VELOCITY = 90     # Chords and harmonic content (softer)

# Velocity shaping boundaries
VELOCITY_SHAPE_LOW = 64
VELOCITY_SHAPE_HIGH = 127

# MIDI standard range
MIN_VELOCITY = 0
MAX_VELOCITY = 127
