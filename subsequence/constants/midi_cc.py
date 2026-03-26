"""General MIDI Continuous Controller (CC) constants.

Standard MIDI CC assignments (0-127). These are supported by virtually all GM-compatible
instruments, synthesizers, and DAWs.

Two ways to use this module:

1. **As constants** - reference CC numbers directly when sending raw MIDI or mapping features::

	import subsequence.constants.midi_cc as cc

	@composition.pattern(...)
	def sweep (p):
		p.cc(cc.FILTER_CUTOFF, 127)

2. **As a lookup map** - pass ``GM_CC_MAP`` if you want to allow string-based mapping in your extensions::

	print(subsequence.constants.midi_cc.GM_CC_MAP["filter_cutoff"]) # 74

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

import typing

# Re-export everything from pymididefs.cc — all CC constants and the lookup dict.
from pymididefs.cc import *  # noqa: F401,F403
from pymididefs.cc import CC_MAP  # noqa: F401

# ─── Backward-compatibility aliases ─────────────────────────────────────────
# Subsequence used FOOT_PEDAL_LSB; pymididefs uses FOOT_CONTROLLER_LSB.
FOOT_PEDAL_LSB = FOOT_CONTROLLER_LSB  # noqa: F405

# Subsequence exposed the lookup dict as GM_CC_MAP; pymididefs uses CC_MAP.
GM_CC_MAP: typing.Dict[str, int] = {
	**CC_MAP,
	"foot_pedal_lsb": FOOT_PEDAL_LSB,
}
