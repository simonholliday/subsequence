"""Every example in a docstring is checked against the API it demonstrates.

The package documents itself with fenced code blocks, RST literal blocks and no
doctests, so until #2326 nothing read them, and until #3486 nothing read the
literal ones.  An example that names a method which has been renamed, or passes
a keyword that has been dropped, is worse than no example: it is confidently
wrong, and it is what the generated reference publishes.

**This checks rather than runs, and that is a decision rather than a shortcut.**
Most of these examples are fragments by design — ``p.arpeggio(chord, root=60)``
inside a pattern function — and executing them means fabricating a ``p`` and a
``chord``, which is done here for the ones that can take it, with a keyed
``Composition`` for the ones that declare patterns on one (building one opens
nothing since #2995).  Some cannot be run at all: one that calls ``play()`` never
returns, and one that reaches the network has no business in a test.  The
static pass covers all of them; the executed pass covers what it safely can.
"""

import ast
import builtins
import contextlib
import inspect
import io
import logging
import pathlib
import random
import re
import textwrap
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.composition
import subsequence.motifs
import subsequence.pattern
import subsequence.pattern_builder


# The language is captured so that only Python is read: a pattern that skipped
# a labelled opening fence matched from its closing fence to the next opening
# one, and read the prose between them as code.
_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)

# What a bare name conventionally is in these examples.  Only names that are
# used consistently across the package appear here; anything else is left
# unchecked rather than guessed at.
_RECEIVERS: typing.Dict[str, type] = {
	"p": subsequence.pattern_builder.PatternBuilder,
	"pattern": subsequence.pattern_builder.PatternBuilder,
	"comp": subsequence.composition.Composition,
	"composition": subsequence.composition.Composition,
	"chord": subsequence.chords.Chord,
}


class Example (typing.NamedTuple):

	"""One example block, fenced or literal, and enough about it to name in a failure."""

	where: str
	source: str

	def __str__ (self) -> str:

		"""The id pytest shows — file and the thing it documents."""

		return self.where


def _python_fences (docstring: str) -> typing.List[str]:

	"""The fenced blocks marked as Python, or not marked at all."""

	return [body for language, body in _FENCE.findall(docstring) if language in ("", "python")]


def _literal_blocks (docstring: str) -> typing.List[str]:

	"""Every RST literal block - the indented block after a line ending ``::`` - outside the fences.

	Nothing read the package's 81 until #3486, when four of them named a
	parameter that does not exist and one left out a required one.  A literal
	block that is not Python - a shell command, sample output - takes a
	labelled fence instead, so every one found here is held to parsing.
	"""

	lines = _FENCE.sub("", docstring).splitlines()
	blocks = []
	index = 0

	while index < len(lines):

		line = lines[index]
		index += 1

		if not line.rstrip().endswith("::") or line.lstrip().startswith(".."):
			continue

		margin = len(line) - len(line.lstrip())

		while index < len(lines) and not lines[index].strip():
			index += 1

		body = []

		while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > margin):
			body.append(lines[index])
			index += 1

		if "".join(body).strip():
			blocks.append(textwrap.dedent("\n".join(body)).strip("\n") + "\n")

	return blocks


def _examples () -> typing.List[Example]:

	"""Every Python code block in every docstring under ``subsequence/``: fenced, and literal."""

	found = []

	package = pathlib.Path(__file__).resolve().parent.parent / "subsequence"

	for path in sorted(package.rglob("*.py")):

		tree = ast.parse(path.read_text())

		for node in ast.walk(tree):

			if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
				continue

			docstring = ast.get_docstring(node)

			if not docstring:
				continue

			owner = getattr(node, "name", "<module>")

			for index, body in enumerate(_python_fences(docstring)):
				suffix = f"[{index}]" if index else ""
				found.append(Example(f"{path.name}::{owner}{suffix}", textwrap.dedent(body)))

			for index, body in enumerate(_literal_blocks(docstring)):
				found.append(Example(f"{path.name}::{owner}::literal[{index}]", body))

	return found


EXAMPLES = _examples()


def test_the_package_still_documents_itself_with_examples () -> None:

	"""A floor on the sweep, so it cannot quietly stop finding anything.

	Every test below is parametrised over what the extractor returns, so an
	extractor that silently matched nothing would report a clean sweep of an
	empty set — the failure mode that makes a guard worse than none.
	"""

	assert len(EXAMPLES) > 100, f"only {len(EXAMPLES)} examples found — has the fence format changed?"


