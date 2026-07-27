"""
MIDI device plumbing — discovering, opening, and registering hardware ports.

Provides interactive/automatic output and input device selection, the
multi-device registry used by the sequencer, and the ``bank_select()``
helper for addressing synth banks beyond the first 128 programs.

Device names are matched as globs — see :func:`match_device_names`.  Most
systems put a number in the name that moves between runs, so pinning the
full name tends to break; a pattern like ``"*U6MIDI Pro *:0"`` survives.
"""

import fnmatch
import logging
import sys
import typing
import mido

logger = logging.getLogger(__name__)


# Type alias for device identifiers: index (int), name (str), or None (device 0).
DeviceId = typing.Union[int, str, None]


class DeviceSelectionError(RuntimeError):

	"""A device pattern could not be resolved to exactly one device.

	Kept distinct from the plain ``RuntimeError`` that a failed port open raises,
	because the two want opposite handling: a port that will not open is logged
	and playback continues without it, whereas an unresolved pattern must reach
	the caller — it means the wrong instrument (or no instrument) would play.
	"""


class MidiDeviceRegistry:

	"""Ordered registry of named MIDI ports (output or input).

	Devices are stored in insertion order.  Index 0 is always the first
	(or only) device — the default for all APIs that do not specify a device.
	Devices can be looked up by integer index or by name string.
	``None`` always resolves to index 0.

	The registry is intended to be append-only once playback has started.
	All registered port objects must already be open.
	"""

	def __init__ (self) -> None:

		"""
		Create an empty registry; populate it with add().
		"""

		self._ports: typing.List[typing.Tuple[str, typing.Any]] = []
		self._name_to_index: typing.Dict[str, int] = {}
		# Per-device physical output latency in milliseconds, parallel to
		# self._ports by index.  Kept separate from the (name, port) tuple so
		# replace() can swap the port object without disturbing latency.
		self._latencies: typing.List[float] = []

	def add (self, name: str, port: typing.Any, latency_ms: float = 0.0) -> int:

		"""Register a port under *name*.  Returns the assigned integer index.

		*latency_ms* is the device's physical output latency (non-negative);
		see :meth:`set_latency`.
		"""

		idx = len(self._ports)
		self._ports.append((name, port))
		self._latencies.append(max(0.0, float(latency_ms)))
		# First registration wins for name collisions.
		if name not in self._name_to_index:
			self._name_to_index[name] = idx
		return idx

	def get (self, device: DeviceId = None) -> typing.Optional[typing.Any]:

		"""Return the port for *device*, or ``None`` if the registry is empty.

		``None`` → index 0.  ``int`` → direct index.  ``str`` → name lookup.
		Returns ``None`` if the device cannot be resolved (empty registry,
		out-of-range index, unknown name).
		"""

		if not self._ports:
			return None
		idx = self.index_of(device)
		if idx < 0 or idx >= len(self._ports):
			return None
		return self._ports[idx][1]

	def index_of (self, device: DeviceId = None) -> int:

		"""Resolve *device* to an integer index.  Returns 0 for ``None``.
		Returns -1 if the name is unknown or the index is out of range."""

		if device is None:
			return 0
		if isinstance(device, int):
			if 0 <= device < len(self._ports):
				return device
			return -1
		# str
		return self._name_to_index.get(device, -1)

	def replace (self, index: int, port: typing.Any) -> None:

		"""Replace the port object at *index* without changing the name or index mapping.

		Used by the backward-compat ``midi_out``/``midi_in`` setters to allow
		test code to inject a fake port after the registry has been populated.
		Raises ``IndexError`` if *index* is out of range.
		"""

		if index < 0 or index >= len(self._ports):
			raise IndexError(f"MidiDeviceRegistry: index {index} out of range (size {len(self._ports)})")
		name = self._ports[index][0]
		self._ports[index] = (name, port)
		# Latency is intentionally preserved — replace() is a pure port swap.

	def set_latency (self, device: DeviceId, latency_ms: float) -> None:

		"""Set the physical output latency (milliseconds) for *device*.

		*latency_ms* must be non-negative — a device cannot sound before it is
		triggered, so a negative output latency is meaningless.  Raises
		``ValueError`` for a negative value or an unknown device.
		"""

		if latency_ms < 0:
			raise ValueError(f"latency_ms must be non-negative — got {latency_ms}")
		idx = self.index_of(device)
		if idx < 0:
			raise ValueError(f"Unknown output device: {device!r}")
		self._latencies[idx] = float(latency_ms)

	def latency_of (self, device: DeviceId = None) -> float:

		"""Return the latency (ms) for *device*, or 0.0 if it cannot be resolved.

		Defensive on the hot dispatch path: an unknown device yields 0.0 rather
		than raising, so a stray event can never crash the send loop.
		"""

		idx = self.index_of(device)
		if idx < 0 or idx >= len(self._latencies):
			return 0.0
		return self._latencies[idx]

	def max_latency (self) -> float:

		"""Return the largest latency across all registered devices (0.0 if empty)."""

		return max(self._latencies, default=0.0)

	def close_all (self) -> None:

		"""Close every registered port and clear the registry."""

		for name, port in self._ports:
			try:
				port.close()
			except (OSError, RuntimeError, AttributeError):
				# Shutdown path: a failure on one port must not prevent closing the rest.
				logger.exception(f"Error closing MIDI port '{name}'")
		self._ports.clear()
		self._name_to_index.clear()
		self._latencies.clear()

	def __len__ (self) -> int:

		"""
		Number of registered devices.
		"""

		return len(self._ports)

	def __iter__ (self) -> typing.Iterator[typing.Any]:
		"""Iterate over port objects (not names)."""
		return (port for _, port in self._ports)

	def __bool__ (self) -> bool:

		"""
		True if at least one device is registered.
		"""

		return bool(self._ports)


