"""No example carries an em dash (#3508).

Simon's rule (#2568): "Spaced hyphens. We should never use an em dash. I do not ever want to see an
em dash in the output."  The package's docstrings and every string it can print are held to it
already (test_docstring_voice.py, test_message_voice.py), and the README and the cheat sheet carry
none.  The examples had 40 until #3508.  An example is read line by line, so here its comments
count as well as its docstrings.
"""

import pathlib
import typing

import pytest


EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

# Built rather than typed: an escape can land in a file as the character it names.
EM_DASH = chr(0x2014)


def _names () -> typing.List[str]:

	names = sorted(path.name for path in EXAMPLES.glob("*.py"))

	assert len(names) >= 12, f"only {len(names)} examples found"

	return names


@pytest.mark.parametrize("name", _names())
def test_an_example_has_no_em_dash (name: str) -> None:

	lines = (EXAMPLES / name).read_text(encoding="utf-8").splitlines()

	assert [f"{number}: {line.strip()}" for number, line in enumerate(lines, 1) if EM_DASH in line] == []
