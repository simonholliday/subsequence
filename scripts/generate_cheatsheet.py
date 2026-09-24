"""
Generate ``api-cheatsheet.md`` from the public API's signatures and docstrings.

Run after changing the public API surface so the cheat sheet stays in sync:
``python scripts/generate_cheatsheet.py``.

**What it documents is ``subsequence.__all__``, and nothing else decides it.**
Each exported class gets a section, each exported module (``roles``) a table
of its own ``__all__``, and each exported function a row; the sequence kernels
come from ``subsequence.sequence_utils.__all__``, the one submodule that
declares its own public list.  The generator used to keep two lists of its own,
and they drifted from ``__all__`` in both directions (#2593).

``--check`` writes nothing and exits non-zero if the file on disk is not what
this would generate, naming what moved.  CI runs that, so the cheat sheet
cannot go stale while somebody is in a hurry — it was accurate by discipline
before, which works right up until the day it does not (#2326).
"""

import difflib
import inspect
import os
import re
import sys
import types
import typing

# What a union can be spelled as.  ``types.UnionType`` is the PEP 604 ``X | Y``
# object, which is what newer interpreters build even for a ``typing.Union``.
_UNION_ORIGINS = (typing.Union, types.UnionType)

# Add the path so we can import subsequence
import subsequence.sequence_utils


def exports () -> typing.List[typing.Tuple[str, typing.Any]]:

	"""Each name in ``subsequence.__all__`` with the object it names, in the list's own order.

	``__all__`` is the public surface — ``tests/test_api_consistency.py`` pins it
	against the package — so it is the only list read here.
	"""

	return [(name, getattr(subsequence, name)) for name in subsequence.__all__]


def exported_classes () -> typing.List[typing.Tuple[str, typing.Any]]:

	"""The exported classes, each documented with a section of its methods."""

	return [(name, member) for name, member in exports() if inspect.isclass(member)]


def exported_modules () -> typing.List[typing.Tuple[str, types.ModuleType]]:

	"""The exported modules, each documented with a table of its own ``__all__``."""

	return [(name, member) for name, member in exports() if inspect.ismodule(member)]


def exported_functions () -> typing.List[typing.Tuple[str, typing.Any]]:

	"""The exported functions, each documented with a row under Global functions."""

	return [
		(name, member) for name, member in exports()
		if callable(member) and not inspect.isclass(member) and not inspect.ismodule(member)
	]


def sequence_utilities () -> typing.List[typing.Tuple[str, typing.Any]]:

	"""The kernels ``subsequence.sequence_utils`` declares public, alphabetically."""

	return sorted(
		((name, getattr(subsequence.sequence_utils, name)) for name in subsequence.sequence_utils.__all__),
		key = lambda pair: pair[0],
	)


# The roles subsystem.co resolves in the reference, spelled as its python_api.py spells them.
_ROLE = re.compile(r":(?:py:)?(?:class|meth|func|attr|mod|data|exc|obj|const):`(?P<target>[^`]+)`")


def _plain_role (match: "re.Match[str]") -> str:

	"""A role as the code it names, shown as the site shows it: ``~a.b.C`` as ``C``, ``label <target>`` as its label."""

	written = match.group("target").strip()
	explicit = re.fullmatch(r"(?P<label>.+?)\s*<(?P<target>[^>]+)>", written)

	if explicit:
		return f"`{explicit.group('label')}`"

	if written.startswith("~"):
		return f"`{written[1:].rsplit('.', 1)[-1]}`"

	return f"`{written}`"


def get_first_line (doc: typing.Optional[str]) -> str:

	"""Extract the first paragraph from a docstring, handling indentation and word-wrap."""

	if not doc:
		return ""

	paragraphs = re.split(r'\n\s*\n', doc.strip())

	if not paragraphs:
		return ""

	first_para = paragraphs[0]
	first_para = first_para.replace('\n', ' ')
	first_para = re.sub(r'\s+', ' ', first_para)

	# subsystem.co publishes this sheet, and the site never prints an em
	# dash: its dash is a spaced hyphen (#2585).  Docstrings keep theirs.
	first_para = re.sub(r'\s*\u2014\s*', ' - ', first_para)

	# Nor can a Markdown table render a Sphinx role: the sheet printed
	# ":class:`Progression`" on GitHub and on the site alike (#3531).
	first_para = _ROLE.sub(_plain_role, first_para)

	return re.sub(r'^[\s*`-]*', '', first_para).strip()


