import inspect
import os
import re
import sys
import typing

# Add the path so we can import subsequence
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import subsequence
import subsequence.composition
import subsequence.groove
import subsequence.intervals
import subsequence.melodic_state
import subsequence.midi_utils
import subsequence.pattern_builder
import subsequence.sequence_utils

classes_to_document: typing.List[typing.Type] = [
	subsequence.composition.Composition,
	subsequence.pattern_builder.PatternBuilder,
	subsequence.groove.Groove,
	subsequence.melodic_state.MelodicState,
]

functions_to_document: typing.List[typing.Callable] = [
	subsequence.intervals.register_scale,
	subsequence.intervals.scale_notes,
	subsequence.midi_utils.bank_select,
]


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

	return re.sub(r'^[\s*`-]*', '', first_para).strip()


def format_signature (sig: inspect.Signature) -> str:

	"""Format a signature by removing 'self' and type annotations for a cleaner cheat sheet."""

	s = str(sig)
	ret_part = ""

	if ") -> " in s:
		# Find the last ") -> " which separates params from return type
		ret_part = s[s.rfind(") -> ") + 1:]

	params = []

	for name, param in sig.parameters.items():

		if name == 'self':
			continue

		if param.kind == inspect.Parameter.VAR_POSITIONAL:
			params.append(f"*{name}")

		elif param.kind == inspect.Parameter.VAR_KEYWORD:
			params.append(f"**{name}")

		else:
			params.append(name)

	return f"({', '.join(params)}){ret_part}"


def escape_md (text: str) -> str:

	"""Escape characters that might break Markdown table formatting."""

	return text.replace('|', '\\|').replace('\n', ' ')


def is_public_method (name: str, member: typing.Any) -> bool:

	"""Determine if a class member should be included in the public API documentation."""

	if name.startswith('_'):

		if name != '__init__':
			return False

	return inspect.isfunction(member) or isinstance(member, property) or inspect.ismethod(member)


def generate_markdown () -> str:

	"""Iterate through the public API surface and generate a Markdown cheat sheet."""

	output = ["# Subsequence API Cheat Sheet\n"]
	output.append("This document provides a quick overview of the public classes, methods, and functions available in the Subsequence API.\n")

	for cls in classes_to_document:

		output.append(f"## `{cls.__name__}`\n")
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

	output.append("## Global Functions\n\n")
	output.append("| Function | Description |")
	output.append("|---|---|")

	for func in functions_to_document:

		name = func.__name__

		try:
			sig = inspect.signature(func)
			signature = format_signature(sig)

		except Exception:
			signature = "(...)"

		desc = get_first_line(func.__doc__)

		code_col = f"`{name}{signature}`"
		output.append(f"| {escape_md(code_col)} | {escape_md(desc)} |")

	output.append("\n## Sequence Utilities (`subsequence.sequence_utils`)\n\n")
	output.append("Functions for generating and transforming sequences.\n\n")
	output.append("| Function | Description |")
	output.append("|---|---|")

	seq_funcs = []

	for name, member in inspect.getmembers(subsequence.sequence_utils):

		if is_public_method(name, member):
			seq_funcs.append((name, member))

	seq_funcs.sort(key=lambda x: x[0])

	for name, func in seq_funcs:
		# Ignore imported modules like typing, math, random, etc.

		if func.__module__ != 'subsequence.sequence_utils':
			continue

		try:
			sig = inspect.signature(func)
			signature = format_signature(sig)

		except Exception:
			signature = "(...)"

		desc = get_first_line(func.__doc__)

		code_col = f"`{name}{signature}`"
		output.append(f"| {escape_md(code_col)} | {escape_md(desc)} |")

	return "\n".join(output)


if __name__ == "__main__":

	md_content = generate_markdown()

	docs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
	output_path = os.path.join(docs_dir, 'api-cheatsheet.md')

	with open(output_path, 'w') as f:
		f.write(md_content)

	print(f"Generated cheatsheet at {output_path}")

