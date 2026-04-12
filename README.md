# Subsequence

**A Stateful Algorithmic MIDI Sequencer for Python.** Subsequence is a generative MIDI sequencer and algorithmic composition engine for your studio. It gives you a palette of advanced algorithmic building blocks - Euclidean rhythm generators, cellular automata, L-systems, Markov chains - and a stateful engine that lets them interact and evolve over time, driving your hardware synths and VSTs with rock-solid timing.

It is designed for **the professional musician who wants generative music with as much control or chaos as they choose** - where patterns combine, react to context, and develop in ways that reward exploration.

Unlike tools that loop a fixed pattern forever, Subsequence rebuilds every pattern fresh before each cycle, granting macro-level structural control and narrative evolution. Each rebuild has full context - the current chord, the composition section, the cycle count, shared data from other patterns. A Euclidean rhythm can thin itself as tension builds; a cellular automaton can seed from the harmony.

An optional chord graph lets you define weighted chord and key transitions; layer on cognitive harmony for Narmour-based melodic inertia, gravity, and voice leading - progressions that model how listeners expect music to move.

Use your own gear. Subsequence provides the logic; your Eurorack, Elektron boxes, or DAW provide the sound. Serving as a boundless software alternative to hardware sequencers, there are no fixed limits on tracks, polyphony, complexity, or pattern length.

> **What you need:** Basic Python knowledge and any MIDI-controllable instrument. Whether you are an experienced coder or a musician tempted to learn Python for the first time, the API is intuitive and accessible. Subsequence generates pure MIDI data; it does not produce sound itself.


## Contents