def format_annotation (annotation: typing.Any) -> str:

	"""Render an annotation the way this project spells types, on any interpreter.

	``str(signature)`` follows the running Python: 3.10 prints ``Optional[int]``
	and 3.14 prints ``int | None`` for the same annotation.  So a sheet
	generated on one and checked on the other differs in rows nobody touched,
	which is how the ``--check`` gate failed on its first run.  This project
	writes ``typing.Optional[X]`` rather than PEP 604 (see the type-hint
	override in the project notes), so that is the spelling here.

	A union is always rendered here rather than read off its repr, because the
	repr is the thing that moves: 3.10 writes ``Union[int, str, NoneType]``
	where 3.14 writes ``int | str | None``, and only one of those is the
	spelling this project uses.  Everything else is handed to the formatter
	``str(signature)`` itself uses, so rows without a union stay byte-identical
	rather than being re-rendered by this.
	"""

	arguments = typing.get_args(annotation)

	if arguments and typing.get_origin(annotation) in _UNION_ORIGINS:

		# None is pulled out and spelled as Optional however many arms there
		# are, so a three-arm union does not become the bare NoneType that a
		# two-arm special case would leave behind.
		present = [a for a in arguments if a is not type(None)]

		if len(present) == 1:
			rendered = format_annotation(present[0])
		else:
			rendered = "Union[" + ", ".join(format_annotation(a) for a in present) + "]"

		return f"Optional[{rendered}]" if len(present) < len(arguments) else rendered

	plain = inspect.formatannotation(annotation)

	if "|" not in plain or not arguments:
		return plain

	# A union nested inside a generic — recurse so it is canonicalised too.
	head = plain.split("[")[0]

	return f"{head}[" + ", ".join(format_annotation(a) for a in arguments) + "]"


def format_signature (sig: inspect.Signature) -> str:

	"""Format a signature by removing 'self' and type annotations for a cleaner cheat sheet."""

	ret_part = ""

	if sig.return_annotation is not inspect.Signature.empty:
		# Forward-reference annotations ("PatternBuilder") render with their
		# quote characters — strip them so the sheet shows `-> Groove`, not
		# the confusing `-> "'Groove'"`.
		ret_part = " -> " + format_annotation(sig.return_annotation).replace('"', '').replace("'", "")

	params = []

	for name, param in sig.parameters.items():

		if name == 'self':
			continue

		if param.kind == inspect.Parameter.VAR_POSITIONAL:
			params.append(f"*{name}")

		elif param.kind == inspect.Parameter.VAR_KEYWORD:

			# `**retired` is a reserved name, not API: a method that has had a
			# parameter renamed catches the old spelling so the error can give
			# the conversion, where a plain TypeError would name the parameter
			# and stop. `tweak(**kwargs)` and `replace(**changes)` really do
			# take arbitrary keywords, so the rule is the name, not the kind.
			if name == "retired":
				continue

			params.append(f"**{name}")

		else:
			params.append(name)

	return f"({', '.join(params)}){ret_part}"


def escape_md (text: str) -> str:

	"""Escape characters that might break Markdown table formatting."""

	return text.replace('|', '\\|').replace('\n', ' ')


def describe_value (value: typing.Any) -> str:

	"""Describe an exported module's value in one cell: a dict by its keys, anything else by its repr."""

	if isinstance(value, dict):
		return "dict of " + ", ".join(f"`{key}`" for key in value)

	return f"`{value!r}`"


def is_public_method (name: str, member: typing.Any) -> bool:

	"""Determine if a class member should be included in the public API documentation."""

	if name.startswith('_'):

		if name != '__init__':
			return False

	return inspect.isfunction(member) or isinstance(member, property) or inspect.ismethod(member)


