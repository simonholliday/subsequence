"""Vermona DRM1 MKIV drum note map.

Note assignments for the Vermona DRM1 analog drum synthesizer.
These note numbers correspond to the factory default trigger assignments.

Two ways to use this module:

1. **As a drum_note_map** - pass ``VERMONA_DRM1_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"kick"``
   or ``"snare"`` in your pattern builder calls::

       import subsequence.constants.instruments.vermona_drm1_drums as drm1

       @composition.pattern(channel=9, length=4, drum_note_map=drm1.VERMONA_DRM1_DRUM_MAP)
       def drums (p):
           p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

2. **As constants** - reference note numbers directly::

       import subsequence.constants.instruments.vermona_drm1_drums as drm1

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(drm1.KICK, [0, 4, 8, 12], velocity=127)

``VERMONA_DRM1_DRUM_MAP`` also accepts a *faithful* subset of General MIDI drum
names (e.g. ``"kick_1"``, ``"snare_1"``, ``"hi_hat_closed"``) as aliases — only
for the voices the DRM1 genuinely has (kick, snare, clap, hi-hats).  These
shared GM names are what let the DRM1 take part in symbolic mirroring (each
device re-resolves a drum name through its own map).  GM names for instruments
the DRM1 lacks (toms, ride/crash cymbals, shakers, cowbell and other latin/aux
percussion) are intentionally NOT aliased — naming one anyway is dropped with
a one-time warning (never a wrong voice); address those by their native
``drum_1`` / ``drum_2`` / ``multi`` names.  Canonical GM names come from
`pymididefs.drums <https://github.com/simonholliday/PyMidiDefs>`_ (``GM_DRUM_MAP``).
"""

import typing


# ─── Individual note constants ───────────────────────────────────────

KICK = 36                # C2
DRUM_1 = 45              # A2
DRUM_2 = 50              # D3
MULTI = 56               # G#3
SNARE = 38               # D2
HIHAT_1_CLOSED = 44      # G#2
HIHAT_1_OPEN = 46        # A#2 (Cymbal)
HIHAT_2_CLOSED = 49      # C#3
HIHAT_2_OPEN = 51        # D#3 (Cymbal)
CLAP = 39                # D#2


# ─── Complete drum note map ──────────────────────────────────────────

VERMONA_DRM1_DRUM_MAP: typing.Dict[str, int] = {
	# Native DRM1 mapping
	"kick": KICK,
	"drum_1": DRUM_1,
	"drum_2": DRUM_2,
	"multi": MULTI,
	"snare": SNARE,
	"hihat_1_closed": HIHAT_1_CLOSED,
	"hihat_1_open": HIHAT_1_OPEN,
	"hihat_2_closed": HIHAT_2_CLOSED,
	"hihat_2_open": HIHAT_2_OPEN,
	"clap": CLAP,

	# General MIDI aliases — *faithful correspondences only*, i.e. GM names for
	# the voices the DRM1 genuinely has.  Canonical names come from
	# ``pymididefs.drums`` (``GM_DRUM_MAP``); this is the shared vocabulary used
	# by symbolic mirroring (each device re-resolves a drum name through its own
	# map).  GM names for instruments the DRM1 lacks — toms, ride/crash cymbals,
	# shakers, and latin/aux percussion — are deliberately NOT aliased: a
	# "creative approximation" onto an unrelated voice (cowbell -> multi,
	# cymbal -> hi-hat) was an over-reach.  Use the native ``drum_1`` /
	# ``drum_2`` / ``multi`` names for those instead.
	"kick_1": KICK,
	"kick_2": KICK,
	"snare_1": SNARE,
	"snare_2": SNARE,
	"hand_clap": CLAP,			# GM 39 == DRM1 CLAP 39
	"hi_hat_closed": HIHAT_1_CLOSED,
	"hi_hat_pedal": HIHAT_1_CLOSED,		# foot-closed hat -> the closed hi-hat voice
	"hi_hat_open": HIHAT_1_OPEN,
}
