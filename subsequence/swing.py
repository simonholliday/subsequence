from __future__ import annotations

import typing

from subsequence.constants import MIDI_QUARTER_NOTE

if typing.TYPE_CHECKING:
	import subsequence.pattern


NoteType = typing.TypeVar("NoteType")


def apply_swing (
	steps: typing.Dict[int, subsequence.pattern.Step],
	swing_ratio: float = 2.0,
	pulses_per_quarter: int = MIDI_QUARTER_NOTE
) -> typing.Dict[int, subsequence.pattern.Step]:

	"""
	Apply swing timing to a step dictionary keyed by pulse positions.
	"""

	if swing_ratio <= 0:
		raise ValueError("Swing ratio must be positive")

	if pulses_per_quarter <= 0:
		raise ValueError("Pulses per quarter must be positive")

	t1 = (swing_ratio / (swing_ratio + 1.0)) * pulses_per_quarter
	t2 = pulses_per_quarter - t1

	new_steps: typing.Dict[int, subsequence.pattern.Step] = {}

	for old_pulse, note_list in steps.items():

		if hasattr(note_list, "notes"):
			container_type = type(note_list)
			notes = note_list.notes

		else:
			container_type = None
			notes = note_list  # type: ignore[assignment]

		quarter_index = old_pulse // pulses_per_quarter
		within_quarter = old_pulse % pulses_per_quarter
		straight_eighth_boundary = pulses_per_quarter // 2

		if within_quarter < straight_eighth_boundary:
			new_pulse = quarter_index * pulses_per_quarter + within_quarter

		else:
			offset_in_second_eighth = within_quarter - straight_eighth_boundary
			fraction_through_second = offset_in_second_eighth / float(straight_eighth_boundary)
			new_pulse = quarter_index * pulses_per_quarter + t1 + fraction_through_second * t2  # type: ignore[assignment]

		new_pulse = int(round(new_pulse))

		if new_pulse not in new_steps:
			new_steps[new_pulse] = container_type() if container_type else []  # type: ignore[assignment]

		if container_type:
			new_steps[new_pulse].notes.extend(notes)
		else:
			new_steps[new_pulse].extend(notes)  # type: ignore[attr-defined]

	return new_steps
