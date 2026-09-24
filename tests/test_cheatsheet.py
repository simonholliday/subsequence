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
import re
import types
import typing

import pytest

import subsequence
import subsequence.sequence_utils


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

	"""End to end: no signature in the sheet is spelled the interpreter's way.

	A pipe reaches the file escaped, as ``\\|``, because the sheet is a Markdown
	table.  Only the signature column is checked: a description may name
	``&``, ``|`` and ``~`` in prose, as ``Sieve``'s does, and that is not a
	union.
	"""

	rows = [line for line in GENERATOR.generate_markdown().splitlines() if line.startswith("| `")]

	assert rows, "the sheet has no signature rows to check"

	for line in rows:
		signature = re.split(r"(?<!\\)\|", line)[1]
		assert "\\|" not in signature, line


def test_the_sheet_on_disk_is_what_the_generator_produces () -> None:

	"""The same thing CI checks, so it fails here first.

	It was CI-only, which is why a version-dependent generator got as far as
	`main` — the gate ran nowhere the drift was actually happening.
	"""

	path = pathlib.Path(__file__).resolve().parent.parent / "api-cheatsheet.md"

	assert path.read_text() == GENERATOR.generate_markdown(), (
		"api-cheatsheet.md is out of date — run: python scripts/generate_cheatsheet.py"
	)


def _documented (markdown: str) -> typing.Tuple[typing.Set[str], typing.Set[str], typing.Set[str]]:

	"""The names the sheet gives a section of their own, a Global functions row, and a Sequence utilities row."""

	sections: typing.Set[str] = set()
	functions: typing.Set[str] = set()
	utilities: typing.Set[str] = set()
	heading = ""

	for line in markdown.splitlines():

		if line.startswith("## "):
			heading = line
			named = re.fullmatch(r"## `(\w+)`", line)
			if named:
				sections.add(named.group(1))
			continue

		row = re.match(r"\| `(\w+)\(", line)

		if row and heading == "## Global functions":
			functions.add(row.group(1))
		elif row and heading.startswith("## Sequence utilities"):
			utilities.add(row.group(1))

	return sections, functions, utilities


def test_every_export_has_its_own_section_or_row () -> None:

	"""A class or module in ``__all__`` gets a section, and a function a row — the exports table alone is not enough.

	Ten exports appeared only in that table while the generator kept its own
	lists, and ``PatternBuilder`` had a section without being exported at all
	(#2593).
	"""

	sections, functions, _ = _documented(GENERATOR.generate_markdown())

	for name in subsequence.__all__:

		member = getattr(subsequence, name)

		if isinstance(member, (type, types.ModuleType)):
			assert name in sections, f"exported {name} has no section of its own"
		else:
			assert name in functions, f"exported {name} has no row under Global functions"


def test_the_sheet_documents_nothing_outside_the_declared_surface () -> None:

	"""Sections and function rows name only exports; the kernel rows are exactly ``sequence_utils.__all__``."""

	sections, functions, utilities = _documented(GENERATOR.generate_markdown())

	assert sections - set(subsequence.__all__) == set(), "a section documents something that is not exported"
	assert functions - set(subsequence.__all__) == set(), "a Global functions row names something that is not exported"
	assert utilities == set(subsequence.sequence_utils.__all__)


def test_the_documented_surface_parser_sees_what_it_counts () -> None:

	"""The two tests above are only as good as this reading of the sheet, so check it on a known fragment."""

	fragment = "\n".join([
		"## Package-level exports", "| `Composition` | class | x |",
		"## `Composition`", "| `play() -> None` | x |",
		"## `roles`", "| `BASS` | dict |",
		"## Global functions", "| `sieve(classes) -> List[int]` | x |",
		"## Sequence utilities (`subsequence.sequence_utils`)", "| `fold(values) -> List[int]` | x |",
	])

	assert _documented(fragment) == ({"Composition", "roles"}, {"sieve"}, {"fold"})



def test_the_sheet_prints_no_em_dash () -> None:

	"""subsystem.co publishes the sheet and never prints an em dash; a docstring's becomes a spaced hyphen (#2585)."""

	sheet = GENERATOR.generate_markdown()

	assert "—" not in sheet
	assert " - " in sheet


@pytest.mark.parametrize("doc, expected", [
	("A frozen sequence of :class:`ChordSpan` - the governing harmony value.", "A frozen sequence of `ChordSpan` - the governing harmony value."),
	("A Motif built as :class:`~subsequence.motifs.Motif` does.", "A Motif built as `Motif` does."),
	("Like :meth:`Motif.transpose`, by degree.", "Like `Motif.transpose`, by degree."),
	("See :func:`the factory <subsequence.progression>`.", "See `the factory`."),
	("Read by :py:class:`Chord`.", "Read by `Chord`."),
], ids = ["class", "tilde", "meth", "label", "py-domain"])
def test_a_role_prints_as_the_code_it_names (doc: str, expected: str) -> None:

	"""As the site shows a role in the reference: a leading ~ keeps the last name, a label replaces its target."""

	assert GENERATOR.get_first_line(doc) == expected


def test_the_sheet_prints_no_raw_role () -> None:

	"""A Markdown table cannot render a Sphinx role, and the sheet printed 18 of them, on GitHub and on the site (#3531)."""

	assert re.findall(r":(?:py:)?[a-z]+:`", GENERATOR.generate_markdown()) == []

