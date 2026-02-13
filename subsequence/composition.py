import asyncio
import inspect
import itertools
import logging
import random
import signal
import typing

import subsequence.chord_graphs
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer
import subsequence.weighted_graph


logger = logging.getLogger(__name__)


class SectionInfo:

	"""Immutable snapshot of the current section state."""

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

		"""
		Initialize a composition with MIDI device, tempo, and optional key.
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

		"""Configure the harmonic state and chord change cycle for this composition."""

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

	def schedule (self, fn: typing.Callable, cycle_beats: int, reschedule_lookahead: int = 1) -> None:

		"""Register a function to run on a repeating beat-based cycle."""

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

		"""Define the compositional form as a sequence of sections or a weighted section graph."""

		self._form_state = FormState(sections, loop=loop, start=start)

	def pattern (
		self,
		channel: int,
		length: int = 4,
		drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
		reschedule_lookahead: int = 1
	) -> typing.Callable:

		"""
		Decorator that registers a builder function as a repeating pattern.
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

		"""
		Start playback, blocking until stopped via Ctrl+C or signal.
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

		await run_until_stopped(self._sequencer)

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
