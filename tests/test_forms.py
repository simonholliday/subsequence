"""Tests for stage 7 — Form payload, energy, and boundaries.

Section/Form values; form(Form, at_end=); form_freeze; list-mode
navigation; the "section" event + on_section; energy() + p.energy +
min_energy gating; Section.key re-anchoring; p.section.ending;
transition(); and sketches (d) and (e) end-to-end.
"""

import pathlib
import types
import typing
import unittest.mock

import mido
import pytest

import subsequence
import subsequence.composition
import subsequence.event_emitter
import subsequence.form_state
import subsequence.forms


# ---------------------------------------------------------------------------
# Section / Form values
# ---------------------------------------------------------------------------


def test_section_validates_loudly () -> None:

	"""Bad payloads raise at construction."""

	with pytest.raises(ValueError, match="at least 1 bar"):
		subsequence.Section("verse", 0)

	with pytest.raises(ValueError, match="energy"):
		subsequence.Section("verse", 4, energy=1.5)

	with pytest.raises(ValueError, match="name"):
		subsequence.Section("", 4)


def test_form_coerces_tuples_and_sections () -> None:

	"""Form([...]) accepts Sections and (name, bars) tuples interchangeably."""

	form = subsequence.Form([("verse", 8), subsequence.Section("chorus", 8, energy=0.9)])

	assert len(form) == 2
	assert form.bars == 16
	assert form.sections[0] == subsequence.Section("verse", 8)
	assert form.sections[1].energy == 0.9

	with pytest.raises(ValueError, match="at least one section"):
		subsequence.Form([])

	with pytest.raises(TypeError, match="Sections or"):
		subsequence.Form(["verse"])


def test_form_algebra_and_edits () -> None:

	"""+ concatenates; replace/insert/with_energy edit by 1-based slot."""

	S = subsequence.Section
	form = subsequence.Form([S("verse", 8), S("chorus", 8)])

	doubled = form + form
	assert len(doubled) == 4 and doubled.bars == 32

	stretched = form.replace(2, bars=16)
	assert stretched.sections[1].bars == 16
	assert stretched.sections[1].name == "chorus"
	assert form.sections[1].bars == 8		# the original is frozen

	swapped = form.replace(1, S("intro", 4))
	assert swapped.sections[0].name == "intro"

	with pytest.raises(ValueError, match="not both"):
		form.replace(1, S("intro", 4), bars=2)

	inserted = form.insert(2, ("bridge", 4))
	assert [section.name for section in inserted] == ["verse", "bridge", "chorus"]

	appended = form.insert(3, ("outro", 4))
	assert appended.sections[-1].name == "outro"

	energised = form.with_energy({"chorus": 0.95})
	assert energised.sections[1].energy == 0.95
	assert energised.sections[0].energy == 0.5

	with pytest.raises(ValueError, match="no section named"):
		form.with_energy({"drop": 1.0})


def test_form_describe_prints_slots_and_payload () -> None:

	"""describe() is the on-paper view: slots, bar ranges, payload."""

	form = subsequence.Form([subsequence.Section("verse", 8, energy=0.6, key="D")])
	text = form.describe()

	assert "verse" in text and "bars 1–8" in text and "energy=0.6" in text and "key=D" in text


# ---------------------------------------------------------------------------
# FormState: payloads, at_end, ending, navigation
# ---------------------------------------------------------------------------


def test_section_info_carries_payload () -> None:

	"""A bound Form's energy/key payloads ride SectionInfo."""

	form = subsequence.Form([subsequence.Section("verse", 2, energy=0.7, key="D")])
	state = subsequence.form_state.FormState(form)

	info = state.get_section_info()
	assert info is not None
	assert info.energy == 0.7 and info.key == "D"


def test_at_end_hold_repeats_the_final_section () -> None:

	"""hold: the last section repeats as a re-entry (index bumps)."""

	state = subsequence.form_state.FormState([("verse", 1), ("outro", 1)], at_end="hold")

	assert state.advance() is True		# verse -> outro
	info = state.get_section_info()
	assert info is not None and info.name == "outro" and info.index == 1
	assert info.next_section == "outro"		# holding: the next is itself

	assert state.advance() is True		# outro -> outro (the hold)
	info = state.get_section_info()
	assert info is not None and info.name == "outro" and info.index == 2 and info.bar == 0


