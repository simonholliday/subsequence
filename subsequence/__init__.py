
"""
Subsequence is a musician-centric generative MIDI sequencer for Python.

It provides a high-level, expressive API for composing music with code,
focusing on rhythmic and harmonic intelligence, deterministic randomness,
and live coding capabilities.

Key concepts:
- **Composition**: The top-level container for your piece. Defines BPM, key, and form.
- **Patterns**: Decorated functions that build musical content bar-by-bar using a `PatternBuilder`.
- **Harmony**: Built-in harmonic gravity models (NIR) and chord progression generators.
- **Conductor**: Global automation signals (LFOs, Ramps) for dynamic modulation.
- **Live Coding**: Hot-swap pattern logic and query state while the music is playing.

Example:
    ```python
    import subsequence
    
    comp = subsequence.Composition(bpm=120, key="Cm")
    
    @comp.pattern(channel=0)
    def melody(p):
        p.euclidean(60, pulses=7)
        p.velocity_shape(60, 100)
        
    comp.play()
    ```
"""

import subsequence.composition


Composition = subsequence.composition.Composition
