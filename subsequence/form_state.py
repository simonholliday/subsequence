"""Compositional form tracking — section sequences, transitions, and lookahead.

Defines :class:`SectionInfo` (immutable per-bar snapshot) and
:class:`FormState` (the stateful form engine that advances through sections).

These are registered on the :class:`~subsequence.composition.Composition`
via :meth:`~subsequence.composition.Composition.form` and read by pattern
builders through ``p.section``.
"""

import dataclasses
import itertools
import logging
import random
import typing

import subsequence.weighted_graph


logger = logging.getLogger(__name__)


@dataclasses.dataclass
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
		next_section: The name of the upcoming section (or ``None`` if the
			form will end after this section).  This is pre-decided when
			the current section begins, so patterns can plan lead-ins.
			A performer or code can override it with ``composition.form_next()``.

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

			# Plan a lead-in on the last bar before a chorus
			if p.section and p.section.last_bar and p.section.next_section == "chorus":
				p.hit_steps("snare", [0, 2, 4, 6, 8, 10, 12, 14], velocity=100)
		```
	"""

	name: str
	bar: int
	bars: int
	index: int
	next_section: typing.Optional[str] = None

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

		# Next-section lookahead: pre-decided when entering a section so
		# patterns can read p.section.next_section for lead-ins.
		# Overridable at any time via queue_next().
		self._next_section_name: typing.Optional[str] = None

		# Iterator peek buffer (list/generator mode only).
		self._peeked: typing.Optional[typing.Tuple[str, int]] = None
		self._peek_exhausted: bool = False

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
			self._pick_next()

		elif isinstance(sections, list):
			# List mode: convert to iterator, optionally cycling.
			self._iterator = itertools.cycle(sections) if loop else iter(sections)

			try:
				self._current = next(self._iterator)
			except StopIteration:
				self._finished = True

			self._peek_iterator()

		else:
			# Generator/iterator mode: use directly.
			self._iterator = sections

			try:
				self._current = next(self._iterator)
			except StopIteration:
				self._finished = True

			self._peek_iterator()

	def _pick_next (self) -> None:

		"""Pre-decide the next section so patterns can read it as a lookahead.

		In graph mode, calls ``choose_next()`` on the weighted graph.
		In iterator mode, delegates to ``_peek_iterator()``.
		"""

		if self._graph is not None:
			assert self._current is not None
			current_name = self._current[0]

			if current_name in self._terminal_sections:
				self._next_section_name = None
			else:
				self._next_section_name = self._graph.choose_next(current_name, self._rng)
		else:
			self._peek_iterator()

	def _peek_iterator (self) -> None:

		"""Peek the next element from the iterator into a one-element buffer."""

		if self._peek_exhausted or self._iterator is None:
			self._next_section_name = None
			return

		try:
			self._peeked = next(self._iterator)
			self._next_section_name = self._peeked[0]
		except StopIteration:
			self._peeked = None
			self._next_section_name = None
			self._peek_exhausted = True

	def queue_next (self, section_name: str) -> None:

		"""Queue a section to play after the current one ends.

		Overrides the automatically pre-decided next section.  The queued
		section takes effect at the natural section boundary — the current
		section plays to completion first.

		Only available in graph mode.

		Args:
			section_name: The section to queue.

		Raises:
			ValueError: If not in graph mode or the section name is unknown.
		"""

		if self._section_bars is None:
			raise ValueError(
				"queue_next() is only available in graph mode. "
				"Call composition.form() with a dict to use this feature."
			)

		if section_name not in self._section_bars:
			known = ", ".join(sorted(self._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._next_section_name = section_name
		logger.info(f"Form: next \u2192 {section_name}")

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
				# Graph mode: consume the pre-decided (or queued) next section.
				if self._next_section_name is None:
					# Terminal section — form ends.
					self._finished = True
					self._current = None
					return True

				assert self._section_bars is not None
				next_name = self._next_section_name
				self._current = (next_name, self._section_bars[next_name])
				self._section_index += 1
				self._bar_in_section = 0
				self._pick_next()
				return True

			else:
				# Iterator mode: consume from the peek buffer.
				if self._peeked is not None:
					self._current = self._peeked
					self._peeked = None
					self._section_index += 1
					self._bar_in_section = 0
					self._peek_iterator()
					return True
				else:
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
			index = self._section_index,
			next_section = self._next_section_name
		)

	@property
	def total_bars (self) -> int:

		"""Return the global bar count since the form started."""

		return self._total_bars

	def jump_to (self, section_name: str) -> None:

		"""Force the form to a named section immediately.

		Only available in **graph mode** (when ``composition.form()`` was called
		with a dict).  The section restarts from bar 0; its normal progression
		through the weighted graph resumes from there.

		The musical effect is not heard until the *next pattern rebuild cycle*,
		because already-queued MIDI notes are unaffected.  This is the same
		natural quantization that applies to all ``composition.data`` writes and
		``composition.tweak()`` calls.

		Args:
			section_name: Name of the section to jump to.  Must exist in the
				form definition passed to ``composition.form()``.

		Raises:
			ValueError: If not in graph mode or the section name is unknown.

		Example::

			composition.form_jump("chorus")   # via Composition helper
		"""

		if self._section_bars is None:
			raise ValueError(
				"jump_to() is only available in graph mode. "
				"Call composition.form() with a dict to use this feature."
			)

		if section_name not in self._section_bars:
			known = ", ".join(sorted(self._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._current = (section_name, self._section_bars[section_name])
		self._bar_in_section = 0
		self._section_index += 1
		self._finished = False
		self._pick_next()
		logger.info(f"Form: jump \u2192 {section_name}")
