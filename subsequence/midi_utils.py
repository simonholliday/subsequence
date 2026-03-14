
import logging
import typing
import mido

logger = logging.getLogger(__name__)


# Type alias for device identifiers: index (int), name (str), or None (device 0).
DeviceId = typing.Union[int, str, None]


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

		self._ports: typing.List[typing.Tuple[str, typing.Any]] = []
		self._name_to_index: typing.Dict[str, int] = {}

	def add (self, name: str, port: typing.Any) -> int:

		"""Register a port under *name*.  Returns the assigned integer index."""

		idx = len(self._ports)
		self._ports.append((name, port))
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

	def close_all (self) -> None:

		"""Close every registered port and clear the registry."""

		for name, port in self._ports:
			try:
				port.close()
			except Exception:
				logger.exception(f"Error closing MIDI port '{name}'")
		self._ports.clear()
		self._name_to_index.clear()

	def __len__ (self) -> int:
		return len(self._ports)

	def __iter__ (self) -> typing.Iterator[typing.Any]:
		"""Iterate over port objects (not names)."""
		return (port for _, port in self._ports)

	def __bool__ (self) -> bool:
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

def select_output_device(device_name: typing.Optional[str] = None) -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Any]]:
    """
    Select and open a MIDI output device.

    If `device_name` is provided, attempts to open that specific device.
    If `device_name` is None, auto-discovers available devices:
    - If exactly one device exists, it is selected automatically.
    - If multiple devices exist, prompts the user to choose one from the console.
    - If no devices exist, logs an error and returns None.

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
            if device_name in outputs:
                midi_out = mido.open_output(device_name)
                logger.info(f"Opened MIDI output: {device_name}")
                return device_name, midi_out
            else:
                logger.error(
                    f"MIDI output device '{device_name}' not found. "
                    f"Available devices: {outputs}"
                )
                return None, None

        # Auto-discover: one device - use it
        if len(outputs) == 1:
            selected_name = outputs[0]
            midi_out = mido.open_output(selected_name)
            logger.info(f"One MIDI output found - using '{selected_name}'")
            return selected_name, midi_out

        # Auto-discover: multiple devices - prompt user
        print("\nAvailable MIDI output devices:\n")
        for i, name in enumerate(outputs, 1):
            print(f"  {i}. {name}")
        print()

        while True:
            try:
                choice = int(input(f"Select a device (1-{len(outputs)}): "))
                if 1 <= choice <= len(outputs):
                    break
            except (ValueError, EOFError):
                pass
            print(f"Enter a number between 1 and {len(outputs)}.")

        selected_name = outputs[choice - 1]
        midi_out = mido.open_output(selected_name)
        logger.info(f"Opened MIDI output: {selected_name}")

        print(f"\nTip: To skip this prompt, pass the device name directly:\n")
        print(f"  Sequencer(output_device_name=\"{selected_name}\")")
        print(f"  Composition(output_device=\"{selected_name}\")\n")

        return selected_name, midi_out

    except Exception as e:
        logger.error(f"Failed to open MIDI output: {e}")
        return None, None


def select_input_device(device_name: typing.Optional[str] = None, callback: typing.Optional[typing.Callable] = None) -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Any]]:
    """
    Select and open a MIDI input device.

    If `device_name` is provided, attempts to open that specific device.
    If `device_name` is None, returns None without prompting (input is optional/advanced).
    To enforce input, the caller should check the return value.

    If the precise name is not found, this function falls back to the first available input
    and logs a warning, which is useful for cross-platform script portability.

    Returns:
        A tuple of (device_name, midi_in_object) or (None, None) on failure.
    """
    if device_name is None:
        return None, None

    try:
        inputs = mido.get_input_names()
        logger.info(f"Available MIDI inputs: {inputs}")

        target = device_name

        if target not in inputs:
            logger.warning(f"MIDI input device '{target}' not found.")
            if inputs:
                target = inputs[0]
                logger.warning(f"Fallback to: {target}")
            else:
                return None, None

        midi_in = mido.open_input(target, callback=callback)
        logger.info(f"Opened MIDI input: {target}")
        return target, midi_in

    except Exception as e:
        logger.error(f"Failed to open MIDI input: {e}")
        return None, None
