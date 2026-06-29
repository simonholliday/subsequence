# Subsequence API Cheat Sheet

This document provides a quick overview of the public classes, methods, and functions available in the Subsequence API.

## `Composition`

The top-level controller for a musical piece.

| Method | Description |
|---|---|
| `__init__(output_device, bpm, time_signature, key, scale, seed, record, record_filename, zero_indexed_channels, latency_ms) -> None` | Initialize a new composition. |
| `builder_bar *(property)*` | Current bar index used by pattern builders. |
| `cc_forward(cc, output, channel, output_channel, mode, input_device, output_device) -> None` | Forward an incoming MIDI CC to the MIDI output in real-time. |
| `cc_map(cc, data_key, channel, min_val, max_val, input_device) -> None` | Map an incoming MIDI CC to a ``composition.data`` key. |
| `chords(channel, progression, harmonic_rhythm, bars, beats, voicing, velocity, detached, root, key, seed, device, mirrors) -> subsequence.progressions.Progression` | Declare a self-contained chord part: a progression at a chosen harmonic rhythm. |
| `clear_tweak(name, *param_names) -> None` | Remove tweaked parameters from a running pattern. |
| `clock_output(enabled) -> None` | Send MIDI timing clock to connected hardware. |
| `current_chord() -> Optional[Any]` | The chord sounding at the playhead, or ``None`` without harmony. |
| `display(enabled, grid, grid_scale) -> None` | Enable or disable the live terminal dashboard. |
| `energy(energies) -> None` | Set per-section energy — the arranging dial, as one plain dict. |
| `form(sections, loop, start, at_end, key, scale) -> None` | Define the structure (sections) of the composition. |
| `form_freeze(sections) -> 'subsequence.forms.Form'` | Freeze the graph form's walk into an editable :class:`~subsequence.forms.Form`. |
| `form_jump(section_name) -> None` | Jump the form to a named section immediately. |
| `form_next(section_name) -> None` | Queue the next section — takes effect when the current section ends. |
| `form_state *(property)*` | The active ``subsequence.form_state.FormState``, or ``None`` if ``form()`` has not been called. |
| `freeze(bars, end, pins, avoid, cadence) -> 'Progression'` | Capture a chord progression from the live harmony engine. |
| `get_tweaks(name) -> Dict[str, Any]` | Return a copy of the current tweaks for a running pattern. |
| `harmonic_state *(property)*` | The active ``HarmonicState``, or ``None`` if ``harmony()`` has not been called. |
| `harmony(style, cycle_beats, dominant_7th, gravity, nir_strength, minor_turnaround_weight, root_diversity, reschedule_lookahead, progression) -> None` | Configure the harmonic logic and chord change intervals. |
| `hotkey(key, action, quantize, label) -> None` | Register a single-key shortcut that fires during playback. |
| `hotkeys(enabled) -> None` | Enable or disable the global hotkey listener. |
| `is_clock_following *(property)*` | True if either the primary or any additional device is following external clock. |
| `layer(*builder_fns, channel, beats, bars, steps, step_duration, drum_note_map, cc_name_map, nrpn_name_map, reschedule_lookahead, voice_leading, device, mirrors) -> None` | Combine multiple functions into a single MIDI pattern. |
| `link(quantum) -> 'Composition'` | Enable Ableton Link tempo and phase synchronisation. |
| `live(port) -> None` | Enable the live coding eval server. |
| `live_info() -> Dict[str, Any]` | Return a dictionary containing the current state of the composition. |
| `load_patterns(source, source_label) -> None` | Compile and apply a pattern-source string to the composition. |
| `lock(name) -> None` | Pin a named stream: keep its current effective seed and realization. |
| `midi_input(device, clock_follow, name) -> None` | Configure a MIDI input device for external sync and MIDI messages. |
| `midi_output(device, name, latency_ms) -> int` | Register an additional MIDI output device. |
| `mirror(name, device, channel, drum_note_map) -> None` | Add a mirror destination to a running pattern. |
| `mute(name) -> None` | Mute a running pattern by name. |
| `note_input(channel, release_ms, latch, input_device) -> None` | Track notes held on a MIDI keyboard for live arpeggiation. |
| `on_event(event_name, callback) -> None` | Register a callback for a sequencer event (e.g., "bar", "start", "stop"). |
| `on_section(callback) -> None` | Register a callback fired on every section change. |
| `osc(receive_port, send_port, send_host, receive_host) -> None` | Enable bi-directional Open Sound Control (OSC). |
| `osc_map(address, handler) -> None` | Register a custom OSC handler. |
| `pattern(channel, beats, bars, steps, step_duration, drum_note_map, cc_name_map, nrpn_name_map, reschedule_lookahead, voice_leading, device, mirrors, min_energy) -> Callable` | Register a function as a repeating MIDI pattern. |
| `phrase_part(channel, part, root, bars, beats, velocity, fit, device, mirrors) -> None` | Declare a part that plays each section's bound Motif/Phrase. |
| `pin_chord(bar, chord) -> None` | Force the chord sounding at a bar — fiat over live generation. |
| `play() -> None` | Start the composition. |
| `render(bars, filename, max_minutes) -> None` | Render the composition to a MIDI file without real-time playback. |
| `request_cadence(cadence, bar) -> None` | Ask the live engine to approach a cadence arriving at a bar. |
| `reroll(name) -> None` | Deal a named stream a fresh deterministic seed — try a new variation. |
| `running_patterns *(property)*` | The currently active patterns, keyed by name. |
| `schedule(fn, cycle_beats, reschedule_lookahead, wait_for_initial, defer) -> None` | Register a custom function to run on a repeating beat-based cycle. |
| `section_cadence(section_name, cadence) -> None` | Close every pass of a section with a cadence — the standing request. |
| `section_chords(section_name, progression) -> None` | Bind a :class:`Progression` to a named form section. |
| `section_motifs(section_name, value, part) -> None` | Bind a Motif or Phrase to a named form section (per optional part). |
| `seed *(property)*` | The composition's random seed, or None when unseeded. |
| `seed_for(name) -> Optional[int]` | Surface the effective derived seed for a named stream. |
| `sequencer *(property)*` | The underlying ``Sequencer`` instance. |
| `set_bpm(bpm) -> None` | Instantly change the tempo. |
| `target_bpm(bpm, bars, shape) -> None` | Smoothly ramp the tempo to a target value over a number of bars. |
| `transition(before, fill, channel, beat, mute, beats, drum_note_map, device) -> None` | Declare boundary material — the automatic fill or mute, one line. |
| `trigger(fn, channel, beats, bars, steps, step_duration, quantize, drum_note_map, cc_name_map, nrpn_name_map, chord, device, mirrors) -> None` | Trigger a one-shot pattern immediately or on a quantized boundary. |
| `tuning(source, cents, ratios, equal, bend_range, channels, reference_note, exclude_drums) -> None` | Set a global microtonal tuning for the composition. |
| `tweak(name, **kwargs) -> None` | Override parameters for a running pattern. |
| `unlock(name) -> None` | Release a ``lock()``: the stream runs free and ``reroll()`` works again. |
| `unmirror(name, device, channel) -> None` | Remove a single mirror destination from a running pattern. |
| `unmirror_all(name) -> None` | Remove every mirror destination from a running pattern. |
| `unmute(name) -> None` | Unmute a previously muted pattern. |
| `unregister(name) -> None` | Fully remove a running pattern from rotation. |
| `watch(path, poll_interval) -> None` | Watch a Python file and reload it into the composition on every save. |
| `web_ui(http_host, ws_host) -> None` | Enable the realtime Web UI Dashboard. |


