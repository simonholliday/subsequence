"""Nothing Subsequence ships points at a site that has been retired.

subsequence.live, which subsystem.co replaced (#3487): 8976864 moved the README's links to
subsystem.co, and ``python -m subsequence`` went on sending a musician's first question to the
retired Cookbook for four more days.

simonholliday.github.io/subsequence, the pdoc reference that 2a1235d stopped building so the
documentation had one home, and which answers 404 since GitHub Pages was switched off on
2026-09-24 (#3536).  Nothing linked there that day; this keeps it so.  pyproject.toml is read
as well, because PyPI shows its links.
"""

import pathlib
import typing

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent

# Each address with its scheme, so prose about a site may still name it.
RETIRED = {
	"github-pages": "://simonholliday.github.io/subsequence",
	"subsequence.live": "://subsequence.live",
}


def _shipped () -> typing.List[pathlib.Path]:

	"""The package, the examples, the README and pyproject's links: everything a musician reads."""

	files = sorted((ROOT / "subsequence").rglob("*.py")) + sorted((ROOT / "examples").rglob("*.py")) + [ROOT / "README.md", ROOT / "pyproject.toml"]

	assert len(files) > 50, "the sweep found almost nothing to read"

	return files


@pytest.mark.parametrize("site", sorted(RETIRED))
def test_nothing_shipped_links_to_a_retired_site (site: str) -> None:

	"""Its address may still be named in prose about it; never linked to."""

	linked = [
		f"{path.relative_to(ROOT)}:{number}"
		for path in _shipped()
		for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
		if RETIRED[site] in line
	]

	assert linked == []
