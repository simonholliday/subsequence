"""
Project definitions loader — a shared name-to-number vocabulary file.

A music project can keep one small YAML file (any filename — ``project.yaml``,
``kit.yaml``) mapping human names to MIDI numbers, shared between Subsequence
and the Subsample sampler.  Both tools read the same file, so renumbering a
sound or a controller is one edit and both follow on their next reload.  The
file format is the only contract — neither application depends on the other.

The file is a flat mapping of sections, each mapping names to whole numbers:

	notes:
	  ride_edge_soft: 53
	  dawn_chorus_pheasant: 60
	cc:
	  sampler_release: 21
	channels:
	  kit: 10
	  birds: 3
	programs:
	  brushes: 1
	nrpn:
	  filter_env_amount: 1042

Sections and value ranges (inclusive):

	- ``notes`` — MIDI note numbers, 0-127.
	- ``cc`` — controller numbers, 0-127.
	- ``channels`` — MIDI channels as musicians count them, 1-16.
	- ``programs`` — program-change numbers as sent on the wire (0-based), 0-127.
	- ``nrpn`` — 14-bit NRPN parameter numbers, 0-16383.  Subsequence-specific;
	  Subsample ignores this section.

Names must match ``[a-z][a-z0-9_]*`` — lowercase letters, digits, underscores;
no dots, no leading digit.  Unknown top-level sections are silently ignored, so
either tool can grow a new section without breaking the other.  An empty file,
an absent section, and a null section are all valid.  Every failure raises
``ValueError`` naming the file, section, and offending entry — the same checks,
in the same order, as Subsample applies, so a bad file fails the same way in
both tools.

Caveats worth knowing:

	- ``channels`` values are always user-facing 1-16 (the cross-tool contract).
	  They pass straight into ``channel=`` under the default numbering; if your
	  composition sets ``zero_indexed_channels=True``, subtract 1 yourself.
	- YAML silently collapses duplicate keys — the last duplicate wins, and
	  neither tool can detect it.
	- Names resolve exactly as written (lowercase) in ``drum_note_map`` /
	  ``cc_name_map`` lookups.  Merging over a stock map, the later dict wins:
	  ``{**gm_drums.GM_DRUM_MAP, **defs.notes}`` lets your names shadow GM ones.
	- A ``subsequence.load_definitions(...)`` call at the top of a watched file
	  re-runs on every live reload, so the definitions re-read naturally.

Example:
	```python
	import subsequence

	defs = subsequence.load_definitions("project.yaml")
	comp = subsequence.Composition(bpm=100)

	@comp.pattern(channel=defs.channels["birds"], drum_note_map=defs.notes, cc_name_map=defs.cc)
	def birds (b):
		b.hit("dawn_chorus_pheasant", beats=[0, 2.5])
		b.cc("sampler_release", 64)
	```
"""

import dataclasses
import pathlib
import re
import typing

import yaml


CONSUMED_SECTIONS: typing.FrozenSet[str] = frozenset({
	"notes", "cc", "channels", "programs", "nrpn",
})

_SECTION_RANGES: typing.Dict[str, typing.Tuple[int, int]] = {
	"notes":    (0, 127),
	"cc":       (0, 127),
	"channels": (1, 16),
	"programs": (0, 127),
	"nrpn":     (0, 16383),
}

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclasses.dataclass(frozen=True)
class Definitions:

	"""
	The name-to-number tables read from a project definitions file.

	One plain ``dict`` per section, always present — an absent or null section
	is an empty dict.  The dicts merge directly into the existing parameters:
	``notes`` into ``drum_note_map=``, ``cc`` into ``cc_name_map=``, ``nrpn``
	into ``nrpn_name_map=``, while ``channels`` values feed ``channel=`` and
	``programs`` values feed ``p.program_change()``.

	The dataclass is frozen (attributes cannot be reassigned) but the dicts
	themselves are ordinary mutable dicts, so they can be merged and extended
	freely.

	Example:
		```python
		defs = subsequence.load_definitions("project.yaml")
		defs.channels["birds"]      # 3
		defs.notes                  # {"ride_edge_soft": 53, ...}
		```
	"""

	notes:    typing.Dict[str, int] = dataclasses.field(default_factory=dict)
	cc:       typing.Dict[str, int] = dataclasses.field(default_factory=dict)
	channels: typing.Dict[str, int] = dataclasses.field(default_factory=dict)
	programs: typing.Dict[str, int] = dataclasses.field(default_factory=dict)
	nrpn:     typing.Dict[str, int] = dataclasses.field(default_factory=dict)


