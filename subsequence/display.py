"""Live terminal status line for composition playback.

Provides a persistent status line showing the current bar, section, chord, BPM, and key.
Log messages scroll above the status line without disruption.

Enable it with a single call before ``play()``:

```python
composition.display()
composition.play()
```

The status line updates every bar and looks like::

	125 BPM  Key: E  Bar: 17  [chorus 1/8]  Chord: Em7

Components adapt to what's configured - the section is omitted if no form is set,
and the chord is omitted if no harmony is configured.
"""

import logging
import sys
import typing

if typing.TYPE_CHECKING:
	from subsequence.composition import Composition


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

	"""Live-updating terminal status line showing composition state.

	Reads bar, section, chord, BPM, and key from the ``Composition`` and renders
	a single line to stderr. A custom ``DisplayLogHandler`` ensures log messages
	scroll cleanly above the status line.

	Example:
		```python
		composition.display()   # enable before play()
		composition.play()
		```
	"""

	def __init__ (self, composition: "Composition") -> None:

		"""Store composition reference for reading playback state.

		Parameters:
			composition: The ``Composition`` instance to read state from.
		"""

		self._composition = composition
		self._active: bool = False
		self._handler: typing.Optional[DisplayLogHandler] = None
		self._saved_handlers: typing.List[logging.Handler] = []
		self._last_line: str = ""
		self._last_bar: typing.Optional[int] = None
		self._cached_section: typing.Any = None

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

		"""Rebuild and redraw the status line; called on both ``"bar"`` and ``"beat"`` events.

		The integer argument (bar or beat number) is ignored — state is read directly from
		the composition.
		"""

		if not self._active:
			return

		self._last_line = self._format_status()
		self.draw()

	def draw (self) -> None:

		"""Write the current status line to the terminal."""

		if not self._active or not self._last_line:
			return

		# \r = carriage return, \033[K = clear to end of line.
		sys.stderr.write("\r\033[K" + self._last_line)
		sys.stderr.flush()

	def clear_line (self) -> None:

		"""Erase the status line from the terminal."""

		if not self._active:
			return

		sys.stderr.write("\r\033[K")
		sys.stderr.flush()

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
				parts.append(f"[{section.name} {section.bar + 1}/{section.bars}]")
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
