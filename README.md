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
- **Scheduled tasks** let any function run on a repeating beat cycle via `composition.schedule()`. Sync functions run in a thread pool so they never block the MIDI clock. Failed tasks are logged and never crash playback.
- **Shared data store** (`composition.data`) lets scheduled tasks publish values that pattern builders can read — connecting music to external inputs (APIs, sensors, files).
- **Form** defines the large-scale structure as a weighted transition graph (or linear list/generator). Sections follow weighted edges — an intro can play once and never return. Patterns read `p.section` to decide what to play in each section.
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
composition.harmony(style="dark_minor", cycle_beats=4, dominant_7th=True, gravity=0.8)

# Schedule a repeating task — sync functions run in a thread pool automatically.
def fetch_data ():
    composition.data["value"] = some_external_api()

composition.schedule(fetch_data, cycle_beats=32)  # Every 8 bars (32 beats)

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    # Fixed four-on-the-floor kick on a 16-step grid.
    p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

    # Use external data to modulate pattern — defaults handle missing values gracefully.
    density = composition.data.get("value", 0.5)

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

## Form (sections)

Define the large-scale structure of your composition with `composition.form()`. Patterns read `p.section` to decide what to play.

### Graph-based form

A dict defines a weighted transition graph. Each section has a bar count and a list of `(next_section, weight)` transitions. Weights control probability — `3:1` means 75%/25%. Sections with an empty list `[]` self-loop forever. Sections with `None` are terminal — the form ends after they complete.

```python
# Intro plays once, then never returns. The outro ends the piece.
composition.form({
    "intro":     (4, [("verse", 1)]),
    "verse":     (8, [("chorus", 3), ("bridge", 1)]),
    "chorus":    (8, [("breakdown", 2), ("verse", 1), ("outro", 1)]),
    "bridge":    (4, [("chorus", 1)]),
    "breakdown": (4, [("verse", 1)]),
    "outro":     (4, None),
}, start="intro")

@composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

    # Mute snare outside the chorus — the pattern keeps cycling silently.
    if not p.section or p.section.name != "chorus":
        return

    # Build intensity through the section (0.0 → ~1.0).
    vel = int(80 + 20 * p.section.progress)
    p.hit_steps("snare", [4, 12], velocity=vel)
```

### List-based form

A list of `(name, bars)` tuples plays sections in order. With `loop=True`, it cycles back to the start:

```python
composition.form([("intro", 4), ("verse", 8), ("chorus", 8)], loop=True)
```

### Generator form

Generators support stochastic or evolving structures:

```python
def my_form ():
    yield ("intro", 4)
    while True:
        yield ("verse", random.choice([8, 16]))
        yield ("chorus", 8)

composition.form(my_form())
```

### SectionInfo

`p.section` is a `SectionInfo` object (or `None` when no form is configured):

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | Current section name |
| `bar` | `int` | Bar within section (0-indexed) |
| `bars` | `int` | Total bars in this section |
| `progress` | `float` | `bar / bars` (0.0 → ~1.0) |
| `first_bar` | `bool` | True on the first bar of the section |
| `last_bar` | `bool` | True on the last bar of the section |

`p.bar` is always available (regardless of form) and tracks the global bar count since playback started.

## Demo details
The demo (`examples/demo.py`) uses the Composition API to schedule drums (kick, snare, hats), chord pads, a cycling arpeggio, and a 16th-note bassline — all on a unified 16-step grid. The form is a weighted graph: the intro (4 bars) plays once then moves to the verse. From the verse (8 bars), the form transitions to the chorus (75%) or a bridge (25%). The chorus (8 bars) leads to a breakdown (67%) or back to the verse (33%). The bridge (4 bars) always goes to the chorus. The breakdown (4 bars) always returns to the verse. The intro never comes back. Each pattern reads `p.section` to control its behavior: the kick always plays, the snare only enters during the chorus, hats are muted during the intro, and chord pads build intensity through each section via `p.section.progress`. A scheduled task fetches the ISS position every 8 bars and stores normalized latitude/longitude in `composition.data`; the snare pattern reads `longitude_norm` to modulate its maximum density. A shared harmonic state advances chords on a 4-beat clock, and any pattern with a `chord` parameter automatically receives the current chord when it rebuilds. The advanced demo (`examples/demo_advanced.py`) shows the same composition using direct `Pattern` subclassing for power users. Press Ctrl+C to stop.

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