def load_definitions (path: typing.Union[str, pathlib.Path]) -> Definitions:

	"""
	Load and validate a project definitions file.

	Reads the YAML file at ``path`` and returns a :class:`Definitions` whose
	``notes`` / ``cc`` / ``channels`` / ``programs`` / ``nrpn`` dicts merge
	straight into pattern parameters.  See the module docstring for the file
	format, the value ranges, and the shared-vocabulary contract with the
	Subsample sampler.

	Validation is strict inside the sections listed above and lenient outside
	them: unknown top-level sections are ignored, while a bad name, a non-whole
	number (including YAML ``true``/``false``), or an out-of-range value is
	rejected with an error naming the file, section, and entry.

	Parameters:
		path: The definitions file, as a path string or ``pathlib.Path``.

	Returns:
		A :class:`Definitions` with one name-to-number dict per section.

	Raises:
		ValueError: If the file is missing, unreadable, or not valid YAML; if
			the top level or a consumed section is not a mapping; or if a name
			or value inside a consumed section is invalid.  File-system and
			YAML errors are wrapped so this is the only error type raised.

	Example:
		```python
		defs = subsequence.load_definitions("project.yaml")

		@comp.pattern(channel=defs.channels["kit"], drum_note_map=defs.notes)
		def kit (p):
			p.hit("ride_edge_soft", beats=[1, 3])
		```
	"""

	p = pathlib.Path(path)

	try:
		with p.open(encoding="utf-8") as fh:
			raw = yaml.safe_load(fh)
	except (OSError, yaml.YAMLError) as exc:
		raise ValueError(
			f"definitions file {p} could not be read: {exc}"
		) from exc

	if raw is None:
		return Definitions()

	if not isinstance(raw, dict):
		raise ValueError(
			f"definitions file {p}: top level must be a mapping of "
			f"sections (notes:, cc:, …), got {type(raw).__name__}"
		)

	tables: typing.Dict[str, typing.Dict[str, int]] = {}

	for section in sorted(CONSUMED_SECTIONS):
		section_raw = raw.get(section)

		if section_raw is None:
			continue

		if not isinstance(section_raw, dict):
			raise ValueError(
				f"definitions file {p}: section {section!r} must be a "
				f"mapping of name to number "
				f"(got {type(section_raw).__name__})"
			)

		lo, hi = _SECTION_RANGES[section]
		table: typing.Dict[str, int] = {}

		for name_raw, value in section_raw.items():
			name = str(name_raw)

			if not _NAME_RE.fullmatch(name):
				raise ValueError(
					f"definitions file {p}: section {section!r}: name "
					f"{name!r} must match [a-z][a-z0-9_]* (lowercase "
					f"letters, digits, underscores — no dots)"
				)

			# bool is an int subclass — reject it first so ``x: true`` fails
			# loudly instead of quietly becoming 1.
			if isinstance(value, bool) or not isinstance(value, int):
				raise ValueError(
					f"definitions file {p}: section {section!r}: "
					f"{name!r} must be a whole number (got {value!r})"
				)

			if not lo <= value <= hi:
				raise ValueError(
					f"definitions file {p}: section {section!r}: "
					f"{name!r} = {value} is outside [{lo}, {hi}]"
				)

			table[name] = value

		tables[section] = table

	return Definitions(
		notes    = tables.get("notes", {}),
		cc       = tables.get("cc", {}),
		channels = tables.get("channels", {}),
		programs = tables.get("programs", {}),
		nrpn     = tables.get("nrpn", {}),
	)
