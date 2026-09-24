"""hit_steps() and sequence() take their steps as any sequence, a range among them (#3503).

Every example passes ``range(16)``, and ``steps`` was annotated ``List[...]``: the one real
error of 46 when mypy was run over ``examples/`` (#3041).  Widening it to ``Sequence`` with the
same position marker publishes an identical catalogue entry, which the last test holds.
"""

import collections.abc
import typing

import subsequence
import subsequence.pattern
import subsequence.pattern_builder


def test_the_steps_are_any_sequence () -> None:

	for name in ("hit_steps", "sequence"):
		hints = typing.get_type_hints(getattr(subsequence.pattern_builder.PatternBuilder, name), include_extras=True)
		assert typing.get_origin(hints["steps"]) is collections.abc.Sequence, f"{name}: {hints['steps']}"


def test_a_range_of_steps_places_what_its_list_places () -> None:

	"""A guard: a range worked at run time before as well; only its annotation refused it."""

	placed = []

	for steps in (range(0, 16, 4), [0, 4, 8, 12]):
		pattern = subsequence.pattern.Pattern(channel=0, length=4)
		builder = subsequence.pattern_builder.PatternBuilder(pattern=pattern, cycle=0, default_grid=16)
		builder.hit_steps(36, steps)
		builder.sequence(steps, pitches=60)
		placed.append(sorted((pulse, note.pitch) for pulse, step in pattern.steps.items() for note in step.notes))

	assert placed[0] == placed[1] and len(placed[0]) == 8


def test_the_published_steps_control_is_unchanged () -> None:

	"""A guard: the catalogue reads Sequence as it reads List, so Superconductor sees the same control."""

	for name in ("hit_steps", "sequence"):
		steps = next(p for p in subsequence.describe_generator(name)["parameters"] if p["name"] == "steps")
		assert steps == {"name": "steps", "label": "steps", "kind": "position", "unit": "steps", "multiple": True, "required": True}
