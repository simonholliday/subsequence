"""Held-note tracking for live MIDI note input.

``HeldNotes`` maintains the set of MIDI notes a player is currently holding
on a ``note_input`` keyboard, so an arpeggiator (or any pattern) can read the
live pitch set each cycle via ``p.held_notes()``.

It is a tiny, dependency-free state machine.  All of its state lives on the
sequencer loop thread: the mido callback thread only appends raw note events
to a deque, which the loop drains and feeds here.  Because it is never touched
from two threads, it needs no locking — and because it takes the current time
as an argument (rather than reading the clock itself), it is fully
deterministic and trivial to unit-test.

Two smoothing behaviours guard against the arp dropping to silence:

* **``release_ms`` debounce** — a just-released note lingers in the held set
  for a short window, so the momentary all-keys-up gap during a hand-position
  changeover does not register as "nothing held".
* **``latch``** — the held set persists after release until a *new* chord is
  started (the first key pressed after every key is up replaces it), like a
  hardware arp's latch / a sustain pedal.  Under ``latch`` the ``release_ms``
  window is unused — latch dominates.
"""

import typing


class HeldNotes:

	"""The live set of notes held on a ``note_input`` keyboard."""

	def __init__ (self, release_ms: float = 0.0, latch: bool = False) -> None:

		"""Create a held-note tracker.

		Parameters:
			release_ms: How long (milliseconds) a released note keeps counting
				as held, smoothing the gap during hand-position changes.  0
				removes a note the instant its note-off arrives.  Ignored when
				``latch`` is True.
			latch: When True, the held set persists after release until the
				next chord is started.
		"""

		self._release_s: float = max(0.0, release_ms) / 1000.0
		self._latch: bool = latch
		# pitch -> velocity for notes physically down right now.
		self._on: typing.Dict[int, int] = {}
		# pitch -> perf_counter deadline for just-released notes (debounce window).
		self._releasing: typing.Dict[int, float] = {}
		# pitch -> velocity for the latched chord (latch mode only).
		self._latched: typing.Dict[int, int] = {}

	def note_on (self, pitch: int, velocity: int, now: float) -> None:

		"""Register a note-on (``now`` = a perf_counter timestamp)."""

		self._releasing.pop(pitch, None)
		if self._latch and not self._on:
			# First key after every key was up — start a fresh latched chord.
			self._latched.clear()
		self._on[pitch] = velocity

	def note_off (self, pitch: int, now: float) -> None:

		"""Register a note-off (``now`` = a perf_counter timestamp)."""

		velocity = self._on.pop(pitch, None)
		if velocity is None:
			return
		if self._latch:
			self._latched[pitch] = velocity
		elif self._release_s > 0.0:
			self._releasing[pitch] = now + self._release_s

	def snapshot (self, now: float) -> typing.List[int]:

		"""Return the currently held MIDI notes, sorted ascending.

		Combines notes physically down, any still within the ``release_ms``
		debounce window at ``now``, and the latched chord.  Expired
		release-window notes are pruned as a side effect.
		"""

		held: typing.Set[int] = set(self._on)
		held.update(self._latched)
		if self._releasing:
			for pitch in [p for p, deadline in self._releasing.items() if deadline <= now]:
				del self._releasing[pitch]
			held.update(self._releasing)
		return sorted(held)