def test_the_literal_blocks_are_read_too () -> None:

	"""A floor on the RST literal blocks, which nothing read before #3486."""

	literal = [example for example in EXAMPLES if "::literal[" in example.where]

	assert len(literal) > 60, f"only {len(literal)} literal blocks found - has the '::' reading changed?"


@pytest.mark.parametrize("example", EXAMPLES, ids=str)
def test_an_example_is_valid_python (example: Example) -> None:

	"""A documented example that does not parse cannot have been run by anybody."""

	try:
		ast.parse(example.source)
	except SyntaxError as exc:
		pytest.fail(f"{example.where}: {exc.msg} on line {exc.lineno}\n\n{example.source}")


@pytest.mark.parametrize("example", EXAMPLES, ids=str)
def test_an_example_calls_methods_that_exist (example: Example) -> None:

	"""Every call on a conventional receiver names a real method.

	This is the drift that matters: a rename leaves the example reading
	perfectly while describing something that is not there.  `p.hit_steps(
	no_overlap=True)` survived two docstrings that way until this test.
	"""

	for call in ast.walk(ast.parse(example.source)):

		if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
			continue

		receiver = call.func.value

		if not isinstance(receiver, ast.Name) or receiver.id not in _RECEIVERS:
			continue

		owner = _RECEIVERS[receiver.id]
		method = getattr(owner, call.func.attr, None)

		assert method is not None, (
			f"{example.where}: {receiver.id}.{call.func.attr}() is not on {owner.__name__}"
		)

		# A bundle splatted in with ** passes its keys as keywords too.  roles.py's
		# own example passed root twice, by name and inside **roles.LEAD (#3486).
		named = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
		bundled: typing.Set[str] = set()

		for keyword in call.keywords:
			bundle = _package_value(keyword.value) if keyword.arg is None else None
			if isinstance(bundle, dict):
				bundled.update(bundle)

		twice = sorted(named & bundled)

		assert not twice, (
			f"{example.where}: {owner.__name__}.{call.func.attr}() is given {', '.join(twice)} by name and in a ** bundle"
		)

		try:
			parameters = inspect.signature(method).parameters
		except (ValueError, TypeError):
			continue

		# `**retired` is not API: it only catches a keyword a rename left behind, to say what
		# replaced it, as the cheat sheet reads it too (#3524).  Any other ** takes what it is given.
		if any(p.kind is inspect.Parameter.VAR_KEYWORD and p.name != "retired" for p in parameters.values()):
			continue

		for name in sorted(named | bundled):

			assert name in parameters, (
				f"{example.where}: {owner.__name__}.{call.func.attr}() takes no {name}="
			)


def _package_value (node: ast.expr) -> typing.Any:

	"""What ``subsequence.x.y`` names, if the expression is one; otherwise None."""

	parts = []

	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value

	if not isinstance(node, ast.Name) or node.id != "subsequence":
		return None

	value: typing.Any = subsequence

	for part in reversed(parts):
		value = getattr(value, part, None)
		if value is None:
			return None

	return value


# ── running the ones that can be run ────────────────────────────────────────

# An example naming any of these starts something that never returns, writes a
# file, or reaches beyond this process: play() never returns, a server listens,
# link() joins the room's Link session, and the WING helper broadcasts on the
# LAN.  An earlier sweep of these examples reached the real ports on this
# machine.  Building a Composition was on this list until #2995 made it open
# nothing; the examples that declare patterns on one now run (#3486).
_UNSAFE = (
	".play(", ".render(", ".live(", ".watch(", ".osc(", ".link(",
	"helpers.wing", "midi_input", "midi_output", "input(", "while True",
)

# Examples that resolve every name and still cannot run here, with the reason.
# Each is asserted to still fail below, so an entry cannot outlive its excuse.
_NEEDS_MORE_THAN_A_NAMESPACE = {
	"definitions.py::Definitions": "reads a project.yaml that only exists in a real project",
	"definitions.py::load_definitions": "reads a project.yaml that only exists in a real project",
	"definitions.py::<module>": "reads a project.yaml that only exists in a real project",
	"composition.py::tuning": "reads a .scl file that only exists beside a real piece",
	"pattern_builder.py::apply_tuning": "reads a .scl file that only exists beside a real piece",
	"composition.py::tweak::literal[0]": "tweaks a pattern named bass that it does not declare",
	"form_state.py::jump_to::literal[0]": "jumps a form that it does not declare",
	"composition.py::form_freeze::literal[0]": "{...} stands for a form, and is not one",
	"gm_cc.py::<module>::literal[0]": "... stands for a value, and is not one",
}


