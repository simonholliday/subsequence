"""What the status line says, and the width it fits in (#3051, #3052).

M22 of the 2026-09-19 review found three things.  Two were in the web dashboard,
its websockets floor and the chord it showed, and went with it when it was
retired in favour of the terminal display (#3052).  The third is here.

**The status line.** Nothing limited it to the terminal's width. A piece with
a key, a form, a chord and three conductor signals gave **132 characters in an
80-column terminal** - and the redraw assumes one line, so every refresh left
a stale copy and the display walked down the screen.

**The signals.** They came last on the status line, so fitting it dropped them
first, and a piece with more than a few never showed them all.  Since #3052 they
have lines of their own above it, wrapped to the terminal's width.
"""

import shutil
import typing

import pytest

import subsequence
import subsequence.display


# ---------------------------------------------------------------------------
# The width it fits in
# ---------------------------------------------------------------------------

def _display (
	monkeypatch: pytest.MonkeyPatch,
	columns: int,
	section_name: str = "intro",
	signals: int = 3,
) -> subsequence.display.Display:

	monkeypatch.setattr(
		shutil, "get_terminal_size",
		lambda fallback = (80, 24): shutil.os.terminal_size((columns, 24)),
	)

	composition = subsequence.Composition(bpm = 128, key = "Bb", scale = "mixolydian", seed = 5)
	composition.harmony(style = "pop_major", cycle_beats = 4)
	composition.form([(section_name, 4), ("verse", 8)])

	@composition.pattern(channel = 1, beats = 4)
	def pad (p: typing.Any) -> None:
		p.note(beat = 0, pitch = 60, velocity = 90)

	for name in ("brightness", "density", "energy")[:signals]:
		composition.conductor.lfo(name, cycle_beats = 16)

	composition._open_output_devices()
	composition.display()

	display = composition._display
	assert display is not None

	return display


def _status_line (monkeypatch: pytest.MonkeyPatch, columns: int, section_name: str = "intro", signals: int = 3) -> str:

	return _display(monkeypatch, columns, section_name, signals)._format_status()


SIGNALS = ("Brightness:", "Density:", "Energy:")


@pytest.mark.parametrize("columns", [40, 60, 80, 100, 200])
def test_the_status_line_fits_the_terminal (
	columns: int,
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""The finding: 132 characters in 80 columns, wrapping on every redraw."""

	line = _status_line(monkeypatch, columns)

	assert len(line) <= columns, f"{len(line)} characters in {columns} columns: {line!r}"


def test_a_narrow_terminal_keeps_the_tempo_and_the_bar (
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""Fitting is easy if you return nothing; it has to keep what matters."""

	line = _status_line(monkeypatch, 40)

	assert "BPM" in line, line
	assert line.strip(), "the status line came back empty"


@pytest.mark.parametrize("columns", [1, 4, 8])
def test_a_terminal_narrower_than_one_part_still_says_something (
	columns: int,
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""The last part is never dropped, however narrow it gets.

	Dropping while anything is left empties the line entirely at a width
	below the first part — and an empty status line reads as a crashed
	display rather than a narrow one.
	"""

	line = _status_line(monkeypatch, columns)

	assert line, f"a {columns}-column terminal produced nothing at all"
	assert len(line) <= columns


def test_the_signals_have_lines_of_their_own (
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""The status line keeps the chord, and the signals go above it, every one (#3052).

	At 80 columns the status line used to drop two of three signals to keep the chord.
	"""

	display = _display(monkeypatch, 80)
	status = display._format_status()
	signals = display._format_signals()

	assert "Chord:" in status and "…" not in status, status
	assert not any(name in status for name in SIGNALS), f"a signal is still on the status line: {status!r}"
	assert all(name in "  ".join(signals) for name in SIGNALS), signals
	assert all(len(line) <= 80 for line in signals), signals


@pytest.mark.parametrize("columns", [20, 40])
def test_every_signal_shows_in_a_narrow_terminal (
	columns: int,
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""Too many for one line, they wrap; none is dropped and none runs past the edge."""

	signals = _display(monkeypatch, columns)._format_signals()

	assert all(name in "  ".join(signals) for name in SIGNALS), signals
	assert all(len(line) <= columns for line in signals), signals
	assert len(signals) > 1, f"three signals fitted one {columns}-column line: {signals}"


def test_a_signal_wider_than_the_terminal_is_cut_rather_than_run_past_the_edge (
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	""""Brightness: 0.50" is 16 characters: in 10 columns it is cut, marked as cut, and still gets its line."""

	signals = _display(monkeypatch, 10)._format_signals()

	assert len(signals) == 3, signals
	assert all(len(line) <= 10 for line in signals), signals
	assert signals[0].endswith("…"), signals


def test_a_wide_terminal_keeps_everything (
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""The control. Nothing is dropped when there is room for it, and the signals share one line."""

	display = _display(monkeypatch, 200)
	line = display._format_status()

	assert "BPM" in line
	assert "Chord:" in line
	assert "…" not in line
	assert len(display._format_signals()) == 1


def test_nothing_is_cut_when_it_already_fits (
	monkeypatch: pytest.MonkeyPatch,
	patch_midi: None,
) -> None:

	"""The documented example is 54 characters and must come through whole."""

	line = _status_line(monkeypatch, 120, signals = 0)

	assert "…" not in line, line
	assert "Chord:" in line