def test_at_end_loop_matches_loop_sugar () -> None:

	"""loop=True is sugar for at_end="loop"."""

	for kwargs in ({"loop": True}, {"at_end": "loop"}):
		state = subsequence.form_state.FormState([("a", 1), ("b", 1)], **kwargs)
		assert state.advance() is True		# a -> b
		assert state.advance() is True		# b -> a (the loop)
		info = state.get_section_info()
		assert info is not None and info.name == "a"


def test_at_end_stop_finishes () -> None:

	"""stop (the default): the form ends; info goes None."""

	state = subsequence.form_state.FormState([("a", 1)])
	assert state.advance() is True
	assert state.get_section_info() is None


def test_at_end_validation () -> None:

	"""Graphs only take "stop"; generators cannot "loop"; unknown values raise."""

	with pytest.raises(ValueError, match="terminal"):
		subsequence.form_state.FormState({"a": (4, None)}, at_end="hold")

	with pytest.raises(ValueError, match="generator"):
		subsequence.form_state.FormState(iter([("a", 4)]), at_end="loop")

	with pytest.raises(ValueError, match="at_end"):
		subsequence.form_state.FormState([("a", 4)], at_end="freeze")


def test_section_ending_property () -> None:

	"""ending: True on the last bar before a DIFFERENT section only."""

	state = subsequence.form_state.FormState([("verse", 2), ("verse", 2), ("chorus", 2)])

	info = state.get_section_info()
	assert info is not None and info.ending is False		# bar 0 of 2

	state.advance()
	info = state.get_section_info()
	assert info is not None and info.last_bar is True
	assert info.ending is False		# verse -> verse: a repeat, not an ending

	state.advance(); state.advance()
	info = state.get_section_info()
	assert info is not None and info.name == "verse" and info.last_bar
	assert info.ending is True		# verse -> chorus

	state.advance(); state.advance()
	info = state.get_section_info()
	assert info is not None and info.name == "chorus" and info.last_bar
	assert info.ending is False		# the form ends after this — no incoming section


def test_sequence_jump_to_lands_on_next_occurrence () -> None:

	"""jump_to in sequence mode searches forward and wraps."""

	state = subsequence.form_state.FormState([("verse", 4), ("chorus", 4), ("verse", 4)])

	state.jump_to("chorus")
	info = state.get_section_info()
	assert info is not None and info.name == "chorus" and info.bar == 0 and info.index == 1
	assert info.next_section == "verse"		# the form continues from slot 2

	state.jump_to("verse")		# forward from chorus -> slot 3
	info = state.get_section_info()
	assert info is not None and info.name == "verse"
	assert info.next_section is None		# slot 3 is the last (at_end="stop")

	with pytest.raises(ValueError, match="not found"):
		state.jump_to("drop")


def test_sequence_queue_next_takes_effect_at_the_boundary () -> None:

	"""queue_next overrides the natural successor; the form continues from there."""

	state = subsequence.form_state.FormState([("a", 1), ("b", 1), ("c", 1)])

	state.queue_next("c")
	info = state.get_section_info()
	assert info is not None and info.next_section == "c"

	state.advance()
	info = state.get_section_info()
	assert info is not None and info.name == "c"		# skipped b
	assert info.next_section is None		# c is the last slot


def test_jump_to_revives_a_finished_sequence () -> None:

	"""Navigation works even after at_end="stop" finished the form."""

	state = subsequence.form_state.FormState([("a", 1), ("b", 1)])
	state.advance(); state.advance()
	assert state.get_section_info() is None

	state.jump_to("a")
	info = state.get_section_info()
	assert info is not None and info.name == "a"


# ---------------------------------------------------------------------------
# form_freeze
# ---------------------------------------------------------------------------


