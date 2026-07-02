"""Regression tests for the Tier 1 low-severity fixes (2026-07 wave).

Covers the behavioural fixes applied directly by the review follow-up:
harmony() style preservation, performer-mute ownership, partial-build
clearing, set_bpm validation order, the web dashboard port substitution,
form navigation error context, and the ChordPattern removal.
"""

import random
import typing

import pytest

import subsequence
import subsequence.form_state
import subsequence.forms
import subsequence.harmony
import subsequence.sequencer


def test_parameter_only_harmony_recall_keeps_style (patch_midi: None) -> None:

	"""harmony(gravity=...) after harmony(style=...) keeps the configured style.

	A parameter-only re-call used to fall back to functional_major,
	silently replacing the configured graph.
	"""

	comp = subsequence.Composition(bpm=120, key="A")
	comp.harmony(style="aeolian_minor")

	comp.harmony(gravity=0.2)

	assert comp._harmony_style == "aeolian_minor"


def test_first_harmony_call_still_defaults_to_functional_major (patch_midi: None) -> None:

	"""With no style ever configured, a bare harmony() call keeps today's default."""

	comp = subsequence.Composition(bpm=120, key="C")
	comp.harmony(gravity=0.5)

	assert comp._harmony_style == "functional_major"


def test_performer_mute_claims_ownership_from_transition (patch_midi: None) -> None:

	"""mute() during a transition approach window survives the boundary.

	The performer's mute removes the name from _transition_muted, so the
	section-boundary restore pass no longer silently unmutes it.
	"""

	comp = subsequence.Composition(bpm=120)

	class _Stub:
		_muted = False

	comp._running_patterns["bass"] = _Stub()
	comp._transition_muted.add("bass")

	comp.mute("bass")

	assert "bass" not in comp._transition_muted
	assert comp._running_patterns["bass"]._muted is True

	# The boundary restore pass only touches names still in the set —
	# simulate it directly and confirm the performer's mute holds.
	for name in comp._transition_muted:
		comp._running_patterns[name]._muted = False
	comp._transition_muted.clear()

	assert comp._running_patterns["bass"]._muted is True


def test_performer_unmute_claims_ownership_from_transition (patch_midi: None) -> None:

	"""unmute() also removes the transition machinery's claim on the pattern."""

	comp = subsequence.Composition(bpm=120)

	class _Stub:
		_muted = True

	comp._running_patterns["lead"] = _Stub()
	comp._transition_muted.add("lead")

	comp.unmute("lead")

	assert "lead" not in comp._transition_muted
	assert comp._running_patterns["lead"]._muted is False


def test_failing_builder_leaves_pattern_silent (patch_midi: None) -> None:

	"""A builder that raises mid-build discards what it already placed.

	The log promises the pattern "will be silent this cycle" — events
	placed before the exception used to play anyway.
	"""

	comp = subsequence.Composition(bpm=120, seed=1)

	@comp.pattern(channel=1, beats=4)
	def partial (p: typing.Any) -> None:

		p.note(60, beat=0.0, duration=0.5)
		raise RuntimeError("halfway through the build")

	pending = comp._pending_patterns[0]
	pattern = comp._build_pattern_from_pending(pending)

	pattern._rebuild()

	assert pattern.steps == {}
	assert pattern.cc_events == []
	assert pattern.raw_note_events == []


def test_set_bpm_validates_before_link_proposal (patch_midi: None) -> None:

	"""set_bpm(0) raises without proposing the tempo to the Link session."""

	seq = subsequence.sequencer.Sequencer(initial_bpm=120)

	class _LinkSpy:

		def __init__ (self) -> None:

			self.proposed: typing.List[float] = []

		def request_tempo (self, bpm: float) -> None:

			self.proposed.append(bpm)

	spy = _LinkSpy()
	seq._link_clock = spy
	seq.running = True

	with pytest.raises(ValueError):
		seq.set_bpm(0)

	assert spy.proposed == []


def test_dashboard_page_carries_ws_port_token () -> None:

	"""index.html uses the __WS_PORT__ token web_ui.py substitutes at serve time.

	The page hardcoding 8765 made WebUI(ws_port=...) a dashboard that
	could never connect; the raw file must keep a regex fallback so it
	still works opened directly from disk.
	"""

	import os
	import subsequence.web_ui

	page_path = os.path.join(os.path.dirname(subsequence.web_ui.__file__), "assets", "web", "index.html")
	page = open(page_path, encoding="utf-8").read()

	assert "__WS_PORT__" in page
	assert "8765" in page		# the no-server fallback

	substituted = page.replace("__WS_PORT__", "9999")
	assert "9999" in substituted


def test_queue_next_error_names_the_operation () -> None:

	"""An unknown section error says which navigation call failed."""

	state = subsequence.form_state.FormState([subsequence.forms.Section("verse", 4)])

	with pytest.raises(ValueError) as exc:
		state.queue_next("nope")

	assert "queue_next" in str(exc.value)
	assert "nope" in str(exc.value)


def test_chord_pattern_class_removed () -> None:

	"""ChordPattern (zero callers, zero tests) is gone; the helpers remain."""

	assert not hasattr(subsequence.harmony, "ChordPattern")
	assert callable(subsequence.harmony.diatonic_chords)
	assert callable(subsequence.harmony.diatonic_chord_sequence)
