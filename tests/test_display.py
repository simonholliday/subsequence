import io
import logging

import pytest

import subsequence
import subsequence.composition
import subsequence.display
import subsequence.harmonic_state


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

	assert "[intro 1/4]" in status


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
	assert "[intro 1/4]" in status
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
