"""Live terminal dashboard for composition playback.

Provides a persistent status line showing the current bar, section, chord, BPM,
and key.  Optionally renders an ASCII grid visualisation of all running patterns
above the status line, showing which steps have notes and at what velocity.

Log messages scroll above the dashboard without disruption.

Enable it with a single call before ``play()``:

```python
composition.display()          # status line only
composition.display(grid=True) # status line + pattern grid
composition.play()
```

The status line updates every beat and looks like::

	125 BPM  Key: E  Bar: 17  [chorus 1/8]  Chord: Em7

The grid (when enabled) updates every bar and looks like::

	drums
	  kick_2      |X . . . X . . . X . . . X . . .|
	  snare_1     |. . . . X . . . . . . . X . . .|
	bass          |X . . X . . X . X . . . X . . .|
"""

import logging
import shutil
import sys
import typing

import subsequence.constants

if typing.TYPE_CHECKING:
	from subsequence.composition import Composition


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_MAX_GRID_COLUMNS = 32
_LABEL_WIDTH = 12
_MIN_TERMINAL_WIDTH = 40
_SUSTAIN = -1


class GridDisplay:

	"""Multi-line ASCII grid visualisation of running pattern steps.

	Renders one block per pattern showing which grid steps have notes and at
	what velocity.  Drum patterns (those with a ``drum_note_map``) show one
	row per drum sound; pitched patterns show a single summary row.

	Not used directly — instantiated by ``Display`` when ``grid=True``.
	"""

	def __init__ (self, composition: "Composition") -> None:

		"""Store composition reference for reading pattern state.

		Parameters:
			composition: The ``Composition`` instance to read running
				patterns from.
		"""

		self._composition = composition
		self._lines: typing.List[str] = []

	@property
	def line_count (self) -> int:

		"""Number of terminal lines the grid currently occupies."""

		return len(self._lines)

	# ------------------------------------------------------------------
	# Static helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _velocity_char (velocity: int) -> str:

		"""Map a MIDI velocity (0-127) to a single ASCII character.

		Returns:
			``"-"`` for sustain (note still sounding), ``"."`` for
			no hit / ghost (0-40), ``"o"`` for soft (41-80), ``"O"`` for
			medium (81-110), ``"X"`` for loud (111-127).
		"""

		if velocity == _SUSTAIN:
			return "-"
		if velocity <= 40:
			return "."
		if velocity <= 80:
			return "o"
		if velocity <= 110:
			return "O"
		return "X"

	@staticmethod
	def _midi_note_name (pitch: int) -> str:

		"""Convert a MIDI note number to a human-readable name.

		Examples: 60 → ``"C4"``, 42 → ``"F#2"``, 36 → ``"C1"``.
		"""

		octave = (pitch // 12) - 1
		note = _NOTE_NAMES[pitch % 12]
		return f"{note}{octave}"

	# ------------------------------------------------------------------
	# Grid building
	# ------------------------------------------------------------------

	def build (self) -> None:

		"""Rebuild grid lines from the current state of all running patterns."""

		lines: typing.List[str] = []
		term_width = shutil.get_terminal_size(fallback=(80, 24)).columns

		if term_width < _MIN_TERMINAL_WIDTH:
			self._lines = []
			return

		for name, pattern in self._composition._running_patterns.items():

			grid_size = min(getattr(pattern, "_default_grid", 16), _MAX_GRID_COLUMNS)
			muted = getattr(pattern, "_muted", False)
			drum_map: typing.Optional[typing.Dict[str, int]] = getattr(pattern, "_drum_note_map", None)

			if muted:
				lines.extend(self._render_muted(name, grid_size, term_width))
			elif drum_map:
				lines.extend(self._render_drum_pattern(name, pattern, drum_map, grid_size, term_width))
			else:
				lines.extend(self._render_pitched_pattern(name, pattern, grid_size, term_width))

		self._lines = lines

	# ------------------------------------------------------------------
	# Rendering helpers
	# ------------------------------------------------------------------

	def _render_muted (self, name: str, grid_size: int, term_width: int) -> typing.List[str]:

		"""Render a muted pattern as a single row of dashes."""

		display_cols = self._fit_columns(grid_size, term_width)
		cells = " ".join(["-"] * display_cols)
		label = f"({name})"[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)
		return [f"  {label}|{cells}|"]

	def _render_drum_pattern (
		self,
		name: str,
		pattern: typing.Any,
		drum_map: typing.Dict[str, int],
		grid_size: int,
		term_width: int,
	) -> typing.List[str]:

		"""Render a drum pattern with one row per distinct drum sound."""

		lines: typing.List[str] = []
		display_cols = self._fit_columns(grid_size, term_width)

		# Build reverse map: {midi_note: drum_name}.
		reverse_map: typing.Dict[int, str] = {}
		for drum_name, midi_note in drum_map.items():
			if midi_note not in reverse_map:
				reverse_map[midi_note] = drum_name

		# Discover which pitches are present in the pattern.
		velocity_grid = self._build_velocity_grid(pattern, grid_size, display_cols)

		if not velocity_grid:
			# Pattern has no notes — just show the header.
			lines.append(f"  {name}")
			return lines

		# Sort rows by MIDI pitch (lowest first — kick before hi-hat).
		lines.append(f"  {name}")

		for pitch in sorted(velocity_grid):
			label_text = reverse_map.get(pitch, self._midi_note_name(pitch))
			label = f"  {label_text[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)}"
			cells = " ".join(self._velocity_char(v) for v in velocity_grid[pitch][:display_cols])
			lines.append(f"{label}|{cells}|")

		return lines

	def _render_pitched_pattern (
		self,
		name: str,
		pattern: typing.Any,
		grid_size: int,
		term_width: int,
	) -> typing.List[str]:

		"""Render a pitched pattern as a single summary row."""

		display_cols = self._fit_columns(grid_size, term_width)

		# Collapse all pitches into a single row using max velocity per slot.
		velocity_grid = self._build_velocity_grid(pattern, grid_size, display_cols)

		summary = [0] * display_cols
		for pitch_velocities in velocity_grid.values():
			for i, vel in enumerate(pitch_velocities[:display_cols]):
				if vel > summary[i] or (vel == _SUSTAIN and summary[i] == 0):
					summary[i] = vel

		label = name[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)
		cells = " ".join(self._velocity_char(v) for v in summary)
		return [f"  {label}|{cells}|"]

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _build_velocity_grid (
		self,
		pattern: typing.Any,
		grid_size: int,
		display_cols: int,
	) -> typing.Dict[int, typing.List[int]]:

		"""Scan pattern steps and build a {pitch: [velocity_per_slot]} dict.

		Each pitch gets a list of length *display_cols*.  At each grid slot
		the highest velocity from any note at that position is stored.
		"""

		total_pulses = int(pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)

		if total_pulses <= 0 or grid_size <= 0:
			return {}

		pulses_per_slot = total_pulses / grid_size

		velocity_grid: typing.Dict[int, typing.List[int]] = {}

		for pulse, step in pattern.steps.items():
			# Map pulse → grid slot.
			slot = int(pulse / pulses_per_slot)

			if slot < 0 or slot >= display_cols:
				continue

			for note in step.notes:
				if note.pitch not in velocity_grid:
					velocity_grid[note.pitch] = [0] * display_cols

				if note.velocity > velocity_grid[note.pitch][slot]:
					velocity_grid[note.pitch][slot] = note.velocity

				# Fill sustain markers for slots where the note is
				# still sounding.  Short notes (drums, staccato) never
				# enter this loop.
				end_pulse = pulse + note.duration
				for s in range(slot + 1, display_cols):
					if s * pulses_per_slot >= end_pulse:
						break
					if velocity_grid[note.pitch][s] == 0:
						velocity_grid[note.pitch][s] = _SUSTAIN

		return velocity_grid

	@staticmethod
	def _fit_columns (grid_size: int, term_width: int) -> int:

		"""Determine how many grid columns fit in the terminal.

		Each column occupies 2 characters (char + space), plus the label
		prefix and pipe delimiters.
		"""

		# "  " + label (LABEL_WIDTH) + "|" + cells + "|"
		# Each cell is "X " (2 chars) but last cell has no trailing space
		# inside the pipes: "X . X ." is grid_size * 2 - 1 chars.
		overhead = 2 + _LABEL_WIDTH + 2  # indent + label + pipes
		available = term_width - overhead

		if available <= 0:
			return 0

		# Each column needs 2 chars (char + space), except the last needs 1.
		max_cols = (available + 1) // 2

		return min(grid_size, max_cols)


class DisplayLogHandler (logging.Handler):

	"""Logging handler that clears and redraws the status line around log output.

	Installed by ``Display.start()`` and removed by ``Display.stop()``. Ensures
	log messages do not overwrite or corrupt the persistent status line.
	"""

	def __init__ (self, display: "Display") -> None:

		"""Store reference to the display for clear/redraw calls."""

		super().__init__()
		self._display = display

	def emit (self, record: logging.LogRecord) -> None:

		"""Clear the status line, write the log message, then redraw."""

		try:
			self._display.clear_line()

			msg = self.format(record)
			sys.stderr.write(msg + "\n")
			sys.stderr.flush()

			self._display.draw()

		except Exception:
			self.handleError(record)


class Display:

	"""Live-updating terminal dashboard showing composition state.

	Reads bar, section, chord, BPM, and key from the ``Composition`` and renders
	a persistent region to stderr.  When ``grid=True`` an ASCII pattern grid is
	rendered above the status line.  A custom ``DisplayLogHandler`` ensures log
	messages scroll cleanly above the dashboard.

	Example:
		```python
		composition.display(grid=True)
		composition.play()
		```
	"""

	def __init__ (self, composition: "Composition", grid: bool = False) -> None:

		"""Store composition reference for reading playback state.

		Parameters:
			composition: The ``Composition`` instance to read state from.
			grid: When True, render an ASCII grid of running patterns
				above the status line.
		"""

		self._composition = composition
		self._active: bool = False
		self._handler: typing.Optional[DisplayLogHandler] = None
		self._saved_handlers: typing.List[logging.Handler] = []
		self._last_line: str = ""
		self._last_bar: typing.Optional[int] = None
		self._cached_section: typing.Any = None
		self._grid: typing.Optional[GridDisplay] = GridDisplay(composition) if grid else None
		self._last_grid_bar: typing.Optional[int] = None
		self._drawn_line_count: int = 0

	def start (self) -> None:

		"""Install the log handler and activate the display.

		Saves existing root logger handlers and replaces them with a
		``DisplayLogHandler`` that clears/redraws the status line around
		each log message. Original handlers are restored by ``stop()``.
		"""

		if self._active:
			return

		self._active = True

		root_logger = logging.getLogger()

		# Save existing handlers so we can restore them on stop.
		self._saved_handlers = list(root_logger.handlers)

		# Build the replacement handler, inheriting the formatter from the
		# first existing handler (if any) for consistent log formatting.
		self._handler = DisplayLogHandler(self)

		if self._saved_handlers and self._saved_handlers[0].formatter:
			self._handler.setFormatter(self._saved_handlers[0].formatter)
		else:
			self._handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))

		root_logger.handlers.clear()
		root_logger.addHandler(self._handler)

	def stop (self) -> None:

		"""Clear the status line and restore original log handlers."""

		if not self._active:
			return

		self.clear_line()
		self._active = False

		root_logger = logging.getLogger()
		root_logger.handlers.clear()

		for handler in self._saved_handlers:
			root_logger.addHandler(handler)

		self._saved_handlers = []
		self._handler = None

	def update (self, _: int = 0) -> None:

		"""Rebuild and redraw the dashboard; called on ``"bar"`` and ``"beat"`` events.

		The integer argument (bar or beat number) is ignored — state is read directly from
		the composition.

		Note: "bar" and "beat" events are emitted as ``asyncio.create_task`` at the start
		of each pulse, but the tasks only execute *after* ``_advance_pulse()`` completes
		(which includes sending MIDI via ``_process_pulse()``). The display therefore
		always trails the audio slightly — this is inherent to the architecture and cannot
		be avoided without restructuring the sequencer loop.
		"""

		if not self._active:
			return

		self._last_line = self._format_status()

		# Rebuild grid data only when the bar counter changes.
		if self._grid is not None:
			current_bar = self._composition._sequencer.current_bar
			if current_bar != self._last_grid_bar:
				self._last_grid_bar = current_bar
				self._grid.build()

		self.draw()

	def draw (self) -> None:

		"""Write the current dashboard to the terminal."""

		if not self._active or not self._last_line:
			return

		grid_lines = self._grid._lines if self._grid is not None else []
		total = len(grid_lines) + 1  # grid lines + status line

		# Move cursor up to overwrite the previously drawn region.
		# Cursor sits on the last line (status) with no trailing newline,
		# so we move up (total - 1) to reach the first line.
		if self._drawn_line_count > 1:
			sys.stderr.write(f"\033[{self._drawn_line_count - 1}A")

		if grid_lines:
			for line in grid_lines:
				sys.stderr.write(f"\r\033[K{line}\n")

		# Status line (no trailing newline — cursor stays on this line).
		sys.stderr.write(f"\r\033[K{self._last_line}")
		sys.stderr.flush()

		self._drawn_line_count = total

	def clear_line (self) -> None:

		"""Erase the entire dashboard region from the terminal."""

		if not self._active:
			return

		if self._drawn_line_count > 1:
			# Cursor is on the last line (no trailing newline).
			# Move up (total - 1) to reach the first line.
			sys.stderr.write(f"\033[{self._drawn_line_count - 1}A")

			# Clear each line.
			for _ in range(self._drawn_line_count):
				sys.stderr.write("\r\033[K\n")

			# Move cursor back up to the starting position.
			sys.stderr.write(f"\033[{self._drawn_line_count}A")
		else:
			sys.stderr.write("\r\033[K")

		sys.stderr.flush()
		self._drawn_line_count = 0

	def _format_status (self) -> str:

		"""Build the status string from current composition state."""

		parts: typing.List[str] = []
		comp = self._composition

		parts.append(f"{comp._sequencer.current_bpm:.2f} BPM")

		if comp.key:
			parts.append(f"Key: {comp.key}")

		bar  = max(0, comp._sequencer.current_bar)  + 1
		beat = max(0, comp._sequencer.current_beat) + 1
		parts.append(f"Bar: {bar}.{beat}")

		# Section info (only when form is configured).
		# Cache refreshes only when the bar counter changes, keeping
		# the section display in sync with the bar display even though
		# the form state advances one beat early (due to lookahead).
		if comp._form_state is not None:
			current_bar = comp._sequencer.current_bar

			if current_bar != self._last_bar:
				self._last_bar = current_bar
				self._cached_section = comp._form_state.get_section_info()

			section = self._cached_section

			if section:
				section_str = f"[{section.name} {section.bar + 1}/{section.bars}"
				if section.next_section:
					section_str += f" \u2192 {section.next_section}"
				section_str += "]"
				parts.append(section_str)
			else:
				parts.append("[form finished]")

		# Current chord (only when harmony is configured).
		if comp._harmonic_state is not None:
			chord = comp._harmonic_state.get_current_chord()
			parts.append(f"Chord: {chord.name()}")

		# Conductor signals (when any are registered).
		conductor = comp.conductor
		if conductor._signals:
			beat = comp._builder_bar * 4
			for name in sorted(conductor._signals):
				value = conductor.get(name, beat)
				parts.append(f"{name.title()}: {value:.2f}")

		return "  ".join(parts)
