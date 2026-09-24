# Subsequence

**A stateful algorithmic MIDI sequencer for Python.**

Subsequence is a generative MIDI sequencer and algorithmic composition engine for your studio. It gives you a palette of algorithmic building blocks - Euclidean generators, cellular automata, L-systems, Markov chains - and a stateful engine that lets them interact and evolve over time, driving your hardware synths and VSTs with rock-solid timing.

It's designed for the musician who wants generative music with as much control - or chaos - as they choose, where patterns combine, react to context, and develop in ways that reward exploration. Unlike tools that loop a fixed pattern forever, Subsequence rebuilds every pattern fresh before each cycle, granting macro-level structural control and narrative evolution. Each rebuild has full context - the current chord, the composition section, the cycle count, shared data from other patterns. A Euclidean rhythm can thin itself as tension builds; a cellular automaton can seed from the harmony.

Use your own gear. Subsequence provides the logic; your Eurorack, Elektron boxes, or DAW provide the sound - with no fixed limits on tracks, polyphony, complexity, or pattern length.

> **What you need:** basic Python knowledge and any MIDI-controllable instrument. Whether you're an experienced coder or a musician learning Python for the first time, the API is designed to be approachable. Subsequence generates pure MIDI data; it does not produce sound itself.

## Why Subsequence?

- **Between traditional and generative.** Most sequencers repeat a fixed loop; most live-coding environments are stateless. Subsequence rebuilds every pattern fresh each cycle with full context - current chord, section, history, shared data. Patterns that evolve, remember, and react.
- **Built-in harmonic intelligence.** An optional chord graph defines weighted chord and key transitions with adjustable pull toward the key and automatic voice leading. Layer on cognitive harmony for Narmour-based melodic inertia - big leaps tend to reverse, small steps tend to continue.
- **Implicit compositional structure.** Predefined sections bring overarching musical form to a piece without getting stuck in infinite loops - music that grows and develops across defined movements.
- **Patterns that talk to each other.** Shared state (`composition.data`) lets autonomous generators cooperate without coupling. A drum pattern broadcasts its density; a bass pattern reads it to place complementary gaps. No callbacks, no wiring.
- **Precision and efficiency.** A hybrid timing strategy holds pulse jitter at a typical **1 μs** on Linux, with no pulse more than 0.1 ms out at any tempo and zero long-term drift - built for live performance and serious studio use.
- **Accessible Python, no CS degree required.** If you can configure a synth, you can write generative music here. Start with tiny scripts and learn as you go - it's the perfect project to tempt a musician into Python.
- **Explore, capture, produce.** Seed a session for deterministic output: explore freely, and when something clicks, the same seed recreates it exactly. Record to a standard multi-channel `.mid` file and bring it straight into your DAW.
- **Turn anything into music.** Patterns are plain Python functions, so any data source - live APIs, sensors, files, network streams - can drive musical decisions at rebuild time. If Python can read it, Subsequence can play it.
- **Microtonal-ready.** Scala `.scl` files and N-TET equal temperaments out of the box, realised via automatic per-note pitch bend - no MPE, no special hardware.

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

Subsequence needs **Python 3.10+** and a MIDI destination - a hardware synth or drum machine, or a virtual MIDI port into your DAW or software instrument. It generates MIDI only; it makes no sound itself.

Install it into your project's virtual environment:

```bash
pip install subsequence

# optional: Ableton Link tempo sync
pip install "subsequence[link]"
```