def generate_markdown () -> str:

	"""Iterate through the public API surface and generate a Markdown cheat sheet."""

	output = ["# Subsequence API cheat sheet\n"]
	output.append("This document provides a quick overview of the public classes, methods, and functions available in the Subsequence API.\n")

	# The inventory first: every name ``subsequence.__all__`` exports, each of
	# which also has its own section or row below.
	output.append("## Package-level exports\n")
	output.append("Everything exported as `subsequence.X`:\n")
	output.append("| Export | Kind | Description |")
	output.append("|---|---|---|")

	for name in sorted(subsequence.__all__):

		member = getattr(subsequence, name)

		if inspect.ismodule(member):
			kind = "module"
		elif inspect.isclass(member):
			kind = "class"
		elif callable(member):
			kind = "function"
		else:
			kind = "value"

		desc = get_first_line(getattr(member, '__doc__', None))
		output.append(f"| `{name}` | {kind} | {escape_md(desc)} |")

	output.append("\n")

	for export_name, cls in exported_classes():

		output.append(f"## `{export_name}`\n")
		doc = get_first_line(cls.__doc__)

		if doc:
			output.append(f"{doc}\n")

		output.append("| Method | Description |")
		output.append("|---|---|")

		# Get public methods
		methods = []

		for name, member in inspect.getmembers(cls):

			if is_public_method(name, member):
				methods.append((name, member))

		methods.sort(key=lambda x: x[0])

		for name, member in methods:

			try:
				if isinstance(member, property):
					signature = " *(property)*"
					desc = get_first_line(member.__doc__)

				else:

					try:
						sig = inspect.signature(member)
						signature = format_signature(sig)

					except ValueError:
						signature = "(...)"

					desc = get_first_line(member.__doc__)

				code_col = f"`{name}{signature}`"

				# escape pipes if any
				code_col = escape_md(code_col)
				desc_md = escape_md(desc)

				output.append(f"| {code_col} | {desc_md} |")

			except Exception:
				# Fallback if something fails
				output.append(f"| `{name}` | Error formatting |")

		output.append("\n")

	for export_name, module in exported_modules():

		output.append(f"## `{export_name}`\n")
		doc = get_first_line(module.__doc__)

		if doc:
			output.append(f"{doc}\n")

		output.append("| Name | Value |")
		output.append("|---|---|")

		for name in module.__all__:
			output.append(f"| `{name}` | {escape_md(describe_value(getattr(module, name)))} |")

		output.append("\n")

	output.append("## Global functions\n\n")
	output.append("| Function | Description |")
	output.append("|---|---|")

	for name, func in exported_functions():

		try:
			sig = inspect.signature(func)
			signature = format_signature(sig)

		except Exception:
			signature = "(...)"

		desc = get_first_line(func.__doc__)

		code_col = f"`{name}{signature}`"
		output.append(f"| {escape_md(code_col)} | {escape_md(desc)} |")

	output.append("\n## Sequence utilities (`subsequence.sequence_utils`)\n\n")
	output.append("Functions for generating and transforming sequences.\n\n")
	output.append("| Function | Description |")
	output.append("|---|---|")

	for name, func in sequence_utilities():

		try:
			sig = inspect.signature(func)
			signature = format_signature(sig)

		except Exception:
			signature = "(...)"

		desc = get_first_line(func.__doc__)

		code_col = f"`{name}{signature}`"
		output.append(f"| {escape_md(code_col)} | {escape_md(desc)} |")

	return "\n".join(output)


def check (path: str, expected: str) -> int:

	"""Report whether the cheat sheet on disk still matches the code.

	Returns a process exit status.  The diff is trimmed rather than printed
	whole: a signature change is a handful of lines, and a regeneration nobody
	ran is hundreds — the first is the useful message and the second only
	needs its size.
	"""

	if not os.path.exists(path):
		print(f"{path} does not exist — run: python scripts/generate_cheatsheet.py")
		return 1

	with open(path) as handle:
		current = handle.read()

	if current == expected:
		print(f"{os.path.basename(path)} is up to date")
		return 0

	diff = list(difflib.unified_diff(
		current.splitlines(), expected.splitlines(),
		fromfile=f"{os.path.basename(path)} (on disk)", tofile="generated from the code",
		lineterm="", n=1,
	))

	print(f"{os.path.basename(path)} is out of date — run: python scripts/generate_cheatsheet.py")
	print()
	print("\n".join(diff[:40]))

	if len(diff) > 40:
		print(f"... and {len(diff) - 40} more lines")

	return 1


if __name__ == "__main__":

	md_content = generate_markdown()

	docs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
	output_path = os.path.join(docs_dir, 'api-cheatsheet.md')

	if "--check" in sys.argv[1:]:
		sys.exit(check(output_path, md_content))

	with open(output_path, 'w') as f:
		f.write(md_content)

	print(f"Generated cheatsheet at {output_path}")

