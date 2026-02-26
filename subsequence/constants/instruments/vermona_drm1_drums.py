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
	
	# GM Drums aliases (for drop-in compatibility).
	# 
	# This comprehensive mapping ensures that sequences written for standard
	# General MIDI kits will still produce sound when played on the DRM1,
	# avoiding "silent" beats. While some mappings are obvious (kick -> kick),
	# others are creative approximations (e.g., cymbals -> hi-hat 2 open, 
	# cowbell -> multi) designed to trigger the best available alternative
	# physical instrument channel.
	
	# Kicks
	"kick_1": KICK,
	"kick_2": KICK,
	
	# Snares & Claps
	"snare_1": SNARE,
	"snare_2": SNARE,
	"side_stick": SNARE,
	"hand_clap": CLAP,

	# Toms (Low toms -> Drum 1, Mid/High toms -> Drum 2)
	"low_floor_tom": DRUM_1,
	"high_floor_tom": DRUM_1,
	"low_tom": DRUM_1,
	"low_mid_tom": DRUM_2,
	"high_mid_tom": DRUM_2,
	"high_tom": DRUM_2,

	# Hi-Hats
	"hi_hat_closed": HIHAT_1_CLOSED,
	"hi_hat_pedal": HIHAT_1_CLOSED,
	"hi_hat_open": HIHAT_1_OPEN,

	# Ride & Crash Cymbals (Mapped to the 2nd Hi-Hat channel's open decay)
	"crash_1": HIHAT_2_OPEN,
	"crash_2": HIHAT_2_OPEN,
	"splash_cymbal": HIHAT_2_OPEN,
	"chinese_cymbal": HIHAT_2_OPEN,
	"ride_1": HIHAT_2_OPEN,
	"ride_2": HIHAT_2_OPEN,
	"ride_bell": HIHAT_2_OPEN,

	# Shakers & Tambourines (Mapped to 2nd Hi-Hat channel's closed decay)
	"tambourine": HIHAT_2_CLOSED,
	"cabasa": HIHAT_2_CLOSED,
	"maracas": HIHAT_2_CLOSED,
	"shaker": HIHAT_2_CLOSED,

	# Percussion (Cowbell, Woodblocks, Claves, Congas, etc. -> Multi channel)
	"cowbell": MULTI,
	"claves": MULTI,
	"high_woodblock": MULTI,
	"low_woodblock": MULTI,
	"high_bongo": MULTI,
	"low_bongo": MULTI,
	"mute_high_conga": MULTI,
	"open_high_conga": MULTI,
	"low_conga": MULTI,
	"high_timbale": MULTI,
	"low_timbale": MULTI,
	"high_agogo": MULTI,
	"low_agogo": MULTI,
	"mute_triangle": MULTI,
	"open_triangle": MULTI,
	"vibraslap": MULTI,
}
