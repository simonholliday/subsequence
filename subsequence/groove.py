"""
Groove templates - repeating timing and velocity feels applied to quantised patterns.

Exports the public Groove class: build one by hand, from a swing percentage,
or from an Ableton ``.agr`` file, then apply it with ``p.groove(template)``.
"""

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
	A timing/velocity template applied to quantised grid positions.

	A groove is a repeating pattern of per-step timing offsets and optional
	velocity adjustments aligned to a rhythmic grid. Apply it as a post-build
	transform with ``p.groove(template)`` to give a pattern its characteristic
	feel - swing, shuffle, MPC-style pocket, or anything extracted from an
	Ableton ``.agr`` file.

	The offsets repeat from the start of the piece, not from the start of each
	pattern, so the same groove given to parts of different lengths keeps them
	in one feel.

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
		57% is a moderate shuffle - the Ableton default.

		Applied, a note moves by whole pulses (24 to a beat), so percentages
		that round to the same pulse sound the same: on sixteenths 55–62 all
		sound as about 58%.  ``PatternBuilder.swing`` lists the steps for
		sixteenths and eighths.

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
	def from_agr (path: str, grid: typing.Optional[float] = None) -> "Groove":

		"""
		Import timing and velocity data from an Ableton .agr groove file.

		An ``.agr`` file is an XML document containing a MIDI clip whose
		note positions encode the groove's rhythmic feel. This method reads
		those note start times and velocities and converts them into the
		``Groove`` dataclass format (per-step offsets and velocity scales).

		Without ``grid=``, the grid is inferred as ``clip length / note
		count`` - which assumes the clip plays **exactly one note per grid
		cell** (the standard shape for a groove clip). A clip with rests or
		chords breaks that assumption: pass ``grid=`` explicitly (e.g.
		``grid=0.25`` for a 16th-note groove) and empty cells keep a neutral
		offset. A clip whose notes cannot be assigned one-per-cell raises
		rather than importing a wrong feel.

		**What is extracted:**

		- ``Time`` attribute of each ``MidiNoteEvent`` → timing offsets
		  relative to ideal grid positions.
		- ``Velocity`` attribute of each ``MidiNoteEvent`` → velocity
		  scaling (normalised to the highest velocity in the file).
		- ``TimingAmount`` from the Groove element → pre-scales the timing
		  offsets (100 = full, 70 = 70% of the groove's timing).
		- ``VelocityAmount`` from the Groove element → pre-scales velocity
		  deviation (100 = full groove velocity, 0 = no velocity changes).

		The resulting ``Groove`` reflects the file author's intended
		strength. Use ``strength=`` when applying to further adjust.

		**What is NOT imported:**

		``RandomAmount`` (use ``p.randomize()`` separately for random
		jitter) and ``QuantizationAmount`` (not applicable - Subsequence
		notes are already grid-quantised by construction).

		Other ``MidiNoteEvent`` fields (``Duration``, ``VelocityDeviation``,
		``OffVelocity``, ``Probability``) are also ignored.

		Parameters:
			path: Path to the .agr file.
			grid: Grid size in beats (0.25 = 16th notes). ``None`` (default)
				infers it from the clip, assuming one note per cell.
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

		# Read Groove Pool blend parameters
		groove_elem = root.find(".//Groove")
		timing_amount = 100.0
		velocity_amount = 100.0
		if groove_elem is not None:
			timing_el = groove_elem.find("TimingAmount")
			if timing_el is not None:
				timing_amount = float(timing_el.get("Value", "100"))
			velocity_el = groove_elem.find("VelocityAmount")
			if velocity_el is not None:
				velocity_amount = float(velocity_el.get("Value", "100"))

		timing_scale = timing_amount / 100.0
		velocity_scale = velocity_amount / 100.0

		# Extract note events sorted by time
		events = clip.findall(".//MidiNoteEvent")
		if not events:
			raise ValueError(f"No MidiNoteEvent elements found in {path}")

		times: typing.List[float] = []
		velocities_raw: typing.List[float] = []
		for event in events:
			times.append(float(event.get("Time", "0")))
			velocities_raw.append(float(event.get("Velocity", "127")))

		# Sort as PAIRS - sorting times alone desynced each offset from its
		# note's velocity whenever the XML listed events out of time order.
		paired = sorted(zip(times, velocities_raw))
		times = [t for t, _ in paired]
		velocities_raw = [v for _, v in paired]

		note_count = len(times)

		# Infer grid from clip length and note count — valid only for the
		# one-note-per-cell clip shape (see docstring); grid= overrides.
		if grid is None:
			grid = clip_length / note_count

		if grid <= 0:
			raise ValueError(f"grid must be positive - got {grid}")

		slot_count = max(1, int(round(clip_length / grid)))

		slot_offsets = [0.0] * slot_count
		slot_velocities: typing.List[typing.Optional[float]] = [None] * slot_count

		if note_count == slot_count:

			# One note per cell - the standard groove clip, and what an inferred
			# grid assumes - so the i-th note belongs to cell i, however far its
			# feel moves it.  Binding each note to its NEAREST grid line instead
			# put a note swung half a cell or more late into the next cell: 75%
			# sixteenth swing, inside the useful range, could not be imported, and
			# the error suggested the grid already in use (#3404).
			for index, (time, velocity) in enumerate(zip(times, velocities_raw)):

				if index and abs(time - times[index - 1]) < 1e-9:
					raise ValueError(
						f"{path}: two notes start together at beat {time:g} (a chord) - a "
						"groove clip plays one note per grid cell, and no grid= can separate them"
					)

				if abs(time - index * grid) >= grid:
					raise ValueError(
						f"{path}: note {index + 1} at beat {time:g} is a whole cell or more from "
						f"its own (grid={grid:g}) - pass grid= matching the clip's note spacing"
					)

				slot_offsets[index] = (time - index * grid) * timing_scale
				slot_velocities[index] = velocity

		else:

			# Rests (fewer notes than cells, under an explicit grid): bind each
			# note to its nearest grid line, and empty cells keep a neutral
			# offset.  Refuse an ambiguous clip rather than import a wrong feel.
			for time, velocity in zip(times, velocities_raw):

				slot = int(round(time / grid))

				if not 0 <= slot < slot_count:
					raise ValueError(
						f"{path}: note at beat {time:g} falls outside the {slot_count}-cell "
						f"grid (grid={grid:g}, clip length {clip_length:g}) - pass grid= "
						"matching the clip's note spacing"
					)

				if slot_velocities[slot] is not None:
					raise ValueError(
						f"{path}: two notes fall nearest grid cell {slot} (grid={grid:g}): a "
						"chord, a grid coarser than the clip's notes, or notes moved half a "
						"cell or more off their lines, which a clip with rests cannot place"
					)

				slot_offsets[slot] = (time - slot * grid) * timing_scale
				slot_velocities[slot] = velocity

		# Calculate velocity scales (relative to max velocity in the file),
		# blended toward 1.0 by VelocityAmount; empty cells stay neutral (1.0).
		filled = [v for v in slot_velocities if v is not None]
		max_vel = max(filled)
		has_velocity_variation = any(v != max_vel for v in filled)
		groove_velocities: typing.Optional[typing.List[float]] = None
		if has_velocity_variation and max_vel > 0:
			raw_scales = [(v / max_vel) if v is not None else 1.0 for v in slot_velocities]
			# velocity_scale=1.0 → full groove velocity; 0.0 → all 1.0 (no change)
			groove_velocities = [1.0 + (s - 1.0) * velocity_scale for s in raw_scales]
			# If blending has removed all variation, set to None
			if all(abs(v - 1.0) < 1e-9 for v in groove_velocities):
				groove_velocities = None

		return Groove(offsets=slot_offsets, grid=grid, velocities=groove_velocities)


def apply_groove (
	steps: typing.Dict[int, "subsequence.pattern.Step"],
	groove: Groove,
	pulses_per_quarter: int = subsequence.constants.MIDI_QUARTER_NOTE,
	strength: float = 1.0,
	origin_pulse: int = 0,
) -> typing.Dict[int, "subsequence.pattern.Step"]:

	"""
	Apply a groove template to a step dictionary keyed by pulse positions.

	Notes close to a grid position are shifted by the groove's offset for
	that slot, to the nearest whole pulse. Notes between grid positions are
	left untouched.

	Which slot a note falls in is counted from ``origin_pulse``, the point on
	the song's timeline where these steps begin. So a groove keeps its phase
	against the music rather than restarting with every pattern, and parts of
	any length swing together.

	Parameters:
		steps: Step dictionary (pulse → Step).
		groove: The groove template to apply.
		pulses_per_quarter: Internal MIDI clock resolution (default 24).
		strength: How much of the groove to apply (0.0–1.0).
			0.0 leaves all timing and velocity unchanged; 1.0 applies
			the full groove. Intermediate values blend between the two,
			equivalent to Ableton’s TimingAmount / VelocityAmount dials.
		origin_pulse: Where these steps start on the song's timeline
			(default 0). ``PatternBuilder.groove()`` passes the cycle's
			start, so a pattern that is not a whole number of groove
			cycles long still swings with everything else.
	"""

	if not 0.0 <= strength <= 1.0:
		raise ValueError("strength must be between 0.0 and 1.0")

	grid_pulses = groove.grid * pulses_per_quarter
	if grid_pulses <= 0:
		return dict(steps)

	num_velocities = len(groove.velocities) if groove.velocities else 0

	new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

	for old_pulse, step in steps.items():

		new_pulse, grid_index = _grooved_pulse(old_pulse, groove, pulses_per_quarter, strength, origin_pulse)

		# Velocity scaling applies only to grooved (on-grid) notes, for the
		# same reason as the timing: an off-grid note shouldn't pick up a
		# slot's accent.
		if grid_index is not None and groove.velocities and num_velocities > 0:
			vel_slot = grid_index % num_velocities
			# Blend between 1.0 (no effect) and the groove's scale (full effect)
			vel_scale = 1.0 + (groove.velocities[vel_slot] - 1.0) * strength
			step = _scale_step_velocity(step, vel_scale)

		if new_pulse not in new_steps:
			new_steps[new_pulse] = subsequence.pattern.Step()

		# Each moved note records how far, so thin(), scale_velocities() and
		# ratchet(steps=) still count it as the step it was placed on (#3447).
		# Copies, as the velocity scaling makes, so the caller's notes are
		# left as they were.
		moved = new_pulse - old_pulse

		if moved:
			new_steps[new_pulse].notes.extend(dataclasses.replace(note, nudge = note.nudge + moved) for note in step.notes)
		else:
			new_steps[new_pulse].notes.extend(step.notes)

	return new_steps


def _grooved_pulse (
	old_pulse: int,
	groove: Groove,
	pulses_per_quarter: int,
	strength: float,
	origin_pulse: int,
) -> typing.Tuple[int, typing.Optional[int]]:

	"""Where ``apply_groove()`` moves a note at *old_pulse*, and the grid line it counted it on.

	The grid line is None for a note it leaves alone, between grid lines.
	The glides call this too, to foresee where the next cycle's first note
	will play (#2927), so the two cannot disagree.
	"""

	grid_pulses = groove.grid * pulses_per_quarter

	if grid_pulses <= 0:
		return old_pulse, None

	# Find the nearest grid position, counted on the song's timeline so a
	# groove keeps its phase against the music however long this pattern
	# is (#2788).  ideal_pulse comes back to the pattern's own axis.
	grid_index = round((old_pulse + origin_pulse) / grid_pulses)
	ideal_pulse = grid_index * grid_pulses - origin_pulse

	# Only groove notes that sit close to a grid position; notes deliberately
	# placed between grid lines (flams, pushes) keep both their timing AND
	# velocity.  The window is ±25% of a cell (half a cell, halved again):
	# narrow on purpose, so off-grid expression survives a quantised groove.
	if abs(old_pulse - ideal_pulse) > grid_pulses / 2.0 * 0.5:
		return old_pulse, None

	slot = grid_index % len(groove.offsets)

	# Blend from the note's OWN pulse toward the groove target so
	# strength=0.0 truly leaves timing untouched.  (Blending from
	# ideal_pulse quantised away in-window micro-timing - e.g. from
	# randomize() - at every strength, including 0.)
	groove_target = ideal_pulse + groove.offsets[slot] * pulses_per_quarter
	new_pulse = int(round(old_pulse + (groove_target - old_pulse) * strength))

	return max(0, new_pulse), grid_index


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
