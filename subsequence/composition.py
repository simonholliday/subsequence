import asyncio
import logging
import os
import signal
import typing

import yaml

import subsequence.harmonic_state
import subsequence.pattern
import subsequence.sequencer


logger = logging.getLogger(__name__)


def load_config (config_path: str = "config.yaml") -> dict:

	"""
	Load configuration from a YAML file.
	"""

	if not os.path.exists(config_path):
		logger.warning(f"Config file {config_path} not found. Using defaults.")
		return {}

	with open(config_path, "r") as config_file:
		return yaml.safe_load(config_file)


def get_sequencer_settings (config: dict, default_device: str, default_bpm: int) -> typing.Tuple[str, int]:

	"""
	Extract MIDI device and BPM settings from config with defaults.
	"""

	midi_device = config.get("midi", {}).get("device_name", default_device)
	initial_bpm = config.get("sequencer", {}).get("initial_bpm", default_bpm)

	return midi_device, initial_bpm


async def schedule_harmonic_clock (
	sequencer: subsequence.sequencer.Sequencer,
	harmonic_state: subsequence.harmonic_state.HarmonicState,
	cycle_beats: int,
	reschedule_lookahead: int = 1
) -> None:

	"""
	Schedule composition-level harmonic changes on a repeating beat interval.
	"""

	def advance_harmony (pulse: int) -> None:

		"""
		Advance the harmonic state on the composition clock.
		"""

		# Decision path: chord changes are driven by the harmonic clock; key changes are explicit in harmonic_state.
		harmonic_state.step()

	# Decision: schedule harmony independently of any pattern, aligned to the cycle grid.
	await sequencer.schedule_callback_repeating(
		callback = advance_harmony,
		interval_beats = cycle_beats,
		start_pulse = 0,
		# Decision: use the same lookahead as patterns so rebuilds see the new chord.
		reschedule_lookahead = reschedule_lookahead
	)


async def schedule_patterns (
	sequencer: subsequence.sequencer.Sequencer,
	patterns: typing.Iterable[subsequence.pattern.Pattern],
	start_pulse: int = 0
) -> None:

	"""
	Schedule a collection of repeating patterns from a shared start pulse.
	"""

	for pattern in patterns:
		await sequencer.schedule_pattern_repeating(pattern, start_pulse=start_pulse)


async def run_until_stopped (sequencer: subsequence.sequencer.Sequencer) -> None:

	"""
	Run the sequencer until a stop signal is received.
	"""

	logger.info("Playing sequence. Press Ctrl+C to stop.")

	await sequencer.start()

	stop_event = asyncio.Event()
	loop = asyncio.get_running_loop()

	def _request_stop () -> None:

		"""
		Signal handler to request a clean shutdown.
		"""

		stop_event.set()

	for sig in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(sig, _request_stop)

	await asyncio.wait(
		[asyncio.create_task(stop_event.wait()), sequencer.task],
		return_when = asyncio.FIRST_COMPLETED
	)

	await sequencer.stop()
