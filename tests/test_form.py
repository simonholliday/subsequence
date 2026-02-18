import random

import pytest

import subsequence
import subsequence.composition
import subsequence.pattern
import subsequence.sequencer


# --- FormState ---


def test_form_state_initial_section () -> None:

	"""FormState should expose the first section immediately after creation."""

	form = subsequence.composition.FormState([("intro", 4), ("verse", 8)])
	section = form.get_section_info()

	assert section is not None
	assert section.name == "intro"
	assert section.bar == 0
	assert section.bars == 4
	assert section.index == 0


def test_form_state_advance_within_section () -> None:

	"""Advancing within a section should increment bar but keep the same name."""

	form = subsequence.composition.FormState([("intro", 4), ("verse", 8)])

	form.advance()
	section = form.get_section_info()

	assert section is not None
	assert section.name == "intro"
	assert section.bar == 1
	assert section.bars == 4

	form.advance()
	section = form.get_section_info()

	assert section.name == "intro"
	assert section.bar == 2


def test_form_state_advance_to_next_section () -> None:

	"""Advancing past a section boundary should transition to the next section."""

	form = subsequence.composition.FormState([("intro", 2), ("verse", 4)])

	# Bar 0 → 1
	form.advance()
	assert form.get_section_info().name == "intro"

	# Bar 1 → section complete → transition to verse, bar 0
	form.advance()
	section = form.get_section_info()

	assert section.name == "verse"
	assert section.bar == 0
	assert section.bars == 4
	assert section.index == 1


def test_form_state_loop () -> None:

	"""A looping form should cycle back to the first section."""

	form = subsequence.composition.FormState([("A", 2), ("B", 2)], loop=True)

	# Advance through A (2 bars) + B (2 bars) = 4 advances
	for _ in range(4):
		form.advance()

	# Should be back to A, bar 0
	section = form.get_section_info()

	assert section is not None
	assert section.name == "A"
	assert section.bar == 0
	assert section.index == 2


def test_form_state_finite_exhausts () -> None:

	"""A non-looping form should return None after all sections are complete."""

	form = subsequence.composition.FormState([("only", 2)])

	form.advance()
	form.advance()

	assert form.get_section_info() is None


def test_form_state_generator () -> None:

	"""FormState should work with a generator of (name, bars) tuples."""

	def my_form ():
		yield ("intro", 2)
		yield ("verse", 4)

	form = subsequence.composition.FormState(my_form())

	section = form.get_section_info()
	assert section.name == "intro"

	# Advance past intro
	form.advance()
	form.advance()

	section = form.get_section_info()
	assert section.name == "verse"
	assert section.bar == 0

	# Advance past verse
	for _ in range(4):
		form.advance()

	assert form.get_section_info() is None


def test_form_state_total_bars () -> None:

	"""The total_bars counter should track the global bar count across sections."""

	form = subsequence.composition.FormState([("A", 2), ("B", 3)])

	assert form.total_bars == 0

	form.advance()
	assert form.total_bars == 1

	form.advance()
	assert form.total_bars == 2

	form.advance()
	assert form.total_bars == 3


# --- SectionInfo ---


def test_section_info_progress () -> None:

	"""Progress should reflect position within the section as 0.0 to ~1.0."""

	info = subsequence.composition.SectionInfo(name="verse", bar=0, bars=8, index=0)
	assert info.progress == 0.0

	info = subsequence.composition.SectionInfo(name="verse", bar=4, bars=8, index=0)
	assert info.progress == 0.5

	info = subsequence.composition.SectionInfo(name="verse", bar=7, bars=8, index=0)
	assert info.progress == 7 / 8


def test_section_info_first_last_bar () -> None:

	"""first_bar and last_bar should be correct at section boundaries."""

	first = subsequence.composition.SectionInfo(name="A", bar=0, bars=4, index=0)
	assert first.first_bar is True
	assert first.last_bar is False

	last = subsequence.composition.SectionInfo(name="A", bar=3, bars=4, index=0)
	assert last.first_bar is False
	assert last.last_bar is True

	mid = subsequence.composition.SectionInfo(name="A", bar=2, bars=4, index=0)
	assert mid.first_bar is False
	assert mid.last_bar is False


# --- Composition integration ---


