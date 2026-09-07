"""Tests for reading back what has been placed on a pattern being built.

``placed()`` exists so a control surface can draw a generated layer differently
from the steps somebody tapped: call it either side of a generator and take the
difference.  That makes two things load-bearing that a looser read-back would
get away with — the answer must be immutable (a caller must not be able to edit
the pattern through it) and two notes that look identical must stay distinct,
or the difference silently loses the second one.
"""

import dataclasses
import typing

import pytest

import subsequence.catalogue
import subsequence.constants
import subsequence.pattern
import subsequence.pattern_builder


_PPQ = subsequence.constants.MIDI_QUARTER_NOTE


def _builder (
	drum_note_map: typing.Optional[typing.Dict[str, int]] = None,
	mirrors: typing.Optional[typing.List[typing.Any]] = None,
) -> subsequence.pattern_builder.PatternBuilder:

	"""A PatternBuilder over a bare 4-beat pattern (no MIDI required)."""

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0, mirrors=mirrors)

	return subsequence.pattern_builder.PatternBuilder(
		pattern, cycle=0, drum_note_map=drum_note_map,
	)


# ---------------------------------------------------------------------------
# What a record carries
# ---------------------------------------------------------------------------

def test_nothing_placed_reads_back_as_nothing () -> None:

	"""An untouched builder reports an empty list, not None."""

	assert _builder().placed() == []


def test_a_note_reads_back_with_its_position_velocity_and_duration () -> None:

	"""Position and duration are in pulses — the unit the pattern stores."""

	p = _builder()
	p.note(60, beat=1.0, velocity=99, duration=0.5)

	placed = p.placed()

	assert len(placed) == 1
	assert placed[0].pitch == 60
	assert placed[0].position == _PPQ
	assert placed[0].velocity == 99
	assert placed[0].duration == _PPQ // 2
	assert placed[0].origin is None


def test_a_named_drum_hit_carries_the_name_that_asked_for_it () -> None:

	"""``origin`` is the point: a panel's rows are voices, not MIDI numbers.

	Without it a hit reads back as bare pitch 36 and nothing can say which row
	of the grid asked for it.
	"""

	p = _builder(drum_note_map={"kick": 36})
	p.hit("kick", [0.0])

	placed = p.placed()

	assert len(placed) == 1
	assert placed[0].pitch == 36
	assert placed[0].origin == "kick"


def test_a_hit_the_primary_device_cannot_sound_says_so () -> None:

	"""A ``primary_unmapped`` note holds a placeholder pitch and stays silent here.

	Drawn without the flag it would show as a hit that never sounds — which is
	exactly the lie the flag exists to prevent.
	"""

	p = _builder(
		drum_note_map = {"kick": 36},
		mirrors = [(1, 0, {"rimshot": 37})],
	)
	p.hit("rimshot", [0.0])

	placed = p.placed()

	assert len(placed) == 1
	assert placed[0].origin == "rimshot"
	assert placed[0].primary_unmapped is True


def test_an_ordinary_hit_is_not_flagged_unmapped () -> None:

	"""The flag means something only if it is False in the ordinary case."""

	p = _builder(drum_note_map={"kick": 36})
	p.hit("kick", [0.0])

	assert p.placed()[0].primary_unmapped is False


# ---------------------------------------------------------------------------
# Immutable, and hashable because of it
# ---------------------------------------------------------------------------

def test_a_record_cannot_be_edited () -> None:

	"""Read-only: a caller must not reach through the answer into the pattern."""

	p = _builder()
	p.note(60, beat=0.0)

	with pytest.raises(dataclasses.FrozenInstanceError):
		p.placed()[0].pitch = 61		# type: ignore[misc]


def test_editing_a_record_could_not_reach_the_pattern_anyway () -> None:

	"""It is a copy, so even the fields it shares do not alias the Note."""

	p = _builder()
	p.note(60, beat=0.0)

	before = p.placed()[0]
	p.note(64, beat=0.0)

	assert before.pitch == 60
	assert p._pattern.steps[0].notes[0].pitch == 60


def test_the_records_go_into_a_set () -> None:

	"""Frozen makes them hashable, which is what the intended diff needs."""

	p = _builder()
	p.note(60, beat=0.0)
	p.note(64, beat=1.0)

	assert len(set(p.placed())) == 2


# ---------------------------------------------------------------------------
# The difference — what this exists for
# ---------------------------------------------------------------------------

def test_the_difference_reports_exactly_what_a_generator_added () -> None:

	"""The whole point: which notes did that generator put there."""

	p = _builder(drum_note_map={"kick": 36, "hihat": 42})
	p.hit("kick", [0.0, 2.0])

	before = set(p.placed())
	p.euclidean("hihat", pulses=3)
	generated = set(p.placed()) - before

	assert len(generated) == 3
	assert {entry.origin for entry in generated} == {"hihat"}


