import logging
import time
import typing

import mido


logger = logging.getLogger(__name__)


def _select_input_device () -> typing.Tuple[str, typing.Any]:

	"""Prompt the user to select a MIDI input device and open it."""

	try:
		inputs = mido.get_input_names()
		logger.info("Available MIDI inputs: %s", inputs)

		if not inputs:
			raise RuntimeError("No MIDI input devices found.")

		if len(inputs) == 1:
			selected_name = inputs[0]
			midi_in = mido.open_input(selected_name)
			logger.info("One MIDI input found - using '%s'", selected_name)
			return selected_name, midi_in

		print("\nAvailable MIDI input devices:\n")
		for i, name in enumerate(inputs, 1):
			print(f"  {i}. {name}")
		print()

		while True:
			try:
				choice = int(input(f"Select a device (1-{len(inputs)}): "))
				if 1 <= choice <= len(inputs):
					break
			except (ValueError, EOFError):
				pass
			print(f"Enter a number between 1 and {len(inputs)}.")

		selected_name = inputs[choice - 1]
		midi_in = mido.open_input(selected_name)
		logger.info("Opened MIDI input: %s", selected_name)
		return selected_name, midi_in
	except Exception as exc:
		raise RuntimeError(f"Failed to open MIDI input: {exc}") from exc


def _format_message (message: typing.Any) -> str:

	"""Format a mido message into a compact, readable line."""

	parts = [message.type]

	if hasattr(message, "channel"):
		parts.append(f"ch={message.channel}")

	if message.type in {"note_on", "note_off"}:
		parts.append(f"note={message.note}")
		parts.append(f"vel={message.velocity}")
	elif message.type == "control_change":
		parts.append(f"cc={message.control}")
		parts.append(f"val={message.value}")
	elif message.type == "program_change":
		parts.append(f"program={message.program}")
	elif message.type == "pitchwheel":
		parts.append(f"pitch={message.pitch}")
	elif message.type == "polytouch":
		parts.append(f"note={message.note}")
		parts.append(f"val={message.value}")
	elif message.type == "aftertouch":
		parts.append(f"val={message.value}")
	elif message.type == "songpos":
		parts.append(f"pos={message.pos}")
	elif message.type == "song_select":
		parts.append(f"song={message.song}")
	elif message.type == "quarter_frame":
		parts.append(f"type={message.frame_type}")
		parts.append(f"val={message.frame_value}")
	elif message.type == "sysex":
		parts.append(f"len={len(message.data)}")

	return " ".join(parts)


def _run () -> int:

	"""Open a MIDI input device and print all incoming messages."""

	print("\nThis tool prints all incoming MIDI messages from a selected input device.")
	print("Use it to discover note, CC, channel, and transport data from your controller.")

	selected_name, midi_in = _select_input_device()

	print(f"\nListening on: {selected_name}")
	print("Press Ctrl+C to quit.\n")

	clock_window_seconds = 5.0
	clock_tick_count = 0
	clock_window_start = time.time()

	def _on_message (message: typing.Any) -> None:

		nonlocal clock_tick_count
		nonlocal clock_window_start

		if message.type == "clock":
			clock_tick_count += 1

			if clock_tick_count == 1:
				print("clock: detected (summary updated every 5 seconds)")

			now = time.time()
			elapsed = now - clock_window_start
			if elapsed >= clock_window_seconds:
				ticks_per_second = clock_tick_count / elapsed
				estimated_bpm = ticks_per_second * 60.0 / 24.0
				print(f"clock: {ticks_per_second:.2f} ticks/s (≈{estimated_bpm:.1f} BPM) [updated every 5 seconds]")

				clock_tick_count = 0
				clock_window_start = now

			return

		print(_format_message(message))

	midi_in.callback = _on_message

	try:
		while True:
			time.sleep(0.1)
	except KeyboardInterrupt:
		print("\nStopping...")
	finally:
		midi_in.close()

	return 0


def main () -> None:

	"""Entry point for the MIDI input observer."""

	raise SystemExit(_run())


if __name__ == "__main__":
	main()
