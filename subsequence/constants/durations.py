"""Beat-based duration constants for pattern lengths and note timing.

All values are in **beats**, where 1.0 = one quarter note. Use these to express
pattern lengths and step sizes in musical terms instead of raw floats.

Multiply by a count for multi-note durations::

    import subsequence.constants.durations as dur

    # "9 sixteenth notes"
    length = 9 * dur.SIXTEENTH     # 2.25 beats

    # "21 eighth notes"
    length = 21 * dur.EIGHTH       # 10.5 beats

    # "4 bars of quarter notes"
    length = 4 * dur.QUARTER       # 4.0 beats

Use directly for step sizes and note durations::

    p.arpeggio(tones, step=dur.SIXTEENTH, velocity=90)
    p.arpeggio(tones, step=dur.DOTTED_SIXTEENTH, velocity=80)
    p.fill(60, step=dur.EIGHTH)
"""

THIRTYSECOND = 0.125
SIXTEENTH = 0.25
DOTTED_SIXTEENTH = 0.375
TRIPLET_EIGHTH = 1 / 3
EIGHTH = 0.5
DOTTED_EIGHTH = 0.75
TRIPLET_QUARTER = 2 / 3
QUARTER = 1.0
DOTTED_QUARTER = 1.5
HALF = 2.0
DOTTED_HALF = 3.0
WHOLE = 4.0
