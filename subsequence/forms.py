"""Forms — the governing values for compositional structure.

:class:`Section` is the payload home: a frozen ``(name, bars, energy, key)``
leaf.  :class:`Form` is a frozen tuple of Sections — constructible from
Sections or plain ``(name, bars)`` tuples (lists coerce), editable by slot
(:meth:`Form.replace` / :meth:`Form.insert` / :meth:`Form.with_energy`),
and concatenable with ``+``.  Repetition is Python:
``[verse, verse, chorus] == [verse] * 2 + [chorus]`` — no letters DSL.

Bind a Form with ``composition.form(form, at_end="stop"|"hold"|"loop")``;
generate one from a graph form with ``composition.form_freeze()``.

Sections compose as plain Python lists that Form coerces — ``Section`` is a
leaf, not an operator algebra.
"""

import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class Section:

	"""One section of a form — the payload home.

	Attributes:
		name: The section name (``"verse"``).
		bars: Length in bars (≥ 1).
		energy: The section's energy level (0.0–1.0; the arranging dial).
			Read by ``p.energy`` and ``min_energy=`` gating; a
			``composition.energy()`` dict overrides it (the dict is the
			later, performance-level dial).
		key: Optional key override — re-anchors *key-relative* content
			(degrees, romans, generated material, and key-relative section
			progressions bound with ``section_chords``) to this section's
			tonic.  *Absolute* content (note names, MIDI pitches, frozen
			chords) is never moved, and *chord-relative* content
			(``ChordTone``, ``Approach``) tracks the sounding chord rather
			than the key — see the three-intent model in the docs.  The
			live graph engine (``harmony(style=...)``) stays in the
			composition key by design (a stateful walk does not transpose
			mid-stream).
		scale: Optional scale/mode override (e.g. ``"minor"``) — moves the
			mode as well as the tonic, so a section can genuinely change
			to the relative or parallel minor.  Falls back to the form's
			scale, then the composition's.
	"""

	name: str
	bars: int
	energy: float = 0.5
	key: typing.Optional[str] = None
	scale: typing.Optional[str] = None

	def __post_init__ (self) -> None:

		"""Validate the payload loudly."""

		if not isinstance(self.name, str) or not self.name:
			raise ValueError(f"a section needs a non-empty string name, got {self.name!r}")

		if not isinstance(self.bars, int) or isinstance(self.bars, bool) or self.bars < 1:
			raise ValueError(f"Section {self.name!r} must last at least 1 bar, got {self.bars!r}")

		if not 0.0 <= float(self.energy) <= 1.0:
			raise ValueError(f"Section {self.name!r} energy must be 0.0–1.0, got {self.energy!r}")


def _coerce_section (element: typing.Any) -> Section:

	"""Coerce a Form element — a Section passes through, a (name, bars) tuple converts."""

	if isinstance(element, Section):
		return element

	if isinstance(element, tuple) and len(element) == 2:
		name, bars = element
		return Section(name = name, bars = bars)

	raise TypeError(
		f"Form elements are Sections or (name, bars) tuples — got {element!r}"
	)


