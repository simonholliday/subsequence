"""Every example in a docstring is checked against the API it demonstrates.

The package documents itself with 147 fenced code blocks and no doctests, so
until now nothing read them (#2326).  An example that names a method which has
been renamed, or passes a keyword that has been dropped, is worse than no
example: it is confidently wrong, and it is what the generated reference
publishes.

**This checks rather than runs, and that is a decision rather than a shortcut.**
Most of these examples are fragments by design — ``p.arpeggio(chord, root=60)``
inside a pattern function — and executing them means fabricating a ``p`` and a
``chord``, which is done here for the ones that can take it.  Some cannot be run
at all: an example that builds a ``Composition`` opens MIDI hardware, and one
that calls ``play()`` never returns.  The static pass covers all of them; the
executed pass covers what it safely can.
"""

import ast
import builtins
import contextlib
import inspect
import io
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


_FENCE = re.compile(r"```(?:python)?\n(.*?)```", re.S)

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

	"""One fenced block, and enough about it to name in a failure."""

	where: str
	source: str

	def __str__ (self) -> str:

		"""The id pytest shows — file and the thing it documents."""

		return self.where


def _examples () -> typing.List[Example]:

	"""Every fenced code block in every docstring under ``subsequence/``."""

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

			for index, body in enumerate(_FENCE.findall(docstring)):
				suffix = f"[{index}]" if index else ""
				found.append(Example(f"{path.name}::{owner}{suffix}", textwrap.dedent(body)))

	return found


EXAMPLES = _examples()


def test_the_package_still_documents_itself_with_examples () -> None:

	"""A floor on the sweep, so it cannot quietly stop finding anything.

	Every test below is parametrised over what the extractor returns, so an
	extractor that silently matched nothing would report a clean sweep of an
	empty set — the failure mode that makes a guard worse than none.
	"""

	assert len(EXAMPLES) > 100, f"only {len(EXAMPLES)} examples found — has the fence format changed?"


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

		try:
			parameters = inspect.signature(method).parameters
		except (ValueError, TypeError):
			continue

		if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
			continue

		for keyword in call.keywords:

			assert keyword.arg is None or keyword.arg in parameters, (
				f"{example.where}: {owner.__name__}.{call.func.attr}() takes no {keyword.arg}="
			)


# ── running the ones that can be run ────────────────────────────────────────

# An example naming any of these builds or starts something: a Composition opens
# MIDI hardware, and play() never returns.  Measured, not guessed — an earlier
# sweep of these examples reached the real ports on this machine.
_UNSAFE = (
	"Composition(", "@composition", ".play(", ".render(", ".live(", ".watch(",
	".web_ui(", ".osc(", "midi_input", "midi_output", "input(", "while True",
)

# Examples that resolve every name and still cannot run here, with the reason.
# Each is asserted to still fail below, so an entry cannot outlive its excuse.
_NEEDS_MORE_THAN_A_NAMESPACE = {
	"definitions.py::Definitions": "reads a project.yaml that only exists in a real project",
	"definitions.py::load_definitions": "reads a project.yaml that only exists in a real project",
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


def _namespace () -> typing.Dict[str, typing.Any]:

	"""What these examples assume around them: the package, a ``p``, a ``chord``.

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
			"kick": 36, "snare": 38, "snare_1": 38, "snare_2": 39,
			"hi_hat_closed": 42, "hh": 42, "clap": 39, "rim": 37,
		},
		rng = random.Random(1),
	)

	namespace: typing.Dict[str, typing.Any] = {"subsequence": subsequence}
	namespace.update({name: getattr(subsequence, name) for name in subsequence.__all__})
	namespace["p"] = builder
	namespace["chord"] = subsequence.chords.parse_chord("Cmaj7")

	return namespace


def _resolvable (example: Example) -> bool:

	"""Whether this example can be run at all against the supplied namespace."""

	if any(marker in example.source for marker in _UNSAFE):
		return False

	return not (_free_names(example.source) - set(_namespace()) - set(dir(builtins)))


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

	assert len(RUNNABLE) > 60, f"only {len(RUNNABLE)} examples are runnable — has the context changed?"


@pytest.mark.parametrize("example", RUNNABLE, ids=str)
def test_a_runnable_example_runs (example: Example, patch_midi: None) -> None:

	"""The example does what it says: no exception, against a real builder.

	Stronger than the static pass, which only asks whether a method exists —
	this catches an argument whose *value* stopped being accepted.

	``patch_midi`` is here because ``_UNSAFE`` cannot be complete: it is a list
	of names somebody thought of, and it missed ``mido.get_output_names()`` in
	`midi_utils`, which enumerated real ports here and raised on a CI runner
	with no ALSA at all.  The fake backend covers the whole class — anything
	that reaches a device — and the name list is left to cover what a fake
	backend cannot, which is the calls that never return.
	"""

	namespace = _namespace()

	try:
		with contextlib.redirect_stdout(io.StringIO()):
			exec(compile(example.source, example.where, "exec"), namespace)	# noqa: S102
	except Exception as exc:
		pytest.fail(f"{example.where}: {type(exc).__name__}: {exc}\n\n{example.source}")


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
