"""
Ableton Link clock adapter for Subsequence.

Wraps ``aalink.Link`` and adapts its asyncio-native API to Subsequence's
24 PPQN pulse model.  Requires the optional ``link`` extra::

    pip install subsequence[link]

Usage::

    link_clock = LinkClock(bpm=120, quantum=4.0, loop=asyncio.get_running_loop())
    beat_origin = await link_clock.wait_for_bar()
    # ... in the pulse loop:
    await link_clock.sync(beat_origin + pulse_count / PPQN)
"""

from __future__ import annotations

import asyncio
import typing


def _require_aalink() -> typing.Any:
	"""Import aalink or raise a helpful RuntimeError."""
	try:
		import aalink  # type: ignore
		return aalink
	except ImportError:
		raise RuntimeError(
			"Ableton Link support requires the 'aalink' package.\n"
			"Install it with:  pip install subsequence[link]"
		) from None


class LinkClock:

	"""
	Thin wrapper around ``aalink.Link`` for Subsequence's pulse-based clock.

	Parameters:
		bpm: Initial tempo in BPM (proposed to the Link session).
		quantum: Beat cycle length — 4.0 means one bar in 4/4 time.
		loop: The running asyncio event loop (required by aalink).
	"""

	def __init__ (self, bpm: float, quantum: float, loop: asyncio.AbstractEventLoop) -> None:

		aalink = _require_aalink()
		self._link = aalink.Link(bpm, loop)
		self._link.enabled = True
		self._link.quantum = float(quantum)

	# ------------------------------------------------------------------
	# Properties that mirror the Link session state
	# ------------------------------------------------------------------

	@property
	def beat (self) -> float:
		"""Current absolute beat position in the Link session timeline."""
		return float(self._link.beat)

	@property
	def tempo (self) -> float:
		"""Current session tempo in BPM (authoritative from the Link network)."""
		return float(self._link.tempo)

	@property
	def quantum (self) -> float:
		"""Beat cycle length (e.g. 4.0 for one bar in 4/4)."""
		return float(self._link.quantum)

	@property
	def num_peers (self) -> int:
		"""Number of connected Link peers (not counting self)."""
		return int(self._link.num_peers)

	@property
	def playing (self) -> bool:
		"""Whether the Link session transport is playing."""
		return bool(self._link.playing)

	# ------------------------------------------------------------------
	# Sync / control
	# ------------------------------------------------------------------

	async def sync (self, beat: float) -> float:
		"""Wait until the Link session beat reaches *beat*, then return *beat*.

		This is the primary timing primitive used by the sequencer loop.
		Calling ``await link_clock.sync(beat_origin + pulse / PPQN)`` for each
		successive pulse gives accurate, Link-synchronised timing.
		"""
		return float(await self._link.sync(beat))

	async def wait_for_bar (self) -> float:
		"""Wait for the next quantum boundary (bar start) and return it.

		Use this to start the sequencer at a musically clean position that is
		phase-aligned with all other Link participants.

		Returns the beat value at which playback should begin (``beat_origin``).
		"""
		current = self._link.beat
		# Next quantum boundary strictly after the current beat
		next_boundary = (int(current / self._link.quantum) + 1) * self._link.quantum
		result = await self._link.sync(next_boundary)
		return float(result)

	def request_tempo (self, bpm: float) -> None:
		"""Propose a new tempo to the Link session.

		Other peers may accept or reject the change depending on their own
		session rules.  Subsequence's sequencer will pick up the network-
		authoritative tempo on the next pulse.
		"""
		self._link.tempo = float(bpm)

	def disable (self) -> None:
		"""Disconnect from the Link session."""
		self._link.enabled = False