def bank_select (bank: int) -> typing.Tuple[int, int]:

	"""
	Convert a 14-bit MIDI bank number to (MSB, LSB) for use with
	``p.program_change()``.

	MIDI bank select uses two control-change messages: CC 0 (Bank MSB) and
	CC 32 (Bank LSB).  Together they encode a 14-bit bank number in the
	range 0–16,383:

	    MSB = bank // 128   (upper 7 bits, sent on CC 0)
	    LSB = bank % 128    (lower 7 bits, sent on CC 32)

	Args:
		bank: Integer bank number, 0–16,383.  Values outside this range are
		      clamped.

	Returns:
		``(msb, lsb)`` tuple, each value in 0–127.

	Example:
		```python
		msb, lsb = subsequence.bank_select(128)   # → (1, 0)
		p.program_change(48, bank_msb=msb, bank_lsb=lsb)
		```
	"""

	bank = max(0, min(16383, bank))
	return bank >> 7, bank & 0x7F

def match_device_names (pattern: str, names: typing.Sequence[str]) -> typing.List[int]:

	"""Find every device whose name matches *pattern*, as indices into *names*.

	Device names carry a number that moves.  On Linux,
	``U6MIDI Pro:U6MIDI Pro Port 1 16:0`` puts the ALSA sequencer client id
	(``16``) in the middle — handed out in registration order, so it differs
	between runs — while the port index after the colon (``0``) stays put.
	Virtual ports are the worst offenders, landing at 128 and upward in whatever
	order things happened to start.  Wildcards let a pattern pin the part that
	holds still and ignore the part that does not.

	``*`` matches any run of characters and ``?`` exactly one; nothing else is
	special.  Matching is case-insensitive with an implicit ``*`` at each end, so
	a pattern containing no wildcards is simply a substring search.

	An exact name wins outright: when the pattern names a device precisely, that
	device is chosen even if the pattern also appears inside longer names.  This
	is what lets a full device name stay unambiguous forever.

	Prefer ``*`` to ``?`` — ``?`` matches a single character, so a pattern written
	for ``16:0`` quietly stops matching once ids reach three digits.

	Keep the trailing port index.  A multi-port interface reports one name per
	port, so ``"*U6MIDI Pro*"`` matches all three ports of a 3-port unit and asks
	which you meant at every launch, while ``"*U6MIDI Pro *:0"`` names one for good.

	Parameters:
		pattern: A device name, or a glob to match against the available names.
		names: The available device names, in the order the backend reports them.

	Returns:
		The indices of every match, in order.  Empty when nothing matches.

	Example:
		```python
		import mido

		hits = subsequence.midi_utils.match_device_names("*U6MIDI Pro *:0", mido.get_output_names())
		```
	"""

	lowered = pattern.lower()

	# An exact name wins, so pinning a full device name cannot be made ambiguous
	# by some longer name that happens to contain it.
	exact = [index for index, name in enumerate(names) if name.lower() == lowered]

	if exact:
		return exact

	# Escape ``[`` so a pasted name containing one is not read as a character
	# class — fnmatch would take "[Pro]" as "any of P, r, o" and match almost
	# everything, a false positive with no visible cause.  fnmatchcase (not
	# fnmatch) because fnmatch applies os.path.normcase, which lowercases again
	# on Windows and would make behaviour differ by platform.
	compiled = f"*{lowered.replace('[', '[[]')}*"

	return [index for index, name in enumerate(names) if fnmatch.fnmatchcase(name.lower(), compiled)]