Pin a piece to the release you made it with, `pip install subsequence==<version>` from the [releases](https://github.com/simonholliday/subsequence/releases), so it renders identically forever, whatever the library does next.

**Linux:** the ALSA backend needs your user in the `audio` group. If you hit `open /dev/snd/seq failed: Permission denied`:

```bash
sudo usermod -a -G audio $USER   # then log out and back in
```

### Naming your MIDI device

Device names are matched as patterns, so you don't have to type them exactly. `*` stands for any run of characters, `?` for exactly one, matching ignores case, and a name with no wildcards is just a substring - so `output_device="Scarlett"` finds your interface without the rest of the name.

Wildcards earn their keep on Linux, where a full name looks like `U6MIDI Pro:U6MIDI Pro Port 1 16:0`. That `16` is an id the system hands out in connection order, so it changes between reboots and a pinned name stops working. The `0` after it is the port on the interface and never moves. Wildcard the part that moves, keep the part that doesn't:

```python
composition = subsequence.Composition(output_device="*U6MIDI Pro *:0")
```

**Keep that trailing port number.** A multi-port interface reports one name per port, so `"*U6MIDI Pro*"` matches all three ports of a three-port unit and asks which you meant every time you start; `"*U6MIDI Pro *:0"` names one port for good. Prefer `*` to `?` - `?` matches a single character, so a pattern written for `16:0` silently stops matching once ids reach three digits.

If a pattern matches nothing, Subsequence tells you and lists what it did find. If it matches several, it asks - unless there's no terminal to ask (a scheduled job, a service, an SSH session without a TTY), in which case it says so rather than waiting for an answer that can't come.

New to Subsequence? The guide's **[Install and connect ↗](https://subsystem.co/subsequence/guide/install-and-connect/)** chapter walks through installation, creating a virtual MIDI port on macOS, Windows or Linux, and your first sound, step by step. (Working from a clone instead? `pip install -e .` and hear it with `python examples/demo.py`.)

## Documentation

**Full documentation: [https://subsystem.co/subsequence/](https://subsystem.co/subsequence/)**

- Guide: [https://subsystem.co/subsequence/guide/](https://subsystem.co/subsequence/guide/)
- API reference: [https://subsystem.co/subsequence/reference/](https://subsystem.co/subsequence/reference/)
- Cheat sheet: [https://subsystem.co/subsequence/cheatsheet/](https://subsystem.co/subsequence/cheatsheet/)
- For AI agents: [https://subsystem.co/subsequence/llms.txt](https://subsystem.co/subsequence/llms.txt)

The guide is a fully runnable tutorial that builds one piece of music, from a first drum beat to a lead line that follows the weather, with every concept earning the next. The API reference and the cheat sheet are generated from the source rather than kept by hand, and each page names the release it describes.

## Design principles

Subsequence aims for *learn one verb, predict the rest*. A handful of conventions hold across the whole API:

- **Verbs share a common front.** The chord verbs (`chord`, `strum`, `arpeggio`) speak the same vocabulary - a chord or list of pitches, `root`, `velocity`, `count`, `beat` - so swapping one for another is usually a one-word change. `broken_chord` plays the tones in an order you give, so it takes `root` and `order` up front and has no `count`.
- **`(low, high)` means one random draw.** `velocity=(60, 90)` draws once per note from that range; a plain int is fixed.
- **A short list starts again.** A list laid over steps or rows repeats from its beginning when it is shorter than they are - `sequence()`'s `pitches=`, `velocities=` and `durations=`, `ghost_fill()`'s `velocities=`, a `sequence_utils.mask()` gate - so three pitches over eight steps make a figure that drifts against the rhythm. A motif is the exception: it is a fixed figure, so its lists give one value per note and must match.
- **One determinism knob: `seed=`.** `Composition(seed=)` makes a whole piece reproducible, and a generator with random choices of its own takes `seed=` for a reproducible take (advanced: `rng=` to share a generator). Precedence is `rng=` > `seed=` > the pattern's `p.rng`, which is also where the verbs without `seed=` draw from, such as `motif()`'s probabilities, or an order for `broken_chord` shuffled with `p.rng.shuffle`.
- **Times are in beats; steps count grid slots.** `beat=`, `spacing=`, and `duration=` are in beats; `hit_steps`, `sequence`, and the decorator's `steps=` count grid steps. A negative `beat=` counts back from the end of the pattern, in every verb that places something: `beat=-1` is the last beat.
- **Lenient names, strict numbers.** An unknown drum or voice *name* is dropped with a one-time warning (the rest of the pattern still plays); a *number* MIDI cannot carry raises - a pitch or velocity outside 0-127, or an out-of-range CC/NRPN/RPN number - because a wrong number is a real mistake. A CC *value* is the exception, and clamps to 0-127.
- **Builders chain, accessors don't.** Methods that place or transform return the builder (`p.euclidean(...).swing(...)`); methods that read return plain data.

## Performance

The internal master clock uses a hybrid sleep+spin strategy: it sleeps to within ~1 ms of each pulse, then busy-waits on `time.perf_counter()` for the remaining sub-millisecond interval. Pulse times are absolute offsets from the session start, so timing error never accumulates. On Linux the clock runs on a `select()`-based event loop rather than asyncio's default: the default loop rounds each wait up to whole milliseconds, and at some tempos that overran the 1 ms margin and made pulses up to 1.5 ms late. Driving a `Sequencer` yourself? Start it with `subsequence.sequencer.run(main())` in place of `asyncio.run` to get the same loop.

Measured at 120 BPM on a Core Ultra 7 155H under Linux 7.0:

| Mode | Median | P99 | Max | Long-term drift |
|---|---|---|---|---|
| Spin-wait on (default) | **1 μs** | 2 μs | 39 μs\* | 0 |
| `asyncio.sleep` only | 406 μs | 555 μs | 799 μs | negligible |

**One tempo is not enough to judge a clock by**, because how each sleep rounds depends on how long it is. Swept from 60 to 200 BPM in steps of 5, eight bars each - 22,272 pulses - the median stays at 1 μs, the worst tempo's P99 is 17 μs, the worst single pulse is 91 μs, and nothing runs more than 1 ms late at any tempo.

<sub>\* Occasional spikes are Python GC pauses, not clock instability. Disable spin-wait (`composition.sequencer.disable_spin_wait()`) for ~0.4 ms jitter and lower CPU. Reproduce with `python benchmarks/clock_jitter.py --sweep 60:200:5`, or `--compare` for one tempo with spin-wait on and off.</sub>

## Examples

The `examples/` directory holds self-documenting compositions. Because Subsequence emits pure MIDI, what you hear depends on the instruments you route to - the same code can drive a hardware monosynth, a VST orchestra, or anything between.

| Example | What it shows |
|---|---|
| `demo.py` / `demo_advanced.py` | Drums, bass, and an arpeggio over evolving E-aeolian harmony - the Composition API vs the Direct Pattern API, side by side. Start here. |
| `labyrinth.py` / `subharmonicon.py` | Fully documented recreations of two Moog semi-modular sequencers, every panel control exposed as a named variable. Exercise most of the API. |
| `arpeggiator.py` | Form sections, four patterns, cycle-dependent variation, Phrygian harmony, and section-aware muting. |
| `bresenham_poly.py` | Dense generative drums on a weighted-graph form (pulse → emerge → peak → dissolve); ghost fills, cellular automata, interlocking hats. |
| `emergence.py` | A six-section drum piece that breathes, builds, and breaks - Perlin fields, rare "fracture" eruptions, the full rhythm toolkit. |
| `frozen.py` | `freeze()` + `section_chords()` - a frozen verse and chorus alongside a live-generated bridge. |
| `iss.py` | Live International Space Station telemetry mapped to tempo, harmony, and arpeggio direction via `EasedValue`. |
| `link_sync.py` | Ableton Link synchronisation - join a LAN tempo/phase session, or start one for other apps to lock onto. |
| `live_init.py` + `live_patterns.py` | The file-watching live-coding workflow - edit and save to hear changes on the next bar. |
| `live_single_file.py` | The compact single-file variant that watches itself. |
| `load_patterns.py` | Registering patterns from a Python string (network or one-shot loads). |

Run any with `python examples/<name>.py`.

## Roadmap

Recently shipped: the **[guide ↗](https://subsystem.co/subsequence/guide/)**, a guided path from a first beat to a finished piece, and a full **[API reference ↗](https://subsystem.co/subsequence/reference/)**.

Planned, roughly in priority order:

- **Example library** - more short, single-screen compositions across styles (minimal techno, ambient generative, polyrhythmic, data-driven).
- **MIDI file import & analysis** - load `.mid` files and extract rhythmic or harmonic content to feed the algorithms (e.g. a Markov chain trained on a Bach invention).
- **Starter templates** - ready-made genre starting points for new compositions.
- **Network sync** - share conductor signals, progressions, and composition data between instances (tempo sync is already handled by Ableton Link).
- **Further out:** standalone Raspberry Pi mode, performance profiling, live-coding UX (editor integration), and CV/Gate output for modular synths.

## Contributing and development

```bash
git clone https://github.com/simonholliday/subsequence
cd subsequence
pip install -e ".[test]"     # editable install with test deps

python -m pytest tests/      # run the suite (async tests use pytest-asyncio)
```

For type checking, `pip install -e ".[dev]"` then `mypy subsequence/`. CI runs it on every pull request, with the suite on Python 3.10 and 3.14 and two checks of the docs: `python scripts/check_docstring_markup.py subsequence`, and `python scripts/generate_cheatsheet.py --check`, which fails when `api-cheatsheet.md` no longer matches the code (run it without `--check` to regenerate the sheet).

Feedback and ideas are very welcome - open a [Discussion ↗](https://github.com/simonholliday/subsequence/discussions) for questions, or an [Issue ↗](https://github.com/simonholliday/subsequence/issues) for bugs and feature requests.

## Related projects

**[Superconductor ↗](https://github.com/simonholliday/superconductor)** - a visual tool for Subsequence, by the same author, and a work in progress. It is a touchscreen control surface: a small service serves one page to the screen's browser, a composition declares the controls it offers, and the page draws them - step grids for drums, pitched note grids, an instrument's own settings, stacks of generators and transforms built from Subsequence's own catalogue, and a transport. Tapping the screen changes the music, and changes in the music show on the screen. It is at an early stage of development, so expect rough edges and an interface that changes between versions. So far, Subsequence is the only software it drives.

**[Subsample ↗](https://github.com/simonholliday/subsample)** - a sister project by the same author: a live sampler, automatic drum-kit builder, and MIDI sample instrument. Point a microphone at the world (or feed in recordings and sample packs) and Subsample captures, analyses, and maps every sound into a playable instrument automatically. Connect it to Subsequence over a virtual MIDI port, or enable OSC on both sides for richer event communication.

## Credits

Subsequence makes use of these excellent open-source libraries:

| Library | Purpose | License |
|---|---|---|
| [mido ↗](https://github.com/mido/mido) | MIDI message handling and file I/O | MIT |
| [python-rtmidi ↗](https://github.com/SpotlightKid/python-rtmidi) | Real-time MIDI I/O | MIT |
| [python-osc ↗](https://github.com/attwad/python-osc) | OSC protocol support | Unlicense |
| [PyYAML ↗](https://github.com/yaml/pyyaml) | Project definitions files, the names shared with Subsample | MIT |
| [pymididefs ↗](https://github.com/simonholliday/PyMidiDefs) | Canonical MIDI 1.0/2.0 constant definitions | MIT |
| [aalink ↗](https://github.com/artfwo/aalink) *(optional)* | Ableton Link integration | GPL-3.0 |

[Ableton Link ↗](https://www.ableton.com/en/link/) is a technology by Ableton AG. The `aalink` Python wrapper is written by Artem Popov and licensed under GPL-3.0, which is compatible with Subsequence's AGPL-3.0 license.

## Author

Subsequence was created by Simon Holliday ([simonholliday.com ↗](https://simonholliday.com/)), a senior technologist and a junior (but trying) musician. From running an electronic music label in the 2000s to prototyping new passive SONAR techniques for defence research, my work has often explored the intersection of code and sound. Subsequence was iterated over a series of proof-of-concept projects during 2025 and pulled together into this codebase in Spring 2026.

This project is managed with [Subroutine](https://github.com/simonholliday/subroutine).

## License

Subsequence is released under the [GNU Affero General Public License v3.0](https://github.com/simonholliday/subsequence/blob/main/LICENSE) (AGPLv3). You are free to use, modify, and distribute it under the terms of the AGPL. If you run a modified version as part of a network service, you must make the source code available to its users.

The core dependencies (mido, python-rtmidi, python-osc, PyYAML, pymididefs) are all permissively licensed (MIT, Unlicense). The optional Ableton Link integration uses `aalink` (GPL-3.0), compatible with the AGPL.

**Commercial licensing.** To use Subsequence in a proprietary or closed-source product without the obligations of the AGPL, contact simon.holliday@protonmail.com to discuss a commercial license.
