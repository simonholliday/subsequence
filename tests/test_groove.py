import os

import subsequence.groove
import subsequence.pattern


def _make_steps (*pulses: int, velocity: int = 100) -> dict:

	"""
	Build a steps dict with one note per pulse position.
	"""

	steps = {}
	for p in pulses:
		steps[p] = subsequence.pattern.Step(notes=[
			subsequence.pattern.Note(pitch=60, velocity=velocity, duration=6, channel=0)
		])
	return steps


# ── Groove.swing() factory ───────────────────────────────────────────

def test_swing_50_percent_is_straight () -> None:

	"""50% swing produces zero offsets (straight time)."""

	g = subsequence.groove.Groove.swing(percent=50.0)
	assert g.offsets == [0.0, 0.0]
	assert g.grid == 0.25


def test_swing_57_percent () -> None:

	"""57% swing produces the expected offset for 16th notes."""

	g = subsequence.groove.Groove.swing(percent=57.0)
	assert g.offsets[0] == 0.0
	assert abs(g.offsets[1] - 0.035) < 1e-9


def test_swing_67_percent_triplet () -> None:

	"""67% gives approximate triplet swing."""

	g = subsequence.groove.Groove.swing(percent=67.0)
	assert g.offsets[0] == 0.0
	# 67% of 0.5 = 0.335, offset = 0.335 - 0.25 = 0.085
	assert abs(g.offsets[1] - 0.085) < 1e-9


def test_swing_eighth_note_grid () -> None:

	"""Swing can be applied to 8th note grid."""

	g = subsequence.groove.Groove.swing(percent=57.0, grid=0.5)
	assert g.grid == 0.5
	# pair_duration = 1.0, offset = (0.57 - 0.5) * 1.0 = 0.07
	assert abs(g.offsets[1] - 0.07) < 1e-9


def test_swing_invalid_percent () -> None:

	"""Percent outside 50-99 range raises ValueError."""

	try:
		subsequence.groove.Groove.swing(percent=40.0)
		assert False, "should have raised"
	except ValueError:
		pass

	try:
		subsequence.groove.Groove.swing(percent=100.0)
		assert False, "should have raised"
	except ValueError:
		pass


# ── apply_groove() ───────────────────────────────────────────────────

def test_apply_groove_shifts_offbeat_16ths () -> None:

	"""Off-beat 16th notes are shifted by the groove offset."""

	# 16th notes at pulses 0, 6, 12, 18 (one beat of 16ths at 24 PPQN)
	steps = _make_steps(0, 6, 12, 18)
	g = subsequence.groove.Groove.swing(percent=57.0)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	# On-beat 16ths (pulse 0, 12) should stay put
	assert 0 in result
	assert 12 in result

	# Off-beat 16ths: ideal=6, offset=0.035*24=0.84 → round(6+0.84)=7
	assert 7 in result
	# ideal=18, offset=0.035*24=0.84 → round(18+0.84)=19
	assert 19 in result


def test_apply_groove_straight_no_change () -> None:

	"""50% swing (straight) produces no timing changes."""

	steps = _make_steps(0, 6, 12, 18)
	g = subsequence.groove.Groove.swing(percent=50.0)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	assert set(result.keys()) == {0, 6, 12, 18}


def test_apply_groove_empty_pattern () -> None:

	"""Empty pattern returns empty result."""

	g = subsequence.groove.Groove.swing(percent=57.0)
	result = subsequence.groove.apply_groove({}, g, pulses_per_quarter=24)
	assert result == {}


def test_apply_groove_notes_between_grid_untouched () -> None:

	"""Notes not close to a grid position are left alone."""

	# Place a note at pulse 3 — midway between grid positions 0 and 6
	steps = _make_steps(3)
	g = subsequence.groove.Groove(offsets=[0.0, 0.1], grid=0.25)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	# Pulse 3 is exactly half a grid cell from each neighbor — should be untouched
	assert 3 in result


def test_apply_groove_velocity_scaling () -> None:

	"""Velocity scaling adjusts note velocities per grid slot."""

	steps = _make_steps(0, 6)
	g = subsequence.groove.Groove(
		offsets=[0.0, 0.0],
		grid=0.25,
		velocities=[1.0, 0.5]
	)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	# Slot 0: velocity unchanged (100 * 1.0 = 100)
	assert result[0].notes[0].velocity == 100
	# Slot 1: velocity halved (100 * 0.5 = 50)
	assert result[6].notes[0].velocity == 50