def _choose_device_interactively (
	names: typing.Sequence[str],
	indices: typing.Sequence[int],
	noun: str,
	reason: str,
	hint: str,
) -> int:

	"""Ask which of *indices* to use, and return the chosen index.

	Raises when there is no terminal to ask.  A menu printed into a service
	manager, a scheduled job, or an SSH session without a TTY waits for an answer
	that can never arrive — an indefinite hang with nothing in the log — so an
	unattended run ends the call instead, carrying *hint* so the log says what to
	pass next time.  Each caller decides whether that becomes a raise or its own
	documented failure return.

	Raises:
		DeviceSelectionError: If the choice cannot be put to a human.
	"""

	candidates = [names[index] for index in indices]

	# isatty() rather than waiting for EOF: a run whose stdin is an open but
	# silent pipe never raises EOFError, it just blocks forever.
	if not sys.stdin.isatty():
		raise DeviceSelectionError(f"{reason}, and there is no terminal to choose from — {hint}")

	print(f"\n{reason}:\n")

	for position, index in enumerate(indices, 1):
		print(f"  {position}. {names[index]}")

	print()

	while True:
		try:
			choice = int(input(f"Select a {noun} (1-{len(indices)}): "))
			if 1 <= choice <= len(indices):
				return indices[choice - 1]
		except ValueError:
			pass
		except EOFError:
			# stdin claimed to be a TTY but gave nothing — retrying would spin.
			raise DeviceSelectionError(f"{reason}, and the prompt could not be read — {hint}") from None

		print(f"Enter a number between 1 and {len(indices)}.")