- **1. Getting Started**
  - [Introduction](#introduction)
  - [Why Subsequence?](#why-subsequence)
  - [What it does](#what-it-does)
  - [Minimal Example](#minimal-example)
  - [Quick start](#quick-start)
- **2. Generating Music**
  - [Algorithmic generators](#algorithmic-generators)
  - [Melody generation](#melody-generation)
- **3. The Core APIs**
  - [Composition API](#composition-api)
  - [Direct Pattern API](#direct-pattern-api)
  - [Mini-notation](#mini-notation)
- **4. Harmony & Structure**
  - [Form and sections](#form-and-sections)
  - [The Conductor](#the-conductor)
  - [Chord inversions and voice leading](#chord-inversions-and-voice-leading)
  - [Harmony and chord graphs](#harmony-and-chord-graphs)
  - [Frozen progressions](#frozen-progressions)
- **5. Live Performance & Tools**
  - [Seed and deterministic randomness](#seed-and-deterministic-randomness)
  - [Terminal display](#terminal-display)
  - [Web UI Dashboard (Beta)](#web-ui-dashboard-beta)
  - [MIDI recording and rendering](#midi-recording-and-rendering)
  - [Live coding](#live-coding)
  - [Clock accuracy](#clock-accuracy)
  - [MIDI input and external clock](#midi-input-and-external-clock)
  - [Ableton Link](#ableton-link)
  - [Pattern tools and hardware control](#pattern-tools-and-hardware-control)
  - [OSC integration](#osc-integration)
  - [Hotkeys](#hotkeys)
  - [Groove](#groove)
- **6. Workflow & Utilities**
  - [Examples](#examples)
  - [Extra utilities](#extra-utilities)
- **7. Project Info**
  - [Feature Roadmap](#feature-roadmap)
  - [Tests](#tests)
  - [Community and Feedback](#community-and-feedback)
  - [Related Projects](#related-projects)
  - [Dependencies and Credits](#dependencies-and-credits)
  - [About the Author](#about-the-author)
  - [License](#license)

## 1. Getting Started

### Introduction

Subsequence is a generative MIDI sequencer and algorithmic composition engine for your studio. Engineered for rock-solid timing and efficiency, it gives you a palette of advanced algorithmic building blocks - Euclidean rhythm generators, cellular automata, L-systems, Markov chains - and a stateful engine that lets them interact and evolve over time.

It is designed for **the professional musician who wants generative music with as much control or chaos as they choose** - where patterns combine, react to context, and develop in ways that reward exploration. An optional chord graph lets you define weighted chord and key transitions; layer on cognitive harmony for Narmour-based melodic inertia, gravity, and voice leading - progressions that model how listeners expect music to move.

### Why Subsequence?

- **Precision and efficiency.** Built for live performance and serious studio use. A highly-optimized hybrid timing strategy achieves typical pulse jitter of **< 5 μs** on Linux, while a comprehensively tested codebase provides rock-solid stability.
- **Accessible Python, no CS degree required.** If you can configure a synth, you can write generative music here. It is the perfect project to tempt a musician into learning basic Python. Simple algorithmic building blocks mean you can get started with tiny scripts and learn as you go.
- **Not just for algorithms.** You can program traditional basslines or fixed drum grooves without any generative variation. Use Subsequence as a highly precise, Python-driven standard MIDI sequencer alongside your evolving patterns.
- **Implicit Compositional Structure.** Subsequence understands predefined sections, bringing overarching musical form to a piece without getting stuck in infinite loops. Patterns rebuild each cycle with full context - chord, section, history - so music can grow and develop across defined movement.
- **Built-in harmonic intelligence.** An optional chord graph lets you define weighted chord and key transitions, with gravity and automatic voice leading. Layer on cognitive harmony for Narmour-based melodic inertia - big leaps tend to reverse, small steps tend to continue - for melodies that model deep listener expectations.
- **Between traditional and generative.** Most sequencers repeat a fixed loop. Most live-coding environments are stateless - the algorithm has no memory of what it just generated. Subsequence rebuilds every pattern fresh each cycle with full context: current chord, section, history, shared data. Patterns that evolve, remember, and react.
- **Patterns that talk to each other.** Shared state (`composition.data`) lets autonomous generators cooperate without coupling. A drum pattern can broadcast its density; a bass pattern reads it to place complementary gaps. No callbacks, no wiring - just a shared namespace rebuilt in sync.
- **Explore, capture, produce.** Seed a session for deterministic output: explore freely, and when something clicks, the same seed recreates it exactly. [Record](#midi-recording-and-rendering) to a standard multi-channel `.mid` file and bring it straight into your DAW to arrange, edit, and polish.
- **Turn anything into music.** Patterns are plain Python functions, so any data source - live APIs, sensors, files, network streams - can drive musical decisions at rebuild time. Orbital telemetry, weather data, stock feeds, machine learning outputs: if Python can read it, Subsequence can play it.
- **Microtonal-ready.** Scala `.scl` file support and N-TET equal temperaments out of the box. Per-note pitch bend is injected automatically - no MPE, no special hardware. Works with any standard MIDI synth.

### What it does

- **Stateful patterns that evolve.** Each pattern is a Python function rebuilt fresh every cycle with full context. Patterns can remember history and decide their next move.
- **Cognitive harmony engine.** Chord progressions evolve via [weighted transition graphs](#harmony-and-chord-graphs) with adjustable gravity and [Narmour-based melodic inertia](#harmonic-gravity-and-melodic-inertia). Automatic [voice leading](#automatic-voice-leading).
- **Single-digit-microsecond clock.** A hybrid sleep+spin timing strategy achieves typical pulse jitter of **< 5 μs** on Linux ([measured](#clock-accuracy)), with zero long-term drift.
- **Pure MIDI, zero sound engine.** Route to hardware synths, drum machines, Eurorack, or VSTs. You provide the sound; Subsequence provides the logic.

### Minimal Example

This is all the code you need to build a simple drum pattern:

```python
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums

composition = subsequence.Composition(bpm=120)

@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):

    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100) # beats 1, 2, 3, 4
    p.hit_steps("snare_1", [4, 12], velocity=90) # beats 2 and 4
    p.hit_steps("hi_hat_closed", range(16), velocity=70) # every sixteenth

composition.play()
```

### Quick start

1. Install dependencies:
```bash
pip install -e .
```
2. Enable Ableton Link support (optional):
```bash
pip install -e ".[link]"
```
3. Run the demo:
```bash
python examples/demo.py
```

For the complete API reference, see the **[documentation](https://simonholliday.github.io/subsequence)**.

## 2. Generating Music

### Algorithmic generators

Before diving into the API, here's what powers it. Subsequence is built on algorithms borrowed from mathematics, physics, biology, and computer science - ideas originally developed to model weather, simulate chemical reactions, draw straight lines on plotters, and generate textures for films. Each one, when applied to rhythm and melody, produces results with a character you can't achieve by programming notes by hand.

These are some of the building blocks available for composition in Subsequence. You don't need to understand the maths to use them - most take two or three parameters and produce something musically interesting immediately.

They're designed to work together inside the stateful engine. A Euclidean rhythm can thin itself based on a conductor signal; a cellular automaton can seed from the current chord; a Perlin noise field can drift velocity across bars while a Markov chain steers the harmony. The algorithms are the vocabulary - the rebuild engine is the grammar.

The first three entries below (`perlin_1d`, `logistic_map`, `pink_noise`) are standalone functions in `subsequence.sequence_utils`, called directly inside pattern functions. The rest are `p.` methods on `PatternBuilder` - you'll see how patterns work in the [Composition API](#composition-api) section that follows.

### Perlin noise

Ken Perlin invented gradient noise in 1983 to generate natural-looking textures for the film *Tron* - he later won an Academy Award for the technique. His insight was that pure randomness looks artificial, but smoothly interpolated randomness looks organic. `perlin_1d(x, seed)` produces values where neighbours are correlated - it drifts like wind, not dice. Use it for velocity curves, pitch bend, density envelopes, or any parameter that should evolve continuously. `perlin_1d_sequence()` returns a list for per-step modulation; `perlin_2d()` adds a second axis (e.g. bar × step position).

`p.grid` is the number of 16th-note steps in this pattern - `16` for a 4-beat bar (`beats=4`), `32` for two bars. In step mode (`steps=N, unit=dur.SIXTEENTH`), `p.grid` equals `N` directly.

```python
import subsequence.sequence_utils
import subsequence.easing

hat_noise = subsequence.sequence_utils.perlin_1d_sequence(
	start=p.bar * p.grid * 0.1, spacing=0.1, count=p.grid, seed=10
)
hat_velocities = [int(subsequence.easing.map_value(v, out_min=50, out_max=100)) for v in hat_noise]
p.hit_steps("hi_hat_closed", range(p.grid), velocity=hat_velocities)
```

### Logistic map

Biologist Robert May introduced `x_{n+1} = r·x_n·(1 - x_n)` in 1976 to model how animal populations boom and crash between seasons. The equation became a landmark of chaos theory: a single parameter `r` controls a smooth transition from stability through period-doubling to full deterministic chaos. `logistic_map(r, steps)` gives you that dial. Below `r=3.0`: stable. Between `3.0` and `3.57`: period-doubling (rhythmic subdivisions). Above `3.57`: chaos. Use it to modulate density, velocity, or anything that should feel on the edge of control.

```python
chaos = subsequence.sequence_utils.logistic_map(r=3.8, steps=16)
for i, v in enumerate(chaos):
	if v > 0.5:
		p.hit_steps("hi_hat_open", [i], velocity=int(v * 100))
```

### Pink noise

Voss and Clarke showed in 1975 that the fluctuations in pitch and loudness of Bach, Scott Joplin, and radio broadcasts all follow a 1/f ("pink") power spectrum - variation at every timescale simultaneously, with larger changes happening more slowly. `pink_noise(steps, seed)` produces values with both slow drift and fast jitter in the same signal, sitting between white noise (flat, uncorrelated) and brown noise (random walk, overly smooth). It matches the statistical fingerprint of real musical dynamics - use it for velocity humanisation, CC modulation, or anywhere you want variation that sounds natural.

```python
pink = subsequence.sequence_utils.pink_noise(16, seed=p.cycle)
velocities = [int(subsequence.easing.map_value(v, out_min=40, out_max=110)) for v in pink]
p.hit_steps("snare_1", range(16), velocity=velocities)
```

### Euclidean

Euclid's algorithm for computing greatest common divisors dates to 300 BC. In 2003, Bjorklund applied it to distribute neutron accelerator pulses as evenly as possible, and Toussaint (2005) showed the resulting patterns match traditional rhythms from around the world - West African bell patterns, Cuban clave, Turkish aksak. `p.euclidean(pitch, pulses, steps)` distributes `pulses` hits as evenly as possible across a `steps`-step grid. Two numbers in, a rhythm out.

```python
p.euclidean("kick_1", pulses=5, steps=16, velocity=100) # tresillo / bossa clave
p.euclidean("hi_hat_closed", pulses=7, steps=12, velocity=70) # 7-against-12
```

### Bresenham

Jack Bresenham developed his line-drawing algorithm at IBM in 1962 for pen plotters - distributing pixels along a line using only integer arithmetic. Where Euclidean rhythms maximise evenness, Bresenham distributes points along a slope, producing subtly different spacings. `p.bresenham(pitch, pulses, steps)` places hits with Bresenham spacing. `p.bresenham_poly(parts, steps)` goes further, distributing multiple voices simultaneously with `no_overlap` collision avoidance - interlocking patterns from a single call.

```python
p.bresenham_poly({
	"kick_1":        0.4,
	"snare_1":       0.25,
	"hi_hat_closed": 0.7,
}, steps=16, no_overlap=True)
```

### Ghost fill

Ghost notes are a drumming technique - barely-audible hits between the main accents that give a groove its feel. Funk and hip-hop drummers (Bernard Purdie, Clyde Stubblefield, Questlove) elevated them to an art form, creating rhythms where what you almost *don't* hear matters as much as the backbeat. `p.ghost_fill(pitch, density, velocity, bias, no_overlap)` adds probability-weighted ghost notes around an existing rhythm. `density` (0–1) scales the fill rate; `bias` shapes which positions are preferred: `"offbeat"`, `"sixteenths"`, `"uniform"`, or a custom per-step weight list.

```python
p.hit_steps("snare_1", {4, 12}, velocity=100)
p.ghost_fill("snare_1", density=0.4, velocity=(30, 60), bias="offbeat", no_overlap=True)
```

**Freeze placement each cycle** - by default ghost positions are different each cycle. Pass `rng=random.Random(seed)` to create a fresh RNG on every rebuild: the same steps are chosen every time, while velocity variation from a `(low, high)` tuple still shifts naturally.

```python
import random

# Same ghost steps every cycle - placement locked, velocity still varies
p.ghost_fill("snare_1", density=0.3, velocity=(25, 45),
             bias="sixteenths", rng=random.Random(7))
```

**Custom bias with `build_ghost_bias`** - `p.build_ghost_bias(grid, bias)` is a public helper that generates the named weight list and returns it as a plain Python list. Modify specific steps before passing it back as `bias=` to get surgical control over which positions are suppressed or boosted.

```python
# Start from a named curve, then silence beat 3 and boost the step before beat 4
weights = p.build_ghost_bias(16, "sixteenths")
weights[8] = 0.0   # no ghosts around beat 3
weights[11] = 1.0  # strong "and" before beat 4
p.ghost_fill("snare_1", density=0.25, velocity=(25, 45),
             bias=weights, no_overlap=True)
```

### Thin

The musical inverse of ghost fill - a subtractive partner to an additive process. Where ghost fill asks "where should I add?", thin asks "where should I remove?". `p.thin(strategy, amount, grid, rng)` removes notes by position-aware probability. `strategy` can be `"front"`, `"back"`, `"uniform"`, or a custom bias list; `amount` (0–1) controls how aggressively notes are thinned. Pair with a conductor signal to sculpt density over time.

```python
# As swell rises, earlier arpeggio notes drop out first
bias = [1.0 - i / 15 for i in range(16)]
p.thin(strategy=bias, amount=swell, grid=16, rng=p.rng)
```

### Ratchet

Ratcheting is a hardware sequencer technique heard on some hardware sequencers - where a single step fires as a rapid burst of repeated hits rather than one note. `p.ratchet(subdivisions, pitch, probability, velocity_start, velocity_end, shape, gate, steps)` is a post-placement transform: it takes notes already in the pattern and replaces each one with `subdivisions` evenly-spaced sub-hits within the original note's duration window. Call it after note-placement methods and before swing or groove.

Velocity across sub-hits is shaped by multipliers (`velocity_start` → `velocity_end`) interpolated via an easing curve - the same easing vocabulary used by `cc_ramp()`. `gate` (0–1) sets sub-note duration as a fraction of each slot: `0.5` is staccato, `1.0` is legato. Use `pitch` to target a single instrument; use `steps` (a list of grid indices) to only ratchet specific positions; use `probability` for chance-based subdivision.

```python
# Triplet roll on every hi-hat
p.euclidean("hh_closed", 8).ratchet(3, pitch="hh_closed")

# Crescendo snare roll: quiet → loud over 4 sub-hits
p.hit_steps("snare", [12]).ratchet(4, velocity_start=0.3, velocity_end=1.0, shape="ease_in")

# Probabilistic 2× ratchet with tight gate
p.euclidean("hh_closed", 12).ratchet(2, probability=0.4, gate=0.25)

# Ratchet only the downbeat and midpoint (steps 0 and 8 of 16)
p.euclidean("kick_1", 6).ratchet(2, pitch="kick_1", steps=[0, 8])
```

### Cellular automaton

John von Neumann and Stanislaw Ulam conceived cellular automata in the 1940s as models of self-replicating systems. Stephen Wolfram systematically explored 1D elementary automata in the 1980s, cataloguing all 256 rules - discovering that Rule 110 is Turing-complete and Rule 30 produces output indistinguishable from randomness. `p.cellular_1d(pitch, rule, velocity)` generates rhythm from a 1D automaton where each generation evolves from the previous, so patterns self-organise, grow, glide, and die. `p.cellular_2d(parts, rule, density, velocity)` runs a 2D Life-like CA where rows map to instruments and columns to time steps.

```python
p.cellular_1d("kick_1", rule=30, velocity=90) # Rule 30: chaotic
p.cellular_1d("hi_hat_closed", rule=110, velocity=70) # Rule 110: complex / structured
```

### Markov

Andrey Markov introduced his probability chains in 1906 to analyse letter sequences in Pushkin's *Eugene Onegin* - proving that dependent random events could still obey the law of large numbers. The model became foundational to information theory, speech recognition, and algorithmic composition (Hiller and Isaacson's *Illiac Suite*, 1957 - one of the first computer-generated scores). `p.markov(pitches, transitions, step, velocity)` walks a weighted transition graph where each note influences only the next - local coherence without global structure. The transition weights define the style: tight weights produce stepwise motion, loose weights produce leaps.

```python
import subsequence
import subsequence.constants.midi_notes as notes

# C major: one octave from middle C (C4–B4)
scale = subsequence.scale_notes("C", "ionian", low=notes.C4, high=notes.B4)
transitions = {i: {i: 3, i-1: 1, i+1: 1} for i in range(len(scale))}
p.markov(scale, transitions, spacing=0.25, velocity=(60, 100))
```

### L-system

Aristid Lindenmayer invented L-systems in 1968 to model the branching growth of algae and plants. A simple rewriting rule ("replace A with AB, replace B with A") applied repeatedly produces Fibonacci-length strings; more complex rules generate fractal trees, ferns, and Koch curves. Unlike sequential grammars, L-systems apply all rules in parallel - every cell grows simultaneously. `p.lsystem(axiom, rules, generations, step, velocity)` expands an L-system string then interprets it as rhythm or melody. The result is self-similar: successive generations produce related patterns at increasing density. Stochastic rules (weighted alternatives) add controlled variation.

```python
p.lsystem(axiom="X", rules={"X": "FX", "F": "FF"}, generations=4, spacing=0.25, velocity=80)
```

### Thue-Morse

Axel Thue described this sequence in 1906 while studying combinatorics on words; Marston Morse rediscovered it in 1921 in differential geometry. The construction is simple - negate the sequence and append - yet the result is aperiodic (never strictly repeating), overlap-free, and perfectly balanced (equal density of 0s and 1s over any power-of-two window). `p.thue_morse()` generates rhythm with this fractal, self-similar structure - unlike Euclidean rhythms (maximally even) or cellular automata (evolving), Thue-Morse is fixed but never periodic. In two-pitch mode (`pitch_b` given), every step plays, alternating between two voices:

```python
@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):
	# Aperiodic kick rhythm - hits at 0-positions of the sequence
	p.thue_morse("kick_1", velocity=100)

	# Two-pitch mode: kick on 0s, snare on 1s - fills all 16 steps
	p.thue_morse("kick_1", pitch_b="snare_1", velocity=90)
```

### De Bruijn

Nicolaas Govert de Bruijn formalised these sequences in 1946, building on earlier work by Martin. A classic application: cracking rotary combination locks - a de Bruijn sequence of order n over k symbols contains every possible n-length combination exactly once, so you can test all combinations by sliding along a single string. `p.de_bruijn()` applies this to melody: over `k` pitches with window `n`, every possible `n`-gram appears exactly once across the bar - every pair (window=2) or triple (window=3) of consecutive pitches is covered. The output auto-fits to the bar length (like `lsystem`) or uses a fixed step.

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def melody (p):
	# All 9 possible 2-note transitions over a C-D-E palette
	p.de_bruijn([notes.C4, notes.D4, notes.E4], window=2, velocity=(60, 100))
```

### Fibonacci

Fibonacci described his sequence in 1202 to model rabbit populations, but the golden ratio it converges to (φ ≈ 1.618) appears throughout nature in phyllotaxis - the spiral arrangement of seeds in sunflowers, leaves on stems, and scales on pinecones. The golden angle (≈137.5°) is the optimal rotation for packing elements with maximum separation and minimum alignment. `p.fibonacci()` places notes using this spacing: each beat position is `(i × φ) mod bar_length`, then sorted - producing an irrational distribution that never lands on a repeating grid. The result is organic, flowing, and maximally spread - like a sunflower, but in time.

```python
@composition.pattern(channel=1, beats=4)
def hi_hats (p):
	# 11 hits with golden-ratio spacing across 4 beats
	p.fibonacci("hi_hat_closed", steps=11, velocity=(60, 90))
```

### Lorenz attractor

Meteorologist Edward Lorenz discovered his strange attractor in 1963 while simulating weather convection with three coupled differential equations. The trajectory never repeats, never settles, and diverges exponentially from nearby starting points - what he later called the "butterfly effect". `p.lorenz()` drives pitch, velocity, and duration from the three axes - correlated-but-independent modulation from a single chaotic source. Small changes to `x0` produce paths that gradually diverge, giving each cycle a different phrase that still shares a family resemblance.

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=2, beats=4)
def chaos_melody (p, chord):
	scale = chord.tones(root=notes.C4, count=8)  # 8 chord tones across octaves

	# Different phrase each cycle, slowly drifting
	p.lorenz(scale, spacing=0.25, velocity=(50, 110), x0=p.cycle * 0.002)
```

A custom `mapping` callable overrides the default x→pitch / y→velocity / z→duration assignment, or returns `None` for a rest:

```python
import subsequence.constants.midi_notes as notes

# Map Lorenz x-axis to a chromatic octave above middle C
p.lorenz([notes.C4, notes.D4, notes.E4], spacing=0.5,
         mapping=lambda x, y, z: (notes.C4 + int(x * 12), 80, 0.2))
```

### Reaction-diffusion

Alan Turing proposed reaction-diffusion in his 1952 paper *"The Chemical Basis of Morphogenesis"* - his final major work. He showed that two chemicals diffusing at different rates and reacting with each other spontaneously produce spatial patterns: spots, stripes, and travelling waves. The model now explains leopard spots, zebra stripes, and coral growth. `p.reaction_diffusion()` runs a 1D Gray-Scott simulation on a ring of cells, then thresholds the resulting concentration field to a hit grid. Unlike cellular automata (discrete binary rules), reaction-diffusion evolves a continuous field - the patterns have a biological, organic character. The `feed_rate` and `kill_rate` parameters select the pattern regime - small changes move between dramatically different pattern types.

```python
@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def organic_kick (p):
	p.reaction_diffusion("kick_1", threshold=0.4, feed_rate=0.055, kill_rate=0.062)

	# Velocity tuple maps concentration to velocity range for active steps
	p.reaction_diffusion("hi_hat_closed", threshold=0.3, velocity=(50, 100))
```

### Self-avoiding walk

Paul Flory pioneered self-avoiding walks in the 1940s–50s to model how polymer chains fold in solution - a molecule that cannot cross itself. The problem became central to statistical physics and remains one of the most-studied objects in combinatorics. `p.self_avoiding_walk()` walks ±1 through a pitch list, refusing to revisit any pitch until trapped (all neighbours visited) - at that point the visited set resets, creating a natural phrase boundary. Within each phrase: no pitch repeats, continuous stepwise motion, guaranteed diversity.

```python
import subsequence

@composition.pattern(channel=2, beats=4)
def bassline (p):
	# E natural minor: E2 to E3, one full octave
	scale = subsequence.scale_notes("E", "aeolian", low=40, high=52)
	p.self_avoiding_walk(scale, spacing=0.25, velocity=(70, 100))
```

### Melody generation

`p.melody()` generates a single-note melodic line guided by the Narmour Implication-Realization (NIR) model - the same cognitive framework used by the chord engine, now adapted for absolute pitch. It expects a `MelodicState` instance created once at module level, which persists history across bar rebuilds so melodic continuity is maintained automatically.

```python
import subsequence.constants.midi_notes as notes

# Create once at module level - history persists across bars.
melody_state = subsequence.MelodicState(
	key="A",
	mode="aeolian",
	low=notes.A3,   # two-octave range: A3 to C6
	high=notes.C6,
	nir_strength=0.6, # How strongly NIR rules shape pitch choice (0–1)
	chord_weight=0.4, # Bonus for chord tones
	rest_probability=0.1, # 10% chance of silence per step
	pitch_diversity=0.6, # Penalise recently-repeated pitches
)

@composition.pattern(channel=4, beats=4, chord=True)
def lead (p, chord):
	tones = chord.tones(notes.C5) if chord else None
	p.melody(melody_state, spacing=0.5, velocity=(70, 100), chord_tones=tones)
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

## 3. The Core APIs

### Composition API

The `Composition` class is the main entry point. Define your MIDI setup, create a composition, add patterns, and play:

```python
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.constants.midi_notes as notes

DRUMS_CHANNEL = 10
BASS_CHANNEL  = 6
SYNTH_CHANNEL = 1

composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

@composition.pattern(channel=DRUMS_CHANNEL, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):
    (p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
      .hit_steps("snare_1", [4, 12], velocity=100)
      .hit_steps("hi_hat_closed", range(16), velocity=80)
      .velocity_shape(low=60, high=100))

@composition.pattern(channel=BASS_CHANNEL, beats=4)
def bass (p, chord):
    root = chord.root_note(notes.E2)  # root voice in bass register
    p.sequence(steps=[0, 4, 8, 12], pitches=root)
    p.legato(0.9)

@composition.pattern(channel=SYNTH_CHANNEL, beats=4)
def arp (p, chord):
    pitches = chord.tones(root=notes.C4, count=4)  # 4 tones up from middle C
    p.arpeggio(pitches, spacing=0.25, velocity=90, direction="up")

if __name__ == "__main__":
    composition.play()
```

Pattern length can be specified two ways - use whichever is clearest:

```python
@composition.pattern(channel=1, beats=4)   # 4 quarter notes (1 bar in 4/4)
@composition.pattern(channel=1, bars=2)    # 2 bars (8 beats)
```

When `output_device` is omitted, Subsequence auto-discovers available MIDI devices. If only one device is connected it is used automatically; if several are found you are prompted to choose. To skip the prompt, pass the device name directly: `Composition(output_device="Your Device:Port", ...)`.

**Multiple output devices** - use `comp.midi_output()` to register additional devices. Each call returns a device index (1, 2, …) that can be used in pattern decorators or as a named alias:

```python
comp = subsequence.Composition(bpm=120, output_device="MOTU Express")  # device 0

comp.midi_output("Roland Integra", name="integra")   # device 1
comp.midi_output("Elektron Analog Four", name="a4")  # device 2

@comp.pattern(channel=1, beats=4, device="integra")
def strings(p):
    p.note(60, beat=0)

@comp.pattern(channel=1, beats=4)  # device defaults to 0 (MOTU Express)
def bass(p):
    p.note(36, beat=0)
```

Patterns without a `device=` parameter always route to device 0 - single-device compositions work exactly as before without any changes.

MIDI channels and drum note mappings are defined by the musician in their composition file - the module does not ship studio-specific constants. Channels use 1-based numbering by default (1-16, matching instrument panels - channel 10 is drums). To use 0-based numbering (0-15, matching the raw MIDI protocol), pass `zero_indexed_channels=True`:

```python
composition = subsequence.Composition(bpm=120, key="E", zero_indexed_channels=True)

@composition.pattern(channel=9, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):
    ...
```

Patterns are plain Python functions, so anything you can express in Python is fair game. A few more features:

```python
import subsequence.constants.midi_notes as notes

# Per-step pitch, velocity, and duration control.
@composition.pattern(channel=1, beats=4)
def melody (p):
    p.sequence(
        steps=[0, 4, 8, 12],
        pitches=[notes.C4, notes.E4, notes.G4, notes.C5],  # C major chord, open voicing
        velocities=[127, 100, 110, 100],
        durations=[0.5, 0.25, 0.25, 0.5],
    )

# Non-quarter-note grid: 6 sixteenth notes (reads like "6/16" in a score).
# hit_steps() and sequence() automatically use 6 grid slots.
import subsequence.constants.durations as dur

@composition.pattern(channel=1, steps=6, unit=dur.SIXTEENTH)
def riff (p, chord):
    root = chord.root_note(notes.E4)  # root voice around E4
    p.sequence(steps=[0, 1, 3, 5], pitches=[root+12, root, root, root])

# Per-step probability - each hi-hat has a 70% chance of playing.
@composition.pattern(channel=DRUMS_CHANNEL, beats=4, drum_note_map=DRUM_NOTE_MAP)
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

### Direct Pattern API

The Direct Pattern API gives you full control over the sequencer, harmony, and scheduling. Patterns are classes instead of decorated functions - you manage the event loop yourself.

<details>
<summary>Full example - same music as the Composition API demo above (click to expand)</summary>

```python
import asyncio

import subsequence.composition
import subsequence.constants
import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.constants.midi_notes as notes
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
        (p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
          .hit_steps("snare_1", [4, 12], velocity=100)
          .hit_steps("hi_hat_closed", range(16), velocity=80)
          .velocity_shape(low=60, high=100))

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
        root  = chord.root_note(notes.E2)  # bass voice in bass register
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
        pitches = chord.tones(root=notes.C4, count=4)  # 4 tones up from middle C
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
*   **Best for:** Rapid prototyping, standard musical forms, live coding.
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

### Mini-notation

For quick rhythmic or melodic entry, Subsequence offers a concise string syntax inspired by live-coding environments. This allows you to express complex rhythms and subdivisions without verbose list definitions.

### Rhythm (Fixed Pitch)

When you provide a `pitch` argument, the string defines the rhythm. Any symbol (except special characters) is treated as a hit.

```python
@composition.pattern(channel=DRUMS_CHANNEL, beats=4)
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
@composition.pattern(channel=SYNTH_CHANNEL, beats=4)
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

## 4. Harmony & Structure

### Form and sections

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

@composition.pattern(channel=10, beats=4, drum_note_map=DRUM_NOTE_MAP)
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

`p.bar` and `p.cycle` are always available (regardless of form) and track two different counters:

- **`p.bar`** - global bar count since playback started. Increments once per time-signature period (every 4 beats in 4/4), regardless of individual pattern lengths.
- **`p.cycle`** - how many times *this pattern* has rebuilt. Increments every time the pattern function runs.

For a `beats=4` pattern in 4/4, they're always equal. For a `beats=8` pattern, `p.cycle` is half `p.bar` (the pattern runs once every two bars). For a `beats=2` pattern, `p.cycle` is double `p.bar`. Use `p.bar` for composition-wide synchronisation (e.g. "fire on bar 8") and `p.cycle` for pattern-local variation (e.g. "every 4th rebuild of this pattern").

#### Musical phrase position - `p.phrase(length)`

For bar-position logic, `p.phrase(length)` replaces raw modulo arithmetic with readable musical vocabulary:

| Intent | Raw modulo | `p.phrase()` |
|---|---|---|
| Every 4 bars | `if p.bar % 4 == 0:` | `if p.phrase(4).first:` |
| Bar 3 of every 8 | `if p.bar % 8 == 2:` | `if p.phrase(8).bar == 2:` |
| Last bar of every 16 | `if p.bar % 16 == 15:` | `if p.phrase(16).last:` |
| Progress through phrase | `(p.bar % 8) / 8` | `p.phrase(8).progress` |

`p.phrase(length)` returns a `Phrase` object with four properties:

- **`.first`** - `True` on the first bar of the phrase
- **`.last`** - `True` on the last bar of the phrase
- **`.bar`** - zero-indexed position within the phrase (0 … length−1)
- **`.progress`** - fractional progress: 0.0 on bar 0, rising each bar (0.25, 0.5, 0.75 for a 4-bar phrase)

```python
@composition.pattern(channel=1, beats=4)
def drums(p):

    p.euclidean("kick_1", 4)

    # Add an open hi-hat fill on the last bar of every 8-bar phrase
    if p.phrase(8).last:
        p.euclidean("hi_hat_open", 3)

    # Build velocity over a 16-bar arc
    intensity = p.phrase(16).progress   # 0.0 → 0.9375
    p.velocity_shape(low=int(50 + 40 * intensity), high=110)
```

To replay the same chords every time a section recurs, see [Frozen progressions](#frozen-progressions).

### The Conductor

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
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def pads(p):
    dynamics = p.signal("swell")

    p.chord(chord, root=notes.C4, velocity=int(60 + 60 * dynamics))
```

For explicit beat control, use `p.conductor.get(name, beat)` directly.

### Shaping transitions

By default, all ramps are linear. Pass `shape=` to any ramp to change how the value moves:

```python
# Slow build that accelerates - good for intensity lines
composition.conductor.line("build", start_val=0.0, end_val=1.0, duration_beats=64, shape="ease_in")

# S-curve BPM shift - the tempo barely moves at first, rushes through the middle, then settles gently
composition.target_bpm(140, bars=16, shape="ease_in_out")

# Filter sweep - cubic response approximates how we hear filter changes
@composition.pattern(channel=1, beats=4)
def sweep (p):
    p.cc_ramp(74, 0, 127, shape="exponential")
```

Available shapes: `"linear"` (default), `"ease_in"`, `"ease_out"`, `"ease_in_out"`, `"exponential"`, `"logarithmic"`, `"s_curve"`. You can also pass any callable that maps a float in [0, 1] to a float in [0, 1] for a custom curve. See `subsequence.easing` for details.

### State vs Signals

Subsequence offers two complementary ways to store values: **Data** (state) and **Conductor** (signals). Use whichever fits:

| | `composition.data` / `p.data` | `composition.conductor` |
|---|---|---|
| **Question it answers** | "What is the value RIGHT NOW?" | "What was the value at beat 40?" |
| **Nature** | Static snapshots - no concept of time | Time-variant signals (LFOs, ramps) |
| **Best for** | External inputs (sensors, API data), mode switches, inter-pattern state | Musical evolution (fades, swells, modulation) that must be smooth and continuous |

Inside a pattern, `p.data` is a direct reference to `composition.data` - the same dictionary object. You can read it, write to it, and use it to pass values between patterns.

Patterns always rebuild in **definition order** (top-to-bottom in your source file). When two patterns share the same `length`, they reschedule at the same moment and the earlier pattern rebuilds first - so the writer's value is already in `p.data` when the reader runs:

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)   # defined first - rebuilds first
def bass(p):
    root = 36 + (p.cycle % 12)
    p.data["bass_root"] = root         # visible to patterns that follow this cycle
    p.note(root, velocity=100)

@composition.pattern(channel=2, beats=4)   # same length - guaranteed same-cycle read
def pad(p):
    root = p.data.get("bass_root", notes.C3) # current-cycle value, because bass ran first
    p.chord(root=root, velocity=60)
```

If the two patterns have **different lengths** they reschedule at different moments, so the reader sees the writer's value from its most recent rebuild - at most one bar old. This one-bar latency is musically natural for slowly-changing state (like a 4-bar bass phrase influencing a 1-bar arp), but use matching lengths when you need immediate reaction.

External data written by `composition.schedule()`, CC input, OSC, or hotkeys flows through the same dict:

```python
import subsequence.constants.midi_notes as notes

def fetch_iss():
    data = requests.get("https://api.wheretheiss.at/v1/satellites/25544").json()
    composition.data["iss_lat"] = data["latitude"]

composition.schedule(fetch_iss, cycle_beats=16, wait_for_initial=True)

@composition.pattern(channel=1)
def iss_melody(p):
    lat = p.data.get("iss_lat", 0.0)   # same dict as composition.data
    root = notes.C3 + int((lat / 90) * 24)  # map latitude to a 2-octave range from C3
    p.note(root, velocity=80)
```

If you use `composition.schedule()` to poll external data and want to ease between each new reading, use **`subsequence.easing.EasedValue`**. Create one instance per field at module level, call `.update(value)` in your scheduled task, and `.get(progress)` in your pattern - no manual `prev`/`current` bookkeeping required. See [`subsequence.easing`](#extra-utilities) for details.

### Chord inversions and voice leading

Most generative tools leave voicing to the user. Subsequence provides automatic voice leading - each chord picks the inversion with the smallest total pitch movement from the previous one, keeping parts smooth without manual effort.

By default, chords are played in root position. You can request a specific inversion, or enable voice leading per pattern.

### Manual inversions

Pass `inversion` to `p.chord()`, `p.strum()`, or `chord.tones()`:

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def chords (p, chord):
    p.chord(chord, root=notes.E3, velocity=90, sustain=True, inversion=1)  # first inversion
```

Inversion 0 is root position, 1 is first inversion, 2 is second, and so on. Values wrap around for chords with fewer notes.

### Strummed chords

`p.strum()` works exactly like `p.chord()` but staggers the notes with a small time offset between each one - like strumming a guitar. The first note always lands on the beat; subsequent notes are delayed by `offset` beats each.

```python
@composition.pattern(channel=1, beats=4)
def guitar (p, chord):
    # Gentle upward strum (low to high)
    p.strum(chord, root=notes.E3, velocity=85, offset=0.06)

    # Fast downward strum (high to low)
    p.strum(chord, root=notes.E3, direction="down", offset=0.03)
```

### Broken chords

`p.broken_chord()` generates the required chord tones and sequences them sequentially according to an `order` map. It delegates internally to `p.arpeggio()`.

```python
@composition.pattern(channel=1, beats=4)
def arp (p, chord):
    # Fixed broken chord order
    p.broken_chord(chord, root=notes.C4, order=[4, 0, 2, 1, 3], spacing=0.25)

    # Or fully randomised broken chords, using the pattern's deterministic RNG
    order = list(range(5))
    p.rng.shuffle(order)
    p.broken_chord(chord, root=notes.C4, order=order, spacing=0.25)
```

### Legato chords

Pass `legato=` directly to `chord()` or `strum()` to collapse the two-step pattern into one call. The value is passed straight to `p.legato()`, stretching each note to fill the given fraction of the gap to the next note:

```python
@composition.pattern(channel=1, beats=4)
def pad (p, chord):
    # Equivalent to: p.chord(...) then p.legato(0.9)
    p.chord(chord, root=notes.E3, velocity=90, legato=0.9)

@composition.pattern(channel=1, beats=4)
def guitar (p, chord):
    p.strum(chord, root=notes.E3, velocity=85, offset=0.06, legato=0.95)
```

`sustain=True` and `legato=` are mutually exclusive - passing both raises a `ValueError`.

### Drones and sustained notes

Unlike `p.note()` which automatically manages duration and Note Off events, `p.drone()` and `p.note_on()` create infinite sustains. These are "raw" events that do not create `Step` entries-they are scheduled directly. This allows you to start a note in one cycle and stop it many bars later.

*   `p.drone(pitch, beat=0.0, velocity=100)`: A musical alias for `p.note_on()`.
*   `p.drone_off(pitch)`: Stops a note started by `p.drone()` (alias for `p.note_off()` at beat 0.0).
*   `p.silence(beat=0.0)`: Sends "All Notes Off" (CC 123) and "All Sound Off" (CC 120) to the pattern's channel.

```python
@composition.pattern(channel=1, beats=16)
def drone_manager (p):
    # Start a drone on the first bar
    if p.bar == 0:
        p.drone(notes.C2, velocity=80)
    
    # Silence it at the end of the 16th bar
    if p.bar == 16:
        p.drone_off(notes.C2)
        # Or p.silence() to clean up everything
```

### Automatic voice leading

Add `voice_leading=True` to the pattern decorator. The injected chord will automatically choose the inversion with the smallest total pitch movement from the previous chord:

```python
@composition.pattern(channel=1, beats=4, voice_leading=True)
def chords (p, chord):
    p.chord(chord, root=notes.E3, velocity=90, sustain=True)
```

Each pattern tracks voice leading independently - a bass line and a pad can voice-lead at their own pace.

**What `chord.tones()` returns with voice leading active:** when `voice_leading=True`, `chord.tones(root=...)` returns the notes of the chosen inversion - the voicing closest to the previous chord - not root position. The `inversion` parameter is ignored; the engine picks the inversion automatically. This matters for arpeggios: if you pass the result of `chord.tones()` to `p.arpeggio()`, the notes will already be in the voice-led order, not ascending from the root.

```python
@composition.pattern(channel=1, beats=4, voice_leading=True, chord=True)
def arp (p, chord):
    # Returns voice-led inversion, not necessarily root position
    tones = chord.tones(root=notes.E3, count=4)
    p.arpeggio(tones, spacing=0.25, velocity=90)
```

If you want root-position notes regardless of voice leading, call `chord.tones()` on the underlying `Chord` object directly from `subsequence.chords` - or sort the tones before passing them to the arpeggio.

### Direct Pattern API

`ChordPattern` accepts `voice_leading=True`:

```python
import subsequence.constants.midi_notes as notes

chords = subsequence.harmony.ChordPattern(
    harmonic_state=harmonic_state, root_midi=notes.E3, velocity=90, channel=0, voice_leading=True
)
```

For standalone use, `subsequence.voicings` provides `invert_chord()`, `voice_lead()`, and `VoiceLeadingState`.

### Extended arpeggios

By default, `chord.tones()` and `p.chord()` return one note per chord tone (3 for triads, 4 for sevenths). Pass `count` to cycle the intervals into higher octaves:

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def pad (p, chord):
    p.chord(chord, root=notes.E3, velocity=90, sustain=True, count=4)  # always 4 notes

@composition.pattern(channel=1, beats=4)
def arp (p, chord):
    tones = chord.tones(root=notes.E4, count=5)  # 5 tones cycling up from E4
    p.arpeggio(tones, spacing=0.25, velocity=90)
```

`count` works with `inversion` - the extended notes continue upward from the inverted voicing.

### Harmony and chord graphs

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
| `gravity` | float | `1.0` | Key gravity blend - how broadly the harmony can roam. `0.0` = stick to functional chords (tonic, dominant, subdominant). `1.0` = any diatonic chord is equally welcome. |
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
import subsequence.harmony

# Seven triads of Eb Major: Eb, Fm, Gm, Ab, Bb, Cm, Ddim
chords = subsequence.harmony.diatonic_chords("Eb")

# Natural minor
chords = subsequence.harmony.diatonic_chords("A", mode="minor")

# Supported modes: "ionian" ("major"), "dorian", "phrygian", "lydian",
#   "mixolydian", "aeolian" ("minor"), "locrian",
#   "harmonic_minor", "melodic_minor"
```

Each entry is a `Chord` object - pass it directly to `p.chord()`, `p.strum()`, or `chord.tones()`:

```python
import subsequence.harmony
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def rising (p):
    current = subsequence.harmony.diatonic_chords("D", mode="dorian")[p.cycle % 7]
    p.chord(current, root=notes.D3, sustain=True)
```

For a **stepped sequence with explicit MIDI roots** - for example, mapping a sensor value to a chord - use `diatonic_chord_sequence()`. It returns `(Chord, midi_root)` tuples stepping diatonically upward from a starting note, wrapping into higher octaves automatically:

```python
import subsequence.harmony
import subsequence.constants.midi_notes as notes

# 12-step D Major ladder from D3 up through D4 and beyond
sequence = subsequence.harmony.diatonic_chord_sequence("D", root_midi=notes.D3, count=12)

# Map a 0-1 value directly to a chord
altitude_ratio = 0.7   # e.g. from ISS data
chord, root = sequence[int(altitude_ratio * (len(sequence) - 1))]
p.chord(chord, root=root, sustain=True)

# Falling sequence - A minor ladder descending from A2
sequence = list(reversed(subsequence.harmony.diatonic_chord_sequence("A", root_midi=notes.A2, count=7, mode="minor")))
```

The `root_midi` must be a note that falls on a scale degree of the chosen key and mode. A `ValueError` is raised otherwise.

### Frozen progressions

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
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=BASS_CHANNEL, beats=4)
def bass (p, chord):
    root = chord.root_note(notes.E2)  # bass register
    p.sequence(steps=[0, 4, 8, 12], pitches=root)
    p.legato(0.9)
```

**Key behaviours:**

- Each time a frozen section is re-entered, playback restarts from chord 0.
- If a section is longer than its progression (more bars than chords), the extra bars fall through to live generation.
- NIR history is restored at the start of each frozen replay so every re-entry begins with the same harmonic context as when the progression was originally generated.
- `freeze()` can be called before or after `form()`.

## 5. Live Performance & Tools

### Seed and deterministic randomness

Set a seed to make all random behavior repeatable:

```python
composition = subsequence.Composition(bpm=125, key="E", seed=42)
# OR
composition.seed(42)
```

When a seed is set, chord progressions, form transitions, and all pattern randomness produce identical output on every run. Pattern builders access the seeded RNG via `p.rng`:

```python
@composition.pattern(channel=10, beats=4, drum_note_map=DRUM_NOTE_MAP)
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
walk = subsequence.sequence_utils.random_walk(16, low=50, high=110, spacing=15, rng=p.rng)
for i, vel in enumerate(walk):
    p.hit_steps("hh_closed", [i], velocity=vel)

# Weighted density choice
density = subsequence.sequence_utils.weighted_choice([(3, 0.5), (5, 0.3), (7, 0.2)], p.rng)
p.euclidean("snare", pulses=density)
```

### Terminal display

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
  kick        |█ ▒ · · █ · · · █ · · · █ · · ▒|
  snare       |· · · · █ · · · · · · · █ · · ·|
  bass        |█ > > █ > > > > █ > > > █ > > ·|
125.00 BPM  Key: E  Bar: 3.1  [intro 3/8 → section_1]
```

Each column is one grid step (16th notes by default). Velocity and duration are encoded in the character at each position:

| Glyph | Meaning |
|-------|---------|
| `·` | Empty step on the grid |
| ` ` | Empty step between grid lines |
| `░` | Ghost attack (velocity < 25%) |
| `▒` | Soft attack (velocity 25% to < 50%) |
| `▓` | Medium attack (velocity 50% to < 75%) |
| `█` | Loud attack (velocity >= 75%) |
| `>` | Sustain (note still sounding from a previous step) |

The sustain marker makes legato and staccato patterns visually distinct - a legato bass line fills its steps with `>` between attacks; drum hits are short and show no sustain. Drum patterns show one row per distinct drum sound, labelled from the drum note map. Pitched patterns show a single summary row.

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

### Web UI Dashboard (Beta)

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

### MIDI recording and rendering

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

@composition.pattern(channel=1, beats=4)
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

### Live coding

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
>>> @composition.pattern(channel=10, beats=4, drum_note_map=DRUM_NOTE_MAP)
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
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def bass (p):
    pitches = p.param("pitches", [notes.C4, notes.E4, notes.G4, notes.C5])  # C major chord
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

### Clock accuracy

Subsequence uses a hybrid sleep+spin timing strategy for its internal master clock. Rather than relying on `asyncio.sleep()` alone (which is subject to OS scheduler granularity), the loop sleeps to within ~1 ms of the target pulse time, then busy-waits on `time.perf_counter()` for the remaining sub-millisecond interval. Pulse times are calculated as absolute offsets from the session start time, so timing errors never accumulate.

**Measured jitter on Linux at 120 BPM (64 bars, 6144 pulses):**

| Mode | Mean | P99 | Max | Long-term drift |
|------|------|-----|-----|-----------------|
| Spin-wait ON (default) | **3 μs** | 4 μs | ~100 μs* | 0 |
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

### MIDI input and external clock

Subsequence can follow an external MIDI clock instead of running its own. This lets you sync with a DAW, drum machine, or any device that sends MIDI clock. Transport messages (start, stop, continue) are respected automatically.

### Enable clock following

```python
MIDI_INPUT_DEVICE = "Your MIDI Device:Port"

composition = subsequence.Composition(bpm=120, key="E")

# Follow external clock and respect transport (start/stop/continue)
composition.midi_input(device=MIDI_INPUT_DEVICE, clock_follow=True)

composition.play()
```

> [!IMPORTANT]
> Only one MIDI input device can be configured to follow the external clock at a time. If you attempt to set `clock_follow=True` on multiple devices, a `ValueError` will be raised.

When `clock_follow=True`:
- The sequencer waits for a MIDI **start** or **continue** message before playing
- Each incoming MIDI **clock** tick advances the sequencer by one pulse (24 ticks = 1 beat, matching the MIDI standard)
- A MIDI **stop** message halts the sequencer
- A MIDI **start** message resets to pulse 0 and begins counting
- A MIDI **continue** message resumes from the current position
- BPM is estimated from incoming tick intervals (for display only), including ticks received before the first start
- `set_bpm()` has no effect - tempo is determined by the external clock

Without `clock_follow` (the default), `midi_input()` opens the input port but does not act on clock or transport messages - it can still receive CC input for mapping (see below).

If you're not sure what your controller or clock source is sending, run `scripts/midi_in_observer.py`. It prompts you to pick a MIDI input device, then prints every incoming message (note/CC/transport) and shows a MIDI clock summary updated every 5 seconds, which is useful for identifying channels and CC numbers before wiring anything into a composition.

### MIDI CC input mapping

Map hardware knobs, faders, and expression pedals directly to `composition.data` - no callback code required:

```python
import subsequence.constants.midi_notes as notes

composition.midi_input("Arturia KeyStep")   # open the input port

If `channel` is omitted, the mapping listens on **all** incoming channels; if provided, only that channel is accepted (using the same numbering convention as `@composition.pattern(channel=...)`).

composition.cc_map(74, "filter_cutoff")          # CC 74 → 0.0–1.0 in composition.data
composition.cc_map(7,  "volume", min_val=0, max_val=127)   # custom range
composition.cc_map(1,  "density", channel=1)     # channel-filtered

@composition.pattern(channel=1, beats=4)
def arps (p):
    cutoff = composition.data.get("filter_cutoff", 0.5)
    velocity = int(60 + 67 * cutoff)
    p.arpeggio([notes.C4, notes.E4, notes.G4], spacing=0.25, velocity=velocity)  # C major triad
```

CC values are scaled from 0–127 to the `min_val`/`max_val` range and written to `composition.data[key]` on every incoming message. Thread safety is provided by Python's GIL for single dict writes.

### Real-time CC forwarding

`cc_map()` makes CC values available to patterns at rebuild time - useful for driving generative parameters. For cases where you need the signal to reach your synth immediately (pitch bend from a mod wheel, cutoff from a fader, expression from a pedal), use `cc_forward()` instead:

```python
composition.midi_input("Arturia KeyStep")

# Forward CC 1 directly to pitch bend on channel 1 - instant, ~1–5 ms latency
composition.cc_forward(1, "pitchwheel", output_channel=1)

# Reroute CC 1 to CC 74 on the same channel
composition.cc_forward(1, "cc:74")

# Custom transform: scale CC 1 range to CC 74 range 40–100
import subsequence.midi as midi
composition.cc_forward(1,
    lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch)
)

# Forward AND map simultaneously - both are active
composition.cc_map(1, "mod_depth")    # value available in patterns via composition.data
composition.cc_forward(1, "cc:74")   # also forwarded in real-time
```

Two dispatch modes:

- **`mode="instant"`** *(default)* - sent immediately on the MIDI input callback thread. Latency is ~1–5 ms (driver round-trip only). Not recorded when recording is enabled.
- **`mode="queued"`** - injected into the sequencer event queue and sent at the next pulse boundary (~0–20 ms at 120 BPM). Properly ordered with note events and **is** recorded when recording is enabled.

Built-in preset strings: `"cc"` (identity), `"cc:N"` (remap to CC N), `"pitchwheel"` (scale to ±8192). Pass a callable for full control over output message type and value scaling.

**Multiple input/output devices** - both `cc_map()` and `cc_forward()` support `input_device=` and `output_device=` parameters for routing between devices:

```python
comp.midi_input("Arturia KeyStep", name="keys")
comp.midi_input("Faderfox EC4", name="faders")    # second call adds an extra input

comp.midi_output("Roland Integra", name="integra")

# Only respond to CC 74 from the fader box
comp.cc_map(74, "filter", input_device="faders")

# Forward mod wheel from the keyboard to pitch bend on the Integra
comp.cc_forward(1, "pitchwheel", input_device="keys", output_device="integra")
```

### MIDI clock output

Make Subsequence the MIDI clock master so hardware can lock to its tempo:

```python
composition = subsequence.Composition(bpm=120, output_device="...")
composition.clock_output()   # send Start, Clock ticks, Stop to the output port
composition.play()
```

Subsequence sends a Start message (0xFA) at the beginning of playback, one Clock tick (0xF8) per pulse (24 PPQN, matching the MIDI standard), and a Stop message (0xFC) when playback ends. This automatically disabled when `midi_input(clock_follow=True)` is active, to prevent a feedback loop.

### Ableton Link

[Ableton Link ↗](https://www.ableton.com/en/link/) is the industry standard for wireless tempo and beat-phase synchronisation - used by 200+ apps including Ableton Live, Reason, and countless iOS synths. When you enable Link in Subsequence, every app on the same LAN locks to the same tempo and phase automatically, with no configuration needed.

Link synchronises three things: tempo, beat phase, and transport start/stop. It does **not** transmit notes or patterns - each participant generates its own music independently, but all pulses stay aligned.

### Installation

Link support is an optional extra that requires the [`aalink` ↗](https://github.com/artfwo/aalink) package:

```
pip install subsequence[link]
```

### Basic usage

```python
import subsequence

comp = subsequence.Composition(bpm=120, key="C")

# Join the Link session. quantum=4.0 means one bar in 4/4 time.
# Playback waits for the next bar boundary before the first note sounds.
comp.link(quantum=4.0)

@comp.pattern(channel=10, beats=4)
def kick(p):
    p.hit(35, beats=[0, 2], velocity=110, duration=0.1)

comp.play()
```

`comp.link()` returns `self` for method chaining. The `quantum` parameter (default 4.0) is the beat cycle length - one bar in 4/4 time. Subsequence will wait for the next quantum boundary before the first note sounds, so it always starts phase-aligned with other Link peers.

`p.hit(pitch, beats, velocity, duration)` places hits at absolute beat positions within the pattern (where `0` is the downbeat, `1` is the second beat, `2` is the third beat, and so on). It is the beat-position counterpart to `p.hit_steps()`, which works in grid step indices (0–15 for a 16-step bar).

### Behaviour

- **Tempo is authoritative from the network.** If another peer changes the tempo, Subsequence picks it up automatically on the next pulse. Calling `set_bpm()` during Link playback proposes a new tempo to the session rather than changing it locally.
- **Bar-aligned start.** `comp.play()` with Link active waits for the next quantum boundary (bar line) before the first note, ensuring clean entry into an existing session.
- **Combined with clock output.** `comp.link()` and `comp.clock_output()` work together - Subsequence syncs its internal clock to the Link session and forwards MIDI clock ticks to downstream hardware at the Link-controlled tempo.

### Syncing multiple Subsequence instances

Run the same script on two machines connected to the same LAN:

```python
import subsequence

comp = subsequence.Composition(bpm=120, key="Am")
comp.link(quantum=4.0)

@comp.pattern(channel=1, beats=8)
def bass(p):
    p.hit(45, beats=[0, 4], velocity=90, duration=0.5)

comp.play()
```

Both instances will lock to each other's tempo and phase within one bar of the first one starting. The faster you call `comp.play()` on each machine, the sooner they'll converge.

See `examples/link_sync.py` for a runnable demo.

### Pattern tools and hardware control

### Program changes

Switch instrument patches mid-pattern with `p.program_change()`:

```python
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def strings (p):
    p.program_change(48)          # String Ensemble 1 (GM #49)
    p.chord(chord, root=notes.C4, velocity=75, sustain=True)
```

Program numbers follow General MIDI (0–127). The message fires at the beat position given by the optional `beat` argument (default 0.0 - the start of the pattern).

#### Bank select

For multi-bank hardware synths (Roland, Yamaha, Korg, etc.), pass `bank_msb` and/or `bank_lsb` to select the bank before the patch change. The two CC messages (CC 0 and CC 32) are sent automatically at the same beat position, in the correct order (CC 0 → CC 32 → program change):

```python
@composition.pattern(channel=1, beats=4)
def synth (p):
    # Roland JV-1080 - bank MSB 81, LSB 0, patch 48
    p.program_change(48, bank_msb=81, bank_lsb=0)
    p.chord(chord, root=notes.C4, velocity=70, sustain=True)
```

Omit either parameter if your synth only uses one bank byte:

```python
p.program_change(12, bank_msb=1)   # MSB only
p.program_change(12, bank_lsb=3)   # LSB only
```

`subsequence.bank_select(bank)` converts an integer bank number (0–16,383) to the `(msb, lsb)` pair - useful when a synth manual lists a single bank number:

```python
msb, lsb = subsequence.bank_select(128)   # → (1, 0)
p.program_change(48, bank_msb=msb, bank_lsb=lsb)
```

#### Section-conditional patch switching

To send a patch change only at the start of a section (not every bar), guard with `p.section.bar`:

```python
@composition.pattern(channel=1)
def synth (p):
    if p.section.bar == 0:             # first bar of this section
        p.program_change(48, bank_msb=81, bank_lsb=0)
    p.chord(chord, root=notes.C4, velocity=70, sustain=True)
```

Or switch patch depending on which section is playing:

```python
@composition.pattern(channel=1)
def lead (p):
    if p.section.name == "verse":
        p.program_change(80)           # Square Lead
    elif p.section.name == "chorus":
        p.program_change(88)           # Fantasia Pad
    p.note(root, velocity=90)
```

### SysEx

Send System Exclusive messages for deep hardware integration - Elektron parameter locking, patch dumps, vendor-specific commands:

```python
@composition.pattern(channel=1, beats=4)
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
import subsequence.constants.midi_notes as notes

# E natural minor bassline fragment: E2 → F#2 → E2 → G2
p.sequence(steps=[0, 4, 8, 12], pitches=[notes.E2, notes.FS2, notes.E2, notes.G2])
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
import subsequence.constants.midi_notes as notes

p.sequence(steps=[0, 4, 8, 12], pitches=[notes.E2, notes.FS2, notes.E2, notes.G2])
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
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=1, beats=4)
def walk (p):
    for beat in range(16):
        pitch = notes.C4 + p.rng.randint(-7, 7)  # random walk around middle C
        p.note(pitch, beat=beat * 0.25)
    p.quantize("G", "dorian")                     # snap everything to G Dorian
```

`quantize(key, mode, strength=1.0)` accepts any key name (`"C"`, `"F#"`, `"Bb"`, etc.) and any registered scale. Equidistant notes prefer the upward direction. The optional `strength` parameter (0.0–1.0) controls how many notes are snapped: `1.0` quantizes everything (default, fully backward compatible), `0.0` leaves all notes untouched, and values in between apply quantization probabilistically - useful for keeping occasional chromatic passing tones.

Built-in modes include western diatonic (`"ionian"`, `"dorian"`, `"minor"`, `"harmonic_minor"`, etc.) and non-western scales (`"hirajoshi"`, `"in_sen"`, `"iwato"`, `"yo"`, `"egyptian"`, `"major_pentatonic"`, `"minor_pentatonic"`).

Register your own scales at any time:

```python
subsequence.register_scale("raga_bhairav", [0, 1, 4, 5, 7, 8, 11])
# then in patterns:
p.quantize("C", "raga_bhairav")
```

### Generating scale note lists

`subsequence.scale_notes(key, mode, low, high)` returns a list of MIDI note numbers for a scale within a pitch range - the musician-friendly alternative to filtering pitch classes by hand:

```python
import subsequence

# C major: all notes from C4 to C5
scale = subsequence.scale_notes("C", "ionian", low=60, high=72)
# → [60, 62, 64, 65, 67, 69, 71, 72]

# E natural minor: one octave from E2 to E3
scale = subsequence.scale_notes("E", "aeolian", low=40, high=52)
# → [40, 42, 43, 45, 47, 48, 50, 52]

# A minor pentatonic: exactly 15 notes ascending from A3
scale = subsequence.scale_notes("A", "minor_pentatonic", low=57, count=15)
# → 15 notes cycling into higher octaves as needed
```

Pass the result directly to `p.markov()`, `p.self_avoiding_walk()`, `p.de_bruijn()`, or any other method that takes a pitch list. Works with all built-in modes and custom scales registered via `register_scale()`.

| Parameter | Description |
|-----------|-------------|
| `key` | Root note name: `"C"`, `"F#"`, `"Bb"`, etc. |
| `mode` | Scale mode: `"ionian"`, `"aeolian"`, `"dorian"`, `"major_pentatonic"`, etc. |
| `low` | Lowest MIDI note to include (inclusive). Defaults to 60 (C4). |
| `high` | Highest MIDI note (inclusive). Defaults to 72 (C5). Ignored when `count` is set. |
| `count` | Return exactly this many notes, ascending from `low` through successive octaves. |

### Evolving loops - `p.evolve()`

`p.evolve()` loops a pitch sequence that gradually mutates each cycle. On cycle 0 the buffer is locked to the seed. Each subsequent cycle, every step has a `drift` probability of being replaced by a value drawn from the pool. At `drift=0.0` the loop never changes; at `drift=1.0` every step is redrawn on every cycle.

State is stored in `p.data` and resets when `cycle == 0`, so restarts are always deterministic. Combine with `p.quantize()` to keep drifted pitches in key.

```python
@composition.pattern(channel=1, beats=4)
def melody (p):
    p.evolve(
        pitches=[60, 62, 64, 67],   # seed sequence and mutation pool
        steps=8,                     # loop length (cycles the seed if shorter)
        drift=0.08,                  # 8% chance each step mutates per cycle
        velocity=(70, 100),
        duration=0.3,
        spacing=0.5,
    )
    p.quantize("C", "minor")        # keep mutations in key
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pitches` | - | Seed sequence. Initial buffer and mutation pool. |
| `steps` | `len(pitches)` | Loop length. Cycles the seed if `steps > len(pitches)`. |
| `drift` | `0.0` | Per-step mutation probability per cycle (0.0 = locked, 1.0 = fully random). |
| `velocity` | `80` | MIDI velocity, or `(low, high)` tuple for per-step random range. |
| `duration` | `0.2` | Note duration in beats. |
| `spacing` | `0.25` | Beat interval between steps. |

### Fractal sequence variation - `p.branch()`

`p.branch()` generates a melodic variation by navigating a binary tree of deterministic transforms applied to a seed sequence. The tree structure is seeded by the sequence content itself, so the same seed always produces the same tree. `path=p.cycle` steps through all `2 ** depth` unique variations in order, wrapping automatically.

**Transforms** (assigned deterministically per level): retrograde, invert (mirror around root), transpose (by seed interval), rotate (shift start point), compress intervals (×0.5), expand intervals (×2.0).

```python
@composition.pattern(channel=1, beats=4)
def melody (p):
    p.branch(
        seed=[60, 64, 67, 72],   # the trunk - original motif
        depth=3,                  # 2^3 = 8 unique variations
        path=p.cycle,             # advance through the tree each bar
        mutation=0.05,            # small random substitution on top
        velocity=85,
        spacing=0.5,
    )
    p.quantize("C", "minor")
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `seed` | - | Original pitch sequence. All variations are derived from this. |
| `depth` | `2` | Branching levels. `2 ** depth` unique variations available. |
| `path` | `0` | Which variation to play. `path=p.cycle` auto-advances. Wraps modulo `2 ** depth`. |
| `mutation` | `0.0` | Probability of random substitution from `seed` pool after branching. |
| `velocity` | `80` | MIDI velocity, or `(low, high)` tuple. |
| `duration` | `0.2` | Note duration in beats. |
| `spacing` | `0.25` | Beat interval between steps. |

### Microtonal tuning - `composition.tuning()` and `p.apply_tuning()`

Subsequence supports alternative tuning systems beyond standard 12-TET by injecting per-note pitch bend events automatically. Any MIDI-compatible synthesiser can play microtonal music without MPE or special hardware: one pitch bend per note, inserted just before each note-on.

#### Setting a global tuning

```python
import subsequence
from subsequence.tuning import Tuning

# From a Scala .scl file
comp.tuning("meanquar.scl", bend_range=2.0)

# From a list of cent values
comp.tuning(cents=[76.05, 193.16, 310.26, 386.31, 503.42, 579.47,
                    696.58, 813.69, 889.74, 1006.84, 1082.89, 1200.0])

# From frequency ratios
comp.tuning(ratios=[9/8, 5/4, 4/3, 3/2, 5/3, 15/8, 2.0])

# N-tone equal temperament
comp.tuning(equal=19)              # 19-TET
comp.tuning(equal=31, bend_range=4.0)
```

`composition.tuning()` applies the tuning to every pattern automatically on each rebuild. Drum patterns (with `drum_note_map=`) are excluded by default.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `source` | `None` | Path to a Scala `.scl` file. |
| `cents` | `None` | List of cent values for degrees 1…N (degree 0 = unison implicit). |
| `ratios` | `None` | List of frequency ratios; each converted via `1200 × log₂(ratio)`. |
| `equal` | `None` | Integer N for N-tone equal temperament. |
| `bend_range` | `2.0` | Synth pitch-bend range in semitones - must match your synthesiser setting. |
| `channels` | `None` | Channel pool for polyphonic parts (see below). |
| `reference_note` | `60` | MIDI note mapped to scale degree 0 (C4 by default). |
| `exclude_drums` | `True` | Skip patterns with a `drum_note_map`. |

#### Per-pattern override

```python
@comp.pattern(channel=1, beats=4)
def lead (p):
    t = Tuning.equal(19)           # 19-TET just for this voice
    p.apply_tuning(t, bend_range=2.0)
    p.sequence(steps=range(4), pitches=[60, 62, 64, 67])
```

`p.apply_tuning()` marks the pattern so the global tuning is not double-applied.

#### Polyphonic parts and channel rotation

MIDI pitch bend is channel-wide: a single bend event affects every sounding note on that channel. For polyphonic parts with simultaneous notes you need a separate channel per voice. Pass a `channels` pool and Subsequence allocates channels automatically:

```python
comp.tuning("meanquar.scl", bend_range=2.0, channels=[1, 2, 3, 4])

@comp.pattern(channel=1, beats=4)
def chords (p, chord):
    # Four simultaneous notes → each gets its own channel from [1, 2, 3, 4]
    p.chord(chord, root=60, count=4, velocity=80)
```

For monophonic lines no `channels` pool is needed - all notes stay on the pattern's channel.

#### Pitch-bend range

The default `bend_range=2.0` (±2 semitones) matches most synthesiser factory presets. For tunings with large deviations from 12-TET (e.g., Bohlen–Pierce) set `bend_range` to `12` or `24` and configure your synth to match. The bend_range on the call to `composition.tuning()` and the synth's setting must always agree.

#### The `Tuning` class

```python
from subsequence.tuning import Tuning

t = Tuning.from_scl("meanquar.scl")     # Scala .scl file
t = Tuning.from_scl_string(scl_text)    # .scl content as a string
t = Tuning.from_cents([100, 200, ..., 1200])
t = Tuning.from_ratios([9/8, 5/4, 4/3, 3/2, 5/3, 15/8, 2.0])
t = Tuning.equal(19)                     # 19-TET

nearest, bend = t.pitch_bend_for_note(64, reference_note=60, bend_range=2.0)
# Returns (nearest_12tet_midi_note, bend_normalized_-1_to_+1)
```

`Tuning` is also exported as `subsequence.Tuning`.

### Chord root and bass helpers

`chord.root_note(midi)` and `chord.bass_note(midi, octave_offset=-1)` make register-aware root extraction self-documenting:

```python
@composition.pattern(channel=BASS_CHANNEL, beats=4)
def bass (p, chord):
    bass_root = chord.bass_note(root, octave_offset=-1)   # one octave below chord voicing
    p.sequence(steps=range(0, 16, 2), pitches=bass_root)
    p.legato(0.9)
```

### Arpeggio directions

`p.arpeggio()` now supports four playback directions:

```python
import subsequence.constants.midi_notes as notes

chord = [notes.C4, notes.E4, notes.G4]  # C major triad
p.arpeggio(chord, spacing=0.25)                     # "up" (default): C E G C E G …
p.arpeggio(chord, spacing=0.25, direction="down")    # descend: G E C G E C …
p.arpeggio(chord, spacing=0.25, direction="up_down") # ping-pong: C E G E C E …
p.arpeggio(chord, spacing=0.25, direction="random")  # shuffled once per call
```

The `"random"` direction uses `p.rng` by default (deterministic when a seed is set). Pass a custom `rng` for independent streams.

### OSC integration

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

Custom handlers can be registered via `composition.osc_map(address, handler)`:

```python
def on_intensity (address, value):
    composition.data["intensity"] = float(value)

composition.osc_map("/intensity", on_intensity)
```

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

@composition.pattern(channel=1, beats=4)
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

### Hotkeys

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

### Real-Time Pattern Triggering

Trigger one-shot patterns in response to external events - sensor readings, OSC messages, MIDI input, or any Python callback. Triggered patterns are one-off generators built and scheduled immediately, useful for fills, stabs, or responsive accompaniment that adapts to live input.

```python
import subsequence.constants.durations as dur
import subsequence.constants.midi_notes as notes

@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)

# Trigger a one-shot snare fill immediately
composition.trigger(
    lambda p: p.euclidean("snare_1", pulses=7, velocity=90),
    channel=10,
    drum_note_map=gm_drums.GM_DRUM_MAP
)

# Quantized to next bar boundary
composition.trigger(
    lambda p: p.euclidean("snare_1", pulses=7, velocity=90),
    channel=10,
    drum_note_map=gm_drums.GM_DRUM_MAP,
    quantize=dur.WHOLE  # snap to next bar
)

# With chord context (if harmony is active)
composition.trigger(
    lambda p: p.arpeggio(p.chord.tones(root=notes.C4), spacing=dur.SIXTEENTH),
    channel=1,
    quantize=dur.WHOLE,
    chord=True  # inject current chord
)
```

Triggered patterns use the same `PatternBuilder` API as `@composition.pattern` decorated patterns - all rhythm and melody methods work (`p.euclidean()`, `p.arpeggio()`, `p.note()`, method chaining, etc.). The builder function runs immediately; the generated MIDI is queued at the specified pulse boundary:

- `quantize=0` (default) - schedule at the next available pulse
- `quantize=dur.QUARTER` - snap to next beat
- `quantize=dur.WHOLE` - snap to next bar
- `quantize=dur.SIXTEENTH` - snap to next 16th note
- Any float in beats works directly

### `composition.trigger(fn, channel, beats=1, bars=None, steps=None, unit=None, quantize=0, drum_note_map=None, chord=False)`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fn` | - | Builder function (same API as `@composition.pattern`) |
| `channel` | - | MIDI channel (1-16 by default, or 0-15 with `zero_indexed_channels=True`) |
| `beats` | `1` | Duration in beats (quarter notes). |
| `bars` | `None` | Duration in bars (4 beats, assumes 4/4). Alternative to `beats=`. |
| `steps` | `None` | Step count for step mode. Requires `unit=`. |
| `unit` | `None` | Duration of one step in beats (e.g. `dur.SIXTEENTH`). Requires `steps=`. |
| `quantize` | `0` | Snap to beat boundary: `0` = immediate, or a float in beats (use `dur.*` constants) |
| `drum_note_map` | `None` | Optional drum name mapping |
| `chord` | `False` | If `True`, the builder receives the current chord as a second parameter |

Triggered patterns are thread-safe - call from OSC handlers, scheduled callbacks, or custom threads. If playback hasn't started yet (before `play()` is called), `trigger()` is a no-op and logs a warning.

### `composition.layer(*builder_fns, channel, beats=4, bars=None, steps=None, unit=None, drum_note_map=None, reschedule_lookahead=1, voice_leading=False)`

Merge multiple builder functions into a single pattern. Each function receives its own `PatternBuilder` and their notes are combined into one MIDI stream. Use this to decompose a complex pattern into reusable parts:

```python
def kick(p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)

def snare(p):
    p.hit_steps("snare_1", [4, 12], velocity=90)

def hats(p):
    p.euclidean("hi_hat_closed", pulses=9, velocity=70)

composition.layer(kick, snare, hats, channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
```

All three functions run on the same cycle length and MIDI channel - equivalent to putting everything in one function, but easier to swap pieces in and out. The `beats=`, `bars=`, `steps=`, and `unit=` parameters work identically to `@composition.pattern`.

### Polyrhythms

To run patterns at different cycle lengths on the same channel, register them as separate top-level patterns. They will run independently and overlap naturally:

```python
# 4-beat kick/snare
@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
    p.hit_steps("snare_1", [4, 12], velocity=90)

# 3-beat hat cycle - creates a 12-beat polyrhythm against the 4-beat drums
@composition.pattern(channel=10, beats=3, drum_note_map=gm_drums.GM_DRUM_MAP)
def hats(p):
    p.euclidean("hi_hat_closed", pulses=5, velocity=70)
```

The patterns share the same MIDI channel and their note events are merged by the sequencer. The combined cycle repeats every LCM(4, 3) = 12 beats.

> **Note on nesting decorators**: It is syntactically possible to place a `@composition.pattern()` decorator inside another pattern's builder function. This works on startup (the nested pattern is registered during the first build), but is not recommended - the nested pattern accumulates duplicate registrations on each rebuild, and its `p.rng` will be `None`, causing crashes in any method that uses randomness. Use separate top-level patterns instead.

### Groove

A groove is a repeating pattern of per-step timing offsets and optional velocity adjustments that gives a pattern its characteristic rhythmic feel. **Swing is a type of groove** - the simplest one, where every other grid note is delayed. More complex grooves shift and accent every step independently, giving you MPC-style pocket, jazz brush feel, or any custom texture.

### Simple swing: `p.swing()`

For the common case of uniform eighth- or sixteenth-note swing, use the shortcut:

```python
@composition.pattern(channel=10, beats=4)
def drums(p):
    p.hit_steps("kick", [0, 8], velocity=100)
    p.hit_steps("hi_hat", range(16), velocity=80)
    p.swing(57)  # 57% = gentle 16th-note shuffle (Ableton default)
```

| Amount | Feel |
|--------|------|
| `50` | Perfectly straight - no swing |
| `57` | Gentle shuffle (Ableton default) |
| `67` | Classic triplet swing |
| `75` | Heavy, almost dotted-eighth feel |

The optional second argument sets the grid: `p.swing(57, grid=0.5)` swings 8th notes instead of 16ths.

### Groove templates: `p.groove()`

For full control - different timing per step, per-step velocity accents, or a shape loaded from a file - construct a `Groove` and apply it:

```python
import subsequence

# Swing from a percentage (identical to p.swing(57), exposed as a Groove object)
groove = subsequence.Groove.swing(percent=57)

# Import from an Ableton .agr file
groove = subsequence.Groove.from_agr("path/to/Swing 16ths 57.agr")

# Fully custom groove - per-step timing and velocity accents
groove = subsequence.Groove(
    grid=0.25,                                # 16th-note grid
    offsets=[0.0, +0.02, 0.0, -0.01],         # timing shift per slot (beats)
    velocities=[1.0, 0.7, 0.9, 0.6],          # velocity scale per slot
)

@composition.pattern(channel=10, beats=4)
def drums(p):
    p.hit_steps("kick", [0, 8], velocity=100)
    p.hit_steps("hi_hat", range(16), velocity=80)
    p.groove(groove)
```

`p.groove()` is a post-build transform - call it at the end of your builder function after all notes are placed. The offset list repeats cyclically, so a 2-slot swing pattern covers the whole bar. Groove and `p.randomize()` pair well: apply the groove first for structured feel, then randomize on top for micro-variation.

Both `p.groove()` and `p.swing()` accept a `strength` parameter (0.0-1.0, default 1.0) that blends the groove's timing offsets and velocity deviation proportionally - equivalent to Ableton's TimingAmount and VelocityAmount dials:

```python
p.groove(groove)               # full groove
p.groove(groove, strength=0.5) # half-strength - subtler feel
p.swing(57, strength=0.7)      # 70% of 57% swing
```

### Ableton `.agr` import

`Groove.from_agr(path)` reads the note timing and velocity data from the embedded MIDI clip inside the `.agr` file:

- **Extracted:** note start positions → per-step timing offsets; note velocities → velocity scaling (normalised to the loudest note in the file); `TimingAmount` and `VelocityAmount` from the Groove Pool section → pre-scale offsets and velocity deviation so the returned `Groove` reflects the file author's intended strength.
- **Not imported:** `RandomAmount` (use `p.randomize()` separately for random timing jitter) and `QuantizationAmount` (not applicable - Subsequence notes are already grid-quantized by construction). Other per-note fields (`Duration`, `VelocityDeviation`, `OffVelocity`, `Probability`) are also ignored.

For a simple swing file like Ableton's built-in "Swing 16ths 57", `from_agr()` and `Groove.swing(57)` produce equivalent results. Use `strength=` when applying to further dial back the effect.

## 6. Workflow & Utilities

### Examples

The `examples/` directory contains self-documenting compositions, each demonstrating a different style and set of features. Because Subsequence generates pure MIDI, what you hear depends on your choice of instruments - the same code can drive a hardware monosynth, a VST orchestra, or anything in between.

If you want to dive in with two fully documented compositions, start with the instrument emulations below - they exercise most of the API in a real-world context. The simpler examples that follow build up the concepts one at a time.

```
python examples/demo.py
```

### Instrument emulations (`examples/labyrinth.py` and `examples/subharmonicon.py`)

Recreations of the compositional architecture of two Moog semi-modular synthesizers (which the author of this package owns and loves!) - every panel control is exposed as a named Python variable you can tweak. These are best-effort emulations of each instrument's *sequencing and composition* behaviour; the tonal character of the output depends entirely on the instruments you route MIDI to.

**[Moog Labyrinth ↗](https://www.moogmusic.com/synthesizers/labyrinth/)** - dual 8-step generative sequencers with per-step random pitch (quantized to a chosen scale), a CORRUPT knob that mutates patterns from subtle pitch drift to full rhythmic chaos, and an EG TRIG MIX crossfader that balances the two sequences. Independent cycle lengths create evolving polymetric interplay.

**[Moog Subharmonicon ↗](https://www.moogmusic.com/synthesizers/subharmonicon/)** - dual 4-step deterministic sequencers with subharmonic oscillators (integer pitch division ÷1–÷16) and four polyrhythmic clock dividers routed freely between the two sequencers. Complex rhythmic patterns emerge from simple integer arithmetic - no randomness involved.

Both examples include optional physical controller mapping via `cc_map()` - connect a MIDI controller and map its knobs to the same parameters you see on screen.

### Demo (`examples/demo.py` and `examples/demo_advanced.py`)

Drums, bass, and an ascending arpeggio over evolving aeolian minor harmony in E. `demo.py` uses the Composition API (decorated functions); `demo_advanced.py` uses the Direct Pattern API (Pattern subclasses with async lifecycle). Compare them side by side to see how the two APIs relate.

### Arpeggiator (`examples/arpeggiator.py`)

A more complete composition with form sections (intro → section_1 ↔ section_2), five patterns (drums, bass, arp, lead), cycle-dependent variation, and Phrygian minor harmony. Demonstrates `velocity_shape`, `legato`, non-quarter-note grids, and section-aware muting.

### Bresenham builds (`examples/bresenham_poly.py`)

Dense generative drums demonstrating `composition.form()` with a weighted graph that cycles through four sections infinitely (pulse → emerge → peak → dissolve). Each section has its own sonic character from bar one. Uses `ghost_fill()` for probability-biased ghost note layers, `cellular_1d()` for evolving cellular-automaton rhythms (Rules 30 and 90), `bresenham_poly()` for interlocking multi-voice hat patterns, and `perlin_1d()` / `perlin_2d()` for smooth organic parameter wandering. The weighted graph means the journey through sections is never quite the same twice. Channel 10 (MIDI 11), GM drum map.

### Emergence (`examples/emergence.py`)

A six-section generative drum composition that breathes, builds, and breaks. Six independent Perlin noise fields wander at prime-ish speeds - because `p.cycle` increments forever, every pass through the form samples a fresh region of each field, so no two bars are ever the same. The weighted graph usually flows void → pulse → swarm → fury → dissolve → void, but a rare "fracture" section can erupt from swarm or fury, lasting only 4 bars of controlled rhythmic chaos before scattering to dissolve, pulse, or void. A "lightning" event fires when the chaos Perlin peaks above 0.92 - roughly once every 70–80 bars. Uses the full rhythm toolkit: `cellular_1d()` (Rules 30, 90, and 110), `ghost_fill()` with multiple bias modes (`'sixteenths'`, `'offbeat'`, `'before'`, `'uniform'`), `bresenham_poly()`, `euclidean()` with Perlin-driven pulse counts in fracture, and transition-aware fills when `p.section.next_section` is known. Channel 10 (MIDI 11), GM drum map, 132 BPM.

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

### Extra utilities

### Rhythm & Pattern
- `subsequence.pattern_builder` provides the `PatternBuilder` with high-level musical methods.
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.groove` provides `Groove` templates (per-step timing/velocity feel). Swing is a type of groove - `p.swing(amount)` is a shortcut for the common case. For full control: `Groove.swing(percent)` for percentage-based swing; `Groove.from_agr(path)` to import timing and velocity from an Ableton `.agr` file (note: the Groove Pool blend controls in the file are not imported - use `strength=` when applying to partially blend the effect); or construct `Groove(offsets=..., velocities=...)` directly for a custom feel. Applied via `p.groove(template, strength=1.0)` - `strength` (0.0-1.0) blends the groove's timing and velocity proportionally, equivalent to Ableton's TimingAmount and VelocityAmount dials.
- `subsequence.sequence_utils` provides the low-level functions underlying the [Algorithmic generators](#algorithmic-generators): `perlin_1d(x, seed)`, `perlin_2d(x, y, seed)`, `perlin_1d_sequence(start, step, count, seed)`, `logistic_map(r, steps, x0=0.5)`, `pink_noise(steps, sources=16, seed=0)`, `generate_euclidean_sequence(steps, pulses)`, `generate_bresenham_sequence(steps, pulses)`, `generate_bresenham_sequence_weighted(parts, steps)` (underlies `p.bresenham_poly()` - pass a `parts` dict of pitch→weight and voices interlock with optional `no_overlap`), `generate_cellular_automaton_1d(steps, rule, generation, seed)`, `generate_cellular_automaton_2d(rows, cols, rule, generation, seed, density)`, `lsystem_expand(axiom, rules, generations, rng=None)`, `thue_morse(n)`, `de_bruijn(k, n)`, `fibonacci_rhythm(steps, length)`, `lorenz_attractor(steps, ...)`, `reaction_diffusion_1d(width, steps, feed_rate, kill_rate)`, `self_avoiding_walk(n, low, high, rng)`. Also provides probability gating (`probability_gate`), random walk (`random_walk`), weighted choice (`weighted_choice`), and scale/clamp helpers.
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
- `subsequence.constants.instruments.gm_instruments` provides all 128 General MIDI Level 1 instrument program numbers. `GM_INSTRUMENT_MAP` for string lookup, `GM_INSTRUMENT_NAMES` for display, `GM_FAMILIES` for family ranges, and individual constants like `VIOLIN`, `FLUTE`, etc.
- `subsequence.constants.midi_notes` provides named MIDI note constants C_NEG1–G9 (MIDI 0–127). Import as `import subsequence.constants.midi_notes as notes`. Convention: `C4 = 60` (Middle C, MMA standard). Naturals: `C4`, `D4`, … `B4`. Sharps: `CS4` (C♯4), `DS4`, `FS4`, `GS4`, `AS4`. Also provides `note_to_name(60) → "C4"` and `name_to_note("Db4") → 61`. Use instead of raw integers: `root = notes.E2` (40), `p.note(notes.A4)` (69).
- `subsequence.constants.instruments.gm_cc` provides named MIDI CC constants (0–127). Import as `import subsequence.constants.instruments.gm_cc as gm_cc`. Constants: `FILTER_CUTOFF` (74), `SUSTAIN_PEDAL` (64), `MODULATION_WHEEL` (1), `VOLUME` (7), `PAN` (10), `ALL_NOTES_OFF` (123), etc. `GM_CC_MAP` dict for string lookup — pass to `cc_name_map=` on `@composition.pattern()` to enable string-based CC names in `p.cc()` and `p.cc_ramp()`.
- `subsequence.constants.pulses` provides pulse-based MIDI timing constants used internally by the engine.

### Infrastructure
- `subsequence.composition` provides the `Composition` class and internal scheduling helpers.
- `subsequence.event_emitter` supports sync/async events used by the sequencer.
- `subsequence.osc` provides the OSC server/client for bi-directional communication. Receiving: `/bpm`, `/mute`, `/unmute`, `/data`. Status broadcasting: `/bar`, `/bpm`, `/chord`, `/section`. Pattern output: `p.osc()`, `p.osc_ramp()`.
- `subsequence.live_server` provides the TCP eval server for live coding. Started internally by `composition.live()`.
- `subsequence.live_client` provides the interactive REPL client. Run with `python -m subsequence.live_client`.

## 7. Project Info

### Feature Roadmap

Planned features, roughly in order of priority.

### High priority

- **Comprehensive Cookbook and Tutorials.** A guided, progressive walkthrough that takes a new user from zero to an evolving composition in 15 minutes, alongside bite-sized, copy-paste recipes for common musical requests (e.g., "generative techno kick", "functional bassline").

- **Example library.** More short, self-contained compositions in different styles - minimal techno, ambient generative, polyrhythmic exploration, data-driven. Each example should demonstrate 2-3 features and fit on one screen.

### Medium priority

- **MIDI File Import & Analysis.** Allow users to load existing `.mid` files and extract their rhythmic or harmonic content to feed into Subsequence algorithms (e.g., generating Markov chains trained on a Bach invention MIDI file).

- **Visual Dashboard / Web UI.** A lightweight local web dashboard to provide real-time visual feedback of the current Chord Graph, global Conductor signals, and active patterns.

- **Starter templates.** Ready-made starting points for common genres to provide a foundation for new compositions.

- **Network sync.** Share conductor signals, chord progressions, and composition data between multiple Subsequence instances - each generates its own patterns locally from shared musical context. (Tempo sync is already handled by [Ableton Link](#ableton-link).)

### Future ideas

- **Standalone Raspberry Pi mode.** Run Subsequence headlessly on a Raspberry Pi with a small touchscreen - turning it into a dedicated hardware sequencer with no desktop environment required.

- **Performance profiling.** Optional debug mode logging timing per `on_reschedule()` call, helping identify pattern logic that may cause jitter under load.

- **Live coding UX improvements.** Richer feedback in the live client - syntax highlighting, error display, undo/history for hot-swapped patterns. Explore integration with editors (VS Code extension, Jupyter notebooks).

- **CV/Gate output.** Direct control voltage output for modular synthesisers via supported hardware interfaces.

### Tests
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

### Community and Feedback

All feedback and suggestions will be gratefully received! Please use these channels:

* [Discussions](https://github.com/simonholliday/subsequence/discussions): The best place to ask questions and share ideas.
* [Issues](https://github.com/simonholliday/subsequence/issues): If you ran into a bug, or have a specific feature request for the codebase, please open an Issue here.

### Related Projects

- **[Subsample ↗](https://github.com/simonholliday/subsample)** — A sister project by the same author: live sampler, automatic drum-kit builder, and MIDI sample instrument. Point a microphone at the world (or feed in recordings and sample packs) and Subsample captures, analyses, and maps every sound into a playable instrument automatically. Connect to Subsequence via a [virtual MIDI port](#virtual-midi) or standard MIDI hardware; enable [OSC](#osc-integration) on both sides for richer event communication (sample-captured notifications, density changes, visualiser data).

### Dependencies and Credits

Subsequence makes use of these excellent open-source libraries:

| Library | Purpose | License |
|---------|---------|---------|
| [mido ↗](https://github.com/mido/mido) | MIDI message handling and file I/O | MIT |
| [python-rtmidi ↗](https://github.com/SpotlightKid/python-rtmidi) | Real-time MIDI I/O | MIT |
| [python-osc ↗](https://github.com/attwad/python-osc) | OSC protocol support | Unlicense |
| [pymididefs ↗](https://github.com/simonholliday/PyMidiDefs) | Canonical MIDI 1.0/2.0 constant definitions | MIT |
| [websockets ↗](https://github.com/python-websockets/websockets) | Web UI dashboard communication | BSD-3-Clause |
| [aalink ↗](https://github.com/artfwo/aalink) *(optional)* | Ableton Link integration | GPL-3.0 |

[Ableton Link ↗](https://www.ableton.com/en/link/) is a technology by Ableton AG. The `aalink` Python wrapper is written by Artem Popov and is licensed under GPL-3.0, which is compatible with Subsequence's AGPL-3.0 license.

### About the Author

Subsequence was created by me, Simon Holliday ([simonholliday.com ↗](https://simonholliday.com/)), a senior technologist and a junior (but trying) musician. From running an electronic music label in the 2000s to prototyping new passive SONAR techniques for defence research, my work has often explored the intersection of code and sound.

Subsequence was iterated over a series of separate proof-of-concept projects during 2025, and pulled together into this new codebase in Spring 2026.

### License

Subsequence is released under the [GNU Affero General Public License v3.0](LICENSE) (AGPLv3).

You are free to use, modify, and distribute this software under the terms of the AGPL. If you run a modified version of Subsequence as part of a network service, you must make the source code available to its users.

Subsequence's core dependencies (mido, python-rtmidi, python-osc, websockets) are all permissively licensed (MIT, Unlicense, BSD-3-Clause). The optional Ableton Link integration uses `aalink` (GPL-3.0), which is compatible with Subsequence's AGPL-3.0 license.

### Commercial licensing

If you wish to use Subsequence in a proprietary or closed-source product without the obligations of the AGPL, please contact [simon.holliday@protonmail.com] to discuss a commercial license.
