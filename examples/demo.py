import asyncio
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


def generate_drum_pattern (length: int = 4) -> subsequence.pattern.Pattern:

	"""
	Generates a drum pattern with Kick, Snare, and Hi-hats.
	"""

	pattern = subsequence.pattern.Pattern(channel=subsequence.constants.MIDI_CHANNEL_DRM1, length=length)

	# Create a simple beat using Euclidean rhythm for kick (4 hits in 16 steps)
	kick_sequence = subsequence.sequence_utils.generate_euclidean_sequence(steps=16, pulses=4)
	pattern.add_sequence(kick_sequence, step_duration=subsequence.constants.MIDI_SIXTEENTH_NOTE, pitch=subsequence.constants.DRM1_MKIV_KICK, velocity=100)

	# Snare on 2 and 4 (standard backbeat)
	# 16th notes: 4, 12
	# Let's make a simple list sequence for snare:
	snare_sequence = [0] * 16
	snare_sequence[4] = 1
	snare_sequence[12] = 1
	pattern.add_sequence(snare_sequence, step_duration=subsequence.constants.MIDI_SIXTEENTH_NOTE, pitch=subsequence.constants.DRM1_MKIV_SNARE, velocity=100)

	# Hi-hats using Bresenham (8 hits in 16 steps = straight 8ths)
	hh_sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=16, pulses=8)
	
	# Use van der Corput to modulate velocity slightly
	vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(n=16, base=2)
	# Map 0-1 float to velocity range 60-100
	hh_velocities = [int(60 + (v * 40)) for v in vdc_values]
	
	pattern.add_sequence(hh_sequence, step_duration=subsequence.constants.MIDI_SIXTEENTH_NOTE, pitch=subsequence.constants.DRM1_MKIV_HH1_CLOSED, velocity=hh_velocities)
	
	# Open Hi-hat on the last off-beat
	pattern.add_note(14 * subsequence.constants.MIDI_SIXTEENTH_NOTE, subsequence.constants.DRM1_MKIV_HH1_OPEN, 80, subsequence.constants.MIDI_SIXTEENTH_NOTE)
	
	return pattern


async def main () -> None:

	"""
	Main entry point for the demo application.
	"""

	logger.info("Subsequence Demo starting...")

	config = load_config()

	midi_device = config.get('midi', {}).get('device_name', 'Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0')
	initial_bpm = config.get('sequencer', {}).get('initial_bpm', 125)

	seq = subsequence.sequencer.Sequencer(midi_device_name=midi_device, initial_bpm=initial_bpm)

	pattern = generate_drum_pattern(length=4)

	# Schedule for 4 bars
	pulses_per_bar = 4 * subsequence.constants.MIDI_QUARTER_NOTE

	for bar in range(4):
		await seq.schedule_pattern(pattern, start_pulse=bar * pulses_per_bar)

	async def on_bar (bar: int) -> None:
		logger.info(f"Bar {bar + 1}")

	seq.add_callback(on_bar)

	logger.info("Playing sequence...")
	await seq.play()


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