def test_composition_form_registers_state (patch_midi: None) -> None:

	"""Calling form() should store a FormState on the composition."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	composition.form([("intro", 4), ("verse", 8)])

	assert composition._form_state is not None
	assert composition._form_state.get_section_info().name == "intro"


def test_section_injected_into_builder (patch_midi: None) -> None:

	"""Builder functions should receive section info via p.section when form is configured."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	composition.form([("intro", 4), ("verse", 8)])

	received_sections = []

	def my_builder (p):
		received_sections.append(p.section)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._build_pattern_from_pending(pending)

	assert len(received_sections) == 1
	assert received_sections[0] is not None
	assert received_sections[0].name == "intro"
	assert received_sections[0].bar == 0


def test_no_form_section_is_none (patch_midi: None) -> None:

	"""Without form(), p.section should be None."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	received_sections = []

	def my_builder (p):
		received_sections.append(p.section)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._build_pattern_from_pending(pending)

	assert received_sections == [None]


def test_builder_bar_available (patch_midi: None) -> None:

	"""Builder functions should have access to p.bar (global bar count)."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	received_bars = []

	def my_builder (p):
		received_bars.append(p.bar)

	pending = subsequence.composition._PendingPattern(
		builder_fn = my_builder,
		channel = 1,
		length = 4,
		drum_note_map = None,
		reschedule_lookahead = 1,
		default_grid = 16
	)

	composition._build_pattern_from_pending(pending)

	assert received_bars == [0]


def test_form_state_empty_list () -> None:

	"""An empty section list should immediately exhaust."""

	form = subsequence.composition.FormState([])

	assert form.get_section_info() is None


def test_form_state_advance_returns_section_changed () -> None:

	"""advance() should return True when transitioning to a new section."""

	form = subsequence.composition.FormState([("A", 2), ("B", 2)])

	# Bar 0 → 1 within section A.
	changed = form.advance()
	assert changed is False
	assert form.get_section_info().name == "A"

	# Bar 1 → 2, transition to section B.
	changed = form.advance()
	assert changed is True
	assert form.get_section_info().name == "B"

	# Bar 0 → 1 within section B.
	changed = form.advance()
	assert changed is False
	assert form.get_section_info().name == "B"

	# Bar 1 → exhausted.
	changed = form.advance()
	assert changed is True
	assert form.get_section_info() is None


# --- Graph-based FormState ---


def test_form_state_graph_initial_section () -> None:

	"""Graph-based FormState should expose the start section immediately after creation."""

	form = subsequence.composition.FormState({
		"intro": (4, [("verse", 1)]),
		"verse": (8, [("chorus", 1)]),
		"chorus": (8, []),
	}, start="intro")

	section = form.get_section_info()

	assert section is not None
	assert section.name == "intro"
	assert section.bar == 0
	assert section.bars == 4
	assert section.index == 0


def test_form_state_graph_advance_within_section () -> None:

	"""Advancing within a graph section should increment bar but keep the same name."""

	form = subsequence.composition.FormState({
		"intro": (4, [("verse", 1)]),
		"verse": (8, []),
	}, start="intro")

	form.advance()
	section = form.get_section_info()

	assert section.name == "intro"
	assert section.bar == 1


def test_form_state_graph_transition () -> None:

	"""Graph-based form should transition to the next section when bars are exhausted."""

	form = subsequence.composition.FormState({
		"intro": (2, [("verse", 1)]),
		"verse": (4, []),
	}, start="intro")

	# Advance through intro (2 bars).
	form.advance()
	form.advance()

	section = form.get_section_info()

	assert section.name == "verse"
	assert section.bar == 0
	assert section.bars == 4
	assert section.index == 1


def test_form_state_graph_weighted_transition () -> None:

	"""Graph transitions should follow weighted probabilities."""

	counts = {"chorus": 0, "bridge": 0}

	for seed in range(100):

		rng = random.Random(seed)

		form = subsequence.composition.FormState({
			"verse": (1, [("chorus", 3), ("bridge", 1)]),
			"chorus": (1, [("verse", 1)]),
			"bridge": (1, [("verse", 1)]),
		}, start="verse", rng=rng)

		form.advance()
		section = form.get_section_info()
		counts[section.name] += 1

	# With 3:1 weights, chorus should get ~75%. Allow a generous margin.
	assert counts["chorus"] > 50
	assert counts["bridge"] > 5


