"""
Ableton Link clock adapter for Subsequence.

Wraps ``aalink.Link`` and adapts its asyncio-native API to Subsequence's
24 PPQN pulse model.  Requires the optional ``link`` extra:

```shell
pip install subsequence[link]
```

Usage::

    link_clock = LinkClock(bpm=120, quantum=4.0)    # made on the running event loop
    beat_origin = await link_clock.wait_for_bar()
    # ... in the pulse loop, stepping one pulse at a time:
    beat = await link_clock.sync(1 / PPQN)

``sync`` takes a **period**, not a position: aalink resumes at the next
multiple of what it is given.  Requires aalink 0.2 or later.
"""

from __future__ import annotations

import math
import typing


def _require_aalink () -> typing.Any:
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

	Made on the running event loop, which aalink takes for itself: from 0.2 it
	warns whenever it is handed one, so every Link session raised a
	DeprecationWarning (#3555).

	Parameters:
		bpm: Initial tempo in BPM (proposed to the Link session).
		quantum: Beat cycle length - 4.0 means one bar in 4/4 time.
	"""

	def __init__ (self, bpm: float, quantum: float) -> None:

		"""
		Join the Link session immediately, proposing *bpm* and setting the bar length to *quantum* beats.
		"""

		aalink = _require_aalink()
		self._link = aalink.Link(bpm)
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

	async def sync (self, period: float) -> float:
		"""Wait for the next Link beat that is a multiple of *period*, and return it.

		**A period, not a position.**  aalink resumes at the next *multiple* of
		its argument - aalink's own documentation gives ``sync(2)`` at beat 11.5
		resuming at 12 - and this was called with an absolute beat instead, so every pulse
		waited for a multiple of itself.  Pulse 0 waited for beat ``2 × quantum``,
		a bar late, and every pulse after it landed on a lattice twice as coarse
		as the one intended: the piece played at exactly half tempo, while the
		display went on showing the right BPM (#2993).

		So the sequencer steps with ``await sync(1 / PPQN)`` - the next pulse
		lattice point, wherever the session has got to - and reads the beat it
		is handed rather than assuming which one it asked for.
		"""
		return float(await self._link.sync(period))

	async def wait_for_bar (self) -> float:
		"""Wait for the next bar boundary and return the beat it fell on.

		``sync(quantum)`` IS "the next multiple of a bar", which is what this
		wants - no arithmetic of our own, and no boundary to get wrong.  The
		hand-computed one raised on aalink 0.2.3 for a zero or negative
		boundary, and on 0.2.2 and earlier hung with the GIL held; aalink
		returns 0.0 for it safely.
		"""
		return float(await self._link.sync(self._link.quantum))

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
