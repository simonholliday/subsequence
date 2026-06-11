"""
Placing Motif values onto patterns: late pitch resolution, the placement
homomorphism, control-gesture emission, span clamping, capture, and the
metric weight table.
"""

import random

import pytest

import subsequence
import subsequence.constants
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequence_utils


M = subsequence.Motif
Degree = subsequence.Degree
ChordTone = subsequence.ChordTone
Approach = subsequence.Approach

PPQ = subsequence.constants.MIDI_QUARTER_NOTE


def _builder (key: str = "A", scale: str = "minor", length: float = 4.0, seed: int = 1, **kwargs) -> subsequence.pattern_builder.PatternBuilder:

	"""A standalone builder over a fresh pattern (no engine required)."""

	pattern = subsequence.pattern.Pattern(channel=0, length=length)

	return subsequence.pattern_builder.PatternBuilder(
		pattern = pattern,
		cycle = 0,
		key = key,
		scale = scale,
		rng = random.Random(seed),
		**kwargs,
	)


def _placed (p: subsequence.pattern_builder.PatternBuilder) -> list:

	"""(beat, pitch) pairs for every placed note, in pulse order."""

	out = []

	for pulse in sorted(p._pattern.steps):
		for note in p._pattern.steps[pulse].notes:
			out.append((pulse / PPQ, note.pitch))

	return out


# ── degree resolution ───────────────────────────────────────────────────────

def test_degrees_resolve_against_key_and_scale () -> None:

	"""A minor, root=60: tonic anchors at A3 (57); degrees keep their contour."""

	p = _builder(key="A", scale="minor")
	p.motif(subsequence.motif([1, 5, 8], durations=0.5), root=60)

	assert _placed(p) == [(0.0, 57), (1.0, 64), (2.0, 69)]


def test_degrees_follow_the_key () -> None:

	"""The same value sounds in the new key — relative content, late resolution."""

	c_major = _builder(key="C", scale="major")
	c_major.motif(subsequence.motif([1, 3, 5], durations=0.5), root=60)

	assert [pitch for _, pitch in _placed(c_major)] == [60, 64, 67]

	d_minor = _builder(key="D", scale="minor")
	d_minor.motif(subsequence.motif([1, 3, 5], durations=0.5), root=60)

	assert [pitch for _, pitch in _placed(d_minor)] == [62, 65, 69]


def test_degree_octave_and_chroma () -> None:

	"""Degree(step, octave=, chroma=) shifts after scale lookup."""

	p = _builder(key="C", scale="major")
	p.motif(M.degrees([Degree(5, octave=1), Degree(5, chroma=1)], durations=0.5), root=60)

	assert [pitch for _, pitch in _placed(p)] == [79, 68]


def test_scale_defaults_to_ionian () -> None:

	"""No scale set means major — the documented default."""

	p = _builder(key="C", scale=None)
	p.motif(subsequence.motif([3], durations=0.5), root=60)

	assert [pitch for _, pitch in _placed(p)] == [64]


def test_degrees_without_key_raise () -> None:

	"""Degrees are relative; placing them with no key is a configuration error."""

	p = _builder(key=None, scale=None)

	with pytest.raises(ValueError, match="key"):
		p.motif(subsequence.motif([1]))


def test_unknown_scale_teaches () -> None:

	"""Unknown mode names raise the registry's teaching error."""

	p = _builder(key="C", scale="klingon")

	with pytest.raises(ValueError, match="register_scale"):
		p.motif(subsequence.motif([1]))


def test_midi_ints_pass_through_and_drums_use_the_funnel () -> None:

	"""Absolute notes place as-is; drum names resolve through drum_note_map."""

	p = _builder(drum_note_map={"kick": 36})
	p.motif(M.notes([72], durations=0.5) & M.hits("kick", beats=[1.0], length=4))

	assert _placed(p) == [(0.0, 72), (1.0, 36)]


def test_chord_tone_without_harmony_and_approach_raise_clearly () -> None:

	"""ChordTone needs the clock (a clear ValueError without one); Approach waits for stage 5."""

	p = _builder()

	with pytest.raises(ValueError, match="harmonic clock"):
		p.motif(M.hits("kick", beats=[0], length=1).pitched("root"))

	with pytest.raises(NotImplementedError, match="harmony window"):
		p.motif(M.from_events([subsequence.MotifEvent(beat=0.0, pitch=Approach(Degree(1)))], length=1))


class _StubHarmony:

	"""A HarmonyView stand-in: chords keyed by cycle beat ranges."""

	def __init__ (self, spans):
		self._spans = spans	# list of (start, end, chord)

	@property
	def chord (self):
		return self.chord_at(0.0)

	def chord_at (self, beat):
		for start, end, chord in self._spans:
			if start <= beat < end:
				return chord
		return None


