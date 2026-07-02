"""Compositional form tracking — section sequences, transitions, and lookahead.

Defines :class:`SectionInfo` (immutable per-bar snapshot) and
:class:`FormState` (the stateful form engine that advances through sections).

These are registered on the :class:`~subsequence.composition.Composition`
via :meth:`~subsequence.composition.Composition.form` and read by pattern
builders through ``p.section``.

A form may be a :class:`~subsequence.forms.Form` value (Sections with
energy/key payloads), a plain list of ``(name, bars)`` tuples or Sections,
a generator yielding ``(name, bars)`` pairs, or a weighted-graph dict.
Everything normalises to :class:`~subsequence.forms.Section` internally —
the payload travels with the section either way.
"""

import dataclasses
import logging
import random
import typing

import subsequence.forms
import subsequence.weighted_graph


logger = logging.getLogger(__name__)


# Form-end behaviours (sequence and generator modes; graphs end via their
# terminal sections).
_AT_END_CHOICES: typing.FrozenSet[str] = frozenset({"stop", "hold", "loop"})


@dataclasses.dataclass
class SectionInfo:

	"""
	An immutable snapshot of the current section in the compositional form.

	Patterns read ``p.section`` to make context-aware decisions, such as increasing
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
		energy: The section's energy payload (0.5 unless a bound
			:class:`~subsequence.forms.Form` says otherwise; the
			``composition.energy()`` dict overrides it at read time).
		key: The section's key override, or ``None`` (a higher tier — form
			key, then composition key — supplies it).
		scale: The section's scale/mode override, or ``None`` (falls back
			through the form scale to the composition scale).

	Example:
		```python
		@composition.pattern(channel=9)
		def drums (p):
			# Always play a basic kick
			p.hit_steps("kick", [0, 8])

			# Only add snare and hats during the "chorus"
			if p.section and p.section.name == "chorus":
				p.hit_steps("snare", [4, 12])

				# Use .progress (0.0 to 1.0) to build a riser
				vel = int(60 + 40 * p.section.progress)
				p.hit_steps("hh", list(range(16)), velocity=vel)

			# Plan a lead-in on the last bar before a different section
			if p.section and p.section.ending:
				p.hit_steps("snare", [0, 2, 4, 6, 8, 10, 12, 14], velocity=100)
		```
	"""

	name: str
	bar: int
	bars: int
	index: int
	next_section: typing.Optional[str] = None
	energy: float = 0.5
	key: typing.Optional[str] = None
	scale: typing.Optional[str] = None

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

	@property
	def ending (self) -> bool:

		"""True on the last bar before a DIFFERENT section.

		A repeat (verse → verse) is not an ending, and neither is the
		form's end — ``ending`` marks the bars where transition material
		(fills, mutes) belongs.
		"""

		return (
			self.last_bar
			and self.next_section is not None
			and self.next_section != self.name
		)


