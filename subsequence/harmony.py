"""Harmony helpers — diatonic chords without the chord-graph engine.

Standalone convenience functions (``diatonic_chords``, ``diatonic_chord``,
``diatonic_chord_sequence``) for building chords from a key and mode.  For
generative progressions use ``progressions``.
"""

import typing

import subsequence.chords
import subsequence.intervals


def diatonic_chords(
    key: str, mode: str = "ionian"
) -> typing.List[subsequence.chords.Chord]:
    """Return the diatonic triads for a key and mode.

    This is a convenience function for generating chord sequences without
    using the chord graph engine. The returned ``Chord`` objects can be
    passed directly to ``p.chord()`` or ``chord.tones()`` inside a pattern.

    Parameters:
            key: Note name for the key (e.g., ``"C"``, ``"Eb"``, ``"F#"``).
            mode: A mode with chord qualities defined (e.g. ``"ionian"``,
                    ``"dorian"``, ``"minor"``). Scales without chord qualities
                    (e.g. ``"hirajoshi"``) will raise ``ValueError`` — use
                    ``p.snap_to_scale()`` for pitch snapping instead.

    Returns:
            List of ``Chord`` objects, one per scale degree.

    Example:
            ```python
            # All 7 chords in Eb Major
            chords = subsequence.harmony.diatonic_chords("Eb")

            # Natural minor chords in A
            chords = subsequence.harmony.diatonic_chords("A", mode="minor")

            # Dorian chords in D
            chords = subsequence.harmony.diatonic_chords("D", mode="dorian")
            ```
    """

    if mode not in subsequence.intervals.SCALE_MODE_MAP:
        available = ", ".join(sorted(subsequence.intervals.SCALE_MODE_MAP.keys()))
        raise ValueError(f"Unknown mode: {mode!r}. Available: {available}")

    _, qualities = subsequence.intervals.SCALE_MODE_MAP[mode]

    if qualities is None:
        raise ValueError(
            f"Mode {mode!r} has no chord qualities defined. "
            "Use register_scale(..., qualities=[...]) to add them, "
            "or use p.snap_to_scale() for pitch snapping without harmony."
        )
    key_pc = subsequence.chords.key_name_to_pc(key)
    scale_pcs = subsequence.intervals.scale_pitch_classes(key_pc, mode)

    return [
        subsequence.chords.Chord(root_pc=root_pc, quality=quality)
        for root_pc, quality in zip(scale_pcs, qualities)
    ]


def diatonic_chord(
    key: str,
    mode: str = "ionian",
    degree: int = 0,
) -> subsequence.chords.Chord:
    """Return a single diatonic chord by scale degree.

    Convenience wrapper around :func:`diatonic_chords` for the common
    case where only one chord is needed.

    Parameters:
            key: Root note name (e.g. ``"E"``, ``"Bb"``).
            mode: Scale mode (default ``"ionian"``).
            degree: Zero-indexed scale degree (0 = I/tonic, 4 = V/dominant, etc.).

    Raises:
            ValueError: If *degree* is out of range for the mode.

    Example:
            ```python
            tonic = diatonic_chord("E", "phrygian")              # I
            dominant = diatonic_chord("E", "phrygian", degree=4)  # V
            ```
    """

    chords = diatonic_chords(key, mode)

    if degree < 0 or degree >= len(chords):
        raise ValueError(
            f"degree {degree} out of range for {mode} (0\u2013{len(chords) - 1})"
        )

    return chords[degree]


def diatonic_chord_sequence(
    key: str, root_midi: int, count: int, mode: str = "ionian"
) -> typing.List[typing.Tuple[subsequence.chords.Chord, int]]:
    """Return a list of ``(Chord, midi_root)`` tuples stepping diatonically upward.

    Useful for mapping a continuous value (like altitude or brightness) to a
    chord, or for building explicit rising/falling progressions without using
    the chord graph engine.

    The returned list has ``count`` entries. Each entry contains the ``Chord``
    object (quality and pitch class) and the exact MIDI note number to use as
    that chord's root. Pass both directly to ``p.chord(chord, root=midi_root)``.

    Counts larger than the number of scale degrees wrap into higher octaves
    automatically. The sequence always steps upward — reverse the list for
    a falling sequence.

    Parameters:
            key: Note name for the key (e.g., ``"D"``, ``"Eb"``, ``"F#"``).
            root_midi: MIDI note number for the first chord's root. Must fall on a
                    scale degree of the chosen key and mode.
            count: Number of ``(Chord, midi_root)`` pairs to generate.
            mode: One of ``"ionian"`` (or ``"major"``), ``"dorian"``,
                    ``"phrygian"``, ``"lydian"``, ``"mixolydian"``,
                    ``"aeolian"`` (or ``"minor"``), ``"locrian"``,
                    ``"harmonic_minor"``, ``"melodic_minor"``.

    Returns:
            List of ``(Chord, int)`` tuples, one per step.

    Raises:
            ValueError: If ``key`` or ``mode`` is not recognised, or if
                    ``root_midi`` does not fall on a scale degree of the key.

    Example:
            ```python
            # 7-step D Major ladder starting at D3 (MIDI 50)
            sequence = subsequence.harmony.diatonic_chord_sequence("D", root_midi=50, count=7)

            # Map a 0-1 value to a chord (e.g. from ISS altitude)
            chord, root = sequence[int(ratio * (len(sequence) - 1))]
            p.chord(chord, root=root, sustain=True)

            # Falling sequence
            for chord, root in reversed(subsequence.harmony.diatonic_chord_sequence("A", 57, 7, "minor")):
                ...
            ```
    """

    # Validate mode before looking up the scale key. diatonic_chords() also
    # validates internally, but diatonic_chord_sequence() is called directly
    # from user code so we give a clear error here without going deeper.
    if mode not in subsequence.intervals.SCALE_MODE_MAP:
        available = ", ".join(sorted(subsequence.intervals.SCALE_MODE_MAP.keys()))
        raise ValueError(f"Unknown mode: {mode!r}. Available: {available}")

    scale_key, _ = subsequence.intervals.SCALE_MODE_MAP[mode]
    scale_ivs = subsequence.intervals.get_intervals(scale_key)

    key_pc = subsequence.chords.key_name_to_pc(key)
    start_pc = root_midi % 12

    # Locate the scale degree that matches the starting MIDI note.
    start_degree: typing.Optional[int] = None

    for i, iv in enumerate(scale_ivs):
        if (key_pc + iv) % 12 == start_pc:
            start_degree = i
            break

    if start_degree is None:
        raise ValueError(
            f"MIDI note {root_midi} (pitch class {start_pc}) is not a scale "
            f"degree of {key!r} {mode!r}."
        )

    all_chords = diatonic_chords(key, mode=mode)
    result: typing.List[typing.Tuple[subsequence.chords.Chord, int]] = []

    num_degrees = len(scale_ivs)

    for i in range(count):
        degree = (start_degree + i) % num_degrees
        octave_bump = (start_degree + i) // num_degrees
        midi_root = (
            root_midi + (scale_ivs[degree] - scale_ivs[start_degree]) + 12 * octave_bump
        )
        result.append((all_chords[degree], midi_root))

    return result