def test_form_freeze_walks_to_the_terminal (patch_midi: None) -> None:

	"""The frozen path starts at the current section and ends at a terminal."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1337)
	composition.form({
		"intro": (8, [("verse", 1)]),
		"verse": (16, [("drop", 1)]),
		"drop":  (16, [("break", 1)]),
		"break": (8, [("drop", 1), ("outro", 1)]),
		"outro": (8, None),
	}, start="intro")

	path = composition.form_freeze()

	assert isinstance(path, subsequence.Form)
	assert path.sections[0].name == "intro" and path.sections[0].bars == 8
	assert path.sections[-1].name == "outro"
	assert [section.name for section in path][:3] == ["intro", "verse", "drop"]


def test_form_freeze_reproduces_the_live_walk (patch_midi: None) -> None:

	"""The frozen path is the path the live graph would have played."""

	def build () -> subsequence.composition.Composition:
		composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=7)
		composition.form({
			"a": (1, [("b", 1), ("c", 1)]),
			"b": (1, [("a", 1), ("c", 1)]),
			"c": (1, None),
		}, start="a")
		return composition

	frozen = build().form_freeze()

	# Drive an identically-seeded live form to its end and record the path.
	live = build()
	assert live._form_state is not None
	played = []
	info = live._form_state.get_section_info()
	while info is not None:
		played.append(info.name)
		live._form_state.advance()
		info = live._form_state.get_section_info()

	assert [section.name for section in frozen] == played


def test_form_freeze_bounds_and_validation (patch_midi: None) -> None:

	"""sections= bounds the walk; terminal-less graphs require it; lists refuse."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=3)
	composition.form({
		"a": (4, [("b", 1)]),
		"b": (4, [("a", 1)]),
	}, start="a")

	with pytest.raises(ValueError, match="no terminal"):
		composition.form_freeze()

	path = composition.form_freeze(sections=5)
	assert len(path) == 5
	assert [section.name for section in path] == ["a", "b", "a", "b", "a"]

	composition.form([("a", 4)])
	with pytest.raises(ValueError, match="already a frozen sequence"):
		composition.form_freeze()


# ---------------------------------------------------------------------------
# energy() + p.energy + min_energy
# ---------------------------------------------------------------------------


def test_energy_validation (patch_midi: None) -> None:

	"""Levels are 0–1; ramps are 2-tuples."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	with pytest.raises(ValueError, match="0.0–1.0"):
		composition.energy({"verse": 1.5})

	with pytest.raises(ValueError, match=r"\(start, end\)"):
		composition.energy({"build": (0.2, 0.5, 1.0)})	# type: ignore[dict-item]


def test_energy_priority_dict_over_payload_over_default (patch_midi: None) -> None:

	"""The energy() dict overrides Section payloads; 0.5 with nothing configured."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	assert composition._current_energy(None) == 0.5

	composition.form(subsequence.Form([subsequence.Section("verse", 4, energy=0.7)]))
	info = composition._form_state.get_section_info() if composition._form_state else None
	assert composition._current_energy(info) == 0.7		# the payload

	composition.energy({"verse": 0.9})
	assert composition._current_energy(info) == 0.9		# the dict wins


def test_energy_ramp_interpolates_across_the_section (patch_midi: None) -> None:

	"""(start, end) tuples are the build gesture — linear over section progress."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	composition.form([("build", 4)])
	composition.energy({"build": (0.2, 1.0)})

	state = composition._form_state
	assert state is not None

	assert composition._current_energy(state.get_section_info()) == pytest.approx(0.2)

	state.advance(); state.advance()
	assert composition._current_energy(state.get_section_info()) == pytest.approx(0.2 + 0.8 * 0.5)


def test_min_energy_gates_the_pattern (patch_midi: None) -> None:

	"""Below the threshold the pattern is silent; raising the energy reopens it."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form([("verse", 4)])
	composition.energy({"verse": 0.3})

	@composition.pattern(channel=10, beats=4, drum_note_map={"conga": 63}, min_energy=0.8)
	def perc (p: typing.Any) -> None:
		p.hit("conga", beats=[0])

	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])
	assert not pattern.steps		# gated

	composition.energy({"verse": 0.9})
	pattern.on_reschedule()
	assert pattern.steps			# the gate opened


