# Subsequence

**A Stateful Algorithmic MIDI Sequencer for Python.** Subsequence combines pattern-based sequencing with the full depth of Python code. It is designed for **the musician who wants compositions that evolve** - where patterns respond to what came before, know where they are in the song, and make musical decisions based on context.

Unlike stateless libraries that loop forever, Subsequence rebuilds patterns each time they play (before they're due). This stateful architecture allows for context-aware harmony, long-form structure, and determinism. You can create complex, evolving compositions where patterns know what happened in the previous bar, as well as traditional linear pieces with fixed notes and sections.

It is a **compositional engine** for your studio - generating pure MIDI to control hardware instruments, modular synthesizers, or VSTs, with no fixed limits on complexity or length.

> **What you need:** Basic Python knowledge and any MIDI-controllable instrument - hardware synths, drum machines, modular gear, or software VSTs/DAWs. Subsequence generates MIDI data; it does not produce sound itself.

### Why Subsequence?

- **Plain Python, no custom language.** Write patterns in a standard, popular language - no domain-specific syntax to learn. Your music is versionable, shareable, and lives in standard `.py` files.
- **Infinite, evolving compositions.** Patterns rebuild each cycle with full context - chord, section, history, external data - so music can grow and develop indefinitely, or run to a fixed structure. Or both.
- **Multiple APIs and notation styles.** Start with a one-line mini-notation drum pattern. Graduate to per-step control, harmonic injection, or the full Direct Pattern API - without changing tools.
- **Built-in harmonic intelligence.** Optional chord graphs with weighted transitions, gravity, voice leading, and Narmour-based melodic cognition. The cognitive engine writes melodies that sound *human* because it models deep listener expectations.
- **Turn data into music.** Schedule any Python function on a beat cycle. Feed in APIs, sensors, files, weather, ISS telemetry - anything Python can reach becomes a musical parameter.
- **Pure MIDI, zero sound engine.** No audio synthesis, no heavyweight dependencies. Route MIDI to your existing hardware or software instruments.
- **Controlled randomness, not chaos.** Every generative decision can be bounded by musical theory and constraints. Set a seed and every "random" decision - chords, form, note choices - becomes repeatable, intentional, and tweakable.

**[Full API documentation →](https://simonholliday.github.io/subsequence)**

## Minimal Example

In this simplest example, using [mini-notation](#mini-notation), we create and play a drum pattern. More detail on the [Composition API](#composition-api) and [Direct Pattern API](#direct-pattern-api) further down.

```
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums

composition = subsequence.Composition(bpm=120)

@composition.pattern(channel=9, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

    p.seq("x ~ x ~", pitch="kick_1", velocity=100)
    p.seq("~ x ~ x", pitch="snare_1", velocity=90)
    p.seq("[x x] [x x] [x x] [x x]", pitch="hi_hat_closed", velocity=70)

composition.play()
```

## Introduction

### The "Stateful" Advantage
Most live-coding environments are **stateless**: passing time determines the event. This excels at cyclic, rhythmic music (techno, polyrhythms) but struggles with narrative. Subsequence is **stateful**: it remembers history.

This means a pattern can look back at the previous cycle to decide its next move ("if I played a C last bar, play an E this bar"). It allows for **motivic development** - ideas that evolve over time rather than just repeating. It also supports traditional linear composition: because the system tracks "Song Position" and "Section", you can write a piece with a distinct Intro, Verse, and Chorus, where specific notes play at specific times, just like in a DAW.

### Cognitive Melody Generation
We believe algorithms should sound like musicians, not random number generators. Standard generative tools often rely on "scale masking" (picking random notes from a scale), which ensures no "wrong" notes but often results in aimless melodies.

Subsequence integrates the **Narmour Implication-Realization model**, a theory of music cognition that predicts what listeners *expect* to hear. It models **melodic inertia**:
*   **Implication:** A series of small steps in one direction implies continuation.
*   **Gap-Fill:** A large leap implies a reversal to fill the gap.

By encoding these principles, Subsequence generates melodies that feel structured and intentional, satisfying the listener's innate expectations of musical grammar.

### The Algorithmic Composer
Subsequence is a workbench for **Algorithmic Composition**. It uses logic, geometry, music theory, randomness, and any external data you want to pull in, to influence the composition. It is a set of tools for creating an evolving music process.

*   **Design the Process.** You define the rules of the composition, the computer follows them. You are the composer, not a spectator.
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
- [Chord inversions and voice leading](#chord-inversions-and-voice-leading)
- [Harmony and chord graphs](#harmony-and-chord-graphs)
- [Frozen progressions](#frozen-progressions)
- [Seed and deterministic randomness](#seed-and-deterministic-randomness)
- [Terminal display](#terminal-display)
- [Web UI Dashboard (Beta)](#web-ui-dashboard-beta)
- [MIDI recording and rendering](#midi-recording-and-rendering)
- [Live coding](#live-coding)
- [Clock accuracy](#clock-accuracy)
- [MIDI input and external clock](#midi-input-and-external-clock)
- [Hotkeys](#hotkeys)
- [Pattern tools and hardware control](#pattern-tools-and-hardware-control)
- [OSC integration](#osc-integration)
- [Examples](#examples)
- [Extra utilities](#extra-utilities)
- [Feature Roadmap](#feature-roadmap)
- [Tests](#tests)
- [About the Author](#about-the-author)
- [License](#license)

## What it does

### What makes it different

- **Stateful patterns that evolve.** Each pattern is a Python function rebuilt fresh every cycle with full context - current chord, section, cycle count, external data. Patterns can remember what happened last bar and decide what to do next. This is not a loop; it's a composition that develops.[^markov]
- **Cognitive harmony engine.** Chord progressions evolve via [weighted transition graphs](#harmony-and-chord-graphs) with adjustable gravity and [Narmour-based melodic inertia](#harmonic-gravity-and-melodic-inertia) - a model of how listeners *expect* music to move. [Eleven built-in palettes](#built-in-chord-graphs). Automatic [voice leading](#automatic-voice-leading). [Freeze progressions](#frozen-progressions) to lock some sections while others evolve freely.
- **Sub-microsecond clock.** A hybrid sleep+spin timing strategy achieves typical pulse jitter of **< 5 μs** on Linux ([measured](#clock-accuracy)), with zero long-term drift. Pattern logic runs ahead of time and never blocks MIDI output.
- **Turn anything into music.** `composition.schedule()` runs any Python function on a beat cycle - APIs, sensors, files, [ISS telemetry](#iss-telemetry-examplesisspy). Anything Python can reach becomes a musical parameter, smoothed over time with built-in `EasedValue` interpolation.
- **Pure MIDI, zero sound engine.** No audio synthesis, no heavyweight dependencies. Route to your existing hardware synths, drum machines, Eurorack, or software instruments. You provide the sound; Subsequence provides the logic.

### Composition tools

- **Rhythm and feel.** [Euclidean and Bresenham generators](#rhythm--pattern), [groove templates](#groove) (including [Ableton .agr import](#groove)), swing, humanize, velocity shaping[^vdc], dropout, per-step probability, polyrhythms via independent pattern lengths, multi-voice weighted Bresenham distribution (`bresenham_poly()`) with `no_overlap` collision avoidance, `ghost_fill()` for probability-biased ghost note layers, `cellular()` for evolving cellular-automaton rhythms, `logistic_map()` for a deterministic chaos modulation source (dial from stable → periodic → chaos with one `r` parameter), and `p.markov()` for Markov-chain melody and bassline generation.
- **Melody generation.** `p.melody()` with `MelodicState` applies the [Narmour Implication-Realization model](#melody-generation) to single-note melodic lines: continuation after small steps, direction reversal after large leaps, chord-tone weighting, range gravity, and pitch-diversity penalty. History persists across bar rebuilds for natural phrase continuity.
- **Expression.** CC messages and ramps, pitch bend, note-correlated [bend/portamento/slide](#pitch-bend-automation), program changes, SysEx, and [OSC output](#osc-integration) - all from within patterns.
- **Form and structure.** Define [song form](#form-and-sections) as a weighted graph, ordered list, or generator. Patterns read `p.section` to adapt. [Conductor signals](#the-conductor) (LFOs, ramps) shape intensity over time.
- **[Mini-notation.](#mini-notation)** Write `p.seq("x x [x x] x", pitch="kick")` - subdivisions, rests, sustains, per-step probability suffixes. Quick ideas in one line.
- **Scales and quantization.** `p.quantize("G", "dorian")` snaps notes to any named scale. Built-in western and [non-western scales](#scale-quantization) (Hirajōshi, In-Sen, Iwato, Yo, Egyptian, pentatonics), plus `register_scale()` for your own.
- **Randomness tools.**[^stochastic] Weighted choice, no-repeat shuffle, random walk, probability gates - controlled randomness via `subsequence.sequence_utils`. Deterministic seeding (`seed=42`) makes every decision repeatable.
- **Pattern transforms.** Legato, staccato, reverse, double/half-time, shift, transpose, invert, humanize, `p.every()`, and `composition.layer()`.
- **Two API levels.** [Composition API](#composition-api) for most musicians; [Direct Pattern API](#direct-pattern-api) for power users who need persistent state or custom scheduling.

### Integration

- **MIDI clock.** [Master](#clock-accuracy) (`clock_output()`) or [follower](#midi-input-and-external-clock) (`clock_follow=True`). Sync to a DAW, drive a Eurorack system, or both.
- **Hardware control.** [CC input mapping](#midi-cc-input-mapping) from knobs and faders to `composition.data`. [OSC](#osc-integration) for bidirectional communication with mixers, lighting, visuals.
- **[Live coding.](#live-coding)** Hot-swap patterns, change tempo, mute/unmute, tweak parameters - all during playback.
- [Hotkeys.](#hotkeys) Single keystrokes to jump sections, tweak patterns, or trigger actions - with optional bar-boundary quantization.
- **Web UI Dashboard (Beta).** Broadcast live composition state and pattern grids to your browser via standard WebSockets.
- **Recording and rendering.** [Record](#midi-recording-and-rendering) to standard MIDI file. [Render to file](#rendering-to-file-no-real-time-wait) without waiting for real-time playback.

## Quick start
1. Install dependencies:
```
pip install -e .
```
2. Run the demo (drums, bass, and arp over evolving aeolian minor harmony in E):
```
python examples/demo.py
```

For the complete API reference, see the **[documentation](https://simonholliday.github.io/subsequence)**. The sections below are a quick overview.

## Composition API

The `Composition` class is the main entry point. Define your MIDI setup, create a composition, add patterns, and play:

```python
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums

DRUMS_CHANNEL = 9
BASS_CHANNEL  = 5
SYNTH_CHANNEL = 0

composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
    p.hit_steps("snare_1", [4, 12], velocity=100)
    p.hit_steps("hi_hat_closed", range(16), velocity=80)
    p.velocity_shape(low=60, high=100)

@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):
    root = chord.root_note(40)
    p.sequence(steps=[0, 4, 8, 12], pitches=root)
    p.legato(0.9)

@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def arp (p, chord):
    pitches = chord.tones(root=60, count=4)
    p.arpeggio(pitches, step=0.25, velocity=90, direction="up")

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

# Non-quarter-note grid: 6 sixteenth notes (reads like "6/16" in a score).
# hit_steps() and sequence() automatically use 6 grid slots.
import subsequence.constants.durations as dur

@composition.pattern(channel=0, length=6, unit=dur.SIXTEENTH)
def riff (p, chord):
    root = chord.root_note(64)
    p.sequence(steps=[0, 1, 3, 5], pitches=[root+12, root, root, root])

# Per-step probability - each hi-hat has a 70% chance of playing.
@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def hats (p):
    p.hit_steps("hh", list(range(16)), velocity=80, probability=0.7)

# Schedule a repeating background task (runs in a thread pool).
# wait_for_initial=True blocks until the first run completes before playback starts.
# Optionally declare a `p` parameter to receive a ScheduleContext with p.cycle (0-indexed).
def fetch_data (p):
    if p.cycle == 0:
        composition.data["value"] = initial_api_call()
    else:
        composition.data["value"] = some_external_api()

composition.schedule(fetch_data, cycle_beats=32, wait_for_initial=True)
```

## Direct Pattern API

The Direct Pattern API gives you full control over the sequencer, harmony, and scheduling. Patterns are classes instead of decorated functions - you manage the event loop yourself.

<details>
<summary>Full example - same music as the Composition API demo above (click to expand)</summary>

```python
import asyncio

import subsequence.composition
import subsequence.constants
import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer

DRUMS_CHANNEL = 9
BASS_CHANNEL  = 5
SYNTH_CHANNEL = 0


class DrumPattern (subsequence.pattern.Pattern):
    """Kick, snare, and hi-hats - built using the PatternBuilder bridge."""

    def __init__ (self) -> None:
        super().__init__(channel=DRUMS_CHANNEL, length=4)
        self._build()

    def _build (self) -> None:
        self.steps = {}
        p = subsequence.pattern_builder.PatternBuilder(
            self, cycle=0, drum_note_map=gm_drums.GM_DRUM_MAP
        )
        p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
        p.hit_steps("snare_1", [4, 12], velocity=100)
        p.hit_steps("hi_hat_closed", range(16), velocity=80)
        p.velocity_shape(low=60, high=100)

    def on_reschedule (self) -> None:
        self._build()


class BassPattern (subsequence.pattern.Pattern):
    """Quarter-note bass following the harmony engine's current chord."""

    def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState) -> None:
        super().__init__(channel=BASS_CHANNEL, length=4)
        self.harmonic_state = harmonic_state
        self._build()

    def _build (self) -> None:
        self.steps = {}
        chord = self.harmonic_state.get_current_chord()
        root  = chord.root_note(40)
        for beat in range(4):
            self.add_note_beats(beat, pitch=root, velocity=100, duration_beats=0.9)

    def on_reschedule (self) -> None:
        self._build()


class ArpPattern (subsequence.pattern.Pattern):
    """Ascending arpeggio cycling through the current chord's tones."""

    def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState) -> None:
        super().__init__(channel=SYNTH_CHANNEL, length=4)
        self.harmonic_state = harmonic_state
        self._build()

    def _build (self) -> None:
        self.steps = {}
        chord   = self.harmonic_state.get_current_chord()
        pitches = chord.tones(root=60, count=4)
        self.add_arpeggio_beats(pitches, step_beats=0.25, velocity=90)

    def on_reschedule (self) -> None:
        self._build()


async def main () -> None:
    seq = subsequence.sequencer.Sequencer(initial_bpm=120)
    harmonic_state = subsequence.harmonic_state.HarmonicState(
        key_name="E", graph_style="aeolian_minor", key_gravity_blend=0.8
    )
    await subsequence.composition.schedule_harmonic_clock(
        seq, lambda: harmonic_state, cycle_beats=4
    )

    drums = DrumPattern()
    bass  = BassPattern(harmonic_state)
    arp   = ArpPattern(harmonic_state)

    await subsequence.composition.schedule_patterns(seq, [drums, bass, arp])
    await subsequence.composition.run_until_stopped(seq)


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

For a larger example with form sections and five patterns, see `examples/arpeggiator.py`.

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

The `Composition` object stores its harmonic and form state internally. After calling `harmony()` and `form()`, three read-only properties expose them:

- `composition.harmonic_state` - the `HarmonicState` object (same one patterns read from)
- `composition.form_state` - the `FormState` object (same one `p.section` reads from)
- `composition.sequencer` - the underlying `Sequencer` instance

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
| `x?0.6` | Probability suffix - fires with the given probability (0.0–1.0) |

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
| `next_section` | `str?` | Name of the upcoming section, or `None` at the end |

`next_section` is pre-decided when the current section begins (graph mode picks probabilistically; list mode peeks the iterator). Use it for lead-ins:

```python
if p.section and p.section.last_bar and p.section.next_section == "chorus":
    p.hit_steps("snare", range(0, 16, 2), velocity=100)  # Snare roll into chorus
```

A performer or code can override the pre-decided next section with `composition.form_next("chorus")` - see [Hotkeys](#hotkeys).

`p.bar` is always available (regardless of form) and tracks the global bar count since playback started.

To replay the same chords every time a section recurs, see [Frozen progressions](#frozen-progressions).

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

### Shaping transitions

By default, all ramps are linear. Pass `shape=` to any ramp to change how the value moves:

```python
# Slow build that accelerates - good for intensity lines
composition.conductor.line("build", start_val=0.0, end_val=1.0, duration_beats=64, shape="ease_in")

# S-curve BPM shift - the tempo barely moves at first, rushes through the middle, then settles gently
composition.target_bpm(140, bars=16, shape="ease_in_out")

# Filter sweep - cubic response approximates how we hear filter changes
@composition.pattern(channel=0, length=4)
def sweep (p):
    p.cc_ramp(74, 0, 127, shape="exponential")
```

Available shapes: `"linear"` (default), `"ease_in"`, `"ease_out"`, `"ease_in_out"`, `"exponential"`, `"logarithmic"`, `"s_curve"`. You can also pass any callable that maps a float in [0, 1] to a float in [0, 1] for a custom curve. See `subsequence.easing` for details.

### State vs Signals

Subsequence offers two complementary ways to store values: **Data** (state) and **Conductor** (signals). Use whichever fits:

| | `composition.data` | `composition.conductor` |
|---|---|---|
| **Question it answers** | "What is the value RIGHT NOW?" | "What was the value at beat 40?" |
| **Nature** | Static snapshots - no concept of time | Time-variant signals (LFOs, ramps) |
| **Best for** | External inputs (sensors, API data), mode switches, irregular updates | Musical evolution (fades, swells, modulation) that must be smooth and continuous |

If you use `composition.schedule()` to poll external data and want to ease between each new reading, use **`subsequence.easing.EasedValue`**. Create one instance per field at module level, call `.update(value)` in your scheduled task, and `.get(progress)` in your pattern - no manual `prev`/`current` bookkeeping required. See [`subsequence.easing`](#extra-utilities) for details.

## Chord inversions and voice leading

Most generative tools leave voicing to the user. Subsequence provides automatic voice leading - each chord picks the inversion with the smallest total pitch movement from the previous one, keeping parts smooth without manual effort.

By default, chords are played in root position. You can request a specific inversion, or enable voice leading per pattern.

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

### Legato chords

Pass `legato=` directly to `chord()` or `strum()` to collapse the two-step pattern into one call. The value is passed straight to `p.legato()`, stretching each note to fill the given fraction of the gap to the next note:

```python
@composition.pattern(channel=0, length=4)
def pad (p, chord):
    # Equivalent to: p.chord(...) then p.legato(0.9)
    p.chord(chord, root=52, velocity=90, legato=0.9)

@composition.pattern(channel=0, length=4)
def guitar (p, chord):
    p.strum(chord, root=52, velocity=85, offset=0.06, legato=0.95)
```

`sustain=True` and `legato=` are mutually exclusive - passing both raises a `ValueError`.

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
| `minor_turnaround_weight` | float | `0.0` | Minor turnaround weight (turnaround graph only) |
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

### Generating a chord list without the graph engine

Use `diatonic_chords()` to get the 7 diatonic triads for any key and mode - plain `Chord` objects with no probabilistic machinery:

```python
from subsequence.harmony import diatonic_chords

# Seven triads of Eb Major: Eb, Fm, Gm, Ab, Bb, Cm, Ddim
chords = diatonic_chords("Eb")

# Natural minor
chords = diatonic_chords("A", mode="minor")

# Supported modes: "ionian" ("major"), "dorian", "phrygian", "lydian",
#   "mixolydian", "aeolian" ("minor"), "locrian",
#   "harmonic_minor", "melodic_minor"
```

Each entry is a `Chord` object - pass it directly to `p.chord()`, `p.strum()`, or `chord.tones()`:

```python
@composition.pattern(channel=0, length=4)
def rising (p):
    current = diatonic_chords("D", mode="dorian")[p.cycle % 7]
    p.chord(current, root=50, sustain=True)
```

For a **stepped sequence with explicit MIDI roots** - for example, mapping a sensor value to a chord - use `diatonic_chord_sequence()`. It returns `(Chord, midi_root)` tuples stepping diatonically upward from a starting note, wrapping into higher octaves automatically:

```python
from subsequence.harmony import diatonic_chord_sequence

# 12-step D Major ladder from D3 (MIDI 50) up through D4 and beyond
sequence = diatonic_chord_sequence("D", root_midi=50, count=12)

# Map a 0-1 value directly to a chord
altitude_ratio = 0.7   # e.g. from ISS data
chord, root = sequence[int(altitude_ratio * (len(sequence) - 1))]
p.chord(chord, root=root, sustain=True)

# Falling sequence
sequence = list(reversed(diatonic_chord_sequence("A", root_midi=45, count=7, mode="minor")))
```

The `root_midi` must be a note that falls on a scale degree of the chosen key and mode. A `ValueError` is raised otherwise.

## Frozen progressions

The harmony engine generates chords live via the weighted graph - great for evolving, exploratory compositions. But sometimes you want **structural repetition**: the verse should always feel like the verse, with the same harmonic journey each time it plays.

`composition.freeze(bars)` captures the current engine output into a `Progression` object. `composition.section_chords(section_name, progression)` then binds it to a form section. Every time that section plays, the harmonic clock replays the frozen chords instead of calling the live engine. Sections without a binding keep generating freely.

Successive `freeze()` calls continue the engine's journey - so verse, chorus, and bridge progressions feel like parts of a whole rather than isolated islands.

```python
composition = subsequence.Composition(bpm=120, key="C")
composition.harmony(style="functional_major", cycle_beats=4)

# Generate progressions before playback. Each call advances the engine,
# so the sections feel harmonically connected.
verse  = composition.freeze(8)   # 8 chords for the verse
chorus = composition.freeze(4)   # next 4 chords for the chorus

composition.form({
    "verse":  (8, [("chorus", 1)]),
    "chorus": (4, [("verse", 2), ("bridge", 1)]),
    "bridge": (8, [("verse", 1)]),
}, start="verse")

composition.section_chords("verse",  verse)
composition.section_chords("chorus", chorus)
# "bridge" is not bound - it generates live chords each time

composition.play()
```

Patterns receive the current chord via the normal `chord` parameter - no changes needed in pattern code:

```python
@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):
    root = chord.root_note(40)
    p.sequence(steps=[0, 4, 8, 12], pitches=root)
    p.legato(0.9)
```

**Key behaviours:**

- Each time a frozen section is re-entered, playback restarts from chord 0.
- If a section is longer than its progression (more bars than chords), the extra bars fall through to live generation.
- NIR history is restored at the start of each frozen replay so every re-entry begins with the same harmonic context as when the progression was originally generated.
- `freeze()` can be called before or after `form()`.

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

## Melody generation

`p.melody()` generates a single-note melodic line guided by the Narmour Implication-Realization (NIR) model - the same cognitive framework used by the chord engine, now adapted for absolute pitch. It expects a `MelodicState` instance created once at module level, which persists history across bar rebuilds so melodic continuity is maintained automatically.

```python
# Create once at module level - history persists across bars.
melody_state = subsequence.MelodicState(
    key="A",
    mode="aeolian",
    low=57,     # A3
    high=84,    # C6
    nir_strength=0.6,    # How strongly NIR rules shape pitch choice (0–1)
    chord_weight=0.4,    # Bonus for chord tones
    rest_probability=0.1,  # 10% chance of silence per step
    pitch_diversity=0.6,   # Penalise recently-repeated pitches
)

@composition.pattern(channel=3, length=4, chord=True)
def lead (p, chord):
    tones = chord.tones(72) if chord else None
    p.melody(melody_state, step=0.5, velocity=(70, 100), chord_tones=tones)
```

**NIR rules in melody:**

| Rule | Trigger | Effect |
|------|---------|--------|
| **Reversal** | Previous interval > 4 semitones (large leap) | Favours direction change (+0.5) and a smaller gap-fill interval (+0.3) |
| **Process** | Previous interval 1–2 semitones (small step) | Favours same direction (+0.4) and similar interval size (+0.2) |
| **Closure** | Candidate is the tonic | +0.2 boost - the tonic feels like a natural landing |
| **Proximity** | Candidate is ≤ 3 semitones from last note | +0.3 boost - small intervals are generally preferred |

Unlike chord NIR, melody NIR operates on **absolute MIDI pitch differences** (not pitch-class modular arithmetic), so it correctly distinguishes an upward leap from a downward one even across octaves.

**Additional factors:**

- **Chord tone boost.** If `chord_tones` is provided, pitch classes that match receive a multiplicative bonus of `1 + chord_weight`. This keeps melodies harmonically grounded without locking them to arpeggios.
- **Range gravity.** A soft quadratic penalty pulls notes toward the centre of `[low, high]`, preventing the melody from drifting to register extremes.
- **Pitch diversity.** Each time a pitch appears in the recent history, its score is multiplied by `pitch_diversity`. Low values (e.g. `0.3`) strongly suppress repetition; `1.0` disables the penalty entirely.

`p.melody()` parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `state` | - | A `MelodicState` instance (required) |
| `step` | `0.25` | Time between note onsets in beats (0.25 = 16th note) |
| `velocity` | `90` | Fixed int or `(low, high)` tuple for random range per step |
| `duration` | `0.2` | Note duration in beats |
| `chord_tones` | `None` | MIDI notes that are chord tones this bar |

## Terminal display

Enable a live status line showing the current bar, section, chord, BPM, and key with a single call:

```python
composition.display()
composition.play()
```

The status line updates every beat and looks like:

```
125.00 BPM  Key: E  Bar: 17.1  [chorus 1/8]  Chord: Em7  Swell: 0.42  Tide: 0.78
```

Components adapt to what's configured - the section is omitted if no form is set, the chord is omitted if no harmony is configured, and conductor signals only appear when registered. Log messages scroll cleanly above the status line without disruption.

### Pattern grid

Add `grid=True` to also render an ASCII grid above the status line showing what each pattern is doing - which steps have notes, at what velocity, and for how long:

```python
composition.display(grid=True)
composition.play()
```

The grid updates once per bar and looks like:

```
  drums
  kick        |O o . . O . . . O . . . O . . o|
  snare       |. . . . O . . . . . . . O . . .|
  bass        |O - - O - - - - O - - - O - - .|
125.00 BPM  Key: E  Bar: 3.1  [intro 3/8 → section_1]
```

Each column is one grid step (16th notes by default). Velocity and duration are encoded in the character at each position:

| Glyph | Meaning |
|-------|---------|
| `.` | Empty step (no note) |
| `o` | Soft attack (velocity 41–80) |
| `O` | Medium attack (velocity 81–110) |
| `X` | Loud attack (velocity 111–127) |
| `-` | Sustain (note still sounding from a previous step) |

The sustain marker makes legato and staccato patterns visually distinct - a legato bass line fills its steps with `-` between attacks; drum hits are short and show no sustain. Drum patterns show one row per distinct drum sound, labelled from the drum note map. Pitched patterns show a single summary row.

### Grid scale

Add `grid_scale` to zoom in horizontally and reveal micro-timing from swing and groove:

```python
composition.display(grid=True, grid_scale=2)
composition.play()
```

At `grid_scale=2` each base grid step expands to 2 visual columns. Empty columns *between* the original grid steps show as spaces; notes shifted by swing or groove appear at those in-between positions. Sustain markers fill all occupied columns:

```
grid_scale=1 (default):
  bass        |O - - O - - - - O - - - O - - .|

grid_scale=2:
  bass        |O -   - O -   -   -   - O -   -   - O -   - .  |
```

`grid_scale` accepts any float and snaps to the nearest integer columns-per-step, guaranteeing all on-grid markers are exactly the same distance apart. Values below 1.5 are equivalent to the default.

To disable:

```python
composition.display(enabled=False)
```

## Web UI Dashboard (Beta)

For an improved visual experience without relying on the terminal, you can enable the experimental Web UI Dashboard. This spins up an HTTP server and a WebSocket connection in the background to serve a reactive web interface that mirrors your composition state:

```python
composition.web_ui()
composition.play()
```

Opening `http://localhost:8080/` in your browser will display:
* A live transport bar showing the current BPM, Key, Bar, and Form Section.
* Gauge bars representing all active Conductor signals (e.g., LFOs and automation lines).
* High-precision visual playheads and piano-roll style Pattern Grids for every pattern currently rendering. 

*Note: The Web UI is an optional beta feature. When you don't call `web_ui()`, it consumes zero threads and zero CPU overhead. It currently relies on an active internet connection to load the Preact frontend dependencies from a CDN.*

## MIDI recording and rendering

Capture a session to a standard MIDI file. Pass `record=True` to `Composition` and Subsequence saves everything it plays to disk when you stop:

```python
composition = subsequence.Composition(bpm=120, key="E", record=True)
composition.play()
# Press Ctrl+C - the recording is saved automatically
```

By default the filename is generated from the timestamp (`session_YYYYMMDD_HHMMSS.mid`). Pass `record_filename` to choose your own:

```python
composition = subsequence.Composition(
    bpm=120, key="E",
    record=True,
    record_filename="my_session.mid"
)
```

The output is a standard Type 1 MIDI file at 480 PPQN - import it directly into any DAW. All note events are recorded on their original MIDI channels. Tempo is embedded as a `set_tempo` meta event, including any mid-session `set_bpm()` calls.

### Rendering to file (no real-time wait)

`composition.render()` runs the sequencer as fast as possible - no waiting for wall-clock time - and saves the result immediately. A default **60-minute safety cap** (`max_minutes=60.0`) stops infinite compositions from filling your disk:

```python
composition = subsequence.Composition(bpm=120, key="C")

@composition.pattern(channel=0, length=4)
def melody (p):
    p.seq("60 [62 64] 67 60")

# Render exactly 8 bars (default 60-min cap still active as a backstop)
composition.render(bars=8, filename="melody.mid")

# Render an infinite composition - stops automatically at 5 minutes of MIDI
composition.render(max_minutes=5, filename="generative.mid")

# Remove the time cap - must supply an explicit bars= count instead
composition.render(bars=128, max_minutes=None, filename="long.mid")
```

If the time cap fires, a warning is logged explaining how to remove it. All patterns, scheduled callbacks, probabilistic gates, and BPM transitions work identically in render mode. The only difference is that simulated time replaces wall-clock time.

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
>>> composition.target_bpm(140, bars=8)                    # smooth ramp over 8 bars
OK
>>> composition.target_bpm(140, bars=8, shape="ease_in_out") # S-curve for a more natural feel
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

## Clock accuracy

Subsequence uses a hybrid sleep+spin timing strategy for its internal master clock. Rather than relying on `asyncio.sleep()` alone (which is subject to OS scheduler granularity), the loop sleeps to within ~1 ms of the target pulse time, then busy-waits on `time.perf_counter()` for the remaining sub-millisecond interval. Pulse times are calculated as absolute offsets from the session start time, so timing errors never accumulate.

**Measured jitter on Linux at 120 BPM (64 bars, 6144 pulses):**

| Mode | Mean | P99 | Max | Long-term drift |
|------|------|-----|-----|-----------------|
| Spin-wait ON (default) | **3 μs** | 4 μs | ~150 μs* | 0 |
| `asyncio.sleep` only | 853 μs | 1.37 ms | 1.72 ms | negligible |

\* Occasional spikes are GC pauses in the Python runtime, not clock instability.

To measure jitter on your own system:

```bash
python benchmarks/clock_jitter.py             # default (spin-wait on, 32 bars)
python benchmarks/clock_jitter.py --compare   # side-by-side with spin-wait off
python benchmarks/clock_jitter.py --bpm 140 --bars 128
```

To disable spin-wait (lower CPU use, ~1 ms jitter):

```python
composition = subsequence.Composition(bpm=120, key="C")
composition.sequencer.disable_spin_wait()
```

Or at construction time: `Sequencer(spin_wait=False)`.

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

Without `clock_follow` (the default), `midi_input()` opens the input port but does not act on clock or transport messages - it can still receive CC input for mapping (see below).

### MIDI CC input mapping

Map hardware knobs, faders, and expression pedals directly to `composition.data` - no callback code required:

```python
composition.midi_input("Arturia KeyStep")   # open the input port

composition.cc_map(74, "filter_cutoff")          # CC 74 → 0.0–1.0 in composition.data
composition.cc_map(7,  "volume", min_val=0, max_val=127)   # custom range
composition.cc_map(1,  "density", channel=0)     # channel-filtered

@composition.pattern(channel=0, length=4)
def arps (p):
    cutoff = composition.data.get("filter_cutoff", 0.5)
    velocity = int(60 + 67 * cutoff)
    p.arpeggio([60, 64, 67], step=0.25, velocity=velocity)
```

CC values are scaled from 0–127 to the `min_val`/`max_val` range and written to `composition.data[key]` on every incoming message. Thread safety is provided by Python's GIL for single dict writes.

### MIDI clock output

Make Subsequence the MIDI clock master so hardware can lock to its tempo:

```python
composition = subsequence.Composition(bpm=120, output_device="...")
composition.clock_output()   # send Start, Clock ticks, Stop to the output port
composition.play()
```

Subsequence sends a Start message (0xFA) at the beginning of playback, one Clock tick (0xF8) per pulse (24 PPQN, matching the MIDI standard), and a Stop message (0xFC) when playback ends. This automatically disabled when `midi_input(clock_follow=True)` is active, to prevent a feedback loop.

## Pattern tools and hardware control

### Program changes

Switch instrument patches mid-pattern with `p.program_change()`:

```python
@composition.pattern(channel=1, length=4)
def strings (p):
    p.program_change(48)          # String Ensemble 1 (GM #49)
    p.chord(chord, root=60, velocity=75, sustain=True)
```

Program numbers follow General MIDI (0–127). The message fires at the beat position given by the optional `beat` argument (default 0.0 - the start of the pattern).

### SysEx

Send System Exclusive messages for deep hardware integration - Elektron parameter locking, patch dumps, vendor-specific commands:

```python
@composition.pattern(channel=0, length=4)
def init (p):
    # GM System On - resets all GM-compatible devices to defaults
    p.sysex([0x7E, 0x7F, 0x09, 0x01])
```

Pass `data` as a `bytes` object or a list of integers (0–127). The surrounding `0xF0`/`0xF7` framing is added automatically by mido. `beat` sets the position within the pattern (default 0.0).

### Pitch bend automation

Three post-build transforms generate correctly-timed pitch bend events by reading actual note positions and durations - no manual beat arithmetic required. Call them *after* `legato()` / `staccato()` so durations are final.

**`p.bend()` - bend a specific note by index:**

```python
p.sequence(steps=[0, 4, 8, 12], pitches=midi_notes.E1)
p.legato(0.95)

# Bend the last note up 1 semitone (±2 st range), easing in over its full duration
p.bend(note=-1, amount=0.5, shape="ease_in")

# Bend the 2nd note down, starting halfway through
p.bend(note=1, amount=-0.3, start=0.5, shape="ease_out")
```

`amount` is normalised to -1.0..1.0. With a standard ±2-semitone pitch wheel range, `0.5` = 1 semitone up. `start` and `end` are fractions of the note's duration (defaults: 0.0 and 1.0). A pitch bend reset is inserted automatically at the next note's onset.

**`p.portamento()` - glide between all consecutive notes:**

```python
p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
p.legato(0.95)

# Gentle glide using the last 15% of each note
p.portamento(time=0.15, shape="ease_in_out")

# Wide bend range (synth set to ±12 semitones)
p.portamento(time=0.2, bend_range=12)

# No range limit - let the instrument decide
p.portamento(time=0.1, bend_range=None)
```

`bend_range` tells Subsequence the instrument's pitch wheel range in semitones (default `2.0`). Pairs with a larger interval are skipped. Pass `None` to disable range checking. `wrap=True` (default) also glides from the last note toward the first note of the next cycle.

**`p.slide()` - TB-303-style selective slide:**

```python
p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
p.legato(0.95)

# Slide into the 2nd and 4th notes (by note index)
p.slide(notes=[1, 3], time=0.2, shape="ease_in")

# Same thing using step grid indices
p.slide(steps=[4, 12], time=0.2, shape="ease_in")

# Without extending the preceding note
p.slide(notes=[1, 3], extend=False)
```

`slide()` is like `portamento()` but only applies to flagged destination notes. With `extend=True` (default) the preceding note is extended to reach the slide target's onset - matching the 303's behaviour where slide notes do not retrigger.

| Method | Key parameters |
|--------|---------------|
| `p.bend(note, amount, start=0.0, end=1.0, shape, resolution)` | `note`: index; `amount`: -1.0..1.0 |
| `p.portamento(time=0.15, shape, resolution, bend_range=2.0, wrap=True)` | `bend_range=None` disables range check |
| `p.slide(notes=None, steps=None, time=0.15, shape, resolution, bend_range=2.0, wrap=True, extend=True)` | `notes` or `steps` required |

### Scale quantization

Snap all notes in a pattern to a named scale - essential after generative or sensor-driven pitch work:

```python
@composition.pattern(channel=0, length=4)
def walk (p):
    for beat in range(16):
        pitch = 60 + p.rng.randint(-7, 7)     # random walk around middle C
        p.note(pitch, beat=beat * 0.25)
    p.quantize("G", "dorian")                  # snap everything to G Dorian
```

`quantize(key, mode)` accepts any key name (`"C"`, `"F#"`, `"Bb"`, etc.) and any registered scale. Equidistant notes prefer the upward direction.

Built-in modes include western diatonic (`"ionian"`, `"dorian"`, `"minor"`, `"harmonic_minor"`, etc.) and non-western scales (`"hirajoshi"`, `"in_sen"`, `"iwato"`, `"yo"`, `"egyptian"`, `"major_pentatonic"`, `"minor_pentatonic"`).

Register your own scales at any time:

```python
subsequence.register_scale("raga_bhairav", [0, 1, 4, 5, 7, 8, 11])
# then in patterns:
p.quantize("C", "raga_bhairav")
```

### Chord root and bass helpers

`chord.root_note(midi)` and `chord.bass_note(midi, octave_offset=-1)` make register-aware root extraction self-documenting:

```python
@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):
    bass_root = chord.bass_note(root, octave_offset=-1)   # one octave below chord voicing
    p.sequence(steps=range(0, 16, 2), pitches=bass_root)
    p.legato(0.9)
```

### Arpeggio directions

`p.arpeggio()` now supports four playback directions:

```python
p.arpeggio([60, 64, 67], step=0.25)                     # "up" (default)
p.arpeggio([60, 64, 67], step=0.25, direction="down")    # descend
p.arpeggio([60, 64, 67], step=0.25, direction="up_down") # ping-pong: C E G E C E ...
p.arpeggio([60, 64, 67], step=0.25, direction="random")  # shuffled once per call
```

The `"random"` direction uses `p.rng` by default (deterministic when a seed is set). Pass a custom `rng` for independent streams.

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

### Sending from patterns

Use `p.osc()` and `p.osc_ramp()` to send arbitrary OSC messages at precise beat positions - useful for automating mixer faders, toggling effects, or controlling any OSC-capable device on the network.

```python
composition.osc(send_port=9001, send_host="192.168.1.100")  # remote mixer on LAN

@composition.pattern(channel=0, length=4)
def mixer_automation(p, chord):
    # Ramp a fader from 0.0 to 1.0 over the full pattern
    p.osc_ramp("/mixer/fader/1", start=0.0, end=1.0)

    # Ease in a reverb send over the second half
    p.osc_ramp("/fx/reverb/wet", 0.0, 0.8, beat_start=2, beat_end=4, shape="ease_in")

    # Trigger an effect toggle at beat 2
    p.osc("/fx/chorus/enable", 1, beat=2.0)

    # Address-only message (no arguments) as a trigger
    p.osc("/scene/next", beat=3.0)
```

| Method | Parameters | Notes |
|--------|-----------|-------|
| `p.osc(address, *args, beat=0.0)` | address: OSC path; args: float/int/str; beat: position | Single message at a beat |
| `p.osc_ramp(address, start, end, beat_start=0, beat_end=None, resolution=4, shape="linear")` | start/end: arbitrary floats | Smooth ramp; resolution=4 ≈ 6 msgs/beat at 120 BPM |

The same easing shapes available for `cc_ramp` (e.g. `"ease_in"`, `"ease_out"`, `"exponential"`) work with `osc_ramp`.

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

## Hotkeys

Assign single keystrokes to trigger actions during live playback - section jumps, tweaks, data updates, mutes, or any zero-argument callable. Linux / macOS only (raw single-character terminal input relies on the POSIX `tty` and `termios` modules, which Windows does not provide).

```python
composition.hotkeys()  # enable before play()

# Most actions are immediate; their musical effect lands at the next
# pattern rebuild cycle, which provides natural musical quantization.
composition.hotkey("a", lambda: composition.form_next("chorus"))
composition.hotkey("A", lambda: composition.form_jump("chorus"))
composition.hotkey("1", lambda: composition.data.update({"density": 0.3}))
composition.hotkey("2", lambda: composition.data.update({"density": 0.9}))

# Use quantize=N for explicit bar-boundary control (next bar divisible by N).
composition.hotkey("s", lambda: composition.mute("drums"),   quantize=4)
composition.hotkey("d", lambda: composition.unmute("drums"), quantize=4)

# Named functions get their name as the label automatically.
def drop_to_breakdown():
    composition.form_jump("breakdown")
    composition.mute("lead")

composition.hotkey("x", drop_to_breakdown)

# Override the label explicitly.
composition.hotkey("q", my_action, label="reset mood")

composition.play()
```

`?` is always reserved - press it during playback to log all active bindings.

### `composition.hotkeys(enabled=True)`

Globally enable or disable the keystroke listener. Call before `play()`. When disabled, no keys are read and no actions fire - zero impact on playback.

### `composition.hotkey(key, action, quantize=0, label=None)`

| Parameter  | Default | Description |
|------------|---------|-------------|
| `key`      | -       | Single character trigger |
| `action`   | -       | Zero-argument callable |
| `quantize` | `0`     | `0` = immediate; `N` = next bar divisible by N |
| `label`    | `None`  | Display name for `?` listing; auto-derived if omitted |

Labels are auto-derived: named functions use `fn.__name__`; lambdas in `.py` files use the lambda body extracted from source; fallback is `<action>`.

### `composition.form_next(section_name)`

Queue a section to play after the current one finishes (graph mode only). Overrides the auto-decided next section. The transition happens at the natural section boundary, keeping the music intact. Call it again to change your mind - last call wins.

### `composition.form_jump(section_name)`

Force the form to a named section immediately (graph mode only). Resets the bar count within the section. Effect is heard at the next pattern rebuild. Use `form_next` for gentle transitions and `form_jump` for urgent ones.

## Groove

A groove is a per-step timing and velocity template that gives patterns a characteristic rhythmic feel - swing, shuffle, MPC-style pocket, or anything extracted from an Ableton `.agr` file. Unlike `p.swing()` (which only delays off-beat 8th notes by a single ratio), a groove can shift and accent every grid position independently.

```python
import subsequence

# Swing from a percentage (50 = straight, 67 ≈ triplet)
groove = subsequence.Groove.swing(percent=57)

# Import from an Ableton .agr file
groove = subsequence.Groove.from_agr("Swing 16ths 57.agr")

# Custom groove - per-beat timing and velocity accents
groove = subsequence.Groove(
    grid=0.25,                                # 16th-note grid
    offsets=[0.0, +0.02, 0.0, -0.01],         # timing shift per slot (beats)
    velocities=[1.0, 0.7, 0.9, 0.6],          # velocity scale per slot
)

@composition.pattern(channel=9, length=4)
def drums (p):
    p.hit_steps("kick", [0, 8], velocity=100)
    p.hit_steps("hi_hat", range(16), velocity=80)
    p.groove(groove)
```

`p.groove()` is a post-build transform - call it at the end of your builder function after all notes are placed. The offset list repeats cyclically, so a 2-slot swing pattern covers an entire bar.

Groove and `p.humanize()` pair well: apply the groove first for structured feel, then humanize on top for micro-variation.

## Examples

The `examples/` directory contains self-documenting compositions, each demonstrating a different style and set of features. Because Subsequence generates pure MIDI, what you hear depends on your choice of instruments - the same code can drive a hardware monosynth, a VST orchestra, or anything in between.

```
python examples/demo.py
```

### Demo (`examples/demo.py` and `examples/demo_advanced.py`)

Drums, bass, and an ascending arpeggio over evolving aeolian minor harmony in E. `demo.py` uses the Composition API (decorated functions); `demo_advanced.py` uses the Direct Pattern API (Pattern subclasses with async lifecycle). Compare them side by side to see how the two APIs relate.

### Arpeggiator (`examples/arpeggiator.py`)

A more complete composition with form sections (intro → section_1 ↔ section_2), five patterns (drums, bass, arp, lead), cycle-dependent variation, and Phrygian minor harmony. Demonstrates `velocity_shape`, `legato`, non-quarter-note grids, and section-aware muting.

### Bresenham builds (`examples/bresenham_poly.py`)

Dense generative drums demonstrating `composition.form()` with a weighted graph that cycles through four sections infinitely (pulse → emerge → peak → dissolve). Each section has its own sonic character from bar one. Uses `ghost_fill()` for probability-biased ghost note layers, `cellular()` for evolving cellular-automaton rhythms (Rules 30 and 90), `bresenham_poly()` for interlocking multi-voice hat patterns, and `perlin_1d()` for smooth organic parameter wandering. The weighted graph means the journey through sections is never quite the same twice. Channel 10 (MIDI 11), GM drum map.

### Emergence (`examples/emergence.py`)

A six-section generative drum composition that breathes, builds, and breaks. Six independent Perlin noise fields wander at prime-ish speeds - because `p.cycle` increments forever, every pass through the form samples a fresh region of each field, so no two bars are ever the same. The weighted graph usually flows void → pulse → swarm → fury → dissolve → void, but a rare "fracture" section can erupt from swarm or fury, lasting only 4 bars of controlled rhythmic chaos before scattering to dissolve, pulse, or void. A "lightning" event fires when the chaos Perlin peaks above 0.92 - roughly once every 70–80 bars. Uses the full rhythm toolkit: `cellular()` (Rules 30, 90, and 110), `ghost_fill()` with four bias modes, `bresenham_poly()`, `euclidean()` with Perlin-driven pulse counts in fracture, and transition-aware fills when `p.section.next_section` is known. Channel 10 (MIDI 11), GM drum map, 132 BPM.

### Frozen progressions (`examples/frozen.py`)

Demonstrates `freeze()` and `section_chords()` - pre-baking chord progressions with different `gravity` and `nir_strength` settings for verse, chorus, and bridge. The verse and chorus replay their frozen chords on every re-entry; the bridge generates live chords each time. Shows how to combine structural repetition with generative freedom in a single composition.

### ISS Telemetry (`examples/iss.py`)

Turns real-time International Space Station telemetry into an evolving composition. Fetches live ISS data every ~32 seconds and uses `EasedValue` instances to smoothly map orbital parameters to musical decisions.

- **Latitude** drives BPM, kick density, snare probabilities, and chord transition "gravity". Dense, fast beats near the poles; sparse groove over the equator.
- **Heading (Latitude delta)** dictates arpeggio direction - ascending while heading North, descending while heading South.
- **Visibility (Day/Night)** switches the harmonic mode - bright functional major in daylight, darker Dorian minor during eclipse.
- **Altitude**, **Longitude**, and **Footprint** influence chord voicings and ride cymbal pulse counts.

**How to run it:**
1. Install the `requests` library: `pip install requests`.
2. Connect your MIDI port to a multitimbral synth or DAW (channels: 10=Drums, 6=Bass, 1=Chords, 4=Arp). [Note: MIDI channels are zero-indexed in the code, i.e. 9, 5, 0, 3].
3. Run: `python examples/iss.py`.

## Extra utilities

### Rhythm & Pattern
- `subsequence.pattern_builder` provides the `PatternBuilder` with high-level musical methods.
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.groove` provides `Groove` templates (per-step timing/velocity feel). `Groove.swing(percent)` for percentage-based swing, `Groove.from_agr(path)` to import Ableton groove files, or construct directly with custom offsets. Applied via `p.groove(template)`.
- `subsequence.swing` applies swing timing to a pattern.
- `subsequence.sequence_utils` provides rhythm generation (Euclidean, Bresenham, weighted multi-voice Bresenham, van der Corput), probability gating, random walk, scale/clamp helpers, smooth 1D Perlin noise (`perlin_1d(x, seed)`), elementary cellular automaton sequences (`generate_cellular_automaton(steps, rule, generation, seed)`), and deterministic chaos sequences (`logistic_map(r, steps, x0=0.5)` - a single `r` parameter controls behaviour from stable fixed point through period-doubling to full chaos, complementing Perlin noise for modulation that can be dialled between order and unpredictability). The weighted Bresenham function (`generate_bresenham_sequence_weighted`) underlies `p.bresenham_poly()` - pass a `parts` dict mapping pitch names to density weights (0.0–1.0) and the voices are distributed across the step grid in interlocking Bresenham patterns. Add `no_overlap=True` to any of `euclidean()`, `bresenham()`, or `bresenham_poly()` to skip placement when the same MIDI pitch already occupies that step - prevents double-triggers when layering an anchor pattern with a ghost-note layer.
- `subsequence.mini_notation` parses a compact string syntax for step-sequencer patterns.
- `subsequence.easing` provides easing/transition curve functions used by `conductor.line()`, `target_bpm()`, `cc_ramp()`, and `pitch_bend_ramp()`. Pass `shape=` to any of these to control how a value moves over time. Built-in shapes: `"linear"` (default), `"ease_in"`, `"ease_out"`, `"ease_in_out"` (Hermite smoothstep), `"exponential"` (cubic, good for filter sweeps), `"logarithmic"` (cubic, good for volume fades), `"s_curve"` (Perlin smootherstep - smoother than `"ease_in_out"` for long transitions). Callable shapes are also accepted for custom curves. Also provides **`EasedValue`** - a lightweight stateful helper that smoothly interpolates between discrete data updates (e.g. API poll results, sensor readings) so patterns hear a continuous eased value rather than a hard jump on each fetch cycle. Create one instance per field at module level, call `.update(value)` in your scheduled task, and call `.get(progress)` in your pattern.

### Harmony & Scales
- `subsequence.intervals` contains interval and scale definitions (`INTERVAL_DEFINITIONS`) for harmonic work, including non-western scales (Hirajōshi, In-Sen, Iwato, Yo, Egyptian) and pentatonics. `SCALE_MODE_MAP` (aliased as `DIATONIC_MODE_MAP`) maps mode/scale names to interval sets and optional chord qualities. `register_scale(name, intervals, qualities=None)` adds custom scales at runtime. `scale_pitch_classes(key_pc, mode)` returns the pitch classes for any key and mode; `quantize_pitch(pitch, scale_pcs)` snaps a MIDI note to the nearest scale degree.
- `subsequence.harmony` provides `diatonic_chords(key, mode)` and `diatonic_chord_sequence(key, root_midi, count, mode)` for working with diatonic chord progressions without the chord graph engine, plus `ChordPattern` for a repeating chord driven by harmonic state.
- `subsequence.chord_graphs` contains chord transition graphs. Each is a `ChordGraph` subclass with `build()` and `gravity_sets()` methods. Built-in styles: `"diatonic_major"`, `"turnaround"`, `"aeolian_minor"`, `"phrygian_minor"`, `"lydian_major"`, `"dorian_minor"`, `"suspended"`, `"chromatic_mediant"`, `"mixolydian"`, `"whole_tone"`, `"diminished"`.
- `subsequence.harmonic_state` holds the shared chord/key state for multiple patterns.
- `subsequence.voicings` provides chord inversions and voice leading. `invert_chord()` rotates intervals; `VoiceLeadingState` picks the closest inversion to the previous chord automatically.
- `subsequence.markov_chain` provides a generic weighted Markov chain utility.
- `subsequence.melodic_state` provides `MelodicState` - the persistent melodic context for `p.melody()`. Tracks pitch history across bar rebuilds and applies NIR scoring (Reversal, Process, Closure, Proximity) to absolute MIDI pitches. Constructor params: `key`, `mode`, `low`, `high`, `nir_strength`, `chord_weight`, `rest_probability`, `pitch_diversity`. Exported from the top-level package as `subsequence.MelodicState`.
- `subsequence.weighted_graph` provides a generic weighted directed graph used for transitions. Used internally by `composition.form()` (section transitions), the harmony engine (chord progressions), and `p.markov()` (Markov-chain melody/bassline generation).

### MIDI Data
- `subsequence.constants.durations` provides beat-based duration constants. Import as `import subsequence.constants.durations as dur` and write `length = 9 * dur.SIXTEENTH` or `step = dur.DOTTED_EIGHTH` instead of raw floats. Constants: `THIRTYSECOND`, `SIXTEENTH`, `DOTTED_SIXTEENTH`, `TRIPLET_EIGHTH`, `EIGHTH`, `DOTTED_EIGHTH`, `TRIPLET_QUARTER`, `QUARTER`, `DOTTED_QUARTER`, `HALF`, `DOTTED_HALF`, `WHOLE`.
- `subsequence.constants.velocity` provides MIDI velocity constants. `DEFAULT_VELOCITY = 100` (most notes), `DEFAULT_CHORD_VELOCITY = 90` (harmonic content), `VELOCITY_SHAPE_LOW = 64` and `VELOCITY_SHAPE_HIGH = 127` (velocity shaping boundaries), `MIN_VELOCITY = 0`, `MAX_VELOCITY = 127`.
- `subsequence.constants.gm_drums` provides the General MIDI Level 1 drum note map. `GM_DRUM_MAP` can be passed as `drum_note_map`; individual constants like `KICK_1` are also available.
- `subsequence.constants.midi_notes` provides named MIDI note constants C0–G9 (MIDI 12–127). Import as `import subsequence.constants.midi_notes as notes`. Convention: `C4 = 60` (Middle C, MMA standard). Naturals: `C4`, `D4`, … `B4`. Sharps: `CS4` (C♯4), `DS4`, `FS4`, `GS4`, `AS4`. Use instead of raw integers: `root = notes.E2` (40), `p.note(notes.A4)` (69).
- `subsequence.constants.pulses` provides pulse-based MIDI timing constants used internally by the engine.

### Infrastructure
- `subsequence.composition` provides the `Composition` class and internal scheduling helpers.
- `subsequence.event_emitter` supports sync/async events used by the sequencer.
- `subsequence.osc` provides the OSC server/client for bi-directional communication. Receiving: `/bpm`, `/mute`, `/unmute`, `/data`. Status broadcasting: `/bar`, `/bpm`, `/chord`, `/section`. Pattern output: `p.osc()`, `p.osc_ramp()`.
- `subsequence.live_server` provides the TCP eval server for live coding. Started internally by `composition.live()`.
- `subsequence.live_client` provides the interactive REPL client. Run with `python -m subsequence.live_client`.

## Feature Roadmap

Planned features, roughly in order of priority.

### High priority

- **Comprehensive Cookbook and Tutorials.** A guided, progressive walkthrough that takes a new user from zero to an evolving composition in 15 minutes, alongside bite-sized, copy-paste recipes for common musical requests (e.g., "generative techno kick", "functional bassline"). The README is a reference; the tutorial and cookbook are the on-ramp.

- **Example library.** More short, self-contained compositions in different styles - minimal techno, ambient generative, polyrhythmic exploration, data-driven - so musicians can hear what the tool does before investing time. Each example should demonstrate 2-3 features and fit on one screen.

### Medium priority

- **Visual Dashboard / Web UI.** A lightweight local web dashboard to provide real-time visual feedback of the current Chord Graph, global Conductor signals, and active patterns, making the generative process more observable.

- **Cross-track / Inter-pattern awareness.** Implementing a high-level compositional capability allowing patterns to easily listen to and react to the current musical density or activity of other patterns.

- **Ableton Link support.** The de facto standard for wireless tempo sync between devices in a modern studio.

- **Starter templates.** Lower the blank-page barrier with ready-made starting points for common genres. Musicians tweak from a working composition rather than building from scratch.

- **Network sync.** Peer-to-peer sync with DAWs and other Link-enabled devices, covering multi-machine Subsequence setups or custom sync protocols.

### Future ideas

- **Standalone Raspberry Pi mode.** Run Subsequence headlessly on a Raspberry Pi with a small touchscreen - turning it into a dedicated hardware sequencer with no desktop environment required.

- **Performance profiling.** Optional debug mode logging timing per `on_reschedule()` call, helping identify pattern logic that may cause jitter under load.

- **Live coding UX improvements.** Richer feedback in the live client - syntax highlighting, error display, undo/history for hot-swapped patterns. Explore integration with editors (VS Code extension, Jupyter notebooks).

- **CV/Gate output.** Direct control voltage output for modular synthesisers via supported hardware interfaces, bridging the gap between code and analogue.

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
