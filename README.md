# Subsequence

Subsequence is a generative MIDI sequencer built in Python. It schedules patterns “just in time,” so music can evolve continuously without stopping. Patterns are defined as collections of notes in pulse time, and when a pattern is scheduled its current state is copied into the sequencer’s event queue. This lets patterns mutate over time without affecting already‑scheduled notes.

## Key ideas
- **Patterns** store notes in pulses and can evolve each cycle.
- **Sequencer** keeps a stable clock, handles note on/off, and reschedules patterns ahead of their cycle end.
- **Polyrhythms** emerge by running patterns with different lengths.
- **Harmony** can evolve via a weighted Markov transition graph (see the chord pattern in the demo).
- **Motifs & swing** utilities support expressive timing and reusable note fragments.
- **Composition clocks** can advance harmony independently of any specific pattern.

## Quick start
1. Install dependencies:
```
pip install -e .
```
2. Copy the default config (optional) and adjust your MIDI output device:
```
cp config.yaml.default config.yaml
```
3. Run the demo (drums + evolving harmony in E major):
```
python examples/demo.py
```

## Configuration
`config.yaml` (optional) supports:
- `midi.device_name` (string): MIDI output device name.
- `sequencer.initial_bpm` (int): tempo in beats per minute.

See `config.yaml.default` for defaults.

## Demo details
The demo schedules two drum patterns, a tonal chord pattern on `MIDI_CHANNEL_VOCE_EP`, a simple swung motif on `MIDI_CHANNEL_MATRIARCH`, and a steady bassline on `MIDI_CHANNEL_MINITAUR` that repeats the chord root on a 16th-note grid. A shared `HarmonicState` advances chords for the whole composition on a dedicated composition clock, and patterns read that state when they rebuild so the motif and bassline follow chord changes together. Chords evolve each cycle using a weighted transition graph and are voiced in root position (inversions may be added later). The harmonic state explicitly selects a graph style (`turnaround_global`) and includes `key_gravity_blend` plus `minor_turnaround_weight` settings. Press Ctrl+C to stop; the sequencer logs a panic message and sends all notes off.

## Extra utilities
- `subsequence.motif` provides a small Motif helper that can render into a Pattern.
- `subsequence.swing` applies swing timing to a pattern.
- `subsequence.intervals` contains interval and scale definitions for future harmonic work.
- `subsequence.event_emitter` supports sync/async events for later extensibility.
- `subsequence.chord_graphs` contains chord transition graphs (functional and global turnaround).
- `subsequence.weighted_graph` provides a generic weighted graph used for transitions.
- `subsequence.harmonic_state` holds the shared chord/key state for multiple patterns.

## Tests
This project uses `pytest`.

```
pytest
```

Async tests use `pytest-asyncio`. Install test dependencies with:

```
pip install -e .[test]
```