def test_a_generated_note_landing_on_a_hand_placed_one_is_still_reported () -> None:

	"""The failure the ``index`` field exists to prevent.

	Nothing dedupes: ``Pattern.add_note`` appends, so a tapped kick on a pulse
	and a generated kick on the same pulse are two Notes with equal fields.
	Without an index they collapse into one set member, the difference comes
	back empty, and a panel draws no generated step while two Note Ons fire.
	"""

	p = _builder(drum_note_map={"kick": 36})
	p.hit("kick", [0.0])

	before = set(p.placed())
	p.hit("kick", [0.0])
	generated = set(p.placed()) - before

	assert len(generated) == 1
	assert generated.pop().position == 0


def test_a_record_still_matches_itself_after_more_notes_arrive () -> None:

	"""A record read early must not change meaning as the build continues.

	The index counts within an append-only collection precisely so that
	placing more notes cannot renumber the ones already read.
	"""

	p = _builder()
	p.note(60, beat=0.0)

	early = p.placed()[0]

	p.note(64, beat=0.0)
	p.note(67, beat=2.0)

	assert early in set(p.placed())


# ---------------------------------------------------------------------------
# Drones — a second collection that would otherwise report nothing
# ---------------------------------------------------------------------------

def test_a_drone_is_reported_with_no_duration () -> None:

	"""A drone sounds, so it draws — and it has no end until one is placed."""

	p = _builder()
	p.drone(48, beat=0.0, velocity=80)

	placed = p.placed()

	assert len(placed) == 1
	assert placed[0].pitch == 48
	assert placed[0].velocity == 80
	assert placed[0].duration is None


def test_a_named_drone_carries_its_name_too () -> None:

	"""``origin`` travels the raw-event path on the same contract."""

	p = _builder(drum_note_map={"bass_drone": 48})
	p.drone("bass_drone")

	assert p.placed()[0].origin == "bass_drone"


def test_ending_a_note_does_not_place_one () -> None:

	"""``drone_off()`` ends a note rather than placing one.

	Reporting it would draw a step at the release point that never sounds.
	"""

	p = _builder()
	p.drone(48)
	p.drone_off(48)

	placed = p.placed()

	assert len(placed) == 1
	assert placed[0].duration is None


def test_a_drone_off_alone_reports_nothing () -> None:

	"""Nothing was placed, so nothing is reported."""

	p = _builder()
	p.note_off(48, beat=0.0)

	assert p.placed() == []


def test_two_drones_on_one_pulse_stay_distinct () -> None:

	"""The index has to work on the raw-event path as well as the step path."""

	p = _builder()
	p.drone(48, beat=0.0)
	p.drone(48, beat=0.0)

	assert len(set(p.placed())) == 2


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

def test_the_answer_is_ordered_by_position () -> None:

	"""Fixed only so two reads agree — but they must agree."""

	p = _builder()
	p.note(67, beat=3.0)
	p.note(60, beat=0.0)
	p.note(64, beat=1.5)

	positions = [entry.position for entry in p.placed()]

	assert positions == sorted(positions)


def test_steps_come_before_drones_sharing_a_pulse () -> None:

	"""The two collections meet at a pulse; the sort is stable, so this is fixed."""

	p = _builder()
	p.drone(48, beat=0.0)
	p.note(60, beat=0.0, duration=0.25)

	placed = p.placed()

	assert [entry.duration is None for entry in placed] == [False, True]


# ---------------------------------------------------------------------------
# The whole cycle, and only this one
# ---------------------------------------------------------------------------

def test_only_this_build_is_reported () -> None:

	"""The pattern is emptied at the top of every rebuild, so the read is per cycle.

	A drone still sounding from an earlier cycle is not here — a consumer
	drawing from ``placed()`` alone sees the cycle, not the sustain.
	"""

	pattern = subsequence.pattern.Pattern(channel=0, length=4, device=0)

	first = subsequence.pattern_builder.PatternBuilder(pattern, cycle=0)
	first.drone(48)
	first.note(60, beat=0.0)

	assert len(first.placed()) == 2

	# What Composition._rebuild() does before calling the pattern function.
	pattern.steps = {}
	pattern.raw_note_events = []

	second = subsequence.pattern_builder.PatternBuilder(pattern, cycle=1)

	assert second.placed() == []


def test_placed_is_an_accessor_not_a_generator () -> None:

	"""It returns data, so it must never be curated into the catalogue.

	The mechanical test is the return annotation — the mistake #2096 caught was
	an accessor listed as a note-placing verb on the strength of its name.
	"""

	assert "placed" not in subsequence.catalogue.GENERATORS
