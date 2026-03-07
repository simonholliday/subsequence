
"""
Subsequence - an algorithmic composition framework for Python.

Subsequence gives you a palette of mathematical building blocks -
Euclidean rhythms, cellular automata, L-systems, Markov chains,
cognitive melody generation - and a stateful engine that lets them
interact and evolve over time. Unlike tools that loop a fixed pattern
forever, Subsequence rebuilds every pattern fresh before each cycle
with full context, so algorithms feed into each other and compositions
emerge that no single technique could produce alone. It generates pure
MIDI (no audio engine) to control hardware synths, modular systems,
drum machines, or software VSTs/DAWs.

What makes it different:

- **A rich algorithmic palette.** Euclidean and Bresenham rhythm
  generators, cellular automata (1D and 2D), L-system string rewriting,
  Markov chains, cognitive melody via the Narmour model, probability-
  weighted ghost notes, position-aware thinning, drones and continuous
  notes, Perlin and pink noise, logistic chaos maps - plus groove
  templates, velocity shaping, and pitch-bend automation to shape
  how they sound.
- **Stateful patterns that evolve.** Each pattern is a Python function
  rebuilt fresh every cycle with full context - current chord, section,
  cycle count, shared data from other patterns. A Euclidean rhythm can
  thin itself as tension builds, a cellular automaton can seed from the
  harmony, and a Markov chain can shift behaviour between sections.
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
  layers (``ghost_fill()``), position-aware note removal (``thin()`` -
  the musical inverse of ``ghost_fill``), evolving cellular-automaton
  rhythms (``cellular_1d()``, ``cellular_2d()``), smooth Perlin noise (``perlin_1d()``,
  ``perlin_2d()``, ``perlin_1d_sequence()``, ``perlin_2d_grid()``),
  deterministic chaos sequences (``logistic_map()``), pink 1/f noise
  (``pink_noise()``), L-system string rewriting (``p.lsystem()``),
  Markov-chain generation (``p.markov()``), aperiodic binary rhythms
  (``p.thue_morse()``), golden-ratio beat placement (``p.fibonacci()``),
  Gray-Scott reaction-diffusion patterns (``p.reaction_diffusion()``),
  Lorenz strange-attractor generation (``p.lorenz()``), exhaustive
  pitch-subsequence melodies (``p.de_bruijn()``), step-wise melodies
  with guaranteed pitch diversity (``p.self_avoiding_walk()``), drones
  and explicit note on/off events (``p.drone()``, ``p.drone_off()``,
  ``p.silence()``),
  groove templates (``Groove.swing()``, ``Groove.from_agr()``), swing via
  ``p.swing()`` (a shortcut for ``Groove.swing()``), randomize,
  velocity shaping, dropout, per-step probability, and polyrhythms
  via independent pattern lengths.
- **Melody generation.** ``p.melody()`` with ``MelodicState`` applies
  the Narmour Implication-Realization model to single-note lines:
  continuation after small steps, reversal after large leaps, chord-tone
  weighting, range gravity, and pitch-diversity penalty.  History persists
  across bar rebuilds for natural phrase continuity.
- **Expression.** CC messages/ramps, pitch bend, note-correlated
  bend/portamento/slide, program changes, SysEx, and OSC output - all
  from within patterns.
- **Form and structure.** Musical form as a weighted graph, ordered list,
  or generator. Patterns read ``p.section`` to adapt. Conductor signals
  (LFOs, ramps) shape intensity over time.
- **Mini-notation.** ``p.seq("x x [x x] x", pitch="kick")`` - concise
  string syntax for rhythms, subdivisions, and per-step probability.
- **Scales and quantization.** ``p.quantize()`` snaps notes to any
  scale. ``scale_notes()`` generates a list of MIDI note numbers from
  a key, mode, and range or note count - useful for arpeggios, Markov
  chains, and melodic walks. Built-in western and non-western modes,
  plus ``register_scale()`` for your own.
- **Randomness tools.** Weighted choice, no-repeat shuffle, random
  walk, probability gates. Deterministic seeding (``seed=42``) makes
  every decision repeatable.
- **Pattern transforms.** Legato, staccato, reverse, double/half-time,
  shift, transpose, invert, randomize, and conditional ``p.every()``.

Integration:

- **MIDI clock.** Master (``clock_output()``) or follower
  (``clock_follow=True``). Sync to a DAW or drive hardware.
- **Hardware control.** CC input mapping from knobs/faders to
  ``composition.data``; patterns read and write the same dict via
  ``p.data`` for both external data access and cross-pattern
  communication. OSC for bidirectional communication with mixers,
  lighting, visuals.
- **Live coding.** Hot-swap patterns, change tempo, mute/unmute, and
  tweak parameters during playback via a built-in TCP eval server.
- **Hotkeys.** Single keystrokes to jump sections, toggle mutes, or
  fire any action - with optional bar-boundary quantization.
- **Real-time pattern triggering.** ``composition.trigger()`` generates
  one-shot patterns in response to sensors, OSC, or any event.
- **Terminal display.** Live status line (BPM, bar, section, chord).
  Add ``grid=True`` for an ASCII pattern grid showing velocity and
  sustain - makes legato and staccato visually distinct at a glance.
  Add ``grid_scale=2`` to zoom in horizontally, revealing swing and
  groove micro-timing.
- **Web UI Dashboard (Beta).** Enable with ``composition.web_ui()`` to 
  broadcast live composition metadata and visualize piano-roll pattern 
  grids in a reactive HTTP/WebSocket browser dashboard.
- **Ableton Link.** Industry-standard wireless tempo/phase sync
  (``comp.link()``; requires ``pip install subsequence[link]``).
  Any Link-enabled app on the same LAN — Ableton Live, iOS synths,
  other Subsequence instances — stays in time automatically.
- **Recording.** Record to standard MIDI file. Render to file without
  waiting for real-time playback.

Minimal example:

    ```python
    import subsequence
    import subsequence.constants.instruments.gm_drums as gm_drums

    comp = subsequence.Composition(bpm=120)

    @comp.pattern(channel=9, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
    def drums (p):
        (p.hit_steps("kick_1",        [0, 4, 8, 12], velocity=100)
          .hit_steps("snare_1",       [4, 12],        velocity=90)
          .hit_steps("hi_hat_closed", range(16),      velocity=70))

    comp.play()
    ```

Community and Feedback:

- **Discussions:** Chat and ask questions at https://github.com/simonholliday/subsequence/discussions
- **Issues:** Report bugs and request features at https://github.com/simonholliday/subsequence/issues

Package-level exports: ``Composition``, ``Groove``, ``MelodicState``, ``register_scale``, ``scale_notes``, ``bank_select``.
"""

import subsequence.composition
import subsequence.groove
import subsequence.intervals
import subsequence.melodic_state
import subsequence.midi_utils


Composition = subsequence.composition.Composition
Groove = subsequence.groove.Groove
MelodicState = subsequence.melodic_state.MelodicState
register_scale = subsequence.intervals.register_scale
scale_notes = subsequence.intervals.scale_notes
bank_select = subsequence.midi_utils.bank_select
