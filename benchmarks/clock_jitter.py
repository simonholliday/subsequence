"""MIDI clock jitter benchmark.

Runs the sequencer timing loop for a configurable number of bars and measures
the deviation of each pulse from its ideal scheduled time.

Usage:
    python benchmarks/clock_jitter.py [--bpm BPM] [--bars N] [--no-spin-wait]
                                      [--device DEVICE_NAME] [--compare]

Options:
    --bpm BPM           Tempo in BPM (default: 120)
    --bars N            Number of bars to measure (default: 32)
    --no-spin-wait      Disable hybrid sleep+spin (use pure asyncio.sleep)
    --device NAME       MIDI output device name (default: auto-select)
    --compare           Run both modes and print a side-by-side comparison
"""

import argparse
import asyncio
import logging
import statistics
import sys

# Suppress sequencer logging during benchmark — we want clean output.
logging.basicConfig(level=logging.ERROR)

import subsequence.sequencer

# ---------------------------------------------------------------------------

PPQN      = 24   # MIDI quarter note = 24 pulses
BEATS_PER_BAR = 4


def _run_benchmark (
	bpm: float,
	bars: int,
	spin_wait: bool,
	device_name: str | None,
) -> list[float]:

	"""Run the sequencer for *bars* bars and return per-pulse jitter (seconds)."""

	jitter_log: list[float] = []
	seconds_per_bar = (60.0 / bpm) * BEATS_PER_BAR
	total_seconds = seconds_per_bar * bars
	pulses = bars * BEATS_PER_BAR * PPQN

	async def _run () -> None:

		seq = subsequence.sequencer.Sequencer(
			output_device_name = device_name,
			initial_bpm = bpm,
			spin_wait = spin_wait,
			_jitter_log = jitter_log,
		)
		await seq.start()

		# Use shield so that the timeout does NOT cancel seq.task — we want
		# the task to exit cleanly when we set running=False below.
		try:
			await asyncio.wait_for(asyncio.shield(seq.task), timeout=total_seconds + 2.0)  # type: ignore[arg-type]
		except asyncio.TimeoutError:
			pass  # Expected — target duration elapsed.

		# Signal the loop to exit at the next pulse, then wait for it.
		seq.running = False
		if seq.task and not seq.task.done():
			try:
				await asyncio.wait_for(seq.task, timeout=2.0)  # type: ignore[arg-type]
			except (asyncio.TimeoutError, asyncio.CancelledError):
				seq.task.cancel()

		if seq.midi_out:
			seq.midi_out.close()
			seq.midi_out = None

	asyncio.run(_run())

	# Trim to the expected pulse count in case of minor over/under-run.
	return jitter_log[:pulses]


def _print_report (
	jitter: list[float],
	bpm: float,
	bars: int,
	spin_wait: bool,
	label: str = "",
) -> None:

	if not jitter:
		print("No jitter data collected.")
		return

	ms = [j * 1000 for j in jitter]   # convert to milliseconds
	us = [j * 1e6  for j in jitter]   # and microseconds for tight results

	mean_ms   = statistics.mean(ms)
	median_ms = statistics.median(ms)
	stdev_ms  = statistics.stdev(ms) if len(ms) > 1 else 0.0
	p95_ms    = sorted(ms)[int(len(ms) * 0.95)]
	p99_ms    = sorted(ms)[int(len(ms) * 0.99)]
	max_ms    = max(ms)

	# Non-accumulating drift: difference between first and last jitter samples.
	drift_ms  = ms[-1] - ms[0] if len(ms) > 1 else 0.0

	ppqn = PPQN
	seconds_per_pulse = 60.0 / bpm / ppqn
	pulse_interval_ms = seconds_per_pulse * 1000

	mode = "spin-wait ON" if spin_wait else "spin-wait OFF"
	header = f"  {label}  " if label else ""

	print(f"\nClock Jitter Benchmark{header}— {bars} bars at {bpm:.0f} BPM ({mode})")
	print(f"{'─' * 62}")
	print(f"  Pulses measured : {len(ms)}")
	print(f"  Pulse interval  : {pulse_interval_ms:.3f} ms  ({ppqn} PPQN)")
	print(f"{'─' * 62}")
	print(f"  Mean jitter     : {mean_ms:>8.3f} ms")
	print(f"  Median jitter   : {median_ms:>8.3f} ms")
	print(f"  Std deviation   : {stdev_ms:>8.3f} ms")
	print(f"  P95 jitter      : {p95_ms:>8.3f} ms")
	print(f"  P99 jitter      : {p99_ms:>8.3f} ms")
	print(f"  Max jitter      : {max_ms:>8.3f} ms")
	print(f"  Clock drift     : {drift_ms:>+8.3f} ms  (non-accumulating)")
	print(f"{'─' * 62}")

	# Qualitative rating.
	if mean_ms < 0.1:
		rating = "Excellent  (sub-100 μs — tight hardware-class timing)"
	elif mean_ms < 0.5:
		rating = "Very good  (sub-500 μs — well below human perception)"
	elif mean_ms < 2.0:
		rating = "Good       (< 2 ms — at or below human perception threshold)"
	elif mean_ms < 5.0:
		rating = "Fair       (2–5 ms — may affect tight sync with hardware)"
	else:
		rating = "Poor       (> 5 ms — noticeable timing issues likely)"

	print(f"  Rating          : {rating}")
	print()


def main () -> None:

	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--bpm",          type=float, default=120,  help="Tempo in BPM (default: 120)")
	parser.add_argument("--bars",         type=int,   default=32,   help="Bars to measure (default: 32)")
	parser.add_argument("--no-spin-wait", action="store_true",       help="Disable spin-wait (use pure asyncio.sleep)")
	parser.add_argument("--device",       type=str,   default=None,  help="MIDI output device name")
	parser.add_argument("--compare",      action="store_true",       help="Run both modes and compare")
	args = parser.parse_args()

	if args.compare:
		print("\nRunning with spin-wait ON ...")
		spin_jitter = _run_benchmark(args.bpm, args.bars, spin_wait=True, device_name=args.device)
		_print_report(spin_jitter, args.bpm, args.bars, spin_wait=True, label="[spin-wait ON]")

		print("Running with spin-wait OFF ...")
		pure_jitter = _run_benchmark(args.bpm, args.bars, spin_wait=False, device_name=args.device)
		_print_report(pure_jitter, args.bpm, args.bars, spin_wait=False, label="[spin-wait OFF]")

	else:
		spin = not args.no_spin_wait
		jitter = _run_benchmark(args.bpm, args.bars, spin_wait=spin, device_name=args.device)
		_print_report(jitter, args.bpm, args.bars, spin_wait=spin)


if __name__ == "__main__":
	main()
