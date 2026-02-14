"""General MIDI Level 1 drum note map.

Standard MIDI percussion assignments for channel 10 (0-indexed channel 9).
These note numbers are supported by virtually all GM-compatible instruments,
drum machines, and DAWs.

Two ways to use this module:

1. **As a drum_note_map** — pass ``GM_DRUM_MAP`` to the ``drum_note_map`` parameter
   of ``@composition.pattern()`` and use human-readable names like ``"kick_1"``
   or ``"snare_1"`` in your pattern builder calls::

       import subsequence.constants.gm_drums

       @composition.pattern(channel=9, length=4, drum_note_map=subsequence.constants.gm_drums.GM_DRUM_MAP)
       def drums (p):
           p.hit_steps("kick_1", [0, 4, 8, 12], velocity=127)

2. **As constants** — reference note numbers directly::

       import subsequence.constants.gm_drums

       @composition.pattern(channel=9, length=4)
       def drums (p):
           p.hit_steps(subsequence.constants.gm_drums.KICK_1, [0, 4, 8, 12], velocity=127)
"""

import typing


# ─── Individual note constants ───────────────────────────────────────
#
# General MIDI Level 1 percussion key map (notes 27-87).
# Names follow the GM specification with underscores for readability.

HIGH_Q = 27
SLAP = 28
SCRATCH_PUSH = 29
SCRATCH_PULL = 30
STICKS = 31
SQUARE_CLICK = 32
METRONOME_CLICK = 33
METRONOME_BELL = 34
KICK_2 = 35
KICK_1 = 36
SIDE_STICK = 37
SNARE_1 = 38
HAND_CLAP = 39
SNARE_2 = 40
LOW_FLOOR_TOM = 41
HI_HAT_CLOSED = 42
HIGH_FLOOR_TOM = 43
HI_HAT_PEDAL = 44
LOW_TOM = 45
HI_HAT_OPEN = 46
LOW_MID_TOM = 47
HIGH_MID_TOM = 48
CRASH_1 = 49
HIGH_TOM = 50
RIDE_1 = 51
CHINESE_CYMBAL = 52
RIDE_BELL = 53
TAMBOURINE = 54
SPLASH_CYMBAL = 55
COWBELL = 56
CRASH_2 = 57
VIBRASLAP = 58
RIDE_2 = 59
HIGH_BONGO = 60
LOW_BONGO = 61
MUTE_HIGH_CONGA = 62
OPEN_HIGH_CONGA = 63
LOW_CONGA = 64
HIGH_TIMBALE = 65
LOW_TIMBALE = 66
HIGH_AGOGO = 67
LOW_AGOGO = 68
CABASA = 69
MARACAS = 70
SHORT_WHISTLE = 71
LONG_WHISTLE = 72
SHORT_GUIRO = 73
LONG_GUIRO = 74
CLAVES = 75
HIGH_WOODBLOCK = 76
LOW_WOODBLOCK = 77
MUTE_CUICA = 78
OPEN_CUICA = 79
MUTE_TRIANGLE = 80
OPEN_TRIANGLE = 81
SHAKER = 82
JINGLE_BELL = 83
BELL_TREE = 84
CASTANETS = 85
MUTE_SURDO = 86
OPEN_SURDO = 87


# ─── Complete drum note map ──────────────────────────────────────────
#
# Pass this dict as the drum_note_map parameter to use string names
# in hit_steps(), hit(), note(), euclidean(), and bresenham().

GM_DRUM_MAP: typing.Dict[str, int] = {
	"high_q": HIGH_Q,
	"slap": SLAP,
	"scratch_push": SCRATCH_PUSH,
	"scratch_pull": SCRATCH_PULL,
	"sticks": STICKS,
	"square_click": SQUARE_CLICK,
	"metronome_click": METRONOME_CLICK,
	"metronome_bell": METRONOME_BELL,
	"kick_2": KICK_2,
	"kick_1": KICK_1,
	"side_stick": SIDE_STICK,
	"snare_1": SNARE_1,
	"hand_clap": HAND_CLAP,
	"snare_2": SNARE_2,
	"low_floor_tom": LOW_FLOOR_TOM,
	"hi_hat_closed": HI_HAT_CLOSED,
	"high_floor_tom": HIGH_FLOOR_TOM,
	"hi_hat_pedal": HI_HAT_PEDAL,
	"low_tom": LOW_TOM,
	"hi_hat_open": HI_HAT_OPEN,
	"low_mid_tom": LOW_MID_TOM,
	"high_mid_tom": HIGH_MID_TOM,
	"crash_1": CRASH_1,
	"high_tom": HIGH_TOM,
	"ride_1": RIDE_1,
	"chinese_cymbal": CHINESE_CYMBAL,
	"ride_bell": RIDE_BELL,
	"tambourine": TAMBOURINE,
	"splash_cymbal": SPLASH_CYMBAL,
	"cowbell": COWBELL,
	"crash_2": CRASH_2,
	"vibraslap": VIBRASLAP,
	"ride_2": RIDE_2,
	"high_bongo": HIGH_BONGO,
	"low_bongo": LOW_BONGO,
	"mute_high_conga": MUTE_HIGH_CONGA,
	"open_high_conga": OPEN_HIGH_CONGA,
	"low_conga": LOW_CONGA,
	"high_timbale": HIGH_TIMBALE,
	"low_timbale": LOW_TIMBALE,
	"high_agogo": HIGH_AGOGO,
	"low_agogo": LOW_AGOGO,
	"cabasa": CABASA,
	"maracas": MARACAS,
	"short_whistle": SHORT_WHISTLE,
	"long_whistle": LONG_WHISTLE,
	"short_guiro": SHORT_GUIRO,
	"long_guiro": LONG_GUIRO,
	"claves": CLAVES,
	"high_woodblock": HIGH_WOODBLOCK,
	"low_woodblock": LOW_WOODBLOCK,
	"mute_cuica": MUTE_CUICA,
	"open_cuica": OPEN_CUICA,
	"mute_triangle": MUTE_TRIANGLE,
	"open_triangle": OPEN_TRIANGLE,
	"shaker": SHAKER,
	"jingle_bell": JINGLE_BELL,
	"bell_tree": BELL_TREE,
	"castanets": CASTANETS,
	"mute_surdo": MUTE_SURDO,
	"open_surdo": OPEN_SURDO,
}
