"""The cheat sheet must read the same whoever generates it.

`api-cheatsheet.md` is generated from signatures and gated in CI, so it is only
a useful gate if two people running the generator get the same file.  They did
not: `str(signature)` follows the running interpreter, so 3.14 wrote
`int | None` where 3.10 wrote `Optional[int]`, and the gate failed on its first
CI run over ten rows nobody had touched.

This project targets 3.10 and writes `typing.Optional[X]` rather than PEP 604,
so that is the spelling — pinned here rather than left to whichever Python is
to hand.
"""

import importlib.util
import pathlib
import types
import typing

import pytest


def _generator () -> types.ModuleType:

	"""Import `scripts/generate_cheatsheet.py`, which is a script rather than a module."""

	path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "generate_cheatsheet.py"
	spec = importlib.util.spec_from_file_location("generate_cheatsheet", path)

	assert spec is not None and spec.loader is not None

	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	return module


GENERATOR = _generator()


@pytest.mark.parametrize("annotation,expected", [
	(int, "int"),
	(typing.Optional[int], "Optional[int]"),
	(typing.Optional[typing.Any], "Optional[Any]"),
	(typing.Union[float, typing.List[float]], "Union[float, List[float]]"),
	(typing.Union[int, str, None], "Optional[Union[int, str]]"),
	(typing.List[typing.Optional[int]], "List[Optional[int]]"),
	(typing.List[int], "List[int]"),
	(typing.Dict[str, int], "Dict[str, int]"),
])
def test_an_annotation_is_spelled_the_project_way (annotation: typing.Any, expected: str) -> None:

	"""The house spelling, not the interpreter's.

	`List[Optional[int]]` is here because a union nested inside a generic is
	the case a top-level fix would miss, and it would fail on CI rather than
	on the machine that wrote it.
	"""

	assert GENERATOR.format_annotation(annotation) == expected


@pytest.mark.parametrize("annotation", [
	typing.Optional[int],
	typing.Union[float, typing.List[float]],
	typing.Union[int, str, None],
	typing.List[typing.Optional[int]],
	typing.Optional[typing.Dict[str, typing.Union[int, float]]],
])
def test_a_union_never_leaks_how_the_interpreter_spells_it (annotation: typing.Any) -> None:

	"""Neither a pipe nor a bare NoneType, whichever Python is running.

	This is the property rather than the spelling, and it is the one that
	broke: rendering a union by reading its repr looked right on 3.14 and
	produced `Union[int, str, NoneType]` on 3.10, because only one of those
	reprs contains a pipe to notice. A union is built here now rather than
	read, so there is no version-dependent path left to test.
	"""

	rendered = GENERATOR.format_annotation(annotation)

	assert "|" not in rendered
	assert "NoneType" not in rendered


def test_the_generated_sheet_carries_no_pipe_unions () -> None:

	"""End to end: nothing in the sheet is spelled the interpreter's way.

	A pipe reaches the file escaped, as ``\\|``, because the sheet is a Markdown
	table — so its absence is the whole check, and it is what CI was really
	complaining about.
	"""

	assert "\\|" not in GENERATOR.generate_markdown()


def test_the_sheet_on_disk_is_what_the_generator_produces () -> None:

	"""The same thing CI checks, so it fails here first.

	It was CI-only, which is why a version-dependent generator got as far as
	`main` — the gate ran nowhere the drift was actually happening.
	"""

	path = pathlib.Path(__file__).resolve().parent.parent / "api-cheatsheet.md"

	assert path.read_text() == GENERATOR.generate_markdown(), (
		"api-cheatsheet.md is out of date — run: python scripts/generate_cheatsheet.py"
	)