def test_p_energy_reaches_the_builder (patch_midi: None) -> None:

	"""p.energy reads the resolved level inside the builder."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form([("chorus", 4)])
	composition.energy({"chorus": 0.9})

	seen: typing.List[float] = []

	@composition.pattern(channel=1, beats=4)
	def lead (p: typing.Any) -> None:
		seen.append(p.energy)

	composition._build_pattern_from_pending(composition._pending_patterns[0])
	assert seen == [0.9]


def test_section_key_reanchors_degrees (patch_midi: None) -> None:

	"""Section.key moves the tonic for relative content bound in that section."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form(subsequence.Form([subsequence.Section("verse", 4, key="D")]))

	placed: typing.List[int] = []

	@composition.pattern(channel=1, beats=4)
	def lead (p: typing.Any) -> None:
		p.motif(subsequence.motif([1]), root=60)
		placed.extend(note.pitch for step in p._pattern.steps.values() for note in step.notes)

	composition._build_pattern_from_pending(composition._pending_patterns[0])
	assert placed == [62]		# degree 1 of D, anchored near middle C


# ---------------------------------------------------------------------------
# The "section" event + on_section + the on_bar hook
# ---------------------------------------------------------------------------


async def _capture_form_clock (
	form_state: subsequence.form_state.FormState,
	on_bar: typing.Optional[typing.Callable[[int, bool], None]] = None,
) -> typing.Tuple[typing.Callable[[int], None], subsequence.event_emitter.EventEmitter]:

	"""Schedule the form clock against a mock sequencer; return (callback, emitter)."""

	captured: typing.Dict[str, typing.Any] = {}

	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24
	mock_seq.time_signature = (4, 4)
	mock_seq.events = subsequence.event_emitter.EventEmitter()

	async def capture (callback: typing.Callable, interval_beats: float, start_pulse: int = 0, reschedule_lookahead: float = 1) -> None:
		captured["callback"] = callback

	mock_seq.schedule_callback_repeating = capture

	await subsequence.composition.schedule_form(
		sequencer = mock_seq,
		form_state = form_state,
		reschedule_lookahead = 1,
		on_bar = on_bar,
	)

	return captured["callback"], mock_seq.events


@pytest.mark.asyncio
async def test_section_event_fires_on_changes () -> None:

	"""The "section" event announces the opening section and every change."""

	state = subsequence.form_state.FormState([("verse", 1), ("chorus", 1)])
	heard: typing.List[typing.Optional[str]] = []

	# Register before scheduling so the initial announcement is caught.
	mock_seq = unittest.mock.MagicMock()
	mock_seq.pulses_per_beat = 24
	mock_seq.time_signature = (4, 4)
	mock_seq.events = subsequence.event_emitter.EventEmitter()
	mock_seq.events.on("section", lambda info: heard.append(info.name if info else None))

	captured: typing.Dict[str, typing.Any] = {}

	async def capture (callback: typing.Callable, interval_beats: float, start_pulse: int = 0, reschedule_lookahead: float = 1) -> None:
		captured["callback"] = callback

	mock_seq.schedule_callback_repeating = capture

	await subsequence.composition.schedule_form(mock_seq, state, reschedule_lookahead=1)

	assert heard == ["verse"]		# the opening announcement

	cb = captured["callback"]
	cb(72)		# the verse/chorus boundary (bar line 96, lookahead 24)
	cb(168)		# the chorus/end boundary

	assert heard == ["verse", "chorus", None]


@pytest.mark.asyncio
async def test_on_bar_hook_receives_boundary_pulses () -> None:

	"""The boundary hook gets the bar-line pulse (fire pulse + lookahead) per bar."""

	state = subsequence.form_state.FormState([("verse", 2)])
	calls: typing.List[typing.Tuple[int, bool]] = []

	cb, _events = await _capture_form_clock(state, on_bar=lambda pulse, changed: calls.append((pulse, changed)))

	assert calls == [(0, True)]		# the schedule-time check for bar 0

	cb(72)		# fires lookahead-early for the bar line at pulse 96
	assert calls[-1] == (96, False)


