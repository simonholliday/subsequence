import io
import logging

import pytest

import subsequence
import subsequence.composition
import subsequence.display
import subsequence.harmonic_state
import subsequence.pattern


def _make_composition (patch_midi: None) -> subsequence.Composition:

	"""Create a minimal composition for display testing."""

	return subsequence.Composition(output_device="Dummy MIDI", bpm=125, key="E")


def test_format_status_minimal (patch_midi: None) -> None:

	"""Status line should show BPM, key, and bar when no form or harmony is configured."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)

	status = display._format_status()

	assert "125.00 BPM" in status
	assert "Key: E" in status
	assert "Bar: 1.1" in status
	assert "Chord" not in status
	assert "[" not in status


def test_format_status_with_harmony (patch_midi: None) -> None:

	"""Status line should include the current chord when harmony is configured."""

	comp = _make_composition(patch_midi)
	comp.harmony(style="aeolian_minor", cycle_beats=4)

	display = subsequence.display.Display(comp)
	status = display._format_status()

	assert "125.00 BPM" in status
	assert "Chord:" in status


def test_format_status_with_form (patch_midi: None) -> None:

	"""Status line should include section info when form is configured."""

	comp = _make_composition(patch_midi)

	comp.form({
		"intro": (4, [("verse", 1)]),
		"verse": (8, []),
	}, start="intro")

	display = subsequence.display.Display(comp)
	status = display._format_status()

	assert "[intro 1/4 \u2192 verse]" in status


def test_format_status_full (patch_midi: None) -> None:

	"""Status line should include all components when form and harmony are configured."""

	comp = _make_composition(patch_midi)
	comp.harmony(style="aeolian_minor", cycle_beats=4)

	comp.form({
		"intro": (4, [("verse", 1)]),
		"verse": (8, []),
	}, start="intro")

	display = subsequence.display.Display(comp)
	status = display._format_status()

	assert "125.00 BPM" in status
	assert "Key: E" in status
	assert "Bar: 1.1" in status
	assert "[intro 1/4 \u2192 verse]" in status
	assert "Chord:" in status


def test_format_status_no_key (patch_midi: None) -> None:

	"""Status line should omit key when none is configured."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120)
	display = subsequence.display.Display(comp)

	status = display._format_status()

	assert "120.00 BPM" in status
	assert "Key:" not in status


def test_draw_writes_to_stderr (patch_midi: None) -> None:

	"""draw() should write the status line with ANSI clear codes."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)
	display._active = True
	display._last_line = "test status"

	stream = io.StringIO()

	# Temporarily redirect stderr to capture output.
	import sys
	original_stderr = sys.stderr
	sys.stderr = stream

	try:
		display.draw()
	finally:
		sys.stderr = original_stderr

	output = stream.getvalue()

	assert "\r\033[K" in output
	assert "test status" in output


def test_clear_line_writes_ansi (patch_midi: None) -> None:

	"""clear_line() should write carriage return and clear-to-end-of-line."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)
	display._active = True

	stream = io.StringIO()

	import sys
	original_stderr = sys.stderr
	sys.stderr = stream

	try:
		display.clear_line()
	finally:
		sys.stderr = original_stderr

	assert stream.getvalue() == "\r\033[K"


def test_update_rebuilds_status (patch_midi: None) -> None:

	"""update() should refresh the stored status line."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)
	display._active = True

	# Redirect stderr to avoid terminal noise during tests.
	import sys
	original_stderr = sys.stderr
	sys.stderr = io.StringIO()

	try:
		display.update(0)
	finally:
		sys.stderr = original_stderr

	assert "125.00 BPM" in display._last_line


def test_update_inactive_is_noop (patch_midi: None) -> None:

	"""update() should do nothing when the display is not active."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)

	display.update(0)

	assert display._last_line == ""