def test_apply_groove_velocity_clamp () -> None:

	"""Velocity is clamped to 1-127."""

	steps = _make_steps(0, velocity=120)
	g = subsequence.groove.Groove(
		offsets=[0.0],
		grid=0.25,
		velocities=[2.0]  # would produce 240
	)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)
	assert result[0].notes[0].velocity == 127


def test_apply_groove_cyclic_repetition () -> None:

	"""Short offset list repeats cyclically across more grid positions."""

	# 2-slot pattern applied to 4 beats of 16th notes (16 positions)
	pulses = [i * 6 for i in range(16)]  # 0, 6, 12, 18, 24, ...
	steps = _make_steps(*pulses)
	g = subsequence.groove.Groove(offsets=[0.0, 0.035], grid=0.25)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	# Every even slot (0, 2, 4, ...) stays; every odd slot shifts
	for i in range(0, 16, 2):
		assert i * 6 in result, f"Even slot {i} at pulse {i * 6} should be unchanged"


def test_apply_groove_no_negative_pulses () -> None:

	"""Notes at pulse 0 with a negative offset are clamped to 0."""

	steps = _make_steps(0)
	g = subsequence.groove.Groove(offsets=[-0.1], grid=0.25)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)
	assert 0 in result


def test_apply_groove_preserves_note_data () -> None:

	"""Notes keep their pitch, duration, and channel through the transform."""

	steps = {6: subsequence.pattern.Step(notes=[
		subsequence.pattern.Note(pitch=48, velocity=90, duration=12, channel=5)
	])}
	g = subsequence.groove.Groove.swing(percent=57.0)

	result = subsequence.groove.apply_groove(steps, g, pulses_per_quarter=24)

	# Find the moved note (should be at pulse 7)
	assert 7 in result
	note = result[7].notes[0]
	assert note.pitch == 48
	assert note.duration == 12
	assert note.channel == 5


# ── Groove.from_agr() ───────────────────────────────────────────────

def test_from_agr_parses_swing_16ths_57 () -> None:

	"""The sample .agr file produces the expected groove."""

	agr_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Swing 16ths 57.agr")
	if not os.path.exists(agr_path):
		return  # skip if file not present

	g = subsequence.groove.Groove.from_agr(agr_path)

	# 16 notes in 4 beats → 16th note grid
	assert abs(g.grid - 0.25) < 1e-9

	# 16 offsets
	assert len(g.offsets) == 16

	# Even slots should be ~0, odd slots should be ~0.035
	for i in range(0, 16, 2):
		assert abs(g.offsets[i]) < 0.001, f"Even slot {i} offset should be ~0"
	for i in range(1, 16, 2):
		assert abs(g.offsets[i] - 0.035) < 0.001, f"Odd slot {i} offset should be ~0.035"

	# All velocities are 127 → no velocity variation → None
	assert g.velocities is None


def test_from_agr_matches_swing_factory () -> None:

	"""The .agr import and Groove.swing(57) produce equivalent offsets."""

	agr_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Swing 16ths 57.agr")
	if not os.path.exists(agr_path):
		return

	agr_groove = subsequence.groove.Groove.from_agr(agr_path)
	factory_groove = subsequence.groove.Groove.swing(percent=57.0)

	# The factory produces a 2-slot repeating pattern
	# The .agr produces a 16-slot pattern that repeats the same 2-slot pattern
	for i in range(16):
		slot = i % len(factory_groove.offsets)
		assert abs(agr_groove.offsets[i] - factory_groove.offsets[slot]) < 0.001


# ── Validation ───────────────────────────────────────────────────────

def test_groove_empty_offsets_raises () -> None:

	"""Empty offsets list raises ValueError."""

	try:
		subsequence.groove.Groove(offsets=[])
		assert False, "should have raised"
	except ValueError:
		pass


def test_groove_zero_grid_raises () -> None:

	"""Zero grid raises ValueError."""

	try:
		subsequence.groove.Groove(offsets=[0.0], grid=0.0)
		assert False, "should have raised"
	except ValueError:
		pass


def test_groove_empty_velocities_raises () -> None:

	"""Empty velocities list raises ValueError (use None instead)."""

	try:
		subsequence.groove.Groove(offsets=[0.0], velocities=[])
		assert False, "should have raised"
	except ValueError:
		pass
