import asyncio
import inspect
import logging
import signal
import typing

import subsequence.chord_graphs
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer


logger = logging.getLogger(__name__)


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

	def harmony (
		self,
		style: typing.Union[str, subsequence.chord_graphs.ChordGraph] = "functional_major",
		cycle: int = 4,
		dominant_7th: bool = True,
		gravity: float = 1.0,
		minor_weight: float = 0.0,
		reschedule_lookahead: int = 1
	) -> None:

		"""
		Configure the harmonic state and chord change cycle for this composition.
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

		self._harmony_cycle_beats = cycle
		self._harmony_reschedule_lookahead = reschedule_lookahead

	def on_event (self, event_name: str, callback: typing.Callable[..., typing.Any]) -> None:

		"""
		Register a callback for a sequencer event (e.g., "bar", "start", "stop").
		"""

		self._sequencer.on_event(event_name, callback)

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
					drum_note_map = self._drum_note_map
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
