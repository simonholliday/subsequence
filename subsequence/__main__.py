import logging
import os
import time

import yaml

import subsequence.constants
import subsequence.pattern
import subsequence.sequencer
import subsequence.sequence_utils


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config (config_path: str = 'config.yaml') -> dict:

	"""
	Load configuration from a YAML file.
	"""

	if not os.path.exists(config_path):
		logger.warning(f"Config file {config_path} not found. Using defaults.")
		return {}

	with open(config_path, 'r') as f:
		return yaml.safe_load(f)


def main () -> None:

	"""
	Main entry point for the subsequence application.
	"""

	logger.info("Subsequence starting...")

	config = load_config()

	midi_device = config.get('midi', {}).get('device_name', 'Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0')
	initial_bpm = config.get('sequencer', {}).get('initial_bpm', 125)

	seq = subsequence.sequencer.Sequencer(midi_device_name=midi_device, initial_bpm=initial_bpm)

	pattern = subsequence.pattern.Pattern(channel=subsequence.constants.MIDI_CHANNEL_DRM1, length=4)

	# Create a simple beat using Euclidean rhythm for kick (4 hits in 16 steps)
	kick_sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=16, pulses=4)
	for i, hit in enumerate(kick_sequence):
		if hit:
			pattern.add_note(i * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_KICK, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Snare on 2 and 4 (standard backbeat)
	# 16th notes: 4, 12
	pattern.add_note(4 * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_SNARE, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)
	pattern.add_note(12 * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_SNARE, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Hi-hats using Bresenham (8 hits in 16 steps = straight 8ths)
	hh_sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=16, pulses=8)
	
	# Use van der Corput to modulate velocity slightly
	velocities = subsequence.sequence_utils.generate_van_der_corput_sequence(n=16, base=2)
	
	for i, hit in enumerate(hh_sequence):
		if hit:
			# Map 0-1 float to velocity range 60-100
			vel = int(60 + (velocities[i] * 40))
			pattern.add_note(i * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_HH1_CLOSED, vel, subsequence.constants.MIDI_SIXTEENTH_NOTE)
	
	# Open Hi-hat on the last off-beat
	pattern.add_note(14 * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_HH1_OPEN, 80, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Schedule for 4 bars
	pulses_per_bar = 4 * subsequence.constants.MIDI_QUARTER_NOTE

	for bar in range(4):
		seq.schedule_pattern(pattern, start_pulse=bar * pulses_per_bar)

	seq.start()

	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		logger.info("Stopping...")
	finally:
		seq.stop()


if __name__ == "__main__":
	main()
