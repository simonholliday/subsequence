# Subsequence API Cheat Sheet

This document provides a quick overview of the public classes, methods, and functions available in the Subsequence API.

## `Composition`

The top-level controller for a musical piece.

| Method | Description |
|---|---|
| `__init__(output_device, bpm, time_signature, key, seed, record, record_filename, zero_indexed_channels, latency_ms) -> None` | Initialize a new composition. |
| `builder_bar *(property)*` | Current bar index used by pattern builders. |
| `cc_forward(cc, output, channel, output_channel, mode, input_device, output_device) -> None` | Forward an incoming MIDI CC to the MIDI output in real-time. |
| `cc_map(cc, key, channel, min_val, max_val, input_device) -> None` | Map an incoming MIDI CC to a ``composition.data`` key. |
| `chords(channel, progression, harmonic_rhythm, bars, beats, voicing, velocity, detached, root, key, seed, device, mirrors) -> subsequence.progression.ChordTimeline` | Declare a self-contained chord part: a progression at a chosen harmonic rhythm. |
| `clear_tweak(name, *param_names) -> None` | Remove tweaked parameters from a running pattern. |
| `clock_output(enabled) -> None` | Send MIDI timing clock to connected hardware. |
| `display(enabled, grid, grid_scale) -> None` | Enable or disable the live terminal dashboard. |
| `form(sections, loop, start) -> None` | Define the structure (sections) of the composition. |
| `form_jump(section_name) -> None` | Jump the form to a named section immediately. |
| `form_next(section_name) -> None` | Queue the next section — takes effect when the current section ends. |
| `form_state *(property)*` | The active ``subsequence.form_state.FormState``, or ``None`` if ``form()`` has not been called. |
| `freeze(bars) -> 'Progression'` | Capture a chord progression from the live harmony engine. |
| `get_tweaks(name) -> Dict[str, Any]` | Return a copy of the current tweaks for a running pattern. |
| `harmonic_state *(property)*` | The active ``HarmonicState``, or ``None`` if ``harmony()`` has not been called. |
| `harmony(style, cycle_beats, dominant_7th, gravity, nir_strength, minor_turnaround_weight, root_diversity, reschedule_lookahead) -> None` | Configure the harmonic logic and chord change intervals. |
| `hotkey(key, action, quantize, label) -> None` | Register a single-key shortcut that fires during playback. |
| `hotkeys(enabled) -> None` | Enable or disable the global hotkey listener. |
| `is_clock_following *(property)*` | True if either the primary or any additional device is following external clock. |
| `layer(*builder_fns, channel, beats, bars, steps, unit, drum_note_map, cc_name_map, nrpn_name_map, reschedule_lookahead, voice_leading, device, mirrors) -> None` | Combine multiple functions into a single MIDI pattern. |
| `link(quantum) -> 'Composition'` | Enable Ableton Link tempo and phase synchronisation. |
| `live(port) -> None` | Enable the live coding eval server. |
| `live_info() -> Dict[str, Any]` | Return a dictionary containing the current state of the composition. |
| `load_patterns(source, source_label) -> None` | Compile and apply a pattern-source string to the composition. |
| `midi_input(device, clock_follow, name) -> None` | Configure a MIDI input device for external sync and MIDI messages. |
| `midi_output(device, name, latency_ms) -> int` | Register an additional MIDI output device. |
| `mirror(name, device, channel, drum_note_map) -> None` | Add a mirror destination to a running pattern. |
| `mute(name) -> None` | Mute a running pattern by name. |
| `on_event(event_name, callback) -> None` | Register a callback for a sequencer event (e.g., "bar", "start", "stop"). |
| `osc(receive_port, send_port, send_host, receive_host) -> None` | Enable bi-directional Open Sound Control (OSC). |
| `osc_map(address, handler) -> None` | Register a custom OSC handler. |
| `pattern(channel, beats, bars, steps, unit, drum_note_map, cc_name_map, nrpn_name_map, reschedule_lookahead, voice_leading, device, mirrors) -> Callable` | Register a function as a repeating MIDI pattern. |
| `play() -> None` | Start the composition. |
| `render(bars, filename, max_minutes) -> None` | Render the composition to a MIDI file without real-time playback. |
| `running_patterns *(property)*` | The currently active patterns, keyed by name. |
| `schedule(fn, cycle_beats, reschedule_lookahead, wait_for_initial, defer) -> None` | Register a custom function to run on a repeating beat-based cycle. |
| `section_chords(section_name, progression) -> None` | Bind a frozen :class:`Progression` to a named form section. |
| `seed(value) -> None` | Set a random seed for deterministic, repeatable playback. |
| `sequencer *(property)*` | The underlying ``Sequencer`` instance. |
| `set_bpm(bpm) -> None` | Instantly change the tempo. |
| `target_bpm(bpm, bars, shape) -> None` | Smoothly ramp the tempo to a target value over a number of bars. |
| `trigger(fn, channel, beats, bars, steps, unit, quantize, drum_note_map, cc_name_map, nrpn_name_map, chord, device, mirrors) -> None` | Trigger a one-shot pattern immediately or on a quantized boundary. |
| `tuning(source, cents, ratios, equal, bend_range, channels, reference_note, exclude_drums) -> None` | Set a global microtonal tuning for the composition. |
| `tweak(name, **kwargs) -> None` | Override parameters for a running pattern. |
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
| `__init__(pattern, cycle, conductor, drum_note_map, cc_name_map, nrpn_name_map, section, bar, rng, tweaks, default_grid, data, key) -> None` | Initialize the builder with pattern context, cycle count, and optional section info. |
| `apply_tuning(tuning, bend_range, channels, reference_note) -> 'PatternBuilder'` | Apply a microtonal tuning to this pattern via pitch bend injection. |
| `arpeggio(pitches, spacing, velocity, duration, direction, rng) -> 'PatternBuilder'` | Cycle through a list of pitches at regular beat intervals. |
| `bend(note, amount, start, end, shape, resolution) -> 'subsequence.pattern_builder.PatternBuilder'` | Bend a specific note by index. |
| `branch(seed, depth, path, mutation, velocity, duration, spacing) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melodic variation by navigating a fractal tree of transforms. |
| `bresenham(pitch, pulses, velocity, duration, dropout, no_overlap, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a rhythm using the Bresenham line algorithm. |
| `bresenham_poly(parts, velocity, duration, grid, dropout, no_overlap, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Distribute multiple drum voices across the pattern using weighted Bresenham. |
| `broken_chord(chord_obj, root, order, spacing, velocity, duration, inversion) -> 'PatternBuilder'` | Play a chord as an arpeggio in a specific or random order. |
| `build_ghost_bias(grid, bias) -> List[float]` | Build probability weights for ghost notes or other generative functions. |
| `c *(property)*` | Alias for self.conductor. |
| `cc(control, value, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single CC message at a beat position. |
| `cc_ramp(control, start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate a CC value over a beat range. |
| `cellular(pitch, rule, generation, velocity, duration, no_overlap, dropout, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate an evolving rhythm using a 1D cellular automaton. |
| `cellular_1d(pitch, rule, generation, velocity, duration, no_overlap, dropout, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate an evolving rhythm using a 1D cellular automaton. |
| `cellular_2d(pitches, rule, generation, velocity, duration, no_overlap, dropout, seed, density, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate polyphonic patterns using a 2D Life-like cellular automaton. |
| `chord(chord_obj, root, velocity, sustain, duration, inversion, count, legato, detached, beat) -> 'PatternBuilder'` | Place a chord at ``beat`` (the start of the pattern by default). |
| `de_bruijn(pitches, window, spacing, velocity, duration) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melody that exhaustively traverses all pitch subsequences. |
| `detached(beats) -> 'PatternBuilder'` | Shorten note durations so a guaranteed silence precedes the next onset. |
| `double_time() -> 'PatternBuilder'` | Compress all notes into the first half of the pattern, doubling the speed. |
| `drone(pitch, beat, velocity) -> 'PatternBuilder'` | A musical alias for `note_on`. Places a raw Note On event without a duration, typically used for sustained notes that span multiple cycles. Must be silenced later using `drone_off()`. |
| `drone_off(pitch) -> 'PatternBuilder'` | A musical alias for `note_off`. Places a raw Note Off event at beat 0.0. Used to stop a sequence started by `drone()`. |
| `dropout(probability, rng) -> 'PatternBuilder'` | Randomly remove notes from the pattern. |
| `duck_map(steps, floor, grid) -> List[float]` | Build a per-step velocity multiplier list for sidechain-style ducking. |
| `euclidean(pitch, pulses, velocity, duration, dropout, no_overlap, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a Euclidean rhythm. |
| `every(n, fn) -> 'PatternBuilder'` | Apply a transformation every Nth cycle. |
| `evolve(pitches, steps, drift, velocity, duration, spacing) -> 'subsequence.pattern_builder.PatternBuilder'` | Loop a pitch sequence that gradually mutates each cycle. |
| `fibonacci(pitch, steps, velocity, duration) -> 'subsequence.pattern_builder.PatternBuilder'` | Place notes at golden-ratio-spaced beat positions (Fibonacci spiral timing). |
| `fill(pitch, spacing, velocity, duration) -> 'PatternBuilder'` | Fill the pattern with a note repeating at a fixed beat interval. |
| `ghost_fill(pitch, density, velocity, bias, no_overlap, grid, duration, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Fill the pattern with probability-biased ghost notes. |
| `grid *(property)*` | Number of grid slots in this pattern (e.g. 16 for a 4-beat sixteenth-note pattern). |
| `groove(template, strength) -> 'PatternBuilder'` | Apply a groove template to all notes in the pattern. |
| `half_time() -> 'PatternBuilder'` | Expand all notes by factor of 2, halving the speed. Notes that fall outside the pattern length are removed. |
| `hit(pitch, beats, velocity, duration) -> 'PatternBuilder'` | Place multiple short 'hits' at a list of beat positions. |
| `hit_steps(pitch, steps, velocity, duration, grid, probability, rng) -> 'PatternBuilder'` | Place short hits at specific step (grid) positions. |
| `invert(pivot) -> 'PatternBuilder'` | Invert all pitches around a pivot note. |
| `legato(ratio) -> 'PatternBuilder'` | Adjust note durations to fill the gap until the next note. |
| `lorenz(pitches, spacing, velocity, duration, dt, sigma, rho, beta, x0, y0, z0, mapping) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a note sequence driven by the Lorenz strange attractor. |
| `lsystem(pitch_map, axiom, rules, generations, spacing, velocity, duration) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a note sequence using L-system string rewriting. |
| `markov(transitions, pitch_map, velocity, duration, spacing, start) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a sequence by walking a first-order Markov chain. |
| `melody(state, spacing, velocity, duration, chord_tones) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melodic line by querying a persistent :class:`~subsequence.melodic_state.MelodicState`. |
| `note(pitch, beat, velocity, duration) -> 'PatternBuilder'` | Place a single MIDI note at a specific beat position. |
| `note_off(pitch, beat) -> 'PatternBuilder'` | Place an explicit Note Off event to silence a drone. |
| `note_on(pitch, beat, velocity) -> 'PatternBuilder'` | Place an explicit Note On event without a duration. Useful for drones or infinite sustains. Must be paired with a `note_off()` later to silence the note. |
| `nrpn(parameter, value, beat, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single NRPN parameter write at a beat position. |
| `nrpn_ramp(parameter, start, end, beat_start, beat_end, resolution, shape, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an NRPN value over a beat range. |
| `osc(address, *args, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send an OSC message at a beat position. |
| `osc_ramp(address, start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an OSC float value over a beat range. |
| `param(name, default) -> Any` | Read a tweakable parameter for this pattern. |
| `phrase(length) -> subsequence.pattern_builder.Phrase` | Return the current bar's position within a repeating musical phrase. |
| `pitch_bend(value, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single pitch bend message at a beat position. |
| `pitch_bend_ramp(start, end, beat_start, beat_end, resolution, shape) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate pitch bend over a beat range. |
| `portamento(time, shape, resolution, bend_range, wrap) -> 'subsequence.pattern_builder.PatternBuilder'` | Glide between all consecutive notes using pitch bend. |
| `program_change(program, beat, bank_msb, bank_lsb) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a Program Change message, optionally preceded by bank select. |
| `progression(source, harmonic_rhythm, key, seed) -> subsequence.progression.ChordTimeline` | Realise a chord progression across the pattern, returning it to place yourself. |
| `quantize(key, mode, strength) -> 'PatternBuilder'` | Snap all notes in the pattern to the nearest pitch in a scale. |
| `randomize(timing, velocity, rng) -> 'PatternBuilder'` | Add random variations to note timing and velocity. |
| `ratchet(subdivisions, pitch, probability, velocity_start, velocity_end, shape, gate, steps, grid, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Subdivide existing notes into rapid repeated hits (rolls/ratchets). |
| `reaction_diffusion(pitch, threshold, velocity, duration, feed_rate, kill_rate, steps, no_overlap, dropout, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a rhythm from a 1D Gray-Scott reaction-diffusion simulation. |
| `reverse() -> 'PatternBuilder'` | Flip the pattern backwards in time. |
| `rpn(parameter, value, beat, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a single RPN parameter write at a beat position. |
| `rpn_ramp(parameter, start, end, beat_start, beat_end, resolution, shape, fine, null_reset) -> 'subsequence.pattern_builder.PatternBuilder'` | Interpolate an RPN value over a beat range. |
| `scale_velocities(factors, grid) -> 'PatternBuilder'` | Scale note velocities by a per-step multiplier list. |
| `self_avoiding_walk(pitches, spacing, velocity, duration, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Generate a melody using a self-avoiding random walk. |
| `seq(notation, pitch, velocity) -> 'PatternBuilder'` | Build a pattern using an expressive string-based 'mini-notation'. |
| `sequence(steps, pitches, velocities, durations, grid, probability, rng) -> 'PatternBuilder'` | A multi-parameter step sequencer. |
| `set_length(length) -> 'PatternBuilder'` | Dynamically change the length of the pattern. |
| `shift(steps, grid) -> 'PatternBuilder'` | Rotate the pattern by a number of grid steps. |
| `signal(name) -> float` | Read a conductor signal at the current bar. |
| `silence(beat) -> 'PatternBuilder'` | Sends an 'All Notes Off' (CC 123) and 'All Sound Off' (CC 120) message on the pattern's channel to immediately silence any ringing notes or drones. |
| `slide(notes, steps, time, shape, resolution, bend_range, wrap, extend) -> 'subsequence.pattern_builder.PatternBuilder'` | TB-303-style selective slide into specific notes. |
| `staccato(beats) -> 'PatternBuilder'` | Set all note durations to a fixed length in beats. |
| `strum(chord_obj, root, velocity, sustain, duration, inversion, count, offset, direction, legato, detached, beat) -> 'PatternBuilder'` | Play a chord with a small time offset between each note (strum effect). |
| `swing(amount, grid, strength) -> 'PatternBuilder'` | Apply swing feel to all notes in the pattern. |
| `sysex(data, beat) -> 'subsequence.pattern_builder.PatternBuilder'` | Send a System Exclusive (SysEx) message at a beat position. |
| `thin(pitch, strategy, amount, grid, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Remove notes from the pattern based on their rhythmic position. |
| `thue_morse(pitch, velocity, duration, pitch_b, velocity_b, no_overlap, dropout, rng) -> 'subsequence.pattern_builder.PatternBuilder'` | Place notes using the Thue-Morse aperiodic binary sequence. |
| `transpose(semitones) -> 'PatternBuilder'` | Shift all note pitches up or down. |
| `velocity_ramp(low, high, shape, grid) -> List[int]` | Build a per-step velocity list that ramps from *low* to *high*. |
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
| `__init__(key, mode, low, high, nir_strength, chord_weight, rest_probability, pitch_diversity) -> None` | Initialise a melodic state for a given key, mode, and MIDI register. |
| `choose_next(chord_tones, rng) -> int \| None` | Score all pitch-pool candidates and return the chosen pitch, or None for a rest. |


## Global Functions


| Function | Description |
|---|---|
| `register_scale(name, intervals, qualities) -> None` | Register a custom scale for use with ``p.quantize()`` and ``scale_pitch_classes()``. |
| `scale_notes(key, mode, low, high, count) -> List[int]` | Return MIDI note numbers for a scale within a pitch range. |
| `bank_select(bank) -> Tuple[int, int]` | Convert a 14-bit MIDI bank number to (MSB, LSB) for use with ``p.program_change()``. |
| `between(low, high, step) -> subsequence.harmonic_rhythm.HarmonicRhythm` | A harmonic rhythm that varies *between* two lengths (in beats). |
| `parse_chord(name) -> subsequence.chords.Chord` | Parse a chord name like ``"Cm7"`` or ``"Dbmaj7"`` into a :class:`Chord`. |

## Sequence Utilities (`subsequence.sequence_utils`)


Functions for generating and transforming sequences.


| Function | Description |
|---|---|
| `de_bruijn(k, n) -> List[int]` | Generate a de Bruijn sequence B(k, n). |
| `fibonacci_rhythm(steps, length) -> List[float]` | Generate beat positions spaced by the golden ratio (Fibonacci spiral). |
| `generate_bresenham_sequence(steps, pulses) -> List[int]` | Generate a rhythm using Bresenham's line algorithm. |
| `generate_bresenham_sequence_weighted(steps, weights) -> List[int]` | Generate a sequence that distributes weighted indices across steps. |
| `generate_cellular_automaton(steps, rule, generation, seed) -> List[int]` | Generate a binary sequence using an elementary cellular automaton. |
| `generate_cellular_automaton_1d(steps, rule, generation, seed) -> List[int]` | Generate a binary sequence using an elementary cellular automaton. |
| `generate_cellular_automaton_2d(rows, cols, rule, generation, seed, density) -> List[List[int]]` | Generate a 2D cellular automaton grid using Life-like rules. |
| `generate_euclidean_sequence(steps, pulses) -> List[int]` | Generate a Euclidean rhythm using Bjorklund's algorithm. |
| `generate_legato_durations(hits) -> List[int]` | Convert a hit list into per-step legato durations. |
| `generate_van_der_corput_sequence(n, base) -> List[float]` | Generate a sequence of n numbers using the van der Corput sequence. |
| `logistic_map(r, steps, x0) -> List[float]` | Generate a deterministic chaos sequence using the logistic map. |
| `lorenz_attractor(steps, dt, sigma, rho, beta, x0, y0, z0) -> List[Tuple[float, float, float]]` | Integrate the Lorenz attractor and return normalised (x, y, z) tuples. |
| `lsystem_expand(axiom, rules, generations, rng) -> str` | Expand an L-system string by applying production rules. |
| `perlin_1d(x, seed) -> float` | Generate smooth 1D noise at position *x*. |
| `perlin_1d_sequence(start, spacing, count, seed) -> List[float]` | Generate a sequence of smooth 1D noise values. |
| `perlin_2d(x, y, seed) -> float` | Generate smooth 2D noise at position *(x, y)*. |
| `perlin_2d_grid(x_start, y_start, x_step, y_step, x_count, y_count, seed) -> List[List[float]]` | Generate a 2D grid of smooth noise values. |
| `pink_noise(steps, sources, seed) -> List[float]` | Generate a 1/f (pink) noise sequence using the Voss-McCartney algorithm. |
| `probability_gate(sequence, probability, rng) -> List[int]` | Filter a binary sequence by probability. |
| `random_walk(n, low, high, step, rng, start) -> List[int]` | Generate values that drift by small steps within a range. |
| `reaction_diffusion_1d(width, steps, feed_rate, kill_rate, du, dv) -> List[float]` | Simulate a 1D Gray-Scott reaction-diffusion system. |
| `roll(indices, shift, length) -> List[int]` | Circularly shift step indices by the specified amount. |
| `rotate(indices, shift, length) -> List[int]` | Circularly shift step indices by the specified amount. |
| `scale_clamp(value, in_min, in_max, out_min, out_max) -> float` | Scale a value from an input range to an output range and clamp the result. |
| `self_avoiding_walk(n, low, high, rng, start) -> List[int]` | Generate a self-avoiding random walk on an integer lattice. |
| `sequence_to_indices(sequence) -> List[int]` | Extract step indices where hits occur in a binary sequence. |
| `shuffled_choices(pool, n, rng) -> List[~T]` | Choose N items from a pool with no immediate repetition. |
| `thue_morse(n) -> List[int]` | Generate the Thue-Morse sequence. |
| `weighted_choice(options, rng) -> ~T` | Pick one item from a list of (value, weight) pairs. |