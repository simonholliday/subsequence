# Subsequence

**A stateful algorithmic MIDI sequencer for Python.** Subsequence is a generative MIDI sequencer and algorithmic composition engine for your studio. It gives you a palette of algorithmic building blocks — Euclidean generators, cellular automata, L-systems, Markov chains — and a stateful engine that lets them interact and evolve over time, driving your hardware synths and VSTs with rock-solid timing.

It's designed for the musician who wants generative music with as much control — or chaos — as they choose, where patterns combine, react to context, and develop in ways that reward exploration. Unlike tools that loop a fixed pattern forever, Subsequence rebuilds every pattern fresh before each cycle, granting macro-level structural control and narrative evolution. Each rebuild has full context — the current chord, the composition section, the cycle count, shared data from other patterns. A Euclidean rhythm can thin itself as tension builds; a cellular automaton can seed from the harmony.

Use your own gear. Subsequence provides the logic; your Eurorack, Elektron boxes, or DAW provide the sound — with no fixed limits on tracks, polyphony, complexity, or pattern length.

> **What you need:** basic Python knowledge and any MIDI-controllable instrument. Whether you're an experienced coder or a musician learning Python for the first time, the API is designed to be approachable. Subsequence generates pure MIDI data; it does not produce sound itself.

**Want to dive in?** Learn it with the **[Cookbook ↗](https://subsequence.live/cookbook/)**, look things up in the **[API Reference ↗](https://subsequence.live/api/subsequence/index.html)**, or browse the full docs at **[subsequence.live ↗](https://subsequence.live)**.

## Why Subsequence?

- **Between traditional and generative.** Most sequencers repeat a fixed loop; most live-coding environments are stateless. Subsequence rebuilds every pattern fresh each cycle with full context — current chord, section, history, shared data. Patterns that evolve, remember, and react.
- **Built-in harmonic intelligence.** An optional chord graph defines weighted chord and key transitions with adjustable gravity and automatic voice leading. Layer on cognitive harmony for Narmour-based melodic inertia — big leaps tend to reverse, small steps tend to continue.
- **Implicit compositional structure.** Predefined sections bring overarching musical form to a piece without getting stuck in infinite loops — music that grows and develops across defined movements.
- **Patterns that talk to each other.** Shared state (`composition.data`) lets autonomous generators cooperate without coupling. A drum pattern broadcasts its density; a bass pattern reads it to place complementary gaps. No callbacks, no wiring.
- **Precision and efficiency.** A hybrid timing strategy achieves typical pulse jitter of **< 5 μs** on Linux, with zero long-term drift — built for live performance and serious studio use.
- **Accessible Python, no CS degree required.** If you can configure a synth, you can write generative music here. Start with tiny scripts and learn as you go — it's the perfect project to tempt a musician into Python.
- **Explore, capture, produce.** Seed a session for deterministic output: explore freely, and when something clicks, the same seed recreates it exactly. Record to a standard multi-channel `.mid` file and bring it straight into your DAW.
- **Turn anything into music.** Patterns are plain Python functions, so any data source — live APIs, sensors, files, network streams — can drive musical decisions at rebuild time. If Python can read it, Subsequence can play it.
- **Microtonal-ready.** Scala `.scl` files and N-TET equal temperaments out of the box, realised via automatic per-note pitch bend — no MPE, no special hardware.

## Quick example

This is all the code you need for a simple drum pattern:

```python
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums

composition = subsequence.Composition(bpm=120)

@composition.pattern(channel=10, beats=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)   # beats 1, 2, 3, 4
	p.hit_steps("snare_1", [4, 12], velocity=90)         # beats 2 and 4
	p.hit_steps("hi_hat_closed", range(16), velocity=70) # every sixteenth

composition.play()
```

## Installation

Subsequence needs **Python 3.10+** and a MIDI destination — a hardware synth or drum machine, or a virtual MIDI port into your DAW or software instrument. It generates MIDI only; it makes no sound itself.

Install it into your project's virtual environment (no clone needed):

```bash
pip install git+https://github.com/simonholliday/subsequence.git

# optional: Ableton Link tempo sync
pip install "subsequence[link] @ git+https://github.com/simonholliday/subsequence.git"
```

Pin a piece to an exact release by appending a tag — `...subsequence.git@v0.6.2` — so it renders identically forever, whatever the library does next.

**Linux:** the ALSA backend needs your user in the `audio` group. If you hit `open /dev/snd/seq failed: Permission denied`:

```bash
sudo usermod -a -G audio $USER   # then log out and back in
```

New to Subsequence? The Cookbook's **[Chapter 0 ↗](https://subsequence.live/cookbook/00-setup.html)** walks through installation, creating a virtual MIDI port on macOS / Windows / Linux, and your first sound, step by step. (Working from a clone instead? `pip install -e .` and hear it with `python examples/demo.py`.)

## Documentation

Full documentation lives at **[subsequence.live ↗](https://subsequence.live)**.

| Resource | What it's for |
|---|---|
| **[Cookbook ↗](https://subsequence.live/cookbook/)** | **Learn it.** A narrative, fully runnable tutorial — from your first beat to generative composition, every concept earning the next. |
| **[API Reference ↗](https://subsequence.live/api/subsequence/index.html)** | **Look it up.** Every class, method, and function with full signatures and types, generated from source so it never drifts. |
| **[`api-cheatsheet.md`](api-cheatsheet.md)** | **Fast recall.** One-line signatures for the whole public surface, here in the repo. |
| **[`llms.txt` ↗](https://subsequence.live/llms.txt)** | **For AI agents.** A clean docs entry point, with the full-text bundle at [`llms-ctx.txt` ↗](https://subsequence.live/llms-ctx.txt). |

## Design principles

Subsequence aims for *learn one verb, predict the rest*. A handful of conventions hold across the whole API:

- **Verbs share a common front.** The chord verbs (`chord`, `strum`, `arpeggio`, `broken_chord`) speak the same vocabulary — a chord or list of pitches, `root`, `velocity`, `count`, `beat` — so swapping one for another is usually a one-word change.
- **`(low, high)` means one random draw.** `velocity=(60, 90)` draws once per note from that range; a plain int is fixed.
- **One determinism knob: `seed=`.** Every generator takes `seed=` for a reproducible take (advanced: `rng=` to share a generator). Precedence is `rng=` > `seed=` > the pattern's `p.rng`.
- **Times are in beats; steps count grid slots.** `beat=`, `spacing=`, and `duration=` are in beats; `hit_steps`, `sequence`, and the decorator's `steps=` count grid steps.
- **Lenient names, strict numbers.** An unknown drum or voice *name* is dropped with a one-time warning (the rest of the pattern still plays); an unmapped CC/NRPN/RPN *number* raises, because a wrong control number is a real mistake.
- **Builders chain, accessors don't.** Methods that place or transform return the builder (`p.euclidean(...).swing(...)`); methods that read return plain data.

## Performance

The internal master clock uses a hybrid sleep+spin strategy: it sleeps to within ~1 ms of each pulse, then busy-waits on `time.perf_counter()` for the remaining sub-millisecond interval. Pulse times are absolute offsets from the session start, so timing error never accumulates.

Measured jitter on Linux at 120 BPM (64 bars, 6144 pulses):

| Mode | Mean | P99 | Max | Long-term drift |
|---|---|---|---|---|
| Spin-wait on (default) | **3 μs** | 4 μs | ~100 μs\* | 0 |
| `asyncio.sleep` only | 853 μs | 1.37 ms | 1.72 ms | negligible |

<sub>\* Occasional spikes are Python GC pauses, not clock instability. Disable spin-wait (`composition.sequencer.disable_spin_wait()`) for ~1 ms jitter and lower CPU. Reproduce with `python benchmarks/clock_jitter.py --compare`.</sub>

## Examples

The `examples/` directory holds self-documenting compositions. Because Subsequence emits pure MIDI, what you hear depends on the instruments you route to — the same code can drive a hardware monosynth, a VST orchestra, or anything between.

| Example | What it shows |
|---|---|
| `demo.py` / `demo_advanced.py` | Drums, bass, and an arpeggio over evolving E-aeolian harmony — the Composition API vs the Direct Pattern API, side by side. Start here. |
| `labyrinth.py` / `subharmonicon.py` | Fully documented recreations of two Moog semi-modular sequencers, every panel control exposed as a named variable. Exercise most of the API. |
| `arpeggiator.py` | Form sections, five patterns, cycle-dependent variation, Phrygian harmony, and section-aware muting. |
| `bresenham_poly.py` | Dense generative drums on a weighted-graph form (pulse → emerge → peak → dissolve); ghost fills, cellular automata, interlocking hats. |
| `emergence.py` | A six-section drum piece that breathes, builds, and breaks — Perlin fields, rare "fracture" eruptions, the full rhythm toolkit. |
| `frozen.py` | `freeze()` + `section_chords()` — a frozen verse and chorus alongside a live-generated bridge. |
| `iss.py` | Live International Space Station telemetry mapped to tempo, harmony, and arpeggio direction via `EasedValue`. |
| `link_sync.py` | Ableton Link synchronisation — join a LAN tempo/phase session, or start one for other apps to lock onto. |
| `live_init.py` + `live_patterns.py` | The file-watching live-coding workflow — edit and save to hear changes on the next bar. |
| `live_single_file.py` | The compact single-file variant that watches itself. |
| `load_patterns.py` | Registering patterns from a Python string (network or one-shot loads). |

Run any with `python examples/<name>.py`.

## Roadmap

Recently shipped: the **[Cookbook and full API reference ↗](https://subsequence.live)** — a guided path from first sound to generative composition.

Planned, roughly in priority order:

- **Example library** — more short, single-screen compositions across styles (minimal techno, ambient generative, polyrhythmic, data-driven).
- **MIDI file import & analysis** — load `.mid` files and extract rhythmic or harmonic content to feed the algorithms (e.g. a Markov chain trained on a Bach invention).
- **Visual dashboard** — a richer real-time view of the chord graph, conductor signals, and active patterns.
- **Starter templates** — ready-made genre starting points for new compositions.
- **Network sync** — share conductor signals, progressions, and composition data between instances (tempo sync is already handled by Ableton Link).
- **Further out:** standalone Raspberry Pi mode, performance profiling, live-coding UX (editor integration), and CV/Gate output for modular synths.

## Contributing and development

```bash
git clone https://github.com/simonholliday/subsequence
cd subsequence
pip install -e ".[test]"     # editable install with test deps

python -m pytest tests/      # run the suite (async tests use pytest-asyncio)
```

For type checking, `pip install -e ".[dev]"` then `mypy subsequence/` — also enforced in CI on every pull request.

Feedback and ideas are very welcome — open a [Discussion ↗](https://github.com/simonholliday/subsequence/discussions) for questions, or an [Issue ↗](https://github.com/simonholliday/subsequence/issues) for bugs and feature requests.

## Related projects

**[Subsample ↗](https://github.com/simonholliday/subsample)** — a sister project by the same author: a live sampler, automatic drum-kit builder, and MIDI sample instrument. Point a microphone at the world (or feed in recordings and sample packs) and Subsample captures, analyses, and maps every sound into a playable instrument automatically. Connect it to Subsequence over a virtual MIDI port, or enable OSC on both sides for richer event communication.

## Credits

Subsequence makes use of these excellent open-source libraries:

| Library | Purpose | License |
|---|---|---|
| [mido ↗](https://github.com/mido/mido) | MIDI message handling and file I/O | MIT |
| [python-rtmidi ↗](https://github.com/SpotlightKid/python-rtmidi) | Real-time MIDI I/O | MIT |
| [python-osc ↗](https://github.com/attwad/python-osc) | OSC protocol support | Unlicense |
| [pymididefs ↗](https://github.com/simonholliday/PyMidiDefs) | Canonical MIDI 1.0/2.0 constant definitions | MIT |
| [websockets ↗](https://github.com/python-websockets/websockets) | Web UI dashboard communication | BSD-3-Clause |
| [aalink ↗](https://github.com/artfwo/aalink) *(optional)* | Ableton Link integration | GPL-3.0 |

[Ableton Link ↗](https://www.ableton.com/en/link/) is a technology by Ableton AG. The `aalink` Python wrapper is written by Artem Popov and licensed under GPL-3.0, which is compatible with Subsequence's AGPL-3.0 license.

## Author

Subsequence was created by Simon Holliday ([simonholliday.com ↗](https://simonholliday.com/)), a senior technologist and a junior (but trying) musician. From running an electronic music label in the 2000s to prototyping new passive SONAR techniques for defence research, my work has often explored the intersection of code and sound. Subsequence was iterated over a series of proof-of-concept projects during 2025 and pulled together into this codebase in Spring 2026.

## License

Subsequence is released under the [GNU Affero General Public License v3.0](LICENSE) (AGPLv3). You are free to use, modify, and distribute it under the terms of the AGPL. If you run a modified version as part of a network service, you must make the source code available to its users.

The core dependencies (mido, python-rtmidi, python-osc, websockets) are all permissively licensed (MIT, Unlicense, BSD-3-Clause). The optional Ableton Link integration uses `aalink` (GPL-3.0), compatible with the AGPL.

**Commercial licensing.** To use Subsequence in a proprietary or closed-source product without the obligations of the AGPL, contact simon.holliday@protonmail.com to discuss a commercial license.