@dataclasses.dataclass(frozen=True)
class Form:

	"""A frozen sequence of Sections — the editable, bindable form value.

	List-friendly: the constructor coerces ``("name", bars)`` tuples, so
	``Form([("verse", 8), ("chorus", 8)])`` and
	``Form([Section("verse", 8), Section("chorus", 8)])`` are the same value.
	Repetition is Python list arithmetic before construction.

	A form may carry its own ``key``/``scale`` — the **form tier** of the
	key-source chain (``Section.key`` overrides it; it overrides the
	composition key).  A whole AABA in one key with one section borrowing
	another is ``Form([...], key="A")`` plus a ``Section(..., key="F")``.
	"""

	sections: typing.Tuple[Section, ...]
	key: typing.Optional[str] = None
	scale: typing.Optional[str] = None

	def __init__ (
		self,
		sections: typing.Iterable[typing.Any],
		key: typing.Optional[str] = None,
		scale: typing.Optional[str] = None,
	) -> None:

		"""Coerce any iterable of Sections / (name, bars) tuples."""

		coerced = tuple(_coerce_section(element) for element in sections)

		if not coerced:
			raise ValueError("a Form needs at least one section")

		object.__setattr__(self, "sections", coerced)
		object.__setattr__(self, "key", key)
		object.__setattr__(self, "scale", scale)

	@property
	def bars (self) -> int:

		"""Total length in bars."""

		return sum(section.bars for section in self.sections)

	def __len__ (self) -> int:

		"""Number of sections."""

		return len(self.sections)

	def __iter__ (self) -> typing.Iterator[Section]:

		"""Iterate the sections in order."""

		return iter(self.sections)

	def __add__ (self, other: "Form") -> "Form":

		"""Sequential concatenation: ``intro_form + body_form``.

		The **left** operand's form-tier ``key``/``scale`` survives (a single
		value cannot hold two form keys); the right form's form-tier key is
		dropped.  Per-section ``Section.key``/``scale`` on either side is
		preserved — the sections concatenate intact.
		"""

		if not isinstance(other, Form):
			return NotImplemented

		return Form(self.sections + other.sections, key = self.key, scale = self.scale)

	def replace (
		self,
		slot: int,
		section: typing.Optional[Section] = None,
		**changes: typing.Any,
	) -> "Form":

		"""Replace the section at a 1-based slot — whole, or by field.

		``form.replace(3, bars=16)`` stretches slot 3;
		``form.replace(3, Section("drop", 16, energy=1.0))`` swaps it out.
		"""

		index = _check_slot(slot, len(self.sections))

		if section is not None and changes:
			raise ValueError("pass either a Section or field changes, not both")

		if section is None:
			if not changes:
				raise ValueError("replace() needs a Section or field changes (bars=, energy=, key=, name=)")
			section = dataclasses.replace(self.sections[index], **changes)

		return Form(self.sections[:index] + (_coerce_section(section),) + self.sections[index + 1:], key = self.key, scale = self.scale)

	def insert (self, slot: int, section: typing.Any) -> "Form":

		"""Insert a section *at* a 1-based slot (existing sections shift right).

		``slot`` may be ``len(form) + 1`` to append.
		"""

		if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= len(self.sections) + 1:
			raise ValueError(f"slot {slot!r} is out of range (1–{len(self.sections) + 1})")

		index = slot - 1

		return Form(self.sections[:index] + (_coerce_section(section),) + self.sections[index:], key = self.key, scale = self.scale)

	def with_energy (self, energies: typing.Dict[str, float]) -> "Form":

		"""Set the energy payload on named sections — ``{"chorus": 0.9}``.

		Every section whose name appears in the mapping takes the new value;
		naming a section the form does not contain raises.  Energy *ramps*
		(``(start, end)`` tuples) live in ``composition.energy()``, not in
		the payload — a Section carries one number.
		"""

		names = {section.name for section in self.sections}

		for name in energies:
			if name not in names:
				known = ", ".join(sorted(names))
				raise ValueError(f"with_energy: no section named {name!r} in this form (sections: {known})")

		return Form(tuple(
			dataclasses.replace(section, energy = energies[section.name])
			if section.name in energies else section
			for section in self.sections
		), key = self.key, scale = self.scale)

	def describe (self) -> str:

		"""A readable one-section-per-line summary."""

		lines = [f"Form — {len(self.sections)} sections over {self.bars} bars"]

		if self.key is not None or self.scale is not None:
			lines.append(f"  (form key={self.key or '–'} scale={self.scale or '–'})")

		bar = 1

		for slot, section in enumerate(self.sections, start = 1):
			extras = f"  energy={section.energy:g}"
			if section.key is not None:
				extras += f"  key={section.key}"
			if section.scale is not None:
				extras += f"  scale={section.scale}"
			lines.append(f"  {slot}. bars {bar}–{bar + section.bars - 1}  {section.name:<10} ({section.bars} bars){extras}")
			bar += section.bars

		return "\n".join(lines)

	def __str__ (self) -> str:

		"""Same as :meth:`describe`."""

		return self.describe()


def _check_slot (slot: int, count: int) -> int:

	"""Validate a 1-based section slot and return its 0-based index."""

	if not isinstance(slot, int) or isinstance(slot, bool):
		raise TypeError(f"section slots are 1-based ints, got {slot!r}")
	if slot < 1 or slot > count:
		raise ValueError(f"section slot {slot} is out of range (1–{count})")

	return slot - 1