class FormState:

	"""Track compositional form as a sequence of named sections with bar durations."""

	def __init__ (
		self,
		sections: typing.Union[
			"subsequence.forms.Form",
			typing.List[typing.Any],
			typing.Iterator[typing.Tuple[str, int]],
			typing.Dict[str, typing.Tuple[int, typing.Optional[typing.List[typing.Tuple[str, int]]]]]
		],
		loop: bool = False,
		start: typing.Optional[str] = None,
		rng: typing.Optional[random.Random] = None,
		at_end: str = "stop",
	) -> None:

		"""
		Initialize from a Form, list, iterator, or dict of weighted section transitions.

		Parameters:
			sections: Form definition. A :class:`~subsequence.forms.Form`
				value, a list of Sections / ``(name, bars)`` tuples, an
				iterator yielding ``(name, bars)`` tuples, or a dictionary
				defining a weighted directed graph for generative progression.
			loop: Sugar for ``at_end="loop"`` (sequence mode).
			start: Name of the starting section when using a graph dict. If omitted,
				it defaults to the first key in the dictionary.
			rng: Optional seeded ``random.Random`` for deterministic graph decisions.
			at_end: What happens when a sequence/generator form runs out —
				``"stop"`` (the form finishes; default), ``"hold"`` (the
				final section repeats until navigated away from), or
				``"loop"`` (start over).  Graphs end via their terminal
				sections, so a graph only accepts ``"stop"``.
		"""

		if at_end not in _AT_END_CHOICES:
			choices = ", ".join(sorted(_AT_END_CHOICES))
			raise ValueError(f"at_end must be one of {choices}, got {at_end!r}")

		if loop:
			if at_end not in ("stop", "loop"):
				raise ValueError(f"loop=True conflicts with at_end={at_end!r} — pass one or the other")
			at_end = "loop"

		self._at_end: str = at_end
		self._current: typing.Optional[subsequence.forms.Section] = None
		self._bar_in_section: int = 0
		self._section_index: int = 0
		self._total_bars: int = 0
		self._finished: bool = False

		# Graph mode state (only set when sections is a dict).
		self._graph: typing.Optional[subsequence.weighted_graph.WeightedGraph] = None
		self._section_bars: typing.Optional[typing.Dict[str, int]] = None
		self._rng: random.Random = rng or random.Random()
		self._iterator: typing.Optional[typing.Iterator[typing.Tuple[str, int]]] = None

		# Sequence mode state (list or Form): the whole timeline is known,
		# which is what makes jump_to()/queue_next() navigable.
		self._sequence: typing.Optional[typing.List[subsequence.forms.Section]] = None
		self._position: int = 0
		self._queued_position: typing.Optional[int] = None

		# Terminal sections (graph mode only): sections with None transitions.
		self._terminal_sections: typing.Set[str] = set()

		# Next-section lookahead: pre-decided when entering a section so
		# patterns can read p.section.next_section for lead-ins.
		# Overridable at any time via queue_next().
		self._next_section_name: typing.Optional[str] = None

		# Iterator peek buffer (generator mode only).
		self._peeked: typing.Optional[subsequence.forms.Section] = None
		self._peek_exhausted: bool = False

		if isinstance(sections, dict):
			# Graph mode: build a WeightedGraph from the dict.
			if at_end != "stop":
				raise ValueError(
					f"at_end={at_end!r} applies to sequence forms — a graph form ends "
					"via its terminal sections (give a section None transitions)"
				)

			self._graph = subsequence.weighted_graph.WeightedGraph()
			self._section_bars = {}

			for name, (bars, transitions) in sections.items():
				if bars < 1:
					raise ValueError(f"Section '{name}' must last at least 1 bar, got {bars}")

				self._section_bars[name] = bars
				if transitions is None:
					self._terminal_sections.add(name)
				else:
					for target, weight in transitions:
						# Validate targets against the whole dict now — a typo
						# would otherwise crash with a bare KeyError at the
						# first section boundary DURING playback, every bar.
						if target not in sections:
							known = ", ".join(sorted(sections))
							raise ValueError(
								f"Section '{name}' transitions to unknown section "
								f"'{target}'. Known sections: {known}"
							)
						self._graph.add_transition(name, target, weight)

			start_name = start if start is not None else next(iter(sections))

			if start_name not in self._section_bars:
				raise ValueError(f"Start section '{start_name}' not found in form definition")

			self._current = subsequence.forms.Section(name = start_name, bars = self._section_bars[start_name])
			self._pick_next()

		elif isinstance(sections, (subsequence.forms.Form, list)):
			# Sequence mode: the timeline is a known, navigable list.
			elements = sections.sections if isinstance(sections, subsequence.forms.Form) else sections
			self._sequence = [subsequence.forms._coerce_section(element) for element in elements]

			if self._sequence:
				self._current = self._sequence[0]
			else:
				self._finished = True

			self._pick_next()

		else:
			# Generator/iterator mode: use directly.
			if at_end == "loop":
				raise ValueError(
					'at_end="loop" cannot replay a generator form — pass a list '
					'(or Form) if the form should cycle'
				)

			self._iterator = sections

			try:
				self._current = subsequence.forms._coerce_section(next(self._iterator))
			except StopIteration:
				self._finished = True

			self._peek_iterator()

	def _pick_next (self) -> None:

		"""Pre-decide the next section so patterns can read it as a lookahead.

		In graph mode, calls ``choose_next()`` on the weighted graph.
		In sequence mode, reads the timeline (respecting ``at_end``).
		In generator mode, delegates to ``_peek_iterator()``.
		"""

		if self._graph is not None:
			assert self._current is not None
			current_name = self._current.name

			if current_name in self._terminal_sections:
				self._next_section_name = None
			else:
				self._next_section_name = self._graph.choose_next(current_name, self._rng)

		elif self._sequence is not None:
			if self._queued_position is not None:
				self._next_section_name = self._sequence[self._queued_position].name
			else:
				upcoming = self._sequence_next_position()
				self._next_section_name = self._sequence[upcoming].name if upcoming is not None else (
					self._current.name if self._at_end == "hold" and self._current is not None else None
				)

		else:
			self._peek_iterator()

	def _sequence_next_position (self) -> typing.Optional[int]:

		"""The natural next position in sequence mode, or None at the end.

		``at_end="loop"`` wraps; ``"hold"`` and ``"stop"`` both return
		None here — hold's repeat is decided at the boundary in
		:meth:`advance` (the position does not move).
		"""

		assert self._sequence is not None

		# An empty form has no position to move to — even under "loop".
		if not self._sequence:
			return None

		following = self._position + 1

		if following < len(self._sequence):
			return following

		if self._at_end == "loop":
			return 0

		return None

	def _peek_iterator (self) -> None:

		"""Peek the next element from the iterator into a one-element buffer."""

		if self._peek_exhausted or self._iterator is None:
			self._next_section_name = (
				self._current.name
				if self._at_end == "hold" and self._current is not None and self._peek_exhausted
				else None
			)
			return

		try:
			self._peeked = subsequence.forms._coerce_section(next(self._iterator))
			self._next_section_name = self._peeked.name
		except StopIteration:
			self._peeked = None
			self._peek_exhausted = True
			self._next_section_name = (
				self._current.name if self._at_end == "hold" and self._current is not None else None
			)

	def _find_occurrence (self, section_name: str, what: str) -> int:

		"""Find the next occurrence of a name in the sequence, searching forward and wrapping."""

		assert self._sequence is not None

		count = len(self._sequence)

		for step in range(1, count + 1):
			candidate = (self._position + step) % count
			if self._sequence[candidate].name == section_name:
				return candidate

		known = ", ".join(sorted({section.name for section in self._sequence}))
		raise ValueError(
			f"Section '{section_name}' not found in form. "
			f"Known sections: {known}"
		)

	def queue_next (self, section_name: str) -> None:

		"""Queue a section to play after the current one ends.

		Overrides the automatically pre-decided next section.  The queued
		section takes effect at the natural section boundary — the current
		section plays to completion first.  In sequence mode the form
		continues from the queued occurrence onward.

		Queuing after the form has finished revives it: the queued section
		starts at the next bar and the form continues from there.

		Available in graph and sequence (list/Form) modes; a generator form
		cannot be navigated.

		Args:
			section_name: The section to queue.

		Raises:
			ValueError: If the form is a generator, or the name is unknown.
		"""

		if self._sequence is not None:
			self._queued_position = self._find_occurrence(section_name, "queue_next")
			self._next_section_name = section_name
			logger.info(f"Form: next → {section_name}")
			return

		if self._section_bars is None:
			raise ValueError(
				"queue_next() needs a navigable form (a graph dict, a list, or a Form value) — "
				"a generator form cannot be navigated"
			)

		if section_name not in self._section_bars:
			known = ", ".join(sorted(self._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._next_section_name = section_name
		logger.info(f"Form: next → {section_name}")

	def advance (self) -> bool:

		"""Advance one bar, transitioning to the next section when needed, returning True if section changed."""

		if self._finished:

			# A queued section revives a finished form at the next bar —
			# queue_next() after the end is a command to play again, not a
			# call to be silently ignored (sequence mode used to trip the
			# not-finished invariant; graph mode ignored it).
			if self._sequence is not None and self._queued_position is not None:
				self._position = self._queued_position
				self._queued_position = None
				self._current = self._sequence[self._position]
			elif self._graph is not None and self._next_section_name is not None:
				assert self._section_bars is not None
				self._current = subsequence.forms.Section(
					name = self._next_section_name,
					bars = self._section_bars[self._next_section_name],
				)
			else:
				return False

			self._finished = False
			self._section_index += 1
			self._bar_in_section = 0
			self._pick_next()
			return True

		self._bar_in_section += 1
		self._total_bars += 1

		assert self._current is not None, "Form state invariant: current should not be None when not finished"

		if self._bar_in_section >= self._current.bars:

			if self._graph is not None:
				# Graph mode: consume the pre-decided (or queued) next section.
				if self._next_section_name is None:
					# Terminal section — form ends.
					self._finished = True
					self._current = None
					return True

				assert self._section_bars is not None
				next_name = self._next_section_name
				self._current = subsequence.forms.Section(name = next_name, bars = self._section_bars[next_name])
				self._section_index += 1
				self._bar_in_section = 0
				self._pick_next()
				return True

			elif self._sequence is not None:
				# Sequence mode: a queued jump wins; otherwise the timeline
				# (with at_end deciding what happens past the last section).
				if self._queued_position is not None:
					self._position = self._queued_position
					self._queued_position = None
				else:
					following = self._sequence_next_position()

					if following is None:
						if self._at_end == "hold":
							# The final section repeats (a re-entry: the index
							# bumps so bound material restarts correctly).
							self._section_index += 1
							self._bar_in_section = 0
							self._pick_next()
							return True

						self._finished = True
						self._current = None
						return True

					self._position = following

				self._current = self._sequence[self._position]
				self._section_index += 1
				self._bar_in_section = 0
				self._pick_next()
				return True

			else:
				# Generator mode: consume from the peek buffer.
				if self._peeked is not None:
					self._current = self._peeked
					self._peeked = None
					self._section_index += 1
					self._bar_in_section = 0
					self._peek_iterator()
					return True
				elif self._at_end == "hold":
					self._section_index += 1
					self._bar_in_section = 0
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

		return SectionInfo(
			name = self._current.name,
			bar = self._bar_in_section,
			bars = self._current.bars,
			index = self._section_index,
			next_section = self._next_section_name,
			energy = self._current.energy,
			key = self._current.key,
			scale = self._current.scale,
		)

	def section_info_at_bar (self, bar: int) -> typing.Optional[SectionInfo]:

		"""Return the section covering a 1-based GLOBAL bar, or ``None``.

		Available for **sequence** forms only (lists and ``Form`` values — the
		whole timeline is known, so a bar maps to a section by accumulating
		``Section.bars``).  Graph and generator forms have no fixed layout
		ahead of the playhead, so they return ``None`` (callers fall back to
		the playhead section).  A looping form wraps; a finite form past its
		end returns ``None``.

		Used to key a relative ``pin_chord`` to the section that *owns* the
		pinned bar rather than the section at the playhead — they differ when
		the harmonic clock's lookahead projects a pin into a later, possibly
		differently-keyed, section.  This is a layout lookup (linear from bar
		1); live ``form_jump`` is not reflected, which is acceptable for
		pre-set pins (the playhead path stays authoritative for live moves).
		"""

		if self._sequence is None or bar < 1:
			return None

		total = sum(section.bars for section in self._sequence)

		if total <= 0:
			return None

		index0 = bar - 1

		if index0 >= total:
			if self._at_end == "loop":
				index0 = index0 % total
			else:
				return None

		cursor = 0

		for position, section in enumerate(self._sequence):
			if cursor <= index0 < cursor + section.bars:
				following = self._sequence[position + 1].name if position + 1 < len(self._sequence) else None
				return SectionInfo(
					name = section.name,
					bar = index0 - cursor,
					bars = section.bars,
					index = position,
					next_section = following,
					energy = section.energy,
					key = section.key,
					scale = section.scale,
				)
			cursor += section.bars

		return None

	@property
	def total_bars (self) -> int:

		"""Return the global bar count since the form started."""

		return self._total_bars

	def jump_to (self, section_name: str) -> None:

		"""Force the form to a named section immediately.

		Available in **graph mode** (dict forms) and **sequence mode**
		(list/Form forms — the jump lands on the next occurrence of the
		name, searching forward and wrapping, and the form continues from
		there).  A generator form cannot be navigated.

		The section restarts from bar 0.  The musical effect is not heard
		until the *next pattern rebuild cycle*, because already-queued MIDI
		notes are unaffected.  This is the same natural quantization that
		applies to all ``composition.data`` writes and
		``composition.tweak()`` calls.

		Args:
			section_name: Name of the section to jump to.  Must exist in the
				form definition passed to ``composition.form()``.

		Raises:
			ValueError: If the form is a generator, or the name is unknown.

		Example::

			composition.form_jump("chorus")   # via Composition helper
		"""

		if self._sequence is not None:
			self._position = self._find_occurrence(section_name, "jump_to")
			self._current = self._sequence[self._position]
			self._bar_in_section = 0
			self._section_index += 1
			self._finished = False
			self._queued_position = None
			self._pick_next()
			logger.info(f"Form: jump → {section_name}")
			return

		if self._section_bars is None:
			raise ValueError(
				"jump_to() needs a navigable form (a graph dict, a list, or a Form value) — "
				"a generator form cannot be navigated"
			)

		if section_name not in self._section_bars:
			known = ", ".join(sorted(self._section_bars))
			raise ValueError(
				f"Section '{section_name}' not found in form. "
				f"Known sections: {known}"
			)

		self._current = subsequence.forms.Section(name = section_name, bars = self._section_bars[section_name])
		self._bar_in_section = 0
		self._section_index += 1
		self._finished = False
		self._pick_next()
		logger.info(f"Form: jump → {section_name}")
