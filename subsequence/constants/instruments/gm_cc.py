"""General MIDI Continuous Controller (CC) constants.

Standard MIDI CC assignments (0-127). These are supported by virtually all GM-compatible
instruments, synthesizers, and DAWs.

Two ways to use this module:

1. **As constants** - reference CC numbers directly when sending MIDI CC messages::

	import subsequence.constants.instruments.gm_cc as gm_cc

	@composition.pattern(...)
	def sweep (p):
		p.cc(gm_cc.FILTER_CUTOFF, 127)

2. **As a cc_name_map** - pass ``GM_CC_MAP`` to the ``cc_name_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"filter_cutoff"``
   or ``"sustain_pedal"`` in your CC calls::

	import subsequence.constants.instruments.gm_cc as gm_cc

	@composition.pattern(channel=1, beats=4, cc_name_map=gm_cc.GM_CC_MAP)
	def synth (p):
		p.cc("filter_cutoff", 100)
		p.cc_ramp("expression", 0, 127, shape="ease_in")

Canonical source: `pymididefs <https://github.com/simonholliday/PyMidiDefs>`_.
"""

import typing

# Re-export everything from pymididefs.cc — all CC constants and the lookup dict.
from pymididefs.cc import *  # noqa: F401,F403
from pymididefs.cc import CC_MAP  # noqa: F401 — explicit re-export for type checkers

# ─── Backward-compatibility aliases ─────────────────────────────────────────
# Subsequence used FOOT_PEDAL_LSB; pymididefs uses FOOT_CONTROLLER_LSB.
FOOT_PEDAL_LSB = FOOT_CONTROLLER_LSB  # noqa: F405

# GM_CC_MAP extends the canonical CC_MAP with the backward-compat alias.
GM_CC_MAP: typing.Dict[str, int] = {
	**CC_MAP,
	"foot_pedal_lsb": FOOT_PEDAL_LSB,
}
