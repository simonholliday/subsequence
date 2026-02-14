# Subsequence

**A generative MIDI sequencer for Python.** Define musical patterns as simple functions — Euclidean rhythms, chord progressions, arpeggios — and let them evolve over time. Subsequence handles the clock, the MIDI plumbing, and the scheduling. You handle the music.

Subsequence is built for **MIDI-literate musicians who can write some Python**. Patterns are plain Python functions with full access to conditionals, randomness, and external data. There is no custom language to learn, no audio engine to configure, and no GUI to wrestle with. Everything is code, and code is versionable, shareable, and diffable.

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Composition API](#composition-api)
- [Form (sections)](#form-sections)
- [Seed and deterministic randomness](#seed-and-deterministic-randomness)
- [Terminal display](#terminal-display)
- [Live coding](#live-coding)
- [Demo details](#demo-details)
- [Extra utilities](#extra-utilities)
- [Feature Roadmap](#feature-roadmap)
- [Tests](#tests)

## What it does

- **Patterns as functions.** Each pattern is a decorated Python function that builds a full cycle of notes. The sequencer calls it fresh each cycle, so patterns can evolve — reading the current chord, section, cycle count, or external data to decide what to play.
- **Harmonic intelligence.** Chord progressions are driven by weighted transition graphs (Markov chains with configurable gravity). Three built-in harmonic palettes — `"diatonic_major"`, `"turnaround"`, and `"dark_minor"` — or subclass `ChordGraph` to create your own. Patterns that accept a `chord` parameter automatically receive the current chord.
- **Compositional form.** Define the large-scale structure — intro, verse, chorus, bridge — as a weighted transition graph, a linear list, or a generator. Sections follow probabilistic edges: an intro can play once and never return; a chorus can lead to a breakdown 67% of the time. Patterns read `p.section` to adapt their behavior.
- **Stable clock, just-in-time scheduling.** The sequencer reschedules patterns ahead of their cycle end, so already-queued notes are never disrupted. The clock is rock-solid; pattern logic never blocks MIDI output.
- **Rhythmic tools.** Euclidean and Bresenham rhythm generators, step grids (16th notes by default), swing, velocity shaping via van der Corput sequences, and dropout for controlled randomness. Per-step probability on `hit_steps()` for Elektron-style conditional triggers.
- **Stochastic primitives.** Weighted random choice, no-repeat shuffle, random walks, and probability gates — controlled randomness that sounds intentional, not arbitrary. All available in `subsequence.sequence_utils`.
- **Deterministic seeding.** Set `seed=42` on your Composition and every random decision — chord progressions, form transitions, pattern randomness — becomes repeatable. Run the same code twice, get the same music. Pattern builders access the seeded RNG via `p.rng`.
- **Polyrhythms** emerge naturally by running patterns with different lengths. Pattern length is a float — use `length=9` for 9 quarter notes, `length=10.5` for 21 eighth notes. Patterns can even change length on rebuild via `p.set_length()`.
- **External data integration.** Schedule any function on a repeating beat cycle via `composition.schedule()`. Sync functions run in a thread pool automatically. Store results in `composition.data` and read them from any pattern — connect music to APIs, sensors, files, or anything Python can reach.
- **Terminal visualization.** A persistent status line showing the current bar, section, chord, BPM, and key. Enabled with `composition.display()`. Log messages scroll cleanly above it without disruption.
- **Two API levels.** The Composition API is high-level and declarative — most musicians will never need anything else. The Direct Pattern API gives power users full control over `Pattern` subclasses, `HarmonicState`, and async scheduling.
- **Pattern transforms.** Reverse, double-time, half-time, shift, transpose, and invert — all as post-build methods on the pattern builder. `p.every(4, lambda p: p.reverse())` applies a transform every 4th cycle. `composition.layer()` merges multiple builder functions into one pattern. Place notes first, then reshape them.
- **Live coding.** Modify a running composition without stopping playback. A TCP eval server accepts Python code from the bundled REPL client, an editor, or a raw socket. Change tempo, mute patterns, hot-swap pattern logic, and query state — all while the music plays. Enable with `composition.live()`.
- **Events** let you react to sequencer milestones (`"bar"`, `"start"`, `"stop"`) via `composition.on_event()`.
- **Pure MIDI.** No audio synthesis, no dependencies beyond `mido` and `python-rtmidi`. Route MIDI to any hardware or software synth.

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
import subsequence
import subsequence.sequence_utils

MIDI_DEVICE = "Your MIDI Device:Port"
DRUMS_MIDI_CHANNEL = 9
DRUM_NOTE_MAP = {"kick": 36, "snare": 38, "hh_closed": 42}

composition = subsequence.Composition(device=MIDI_DEVICE, bpm=125, key="E", seed=42)
composition.harmony(style="dark_minor", cycle_beats=4, dominant_7th=True, gravity=0.8)

# Schedule a repeating task — sync functions run in a thread pool automatically.
def fetch_data ():
    composition.data["value"] = some_external_api()

composition.schedule(fetch_data, cycle_beats=32)  # Every 8 bars (32 beats)

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    # Fixed four-on-the-floor kick on a 16-step grid.
    p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

    # Hi-hats with per-step probability — some steps randomly drop out.
    p.hit_steps("hh_closed", list(range(16)), velocity=80, probability=0.8)

    # Euclidean snare with random density, rolled +4 for backbeat offset.
    # p.rng is seeded — same output every run when composition has a seed.
    if p.cycle > 3:
        snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, p.rng.randint(1, 6))
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

## Seed and deterministic randomness

Set a seed to make all random behavior repeatable:

```python
composition = subsequence.Composition(device=MIDI_DEVICE, bpm=125, key="E", seed=42)
# OR
composition.seed(42)
```

When a seed is set, chord progressions, form transitions, and all pattern randomness produce identical output on every run. Pattern builders access the seeded RNG via `p.rng`:

```python
@composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    # p.rng replaces random.randint/random.choice — deterministic when seeded.
    density = p.rng.choice([3, 5, 7])
    p.euclidean("kick", pulses=density)

    # Per-step probability also uses p.rng by default.
    p.hit_steps("hh_closed", list(range(16)), velocity=80, probability=0.7)
```

`p.rng` is always available, even without a seed — in that case it's a fresh unseeded `random.Random`.

### Stochastic utilities

`subsequence.sequence_utils` provides structured randomness primitives:

| Function | Description |
|----------|-------------|
| `weighted_choice(options, rng)` | Pick from `(value, weight)` pairs — biased selection |
| `shuffled_choices(pool, n, rng)` | N items with no adjacent repeats (Max/MSP `urn`) |
| `random_walk(n, low, high, step, rng)` | Values that drift by small steps (Max/MSP `drunk`) |
| `probability_gate(sequence, probability, rng)` | Filter a binary sequence by probability |

All require an explicit `rng` parameter — use `p.rng` in pattern builders:

```python
# Wandering hi-hat velocity
walk = subsequence.sequence_utils.random_walk(16, low=50, high=110, step=15, rng=p.rng)
for i, vel in enumerate(walk):
    p.hit_steps("hh_closed", [i], velocity=vel)

# Weighted density choice
density = subsequence.sequence_utils.weighted_choice([(3, 0.5), (5, 0.3), (7, 0.2)], p.rng)
p.euclidean("snare", pulses=density)
```

## Terminal display

Enable a live status line showing the current bar, section, chord, BPM, and key with a single call:

```python
composition.display()
composition.play()
```

The status line updates every bar and looks like:

```
125 BPM  Key: E  Bar: 17  [chorus 1/8]  Chord: Em7
```

When form is not configured, the section is omitted. When harmony is not configured, the chord is omitted. Log messages scroll cleanly above the status line without disruption.

To disable:

```python
composition.display(enabled=False)
```

## Live coding

Modify a running composition without stopping playback. Subsequence includes a TCP eval server that accepts Python code from any source — the bundled REPL client, an editor plugin, or a raw socket. Change tempo, mute patterns, hot-swap pattern logic, and query state — all while the music plays.

### Enable the server

One line before `play()`:

```python
composition.live()      # start on localhost:5555
composition.display()
composition.play()
```

### Connect with the REPL client

In another terminal:

```
$ python -m subsequence.live_client
Connected to Subsequence on 127.0.0.1:5555
{'bpm': 120, 'key': 'C', 'bar': 12, 'section': {'name': 'verse', ...}, 'chord': 'Em7', ...}

>>>
```

### What you can do

**Query state** — see what's playing right now:

```python
>>> composition.live_info()
{'bpm': 120, 'key': 'E', 'bar': 34, 'section': {'name': 'chorus', 'bar': 2, 'bars': 8, 'progress': 0.25}, 'chord': 'Em7', 'patterns': [{'name': 'drums', 'channel': 9, 'length': 4.0, 'cycle': 17, 'muted': False}, ...], 'data': {}}
```

**Change tempo** — hear the difference immediately:

```python
>>> composition.set_bpm(140)
OK
```

**Mute and unmute patterns** — patterns keep cycling silently, so they stay in sync:

```python
>>> composition.mute("hats")
OK
>>> composition.unmute("hats")
OK
```

**Modify shared data** — any value patterns read from `composition.data`:

```python
>>> composition.data["intensity"] = 0.8
OK
```

**Hot-swap a pattern** — redefine the builder function and it takes effect on the next cycle:

```python
>>> @composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
... def drums(p):
...     p.hit_steps("kick", [0, 8], velocity=127)
...     p.hit_steps("snare", [4, 12], velocity=100)
...
OK
```

The running pattern keeps its cycle count, RNG state, and scheduling position — only the builder logic changes.

### Use from any tool

The server speaks a simple text protocol (messages delimited by `\x04`). You can send code from anything that opens a TCP socket:

```bash
# From another terminal with netcat
echo -ne 'composition.set_bpm(140)\x04' | nc localhost 5555

# Or Python one-liner
python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',5555)); s.send(b'composition.live_info()\x04'); print(s.recv(4096).decode())"
```

### Input validation

All code is validated as syntactically correct Python before execution. If you send a typo or malformed code, the server returns a `SyntaxError` traceback — nothing is executed, and the running composition is never affected.

## Demo details

### demo.py — Dark minor composition with form
The demo (`examples/demo.py`) uses the Composition API to schedule drums (kick, snare, hats), chord pads, a cycling arpeggio, and a 16th-note bassline — all on a unified 16-step grid. The form is a weighted graph: the intro (4 bars) plays once then moves to the verse. From the verse (8 bars), the form transitions to the chorus (75%) or a bridge (25%). The chorus (8 bars) leads to a breakdown (67%) or back to the verse (33%). The bridge (4 bars) always goes to the chorus. The breakdown (4 bars) always returns to the verse. The intro never comes back. Each pattern reads `p.section` to control its behavior: the kick always plays, the snare only enters during the chorus, hats are muted during the intro, and chord pads build intensity through each section via `p.section.progress`. A scheduled task fetches the ISS position every 8 bars and stores normalized latitude/longitude in `composition.data`; the snare pattern reads `longitude_norm` to modulate its maximum density. A shared harmonic state advances chords on a 4-beat clock, and any pattern with a `chord` parameter automatically receives the current chord when it rebuilds. The advanced demo (`examples/demo_advanced.py`) shows the same composition using direct `Pattern` subclassing for power users. Press Ctrl+C to stop.

### arpeggiator.py — Polyrhythmic arpeggios
The arpeggiator (`examples/arpeggiator.py`) demonstrates polyrhythmic capabilities with seven patterns cycling at five different lengths. A steady 4-beat drum pattern anchors the piece while arpeggios at 3, 5, 7, and 10.5 beats weave around it, creating 3:4, 5:4, and 7:4 polyrhythms. A second drum pattern runs on a 6-beat / 12-step triplet grid using General MIDI drum names from `subsequence.constants.gm_drums`. The 10.5-beat bass arpeggio demonstrates float length support (21 eighth notes). Turnaround harmony drifts between keys for infinite evolution. Full phase alignment takes 420+ beats, so the piece always sounds fresh.

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
- `subsequence.constants.durations` provides beat-based duration constants. Import as `import subsequence.constants.durations as dur` and write `length = 9 * dur.SIXTEENTH` or `step = dur.DOTTED_EIGHTH` instead of raw floats. Constants: `THIRTYSECOND`, `SIXTEENTH`, `DOTTED_SIXTEENTH`, `TRIPLET_EIGHTH`, `EIGHTH`, `DOTTED_EIGHTH`, `TRIPLET_QUARTER`, `QUARTER`, `DOTTED_QUARTER`, `HALF`, `DOTTED_HALF`, `WHOLE`.
- `subsequence.constants.gm_drums` provides the General MIDI Level 1 drum note map. `GM_DRUM_MAP` can be passed as `drum_note_map`; individual constants like `KICK_1` are also available.
- `subsequence.constants.pulses` provides pulse-based MIDI timing constants used internally by the engine.
- `subsequence.live_server` provides the TCP eval server for live coding. Started internally by `composition.live()`.
- `subsequence.live_client` provides the interactive REPL client. Run with `python -m subsequence.live_client`.
- `subsequence.composition` provides the `Composition` class and internal scheduling helpers.

## Feature Roadmap

Planned features, roughly in order of priority.

### High priority

- **Example library.** A handful of short compositions in different styles (techno, ambient, jazz, minimal) so musicians can hear what the tool can do before investing time.

### Medium priority

- **Mini-notation.** An optional string shorthand (e.g., `"x . x [x x]"`) that compiles to `hit_steps` calls for quick rhythm entry.
- **MIDI input / CC mapping.** Map a hardware knob to `composition.data` so Subsequence feels like a hybrid hardware/software instrument.
- **Ableton Link / MIDI clock sync.** Sync with DAWs and other devices for integration into existing studio setups.

### Future ideas

- Jupyter notebook mode for interactive examples
- Chord inversions and voice leading
- Embeddable engine mode (run as a library inside games or installations)
- MIDI file export for capturing sessions into a DAW

## Tests
This project uses `pytest`.

```
pytest
```

Async tests use `pytest-asyncio`. Install test dependencies with:

```
pip install -e .[test]
```
