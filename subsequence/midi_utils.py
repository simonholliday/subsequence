
import logging
import typing
import mido

logger = logging.getLogger(__name__)

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
