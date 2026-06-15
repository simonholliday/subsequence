"""Guard against docstring markup that renders wrong under Sphinx/RST.

Flags two things inside docstrings (skipping ```` ```...``` ```` fenced code
blocks, ``:role:`x``` roles, and ``\\`text <url>\\`_`` hyperlink references):

* bare single-backtick inline code (``\\`Chord\\```) — RST reads a single
  backtick as an interpreted-text role, so inline code must use double
  backticks (``\\`\\`Chord\\`\\```);
* bare ``*args`` / ``**kwargs`` in prose — a lone ``*``/``**`` starts RST
  emphasis/strong with no end, so varargs must be wrapped in double backticks.

Runs over ``subsequence/`` and exits non-zero on any finding, naming the
file and line so the offending docstring is easy to find.  Inline-code that
renders as code under both pdoc (markdown) and Sphinx (RST) passes clean.

Usage:
    python scripts/check_docstring_markup.py [path ...]   # default: subsequence
"""

import ast
import pathlib
import re
import sys


# A standalone inline single-backtick span (group 1) — NOT a :role:`x`, NOT a
# `text`_ hyperlink, NOT already double.  Roles are matched first so their
# backticks are consumed and never mistaken for inline code.
_SPAN = re.compile(r":[a-zA-Z_]+:`[^`\n]+`|(?<![:`_])`([^`\n]+)`(?![`_])")

# Bare *args / **kwargs (varargs notation) outside backticks/emphasis.
_VARARGS = re.compile(r"(?<![`*\w])\*\*?(?:args|kwargs)(?![`*\w])")

_FENCE = re.compile(r"^\s*```")


def _docstrings (tree):

	"""Yield (start_lineno, text) for each module/class/function docstring."""

	for node in ast.walk(tree):

		if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:

			first = node.body[0]

			if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
				yield (first.value.lineno, first.value.value)


def check_file (path):

	"""Return a list of (lineno, message) findings for one .py file."""

	source = path.read_text()
	tree = ast.parse(source)

	findings = []

	for start_lineno, text in _docstrings(tree):

		in_fence = False

		for offset, line in enumerate(text.splitlines()):

			if _FENCE.match(line):
				in_fence = not in_fence
				continue

			if in_fence:
				continue

			lineno = start_lineno + offset

			if any(match.group(1) is not None for match in _SPAN.finditer(line)):
				findings.append((lineno, "single-backtick inline code — use double backticks"))

			if _VARARGS.search(line):
				findings.append((lineno, "bare *args/**kwargs — wrap in double backticks"))

	return findings


def main (argv):

	"""Scan the given paths (default subsequence/) and report findings."""

	roots = [pathlib.Path(a) for a in argv] or [pathlib.Path("subsequence")]
	files = []

	for root in roots:
		files.extend(sorted(root.rglob("*.py")) if root.is_dir() else [root])

	total = 0

	for path in files:
		for lineno, message in check_file(path):
			print(f"{path}:{lineno}: {message}")
			total += 1

	if total:
		print(f"\n{total} docstring markup issue(s) — see docs at scripts/check_docstring_markup.py")
		return 1

	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
