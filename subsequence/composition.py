import asyncio
import inspect
import itertools
import logging
import random
import signal
import typing

import subsequence.chord_graphs
import subsequence.display
import subsequence.harmonic_state
import subsequence.live_server
import subsequence.osc
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer
import subsequence.voicings
import subsequence.weighted_graph
import subsequence.conductor


logger = logging.getLogger(__name__)


def _fn_has_parameter (fn: typing.Callable, name: str) -> bool:

	"""Check whether a callable accepts a parameter with the given name."""

	return name in inspect.signature(fn).parameters


class SectionInfo:

	"""
	An immutable snapshot of the current section in the compositional form.
	
	Patterns read `p.section` to make context-aware decisions, such as increasing
	intensity as a section progresses or playing variation only in certain blocks.
	
	Attributes:
		name: The string name of the section (e.g., "verse").
		bar: The current bar index within this section (0-indexed).
		bars: Total number of bars in this section.
		index: The global index of this section in the form's timeline.

	Example:
		```python
		@composition.pattern(channel=9)
		def drums(p):
			# Always play a basic kick
			p.hit_steps("kick", [0, 8])

			# Only add snare and hats during the "chorus"
			if p.section and p.section.name == "chorus":
				p.hit_steps("snare", [4, 12])
				
				# Use .progress (0.0 to 1.0) to build a riser
				vel = int(60 + 40 * p.section.progress)
				p.hit_steps("hh", list(range(16)), velocity=vel)
		```
	"""

	def __init__ (self, name: str, bar: int, bars: int, index: int) -> None:

		"""Store the section name, bar position, total bars, and form index."""

		self.name = name
		self.bar = bar
		self.bars = bars
		self.index = index

	@property
	def progress (self) -> float:

		"""Return how far through this section we are (0.0 to ~1.0)."""

		if self.bars <= 0:
			return 0.0

		return self.bar / self.bars

	@property
	def first_bar (self) -> bool:

		"""Return True if this is the first bar of the section."""

		return self.bar == 0

	@property
	def last_bar (self) -> bool:

		"""Return True if this is the last bar of the section."""

		return self.bar == self.bars - 1


class FormState:

	"""Track compositional form as a sequence of named sections with bar durations."""

	def __init__ (
		self,
		sections: typing.Union[
			typing.List[typing.Tuple[str, int]],
			typing.Iterator[typing.Tuple[str, int]],
			typing.Dict[str, typing.Tuple[int, typing.Optional[typing.List[typing.Tuple[str, int]]]]]
		],
		loop: bool = False,
		start: typing.Optional[str] = None,
		rng: typing.Optional[random.Random] = None
	) -> None:

		"""Initialize from a list, iterator, or dict of weighted section transitions."""

		self._current: typing.Optional[typing.Tuple[str, int]] = None
		self._bar_in_section: int = 0
		self._section_index: int = 0
		self._total_bars: int = 0
		self._finished: bool = False

		# Graph mode state (only set when sections is a dict).
		self._graph: typing.Optional[subsequence.weighted_graph.WeightedGraph] = None
		self._section_bars: typing.Optional[typing.Dict[str, int]] = None
		self._rng: random.Random = rng or random.Random()
		self._iterator: typing.Optional[typing.Iterator[typing.Tuple[str, int]]] = None

		# Terminal sections (graph mode only): sections with None transitions.
		self._terminal_sections: typing.Set[str] = set()

		if isinstance(sections, dict):
			# Graph mode: build a WeightedGraph from the dict.
			self._graph = subsequence.weighted_graph.WeightedGraph()
			self._section_bars = {}

			for name, (bars, transitions) in sections.items():
				self._section_bars[name] = bars
				if transitions is None:
					self._terminal_sections.add(name)
				else:
					for target, weight in transitions:
						self._graph.add_transition(name, target, weight)

			start_name = start if start is not None else next(iter(sections))

			if start_name not in self._section_bars:
				raise ValueError(f"Start section '{start_name}' not found in form definition")

			self._current = (start_name, self._section_bars[start_name])

		elif isinstance(sections, list):
			# List mode: convert to iterator, optionally cycling.
			self._iterator = itertools.cycle(sections) if loop else iter(sections)

			try:
				self._current = next(self._iterator)
			except StopIteration:
				self._finished = True

		else:
			# Generator/iterator mode: use directly.
			self._iterator = sections

			try:
				self._current = next(self._iterator)
			except StopIteration:
				self._finished = True

	def advance (self) -> bool:

		"""Advance one bar, transitioning to the next section when needed, returning True if section changed."""

		if self._finished:
			return False

		self._bar_in_section += 1
		self._total_bars += 1

		assert self._current is not None, "Form state invariant: current should not be None when not finished"
		_, current_bars = self._current

		if self._bar_in_section >= current_bars:

			if self._graph is not None:
				# Graph mode: choose next section via weighted graph.
				assert self._current is not None
				current_name = self._current[0]

				if current_name in self._terminal_sections:
					# Terminal section - form ends.
					self._finished = True
					self._current = None
					return True

				assert self._section_bars is not None
				next_name = self._graph.choose_next(current_name, self._rng)
				self._current = (next_name, self._section_bars[next_name])
				self._section_index += 1
				self._bar_in_section = 0
				return True

			else:
				# Iterator mode.
				try:
					assert self._iterator is not None
					self._current = next(self._iterator)
					self._section_index += 1
					self._bar_in_section = 0
					return True

				except StopIteration:
					self._finished = True
					self._current = None
					return True

		return False

	def get_section_info (self) -> typing.Optional[SectionInfo]:

		"""Return current section info, or None if the form is exhausted."""

		if self._finished or self._current is None:
			return None

		name, bars = self._current

		return SectionInfo(
			name = name,
			bar = self._bar_in_section,
			bars = bars,
			index = self._section_index
		)

	@property
	def total_bars (self) -> int:

		"""Return the global bar count since the form started."""

		return self._total_bars


