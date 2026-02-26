
"""
Subsequence - a stateful algorithmic MIDI sequencer for Python.

Unlike stateless sequencers that loop forever, Subsequence rebuilds each
pattern before it plays - giving it access to the current chord, section,
cycle count, external data, and anything else in scope. This makes
compositions that evolve over time as natural to write as static loops.
It generates pure MIDI (no audio engine) to control hardware synths,
modular gear, drum machines, or software VSTs/DAWs.

Features:

- **Patterns as functions.** Decorated Python functions rebuilt each cycle
  with full musical context - chord, section, bar count, external data.
- **Mini-notation.** ``p.seq("x x [x x] x", pitch="kick")`` - concise
  string syntax for rhythms, melodies, subdivisions, and per-step
  probability.
- **Context-aware harmony.** Weighted chord-transition graphs with
  adjustable gravity, Narmour melodic cognition, and automatic voice
  leading. Eleven built-in harmonic palettes.
- **Form and sections.** Define song structure as a weighted graph, an
  ordered list, or a Python generator. Patterns read ``p.section`` to
  adapt their behaviour per section.
- **Frozen progressions.** ``composition.freeze(bars)`` captures a
  chord sequence from the live engine into a ``Progression`` object.
  ``composition.section_chords(name, progression)`` binds it to a form
  section so it replays identically on every re-entry. Unbound sections
  continue generating live. Successive freeze calls advance the engine
  so sections feel harmonically connected.
- **Rhythmic tools.** Euclidean and Bresenham rhythm generators, groove
  templates (``Groove.swing()``, ``Groove.from_agr()``), swing, humanize,
  velocity shaping, dropout, and per-step probability.
- **The Conductor.** Global time-varying signals - LFOs and automation
  ramps with easing curves - that patterns read via ``p.signal()``.
- **Expression and OSC output.** CC messages, CC ramps, pitch bend,
  note-correlated bend/portamento/slide (``p.bend()``,
  ``p.portamento()``, ``p.slide()``), program changes, SysEx, and OSC
  automation (``p.osc()``, ``p.osc_ramp()``) - all from within
  pattern builders.
- **Scale quantization.** ``p.quantize()`` snaps notes to any scale.
  Built-in western and non-western modes (Hirajoshi, In-Sen, Iwato, Yo,
  Egyptian, pentatonics), plus ``register_scale()`` for your own.
- **External data.** ``composition.schedule()`` runs any Python function
  on a beat cycle - feed in APIs, sensors, or files and read the results
  from any pattern via ``composition.data``.
- **Live coding.** Hot-swap pattern logic, change tempo, mute/unmute, and
  tweak parameters during playback via a built-in TCP eval server.
- **MIDI I/O.** Record to file, render offline, follow an external clock,
  output clock to hardware, and map incoming CC to ``composition.data``.
- **Hotkeys.** Assign single keystrokes to jump sections, toggle mutes,
  or fire any action - with optional bar-boundary quantization.
- **Pattern transforms.** Legato, staccato, reverse, double/half-time,
  shift, transpose, invert, humanize, and conditional ``p.every()``.
- **Deterministic seeding.** ``seed=42`` makes every random decision -
  chords, form, note choices - repeatable and tweakable.
- **Pure MIDI.** No audio synthesis, no heavyweight dependencies. Route
  to any hardware or software instrument.

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

Package-level exports: ``Composition``, ``Groove``, ``register_scale``.
"""

import subsequence.composition
import subsequence.groove
import subsequence.intervals


Composition = subsequence.composition.Composition
Groove = subsequence.groove.Groove
register_scale = subsequence.intervals.register_scale
