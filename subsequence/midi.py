"""
Lightweight MIDI message constructors.

Provides factory functions that return ``mido.Message`` objects without
requiring users to import or interact with mido directly.  Intended for use
with ``composition.cc_forward()`` callable transforms and any other context
where a ``mido.Message`` is needed as a return value.

Example::

    import subsequence.midi as midi

    composition.cc_forward(1,
        lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch)
    )
"""

import typing
import mido


def cc (
	control: int,
	value: int,
	channel: int = 0,
) -> mido.Message:

	"""Create a MIDI Control Change message.

	Parameters:
		control: CC number (0–127).
		value: CC value (0–127).
		channel: MIDI channel (0-indexed, 0–15).  Defaults to 0.

	Returns:
		A ``mido.Message`` of type ``control_change``.

	Example:
		```python
		import subsequence.midi as midi

		# Forward CC 1 to CC 74, scaling range to 40–100
		composition.cc_forward(1,
		    lambda v, ch: midi.cc(74, int(v / 127 * 60) + 40, channel=ch)
		)
		```
	"""

	return mido.Message('control_change', channel=channel, control=control, value=value)


def pitchwheel (
	pitch: int,
	channel: int = 0,
) -> mido.Message:

	"""Create a MIDI Pitch Wheel message.

	Parameters:
		pitch: Pitch bend value (-8192 to 8191).  0 is centre (no bend).
		       Out-of-range values are clamped to the valid range.
		channel: MIDI channel (0-indexed, 0–15).  Defaults to 0.

	Returns:
		A ``mido.Message`` of type ``pitchwheel``.

	Example:
		```python
		import subsequence.midi as midi

		# Forward CC 1 as pitch bend, scaled to upper half only (0 to +8191)
		composition.cc_forward(1,
		    lambda v, ch: midi.pitchwheel(int(v / 127 * 8191), channel=ch)
		)
		```
	"""

	pitch = max(-8192, min(8191, pitch))
	return mido.Message('pitchwheel', channel=channel, pitch=pitch)


def program_change (
	program: int,
	channel: int = 0,
) -> mido.Message:

	"""Create a MIDI Program Change message.

	Parameters:
		program: Program number (0–127).
		channel: MIDI channel (0-indexed, 0–15).  Defaults to 0.

	Returns:
		A ``mido.Message`` of type ``program_change``.
	"""

	return mido.Message('program_change', channel=channel, program=program)
