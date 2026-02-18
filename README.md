# Subsequence

**A Stateful Algorithmic MIDI Sequencer for Python.** Subsequence combines pattern-based sequencing with the full depth of Python code. It is designed for **the musician who wants compositions that evolve** - where patterns respond to what came before, know where they are in the song, and make musical decisions based on context.

Unlike stateless libraries that loop forever, Subsequence rebuilds patterns each time they play (before they're due). This stateful architecture allows for context-aware harmony, long-form structure, and determinism. You can create complex, evolving compositions where patterns know what happened in the previous bar, as well as traditional linear pieces with fixed notes and sections.

It is a **compositional engine** for your studio - generating pure MIDI to control hardware instruments, modular synthesizers, or VSTs, with no fixed limits on complexity or length.

> **Note:** Subsequence does not produce sound. It generates MIDI data to control existing hardware or software instruments. 

## Introduction

### The "Stateful" Advantage
Most live-coding environments are **stateless**: passing time determines the event. This excels at cyclic, rhythmic music (techno, polyrhythms) but struggles with narrative. Subsequence is **stateful**: it remembers history.

This means a pattern can look back at the previous cycle to decide its next move ("if I played a C last bar, play an E this bar"). It allows for **motivic development** - ideas that evolve over time rather than just repeating. It also supports traditional linear composition: because the system tracks "Song Position" and "Section", you can write a piece with a distinct Intro, Verse, and Chorus, where specific notes play at specific times, just like in a DAW.

### Cognitive Melody Generation
Standard generative tools often rely on "scale masking" (picking random notes from a scale), which ensures no "wrong" notes but often results in aimless melodies.

Subsequence integrates the **Narmour Implication-Realization model**, a theory of music cognition that predicts what listeners *expect* to hear. It models **melodic inertia**:
*   **Implication:** A series of small steps in one direction implies continuation.
*   **Gap-Fill:** A large leap implies a reversal to fill the gap.

By encoding these principles, Subsequence generates melodies that feel structured and intentional, satisfying the listener's innate expectations of musical grammar.

### The Algorithmic Composer
Subsequence is a workbench for **Algorithmic Composition**, NOT an "AI Music Generator".

*   **Don't Prompt. Design.** You define the composition, the computer provides the processing power. You are the composer and conductor, not a spectator.
*   **Code is the Interface.** Patterns are plain text files, meaning your music is versionable, shareable, and collaborative by default. There is no custom language to learn, no audio engine to configure, and no GUI to wrestle with.
*   **Deterministic Control.** Set a seed and get the exact same "random" results every time. Tweak your code and re-run to perfect the output.

Subsequence connects to your existing world. Sync it to your DAW's clock, or let it drive your Eurorack system. It provides the logic; you provide the sound.

## Contents

- [Introduction](#introduction)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Composition API](#composition-api)
- [Direct Pattern API](#direct-pattern-api)
- [Mini-notation](#mini-notation)
- [Form and sections](#form-and-sections)
- [The Conductor](#the-conductor)
- [State vs Signals](#state-vs-signals)
- [Chord inversions and voice leading](#chord-inversions-and-voice-leading)
- [Harmony and chord graphs](#harmony-and-chord-graphs)
- [Seed and deterministic randomness](#seed-and-deterministic-randomness)
- [Terminal display](#terminal-display)
- [Live coding](#live-coding)
- [MIDI input and external clock](#midi-input-and-external-clock)
- [OSC integration](#osc-integration)
- [Examples](#examples)
- [Extra utilities](#extra-utilities)
- [Feature Roadmap](#feature-roadmap)
- [Tests](#tests)
- [About the Author](#about-the-author)
- [License](#license)

## What it does

- **Patterns as functions.** Each pattern is a Python function that builds a full cycle of notes. The sequencer calls it fresh each cycle, so patterns can evolve - reading the current chord, section, cycle count, or external data to decide what to play. Patterns can even change their own length dynamically via `p.set_length()`.
- **Context-Aware Harmony.** Chord progressions drift and evolve, with adjustable pull toward home - each chord leads to the next based on weighted **harmonic probability**.[^markov] Harmony and gravity can be changed on the fly (`composition.harmony()`, `key_gravity_blend`). **Advanced Harmonic Gravity** applies Narmour's Implication-Realization model to give progressions inertia. Eleven built-in harmonic palettes (see [Built-in chord graphs](#built-in-chord-graphs)). Patterns that accept a `chord` parameter automatically receive the current chord. Chord inversions and voice leading keep voices moving smoothly.
- **Architectural Sequencing.** Define the large-scale form - intro, verse, chorus, bridge - as a **Weighted Transition Graph**. Sections follow probabilistic paths: an intro can play once and never return; a chorus can lead to a breakdown 67% of the time. Patterns read `p.section` to adapt their behavior, ensuring the song has structure, not just loops.
- **Stable clock, just-in-time scheduling.** The sequencer reschedules patterns ahead of their cycle end, so already-queued notes are never disrupted. The clock is rock-solid; pattern logic never blocks MIDI output.
- **Rhythmic tools.** Euclidean and Bresenham rhythm generators, step grids (16th notes by default), swing, velocity shaping[^vdc] for natural-sounding variation, and dropout for controlled randomness. Per-step probability on `hit_steps()` for step-based conditional triggers.
- **Randomness tools.**[^stochastic] Weighted random choice, no-repeat shuffle, random walks, and probability gates - controlled randomness that sounds intentional, not arbitrary. All available in `subsequence.sequence_utils`.
- **Mini-notation.** Concise string syntax for rhythms and melodies. Write `p.seq("x x [x x] x", pitch="kick")` instead of verbose list definitions. Supports subdivisions `[...]`, rests `.`/`~`, and sustains `_`.
- **Deterministic seeding.** Set `seed=42` on your Composition and every random decision - chord progressions, form transitions, pattern randomness - becomes repeatable. Run the same code twice, get the same music. Use `p.rng` in your patterns for seeded randomness.
- **Polyrhythms** emerge naturally by running patterns with different lengths. Pattern length can be any number - use `length=9` for 9 quarter notes, `length=10.5` for 21 eighth notes. Patterns can even change length on rebuild via `p.set_length()`.
- **External data integration.** Schedule any function on a repeating beat cycle via `composition.schedule()`. Functions run in the background automatically. Store results in `composition.data` and read them from any pattern - connect music to APIs, sensors, files, or anything Python can reach.
- **Terminal visualization.** A persistent status line showing the current bar, section, chord, BPM, and key. Enabled with `composition.display()`. Log messages scroll cleanly above it without disruption.
- **Two API levels.** The Composition API is straightforward - most musicians will never need anything else. The Direct Pattern API gives power users full control over patterns, harmony, and scheduling.
- **Pattern transforms.** Legato (fills gaps), staccato (fixed duration), reverse, double-time, half-time, shift, transpose, and invert - applied after placing notes. `p.every(4, lambda p: p.reverse())` applies a transform every 4th cycle. `composition.layer()` merges multiple builder functions into one pattern. Place notes first, then reshape them.
- **Live coding.** Modify a running composition without stopping playback. A built-in server accepts Python code from the bundled command-line client, an editor, or a raw socket. Change tempo, mute patterns, hot-swap pattern logic, and query state - all while the music plays. Enable with `composition.live()`.
- **External clock follower.** Sync to an external MIDI clock from a DAW, drum machine, or hardware sequencer. Transport messages (start, stop, continue) are respected automatically. Enable with `composition.midi_input(device, clock_follow=True)`.
- **Events** let you react to sequencer milestones (`"bar"`, `"start"`, `"stop"`) via `composition.on_event()`.
- **Pure MIDI.** No audio synthesis, no dependencies beyond `mido` and `python-rtmidi`. Route MIDI to any hardware or software synth.

## Quick start
1. Install dependencies:
```
pip install -e .
```
2. Run the demo (drums + evolving aeolian minor harmony in E):
```
python examples/demo.py
```

## Composition API

The `Composition` class is the main entry point. Define your MIDI setup, create a composition, add patterns, and play:

```python
import subsequence

DRUMS_CHANNEL = 9
SYNTH_CHANNEL = 0
DRUM_NOTE_MAP = {"kick": 36, "snare": 38, "hh": 42}

composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    p.hit_steps("kick", [0, 4, 8, 12], velocity=127)
    p.hit_steps("snare", [4, 12], velocity=100)
    p.hit_steps("hh", list(range(16)), velocity=80)

@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def chords (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True)

if __name__ == "__main__":
    composition.play()
```

When `output_device` is omitted, Subsequence auto-discovers available MIDI devices. If only one device is connected it is used automatically; if several are found you are prompted to choose. To skip the prompt, pass the device name directly: `Composition(output_device="Your Device:Port", ...)`.

MIDI channels and drum note mappings are defined by the musician in their composition file - the module does not ship studio-specific constants.

Patterns are plain Python functions, so anything you can express in Python is fair game. A few more features:

```python
# Per-step pitch, velocity, and duration control.
@composition.pattern(channel=0, length=4)
def melody (p):
    p.sequence(
        steps=[0, 4, 8, 12],
        pitches=[60, 64, 67, 72],
        velocities=[127, 100, 110, 100],
        durations=[0.5, 0.25, 0.25, 0.5],
    )

# Per-step probability - each hi-hat has a 70% chance of playing.
@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def hats (p):
    p.hit_steps("hh", list(range(16)), velocity=80, probability=0.7)

# Schedule a repeating background task (runs in a thread pool).
def fetch_data ():
    composition.data["value"] = some_external_api()

composition.schedule(fetch_data, cycle_beats=32)
```

## Direct Pattern API

The Direct Pattern API gives you full control over the sequencer, harmony, and scheduling. Patterns are classes instead of decorated functions - you manage the event loop yourself.

This example produces the same music as the Composition API example above (kick, snare, hi-hats, and chord pad in E aeolian minor at 120 BPM):

```python
import asyncio
import subsequence.composition
import subsequence.constants
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer

DRUMS_CHANNEL = 9
SYNTH_CHANNEL = 0
DRUM_KICK = 36
DRUM_SNARE = 38
DRUM_HH = 42


class DrumPattern (subsequence.pattern.Pattern):

    def __init__ (self) -> None:
        super().__init__(channel=DRUMS_CHANNEL, length=4)
        self._build_pattern()

    def _build_pattern (self) -> None:
        self.steps = {}
        step = subsequence.constants.MIDI_SIXTEENTH_NOTE
        self.add_sequence([1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0], step_duration=step, pitch=DRUM_KICK, velocity=127)
        self.add_sequence([0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0], step_duration=step, pitch=DRUM_SNARE, velocity=100)
        self.add_sequence([1]*16, step_duration=step, pitch=DRUM_HH, velocity=80)

    def on_reschedule (self) -> None:
        self._build_pattern()


class ChordPadPattern (subsequence.pattern.Pattern):

    def __init__ (self, harmonic_state) -> None:
        super().__init__(channel=SYNTH_CHANNEL, length=4)
        self.harmonic_state = harmonic_state
        self._build_pattern()

    def _build_pattern (self) -> None:
        self.steps = {}
        chord = self.harmonic_state.get_current_chord()
        root = self.harmonic_state.get_chord_root_midi(52, chord)
        duration = int(self.length * subsequence.constants.MIDI_QUARTER_NOTE)
        for interval in chord.intervals():
            self.add_note(0, root + interval, 90, duration)

    def on_reschedule (self) -> None:
        self._build_pattern()


async def main () -> None:
    seq = subsequence.sequencer.Sequencer(initial_bpm=120)
    harmonic_state = subsequence.harmonic_state.HarmonicState(
        key_name="E", graph_style="aeolian_minor", key_gravity_blend=0.8
    )
    await subsequence.composition.schedule_harmonic_clock(seq, lambda: harmonic_state, cycle_beats=4)

    drums = DrumPattern()
    chords = ChordPadPattern(harmonic_state=harmonic_state)
    await subsequence.composition.schedule_patterns(seq, [drums, chords])
    await subsequence.composition.run_until_stopped(seq)

if __name__ == "__main__":
    asyncio.run(main())
```

For the full version with form, external data, and five patterns, see `examples/demo_advanced.py`.

### API Comparison

| Feature | Composition API | Direct Pattern API |
|---------|-----------------|--------------------|
| **Primary Paradigm** | Declarative / Functional | Object-Oriented (OO) |
| **User Code** | Decorated functions | Pattern subclasses |
| **Complexity** | Low (Musician-friendly) | Medium (Developer-friendly) |
| **Lifecycle** | Automated (`play()`) | Manual (`asyncio.run()`) |
| **State** | Stateless builders | Persistent instance variables |

**1. Composition API** (`composition.py`)
This is the recommended starting point for most musicians. It handles the infrastructure (async loop, MIDI device discovery, clock management) so you can focus on writing patterns.
*   **Best for:** Rapid prototyping, standard song forms, live coding.
*   **Limitation:** Patterns are stateless functions that get rebuilt from scratch every cycle. To keep state (like a counter), you need global variables or closures.

**2. Direct Pattern API** (`pattern.py`)
This gives you full control by letting you subclass `Pattern` directly. It's for power users who need features the Composition API abstracts away.
*   **Unique Capabilities:**
    *   **Persistent State:** Store variables in `self` that persist across cycles (e.g., an evolving density counter).
    *   **Incremental Updates:** In `on_reschedule()`, you can modify existing notes instead of clearing `self.steps`.
    *   **Custom Scheduling:** Launch async tasks that don't align with the pattern's cycle.
    *   **Multiple Contexts:** Run multiple independent sequencers or harmonic states.

*   **Example:** A pattern that gets denser every cycle:
    ```python
    class EvolvingPattern(subsequence.pattern.Pattern):
        def __init__(self):
            super().__init__(channel=0, length=4)
            self.density = 0.5 

        def on_reschedule(self):
            self.density += 0.05  # State persists!
            self.steps = {}       # Clear old notes
            self.euclidean(pulses=int(16 * self.density))
    ```

### Accessing internal state

The `Composition` object stores its harmonic and form state internally. After calling `harmony()` and `form()`:

- `composition._harmonic_state` - the `HarmonicState` object (same one patterns read from)
- `composition._form_state` - the `FormState` object (same one `p.section` reads from)
- `composition._sequencer` - the underlying `Sequencer` instance

If you need `Pattern` subclasses alongside decorated patterns, the simplest approach is to use the Direct Pattern API for the entire composition - create a `HarmonicState` and `FormState` manually, then pass them to both simple helper patterns and complex Pattern subclasses. `examples/demo.py` and `examples/demo_advanced.py` produce the same music using each API.

## Mini-notation

For quick rhythmic or melodic entry, Subsequence offers a concise string syntax inspired by live-coding environments. This allows you to express complex rhythms and subdivisions without verbose list definitions.

### Rhythm (Fixed Pitch)

When you provide a `pitch` argument, the string defines the rhythm. Any symbol (except special characters) is treated as a hit.

```python
@composition.pattern(channel=DRUMS_CHANNEL, length=4)
def drums(p):
    # Kick on beats 0, 2, 3
    p.seq("x . x x", pitch="kick")

    # Hi-hats with subdivisions:
    # [x x] puts two hits in the space of one
    p.seq("x [x x] x x", pitch="hh", velocity=80)
```

### Melody (Symbol as Pitch)

When `pitch` is omitted, the symbols in the string are interpreted as pitches (MIDI note numbers or drum names).

```python
@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def melody(p):
    # Play 60, 62, hold 62, then 64
    # "_" sustains the previous note
    p.seq("60 62 _ 64")
```

### Syntax Reference

| Symbol | Description |
|--------|-------------|
| `x` | Event (note/hit) |
| `.` or `~` | Rest |
| `_` | Sustain (legato) |
| `[ ... ]` | Subdivision |

### Using with Direct Pattern API

While designed for the Composition API, you can use mini-notation in `Pattern` subclasses by wrapping `self` in a `PatternBuilder`:

```python
def _build_pattern(self):
    # Create a transient builder to access high-level features
    p = subsequence.pattern_builder.PatternBuilder(self, cycle=0)
    p.seq("x . x [x x]", pitch=36)
```

## Form and sections

Define the large-scale structure of your composition with `composition.form()`. Patterns read `p.section` to decide what to play.

### Graph-based form

A dict defines a weighted transition graph. Each section has a bar count and a list of `(next_section, weight)` transitions. Weights control probability - `3:1` means 75%/25%. Sections with an empty list `[]` self-loop forever. Sections with `None` are terminal - the form ends after they complete.

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

    # Mute snare outside the chorus - the pattern keeps cycling silently.
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

## The Conductor

Patterns often feel static when they just loop. **The Conductor** provides global signals (LFOs and automation lines) that patterns can read to modulate parameters over time.

### Defining Signals

Create signals in your composition setup:

```python
# A sine wave LFO that cycles every 16 bars
composition.conductor.lfo("swell", shape="sine", cycle_beats=16*4)

# A ramp that builds from 0.0 to 1.0 over 32 bars, then stays at 1.0
composition.conductor.line("intensity", start_val=0.0, end_val=1.0, duration_beats=32*4)
```

### Using Signals in Patterns

Use `p.signal(name)` to read a conductor signal at the current bar:

```python
@composition.pattern(channel=0, length=4)
def pads(p):
    dynamics = p.signal("swell")

    p.chord(chord, root=60, velocity=int(60 + 60 * dynamics))
```

For explicit beat control, use `p.c.get(name, beat)` directly.

## State vs Signals

Subsequence offers two ways to store correct values: **Data** (state) and **Conductor** (signals).

### `composition.data` (State)
*   **"What is the value RIGHT NOW?"**
*   A dictionary for static snapshots. It has no concept of time.
*   Values stay exactly as set until overwritten.
*   **Use for:** External inputs (sensors, API data like ISS position), discrete mode switches, or values that update irregularly.

### `composition.conductor` (Signals)
*   **"What was the value at beat 40?"**
*   A system for time-variant signals.
*   You define a *behavior* (e.g. an LFO), and it calculates the correct value for any given point in time.
*   **Use for:** Musical evolution (fades, swells, modulation) that must be smooth and continuous regardless of tempo.

## Chord inversions and voice leading

By default, chords are played in root position. You can request a specific inversion, or enable automatic voice leading so each chord picks the inversion closest to the previous one.

### Manual inversions

Pass `inversion` to `p.chord()`, `p.strum()`, or `chord.tones()`:

```python
@composition.pattern(channel=0, length=4)
def chords (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True, inversion=1)  # first inversion
```

Inversion 0 is root position, 1 is first inversion, 2 is second, and so on. Values wrap around for chords with fewer notes.

### Strummed chords

`p.strum()` works exactly like `p.chord()` but staggers the notes with a small time offset between each one - like strumming a guitar. The first note always lands on the beat; subsequent notes are delayed by `offset` beats each.

```python
@composition.pattern(channel=0, length=4)
def guitar (p, chord):
    # Gentle upward strum (low to high)
    p.strum(chord, root=52, velocity=85, offset=0.06)

    # Fast downward strum (high to low)
    p.strum(chord, root=52, direction="down", offset=0.03)
```

### Automatic voice leading

Add `voice_leading=True` to the pattern decorator. The injected chord will automatically choose the inversion with the smallest total pitch movement from the previous chord:

```python
@composition.pattern(channel=0, length=4, voice_leading=True)
def chords (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True)
```

Each pattern tracks voice leading independently - a bass line and a pad can voice-lead at their own pace.

### Direct Pattern API

`ChordPattern` accepts `voice_leading=True`:

```python
chords = subsequence.harmony.ChordPattern(
    harmonic_state=harmonic_state, root_midi=52, velocity=90, channel=0, voice_leading=True
)
```

For standalone use, `subsequence.voicings` provides `invert_chord()`, `voice_lead()`, and `VoiceLeadingState`.

### Extended arpeggios

By default, `chord.tones()` and `p.chord()` return one note per chord tone (3 for triads, 4 for sevenths). Pass `count` to cycle the intervals into higher octaves:

```python
@composition.pattern(channel=0, length=4)
def pad (p, chord):
    p.chord(chord, root=52, velocity=90, sustain=True, count=4)  # always 4 notes

@composition.pattern(channel=0, length=4)
def arp (p, chord):
    tones = chord.tones(root=64, count=5)  # 5 notes cycling upward
    p.arpeggio(tones, step=0.25, velocity=90)
```

`count` works with `inversion` - the extended notes continue upward from the inverted voicing.

## Harmony and chord graphs

Subsequence generates chord progressions using **weighted transition graphs**. Each chord has weighted edges to its possible successors, so the progression is probabilistic but musically constrained. On top of the base graph weights, two gravity systems shape which chord is chosen next.

### The `harmony()` method

```python
composition.harmony(
    style="aeolian_minor",
    cycle_beats=4,
    gravity=0.8,
    nir_strength=0.5,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `style` | str or ChordGraph | `"functional_major"` | Built-in name or custom ChordGraph instance |
| `cycle_beats` | int | `4` | Beats per chord change |
| `dominant_7th` | bool | `True` | Include dominant 7th chords |
| `gravity` | float | `1.0` | Key gravity blend (0.0 = functional chords only, 1.0 = full diatonic set) |
| `nir_strength` | float | `0.5` | Melodic inertia (0.0 = off, 1.0 = full). Controls how strongly transitions follow Narmour's Implication-Realization model |
| `minor_weight` | float | `0.0` | Minor turnaround weight (turnaround graph only) |
| `root_diversity` | float | `0.4` | Root-repetition damping (0.0 = maximum, 1.0 = off). Each recent same-root chord multiplies the weight by this factor |

### Built-in chord graphs

| Style | Character |
|-------|-----------|
| `"diatonic_major"` / `"functional_major"` | Standard major key (I-ii-iii-IV-V-vi-vii) |
| `"turnaround"` | Jazz turnaround with optional modulation to relative minor |
| `"aeolian_minor"` | Natural minor with Phrygian cadence option |
| `"phrygian_minor"` | Dark, minimal palette (i-bII-iv-v) |
| `"lydian_major"` | Bright, floating (#IV colour) |
| `"dorian_minor"` | Minor with major IV (soul, funk) |
| `"chromatic_mediant"` | Film-score style third-relation shifts |
| `"suspended"` | Ambiguous sus2/sus4 palette |
| `"mixolydian"` | Major with flat 7th; open, unresolved (EDM, synthwave) |
| `"whole_tone"` | Symmetrical augmented palette; dreamlike drift (IDM, ambient) |
| `"diminished"` | Minor-third symmetry; angular, disorienting (dark, experimental) |

### Harmonic gravity and melodic inertia

Four layers influence which chord comes next:

1.  **Graph weights** - the base transition probabilities defined by the chord graph. A strong cadence (e.g. V-I) has a higher weight than a deceptive resolution (e.g. V-vi).
2.  **Key gravity** - blends between functional pull (tonic, subdominant, dominant) and full diatonic pull. It ensures the progression retains a sense of home.
3.  **Melodic inertia (Narmour)** - applies **'cognitive expectation'** principles to the root motion of the chords. It models the listener's innate sense of musical grammar:
    *   **Process (A+A):** A series of small steps in one direction implies a continuation in that same direction. The melody gathers momentum.
    *   **Gap-Fill (Reversal):** A large leap (> 4 semitones) stretches the "elastic" of pitch space, implying a change of direction to fill the gap.
    *   **Proximity:** Small intervals (1-3 semitones) are generally preferred over large leaps.
    *   **Closure:** Return to tonic gets a gentle boost.
4.  **Root diversity** - an automatic penalty that discourages the same chord root from appearing repeatedly. Each recent chord sharing a candidate's root multiplies the transition weight by `root_diversity` (default 0.4). This prevents progressions from getting stuck on one root, even in graphs with same-root voicing changes (e.g., sus2/sus4 pairs) or strong resolution weights. Set `root_diversity=1.0` to disable.

At `nir_strength=0.0` the system is purely probabilistic (Markov). At `1.0` it is heavily driven by these cognitive rules. The default `0.5` balances structural surprise with melodic coherence.

### Creating a custom chord graph

Subclass `ChordGraph` and implement two methods: `build()` returns a weighted transition graph and the tonic chord, `gravity_sets()` returns the diatonic and functional chord sets for key gravity weighting.

```python
import subsequence

class PowerChords (subsequence.chord_graphs.ChordGraph):

    def build (self, key_name):
        key_pc = subsequence.chord_graphs.validate_key_name(key_name)
        I  = subsequence.chords.Chord(root_pc=key_pc, quality="major")
        IV = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major")
        V  = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="major")

        graph = subsequence.weighted_graph.WeightedGraph()
        graph.add_transition(I, IV, 4)
        graph.add_transition(I, V, 3)
        graph.add_transition(IV, V, 5)
        graph.add_transition(IV, I, 2)
        graph.add_transition(V, I, 6)   # Strong resolution
        graph.add_transition(V, IV, 2)
        return graph, I

    def gravity_sets (self, key_name):
        key_pc = subsequence.chord_graphs.validate_key_name(key_name)
        I  = subsequence.chords.Chord(root_pc=key_pc, quality="major")
        IV = subsequence.chords.Chord(root_pc=(key_pc + 5) % 12, quality="major")
        V  = subsequence.chords.Chord(root_pc=(key_pc + 7) % 12, quality="major")
        all_chords = {I, IV, V}
        return all_chords, {I, V}  # (diatonic, functional)

composition.harmony(style=PowerChords(), cycle_beats=4, gravity=0.8)
```

Higher edge weights mean a transition is more likely. Use the constants `WEIGHT_STRONG` (6), `WEIGHT_MEDIUM` (4), `WEIGHT_COMMON` (3), `WEIGHT_DECEPTIVE` (2), `WEIGHT_WEAK` (1) from `subsequence.chord_graphs` for consistency with the built-in graphs.

## Seed and deterministic randomness

Set a seed to make all random behavior repeatable:

```python
composition = subsequence.Composition(bpm=125, key="E", seed=42)
# OR
composition.seed(42)
```

When a seed is set, chord progressions, form transitions, and all pattern randomness produce identical output on every run. Pattern builders access the seeded RNG via `p.rng`:

```python
@composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums (p):
    # p.rng replaces random.randint/random.choice - deterministic when seeded.
    density = p.rng.choice([3, 5, 7])
    p.euclidean("kick", pulses=density)

    # Per-step probability also uses p.rng by default.
    p.hit_steps("hh_closed", list(range(16)), velocity=80, probability=0.7)
```

`p.rng` is always available, even without a seed - in that case it's a fresh unseeded `random.Random`.

### Stochastic utilities

`subsequence.sequence_utils` provides structured randomness primitives:

| Function | Description |
|----------|-------------|
| `weighted_choice(options, rng)` | Pick from `(value, weight)` pairs - biased selection |
| `shuffled_choices(pool, n, rng)` | N items with no adjacent repeats (classic `urn` algorithm) |
| `random_walk(n, low, high, step, rng)` | Values that drift by small steps (classic `drunk` algorithm) |
| `probability_gate(sequence, probability, rng)` | Filter a binary sequence by probability |

All require an explicit `rng` parameter - use `p.rng` in pattern builders:

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
125 BPM  Key: E  Bar: 17  [chorus 1/8]  Chord: Em7  Swell: 0.42  Tide: 0.78
```

Components adapt to what's configured - the section is omitted if no form is set, the chord is omitted if no harmony is configured, and conductor signals only appear when registered. Log messages scroll cleanly above the status line without disruption.

To disable:

```python
composition.display(enabled=False)
```

## Live coding

Modify a running composition without stopping playback. Subsequence includes a TCP eval server that accepts Python code from any source - the bundled REPL client, an editor plugin, or a raw socket. Change tempo, mute patterns, hot-swap pattern logic, and query state - all while the music plays.

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

**Query state** - see what's playing right now:

```python
>>> composition.live_info()
{'bpm': 120, 'key': 'E', 'bar': 34, 'section': {'name': 'chorus', 'bar': 2, 'bars': 8, 'progress': 0.25}, 'chord': 'Em7', 'patterns': [{'name': 'drums', 'channel': 9, 'length': 4.0, 'cycle': 17, 'muted': False, 'tweaks': {}}, ...], 'data': {}}
```

**Change tempo** - hear the difference immediately:

```python
>>> composition.set_bpm(140)           # instant jump
OK
>>> composition.target_bpm(140, bars=8) # smooth ramp over 8 bars
OK
```

**Mute and unmute patterns** - patterns keep cycling silently, so they stay in sync:

```python
>>> composition.mute("hats")
OK
>>> composition.unmute("hats")
OK
```

**Modify shared data** - any value patterns read from `composition.data`:

```python
>>> composition.data["intensity"] = 0.8
OK
```

**Hot-swap a pattern** - redefine the builder function and it takes effect on the next cycle:

```python
>>> @composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
... def drums(p):
...     p.hit_steps("kick", [0, 8], velocity=127)
...     p.hit_steps("snare", [4, 12], velocity=100)
...
OK
```

The running pattern keeps its cycle count, RNG state, and scheduling position - only the builder logic changes.

**Tweak a single parameter** - change one value without replacing the whole pattern:

```python
>>> composition.tweak("bass", pitches=[48, 52, 55, 60])
OK
>>> composition.get_tweaks("bass")
{'pitches': [48, 52, 55, 60]}
>>> composition.clear_tweak("bass", "pitches")
OK
```

The pattern builder reads tweakable values via `p.param()`, which returns the tweaked value if set or a default otherwise:

```python
@composition.pattern(channel=0, length=4)
def bass (p):
    pitches = p.param("pitches", [60, 64, 67, 72])
    vel = p.param("velocity", 100)
    p.sequence(steps=[0, 4, 8, 12], pitches=pitches, velocities=vel)
```

Changes take effect on the next rebuild cycle. Call `clear_tweak("bass")` with no parameter name to clear all tweaks.

### Use from any tool

The server speaks a simple text protocol (messages delimited by `\x04`). You can send code from anything that opens a TCP socket:

```bash
# From another terminal with netcat
echo -ne 'composition.set_bpm(140)\x04' | nc localhost 5555

# Or Python one-liner
python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',5555)); s.send(b'composition.live_info()\x04'); print(s.recv(4096).decode())"
```

### Input validation

All code is validated as syntactically correct Python before execution. If you send a typo or malformed code, the server returns a `SyntaxError` traceback - nothing is executed, and the running composition is never affected.

## MIDI input and external clock

Subsequence can follow an external MIDI clock instead of running its own. This lets you sync with a DAW, drum machine, or any device that sends MIDI clock. Transport messages (start, stop, continue) are respected automatically.

### Enable clock following

```python
MIDI_INPUT_DEVICE = "Your MIDI Device:Port"

composition = subsequence.Composition(bpm=120, key="E")

# Follow external clock and respect transport (start/stop/continue)
composition.midi_input(device=MIDI_INPUT_DEVICE, clock_follow=True)

composition.play()
```

When `clock_follow=True`:
- The sequencer waits for a MIDI **start** or **continue** message before playing
- Each incoming MIDI **clock** tick advances the sequencer by one pulse (24 ticks = 1 beat, matching the MIDI standard)
- A MIDI **stop** message halts the sequencer
- A MIDI **start** message resets to pulse 0 and begins counting
- A MIDI **continue** message resumes from the current position
- BPM is estimated from incoming tick intervals (for display only)
- `set_bpm()` has no effect - tempo is determined by the external clock

Without `clock_follow` (the default), `midi_input()` opens the input port but does not act on clock or transport messages. This prepares for future MIDI CC mapping.

## OSC integration

Subsequence includes Open Sound Control (OSC) support for remote control and state broadcasting. This is useful for connecting to modular synth environments, custom touch interfaces, or other creative coding tools.

### Enable OSC

Start the OSC server before calling `play()`:

```python
composition.osc(receive_port=9000, send_port=9001, send_host="127.0.0.1")
composition.play()
```

### Receiving (Control)

The server listens for incoming UDP messages (default port 9000) and maps them to composition actions:

| Address | Argument | Action |
|---------|----------|--------|
| `/bpm` | `int` | Set composition tempo |
| `/mute/<name>` | (none) | Mute a pattern by its function name |
| `/unmute/<name>` | (none) | Unmute a pattern |
| `/data/<key>` | `any` | Update a value in `composition.data` |

Custom handlers can be registered via `composition._osc_server.map(address, handler)`.

### Sending (Status)

Subsequence automatically broadcasts its state via OSC (default port 9001) at the start of every bar:

| Address | Type | Description |
|---------|------|-------------|
| `/bar` | `int` | Current global bar count |
| `/bpm` | `int` | Current tempo |
| `/chord` | `str` | Current chord name (e.g. `"Em7"`) |
| `/section` | `str` | Current section name (if form is configured) |

### Direct Pattern API

```python
osc_server = subsequence.osc.OscServer(
    composition, receive_port=9000, send_port=9001
)
await osc_server.start()
```

### MIDI input: Direct API

```python
seq = subsequence.sequencer.Sequencer(
    initial_bpm=120,
    input_device_name="Your MIDI Device:Port",
    clock_follow=True
)
```

## Examples

The `examples/` directory contains self-documenting compositions demonstrating different techniques and musical styles. Each file includes detailed comments explaining its structure, harmony, form, and pattern design. To run an example:

1. Run: `python examples/filename.py`
2. Press Ctrl+C to stop

## Extra utilities
- `subsequence.pattern_builder` provides the `PatternBuilder` with high-level musical methods.
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.swing` applies swing timing to a pattern.
- `subsequence.intervals` contains interval and scale definitions for harmonic work.
- `subsequence.markov_chain` provides a generic weighted Markov chain utility.
- `subsequence.event_emitter` supports sync/async events used by the sequencer.
- `subsequence.voicings` provides chord inversions and voice leading. `invert_chord()` rotates intervals; `VoiceLeadingState` picks the closest inversion to the previous chord automatically.
- `subsequence.chord_graphs` contains chord transition graphs. Each is a `ChordGraph` subclass with `build()` and `gravity_sets()` methods. Built-in styles: `"diatonic_major"`, `"turnaround"`, `"aeolian_minor"`, `"phrygian_minor"`, `"lydian_major"`, `"dorian_minor"`, `"suspended"`, `"chromatic_mediant"`, `"mixolydian"`, `"whole_tone"`, `"diminished"`.
- `subsequence.weighted_graph` provides a generic weighted graph used for transitions.
- `subsequence.harmonic_state` holds the shared chord/key state for multiple patterns.
- `subsequence.constants.durations` provides beat-based duration constants. Import as `import subsequence.constants.durations as dur` and write `length = 9 * dur.SIXTEENTH` or `step = dur.DOTTED_EIGHTH` instead of raw floats. Constants: `THIRTYSECOND`, `SIXTEENTH`, `DOTTED_SIXTEENTH`, `TRIPLET_EIGHTH`, `EIGHTH`, `DOTTED_EIGHTH`, `TRIPLET_QUARTER`, `QUARTER`, `DOTTED_QUARTER`, `HALF`, `DOTTED_HALF`, `WHOLE`.
- `subsequence.constants.velocity` provides MIDI velocity constants. `DEFAULT_VELOCITY = 100` (most notes), `DEFAULT_CHORD_VELOCITY = 90` (harmonic content), `VELOCITY_SHAPE_LOW = 64` and `VELOCITY_SHAPE_HIGH = 127` (velocity shaping boundaries), `MIN_VELOCITY = 0`, `MAX_VELOCITY = 127`.
- `subsequence.constants.gm_drums` provides the General MIDI Level 1 drum note map. `GM_DRUM_MAP` can be passed as `drum_note_map`; individual constants like `KICK_1` are also available.
- `subsequence.constants.pulses` provides pulse-based MIDI timing constants used internally by the engine.
- `subsequence.osc` provides the OSC server/client for bi-directional communication.
- `subsequence.live_server` provides the TCP eval server for live coding. Started internally by `composition.live()`.
- `subsequence.live_client` provides the interactive REPL client. Run with `python -m subsequence.live_client`.
- `subsequence.composition` provides the `Composition` class and internal scheduling helpers.

## Feature Roadmap

Planned features, roughly in order of priority.

### High priority

- **Example library.** A handful of short compositions in different styles so musicians can hear what the tool can do before investing time.
- **Conductor `[]` access.** Allow `p.c["name"]` syntax which automatically infers the current time from the pattern builder state. Currently `p.c.get("name", time)` is required.
- **MIDI file export.** Capture sessions to a standard MIDI file for import into a DAW.

### Medium priority

- **MIDI CC mapping.** Map hardware knobs and controllers to `composition.data` via event handlers (e.g., "map CC 1 to probability") so Subsequence feels like a hybrid hardware/software instrument for live performance. This enables full **MIDI CC automation** of any Python variable. MIDI input port and clock following are already supported via `composition.midi_input()`.
- **Network Sync.** Peer-to-peer network sync with DAWs and other Link-enabled devices.

### Future ideas

- **Performance profiling.** Optional debug mode to log timing for each `on_reschedule()` call, helping identify custom pattern logic that may cause timing jitter or performance issues.
- **Embeddable engine mode.** Run Subsequence as a library inside games or live installations.

## Tests
This project uses `pytest`.

```
pytest
```

Async tests use `pytest-asyncio`. Install test dependencies with:

```
pip install -e .[test]
```

### Type Checking

This project uses mypy for static type checking. Run locally with:

```bash
pip install -e .[dev]
mypy subsequence/
```

Type checking runs automatically in CI on all pull requests.

## About the Author

Subsequence was created by me, Simon Holliday ([https://simonholliday.com/](https://simonholliday.com/)), a senior technologist and a junior (but trying) musician. From running an electronic music label in the 2000s to prototyping new passive SONAR techniques for defence research, my work has often explored the intersection of code and sound.

Subsequence was iterated over a series of separate proof-of-concept projects during 2025, and pulled together into this new codebase in Spring 2026.

## License

Subsequence is released under the [GNU Affero General Public License v3.0](LICENSE) (AGPLv3).

You are free to use, modify, and distribute this software under the terms of the AGPL. If you run a modified version of Subsequence as part of a network service, you must make the source code available to its users.

### Commercial licensing

If you wish to use Subsequence in a proprietary or closed-source product without the obligations of the AGPL, please contact [simon.holliday@protonmail.com] to discuss a commercial license.

[^markov]: A [Markov chain](https://en.wikipedia.org/wiki/Markov_chain) is a system where each state (here, a chord) transitions to the next based on weighted probabilities. Subsequence adds "gravity" - a configurable pull that draws progressions back toward the home key, so harmony drifts but never gets lost.
[^vdc]: Velocity values are spread using a [van der Corput sequence](https://en.wikipedia.org/wiki/Van_der_Corput_sequence) - a low-discrepancy series that distributes values more evenly than pure randomness, producing a more natural, musical feel.
[^stochastic]: "Stochastic" means governed by probability. These tools give you controlled randomness - results that sound intentional rather than arbitrary.