class _InjectedChord:

	"""
	Wraps a Chord with key context so tones() transposes correctly.
	"""

	def __init__ (self, chord: typing.Any, key_root_pc: int, voice_leading_state: typing.Optional[subsequence.voicings.VoiceLeadingState] = None) -> None:

		"""
		Store the chord and key root pitch class for transposition.
		"""

		self._chord = chord
		self._key_root_pc = key_root_pc
		self._voice_leading_state = voice_leading_state

	def root_midi (self, base: int) -> int:

		"""
		Compute the MIDI root for this chord relative to a base note and key.
		"""

		offset = (self._chord.root_pc - self._key_root_pc) % 12

		return base + offset  # type: ignore[no-any-return]

	def tones (self, root: int, inversion: int = 0, count: typing.Optional[int] = None) -> typing.List[int]:

		"""Return MIDI note numbers transposed to the correct chord root.

		When voice leading is active, the best inversion is chosen
		automatically and the ``inversion`` parameter is ignored.

		When ``count`` is set, the chord intervals cycle into higher
		octaves until ``count`` notes are produced.
		"""

		midi_root = self.root_midi(root)
		intervals = self._chord.intervals()

		if self._voice_leading_state is not None:
			base = self._voice_leading_state.next(intervals, midi_root)
			if count is not None and count > len(base):
				n = len(base)
				base_intervals = [p - base[0] for p in base]
				return [base[0] + base_intervals[i % n] + 12 * (i // n) for i in range(count)]
			return base

		if inversion != 0:
			intervals = subsequence.voicings.invert_chord(intervals, inversion)

		if count is not None:
			n = len(intervals)
			return [midi_root + intervals[i % n] + 12 * (i // n) for i in range(count)]

		return [midi_root + interval for interval in intervals]

	def intervals (self) -> typing.List[int]:

		"""
		Forward to the underlying chord's intervals.
		"""

		return self._chord.intervals()  # type: ignore[no-any-return]

	def name (self) -> str:

		"""
		Forward to the underlying chord's name.
		"""

		return self._chord.name()  # type: ignore[no-any-return]


async def schedule_harmonic_clock (
	sequencer: subsequence.sequencer.Sequencer,
	harmonic_state: subsequence.harmonic_state.HarmonicState,
	cycle_beats: int,
	reschedule_lookahead: float = 1
) -> None:

	"""
	Schedule composition-level harmonic changes on a repeating beat interval.
	"""

	def advance_harmony (pulse: int) -> None:

		"""
		Advance the harmonic state on the composition clock.
		"""

		harmonic_state.step()

	await sequencer.schedule_callback_repeating(
		callback = advance_harmony,
		interval_beats = cycle_beats,
		start_pulse = 0,
		reschedule_lookahead = reschedule_lookahead
	)


def _make_safe_callback (fn: typing.Callable) -> typing.Callable[[int], None]:

	"""Wrap a user function as a fire-and-forget callback that never blocks the clock."""

	is_async = asyncio.iscoroutinefunction(fn)

	async def _execute () -> None:

		"""Run the user function with error handling and optional threading."""

		try:

			if is_async:
				await fn()

			else:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, fn)

		except Exception as exc:
			logger.warning(f"Scheduled task {fn.__name__!r} failed: {exc}")

	def wrapper (pulse: int) -> None:

		"""Spawn the task in the background without blocking the sequencer."""

		asyncio.create_task(_execute())

	return wrapper


async def schedule_task (
	sequencer: subsequence.sequencer.Sequencer,
	fn: typing.Callable,
	cycle_beats: int,
	reschedule_lookahead: int = 1
) -> None:

	"""Schedule a non-blocking repeating task on the sequencer's beat clock."""

	wrapped = _make_safe_callback(fn)

	await sequencer.schedule_callback_repeating(
		callback = wrapped,
		interval_beats = cycle_beats,
		start_pulse = 0,
		reschedule_lookahead = reschedule_lookahead
	)


async def schedule_form (
	sequencer: subsequence.sequencer.Sequencer,
	form_state: FormState,
	reschedule_lookahead: int = 1
) -> None:

	"""Schedule the form state to advance each bar."""

	# Log the initial section.
	initial_section = form_state.get_section_info()
	if initial_section:
		logger.info(f"Form: {initial_section.name}")

	def advance_form (pulse: int) -> None:

		"""Advance the form by one bar, logging section changes."""

		section_changed = form_state.advance()

		if section_changed:
			section = form_state.get_section_info()
			if section:
				logger.info(f"Form: {section.name}")
			else:
				logger.info("Form: finished")

	await sequencer.schedule_callback_repeating(
		callback = advance_form,
		interval_beats = 4,
		start_pulse = 0,
		reschedule_lookahead = reschedule_lookahead
	)


async def schedule_patterns (
	sequencer: subsequence.sequencer.Sequencer,
	patterns: typing.Iterable[subsequence.pattern.Pattern],
	start_pulse: int = 0
) -> None:

	"""
	Schedule a collection of repeating patterns from a shared start pulse.
	"""

	for pattern in patterns:
		await sequencer.schedule_pattern_repeating(pattern, start_pulse=start_pulse)


async def run_until_stopped (sequencer: subsequence.sequencer.Sequencer) -> None:

	"""
	Run the sequencer until a stop signal is received.
	"""

	logger.info("Playing sequence. Press Ctrl+C to stop.")

	await sequencer.start()

	stop_event = asyncio.Event()
	loop = asyncio.get_running_loop()

	def _request_stop () -> None:

		"""
		Signal handler to request a clean shutdown.
		"""

		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(sig, _request_stop)

	assert sequencer.task is not None, "Sequencer task should exist after start()"
	await asyncio.wait(
		[asyncio.create_task(stop_event.wait()), sequencer.task],
		return_when = asyncio.FIRST_COMPLETED
	)

	await sequencer.stop()


class _PendingPattern:

	"""
	Holds decorator arguments and builder function until play() is called.
	"""

	def __init__ (
		self,
		builder_fn: typing.Callable,
		channel: int,
		length: float,
		drum_note_map: typing.Optional[typing.Dict[str, int]],
		reschedule_lookahead: float,
		voice_leading: bool = False
	) -> None:

		"""
		Store pattern registration details for deferred scheduling.
		"""

		self.builder_fn = builder_fn
		self.channel = channel
		self.length = length
		self.drum_note_map = drum_note_map
		self.reschedule_lookahead = reschedule_lookahead
		self.voice_leading = voice_leading


class _PendingScheduled:

	"""Holds a user function and cycle interval for deferred scheduling."""

	def __init__ (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int) -> None:

		"""Store the function and scheduling parameters."""

		self.fn = fn
		self.cycle_beats = cycle_beats
		self.reschedule_lookahead = reschedule_lookahead


class Composition:

	"""
	The top-level controller for a musical piece.
	
	The `Composition` object manages the global clock (Sequencer), the harmonic
	progression (HarmonicState), the song structure (FormState), and all MIDI patterns.
	It serves as the main entry point for defining your music.
	
	Typical workflow:
	1. Initialize `Composition` with BPM and Key.
	2. Define harmony and form (optional).
	3. Register patterns using the `@composition.pattern` decorator.
	4. Call `composition.play()` to start the music.
	"""

	def __init__ (self, output_device: typing.Optional[str] = None, bpm: float = 120, key: typing.Optional[str] = None, seed: typing.Optional[int] = None) -> None:

		"""
		Initialize a new composition.

		Parameters:
			output_device: The name of the MIDI output port to use. If `None`, 
				Subsequence will attempt to find a device, prompting if necessary.
			bpm: Initial tempo in beats per minute (default 120).
			key: The root key of the piece (e.g., "C", "F#", "Bb").
				Required if you plan to use `harmony()`.
			seed: An optional integer for deterministic randomness. When set, 
				every random decision (chord choices, drum probability, etc.) 
				will be identical on every run.

		Example:
			```python
			comp = subsequence.Composition(bpm=128, key="Eb", seed=123)
			```
		"""

		self.output_device = output_device
		self.bpm = bpm
		self.key = key
		self._seed: typing.Optional[int] = seed

		self._sequencer = subsequence.sequencer.Sequencer(
			output_device_name = output_device,
			initial_bpm = bpm
		)

		self._harmonic_state: typing.Optional[subsequence.harmonic_state.HarmonicState] = None
		self._harmony_cycle_beats: typing.Optional[int] = None
		self._harmony_reschedule_lookahead: float = 1
		self._pending_patterns: typing.List[_PendingPattern] = []
		self._pending_scheduled: typing.List[_PendingScheduled] = []
		self._form_state: typing.Optional[FormState] = None
		self._builder_bar: int = 0
		self._display: typing.Optional[subsequence.display.Display] = None
		self._live_server: typing.Optional[subsequence.live_server.LiveServer] = None
		self._is_live: bool = False
		self._running_patterns: typing.Dict[str, typing.Any] = {}
		self._input_device: typing.Optional[str] = None
		self._clock_follow: bool = False
		self.data: typing.Dict[str, typing.Any] = {}
		self._osc_server: typing.Optional[subsequence.osc.OscServer] = None
		self.conductor = subsequence.conductor.Conductor()

	def harmony (
		self,
		style: typing.Union[str, subsequence.chord_graphs.ChordGraph] = "functional_major",
		cycle_beats: int = 4,
		dominant_7th: bool = True,
		gravity: float = 1.0,
		nir_strength: float = 0.5,
		minor_weight: float = 0.0,
		reschedule_lookahead: float = 1
	) -> None:

		"""
		Configure the harmonic logic and chord change intervals.

		Subsequence uses a weighted transition graph to choose the next chord.
		You can influence these choices using 'gravity' (favoring the tonic) and
		'NIR strength' (melodic inertia based on Narmour's model).

		Parameters:
			style: The harmonic style to use. Built-in: "functional_major"
				(alias "diatonic_major"), "turnaround", "aeolian_minor",
				"phrygian_minor", "lydian_major", "dorian_minor",
				"chromatic_mediant", "suspended", "mixolydian", "whole_tone",
				"diminished". See README for full descriptions.
			cycle_beats: How many beats each chord lasts (default 4).
			dominant_7th: Whether to include V7 chords (default True).
			gravity: Key gravity (0.0 to 1.0). High values stay closer to the root chord.
			nir_strength: Melodic inertia (0.0 to 1.0). Influences chord movement 
				expectations.
			minor_weight: For "turnaround" style, influences major vs minor feel.
			reschedule_lookahead: How many beats in advance to calculate the 
				next chord.

		Example:
			```python
			# A moody minor progression that changes every 8 beats
			comp.harmony(style="aeolian_minor", cycle_beats=8, gravity=0.4)
			```
		"""

		if self.key is None:
			raise ValueError("Cannot configure harmony without a key - set key in the Composition constructor")

		self._harmonic_state = subsequence.harmonic_state.HarmonicState(
			key_name = self.key,
			graph_style = style,
			include_dominant_7th = dominant_7th,
			key_gravity_blend = gravity,
			nir_strength = nir_strength,
			minor_turnaround_weight = minor_weight
		)

		self._harmony_cycle_beats = cycle_beats
		self._harmony_reschedule_lookahead = reschedule_lookahead

	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a sequencer event (e.g., "bar", "start", "stop").
		"""

		self._sequencer.on_event(event_name, callback)

	def seed (self, value: int) -> None:

		"""
		Set a random seed for deterministic, repeatable playback.

		If a seed is set, Subsequence will produce the exact same sequence 
		every time you run the script. This is vital for finishing tracks or 
		reproducing a specific 'performance'.

		Parameters:
			value: An integer seed.

		Example:
			```python
			# Fix the randomness
			comp.seed(42)
			```
		"""

		self._seed = value

	def display (self, enabled: bool = True) -> None:

		"""
		Enable or disable the live terminal dashboard.

		When enabled, Subsequence uses a safe logging handler that allows a 
		persistent status line (BPM, Key, Bar, Section, Chord) to stay at 
		the bottom of the terminal while logs scroll above it.

		Parameters:
			enabled: Whether to show the display (default True).
		"""

		if enabled:
			self._display = subsequence.display.Display(self)
		else:
			self._display = None

	def midi_input (self, device: str, clock_follow: bool = False) -> None:

		"""
		Configure MIDI input for external sync and MIDI messages.

		Parameters:
			device: The name of the MIDI input port.
			clock_follow: If True, Subsequence will slave its clock to incoming 
				MIDI Ticks. It will also follow MIDI Start/Stop/Continue 
				commands.

		Example:
			```python
			# Slave Subsequence to an external hardware sequencer
			comp.midi_input("Scarlett 2i4", clock_follow=True)
			```
		"""

		self._input_device = device
		self._clock_follow = clock_follow

	def live (self, port: int = 5555) -> None:

		"""
		Enable the live coding eval server.

		This allows you to connect to a running composition using the 
		`subsequence.live_client` REPL and hot-swap pattern code or 
		modify variables in real-time.

		Parameters:
			port: The TCP port to listen on (default 5555).
		"""

		self._live_server = subsequence.live_server.LiveServer(self, port=port)
		self._is_live = True

	def osc (self, receive_port: int = 9000, send_port: int = 9001, send_host: str = "127.0.0.1") -> None:

		"""
		Enable bi-directional Open Sound Control (OSC).

		Subsequence will listen for commands (like `/bpm` or `/mute`) and 
		broadcast its internal state (like `/chord` or `/bar`) over UDP.

		Parameters:
			receive_port: Port to listen for incoming OSC messages (default 9000).
			send_port: Port to send state updates to (default 9001).
			send_host: The IP address to send updates to (default "127.0.0.1").
		"""

		self._osc_server = subsequence.osc.OscServer(
			self,
			receive_port = receive_port,
			send_port = send_port,
			send_host = send_host
		)

	def set_bpm (self, bpm: float) -> None:

		"""
		Instantly change the tempo.

		Parameters:
			bpm: The new tempo in beats per minute.
		"""

		self._sequencer.set_bpm(bpm)

		if not self._clock_follow:
			self.bpm = bpm

	def target_bpm (self, bpm: float, bars: int) -> None:

		"""
		Smoothly ramp the tempo to a target value over a number of bars.

		Example:
			```python
			# Accelerate to 140 BPM over the next 8 bars
			comp.target_bpm(140, bars=8)
			```
		"""

		self._sequencer.set_target_bpm(bpm, bars)

	def live_info (self) -> typing.Dict[str, typing.Any]:

		"""
		Return a dictionary containing the current state of the composition.
		
		Includes BPM, key, current bar, active section, current chord, 
		running patterns, and custom data.
		"""

		section_info = None
		if self._form_state is not None:
			section = self._form_state.get_section_info()
			if section is not None:
				section_info = {
					"name": section.name,
					"bar": section.bar,
					"bars": section.bars,
					"progress": section.progress
				}

		chord_name = None
		if self._harmonic_state is not None:
			chord = self._harmonic_state.get_current_chord()
			if chord is not None:
				chord_name = chord.name()

		pattern_list = []
		for name, pat in self._running_patterns.items():
			pattern_list.append({
				"name": name,
				"channel": pat.channel,
				"length": pat.length,
				"cycle": pat._cycle_count,
				"muted": pat._muted
			})

		return {
			"bpm": self._sequencer.current_bpm,
			"key": self.key,
			"bar": self._builder_bar,
			"section": section_info,
			"chord": chord_name,
			"patterns": pattern_list,
			"input_device": self._input_device,
			"clock_follow": self._clock_follow,
			"data": self.data
		}

	def mute (self, name: str) -> None:

		"""
		Mute a running pattern by name.
		
		The pattern continues to 'run' and increment its cycle count in 
		the background, but it will not produce any MIDI notes until unmuted.

		Parameters:
			name: The function name of the pattern to mute.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		self._running_patterns[name]._muted = True
		logger.info(f"Muted pattern: {name}")

	def unmute (self, name: str) -> None:

		"""
		Unmute a previously muted pattern.
		"""

		if name not in self._running_patterns:
			raise ValueError(f"Pattern '{name}' not found. Available: {list(self._running_patterns.keys())}")

		self._running_patterns[name]._muted = False
		logger.info(f"Unmuted pattern: {name}")

	def schedule (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int = 1) -> None:

		"""
		Register a custom function to run on a repeating beat-based cycle.

		Subsequence automatically runs synchronous functions in a thread pool 
		so they don't block the timing-critical MIDI clock. Async functions 
		are run directly on the event loop.

		Parameters:
			fn: The function to call.
			cycle_beats: How often to call it (e.g., 4 = every bar).
			reschedule_lookahead: How far in advance to schedule the next call.
		"""

		self._pending_scheduled.append(_PendingScheduled(fn, cycle_beats, reschedule_lookahead))

	def form (
		self,
		sections: typing.Union[
			typing.List[typing.Tuple[str, int]],
			typing.Iterator[typing.Tuple[str, int]],
			typing.Dict[str, typing.Tuple[int, typing.Optional[typing.List[typing.Tuple[str, int]]]]]
		],
		loop: bool = False,
		start: typing.Optional[str] = None
	) -> None:

		"""
		Define the structure (sections) of the composition.

		You can define form in three ways:
		1. **Graph (Dict)**: Dynamic transitions based on weights.
		2. **Sequence (List)**: A fixed order of sections.
		3. **Generator**: A Python generator that yields `(name, bars)` pairs.

		Parameters:
			sections: The form definition (Dict, List, or Generator).
			loop: Whether to cycle back to the start (List mode only).
			start: The section to start with (Graph mode only).

		Example:
			```python
			# A simple pop structure
			comp.form([
				("verse", 8),
				("chorus", 8),
				("verse", 8),
				("chorus", 16)
			])
			```
		"""

		self._form_state = FormState(sections, loop=loop, start=start)

	def pattern (
		self,
		channel: int,
		length: float = 4,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: float = 1,
		voice_leading: bool = False
	) -> typing.Callable:

		"""
		Register a function as a repeating MIDI pattern.

		The decorated function will be called once per cycle to 'rebuild' its 
		content. This allows for generative logic that evolves over time.

		Parameters:
			channel: MIDI channel (0-15).
			length: Duration of the loop in beats (default 4).
			drum_note_map: Optional mapping for drum instruments.
			reschedule_lookahead: Beats in advance to compute the next cycle.
			voice_leading: If True, chords in this pattern will automatically 
				use inversions that minimize voice movement.

		Example:
			```python
			@comp.pattern(channel=0)
			def bass(p):
				p.seq("60 . . 60", velocity=80)
			```
		"""

		def decorator (fn: typing.Callable) -> typing.Callable:

			"""
			Wrap the builder function and register it as a pending pattern.
			During live sessions, hot-swap an existing pattern's builder instead.
			"""

			# Hot-swap: if we're live and a pattern with this name exists, replace its builder.
			if self._is_live and fn.__name__ in self._running_patterns:
				running = self._running_patterns[fn.__name__]
				running._builder_fn = fn
				running._wants_chord = _fn_has_parameter(fn, "chord")
				logger.info(f"Hot-swapped pattern: {fn.__name__}")
				return fn

			pending = _PendingPattern(
				builder_fn = fn,
				channel = channel,
				length = length,
				drum_note_map = drum_note_map,
				reschedule_lookahead = reschedule_lookahead,
				voice_leading = voice_leading
			)

			self._pending_patterns.append(pending)

			return fn

		return decorator

	def layer (
		self,
		*builder_fns: typing.Callable,
		channel: int,
		length: float = 4,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: float = 1,
		voice_leading: bool = False
	) -> None:

		"""
		Combine multiple functions into a single MIDI pattern.
		
		This is useful for composing complex patterns out of reusable 
		building blocks (e.g., a 'kick' function and a 'snare' function).
		"""

		wants_chord = any(_fn_has_parameter(fn, "chord") for fn in builder_fns)

		if wants_chord:

			def merged_builder (p: subsequence.pattern_builder.PatternBuilder, chord: _InjectedChord) -> None:

				for fn in builder_fns:
					if _fn_has_parameter(fn, "chord"):
						fn(p, chord)
					else:
						fn(p)

		else:

			def merged_builder (p: subsequence.pattern_builder.PatternBuilder) -> None:  # type: ignore[misc]

				for fn in builder_fns:
					fn(p)

		pending = _PendingPattern(
			builder_fn = merged_builder,
			channel = channel,
			length = length,
			drum_note_map = drum_note_map,
			reschedule_lookahead = reschedule_lookahead,
			voice_leading = voice_leading
		)

		self._pending_patterns.append(pending)

	def play (self) -> None:

		"""
		Start the composition.
		
		This call blocks until the program is interrupted (e.g., via Ctrl+C).
		It initializes the MIDI hardware, launches the background sequencer, 
		and begins playback.
		"""

		try:
			asyncio.run(self._run())

		except KeyboardInterrupt:
			pass

	async def _run (self) -> None:

		"""
		Async entry point that schedules all patterns and runs the sequencer.
		"""

		# Pass MIDI input configuration to the sequencer before start.
		if self._input_device is not None:
			self._sequencer.input_device_name = self._input_device
			self._sequencer.clock_follow = self._clock_follow

		# Derive child RNGs from the master seed so each component gets
		# an independent, deterministic stream.  When no seed is set,
		# each component creates its own unseeded RNG (existing behaviour).
		self._pattern_rngs: typing.List[random.Random] = []

		if self._seed is not None:
			master = random.Random(self._seed)

			if self._harmonic_state is not None:
				self._harmonic_state.rng = random.Random(master.randint(0, 2 ** 63))

			if self._form_state is not None:
				self._form_state._rng = random.Random(master.randint(0, 2 ** 63))

			for _ in self._pending_patterns:
				self._pattern_rngs.append(random.Random(master.randint(0, 2 ** 63)))

		if self._harmonic_state is not None and self._harmony_cycle_beats is not None:

			await schedule_harmonic_clock(
				sequencer = self._sequencer,
				harmonic_state = self._harmonic_state,
				cycle_beats = self._harmony_cycle_beats,
				reschedule_lookahead = self._harmony_reschedule_lookahead
			)

		if self._form_state is not None:

			await schedule_form(
				sequencer = self._sequencer,
				form_state = self._form_state,
				reschedule_lookahead = 1
			)

		# Bar counter - always active so p.bar is available to all builders.
		def _advance_builder_bar (pulse: int) -> None:
			self._builder_bar += 1

		await self._sequencer.schedule_callback_repeating(
			callback = _advance_builder_bar,
			interval_beats = 4,
			start_pulse = 0,
			reschedule_lookahead = 1
		)

		for pending_task in self._pending_scheduled:

			wrapped = _make_safe_callback(pending_task.fn)

			await self._sequencer.schedule_callback_repeating(
				callback = wrapped,
				interval_beats = pending_task.cycle_beats,
				start_pulse = 0,
				reschedule_lookahead = pending_task.reschedule_lookahead
			)

		# Build Pattern objects from pending registrations.
		patterns: typing.List[subsequence.pattern.Pattern] = []

		for i, pending in enumerate(self._pending_patterns):

			pattern_rng = self._pattern_rngs[i] if i < len(self._pattern_rngs) else None
			pattern = self._build_pattern_from_pending(pending, pattern_rng)
			patterns.append(pattern)

		await schedule_patterns(
			sequencer = self._sequencer,
			patterns = patterns,
			start_pulse = 0
		)

		# Populate the running patterns dict for live hot-swap and mute/unmute.
		for i, pending in enumerate(self._pending_patterns):
			name = pending.builder_fn.__name__
			self._running_patterns[name] = patterns[i]

		if self._display is not None:
			self._display.start()
			self._sequencer.on_event("bar", self._display.update)

		if self._live_server is not None:
			await self._live_server.start()

		if self._osc_server is not None:
			await self._osc_server.start()

			def _send_osc_status (bar: int) -> None:
				if self._osc_server:
					self._osc_server.send("/bar", bar)
					self._osc_server.send("/bpm", self._sequencer.current_bpm)
					
					if self._harmonic_state:
						self._osc_server.send("/chord", self._harmonic_state.current_chord.name())
					
					if self._form_state:
						info = self._form_state.get_section_info()
						if info:
							self._osc_server.send("/section", info.name)

			self._sequencer.on_event("bar", _send_osc_status)

		await run_until_stopped(self._sequencer)

		if self._live_server is not None:
			await self._live_server.stop()

		if self._osc_server is not None:
			await self._osc_server.stop()

		if self._display is not None:
			self._display.stop()

	def _build_pattern_from_pending (self, pending: _PendingPattern, rng: typing.Optional[random.Random] = None) -> subsequence.pattern.Pattern:

		"""
		Create a Pattern from a pending registration using a temporary subclass.
		"""

		composition_ref = self

		class _DecoratorPattern (subsequence.pattern.Pattern):

			"""
			Pattern subclass that delegates to a builder function on each reschedule.
			"""

			def __init__ (self, pending: _PendingPattern, pattern_rng: typing.Optional[random.Random] = None) -> None:

				"""
				Initialize the decorator pattern from pending registration details.
				"""

				super().__init__(
					channel = pending.channel,
					length = pending.length,
					reschedule_lookahead = pending.reschedule_lookahead
				)

				self._builder_fn = pending.builder_fn
				self._drum_note_map = pending.drum_note_map
				self._wants_chord = _fn_has_parameter(pending.builder_fn, "chord")
				self._cycle_count = 0
				self._rng = pattern_rng
				self._muted = False
				self._voice_leading_state: typing.Optional[subsequence.voicings.VoiceLeadingState] = (
					subsequence.voicings.VoiceLeadingState() if pending.voice_leading else None
				)

				self._rebuild()

			def _rebuild (self) -> None:

				"""
				Clear steps and call the builder function to repopulate.
				"""

				self.steps = {}
				current_cycle = self._cycle_count
				self._cycle_count += 1

				if self._muted:
					return

				# Import here to avoid circular import at module level.
				import subsequence.pattern_builder

				builder = subsequence.pattern_builder.PatternBuilder(
					pattern = self,
					cycle = current_cycle,
					drum_note_map = self._drum_note_map,
					section = composition_ref._form_state.get_section_info() if composition_ref._form_state else None,
					bar = composition_ref._builder_bar,
					conductor = composition_ref.conductor,
					rng = self._rng
				)

				try:

					if self._wants_chord and composition_ref._harmonic_state is not None:
						chord = composition_ref._harmonic_state.get_current_chord()
						key_root_pc = composition_ref._harmonic_state.key_root_pc
						injected = _InjectedChord(chord, key_root_pc, self._voice_leading_state)
						self._builder_fn(builder, injected)

					else:
						self._builder_fn(builder)

				except Exception:
					logger.exception("Error in pattern builder '%s' (cycle %d) - pattern will be silent this cycle", self._builder_fn.__name__, current_cycle)

			def on_reschedule (self) -> None:

				"""
				Rebuild the pattern from the builder function before the next cycle.
				"""

				self._rebuild()

		return _DecoratorPattern(pending, rng)