def select_output_device (device_name: typing.Optional[str] = None) -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Any]]:

	"""
	Select and open a MIDI output device.

	``device_name`` is matched as a glob (see :func:`match_device_names`), so
	``"*U6MIDI Pro *:0"`` survives the client id changing between runs.  A name
	with no wildcards is a case-insensitive substring, and an exact name always
	wins outright.  When a pattern matches several devices you are asked which
	you meant; when it matches none, that is logged and no port is opened.

	If ``device_name`` is None, auto-discovers available devices:

	- If exactly one device exists, it is selected automatically.
	- If multiple devices exist, prompts the user to choose one from the console.
	- If no devices exist, logs an error and returns None.

	Every failure — no match, no devices, or a choice that cannot be put to a
	human on an unattended run — takes the same documented exit: log what went
	wrong and how to fix it, then return ``(None, None)``.  Playback continues
	without that port rather than raising.

	Returns:
		A tuple of (device_name, midi_out_object) or (None, None) on failure.
	"""

	try:
		outputs = mido.get_output_names()
		logger.info(f"Available MIDI outputs: {outputs}")

		if not outputs:
			logger.error("No MIDI output devices found.")
			return None, None

		# Explicit device requested
		if device_name is not None:
			matches = match_device_names(device_name, outputs)

			if not matches:
				logger.error(
					f"MIDI output device '{device_name}' not found. "
					f"Available devices: {outputs}"
				)
				return None, None

			if len(matches) == 1:
				selected_name = outputs[matches[0]]
			else:
				selected_name = outputs[_choose_device_interactively(
					outputs,
					matches,
					"device",
					f"'{device_name}' matches {len(matches)} MIDI outputs",
					f"narrow output_device= to one of: {[outputs[i] for i in matches]} "
					f"(a trailing port index such as ' *:0' usually names a single port)",
				)]

			midi_out = mido.open_output(selected_name)
			logger.info(f"Opened MIDI output: {selected_name}")
			return selected_name, midi_out

		# Auto-discover: one device - use it
		if len(outputs) == 1:
			selected_name = outputs[0]
			midi_out = mido.open_output(selected_name)
			logger.info(f"One MIDI output found - using '{selected_name}'")
			return selected_name, midi_out

		# Auto-discover: multiple devices - prompt user
		selected_name = outputs[_choose_device_interactively(
			outputs,
			list(range(len(outputs))),
			"device",
			f"{len(outputs)} MIDI outputs are available",
			f"pass output_device= with one of: {outputs}",
		)]

		midi_out = mido.open_output(selected_name)
		logger.info(f"Opened MIDI output: {selected_name}")

		print(f"\nTip: To skip this prompt, pass the device name directly:\n")
		print(f"  Sequencer(output_device_name=\"{selected_name}\")")
		print(f"  Composition(output_device=\"{selected_name}\")\n")

		return selected_name, midi_out

	# DeviceSelectionError is a RuntimeError, so an unanswerable choice lands here
	# and becomes this function's documented (None, None) return with the hint in
	# the log — deliberately, so a headless run neither hangs nor raises.
	except (OSError, RuntimeError) as e:
		logger.error(f"Failed to open MIDI output: {e}")
		return None, None


def select_input_device (device_name: typing.Optional[str] = None, callback: typing.Optional[typing.Callable] = None) -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Any]]:

	"""
	Select and open a MIDI input device.

	``device_name`` is matched as a glob (see :func:`match_device_names`), so
	``"*Launchpad *:0"`` survives the client id changing between runs.  A name
	with no wildcards is a case-insensitive substring, and an exact name always
	wins outright.

	If ``device_name`` is None, returns None without prompting (input is optional/advanced).
	To enforce input, the caller should check the return value.

	A pattern matching no device raises ValueError rather than falling back to
	another input: MIDI input drives clock-follow and live note capture, so
	silently listening to the wrong device would desynchronise or mis-record a
	performance.  For the same reason a pattern matching several devices asks
	which you meant rather than guessing — and says so plainly when there is no
	terminal to ask.  The device actually opened is logged, so a pattern that
	resolved to something unintended is visible in the session log.

	Returns:
		A tuple of (device_name, midi_in_object), or (None, None) when no
		name was given or the device failed to open.

	Raises:
		ValueError: If *device_name* matches none of the available inputs.
		DeviceSelectionError: If it matches several and there is no terminal
			to put the choice to.
	"""

	if device_name is None:
		return None, None

	try:
		inputs = mido.get_input_names()
		logger.info(f"Available MIDI inputs: {inputs}")

		matches = match_device_names(device_name, inputs)

		if not matches:
			raise ValueError(
				f"MIDI input device '{device_name}' not found. "
				f"Available devices: {inputs}"
			)

		if len(matches) == 1:
			selected_name = inputs[matches[0]]
		else:
			selected_name = inputs[_choose_device_interactively(
				inputs,
				matches,
				"input",
				f"'{device_name}' matches {len(matches)} MIDI inputs",
				f"narrow the device pattern to one of: {[inputs[i] for i in matches]} "
				f"(a trailing port index such as ' *:0' usually names a single port)",
			)]

		midi_in = mido.open_input(selected_name, callback=callback)
		logger.info(f"Opened MIDI input: {selected_name}")
		return selected_name, midi_in

	except DeviceSelectionError:
		# See the matching note in select_output_device — an unresolved pattern
		# must not be downgraded into a silent "no input" run.
		raise

	except (OSError, RuntimeError) as e:
		logger.error(f"Failed to open MIDI input: {e}")
		return None, None