def test_on_section_registers_on_the_composition (patch_midi: None) -> None:

	"""comp.on_section is sugar over the sequencer's "section" event."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	heard: typing.List[typing.Any] = []

	composition.on_section(heard.append)
	composition._sequencer.events.emit_sync("section", "probe")

	assert heard == ["probe"]


# ---------------------------------------------------------------------------
# transition()
# ---------------------------------------------------------------------------


def test_transition_validation (patch_midi: None) -> None:

	"""Actionless rules and homeless fills raise."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	with pytest.raises(ValueError, match="fill= and/or mute="):
		composition.transition(before="*")

	with pytest.raises(ValueError, match="channel="):
		composition.transition(before="*", fill=subsequence.Motif.hits("snare", beats=[0], length=1))


def test_transition_fill_fires_in_the_final_bar (patch_midi: None) -> None:

	"""The fill one-shot lands at the final bar's start + beat, with a borrowed drum map."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form([("verse", 2), ("chorus", 2)])

	fill = subsequence.Motif.hits("snare", beats=[0, 0.5], length=2)
	composition.transition(before="*", fill=fill, channel=10, beat=2.0)

	# A registered pattern on channel 10 donates its drum map to the fill.
	@composition.pattern(channel=10, beats=4, drum_note_map={"kick": 36, "snare": 38})
	def drums (p: typing.Any) -> None:
		p.hit("kick", beat=0)

	fired: typing.List[typing.Tuple[typing.Any, int]] = []
	composition._schedule_one_shot = lambda pattern, start_pulse: fired.append((pattern, start_pulse))	# type: ignore[method-assign]

	state = composition._form_state
	assert state is not None

	# Bar 0 of verse: not the last bar — nothing fires.
	composition._check_transitions(0, True)
	assert fired == []

	# Bar 1 of verse (the final bar before chorus): the fill fires at +2 beats.
	state.advance()
	composition._check_transitions(96, False)

	assert len(fired) == 1
	pattern, start_pulse = fired[0]
	assert start_pulse == 96 + 2 * 24
	pitches = [note.pitch for step in pattern.steps.values() for note in step.notes]
	assert pitches == [38, 38]		# the borrowed map resolved "snare"


def test_transition_star_skips_repeats (patch_midi: None) -> None:

	"""before="*" means a DIFFERENT section — verse→verse does not fire."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form([("verse", 1), ("verse", 1), ("chorus", 1)])
	composition.transition(before="*", fill=subsequence.Motif.hits("snare", beats=[0], length=1), channel=10,
		drum_note_map={"snare": 38})

	fired: typing.List[int] = []
	composition._schedule_one_shot = lambda pattern, start_pulse: fired.append(start_pulse)	# type: ignore[method-assign]

	composition._check_transitions(0, True)		# verse bar 0 (last bar) -> verse: a repeat
	assert fired == []

	state = composition._form_state
	assert state is not None
	state.advance()
	composition._check_transitions(96, True)		# verse -> chorus next: fires
	assert fired == [96]


