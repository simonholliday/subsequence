# Subsequence

Subsequence is a generative MIDI sequencer built in Python. It schedules patterns "just in time," so music can evolve continuously without stopping. Patterns are defined as collections of notes in pulse time, and when a pattern is scheduled its current state is copied into the sequencer's event queue. This lets patterns mutate over time without affecting already-scheduled notes.

## Key ideas
- **Composition API** wraps the engine in a musician-friendly interface — define patterns as simple functions and let the module handle scheduling, async, and MIDI plumbing.
- **Patterns** store notes in pulses and can evolve each reschedule cycle.
- **PatternBuilder** provides high-level musical verbs (`note`, `hit`, `fill`, `chord`, `euclidean`, `bresenham`, `dropout`, `swing`, `velocity_shape`).
- **Sequencer** keeps a stable clock, handles note on/off, and reschedules patterns ahead of their cycle end.
- **Polyrhythms** emerge by running patterns with different lengths.
- **Harmony** evolves via a weighted Markov transition graph; patterns that accept a `chord` parameter automatically receive the current harmonic state.
- **Motifs & swing** utilities support expressive timing and reusable note fragments.
- **Composition clocks** advance harmony independently of any specific pattern.

## Quick start
1. Install dependencies:
```
pip install -e .
```
2. Edit `examples/demo.py` to set your MIDI device name (line 24)
3. Run the demo (drums + evolving harmony in E major):
```
python examples/demo.py
```

## Composition API

The `Composition` class is the main entry point. Define your MIDI setup, create a composition, add patterns, and play:

```python
import subsequence

MIDI_DEVICE = "Your MIDI Device:Port"
DRUMS_MIDI_CHANNEL = 9
DRUM_NOTE_MAP = {"kick": 36, "snare": 38, "hh_closed": 42}

composition = subsequence.Composition(device=MIDI_DEVICE, bpm=125, key="E")
composition.harmony(style="turnaround_global", cycle=4, dominant_7th=True)

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def kick (p):
    p.euclidean("kick", pulses=4, velocity=105, dropout=0.2)
    p.hit("snare", beats=[1, 3], velocity=100)

@composition.pattern(channel=6, length=4)
def chords (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True)

if __name__ == "__main__":
    composition.play()
```

MIDI channels, device names, and drum note mappings are defined by the musician in their composition file — the module does not ship studio-specific constants.

## Demo details
The demo (`examples/demo.py`) uses the Composition API to schedule drums (kick, snare, hats), chord pads, a swung motif, and a 16th-note bassline. A 5-beat hi-hat pattern creates polyrhythm against the 4-beat core. A shared harmonic state advances chords on a 4-beat clock, and any pattern with a `chord` parameter automatically receives the current chord when it rebuilds. The advanced demo (`examples/demo_advanced.py`) shows the same composition using direct `Pattern` subclassing for power users. Press Ctrl+C to stop.

## Extra utilities
- `subsequence.pattern_builder` provides the `PatternBuilder` with high-level musical methods.
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.swing` applies swing timing to a pattern.
- `subsequence.intervals` contains interval and scale definitions for future harmonic work.
- `subsequence.event_emitter` supports sync/async events for later extensibility.
- `subsequence.chord_graphs` contains chord transition graphs (functional and global turnaround).
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