def _free_names (source: str) -> typing.Set[str]:

	"""Names an example uses before anything in it binds them.

	Order matters: ``lead = lead.reroll(...)`` binds ``lead`` *and* needs one
	already, so a set-based reading calls it self-contained and then fails at
	runtime.  Walking statements in order is enough for straight-line examples,
	which is what these are.
	"""

	bound: typing.Set[str] = set()
	free: typing.Set[str] = set()

	for statement in ast.parse(source).body:

		for node in ast.walk(statement):

			if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
				free.add(node.id)
			elif isinstance(node, ast.arg):
				bound.add(node.arg)

		for node in ast.walk(statement):

			if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
				bound.add(node.id)
			elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				bound.add(node.name)
			elif isinstance(node, (ast.Import, ast.ImportFrom)):
				bound.update((alias.asname or alias.name.split(".")[0]) for alias in node.names)

	return free


def _namespace (with_composition: bool = True) -> typing.Dict[str, typing.Any]:

	"""What these examples assume around them: the package, a ``p``, a ``chord``, a ``composition``.

	This is the fabrication the module docstring warns about — the fragments
	are written for a pattern function, so one is supplied.  The drum map holds
	the voices the examples name, because a missing voice is dropped with a
	warning and would hide a real failure behind a silent rest.
	"""

	builder = subsequence.pattern_builder.PatternBuilder(
		subsequence.pattern.Pattern(channel=0, length=4.0),
		cycle = 0,
		key = "C",
		scale = "major",
		drum_note_map = {
			"kick": 36, "kick_1": 36, "snare": 38, "snare_1": 38, "snare_2": 39,
			"hi_hat_closed": 42, "hh": 42, "clap": 39, "hand_clap": 39, "rim": 37,
		},
		rng = random.Random(1),
	)

	namespace: typing.Dict[str, typing.Any] = {"subsequence": subsequence}
	namespace.update({name: getattr(subsequence, name) for name in subsequence.__all__})
	namespace["p"] = builder
	namespace["chord"] = subsequence.chords.parse_chord("Cmaj7")

	# Built only where a test asks for it, under the fake MIDI backend: the list
	# of runnable examples is worked out at collection, before any fixture runs.
	if with_composition:
		namespace["composition"] = namespace["comp"] = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

	return namespace


def _resolvable (example: Example) -> bool:

	"""Whether this example can be run at all against the supplied namespace."""

	if any(marker in example.source for marker in _UNSAFE):
		return False

	# One that does not parse is reported by the parse test, by name.  Raising
	# here, at collection, took the whole file down with it instead.
	try:
		free = _free_names(example.source)
	except SyntaxError:
		return False

	names = set(_namespace(with_composition=False)) | {"composition", "comp"}

	return not (free - names - set(dir(builtins)))


RUNNABLE = [
	example for example in EXAMPLES
	if _resolvable(example) and example.where not in _NEEDS_MORE_THAN_A_NAMESPACE
]


def test_enough_examples_can_actually_be_run () -> None:

	"""A floor on the executed set, so it cannot quietly shrink to nothing.

	A guard that skips everything passes forever.  The number is a floor rather
	than an equality because adding a documented example should not fail a test
	about a different property.
	"""

	assert len(RUNNABLE) > 100, f"only {len(RUNNABLE)} examples are runnable - has the context changed?"


