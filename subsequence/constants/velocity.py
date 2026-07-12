"""MIDI velocity constants.

Velocity is the MIDI attack strength (0-127). These constants define sensible
defaults for different musical contexts.
"""

# Primary defaults
DEFAULT_VELOCITY = 100  # Most notes, hits, arpeggios
DEFAULT_CHORD_VELOCITY = 90  # Chords and harmonic content (softer)

# Generative / texture defaults — named so these values don't scatter as raw literals
DEFAULT_GENERATIVE_VELOCITY = (
    80  # Generative melodic lines (lsystem, de_bruijn, evolve, branch, lorenz, …)
)
DEFAULT_CA_VELOCITY = 60  # Cellular automata (cellular_1d / cellular_2d)
GHOST_FILL_VELOCITY = 35  # Deliberately soft ghost-note layer

# Velocity shaping boundaries
VELOCITY_SHAPE_LOW = 64
VELOCITY_SHAPE_HIGH = 127

# MIDI standard range
MIN_VELOCITY = 0
MAX_VELOCITY = 127