def test_transition_mute_closes_and_reopens (patch_midi: None) -> None:

	"""mute= closes named patterns over the approach and restores them at the boundary."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=1)
	composition.form([("verse", 2), ("chorus", 2)])
	composition.transition(before="chorus", mute=["kick_pattern"], beats=4)

	kick = types.SimpleNamespace(_muted=False, channel=9)
	performer_muted = types.SimpleNamespace(_muted=True, channel=9)
	composition._running_patterns["kick_pattern"] = kick		# type: ignore[assignment]
	composition._running_patterns["pads"] = performer_muted	# type: ignore[assignment]

	state = composition._form_state
	assert state is not None

	composition._check_transitions(0, True)
	assert kick._muted is False		# bar 0: outside the 1-bar window

	state.advance()
	composition._check_transitions(96, False)
	assert kick._muted is True		# the approach: muted

	state.advance()		# the boundary: chorus begins
	composition._check_transitions(192, True)
	assert kick._muted is False		# restored
	assert performer_muted._muted is True		# the performer's mute was never ours to touch


# ---------------------------------------------------------------------------
# Sketches (d) and (e) — the acceptance contract
# ---------------------------------------------------------------------------


def test_sketch_d_fills_and_energy_layers (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""Sketch (d): automatic fill before every section change; energy-driven layers."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="C", seed=42)
	composition.form([("verse", 2), ("chorus", 2)], loop=True)

	DRUM_MAP = {"kick": 36, "snare": 38, "hh": 42, "conga": 63}

	KICK = subsequence.Motif.hits("kick", beats=[0, 1.5, 3], length=4)
	FILL = subsequence.Motif.hits("snare",
		beats=[0, 0.5, 1.0, 1.25] + [1.5 + i * 0.125 for i in range(4)],
		length=2)

	composition.energy({"verse": 0.5, "chorus": 0.9})
	composition.transition(before="*", fill=FILL, channel=10, beat=2.0)

	@composition.pattern(channel=10, beats=4, drum_note_map=DRUM_MAP)
	def drums (p: typing.Any) -> None:
		p.motif(KICK)
		if p.energy >= 0.6:
			p.euclidean("hh", pulses=int(5 + 6 * p.energy), velocity=(60, 90))

	@composition.pattern(channel=10, beats=4, drum_note_map=DRUM_MAP, min_energy=0.8)
	def perc (p: typing.Any) -> None:
		p.bresenham("conga", 7)

	composition.render(bars=4, filename=str(tmp_path / "sketch_d.mid"))

	mid = mido.MidiFile(str(tmp_path / "sketch_d.mid"))
	tpb = mid.ticks_per_beat

	notes: typing.List[typing.Tuple[float, int]] = []
	for track in mid.tracks:
		now = 0
		for msg in track:
			now += msg.time
			if not isinstance(msg, mido.MetaMessage) and msg.type == "note_on" and msg.velocity > 0:
				notes.append((now / tpb, msg.note))

	verse_window = [n for beat, n in notes if beat < 8]
	chorus_window = [n for beat, n in notes if 8 <= beat < 16]

	# Energy layers: hats and congas only in the chorus (0.9 >= thresholds).
	assert 42 not in verse_window and 63 not in verse_window
	assert 42 in chorus_window and 63 in chorus_window

	# The fill: snares in the back half of bar 2 (the last verse bar) — the
	# transition fired automatically before the section change.
	fill_notes = [beat for beat, n in notes if n == 38 and 6 <= beat < 8]
	assert len(fill_notes) == 8


def test_sketch_e_full_song_runs_as_written (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""Sketch (e): explicit form with payload, generated + manual material,
	frozen, inspected, two hand-edits, rebound."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="C", scale="major", seed=42)

	S = subsequence.Section
	form = subsequence.Form([
		S("verse", bars=8, energy=0.55), S("verse", bars=8, energy=0.6),
		S("chorus", bars=8, energy=0.9), S("verse", bars=8, energy=0.65),
		S("outro", bars=4, energy=0.3),
	])

	composition.harmony(style="functional_major", cycle_beats=4)
	verse_prog = composition.freeze(8)
	chorus_prog = subsequence.progression(style="functional_major", bars=8, end=1, seed=9)

	theme = subsequence.motif([1, 3, 5, 6, 5, 3, 2], durations=[1, 1, 1, 1, 1, 1, 2])
	verse_line = subsequence.Phrase.develop(theme, bars=8, plan=["a", "a", "a", "b"], seed=4)

	print(verse_prog); print(verse_line)
	verse_prog = verse_prog.replace(6, "Dm9")
	verse_line = verse_line.replace(4, subsequence.motif([3, 2, 1], durations=[1, 1, 2]))

	composition.form(form, at_end="stop")
	composition.section_chords("verse", verse_prog)
	composition.section_chords("chorus", chorus_prog)
	composition.section_motifs("verse", verse_line, part="lead")
	composition.phrase_part(channel=4, root=72, part="lead", fit=0.7)

	# The edits took: chord 6 is decorated, segment 4 was swapped.
	assert verse_prog.spans[5].extensions == (9,)
	assert verse_line.segments[3].length == 4.0

	composition.render(bars=10, filename=str(tmp_path / "sketch_e.mid"))

	mid = mido.MidiFile(str(tmp_path / "sketch_e.mid"))
	lead_notes = 0
	for track in mid.tracks:
		for msg in track:
			if not isinstance(msg, mido.MetaMessage) and msg.type == "note_on" and msg.velocity > 0 and msg.channel == 3:
				lead_notes += 1

	assert lead_notes > 0		# the verse's bound lead actually sounded


def test_sketch_f_fully_generated_from_one_seed (tmp_path: pathlib.Path, patch_midi: None) -> None:

	"""Sketch (f): fully generated from one seed — keep what works, reroll what
	doesn't.  Every line is a declared primitive; no compose() magic."""

	DRUM_MAP = {"kick": 36, "snare": 38, "hh": 42, "conga": 63}

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=480, key="F#", scale="minor", seed=1337)
	composition.harmony(style="phrygian_minor", cycle_beats=4)
	composition.form({
		"intro": (8, [("verse", 1)]),
		"verse": (16, [("drop", 1)]),
		"drop":  (16, [("break", 1)]),
		"break": (8, [("drop", 1), ("outro", 1)]),
		"outro": (8, None),
	}, start="intro")

	path = composition.form_freeze()                 # graph walk -> editable, seeded Form
	composition.form(path, at_end="stop")
	composition.energy({"intro": 0.2, "verse": 0.55, "drop": 0.95, "break": 0.35, "outro": 0.2})

	for name, bars in (("verse", 16), ("drop", 16), ("break", 8)):
		composition.section_chords(name, composition.freeze(bars))

	hook = subsequence.Motif.generate(
		rhythm=[0, 1, 1.5, 1.75, 2.5], scale="minor_pentatonic",
		contour="arch", end_on=1, seed=composition.seed_for("hook"),
	)
	verse_line = subsequence.Phrase.develop(hook, bars=8, plan="call_response",
		seed=composition.seed_for("verse_line"))
	drop_line = subsequence.Phrase.develop(hook.transpose(steps=2), bars=8,
		plan=["a", "a", "a", "b"], seed=composition.seed_for("drop_line"))

	KICK = subsequence.Motif.euclidean(5, 16, "kick", length=4)
	HATS = subsequence.Motif.euclidean(11, 16, "hh", length=4)

	@composition.pattern(channel=10, beats=4, drum_note_map=DRUM_MAP)
	def drums (p: typing.Any) -> None:
		p.motif(KICK & HATS)

	drop_line = drop_line.reroll(bars=[5, 6], seed=2)
	composition.section_motifs("verse", verse_line, part="lead")
	composition.section_motifs("drop", drop_line, part="lead")
	composition.phrase_part(channel=4, root=78, part="lead")

	# The frozen path is the seeded walk: intro first, outro terminal.
	assert path.sections[0].name == "intro"
	assert path.sections[-1].name == "outro"

	# Render across the intro/verse boundary: the verse's bound lead enters.
	composition.render(bars=12, filename=str(tmp_path / "sketch_f.mid"))

	mid = mido.MidiFile(str(tmp_path / "sketch_f.mid"))
	tpb = mid.ticks_per_beat

	drum_notes = 0
	lead_beats: typing.List[float] = []
	for track in mid.tracks:
		now = 0
		for msg in track:
			now += msg.time
			if isinstance(msg, mido.MetaMessage) or msg.type != "note_on" or msg.velocity == 0:
				continue
			if msg.channel == 9:
				drum_notes += 1
			if msg.channel == 3:
				lead_beats.append(now / tpb)

	assert drum_notes > 0
	assert lead_beats and min(lead_beats) >= 32.0		# silent intro; the lead enters with the verse