@pytest.mark.parametrize("example", RUNNABLE, ids=str)
def test_a_runnable_example_runs (example: Example, patch_midi: None, caplog: pytest.LogCaptureFixture) -> None:

	"""The example does what it says: no exception, against a real builder.

	Stronger than the static pass, which only asks whether a method exists —
	this catches an argument whose *value* stopped being accepted.

	``patch_midi`` is here because ``_UNSAFE`` cannot be complete: it is a list
	of names somebody thought of, and it missed ``mido.get_output_names()`` in
	`midi_utils`, which enumerated real ports here and raised on a CI runner
	with no ALSA at all.  The fake backend covers the whole class — anything
	that reaches a device — and the name list is left to cover what a fake
	backend cannot, which is the calls that never return.

	A voice the drum map lacks is dropped with a warning rather than raising,
	so that warning fails the example too.  The map lacked ``kick_1`` and seven
	examples ran their kick as a silent rest (#3471); a name missing from the
	map can only be caught by the warning, never by the list.
	"""

	namespace = _namespace()

	try:
		with contextlib.redirect_stdout(io.StringIO()), caplog.at_level(logging.WARNING, logger="subsequence"):
			exec(compile(example.source, example.where, "exec"), namespace)	# noqa: S102
	except Exception as exc:
		pytest.fail(f"{example.where}: {type(exc).__name__}: {exc}\n\n{example.source}")

	dropped = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Drum name '")]

	assert not dropped, f"{example.where} names a voice the runner's drum map lacks: {dropped}"


@pytest.mark.parametrize("where,reason", sorted(_NEEDS_MORE_THAN_A_NAMESPACE.items()))
def test_an_excused_example_still_needs_its_excuse (where: str, reason: str, patch_midi: None) -> None:

	"""An example excused from running must still be unable to run.

	Otherwise the list becomes a place things go to stop being checked — the
	failure mode of every skip list nobody revisits.
	"""

	example = next((e for e in EXAMPLES if e.where == where), None)

	assert example is not None, f"{where} is excused but no longer exists — drop the entry"

	with pytest.raises(Exception):
		with contextlib.redirect_stdout(io.StringIO()):
			exec(compile(example.source, example.where, "exec"), _namespace())	# noqa: S102


# ── the checks themselves (#3486) ───────────────────────────────────────────
#
# The package holds nothing these checks object to, so without inputs of their
# own a break in any of them would fail nothing.

def test_a_labelled_fence_is_not_read_as_python () -> None:

	"""A shell fence is not an example, and the prose after it is not code."""

	docstring = "Install it:\n\n```shell\npip install thing\n```\n\nThen:\n\n```python\np.note(60, beat=0)\n```\n"

	assert _python_fences(docstring) == ["p.note(60, beat=0)\n"]


def test_a_literal_block_is_read_and_its_prose_is_not () -> None:

	"""The indented block after ``::`` is an example; the paragraph after it is not."""

	docstring = "Example::\n\n    p.note(60, beat=0)\n    p.note(64, beat=1)\n\nThat plays two notes.\n"

	assert _literal_blocks(docstring) == ["p.note(60, beat=0)\np.note(64, beat=1)\n"]


def test_a_keyword_given_by_name_and_in_a_bundle_is_caught () -> None:

	"""roles.py's own example did this: ``**roles.LEAD`` holds ``root`` already."""

	example = Example("synthetic", 'comp.phrase_part(channel=4, part="lead", **subsequence.roles.LEAD, root=78)\n')

	with pytest.raises(AssertionError, match="by name and in a"):
		test_an_example_calls_methods_that_exist(example)


def test_a_retired_catch_all_does_not_excuse_a_wrong_keyword () -> None:

	"""harmony() takes ``**retired`` only to say what a renamed keyword became (#3524).

	Any ``**`` used to excuse a method from this check, so harmony()'s examples went unchecked
	from the day gravity= was retired.
	"""

	example = Example("synthetic", 'comp.harmony(style="aeolian_minor", gravitas=0.5)\n')

	with pytest.raises(AssertionError, match="takes no gravitas="):
		test_an_example_calls_methods_that_exist(example)


def test_an_example_that_reaches_the_network_is_never_run () -> None:

	"""Pinned here, never by running one: the WING helper broadcasts on the LAN, and link() joins a session."""

	assert not _resolvable(Example("synthetic", "import subsequence.helpers.wing as wing\nwing.discover()\n"))
	assert not _resolvable(Example("synthetic", "composition.link()\n"))


def test_an_example_that_does_not_parse_is_left_to_the_parse_test () -> None:

	"""Deciding whether it can run must not raise at collection, where it took the whole file down."""

	try:
		runnable = _resolvable(Example("synthetic", "pip install subsequence[link]\n"))
	except SyntaxError as error:
		pytest.fail(f"deciding whether a shell line can run raised {error!r}")

	assert not runnable
