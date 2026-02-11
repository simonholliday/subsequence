import logging
import os
import time

import yaml

import subsequence.constants
import subsequence.pattern
import subsequence.sequencer


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

	# Create a simple beat
	# Kick on 1, 3
	pattern.add_note(0 * subsequence.constants.MIDI_QUARTER_NOTE, subsequence.constants.DRM1_MKIV_KICK, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)
	pattern.add_note(2 * subsequence.constants.MIDI_QUARTER_NOTE, subsequence.constants.DRM1_MKIV_KICK, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Snare on 2, 4
	pattern.add_note(1 * subsequence.constants.MIDI_QUARTER_NOTE, subsequence.constants.DRM1_MKIV_SNARE, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)
	pattern.add_note(3 * subsequence.constants.MIDI_QUARTER_NOTE, subsequence.constants.DRM1_MKIV_SNARE, 100, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Hi-hats on 8ths
	for i in range(8):
		pos = i * (subsequence.constants.MIDI_QUARTER_NOTE // 2)
		pattern.add_note(pos, subsequence.constants.DRM1_MKIV_HH1_CLOSED, 80, subsequence.constants.MIDI_SIXTEENTH_NOTE)

	# Open Hi-hat on the last off-beat
	pattern.add_note(7 * (subsequence.constants.MIDI_QUARTER_NOTE // 2), subsequence.constants.DRM1_MKIV_HH1_OPEN, 80, subsequence.constants.MIDI_SIXTEENTH_NOTE)

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
