from __future__ import annotations

import dataclasses
import typing
import xml.etree.ElementTree

import subsequence.constants

if typing.TYPE_CHECKING:
	import subsequence.pattern


@dataclasses.dataclass
class Groove:

	"""
	A timing/velocity template applied to quantized grid positions.

	A groove is a repeating pattern of per-step timing offsets and optional
	velocity adjustments aligned to a rhythmic grid. Apply it as a post-build
	transform with ``p.groove(template)`` to give a pattern its characteristic
	feel — swing, shuffle, MPC-style pocket, or anything extracted from an
	Ableton ``.agr`` file.

	Parameters:
		offsets: Timing offset per grid slot, in beats. Repeats cyclically.
			Positive values delay the note; negative values push it earlier.
		grid: Grid size in beats (0.25 = 16th notes, 0.5 = 8th notes).
		velocities: Optional velocity scale per grid slot (1.0 = unchanged).
			Repeats cyclically alongside offsets.

	Example::

		# Ableton-style 57% swing on 16th notes
		groove = Groove.swing(percent=57)

		# Custom groove with timing and velocity
		groove = Groove(
			grid=0.25,
			offsets=[0.0, +0.02, 0.0, -0.01],
			velocities=[1.0, 0.7, 0.9, 0.6],
		)
	"""

	offsets: typing.List[float]
	grid: float = 0.25
	velocities: typing.Optional[typing.List[float]] = None

	def __post_init__ (self) -> None:
		if not self.offsets:
			raise ValueError("offsets must not be empty")
		if self.grid <= 0:
			raise ValueError("grid must be positive")
		if self.velocities is not None and not self.velocities:
			raise ValueError("velocities must not be empty (use None for no velocity adjustment)")

	@staticmethod
	def swing (percent: float = 57.0, grid: float = 0.25) -> "Groove":

		"""
		Create a swing groove from a percentage.

		50% is straight (no swing). 67% is approximately triplet swing.
		57% is a moderate shuffle — the Ableton default.

		Parameters:
			percent: Swing amount (50–75 is the useful range).
			grid: Grid size in beats (0.25 = 16ths, 0.5 = 8ths).
		"""

		if percent < 50.0 or percent > 99.0:
			raise ValueError("swing percent must be between 50 and 99")
		pair_duration = grid * 2
		offset = (percent / 100.0 - 0.5) * pair_duration
		return Groove(offsets=[0.0, offset], grid=grid)

	@staticmethod
	def from_agr (path: str) -> "Groove":

		"""
		Import an Ableton .agr groove file.

		Parses the XML, extracts note timing and velocity data, and
		calculates per-step offsets from the ideal grid positions.

		Parameters:
			path: Path to the .agr file.
		"""

		tree = xml.etree.ElementTree.parse(path)
		root = tree.getroot()

		# Find the MIDI clip
		clip = root.find(".//MidiClip")
		if clip is None:
			raise ValueError(f"No MidiClip found in {path}")

		# Get clip length
		current_end = clip.find("CurrentEnd")
		if current_end is None:
			raise ValueError(f"No CurrentEnd found in {path}")
		clip_length = float(current_end.get("Value", "4"))

		# Extract note events sorted by time
		events = clip.findall(".//MidiNoteEvent")
		if not events:
			raise ValueError(f"No MidiNoteEvent elements found in {path}")

		times: typing.List[float] = []
		velocities_raw: typing.List[float] = []
		for event in events:
			times.append(float(event.get("Time", "0")))
			velocities_raw.append(float(event.get("Velocity", "127")))

		times.sort()
		note_count = len(times)

		# Infer grid from clip length and note count
		grid = clip_length / note_count

		# Calculate offsets from ideal grid positions
		offsets: typing.List[float] = []
		for i, time in enumerate(times):
			ideal = i * grid
			offsets.append(time - ideal)

		# Calculate velocity scales (relative to max velocity in the file)
		max_vel = max(velocities_raw)
		has_velocity_variation = any(v != max_vel for v in velocities_raw)
		groove_velocities: typing.Optional[typing.List[float]] = None
		if has_velocity_variation and max_vel > 0:
			groove_velocities = [v / max_vel for v in velocities_raw]

		return Groove(offsets=offsets, grid=grid, velocities=groove_velocities)


def apply_groove (
	steps: typing.Dict[int, "subsequence.pattern.Step"],
	groove: Groove,
	pulses_per_quarter: int = subsequence.constants.MIDI_QUARTER_NOTE
) -> typing.Dict[int, "subsequence.pattern.Step"]:

	"""
	Apply a groove template to a step dictionary keyed by pulse positions.

	Notes close to a grid position are shifted by the groove's offset for
	that slot. Notes between grid positions are left untouched.
	"""

	grid_pulses = groove.grid * pulses_per_quarter
	if grid_pulses <= 0:
		return dict(steps)

	half_grid = grid_pulses / 2.0
	num_offsets = len(groove.offsets)
	num_velocities = len(groove.velocities) if groove.velocities else 0

	new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

	for old_pulse, step in steps.items():

		# Find nearest grid position
		grid_index = round(old_pulse / grid_pulses)
		ideal_pulse = grid_index * grid_pulses

		# Only affect notes close to a grid position
		if abs(old_pulse - ideal_pulse) > half_grid * 0.5:
			new_pulse = old_pulse
		else:
			slot = grid_index % num_offsets
			offset_pulses = groove.offsets[slot] * pulses_per_quarter
			new_pulse = int(round(ideal_pulse + offset_pulses))
			new_pulse = max(0, new_pulse)

		# Apply velocity scaling if present
		if groove.velocities and num_velocities > 0:
			vel_slot = grid_index % num_velocities
			vel_scale = groove.velocities[vel_slot]
			step = _scale_step_velocity(step, vel_scale)

		if new_pulse not in new_steps:
			new_steps[new_pulse] = subsequence.pattern.Step()

		new_steps[new_pulse].notes.extend(step.notes)

	return new_steps


def _scale_step_velocity (step: "subsequence.pattern.Step", scale: float) -> "subsequence.pattern.Step":

	"""
	Return a copy of the step with scaled velocities.
	"""

	import subsequence.pattern

	new_notes = []
	for note in step.notes:
		new_notes.append(dataclasses.replace(
			note,
			velocity=max(1, min(127, int(round(note.velocity * scale))))
		))
	return subsequence.pattern.Step(notes=new_notes)
