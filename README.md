# Subsequence

Subsequence is a generative MIDI sequencer built in Python. It schedules patterns "just in time," so music can evolve continuously without stopping. Patterns are defined as collections of notes in pulse time, and when a pattern is scheduled its current state is copied into the sequencer's event queue. This lets patterns mutate over time without affecting already-scheduled notes.

## Key ideas
- **Composition API** wraps the engine in a musician-friendly interface — define patterns as simple functions and let the module handle scheduling, async, and MIDI plumbing.
- **Patterns** store notes in pulses and can evolve each reschedule cycle.
- **PatternBuilder** provides high-level musical verbs (`note`, `hit`, `hit_steps`, `fill`, `arpeggio`, `chord`, `euclidean`, `bresenham`, `dropout`, `swing`, `velocity_shape`).
- **Sequencer** keeps a stable clock, handles note on/off, and reschedules patterns ahead of their cycle end.
- **Polyrhythms** emerge by running patterns with different lengths.
- **Harmony** evolves via weighted chord transition graphs; patterns that accept a `chord` parameter automatically receive the current harmonic state.
- **Chord graphs** define harmonic palettes: `"diatonic_major"` (single-key I–vii), `"turnaround"` (ii-V-I across all keys), and `"dark_minor"` (Phrygian/aeolian minor). Subclass `ChordGraph` to create your own.
- **Events** let you react to sequencer milestones (`"bar"`, `"start"`, `"stop"`) via `composition.on_event()`.
- **Motifs & swing** utilities support expressive timing and reusable note fragments.

## Quick start
1. Install dependencies:
```
pip install -e .
```
2. Edit `examples/demo.py` to set your MIDI device name (line 24)
3. Run the demo (drums + evolving dark minor harmony in E):
```
python examples/demo.py
```

## Composition API

The `Composition` class is the main entry point. Define your MIDI setup, create a composition, add patterns, and play:

```python
import random

import subsequence
import subsequence.sequence_utils

MIDI_DEVICE = "Your MIDI Device:Port"
DRUMS_MIDI_CHANNEL = 9
DRUM_NOTE_MAP = {"kick": 36, "snare": 38, "hh_closed": 42}

composition = subsequence.Composition(device=MIDI_DEVICE, bpm=125, key="E")
composition.harmony(style="dark_minor", cycle=4, dominant_7th=True, gravity=0.8)

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    # Fixed four-on-the-floor kick on a 16-step grid.
    p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

    # Euclidean snare with random density, rolled +4 for backbeat offset.
    if p.cycle > 3:
        snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, random.randint(1, 6))
        snare_steps = subsequence.sequence_utils.sequence_to_indices(snare_seq)
        p.hit_steps("snare", subsequence.sequence_utils.roll(snare_steps, 4, 16), velocity=100)

@composition.pattern(channel=6, length=4)
def chords (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True)

if __name__ == "__main__":
    composition.on_event("bar", lambda bar: print(f"Bar {bar + 1}"))
    composition.play()
```

MIDI channels, device names, and drum note mappings are defined by the musician in their composition file — the module does not ship studio-specific constants.

## Demo details
The demo (`examples/demo.py`) uses the Composition API to schedule drums (kick, snare, hats), chord pads, a cycling arpeggio, and a 16th-note bassline — all on a unified 16-step grid. The kick is fixed four-on-the-floor while the snare uses euclidean generation with `roll()` for backbeat offset. A shared harmonic state advances chords on a 4-beat clock, and any pattern with a `chord` parameter automatically receives the current chord when it rebuilds. The builder's `cycle` property lets patterns evolve over time (e.g. introducing the snare after cycle 3). The advanced demo (`examples/demo_advanced.py`) shows the same composition using direct `Pattern` subclassing for power users. Press Ctrl+C to stop.

## Extra utilities
- `subsequence.pattern_builder` provides the `PatternBuilder` with high-level musical methods.
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.swing` applies swing timing to a pattern.
- `subsequence.intervals` contains interval and scale definitions for harmonic work.
- `subsequence.markov_chain` provides a generic weighted Markov chain utility.
- `subsequence.event_emitter` supports sync/async events used by the sequencer.
- `subsequence.chord_graphs` contains chord transition graphs. Each is a `ChordGraph` subclass with `build()` and `gravity_sets()` methods. Built-in styles: `"diatonic_major"`, `"turnaround"`, `"dark_minor"`.
- `subsequence.weighted_graph` provides a generic weighted graph used for transitions.
- `subsequence.harmonic_state` holds the shared chord/key state for multiple patterns.
- `subsequence.composition` provides the `Composition` class and internal scheduling helpers.

## Tests
This project uses `pytest`.

```
pytest
```

Async tests use `pytest-asyncio`. Install test dependencies with:

```
pip install -e .[test]
```
