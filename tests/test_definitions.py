"""Tests for the project definitions loader — the shared Subsample vocabulary file."""

import dataclasses
import pathlib

import pytest

import subsequence.definitions
import subsequence.pattern
import subsequence.pattern_builder


SPEC_EXAMPLE = """\
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
"""


def _write (tmp_path: pathlib.Path, content: str) -> pathlib.Path:

	"""Write ``content`` to a defs.yaml in ``tmp_path`` and return its path."""

	path = tmp_path / "defs.yaml"
	path.write_text(content)
	return path


def _load (tmp_path: pathlib.Path, content: str) -> subsequence.definitions.Definitions:

	"""Write ``content`` and load it through the real loader."""

	return subsequence.definitions.load_definitions(_write(tmp_path, content))


class TestLoadDefinitions:

	"""Behaviour of the file loader/validator (mirrors Subsample's coverage)."""

	def test_all_five_sections_load (self, tmp_path: pathlib.Path) -> None:

		"""The spec's worked example (plus nrpn) loads into per-section dicts."""

		defs = _load(tmp_path, SPEC_EXAMPLE)

		assert defs.notes == {"ride_edge_soft": 53, "dawn_chorus_pheasant": 60}
		assert defs.cc == {"sampler_release": 21}
		assert defs.channels == {"kit": 10, "birds": 3}
		assert defs.programs == {"brushes": 1}
		assert defs.nrpn == {"filter_env_amount": 1042}

	def test_unknown_sections_ignored (self, tmp_path: pathlib.Path) -> None:

		"""Foreign top-level sections load without error and are not exposed."""

		defs = _load(tmp_path, "notes: { kick: 36 }\nmixer: { main: 0 }\n")

		assert defs.notes == {"kick": 36}
		assert not hasattr(defs, "mixer")

	def test_empty_file_ok (self, tmp_path: pathlib.Path) -> None:

		"""An empty file is valid and yields empty tables."""

		defs = _load(tmp_path, "")

		assert defs.notes == {}
		assert defs.cc == {}
		assert defs.channels == {}
		assert defs.programs == {}
		assert defs.nrpn == {}

	def test_absent_and_null_sections_ok (self, tmp_path: pathlib.Path) -> None:

		"""A null section equals an absent one; attributes are always present."""

		defs = _load(tmp_path, "notes:\ncc: { a: 1 }\n")

		assert defs.notes == {}
		assert defs.cc == {"a": 1}
		assert defs.programs == {}

	def test_non_mapping_top_level_raises (self, tmp_path: pathlib.Path) -> None:

		"""A YAML list at the top level is rejected."""

		with pytest.raises(ValueError, match="top level must be a mapping"):
			_load(tmp_path, "- a\n- b\n")

	def test_consumed_section_not_mapping_raises (self, tmp_path: pathlib.Path) -> None:

		"""A consumed section holding a list is rejected."""

		with pytest.raises(ValueError, match="section 'notes' must be a mapping"):
			_load(tmp_path, "notes: [a, b]\n")

	def test_bool_value_raises (self, tmp_path: pathlib.Path) -> None:

		"""YAML ``true`` must not silently become 1 (bool is an int subclass)."""

		with pytest.raises(ValueError, match="whole number"):
			_load(tmp_path, "notes: { x: true }\n")

	def test_non_int_value_raises (self, tmp_path: pathlib.Path) -> None:

		"""Strings, floats, and empty values are rejected as non-whole-numbers."""

		for bad in ("notes: { x: hat }\n", "notes: { x: 1.5 }\n", "notes: { x: }\n"):
			with pytest.raises(ValueError, match="whole number"):
				_load(tmp_path, bad)

	def test_note_and_cc_value_range (self, tmp_path: pathlib.Path) -> None:

		"""notes and cc are 0-127 inclusive."""

		with pytest.raises(ValueError, match=r"outside \[0, 127\]"):
			_load(tmp_path, "notes: { x: -1 }\n")

		with pytest.raises(ValueError, match=r"outside \[0, 127\]"):
			_load(tmp_path, "cc: { x: 128 }\n")

		defs = _load(tmp_path, "notes: { lo: 0, hi: 127 }\n")
		assert defs.notes == {"lo": 0, "hi": 127}

	def test_channel_value_range (self, tmp_path: pathlib.Path) -> None:

		"""channels are user-facing 1-16 inclusive."""

		with pytest.raises(ValueError, match=r"outside \[1, 16\]"):
			_load(tmp_path, "channels: { x: 0 }\n")

		with pytest.raises(ValueError, match=r"outside \[1, 16\]"):
			_load(tmp_path, "channels: { x: 17 }\n")

		defs = _load(tmp_path, "channels: { lo: 1, hi: 16 }\n")
		assert defs.channels == {"lo": 1, "hi": 16}

	def test_program_value_range (self, tmp_path: pathlib.Path) -> None:

		"""programs are 0-127 inclusive (0-based wire numbering)."""

		with pytest.raises(ValueError, match=r"outside \[0, 127\]"):
			_load(tmp_path, "programs: { x: 128 }\n")

	def test_nrpn_value_range (self, tmp_path: pathlib.Path) -> None:

		"""nrpn parameter numbers are 14-bit, 0-16383 inclusive."""

		defs = _load(tmp_path, "nrpn: { max: 16383 }\n")
		assert defs.nrpn == {"max": 16383}

		with pytest.raises(ValueError, match=r"outside \[0, 16383\]"):
			_load(tmp_path, "nrpn: { x: 16384 }\n")

		with pytest.raises(ValueError, match=r"outside \[0, 16383\]"):
			_load(tmp_path, "nrpn: { x: -1 }\n")

	def test_bad_name_pattern_raises (self, tmp_path: pathlib.Path) -> None:

		"""Uppercase, leading digits, dots, and dashes violate the name grammar."""

		for bad_name in ("Dawn_Chorus", "1st", "a.b", "a-b"):
			with pytest.raises(ValueError, match=r"\[a-z\]\[a-z0-9_\]\*"):
				_load(tmp_path, f'notes: {{ "{bad_name}": 60 }}\n')

	def test_non_string_name_coerced_then_rejected (self, tmp_path: pathlib.Path) -> None:

		"""A numeric YAML key is str()-coerced and then fails the grammar check."""

		with pytest.raises(ValueError, match=r"'123' must match \[a-z\]"):
			_load(tmp_path, "notes: { 123: 60 }\n")

	def test_missing_file_raises_valueerror (self, tmp_path: pathlib.Path) -> None:

		"""A missing file surfaces as ValueError, never a bare OSError."""

		with pytest.raises(ValueError, match="could not be read"):
			subsequence.definitions.load_definitions(tmp_path / "nope.yaml")

	def test_unparseable_yaml_raises_valueerror (self, tmp_path: pathlib.Path) -> None:

		"""Broken YAML is wrapped into the loader's single error type."""

		with pytest.raises(ValueError, match="could not be read"):
			_load(tmp_path, "notes: {broken: [\n")

	def test_path_accepts_str_and_pathlib (self, tmp_path: pathlib.Path) -> None:

		"""Both a path string and a pathlib.Path load identically."""

		path = _write(tmp_path, "notes: { kick: 36 }\n")

		from_str = subsequence.definitions.load_definitions(str(path))
		from_path = subsequence.definitions.load_definitions(path)

		assert from_str == from_path
		assert from_str.notes == {"kick": 36}

	def test_definitions_frozen (self, tmp_path: pathlib.Path) -> None:

		"""Attributes cannot be reassigned (the dicts themselves stay mutable)."""

		defs = _load(tmp_path, "notes: { kick: 36 }\n")

		with pytest.raises(dataclasses.FrozenInstanceError):
			defs.notes = {}  # type: ignore[misc]

	def test_error_names_file_section_and_name (self, tmp_path: pathlib.Path) -> None:

		"""Errors carry the file, section, and name — the cross-tool message shape."""

		with pytest.raises(ValueError, match=r"defs\.yaml: section 'notes': name 'Bad'"):
			_load(tmp_path, 'notes: { "Bad": 60 }\n')


class TestDefinitionsIntegration:

	"""Loaded tables drive the existing name-resolution surface."""

	def test_notes_merge_into_drum_note_map (self, tmp_path: pathlib.Path) -> None:

		"""A definitions name places a note through drum_note_map resolution."""

		defs = _load(tmp_path, SPEC_EXAMPLE)
		pattern = subsequence.pattern.Pattern(channel=0, length=4)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			drum_note_map = dict(defs.notes),
			default_grid = 16,
		)

		builder.hit("dawn_chorus_pheasant", beats=[0])

		assert pattern.steps[0].notes[0].pitch == 60

	def test_cc_names_resolve_via_cc_name_map (self, tmp_path: pathlib.Path) -> None:

		"""A definitions CC name resolves through cc_name_map."""

		defs = _load(tmp_path, SPEC_EXAMPLE)
		pattern = subsequence.pattern.Pattern(channel=0, length=4)

		builder = subsequence.pattern_builder.PatternBuilder(
			pattern = pattern,
			cycle = 0,
			cc_name_map = dict(defs.cc),
			default_grid = 16,
		)

		builder.cc("sampler_release", 64)

		assert len(pattern.cc_events) == 1
		assert pattern.cc_events[0].control == 21
		assert pattern.cc_events[0].value == 64
