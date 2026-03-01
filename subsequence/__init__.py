
"""
Subsequence - a stateful algorithmic MIDI sequencer for Python.

Unlike stateless sequencers that loop forever, Subsequence rebuilds each
pattern before it plays - giving it access to the current chord, section,
cycle count, external data, and anything else in scope. This makes
compositions that evolve over time as natural to write as static loops.
It generates pure MIDI (no audio engine) to control hardware synths,
modular gear, drum machines, or software VSTs/DAWs.

What makes it different:

- **Stateful patterns that evolve.** Each pattern is a Python function
  rebuilt fresh every cycle with full context - current chord, section,
  cycle count, external data. Patterns remember what happened last bar
  and decide what to do next.
- **Cognitive harmony engine.** Chord progressions evolve via weighted
  transition graphs with adjustable gravity and Narmour-based melodic
  inertia. Eleven built-in palettes, automatic voice leading, and frozen
  progressions to lock some sections while others evolve freely.
- **Sub-microsecond clock.** Hybrid sleep+spin timing achieves typical
  pulse jitter of < 5 us on Linux, with zero long-term drift.
- **Turn anything into music.** ``composition.schedule()`` runs any
  Python function on a beat cycle - APIs, sensors, files. Anything
  Python can reach becomes a musical parameter.
- **Pure MIDI, zero sound engine.** No audio synthesis, no heavyweight
  dependencies. Route to hardware synths, drum machines, Eurorack, or
  software instruments.

Composition tools:

- **Rhythm and feel.** Euclidean and Bresenham generators, multi-voice
  weighted Bresenham distribution (``bresenham_poly()``), ghost note
  layers (``ghost_fill()``), evolving cellular-automaton rhythms
  (``cellular()``), smooth Perlin noise (``perlin_1d()``, ``perlin_2d()``), deterministic
  chaos sequences (``logistic_map()``), Markov-chain generation
  (``p.markov()``), groove templates (``Groove.swing()``,
  ``Groove.from_agr()``), swing, humanize, velocity shaping, dropout,
  per-step probability, and polyrhythms via independent pattern lengths.
- **Melody generation.** ``p.melody()`` with ``MelodicState`` applies
  the Narmour Implication-Realization model to single-note lines:
  continuation after small steps, reversal after large leaps, chord-tone
  weighting, range gravity, and pitch-diversity penalty.  History persists
  across bar rebuilds for natural phrase continuity.
- **Expression.** CC messages/ramps, pitch bend, note-correlated
  bend/portamento/slide, program changes, SysEx, and OSC output - all
  from within patterns.
- **Form and structure.** Song form as a weighted graph, ordered list,
  or generator. Patterns read ``p.section`` to adapt. Conductor signals
  (LFOs, ramps) shape intensity over time.
- **Mini-notation.** ``p.seq("x x [x x] x", pitch="kick")`` - concise
  string syntax for rhythms, subdivisions, and per-step probability.
- **Scales and quantization.** ``p.quantize()`` snaps notes to any
  scale. Built-in western and non-western modes, plus
  ``register_scale()`` for your own.
- **Randomness tools.** Weighted choice, no-repeat shuffle, random
  walk, probability gates. Deterministic seeding (``seed=42``) makes
  every decision repeatable.
- **Pattern transforms.** Legato, staccato, reverse, double/half-time,
  shift, transpose, invert, humanize, and conditional ``p.every()``.

Integration:

- **MIDI clock.** Master (``clock_output()``) or follower
  (``clock_follow=True``). Sync to a DAW or drive hardware.
- **Hardware control.** CC input mapping from knobs/faders to
  ``composition.data``. OSC for bidirectional communication with
  mixers, lighting, visuals.
- **Live coding.** Hot-swap patterns, change tempo, mute/unmute, and
  tweak parameters during playback via a built-in TCP eval server.
- **Hotkeys.** Single keystrokes to jump sections, toggle mutes, or
  fire any action - with optional bar-boundary quantization.
- **Terminal display.** Live status line (BPM, bar, section, chord).
  Add ``grid=True`` for an ASCII pattern grid showing velocity and
  sustain - makes legato and staccato visually distinct at a glance.
  Add ``grid_scale=2`` to zoom in horizontally, revealing swing and
  groove micro-timing.
- **Web UI Dashboard (Beta).** Enable with ``composition.web_ui()`` to 
  broadcast live composition metadata and visualize piano-roll pattern 
  grids in a reactive HTTP/WebSocket browser dashboard.
- **Recording.** Record to standard MIDI file. Render to file without
  waiting for real-time playback.

Minimal example:

    ```python
    import subsequence
    import subsequence.constants.instruments.gm_drums as gm_drums

    comp = subsequence.Composition(bpm=120, key="Cm")

    @comp.pattern(channel=0, drum_note_map=gm_drums.GM_DRUM_MAP)
    def drums (p):
        p.seq("x ~ x ~", pitch="kick_1", velocity=100)
        p.seq("~ x ~ x", pitch="snare_1", velocity=90)
        p.seq("[x x] [x x] [x x] [x x]", pitch="hi_hat_closed", velocity=70)

    comp.play()
    ```

Community and Feedback:

- **Discussions:** Chat and ask questions at https://github.com/simonholliday/subsequence/discussions
- **Issues:** Report bugs and request features at https://github.com/simonholliday/subsequence/issues

Package-level exports: ``Composition``, ``Groove``, ``MelodicState``, ``register_scale``.
"""

import subsequence.composition
import subsequence.groove
import subsequence.intervals
import subsequence.melodic_state


Composition = subsequence.composition.Composition
Groove = subsequence.groove.Groove
MelodicState = subsequence.melodic_state.MelodicState
register_scale = subsequence.intervals.register_scale
