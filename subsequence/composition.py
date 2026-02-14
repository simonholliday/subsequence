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
import subsequence.pattern
import subsequence.sequencer
import subsequence.weighted_graph


logger = logging.getLogger(__name__)


class SectionInfo:

	"""Immutable snapshot of the current section state.

	Patterns read `p.section` to decide what to play in each section.

	Example:
		```python
		@composition.pattern(channel=9, length=4, drum_note_map=DRUM_NOTE_MAP)
		def drums(p):
			# Always play kick
			p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

			# Only play snare during chorus
			if p.section and p.section.name == "chorus":
				# Build intensity through the section
				vel = int(80 + 20 * p.section.progress)
				p.hit_steps("snare", [4, 12], velocity=vel)
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

		_, current_bars = self._current

		if self._bar_in_section >= current_bars:

			if self._graph is not None:
				# Graph mode: choose next section via weighted graph.
				current_name = self._current[0]

				if current_name in self._terminal_sections:
					# Terminal section — form ends.
					self._finished = True
					self._current = None
					return True

				next_name = self._graph.choose_next(current_name, self._rng)
				self._current = (next_name, self._section_bars[next_name])
				self._section_index += 1
				self._bar_in_section = 0
				return True

			else:
				# Iterator mode.
				try:
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

	def __init__ (self, chord: typing.Any, key_root_pc: int) -> None:

		"""
		Store the chord and key root pitch class for transposition.
		"""

		self._chord = chord
		self._key_root_pc = key_root_pc

	def root_midi (self, base: int) -> int:

		"""
		Compute the MIDI root for this chord relative to a base note and key.
		"""

		offset = (self._chord.root_pc - self._key_root_pc) % 12

		return base + offset

	def tones (self, root: int) -> typing.List[int]:

		"""
		Return MIDI note numbers transposed to the correct chord root.
		"""

		return [self.root_midi(root) + interval for interval in self._chord.intervals()]

	def intervals (self) -> typing.List[int]:

		"""
		Forward to the underlying chord's intervals.
		"""

		return self._chord.intervals()

	def name (self) -> str:

		"""
		Forward to the underlying chord's name.
		"""

		return self._chord.name()


async def schedule_harmonic_clock (
	sequencer: subsequence.sequencer.Sequencer,
	harmonic_state: subsequence.harmonic_state.HarmonicState,
	cycle_beats: int,
	reschedule_lookahead: int = 1
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
		length: int,
		drum_note_map: typing.Optional[typing.Dict[str, int]],
		reschedule_lookahead: int
	) -> None:

		"""
		Store pattern registration details for deferred scheduling.
		"""

		self.builder_fn = builder_fn
		self.channel = channel
		self.length = length
		self.drum_note_map = drum_note_map
		self.reschedule_lookahead = reschedule_lookahead


class _PendingScheduled:

	"""Holds a user function and cycle interval for deferred scheduling."""

	def __init__ (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int) -> None:

		"""Store the function and scheduling parameters."""

		self.fn = fn
		self.cycle_beats = cycle_beats
		self.reschedule_lookahead = reschedule_lookahead


class Composition:

	"""
	Top-level composition object that owns the sequencer, harmonic state, and pattern registry.
	"""

	def __init__ (self, device: str, bpm: int = 120, key: typing.Optional[str] = None) -> None:

		"""Initialize a composition with MIDI device, tempo, and optional key.

		Parameters:
			device: MIDI device name (e.g., `"Device Name:Port 1 16:0"`)
			bpm: Tempo in beats per minute (default 120)
			key: Root key name (e.g., `"C"`, `"F#"`, `"Bb"`). Required if using `harmony()`.

		Example:
			```python
			composition = subsequence.Composition(
				device="Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0",
				bpm=125,
				key="E"
			)
			```
		"""

		self.device = device
		self.bpm = bpm
		self.key = key

		self._sequencer = subsequence.sequencer.Sequencer(
			midi_device_name = device,
			initial_bpm = bpm
		)

		self._harmonic_state: typing.Optional[subsequence.harmonic_state.HarmonicState] = None
		self._harmony_cycle_beats: typing.Optional[int] = None
		self._harmony_reschedule_lookahead: int = 1
		self._pending_patterns: typing.List[_PendingPattern] = []
		self._pending_scheduled: typing.List[_PendingScheduled] = []
		self._form_state: typing.Optional[FormState] = None
		self._builder_bar: int = 0
		self._display: typing.Optional[subsequence.display.Display] = None
		self.data: typing.Dict[str, typing.Any] = {}

	def harmony (
		self,
		style: typing.Union[str, subsequence.chord_graphs.ChordGraph] = "functional_major",
		cycle_beats: int = 4,
		dominant_7th: bool = True,
		gravity: float = 1.0,
		minor_weight: float = 0.0,
		reschedule_lookahead: int = 1
	) -> None:

		"""Configure the harmonic state and chord change cycle for this composition.

		Parameters:
			style: Chord graph style — `"diatonic_major"`, `"turnaround"`, `"dark_minor"`, or a `ChordGraph` instance
			cycle_beats: How often chords change (in beats, default 4)
			dominant_7th: Include dominant seventh chords (default True)
			gravity: Key gravity blend 0.0-1.0 (default 1.0). Higher values favor chords closer to the tonic.
			minor_weight: Weight for minor vs major turnarounds 0.0-1.0 (default 0.0, turnaround graph only)
			reschedule_lookahead: Reschedule lookahead in beats (default 1)

		Example:
			```python
			composition.harmony(
				style="dark_minor",
				cycle_beats=4,
				dominant_7th=True,
				gravity=0.8
			)
			```
		"""

		if self.key is None:
			raise ValueError("Cannot configure harmony without a key — set key in the Composition constructor")

		self._harmonic_state = subsequence.harmonic_state.HarmonicState(
			key_name = self.key,
			graph_style = style,
			include_dominant_7th = dominant_7th,
			key_gravity_blend = gravity,
			minor_turnaround_weight = minor_weight
		)

		self._harmony_cycle_beats = cycle_beats
		self._harmony_reschedule_lookahead = reschedule_lookahead

	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a sequencer event (e.g., "bar", "start", "stop").
		"""

		self._sequencer.on_event(event_name, callback)

	def display (self, enabled: bool = True) -> None:

		"""Enable or disable the live terminal status line.

		When enabled, a persistent status line shows the current bar, section,
		chord, BPM, and key. Log messages scroll above it without disruption.

		Parameters:
			enabled: Turn the display on (True) or off (False)

		Example:
			```python
			composition.display()  # enable before play()
			composition.play()
			```
		"""

		if enabled:
			self._display = subsequence.display.Display(self)
		else:
			self._display = None

	def schedule (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int = 1) -> None:

		"""Register a function to run on a repeating beat-based cycle.

		Sync functions automatically run in a thread pool so they never block the MIDI clock.
		Async functions run directly on the event loop.

		Parameters:
			fn: Function to call on each cycle (sync or async)
			cycle_beats: How often to call the function (in beats)
			reschedule_lookahead: Reschedule lookahead in beats (default 1)

		Example:
			```python
			# Sync function (runs in thread pool automatically)
			def fetch_data():
				composition.data["value"] = some_external_api()

			composition.schedule(fetch_data, cycle_beats=32)  # Every 8 bars

			# Async function (runs directly)
			async def async_task():
				composition.data["value"] = await some_async_api()

			composition.schedule(async_task, cycle_beats=16)
			```
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

		"""Define the compositional form as a sequence of sections or a weighted section graph.

		Three modes:
		- **Dict** (graph): Weighted section transitions. Format: `{section_name: (bars, [(next_section, weight), ...])}`
		- **List**: Linear sequence. With `loop=True`, cycles back to the start.
		- **Generator**: Yields `(name, bars)` tuples for stochastic structures.

		Parameters:
			sections: Dict (graph), list, or generator of `(name, bars)` tuples
			loop: For lists only — cycle back to start after the last section (default False)
			start: For dicts only — initial section name (default: first dict key)

		Example:
			```python
			# Graph-based form — intro plays once, then never returns
			composition.form({
				"intro":     (4, [("verse", 1)]),
				"verse":     (8, [("chorus", 3), ("bridge", 1)]),
				"chorus":    (8, [("breakdown", 2), ("verse", 1)]),
				"bridge":    (4, [("chorus", 1)]),
				"breakdown": (4, [("verse", 1)]),
			}, start="intro")

			# List-based form with loop
			composition.form([("intro", 4), ("verse", 8), ("chorus", 8)], loop=True)

			# Generator form
			def my_form():
				yield ("intro", 4)
				while True:
					yield ("verse", random.choice([8, 16]))
					yield ("chorus", 8)

			composition.form(my_form())
			```
		"""

		self._form_state = FormState(sections, loop=loop, start=start)

	def pattern (
		self,
		channel: int,
		length: int = 4,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: int = 1
	) -> typing.Callable:

		"""Decorator that registers a builder function as a repeating pattern.

		The builder function receives a `PatternBuilder` (`p`) and optionally a `chord` parameter
		(automatically injected if present and harmony is configured).

		Parameters:
			channel: MIDI channel (0-15)
			length: Pattern length in beats (default 4)
			drum_note_map: Optional dict mapping string names to MIDI note numbers (e.g., `{"kick": 36}`)
			reschedule_lookahead: Reschedule lookahead in beats (default 1)

		Example:
			```python
			@composition.pattern(channel=9, length=4, drum_note_map={"kick": 36, "snare": 38})
			def drums(p):
				p.hit_steps("kick", [0, 4, 8, 12], velocity=127)
				p.hit_steps("snare", [4, 12], velocity=100)

			@composition.pattern(channel=0, length=4)
			def melody(p, chord):
				# chord is automatically injected
				p.note(chord.tones(root=60)[0], beat=0, velocity=90)
			```
		"""

		def decorator (fn: typing.Callable) -> typing.Callable:

			"""
			Wrap the builder function and register it as a pending pattern.
			"""

			pending = _PendingPattern(
				builder_fn = fn,
				channel = channel,
				length = length,
				drum_note_map = drum_note_map,
				reschedule_lookahead = reschedule_lookahead
			)

			self._pending_patterns.append(pending)

			return fn

		return decorator

	def play (self) -> None:

		"""Start playback, blocking until stopped via Ctrl+C or signal.

		Schedules all registered patterns, harmonic state (if configured), form state (if configured),
		and scheduled tasks. Runs the sequencer loop until interrupted.

		Example:
			```python
			if __name__ == "__main__":
				composition.play()  # Press Ctrl+C to stop
			```
		"""

		try:
			asyncio.run(self._run())

		except KeyboardInterrupt:
			pass

	async def _run (self) -> None:

		"""
		Async entry point that schedules all patterns and runs the sequencer.
		"""

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

		# Bar counter — always active so p.bar is available to all builders.
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
		# The actual _DecoratorPattern will be implemented in Phase 2.
		# For now, we create simple patterns from the builder functions.
		patterns: typing.List[subsequence.pattern.Pattern] = []

		for pending in self._pending_patterns:

			pattern = self._build_pattern_from_pending(pending)
			patterns.append(pattern)

		await schedule_patterns(
			sequencer = self._sequencer,
			patterns = patterns,
			start_pulse = 0
		)

		if self._display is not None:
			self._display.start()
			self._sequencer.on_event("bar", self._display.update)

		await run_until_stopped(self._sequencer)

		if self._display is not None:
			self._display.stop()

	def _build_pattern_from_pending (self, pending: _PendingPattern) -> subsequence.pattern.Pattern:

		"""
		Create a Pattern from a pending registration using a temporary subclass.
		"""

		composition_ref = self

		class _DecoratorPattern (subsequence.pattern.Pattern):

			"""
			Pattern subclass that delegates to a builder function on each reschedule.
			"""

			def __init__ (self, pending: _PendingPattern) -> None:

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
				self._wants_chord = "chord" in inspect.signature(pending.builder_fn).parameters
				self._cycle_count = 0

				self._rebuild()

			def _rebuild (self) -> None:

				"""
				Clear steps and call the builder function to repopulate.
				"""

				self.steps = {}
				current_cycle = self._cycle_count
				self._cycle_count += 1

				# Import here to avoid circular import at module level.
				import subsequence.pattern_builder

				builder = subsequence.pattern_builder.PatternBuilder(
					pattern = self,
					cycle = current_cycle,
					drum_note_map = self._drum_note_map,
					section = composition_ref._form_state.get_section_info() if composition_ref._form_state else None,
					bar = composition_ref._builder_bar
				)

				if self._wants_chord and composition_ref._harmonic_state is not None:
					chord = composition_ref._harmonic_state.get_current_chord()
					key_root_pc = composition_ref._harmonic_state.key_root_pc
					injected = _InjectedChord(chord, key_root_pc)
					self._builder_fn(builder, injected)

				else:
					self._builder_fn(builder)

			def on_reschedule (self) -> None:

				"""
				Rebuild the pattern from the builder function before the next cycle.
				"""

				self._rebuild()

		return _DecoratorPattern(pending)