def test_chord_tone_resolves_against_the_chord_under_the_event () -> None:

	"""ChordTone indices voice the chord sounding at the EVENT's beat, not the cycle start."""

	a_minor = subsequence.chords.parse_chord("Am")
	f_major = subsequence.chords.parse_chord("F")
	view = _StubHarmony([(0.0, 2.0, a_minor), (2.0, 4.0, f_major)])

	p = _builder(harmony=view)
	value = M.from_events([
		subsequence.MotifEvent(beat=0.0, pitch=ChordTone("root")),
		subsequence.MotifEvent(beat=1.0, pitch=ChordTone("third")),
		subsequence.MotifEvent(beat=2.0, pitch=ChordTone("root")),
	], length=4)

	p.motif(value, root=60)

	placed = _placed(p)
	assert placed == [(0.0, 57), (1.0, 60), (2.0, 65)]	# A3, C4 (Am), then F4 (F)


def test_chord_tone_octave_and_cycling () -> None:

	"""Indices past the chord's size cycle into higher octaves; octave= shifts whole octaves."""

	a_minor = subsequence.chords.parse_chord("Am")
	view = _StubHarmony([(0.0, 4.0, a_minor)])

	p = _builder(harmony=view)
	p.motif(M.from_events([
		subsequence.MotifEvent(beat=0.0, pitch=ChordTone(4)),
		subsequence.MotifEvent(beat=1.0, pitch=ChordTone("root", octave=1)),
	], length=4), root=60)

	assert _placed(p) == [(0.0, 69), (1.0, 69)]	# A4: the cycled 4th tone; A3 + 12


def test_chord_tone_outside_window_raises () -> None:

	"""An event beat the window does not cover fails with the window message."""

	view = _StubHarmony([(0.0, 1.0, subsequence.chords.parse_chord("Am"))])

	p = _builder(harmony=view)

	with pytest.raises(ValueError, match="window"):
		p.motif(M.from_events([subsequence.MotifEvent(beat=2.0, pitch=ChordTone(1))], length=4))


def test_skeleton_placement_raises () -> None:

	"""A rhythm() skeleton must be re-pitched before placing."""

	p = _builder()

	with pytest.raises(ValueError, match="pitched"):
		p.motif(M.notes([60]).rhythm())


# ── placement mechanics ─────────────────────────────────────────────────────

def test_placement_homomorphism () -> None:

	"""Placing a & b equals placing a then b — the builder layers."""

	a = M.notes([60], durations=0.5)
	b = M.notes([72], beats=[1.0], durations=0.5)

	merged = _builder()
	merged.motif(a & b)

	separate = _builder()
	separate.motif(a)
	separate.motif(b)

	assert _placed(merged) == _placed(separate)


def test_beat_offset_shifts_the_whole_motif () -> None:

	"""beat= is the motif's start within the pattern."""

	p = _builder()
	p.motif(M.notes([60, 62], durations=0.5), beat=1.0)

	assert [beat for beat, _ in _placed(p)] == [1.0, 2.0]


def test_span_clamps_late_events () -> None:

	"""Events at or beyond span are dropped — the arpeggio convention."""

	p = _builder()
	p.motif(M.notes([60, 62, 64, 65], durations=0.5), span=2.0)

	assert [pitch for _, pitch in _placed(p)] == [60, 62]


def test_velocity_override () -> None:

	"""velocity= replaces every event's velocity at placement."""

	p = _builder()
	p.motif(M.notes([60], velocities=80, durations=0.5), velocity=127)

	assert p._pattern.steps[0].notes[0].velocity == 127


def test_probability_rolls_on_the_pattern_stream () -> None:

	"""probability=0 never sounds; probability=1 always does; rolls use p.rng."""

	p = _builder()
	p.motif(M.notes([60], durations=0.5, probabilities=0.0))
	p.motif(M.notes([72], beats=[1.0], durations=0.5, probabilities=1.0))

	assert [pitch for _, pitch in _placed(p)] == [72]


def test_motif_returns_self_for_chaining () -> None:

	"""Placement verbs chain like every other builder verb."""

	p = _builder()

	assert p.motif(M.notes([60], durations=0.5)) is p


def test_duck_typing_rejects_non_values () -> None:

	"""Anything without .events/.length is not placeable."""

	p = _builder()

	with pytest.raises(TypeError, match="events"):
		p.motif([60, 62])


# ── control gestures ────────────────────────────────────────────────────────

def test_control_gestures_emit_through_the_cc_machinery () -> None:

	"""A packaged sweep lands as ordinary cc_events at placement."""

	p = _builder(cc_name_map={"cutoff": 74})
	acid = M.notes([60], durations=0.5) & M.cc_ramp("cutoff", 20, 110, beat_end=4)
	p.motif(acid)

	cc = [e for e in p._pattern.cc_events if e.message_type == "control_change"]

	assert cc, "the sweep emitted no CC events"
	assert all(e.control == 74 for e in cc)
	assert cc[0].value == 20 and cc[-1].value == 110


