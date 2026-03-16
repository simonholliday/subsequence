#!/usr/bin/env python3
"""
This script plays a pulsed E3 note on all 16 MIDI channels of a selected output device.

It is utility is used to assess whether instruments are in tune with each 
other and allow tuning against a reference. This is particularly useful 
for analogue instruments which may drift in pitch over time.

The note is triggered once per second to accommodate instruments with 
short non-sustaining envelopes.
"""

import logging
import sys
import time
import typing

import mido


logger = logging.getLogger(__name__)


def _select_output_device () -> typing.Tuple[str, typing.Any]:

	"""Prompt the user to select a MIDI output device and open it."""

	try:
		outputs = mido.get_output_names()
		logger.info("Available MIDI outputs: %s", outputs)

		if not outputs:
			raise RuntimeError("No MIDI output devices found.")

		if len(outputs) == 1:
			selected_name = outputs[0]
			midi_out = mido.open_output(selected_name)
			logger.info("One MIDI output found - using '%s'", selected_name)
			return selected_name, midi_out

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
		logger.info("Opened MIDI output: %s", selected_name)
		return selected_name, midi_out
	except Exception as exc:
		raise RuntimeError(f"Failed to open MIDI output: {exc}") from exc


def main () -> None:

	"""Run the tuner tone script."""

	logging.basicConfig(level=logging.WARNING, format='%(message)s')

	print("Subsequence Tuner Tone\n")

	try:
		device_name, midi_out = _select_output_device()
	except RuntimeError as exc:
		print(exc)
		sys.exit(1)

	# E3 is MIDI note 52 (assuming C4 = 60).
	pitch = 52
	velocity = 100

	print(f"\nSending E3 (note {pitch}) to all 16 channels on '{device_name}'...")
	print("Press CTRL-C to stop.")

	try:
		# Keep running until interrupted, repeatedly triggering the notes
		while True:
			for channel in range(16):
				msg_on = mido.Message('note_on', note=pitch, velocity=velocity, channel=channel)
				midi_out.send(msg_on)
			
			time.sleep(1.0)
			
			for channel in range(16):
				msg_off = mido.Message('note_off', note=pitch, velocity=0, channel=channel)
				midi_out.send(msg_off)

	except KeyboardInterrupt:
		print("\nStopping notes...")
	finally:
		# Send note_off to all channels
		for channel in range(16):
			msg_off = mido.Message('note_off', note=pitch, velocity=0, channel=channel)
			midi_out.send(msg_off)
		midi_out.close()
		print("Done.")


if __name__ == '__main__':
	main()