def test_form_state_graph_dead_end_self_loops () -> None:

	"""A section with no outgoing edges should loop itself."""

	form = subsequence.composition.FormState({
		"intro": (2, [("end", 1)]),
		"end":   (2, []),
	}, start="intro")

	# Advance through intro.
	form.advance()
	form.advance()

	assert form.get_section_info().name == "end"

	# Advance through "end" - should self-loop.
	form.advance()
	form.advance()

	section = form.get_section_info()

	assert section.name == "end"
	assert section.bar == 0
	assert section.index == 2


def test_form_state_graph_never_finishes () -> None:

	"""Graph-based form should never exhaust - it always has a next section."""

	form = subsequence.composition.FormState({
		"A": (1, [("B", 1)]),
		"B": (1, [("A", 1)]),
	}, start="A")

	for _ in range(100):
		form.advance()
		assert form.get_section_info() is not None


def test_form_state_graph_default_start () -> None:

	"""Omitting start= should default to the first key in the dict."""

	form = subsequence.composition.FormState({
		"alpha": (2, [("beta", 1)]),
		"beta":  (2, [("alpha", 1)]),
	})

	assert form.get_section_info().name == "alpha"


def test_form_state_graph_invalid_start_raises () -> None:

	"""Passing a start section not in the dict should raise ValueError."""

	with pytest.raises(ValueError):

		subsequence.composition.FormState({
			"A": (2, [("B", 1)]),
			"B": (2, []),
		}, start="Z")


def test_form_state_graph_total_bars () -> None:

	"""The total_bars counter should track across graph transitions."""

	form = subsequence.composition.FormState({
		"A": (2, [("B", 1)]),
		"B": (2, [("A", 1)]),
	}, start="A")

	assert form.total_bars == 0

	form.advance()
	assert form.total_bars == 1

	form.advance()
	assert form.total_bars == 2

	form.advance()
	assert form.total_bars == 3


def test_form_state_graph_section_progress () -> None:

	"""Section progress should reflect position within graph-mode sections."""

	form = subsequence.composition.FormState({
		"verse": (4, [("verse", 1)]),
	}, start="verse")

	assert form.get_section_info().progress == 0.0

	form.advance()
	assert form.get_section_info().progress == 0.25

	form.advance()
	assert form.get_section_info().progress == 0.5


def test_composition_form_graph_registers_state (patch_midi: None) -> None:

	"""Calling form() with a dict should create a graph-mode FormState."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="C")

	composition.form({
		"intro": (4, [("verse", 1)]),
		"verse": (8, []),
	}, start="intro")

	assert composition._form_state is not None
	assert composition._form_state.get_section_info().name == "intro"


# --- Terminal graph sections ---


def test_form_state_graph_terminal_section () -> None:

	"""A section with None transitions should end the form after completing."""

	form = subsequence.composition.FormState({
		"intro": (2, [("outro", 1)]),
		"outro": (2, None),
	}, start="intro")

	# Advance through intro (2 bars).
	form.advance()
	form.advance()

	assert form.get_section_info().name == "outro"

	# Advance through outro (2 bars) - form should end.
	form.advance()
	form.advance()

	assert form.get_section_info() is None


def test_form_state_graph_terminal_vs_dead_end () -> None:

	"""None transitions end the form; empty list transitions self-loop."""

	# Terminal: None → form ends.
	terminal = subsequence.composition.FormState({
		"end": (1, None),
	}, start="end")

	terminal.advance()
	assert terminal.get_section_info() is None

	# Dead end: [] → self-loops.
	dead_end = subsequence.composition.FormState({
		"end": (1, []),
	}, start="end")

	dead_end.advance()
	assert dead_end.get_section_info() is not None
	assert dead_end.get_section_info().name == "end"


def test_form_state_graph_terminal_advance_returns_changed () -> None:

	"""advance() should return True when the form ends at a terminal section."""

	form = subsequence.composition.FormState({
		"only": (2, None),
	}, start="only")

	changed = form.advance()
	assert changed is False

	changed = form.advance()
	assert changed is True
	assert form.get_section_info() is None