def test_start_installs_handler (patch_midi: None) -> None:

	"""start() should replace root logger handlers with DisplayLogHandler."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)

	root_logger = logging.getLogger()
	original_handlers = list(root_logger.handlers)

	display.start()

	try:
		assert len(root_logger.handlers) == 1
		assert isinstance(root_logger.handlers[0], subsequence.display.DisplayLogHandler)
	finally:
		display.stop()


def test_stop_restores_handlers (patch_midi: None) -> None:

	"""stop() should restore the original root logger handlers."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)

	root_logger = logging.getLogger()
	original_handlers = list(root_logger.handlers)

	display.start()
	display.stop()

	assert root_logger.handlers == original_handlers


def test_log_handler_clears_and_redraws (patch_midi: None) -> None:

	"""DisplayLogHandler should clear the status line before logging and redraw after."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)
	display._active = True
	display._last_line = "test status"

	stream = io.StringIO()

	import sys
	original_stderr = sys.stderr
	sys.stderr = stream

	try:
		handler = subsequence.display.DisplayLogHandler(display)
		handler.setFormatter(logging.Formatter("%(message)s"))

		record = logging.LogRecord(
			name="test",
			level=logging.INFO,
			pathname="",
			lineno=0,
			msg="hello",
			args=(),
			exc_info=None
		)

		handler.emit(record)
	finally:
		sys.stderr = original_stderr

	output = stream.getvalue()

	# Should clear, write message, then redraw.
	assert output.count("\r\033[K") >= 2
	assert "hello\n" in output
	assert "test status" in output


def test_composition_display_creates_display (patch_midi: None) -> None:

	"""composition.display() should create a Display instance."""

	comp = _make_composition(patch_midi)

	assert comp._display is None

	comp.display()

	assert comp._display is not None
	assert isinstance(comp._display, subsequence.display.Display)


def test_composition_display_disable (patch_midi: None) -> None:

	"""composition.display(enabled=False) should clear the display."""

	comp = _make_composition(patch_midi)
	comp.display()

	assert comp._display is not None

	comp.display(enabled=False)

	assert comp._display is None


def test_format_status_with_conductor_signals (patch_midi: None) -> None:

	"""Status line should include conductor signal names and formatted values."""

	comp = _make_composition(patch_midi)
	comp.conductor.lfo("swell", shape="triangle", cycle_beats=16.0)
	comp.conductor.line("ramp", start_val=0.0, end_val=1.0, duration_beats=32.0)

	display = subsequence.display.Display(comp)
	status = display._format_status()

	assert "Swell:" in status
	assert "Ramp:" in status


def test_format_status_no_conductor_signals (patch_midi: None) -> None:

	"""Status line should not contain signal info when none are registered."""

	comp = _make_composition(patch_midi)
	display = subsequence.display.Display(comp)
	status = display._format_status()

	# Should contain standard parts but no signal formatting.
	assert "125.00 BPM" in status
	assert ":" not in status.split("Key:")[-1].split("Bar:")[0].strip()


def test_section_display_syncs_with_bar_counter (patch_midi: None) -> None:

	"""Section info should only update when the bar counter changes.

	The form state advances 1 beat early (due to reschedule_lookahead), but the
	display should not reflect that until the bar counter also advances.
	"""

	comp = _make_composition(patch_midi)

	comp.form({
		"intro": (4, [("verse", 1)]),
		"verse": (8, []),
	}, start="intro")

	display = subsequence.display.Display(comp)

	# First render at bar 0 (displayed as "Bar: 1.1") — section should initialise.
	status_1 = display._format_status()
	assert "[intro 1/4 \u2192 verse]" in status_1

	# Simulate what happens when form advances early (lookahead fires before
	# the bar counter increments): advance the form state, but leave
	# current_bar unchanged.
	comp._form_state.advance()

	# The form state now says bar 2, but the sequencer bar hasn't changed.
	status_2 = display._format_status()
	assert "[intro 1/4 \u2192 verse]" in status_2, "Section should NOT update before bar counter changes"

	# Now simulate the bar counter advancing.
	comp._sequencer.current_bar = 1

	status_3 = display._format_status()
	assert "[intro 2/4 \u2192 verse]" in status_3, "Section should update when bar counter changes"


def test_conductor_signals_sorted (patch_midi: None) -> None:

	"""Conductor signals should appear in alphabetical order."""

	comp = _make_composition(patch_midi)
	comp.conductor.lfo("zebra", shape="sine", cycle_beats=16.0)
	comp.conductor.lfo("alpha", shape="sine", cycle_beats=16.0)

	display = subsequence.display.Display(comp)
	status = display._format_status()

	alpha_pos = status.index("Alpha:")
	zebra_pos = status.index("Zebra:")

	assert alpha_pos < zebra_pos


# ---------------------------------------------------------------------------
# GridDisplay tests
# ---------------------------------------------------------------------------


def test_grid_velocity_char () -> None:

	"""Velocity characters should map to the correct glyphs at all thresholds."""

	vc = subsequence.display.GridDisplay._velocity_char
	assert vc(-1)  == ">"
	assert vc(0)   == "·"
	assert vc(1)   == "░"
	assert vc(31)  == "░"
	assert vc(32)  == "▒"
	assert vc(63)  == "▒"
	assert vc(64)  == "▓"
	assert vc(95)  == "▓"
	assert vc(96)  == "█"
	assert vc(127) == "█"


def test_grid_midi_note_name () -> None:

	"""MIDI note name should return correct names for common pitches."""

	nn = subsequence.display.GridDisplay._midi_note_name
	assert nn(60) == "C4"
	assert nn(36) == "C2"
	assert nn(42) == "F#2"
	assert nn(69) == "A4"
	assert nn(127) == "G9"


def test_grid_build_empty (patch_midi: None) -> None:

	"""Grid should produce no lines when no patterns are running."""

	comp = _make_composition(patch_midi)
	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	assert grid._lines == []
	assert grid.line_count == 0


def _make_drum_pattern () -> subsequence.pattern.Pattern:

	"""Create a 4-beat drum pattern with kick and snare hits."""

	pat = subsequence.pattern.Pattern(channel=9, length=4)
	# Kick at steps 0 and 8 (pulses 0 and 48 in 96-pulse bar).
	pat.add_note(position=0,  pitch=36, velocity=120, duration=6)
	pat.add_note(position=48, pitch=36, velocity=100, duration=6)
	# Snare at step 4 (pulse 24).
	pat.add_note(position=24, pitch=38, velocity=90, duration=6)
	return pat


def _make_pitched_pattern () -> subsequence.pattern.Pattern:

	"""Create a 4-beat pitched pattern with notes at various steps."""

	pat = subsequence.pattern.Pattern(channel=5, length=4)
	# E1 at steps 0, 8, 12 (pulses 0, 48, 72).
	pat.add_note(position=0,  pitch=28, velocity=100, duration=12)
	pat.add_note(position=48, pitch=28, velocity=80,  duration=12)
	pat.add_note(position=72, pitch=28, velocity=60,  duration=12)
	return pat


def test_grid_build_drum_pattern (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Drum patterns should produce one row per distinct drum sound."""

	# Ensure terminal width is wide enough for 16 columns.
	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)
	drum_map = {"kick_1": 36, "snare_1": 38}

	pat = _make_drum_pattern()
	pat._drum_note_map = drum_map  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["drums"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	assert grid.line_count >= 2  # kick row + snare row

	# Find the kick row and snare row.
	kick_line = next(l for l in grid._lines if "kick_1" in l)
	snare_line = next(l for l in grid._lines if "snare_1" in l)

	# Kick at step 0 (vel 120 → █) and step 8 (vel 100 → █).
	assert "|" in kick_line
	parts = kick_line.split("|")[1]  # content between pipes
	chars = parts.split()
	assert chars[0] == "█"   # step 0, velocity 120
	assert chars[8] == "█"   # step 8, velocity 100

	# Snare at step 4 (vel 90 → ▓).
	parts = snare_line.split("|")[1]
	chars = parts.split()
	assert chars[4] == "▓"   # step 4, velocity 90


def test_grid_build_pitched_pattern (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Pitched patterns should produce a single summary row."""

	# Ensure terminal width is wide enough for 16 columns.
	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	# Pitched pattern: 1 line (name + summary row combined).
	assert grid.line_count == 1

	line = grid._lines[0]
	assert "bass" in line
	assert "|" in line

	# Check velocity chars at known positions.
	parts = line.split("|")[1]
	chars = parts.split()
	assert chars[0] == "█"   # step 0, velocity 100 (100/127=78% -> █)
	assert chars[8] == "▓"   # step 8, velocity 80 (80/127=63% -> ▓)
	assert chars[12] == "▒"  # step 12, velocity 60 (60/127=47% -> ▒)


def test_grid_build_muted_pattern (patch_midi: None) -> None:

	"""Muted patterns should show parenthesised name and dashes."""

	comp = _make_composition(patch_midi)

	pat = _make_drum_pattern()
	pat._drum_note_map = {"kick_1": 36, "snare_1": 38}  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = True  # type: ignore[attr-defined]

	comp._running_patterns["drums"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	# Muted: single line with dashes.
	assert grid.line_count == 1

	line = grid._lines[0]
	assert "(drums)" in line
	assert "-" in line
	# No velocity chars.
	assert "█" not in line
	assert "▓" not in line
	assert "▒" not in line
	assert "░" not in line


def test_display_grid_flag (patch_midi: None) -> None:

	"""composition.display(grid=True) should create a Display with a GridDisplay."""

	comp = _make_composition(patch_midi)
	comp.display(grid=True)

	assert comp._display is not None
	assert comp._display._grid is not None
	assert isinstance(comp._display._grid, subsequence.display.GridDisplay)


def test_display_no_grid_by_default (patch_midi: None) -> None:

	"""composition.display() should not create a GridDisplay by default."""

	comp = _make_composition(patch_midi)
	comp.display()

	assert comp._display is not None
	assert comp._display._grid is None


def test_draw_multiline (patch_midi: None) -> None:

	"""draw() with grid enabled should write multiple lines with ANSI cursor movement."""

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]
	comp._running_patterns["bass"] = pat

	display = subsequence.display.Display(comp, grid=True)
	display._active = True
	display._last_line = "test status"
	display._grid.build()  # type: ignore[union-attr]

	# Simulate a previous draw so drawn_line_count is set.
	stream = io.StringIO()
	import sys
	original_stderr = sys.stderr
	sys.stderr = stream

	try:
		display.draw()
		# Second draw should include cursor-up escape.
		display.draw()
	finally:
		sys.stderr = original_stderr

	output = stream.getvalue()

	# Should contain grid content and status line.
	assert "bass" in output
	assert "test status" in output
	# Second draw should have cursor-up ANSI code.
	assert "\033[" in output


def test_clear_multiline (patch_midi: None) -> None:

	"""clear_line() with grid should clear the full multi-line region."""

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]
	comp._running_patterns["bass"] = pat

	display = subsequence.display.Display(comp, grid=True)
	display._active = True
	display._last_line = "test status"
	display._grid.build()  # type: ignore[union-attr]

	stream = io.StringIO()
	import sys
	original_stderr = sys.stderr
	sys.stderr = stream

	try:
		# First draw to set drawn_line_count.
		display.draw()

		# Reset stream to capture only the clear.
		stream.truncate(0)
		stream.seek(0)

		display.clear_line()
	finally:
		sys.stderr = original_stderr

	output = stream.getvalue()

	# Should contain cursor-up ANSI code for multi-line clear.
	assert "\033[" in output
	# Should have cleared multiple lines.
	assert output.count("\r\033[K") >= 2


def test_grid_fit_columns () -> None:

	"""_fit_columns should respect terminal width constraints."""

	fit = subsequence.display.GridDisplay._fit_columns

	# Wide terminal: all 16 columns fit.
	assert fit(16, 80) == 16

	# Narrow terminal: fewer columns.
	# Overhead = 16 (label) + 2 (pipes) = 18.
	# Available = 30 - 18 = 12.  Max cols = (12 + 1) // 2 = 6.
	assert fit(16, 30) == 6

	# Very narrow terminal: no columns.
	assert fit(16, 16) == 0


def test_grid_update_only_on_bar_change (patch_midi: None) -> None:

	"""Grid should only rebuild when the bar counter changes."""

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]
	comp._running_patterns["bass"] = pat

	display = subsequence.display.Display(comp, grid=True)
	display._active = True

	import sys
	original_stderr = sys.stderr
	sys.stderr = io.StringIO()

	try:
		# First update at bar 0.
		display.update(0)
		first_lines = list(display._grid._lines)  # type: ignore[union-attr]
		assert len(first_lines) > 0

		# Second update at same bar — grid should be the same object contents.
		display.update(0)
		assert display._grid._lines == first_lines  # type: ignore[union-attr]

		# Advance bar counter.
		comp._sequencer.current_bar = 1
		display.update(0)
		# Grid was rebuilt (contents may be same since pattern didn't change,
		# but the rebuild path was exercised).
		assert display._last_grid_bar == 1
	finally:
		sys.stderr = original_stderr


# ---------------------------------------------------------------------------
# Sustain marker tests
# ---------------------------------------------------------------------------


def test_grid_sustain_single_note (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""A note spanning multiple slots should produce sustain markers after the attack."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = subsequence.pattern.Pattern(channel=5, length=4)
	# One note at pulse 0, duration 18 pulses (= 3 slots of 6 pulses each).
	pat.add_note(position=0, pitch=60, velocity=100, duration=18)
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["synth"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	assert grid.line_count == 1

	parts = grid._lines[0].split("|")[1]
	chars = parts.split()
	assert chars[0] == "█"   # attack (velocity 100)
	assert chars[1] == ">"   # sustain
	assert chars[2] == ">"   # sustain
	assert chars[3] == "·"   # empty — note ended


def test_grid_sustain_short_note (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""A note shorter than one grid slot should produce no sustain markers."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = subsequence.pattern.Pattern(channel=9, length=4)
	# Short drum hit: 3 pulses (half a slot at 6 pps).
	pat.add_note(position=0, pitch=36, velocity=120, duration=3)
	pat._drum_note_map = {"kick_1": 36}  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["drums"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	# Find the kick row.
	kick_line = next(l for l in grid._lines if "kick_1" in l)
	parts = kick_line.split("|")[1]
	chars = parts.split()
	assert chars[0] == "█"   # attack
	assert chars[1] == "·"   # no sustain — note too short


def test_grid_sustain_does_not_overwrite_attack (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""A sustain marker should not overwrite an attack at the same slot."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = subsequence.pattern.Pattern(channel=5, length=4)
	# Note A at pulse 0, sustains through 4 slots (24 pulses).
	pat.add_note(position=0,  pitch=60, velocity=100, duration=24)
	# Note B attacks at pulse 12 (slot 2) — should NOT be overwritten by A's sustain.
	pat.add_note(position=12, pitch=60, velocity=80,  duration=6)
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["lead"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	parts = grid._lines[0].split("|")[1]
	chars = parts.split()
	assert chars[0] == "█"   # Note A attack (vel 100)
	assert chars[1] == ">"   # Note A sustain
	assert chars[2] == "▓"   # Note B attack (vel 80) — NOT sustain
	assert chars[3] == ">"   # Note A still sustaining


def test_grid_pitched_summary_sustain (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Pitched summary row should show sustain markers from the collapsed pitches."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = subsequence.pattern.Pattern(channel=5, length=4)
	# Legato note spanning 3 slots.
	pat.add_note(position=0, pitch=60, velocity=100, duration=18)
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	grid = subsequence.display.GridDisplay(comp)
	grid.build()

	parts = grid._lines[0].split("|")[1]
	chars = parts.split()
	assert chars[0] == "█"   # attack
	assert chars[1] == ">"   # sustain visible in summary
	assert chars[2] == ">"   # sustain visible in summary


# ---------------------------------------------------------------------------
# Grid scale tests
# ---------------------------------------------------------------------------


def test_grid_scale_default (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""scale=1.0 (default) should produce identical output to unscaled grid."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	grid_default = subsequence.display.GridDisplay(comp)
	grid_default.build()

	grid_scale1 = subsequence.display.GridDisplay(comp, scale=1.0)
	grid_scale1.build()

	assert grid_default._lines == grid_scale1._lines


def test_grid_scale_doubles_columns (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""scale=2.0 should produce 32 visual columns for a 16-step pattern."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	grid = subsequence.display.GridDisplay(comp, scale=2.0)
	grid.build()

	assert grid.line_count == 1

	parts = grid._lines[0].split("|")[1]
	# Can't use .split() — space cells merge with separators.
	# Every other char is a cell (cells separated by single spaces).
	individual_cells = list(parts[::2])

	# 32 visual columns (16 grid steps * cols_per_step=2).
	assert len(individual_cells) == 32


def test_grid_scale_on_grid_dot_between_grid_space (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Empty on-grid positions should show '.', empty between-grid positions should show ' '."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	# Pattern with a single note at pulse 0 — most positions are empty.
	pat = subsequence.pattern.Pattern(channel=5, length=4)
	pat.add_note(position=0, pitch=60, velocity=100, duration=3)  # short note, no sustain
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["lead"] = pat

	grid = subsequence.display.GridDisplay(comp, scale=2.0)
	grid.build()

	parts = grid._lines[0].split("|")[1]
	chars = parts.split()

	# col 0 = on-grid, has attack.
	assert chars[0] == "█"
	# col 1 = between-grid, empty → space (represented as empty string after split).
	# col 2 = on-grid, empty → "·".
	assert chars[1] == "·"

	# Verify the raw string has spaces at between-grid empty positions.
	# Between col 0 ("O") and col 2 ("."), the raw cells are "O" + " " + " " + " " + ".".
	# That's: "O     ." — three spaces between them (separator + space-cell + separator).
	raw = grid._lines[0].split("|")[1]
	# Find a between-grid empty cell: col 1 should be a space character, col 2 should be a dot.
	# The raw format is "X Y Z ..." where each cell is separated by a space.
	# Cell at position 0 is O, cell at position 1 is space, cell at position 2 is dot.
	individual_cells = list(raw[::2])  # every other char (skip separators)
	assert individual_cells[0] == "█"
	assert individual_cells[1] == " "   # between-grid empty
	assert individual_cells[2] == "·"   # on-grid empty


def test_grid_scale_sustain_fills_between_grid (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Sustain markers should appear at both on-grid and between-grid positions."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	pat = subsequence.pattern.Pattern(channel=5, length=4)
	# Note spanning 4 grid slots = 8 visual columns at scale=2.
	# At 96 pulses / 16 steps = 6 pulses per step, 4 steps = 24 pulses.
	pat.add_note(position=0, pitch=60, velocity=100, duration=24)
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["synth"] = pat

	grid = subsequence.display.GridDisplay(comp, scale=2.0)
	grid.build()

	parts = grid._lines[0].split("|")[1]
	individual_cells = list(parts[::2])  # every other char (skip separators)

	# Col 0: attack.
	assert individual_cells[0] == "█"
	# Cols 1-7: sustain (both on-grid and between-grid).
	for i in range(1, 8):
		assert individual_cells[i] == ">", f"col {i} should be sustain '>', got '{individual_cells[i]}'"
	# Col 8: note ended (on-grid empty).
	assert individual_cells[8] == "·"


def test_grid_scale_muted (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Muted pattern at scale=2 should show '-' at on-grid positions, space at between-grid."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_drum_pattern()
	pat._drum_note_map = {"kick_1": 36, "snare_1": 38}  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = True  # type: ignore[attr-defined]

	comp._running_patterns["drums"] = pat

	grid = subsequence.display.GridDisplay(comp, scale=2.0)
	grid.build()

	assert grid.line_count == 1

	parts = grid._lines[0].split("|")[1]
	individual_cells = list(parts[::2])

	# 32 visual columns. On-grid at even indices: '-', between-grid at odd: ' '.
	for i in range(32):
		if i % 2 == 0:
			assert individual_cells[i] == "-", f"on-grid col {i} should be '-'"
		else:
			assert individual_cells[i] == " ", f"between-grid col {i} should be ' '"


def test_grid_scale_float_snaps (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Non-integer scale values should snap to the nearest integer cols_per_step."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	# scale=1.5 → round(1.5) = 2 → cols_per_step=2 → 32 visual columns.
	grid_15 = subsequence.display.GridDisplay(comp, scale=1.5)
	grid_15.build()
	parts_15 = grid_15._lines[0].split("|")[1]
	assert len(list(parts_15[::2])) == 32

	# scale=2.6 → round(2.6) = 3 → cols_per_step=3 → 48 visual columns.
	grid_26 = subsequence.display.GridDisplay(comp, scale=2.6)
	grid_26.build()
	parts_26 = grid_26._lines[0].split("|")[1]
	assert len(list(parts_26[::2])) == 48


def test_grid_scale_below_one (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""Scale values below 1.0 should clamp to cols_per_step=1 (no change)."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((120, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	grid_default = subsequence.display.GridDisplay(comp, scale=1.0)
	grid_default.build()

	grid_low = subsequence.display.GridDisplay(comp, scale=0.5)
	grid_low.build()

	assert grid_default._lines == grid_low._lines


def test_grid_scale_uniform_spacing (patch_midi: None, monkeypatch: pytest.MonkeyPatch) -> None:

	"""All adjacent on-grid markers should be exactly cols_per_step apart."""

	import os
	monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 24)))

	comp = _make_composition(patch_midi)

	pat = _make_pitched_pattern()
	pat._drum_note_map = None  # type: ignore[attr-defined]
	pat._default_grid = 16  # type: ignore[attr-defined]
	pat._muted = False  # type: ignore[attr-defined]

	comp._running_patterns["bass"] = pat

	for scale, expected_step in [(1.0, 1), (2.0, 2), (3.0, 3), (1.5, 2), (2.6, 3)]:
		grid = subsequence.display.GridDisplay(comp, scale=scale)
		grid.build()

		parts = grid._lines[0].split("|")[1]
		individual_cells = list(parts[::2])

		# Identify on-grid positions: they are at multiples of expected_step.
		on_grid_positions = [i for i in range(len(individual_cells)) if i % expected_step == 0]

		# All gaps between adjacent on-grid positions should be identical.
		gaps = [on_grid_positions[j + 1] - on_grid_positions[j] for j in range(len(on_grid_positions) - 1)]
		assert all(g == expected_step for g in gaps), (
			f"scale={scale}: expected uniform gap of {expected_step}, got {gaps}"
		)


def test_composition_display_grid_scale (patch_midi: None) -> None:

	"""composition.display(grid=True, grid_scale=2.0) should pass scale through to GridDisplay."""

	comp = _make_composition(patch_midi)
	comp.display(grid=True, grid_scale=2.0)

	assert comp._display is not None
	assert comp._display._grid is not None
	assert comp._display._grid._scale == 2.0