def test_discrete_control_write () -> None:

	"""A discrete CC event lands at its pulse with its value."""

	p = _builder()
	p.motif(M.cc(74, [64], beats=[2.0]), beat=1.0)

	cc = p._pattern.cc_events

	assert len(cc) == 1
	assert cc[0].pulse == int(3.0 * PPQ)
	assert cc[0].value == 64


def test_pitch_bend_gesture () -> None:

	"""A bend dive emits pitchwheel events ending at the target."""

	p = _builder()
	p.motif(M.pitch_bend_ramp(0.0, -0.5, beat_start=3.5, beat_end=4.0))

	bends = [e for e in p._pattern.cc_events if e.message_type == "pitchwheel"]

	assert bends
	assert bends[-1].value == int(round(-0.5 * 8192))


def test_nrpn_gesture_carries_flags () -> None:

	"""NRPN writes emit the select/data burst (multiple CC messages)."""

	p = _builder()
	p.motif(M.nrpn(9, [700], beats=[0.0], fine=True))

	controls = [e.control for e in p._pattern.cc_events]

	assert 99 in controls and 98 in controls and 6 in controls and 38 in controls


def test_control_probability_rolls () -> None:

	"""A gesture with probability 0 never emits."""

	p = _builder()
	p.motif(M.cc(74, [64], beats=[0.0], probabilities=0.0))

	assert p._pattern.cc_events == []


def test_resolution_override_thins_ramp_traffic () -> None:

	"""resolution= at the placement call reduces message density."""

	dense = _builder()
	dense.motif(M.cc_ramp(74, 0, 127, beat_end=4))

	sparse = _builder()
	sparse.motif(M.cc_ramp(74, 0, 127, beat_end=4), resolution=8)

	assert len(sparse._pattern.cc_events) < len(dense._pattern.cc_events)


def test_fit_is_accepted () -> None:

	"""fit= parses today; the dial activates with a harmonic context later."""

	p = _builder()
	p.motif(subsequence.motif([1], durations=0.5), fit=0.8)

	assert len(_placed(p)) == 1


# ── capture ─────────────────────────────────────────────────────────────────

def test_capture_round_trip () -> None:

	"""Placed notes read back as an absolute-MIDI motif that replaces identically."""

	source = _builder()
	source.motif(M.notes([60, 64, 67], beats=[0.0, 1.5, 3.0], durations=0.5))

	captured = source.capture(beat=0.0, span=4.0)

	assert captured.length == 4.0
	assert [e.pitch for e in captured.events] == [60, 64, 67]
	assert [e.beat for e in captured.events] == [0.0, 1.5, 3.0]

	replay = _builder()
	replay.motif(captured)

	assert _placed(replay) == _placed(source)


def test_capture_is_absolute_even_for_degrees () -> None:

	"""Relative specs do not survive resolution — capture is lossy by design."""

	p = _builder(key="A", scale="minor")
	p.motif(subsequence.motif([1], durations=0.5), root=60)

	captured = p.capture(beat=0.0, span=4.0)

	assert captured.events[0].pitch == 57  # an int, not a Degree


def test_capture_windows () -> None:

	"""Only notes inside the window are captured, re-anchored to zero."""

	p = _builder()
	p.motif(M.notes([60, 62, 64, 65], durations=0.5))

	window = p.capture(beat=1.0, span=2.0)

	assert [e.pitch for e in window.events] == [62, 64]
	assert [e.beat for e in window.events] == [0.0, 1.0]


# ── threading + metric weights ──────────────────────────────────────────────

def test_builder_exposes_scale_and_time_signature () -> None:

	"""p.scale and p.time_signature are injected context."""

	p = _builder(key="A", scale="minor", time_signature=(3, 4))

	assert p.scale == "minor"
	assert p.time_signature == (3, 4)


def test_metric_weights_four_four () -> None:

	"""The 4/4 sixteenth table: downbeat, half-bar, beats, eighths, sixteenths."""

	w = subsequence.sequence_utils.build_metric_weights((4, 4), grid=16)

	assert w == [
		1.0, 0.125, 0.25, 0.125,
		0.5, 0.125, 0.25, 0.125,
		0.75, 0.125, 0.25, 0.125,
		0.5, 0.125, 0.25, 0.125,
	]


def test_metric_weights_three_four_has_no_half_bar () -> None:

	"""Odd meters skip the half-bar tier."""

	w = subsequence.sequence_utils.build_metric_weights((3, 4), grid=12)

	assert w[0] == 1.0
	assert w[4] == w[8] == 0.5
	assert 0.75 not in w
