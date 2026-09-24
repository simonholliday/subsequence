"""A docstring is published text, so it is held to the site's voice here, before a re-pin finds it.

subsystem.co generates Subsequence's API reference from the docstrings of everything in
`subsequence.__all__`, and the cheat sheet from their first lines.  The site never prints an em
dash: the dash is a spaced hyphen (#2568).  Its prose is British English (#2323).  Its checks run
only when the site pins a new commit, long after the docstring was written - 978 dashes had
accumulated by the time they first ran - so this reads every docstring in the package, published
or not, on every run of the suite.
"""

import ast
import pathlib
import re
import typing

import subsequence


PACKAGE = pathlib.Path(subsequence.__file__).resolve().parent

# The site's own pattern for a US spelling (subsystem.voice._US_SPELLING), and the words it lets
# through because their -ize is not a suffix.  Copied rather than imported: the site is another
# repository, and this suite has to run without it.
_US_SPELLING = re.compile(
	r"\b(?:"
	r"[A-Za-z]+iz(?:e|es|ed|er|ers|ing|ation|ations)"
	r"|[A-Za-z]+yz(?:e|es|ed|er|ers|ing)"
	r"|colors?|colored|coloring|colorful|colorless"
	r"|behaviors?|behavioral"
	r"|centers?|centered|centering"
	r"|favorites?|flavors?|honors?|neighbors?|labor"
	r"|analog|catalogs?"
	r")\b",
	re.IGNORECASE,
)

# Ours, beside the site's: a music package's word that its list does not carry (#3531).  A
# measuring meter is spelled the same, and none is in the package; one would go in backticks.
_METER = re.compile(r"\bmeters?\b", re.IGNORECASE)

_NOT_A_SUFFIX = re.compile(
	r"(?:re|over|down|up|under|bite|king|life|pint|full)?-?siz(?:e|es|ed|er|ing)"
	r"|seiz(?:e|es|ed|ing)|priz(?:e|es|ed|ing)|capsiz(?:e|es|ed|ing)|maize|baize|assizes?",
	re.IGNORECASE,
)

_CODE_SPAN = re.compile(r"``.+?``|`[^`\n]+`")


def _docstrings () -> typing.List[typing.Tuple[str, str]]:

	"""Every module, class and function docstring in the package, with the line it starts on."""

	found: typing.List[typing.Tuple[str, str]] = []

	for path in sorted(PACKAGE.rglob("*.py")):

		tree = ast.parse(path.read_text(encoding="utf-8"))

		for node in ast.walk(tree):

			if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
				continue

			docstring = ast.get_docstring(node, clean=False)

			if docstring:
				found.append((f"{path.relative_to(PACKAGE.parent)}:{node.body[0].lineno}", docstring))

	return found


def test_the_walk_reads_the_whole_package () -> None:

	"""A walk that found nothing would pass every check below, so it must find the package first."""

	where = [location for location, _ in _docstrings()]

	assert len(where) > 1000
	assert any(location.startswith("subsequence/composition.py:") for location in where)
	assert any(location.startswith("subsequence/constants/") for location in where)


def test_no_docstring_prints_an_em_dash () -> None:

	"""The site never prints an em dash, and a docstring is what it prints (#2568)."""

	offenders = [location for location, text in _docstrings() if "\u2014" in text]

	assert offenders == []


def _us_spellings (docstring: str) -> typing.List[str]:

	"""The US spellings in a docstring's prose, leaving out its code and every word used as a name.

	Code is a fenced block, a doctest line or a code span.  A word is a name rather than English
	when it follows `.` or `_`, comes before `(`, `=` or `_`, or labels an item at the start of a
	line, as `quantize:` labels a parameter.  The site prints those as code, and respelling one
	would name something that does not exist.
	"""

	found: typing.List[str] = []
	fence = False

	for line in docstring.split("\n"):

		stripped = line.strip()

		if stripped.startswith("```"):
			fence = not fence
			continue

		if fence or stripped.startswith((">>>", "...")):
			continue

		masked = _CODE_SPAN.sub(lambda match: "\x00" * len(match.group(0)), line)

		for match in [*_US_SPELLING.finditer(masked), *_METER.finditer(masked)]:

			before, after = masked[:match.start()], masked[match.end():]

			if _NOT_A_SUFFIX.fullmatch(match.group(0)):
				continue

			if before.endswith((".", "_")) or after.startswith(("(", "=", "_")):
				continue

			if not before.strip() and re.match(r"\s*(\([^)]*\))?\s*:", after):
				continue

			found.append(match.group(0))

	return found


def test_the_spelling_check_reads_prose_and_passes_names () -> None:

	"""What the check below finds, on text whose answer is known: so a check that saw nothing cannot pass."""

	assert _us_spellings("Snap each note to a quantized grid, then normalize it.") == ["quantized", "normalize"]
	assert _us_spellings("Resize the window, then seize the moment.") == []
	assert _us_spellings("In additive meters the meter-independent flavour holds; parameters pass.") == ["meters", "meter"]

	names = "\n".join([
		"quantize: ``0`` fires at once.",
		"normalize (bool): Divide by the maximum.",
		"Pass ``quantize=4`` to wait, or call p.randomize() for feel.",
		"Read the ``quantized`` flag, or the `synthesizer` port.",
		"```python",
		"composition.trigger(builder, quantize=4)  # a quantized trigger",
		"```",
		">>> print('a quantized grid')",
	])

	assert _us_spellings(names) == []


def test_docstring_prose_is_british () -> None:

	"""The site's prose is British English (#2323), and it reads a docstring's prose as its own."""

	offenders = [f"{location} {word}" for location, text in _docstrings() for word in _us_spellings(text)]

	assert offenders == []