## `PatternBuilder`

The musician's 'palette' for creating musical content.

| Method | Description |
|---|---|
| `__init__(pattern, cycle, conductor, drum_note_map, cc_name_map, nrpn_name_map, section, bar, rng, tweaks, default_grid, data, key, scale, time_signature, held_notes, harmony, section_motifs, energy) -> None` | Initialize the builder with pattern context, cycle count, and optional section info. |
| `apply_tuning(tuning, bend_range, channels, reference_note) -> 'PatternBuilder'` | Apply a microtonal tuning to this pattern via pitch bend injection. |
| `arpeggio(notes, root, velocity, count, inversion, beat, span, spacing, duration, direction, seed, rng) -> 'PatternBuilder'` | Arpeggiate a chord (or a list of pitches) — cycle the notes one at a time at regular beat intervals. |
| `bar_cycle(length) -> subsequence.pattern_builder.BarCycle` | Return the current bar's position within a repeating cycle of bars. |
| `bend(note, amount, start, end, shape, resolution) -> 'subsequence.pattern_builder.PatternBuilder'` | Bend a specific note by index. |
| `branch(pitches, depth, path, mutation, velocity, duration, spacing, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melodic variation by navigating a fractal tree of transforms. |
| `bresenham(pitch, pulses, velocity, duration, probability, no_overlap, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a rhythm using the Bresenham line algorithm. |
| `bresenham_poly(parts, velocity, duration, grid, probability, no_overlap, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Distribute multiple drum voices across the pattern using weighted Bresenham. |
| `broken_chord(chord_obj, root, order, spacing, velocity, duration, inversion, beat, span) -> 'PatternBuilder'` | Play a chord as an arpeggio in a specific or random order. |
| `build_ghost_bias(grid, bias) -> List[float]` | Build probability weights for ghost notes or other generative functions. |
| `build_velocity_ramp(low, high, shape, grid) -> List[int]` | Build a per-step velocity list that ramps from *low* to *high*. |
| `c *(property)*` | Alias for self.conductor. |
| `capture(beat, span) -> 'subsequence.motifs.Motif'` | Read the notes placed so far back out as a :class:`~subsequence.motifs.Motif`. |
| `cc(control, value, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single CC message at a beat position. |
| `cc_ramp(control, start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate a CC value over a beat range. |
| `cellular_1d(pitch, rule, generation, velocity, duration, no_overlap, probability, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate an evolving rhythm using a 1D cellular automaton. |
| `cellular_2d(pitches, rule, generation, velocity, duration, no_overlap, probability, initial_state, density, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate polyphonic patterns using a 2D Life-like cellular automaton. |
| `chord(chord_obj, root, velocity, sustain, duration, inversion, count, legato, detached, beat) -> 'PatternBuilder'` | Place a chord at ``beat`` (the start of the pattern by default). |
| `de_bruijn(pitches, window, spacing, velocity, duration, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melody that exhaustively traverses all pitch subsequences. |
| `detached(beats) -> 'PatternBuilder'` | Shorten note durations so a guaranteed silence precedes the next onset. |
| `drone(pitch, beat, velocity) -> 'PatternBuilder'` | A musical alias for ``note_on``. Places a raw Note On event without a duration, typically used for sustained notes that span multiple cycles. Must be silenced later using ``drone_off()``. |
| `drone_off(pitch) -> 'PatternBuilder'` | A musical alias for ``note_off``. Places a raw Note Off event at beat 0.0. Used to stop a sequence started by ``drone()``. |
| `dropout(probability, seed, rng) -> 'PatternBuilder'` | Randomly remove notes from the pattern. |
| `duck_map(steps, floor, grid) -> List[float]` | Build a per-step velocity multiplier list for sidechain-style ducking. |
| `duration(beats) -> 'PatternBuilder'` | Set every note's duration to a fixed length in beats. |
| `euclidean(pitch, pulses, velocity, duration, probability, no_overlap, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a Euclidean rhythm. |
| `every(n, fn) -> 'PatternBuilder'` | Apply a transformation every Nth cycle. |
| `evolve(pitches, length, drift, velocity, duration, spacing, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Loop a pitch sequence that gradually mutates each cycle. |
| `fibonacci(pitch, count, velocity, duration, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Place notes at golden-ratio-spaced beat positions (Fibonacci spiral timing). |
| `ghost_fill(pitch, density, velocity, bias, no_overlap, grid, duration, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Fill the pattern with probability-biased ghost notes. |
| `grid *(property)*` | Number of grid slots in this pattern (e.g. 16 for a 4-beat sixteenth-note pattern). |
| `groove(template, strength) -> 'PatternBuilder'` | Apply a groove template to all notes in the pattern. |
| `held_notes() -> List[int]` | Return the MIDI notes currently held on the ``note_input`` keyboard. |
| `hit(pitch, beats, velocity, duration) -> 'PatternBuilder'` | Place multiple short 'hits' at a list of beat positions. |
| `hit_steps(pitch, steps, velocity, duration, grid, probability, seed, rng) -> 'PatternBuilder'` | Place short hits at specific step (grid) positions. |
| `invert(pivot) -> 'PatternBuilder'` | Invert all pitches around a pivot note. |
| `legato(ratio) -> 'PatternBuilder'` | Adjust note durations to fill the gap until the next note. |
| `lorenz(pitches, spacing, velocity, duration, dt, sigma, rho, beta, x0, y0, z0, mapping) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a note sequence driven by the Lorenz strange attractor. |
| `lsystem(pitch_map, axiom, rules, generations, spacing, velocity, duration, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a note sequence using L-system string rewriting. |
| `markov(transitions, pitch_map, velocity, duration, spacing, start, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a sequence by walking a first-order Markov chain. |
| `melody(state, spacing, velocity, duration, chord_tones, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melodic line by querying a persistent :class:`~subsequence.melodic_state.MelodicState`. |
| `motif(m, beat, span, root, velocity, fit, fit_weights, resolution) -> 'PatternBuilder'` | Place an immutable :class:`~subsequence.motifs.Motif` onto the pattern. |
| `note(pitch, beat, velocity, duration) -> 'PatternBuilder'` | Place a single MIDI note at a specific beat position. |
| `note_off(pitch, beat) -> 'PatternBuilder'` | Place an explicit Note Off event to silence a drone. |
| `note_on(pitch, beat, velocity) -> 'PatternBuilder'` | Place an explicit Note On event without a duration. Useful for drones or infinite sustains. Must be paired with a ``note_off()`` later to silence the note. |
| `nrpn(parameter, value, beat, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single NRPN parameter write at a beat position. |
| `nrpn_ramp(parameter, start, end, beat_start, beat_end, resolution, shape, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an NRPN value over a beat range. |
| `osc(address, *args, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send an OSC message at a beat position. |
| `osc_ramp(address, start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an OSC float value over a beat range. |
| `param(name, default) -> Any` | Read a tweakable parameter for this pattern. |
| `phrase(value, root, velocity, fit, resolution, align, offset) -> 'PatternBuilder'` | Place this cycle's window of a Phrase — position computed, never stored. |
| `pitch_bend(value, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single pitch bend message at a beat position. |
| `pitch_bend_ramp(start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate pitch bend over a beat range. |
| `portamento(time, shape, resolution, bend_range, wrap) -> 'subsequence.pattern_builder.PatternBuilder'` | Glide between all consecutive notes using pitch bend. |
| `program_change(program, beat, bank_msb, bank_lsb) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a Program Change message, optionally preceded by bank select. |
| `progression(source, harmonic_rhythm, key, seed, rng) -> subsequence.progressions.Progression` | Realise a chord progression across the pattern, returning it to place yourself. |
| `randomize(timing, velocity, seed, rng) -> 'PatternBuilder'` | Add random variations to note timing and velocity. |
| `ratchet(subdivisions, pitch, probability, velocity_start, velocity_end, shape, gate, steps, grid, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Subdivide existing notes into rapid repeated hits (rolls/ratchets). |
| `reaction_diffusion(pitch, threshold, velocity, duration, feed_rate, kill_rate, steps, no_overlap, probability, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a rhythm from a 1D Gray-Scott reaction-diffusion simulation. |
| `repeat(pitch, spacing, velocity, duration) -> 'PatternBuilder'` | Repeat a note at a fixed beat interval for the whole pattern. |
| `reverse() -> 'PatternBuilder'` | Flip the pattern backwards in time (retrograde). |
| `rotate(steps, grid) -> 'PatternBuilder'` | Rotate the pattern by a number of grid steps, wrapping around. |
| `rpn(parameter, value, beat, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single RPN parameter write at a beat position. |
| `rpn_ramp(parameter, start, end, beat_start, beat_end, resolution, shape, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an RPN value over a beat range. |
| `scale_velocities(factors, grid) -> 'PatternBuilder'` | Scale note velocities by a per-step multiplier list. |
| `section_motif(part) -> Optional[Any]` | The Motif/Phrase bound to the current section (and part), or ``None``. |
| `self_avoiding_walk(pitches, spacing, velocity, duration, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melody using a self-avoiding random walk. |
| `seq(notation, pitch, velocity, seed, rng) -> 'PatternBuilder'` | Build a pattern using an expressive string-based 'mini-notation'. |
| `sequence(steps, pitches, velocities, durations, grid, probability, seed, rng) -> 'PatternBuilder'` | A multi-parameter step sequencer. |
| `set_length(length) -> 'PatternBuilder'` | Dynamically change the length of the pattern. |
| `signal(name) -> float` | Read a conductor signal at the current bar. |
| `silence(beat) -> 'PatternBuilder'` | Sends an 'All Notes Off' (CC 123) and 'All Sound Off' (CC 120) message on the pattern's channel to immediately silence any ringing notes or drones. |
| `slide(notes, steps, time, shape, resolution, bend_range, wrap, extend) -> 'subsequence.pattern_builder.PatternBuilder'` | TB-303-style selective slide into specific notes. |
| `snap_to_scale(key, mode, strength, seed, rng) -> 'PatternBuilder'` | Snap all notes in the pattern to the nearest pitch in a scale. |
| `stretch(factor) -> 'PatternBuilder'` | Stretch the pattern in time, scaling note positions and durations. |
| `strum(chord_obj, root, velocity, sustain, duration, inversion, count, spacing, direction, legato, detached, beat) -> 'PatternBuilder'` | Play a chord with a small time offset between each note (strum effect). |
| `swing(percent, grid, strength) -> 'PatternBuilder'` | Apply swing feel to all notes in the pattern. |
| `sysex(data, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a System Exclusive (SysEx) message at a beat position. |
| `thin(pitch, strategy, amount, grid, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Remove notes from the pattern based on their rhythmic position. |
| `thue_morse(pitch, velocity, duration, pitch_b, velocity_b, no_overlap, probability, seed, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Place notes using the Thue-Morse aperiodic binary sequence. |
| `transpose(semitones) -> 'PatternBuilder'` | Shift all note pitches up or down. |
| `velocity_shape(low, high) -> 'PatternBuilder'` | Apply organic velocity variation to all notes in the pattern. |


## `Groove`

A timing/velocity template applied to quantized grid positions.

| Method | Description |
|---|---|
| `__init__(offsets, grid, velocities) -> None` |  |
| `from_agr(path) -> "'Groove'"` | Import timing and velocity data from an Ableton .agr groove file. |
| `swing(percent, grid) -> "'Groove'"` | Create a swing groove from a percentage. |


## `MelodicState`

Persistent melodic context that applies NIR scoring to single-note lines.

| Method | Description |
|---|---|
| `__init__(key, mode, low, high, nir_strength, chord_weight, rest_probability, pitch_diversity, tessitura_strength) -> None` | Initialise a melodic state for a given key, mode, and MIDI register. |
| `choose_next(chord_tones, rng, beat, position, contour_target) -> Optional[int]` | Score all pitch-pool candidates and return the chosen pitch, or None for a rest. |
| `clone() -> 'MelodicState'` | An independent copy — settings, factors, pool, and history. |
| `configure_defaults(key, mode) -> None` | Adopt the surrounding key/scale where this state left them unset. |
| `record(pitch) -> None` | Append a pitch to the melodic history (capped at 4 entries). |
| `set_pool(pitches) -> None` | Replace the pitch pool with explicit MIDI pitches — the experimental seam. |


## `Tuning`

A microtonal tuning system expressed as cent offsets from the unison.

| Method | Description |
|---|---|
| `__init__(cents, description) -> None` |  |
| `equal(divisions, period) -> 'Tuning'` | Construct an equal-tempered tuning with ``divisions`` equal steps per period. |
| `from_cents(cents, description) -> 'Tuning'` | Construct a tuning from a list of cent values for degrees 1..N. |
| `from_ratios(ratios, description) -> 'Tuning'` | Construct a tuning from frequency ratios relative to 1/1. |
| `from_scl(source) -> 'Tuning'` | Parse a Scala .scl file. |
| `from_scl_string(text) -> 'Tuning'` | Parse a Scala .scl file from a string (useful for testing). |
| `period_cents *(property)*` | Cent span of one period (typically 1200.0 for octave-repeating scales). |
| `pitch_bend_for_note(midi_note, reference_note, bend_range) -> Tuple[int, float]` | Return ``(nearest_12tet_note, bend_normalized)`` for a MIDI note number. |
| `size *(property)*` | Number of scale degrees per period (the .scl ``count`` line). |


## `Chord`

Represents a chord as a root pitch class and quality.

| Method | Description |
|---|---|
| `__init__(root_pc, quality) -> None` |  |
| `bass_note(root_midi, octave_offset) -> int` | Return the chord root shifted by a number of octaves. |
| `intervals() -> List[int]` | Return the chord intervals for this chord quality. |
| `name() -> str` | Return a human-friendly chord name. |
| `root_note(root_midi) -> int` | Return the MIDI note number for the chord root nearest to *root_midi*. |
| `tones(root, inversion, count) -> List[int]` | Return MIDI note numbers for chord tones starting from a root. |


## `Progression`

A frozen sequence of :class:`ChordSpan` — the governing harmony value.

| Method | Description |
|---|---|
| `__init__(spans, trailing_history) -> None` |  |
| `borrow(slot) -> 'Progression'` | Borrow the chord(s) at the given 1-based slot(s) from the parallel scale. |
| `cadence(name) -> 'Progression'` | Substitute a cadence formula into the tail — the close, named. |
| `chords *(property)*` | The bare chords, one per span (concrete progressions only). |
| `describe(key, scale) -> str` | A readable, one-chord-per-line summary. |
| `elaborate(depth, seed) -> 'Progression'` | Steedman-inspired chord elaboration — approach each chord by fifths. |
| `events() -> Tuple[subsequence.progressions.ChordEvent, ...]` | The realised timeline as a tuple (iteration, materialised). |
| `extend(*extensions, only) -> 'Progression'` | Add chord extensions (``7``/``9``/``11``/``13``/``"sus4"``/...) to every span. |
| `generate(style, bars, beats, key, scale, seed, rng, pins, end, avoid, cadence, dominant_7th, gravity, nir_strength, minor_turnaround_weight, root_diversity) -> 'Progression'` | Generate a progression from a chord-graph walk — the hybrid generator. |
| `inversions(spec) -> 'Progression'` | Set chord inversions — a single int for all spans, or a list cycled per span. |
| `is_concrete *(property)*` | True when every span is key-independent (no romans/degrees). |
| `length *(property)*` | Total length in beats (the sum of span lengths). |
| `loops_on_exhaustion *(property)*` | True when the clock must loop rather than fall through to live stepping. |
| `over(bass, only) -> 'Progression'` | Put the progression over a slash/pedal bass — *the* trance/techno move. |
| `replace(slot, chord) -> 'Progression'` | Replace the chord at a 1-based slot (the span keeps its beats). |
| `resolve(key, scale) -> 'Progression'` | Resolve every key-relative span against a key (name or pitch class). |
| `span_at(beat) -> Tuple[subsequence.progressions.ChordSpan, float, float]` | Return ``(span, start, end)`` for the span sounding at *beat*. |
| `spread(style) -> 'Progression'` | Set the voicing spread: ``"close"``, ``"open"`` (drop-2), or ``"wide"``. |
| `with_rhythm(beats) -> 'Progression'` | Reshape the harmonic rhythm — a scalar for all spans, or a list cycled per span. |


## `ChordSpan`

One chord with a duration and its decoration — the unit of harmonic time.

| Method | Description |
|---|---|
| `__init__(chord, beats, extensions, bass, inversion, spread, extension_intervals) -> None` |  |
| `decorated_intervals() -> List[int]` | Semitone offsets of the decorated voicing (before inversion/spread/bass). |
| `is_concrete *(property)*` | True when the chord (and any pedal bass) needs no key context to sound. |
| `is_decorated *(property)*` | True when the span carries any decoration beyond the bare chord. |
| `label(key_pc, scale) -> str` | A printable chord label: roman text when relative, decorated name when concrete. |
| `resolve(key_pc, scale) -> 'ChordSpan'` | Return a concrete span: romans resolved, bass resolved to a pitch class. |
| `tones(root, count) -> List[int]` | MIDI notes of the decorated voicing nearest *root* (concrete spans only). |


## `PitchSet`

A nameless sonority — a frozen set of absolute MIDI pitches.

| Method | Description |
|---|---|
| `__init__(pitches) -> None` | Normalise any iterable of MIDI pitches into a sorted frozen tuple. |
| `intervals() -> List[int]` | Semitone offsets from the lowest pitch (the ``Chord`` protocol). |
| `name() -> str` | A readable label for describe() output. |
| `tones(root, inversion, count) -> List[int]` | Return the pitches (absolute — *root* is ignored by design). |


## `Motif`

An immutable musical figure: timed note events + control gestures + a length in beats.

| Method | Description |
|---|---|
| `__init__(events, length, controls, fit) -> None` |  |
| `accent(beat, amount) -> 'Motif'` | Add *amount* velocity to every note at the given beat position (0-based beats). |
| `answer(to) -> 'Motif'` | Call → response: re-aim the tail to a stable degree. |
| `cc(control, values, beats, length, probabilities) -> 'Motif'` | Discrete CC writes at beat positions — mirrors ``p.cc()``; names resolve at placement. |
| `cc_ramp(control, start, end, beat_start, beat_end, shape, length, probability) -> 'Motif'` | A CC value swept ``start`` → ``end`` over a beat range — mirrors ``p.cc_ramp()``. |
| `degrees(degrees, beats, velocities, durations, probabilities, length) -> 'Motif'` | A melody written as 1-based scale degrees, one per beat by default. |
| `describe() -> str` | A readable one-line summary: length, notes (pitch@beat), and control gestures. |
| `empty() -> 'Motif'` | The empty motif (zero events, zero length) — the identity for ``then``. |
| `euclidean(pulses, steps, pitch, length, velocities, durations, probabilities) -> 'Motif'` | A euclidean rhythm as a value: *pulses* spread evenly across *steps* over *length* beats. |
| `from_events(events, length, controls) -> 'Motif'` | Build a motif from explicit events (power use; length defaults to the next whole beat). |
| `generate(rhythm, length, scale, contour, end_on, cadence, pins, max_pitches, velocities, durations, seed, rng, state, nir_strength, pitch_diversity, tessitura_strength) -> 'Motif'` | Generate a melodic motif — rhythm first, pitches walked, a value out. |
| `hits(pitch, beats, length, velocities, durations, probabilities) -> 'Motif'` | One pitch (usually a drum name) at a list of beat positions — the ``hit()`` convention. |
| `invert(pivot) -> 'Motif'` | Mirror pitches around a pivot: MIDI content around a MIDI pivot, degree content around a degree pivot (default: the first note's pitch). Drum motifs raise. |
| `join(motifs) -> 'Motif'` | Fold a list of motifs into one with ``then`` (empty list → ``Motif.empty()``). |
| `notes(notes, beats, velocities, durations, probabilities, length) -> 'Motif'` | A melody written as absolute MIDI note numbers (60 = middle C); ``None`` = rest. |
| `nrpn(parameter, values, beats, fine, null_reset, length, probabilities) -> 'Motif'` | Discrete NRPN parameter writes at beat positions — mirrors ``p.nrpn()``. |
| `nrpn_ramp(parameter, start, end, beat_start, beat_end, shape, fine, null_reset, length, probability) -> 'Motif'` | An NRPN value swept over a beat range — mirrors ``p.nrpn_ramp()``. |
| `onsets() -> List[float]` | The note onset beats, in order — ready for rhythm-first generation. |
| `osc(address, values, beats, length, probabilities) -> 'Motif'` | Discrete OSC float sends at beat positions — mirrors ``p.osc()``. |
| `osc_ramp(address, start, end, beat_start, beat_end, shape, length, probability) -> 'Motif'` | An OSC float swept over a beat range — mirrors ``p.osc_ramp()``. |
| `pitch_bend(values, beats, length, probabilities) -> 'Motif'` | Discrete pitch-bend writes (-1.0 to 1.0) at beat positions — mirrors ``p.pitch_bend()``. |
| `pitch_bend_ramp(start, end, beat_start, beat_end, shape, length, probability) -> 'Motif'` | Pitch bend swept ``start`` → ``end`` (-1.0 to 1.0) over a beat range — mirrors ``p.pitch_bend_ramp()``. |
| `pitched(spec) -> 'Motif'` | Replace every pitch with one spec — a kick rhythm becomes a bass line. |
| `preset(name, pitch, length, velocities, durations, probabilities) -> 'Motif'` | A named world-rhythm timeline as a value — ``Motif.preset("son_clave_3_2")``. |
| `quantize(grid) -> 'Motif'` | Snap note onsets to the nearest multiple of *grid* beats (control gestures untouched). |
| `reverse() -> 'Motif'` | Mirror the figure in time; ramps swap direction (a rising sweep falls). |
| `rhythm() -> 'Motif'` | Strip pitches (and control gestures): a reusable rhythmic skeleton. |
| `rotate(beats) -> 'Motif'` | Shift every onset by *beats*, wrapping modulo the length (spans ride along). |
| `rpn(parameter, values, beats, fine, null_reset, length, probabilities) -> 'Motif'` | Discrete RPN parameter writes at beat positions — mirrors ``p.rpn()``. |
| `rpn_ramp(parameter, start, end, beat_start, beat_end, shape, fine, null_reset, length, probability) -> 'Motif'` | An RPN value swept over a beat range — mirrors ``p.rpn_ramp()``. |
| `slice(start, end) -> 'Motif'` | A window onto the motif, on its own authority: events starting outside are dropped; durations and ramp spans truncate at the cut (a truncated ramp ends at its interpolated cut value). Beats shift so the window starts at 0. |
| `stack(other) -> 'Motif'` | Parallel merge (the spelled form of ``&``): event union, length = max. |
| `steps(steps, pitches, velocities, durations, probabilities, step_duration, length) -> 'Motif'` | Grid placement — the ``sequence()`` convention: ``steps`` are 0-based grid indices (sixteenths by default), ``pitches`` a scalar or parallel list of MIDI ints or drum names. |
| `stretch(factor) -> 'Motif'` | Scale time by *factor* (2.0 = half-time feel): beats, durations, spans, and length. |
| `then(other) -> 'Motif'` | Closed sequential concat: glue *other* after this motif into ONE longer motif. |
| `transpose(steps, semitones) -> 'Motif'` | Transpose pitched content; the keyword names the unit. |
| `vary(notes, position, seed, rng, keep_contour) -> 'Motif'` | Replace a few pitches, preserving the rhythm — the smallest variation. |
| `with_velocity(velocity) -> 'Motif'` | Replace every note's velocity (an int, or a ``(low, high)`` random range). |


## `Phrase`

A sequence of Motifs with segmentation preserved.

| Method | Description |
|---|---|
| `__init__(segments, recipe) -> None` | Coerce any iterable of Motifs. |
| `describe() -> str` | A readable summary: total length and each segment on its own line. |
| `develop(motif, bars, plan, seed, beats_per_bar) -> 'Phrase'` | Grow a motif into a phrase by a plan — the phrase generator. |
| `flatten() -> subsequence.motifs.Motif` | Erase segmentation: one long Motif (the monoid homomorphism onto ``then``). |
| `invert(pivot) -> 'Phrase'` | Mirror pitches in every segment around one pivot (see :meth:`Motif.invert`). |
| `length *(property)*` | Total length in beats (sum of segment lengths). |
| `pitched(spec) -> 'Phrase'` | Replace every pitch, segment-wise. |
| `quantize(grid) -> 'Phrase'` | Snap note onsets segment-wise. |
| `replace(position, motif) -> 'Phrase'` | Replace the segment at a 1-based position (musicians count from one). |
| `reroll(bar, bars, seed) -> 'Phrase'` | Regenerate only the named bars — rhythm and boundary pitches kept. |
| `reverse() -> 'Phrase'` | Reverse the whole timeline: segments reverse order AND each reverses internally. |
| `rhythm() -> 'Phrase'` | Strip pitches segment-wise: a phrase-shaped skeleton. |
| `rotate(beats) -> 'Phrase'` | Rotate the whole timeline modulo the total length, then re-segment at the original boundaries. |
| `slice(start, end) -> 'Phrase'` | A window; re-segments at the cut points (partial segments are sliced). |
| `stack(other) -> subsequence.motifs.Motif` | The spelled form of ``&`` — flattens, then merges. |
| `stretch(factor) -> 'Phrase'` | Scale time in every segment (lengths scale with them). |
| `transpose(steps, semitones) -> 'Phrase'` | Transpose every segment (see :meth:`Motif.transpose`). |
| `with_velocity(velocity) -> 'Phrase'` | Replace every note's velocity, segment-wise. |


## `Section`

One section of a form — the payload home.

| Method | Description |
|---|---|
| `__init__(name, bars, energy, key, scale) -> None` |  |


## `Form`

A frozen sequence of Sections — the editable, bindable form value.

| Method | Description |
|---|---|
| `__init__(sections, key, scale) -> None` | Coerce any iterable of Sections / (name, bars) tuples. |
| `bars *(property)*` | Total length in bars. |
| `describe() -> str` | A readable one-section-per-line summary. |
| `insert(slot, section) -> 'Form'` | Insert a section *at* a 1-based slot (existing sections shift right). |
| `replace(slot, section, **changes) -> 'Form'` | Replace the section at a 1-based slot — whole, or by field. |
| `with_energy(energies) -> 'Form'` | Set the energy payload on named sections — ``{"chorus": 0.9}``. |


## Global Functions


| Function | Description |
|---|---|
| `register_scale(name, intervals, qualities) -> None` | Register a custom scale for use with ``p.snap_to_scale()`` and ``scale_pitch_classes()``. |
| `scale_notes(key, mode, low, high, count) -> List[int]` | Return MIDI note numbers for a scale within a pitch range. |
| `bank_select(bank) -> Tuple[int, int]` | Convert a 14-bit MIDI bank number to (MSB, LSB) for use with ``p.program_change()``. |
| `between(low, high, step) -> subsequence.harmonic_rhythm.HarmonicRhythm` | A harmonic rhythm that varies *between* two lengths (in beats). |
| `parse_chord(name) -> subsequence.chords.Chord` | Parse a chord name like ``"Cm7"`` or ``"Dbmaj7"`` into a :class:`Chord`. |
| `register_chord_quality(name, intervals, suffix) -> None` | Register a custom chord quality for use everywhere chords are used. |
| `progression(source, beats, style, bars, key, scale, seed, rng, pins, end, avoid, cadence, dominant_7th, gravity, nir_strength, minor_turnaround_weight, root_diversity) -> subsequence.progressions.Progression` | Build a :class:`Progression` — the lowercase factory. |
| `motif(degrees, beats, velocities, durations, probabilities, length) -> subsequence.motifs.Motif` | The lowercase shortcut: a melody as 1-based scale degrees. |
| `sentence(motif, bars, cadence, seed, beats_per_bar) -> subsequence.motifs.Phrase` | The classical sentence, as a thin combinator — idea, idea, drive, close. |
| `period(antecedent, cadence, beats_per_bar) -> subsequence.motifs.Phrase` | The classical period, as a thin combinator — question, then answer. |
| `cadence_formula(name) -> subsequence.cadences.Cadence` | Look up a cadence by producer name or theory alias, loudly. |
| `vl_distance(source, target, pitch_classes) -> int` | Voice-leading distance between two chords (Tymoczko's taxicab metric). |
| `branch_sequence(pitches, depth, path, mutation, rng) -> List[int]` | Navigate a fractal tree of pitch-sequence transforms and return one variation. |
| `build_metric_weights(time_signature, grid) -> List[float]` | Per-step metric weights for one bar — how "strong" each grid position is. |
| `sieve(classes, hi, lo) -> List[int]` | Xenakis sieve: the sorted integers in ``[lo, hi)`` in any of the classes. |
| `residual_class(modulus, residue) -> subsequence.sequence_utils.Sieve` | A single residual class ``{x : x % modulus == residue}`` as a :class:`Sieve`. |
| `rhythmic_evenness(onsets, grid, normalize) -> float` | How evenly onsets are spread around the cycle (Toussaint's evenness). |
| `offbeatness(onsets, grid) -> int` | How many onsets fall on intrinsically off-beat pulses (Toussaint). |
| `syncopation(onsets, grid, time_signature, weights) -> float` | How much a rhythm pulls away from its metric strong points. |

## Sequence Utilities (`subsequence.sequence_utils`)


Functions for generating and transforming sequences.


| Function | Description |
|---|---|
| `branch_sequence(pitches, depth, path, mutation, rng) -> List[int]` | Navigate a fractal tree of pitch-sequence transforms and return one variation. |
| `build_metric_weights(time_signature, grid) -> List[float]` | Per-step metric weights for one bar — how "strong" each grid position is. |
| `choke(sequence, against, steps, floor) -> List[~T]` | Suppress the steps where a selector is active, keeping the rest. |
| `clamp(value, low, high) -> Union[float, List[float]]` | Bound a value (or list) to the range ``[low, high]``. |
| `combine_densities(layers, strategy) -> Union[float, List[float]]` | Blend several density layers into one consensus density. |
| `constrained_walk(graph, start, length, rng, pins, end, avoid, weight_modifier, before_choice, after_choice) -> List[~T]` | Walk a weighted graph under constraints — the shared hybrid kernel. |
| `cseg(pitches) -> List[int]` | Contour segment: each pitch's rank within the line (Morris's CSEG). |
| `csim(a, b) -> float` | Contour similarity between two equal-length lines (Marvin/Laprade CSIM). |
| `de_bruijn(k, n) -> List[int]` | Generate a de Bruijn sequence B(k, n). |
| `density_spread(value, amount, midpoint) -> Union[float, List[float]]` | Expand or contract a probability/density about a fixed anchor. |
| `density_warp(value, amount) -> Union[float, List[float]]` | Warp a probability/density by a single denser/sparser knob. |
| `fibonacci_rhythm(steps, length) -> List[float]` | Generate beat positions spaced by the golden ratio (Fibonacci spiral). |
| `flip(value, low, high) -> Union[float, List[float]]` | Reflect a value within a range — its complement about the mid-point. |
| `generate_bresenham_sequence(steps, pulses) -> List[int]` | Generate a rhythm using Bresenham's line algorithm. |
| `generate_bresenham_sequence_weighted(steps, weights) -> List[int]` | Generate a sequence that distributes weighted indices across steps. |
| `generate_cellular_automaton_1d(steps, rule, generation, seed) -> List[int]` | Generate a binary sequence using an elementary cellular automaton. |
| `generate_cellular_automaton_2d(rows, cols, rule, generation, seed, density) -> List[List[int]]` | Generate a 2D cellular automaton grid using Life-like rules. |
| `generate_euclidean_sequence(steps, pulses) -> List[int]` | Generate a Euclidean rhythm using Bjorklund's algorithm. |
| `generate_legato_durations(hits) -> List[int]` | Convert a hit list into per-step legato durations. |
| `generate_van_der_corput_sequence(n, base) -> List[float]` | Generate a sequence of n numbers using the van der Corput sequence. |
| `logistic_map(r, steps, x0) -> List[float]` | Generate a deterministic chaos sequence using the logistic map. |
| `lorenz_attractor(steps, dt, sigma, rho, beta, x0, y0, z0) -> List[Tuple[float, float, float]]` | Integrate the Lorenz attractor and return normalised (x, y, z) tuples. |
| `lsystem_expand(axiom, rules, generations, rng) -> str` | Expand an L-system string by applying production rules. |
| `mask(sequence, against, steps, zero) -> List[~T]` | Keep the steps where a selector is active, zeroing the rest. |
| `offbeatness(onsets, grid) -> int` | How many onsets fall on intrinsically off-beat pulses (Toussaint). |
| `perlin_1d(x, seed) -> float` | Generate smooth 1D noise at position *x*. |
| `perlin_1d_sequence(start, spacing, count, seed) -> List[float]` | Generate a sequence of smooth 1D noise values. |
| `perlin_2d(x, y, seed) -> float` | Generate smooth 2D noise at position *(x, y)*. |
| `perlin_2d_grid(x_start, y_start, x_step, y_step, x_count, y_count, seed) -> List[List[float]]` | Generate a 2D grid of smooth noise values. |
| `pink_noise(steps, sources, seed) -> List[float]` | Generate a 1/f (pink) noise sequence using the Voss-McCartney algorithm. |
| `probability_gate(sequence, probability, rng) -> List[int]` | Filter a binary sequence by probability. |
| `random_walk(n, low, high, step, rng, start) -> List[int]` | Generate values that drift by small steps within a range. |
| `reaction_diffusion_1d(width, steps, feed_rate, kill_rate, du, dv) -> List[float]` | Simulate a 1D Gray-Scott reaction-diffusion system. |
| `residual_class(modulus, residue) -> subsequence.sequence_utils.Sieve` | A single residual class ``{x : x % modulus == residue}`` as a :class:`Sieve`. |
| `rhythmic_evenness(onsets, grid, normalize) -> float` | How evenly onsets are spread around the cycle (Toussaint's evenness). |
| `rotate(indices, shift, length) -> List[int]` | Circularly rotate step indices by the specified amount, wrapping at *length*. |
| `scale_clamp(value, in_min, in_max, out_min, out_max) -> float` | Scale a value from an input range to an output range and clamp the result. |
| `self_avoiding_walk(n, low, high, rng, start) -> List[int]` | Generate a self-avoiding random walk on an integer lattice. |
| `sequence_to_indices(sequence) -> List[int]` | Extract step indices where hits occur in a binary sequence. |
| `shuffled_choices(pool, n, rng) -> List[~T]` | Choose N items from a pool with no immediate repetition. |
| `sieve(classes, hi, lo) -> List[int]` | Xenakis sieve: the sorted integers in ``[lo, hi)`` in any of the classes. |
| `syncopation(onsets, grid, time_signature, weights) -> float` | How much a rhythm pulls away from its metric strong points. |
| `threshold(sequence, cutoff) -> List[int]` | Gate a per-step field into a deterministic 0/1 sequence. |
| `thue_morse(n) -> List[int]` | Generate the Thue-Morse sequence. |
| `tile(sequence, length) -> List[~T]` | Cycle a sequence to an exact length. |
| `vl_distance(source, target, pitch_classes) -> int` | Voice-leading distance between two chords (Tymoczko's taxicab metric). |
| `warp_stack(value, amounts) -> Union[float, List[float]]` | Apply several density knobs to ``value`` so they compound. |
| `weighted_choice(options, rng) -> ~T` | Pick one item from a list of (value, weight) pairs. |