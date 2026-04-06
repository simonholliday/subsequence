"""Roland TR-8S instrument definition.

Note assignments and CC mappings for the Roland TR-8S drum machine.
Note numbers correspond to the factory default trigger assignments
for the 11 instrument tracks.  CC numbers are from the official MIDI
Implementation Chart (Version 1.10, 2018-10-04).

Three ways to use this module:

1. **As a drum_note_map** - pass ``ROLAND_TR8S_DRUM_MAP`` to the ``drum_note_map``
   parameter of ``@composition.pattern()`` and use track names like ``"bd"``
   or ``"sd"`` in your pattern builder calls::

       import subsequence.constants.instruments.roland_tr8s as tr8s

       @composition.pattern(channel=9, beats=4, drum_note_map=tr8s.ROLAND_TR8S_DRUM_MAP)
       def drums (p):
           p.hit_steps("bd", [0, 4, 8, 12], velocity=127)

2. **As a cc_name_map** - pass ``ROLAND_TR8S_CC_MAP`` to the ``cc_name_map``
   parameter of ``@composition.pattern()`` and use human-readable CC names::

       import subsequence.constants.instruments.roland_tr8s as tr8s

       @composition.pattern(channel=9, beats=4,
           drum_note_map=tr8s.ROLAND_TR8S_DRUM_MAP,
           cc_name_map=tr8s.ROLAND_TR8S_CC_MAP)
       def drums (p):
           p.hit_steps("bd", [0, 4, 8, 12], velocity=127)
           p.cc("bd_tune", 64)
           p.cc_ramp("bd_decay", 40, 100, shape="ease_in")

3. **As constants** - reference note numbers and CC numbers directly::

       import subsequence.constants.instruments.roland_tr8s as tr8s

       p.hit_steps(tr8s.BD, [0, 4, 8, 12], velocity=127)
       p.cc(tr8s.BD_TUNE, 64)

Note: The TR-8S CC assignments are instrument-specific and overlap with
standard GM CC numbers in incompatible ways (e.g. CC 9 = Shuffle on the
TR-8S, not a standard GM assignment).  This map does NOT extend GM_CC_MAP.
"""

import typing


# ═══════════════════════════════════════════════════════════════════════
#  Drum note constants
# ═══════════════════════════════════════════════════════════════════════

BD = 36          # Bass Drum
SD = 38          # Snare Drum
LT = 43          # Low Tom
MT = 47          # Mid Tom
HT = 50          # High Tom
RS = 37          # Rim Shot
HC = 39          # Hand Clap
CH = 42          # Closed Hi-Hat
OH = 46          # Open Hi-Hat
CC = 49          # Crash Cymbal
RC = 51          # Ride Cymbal

# Alternate note numbers (configurable on UTILITY:MIDI:Inst Note)
BD_ALT = 35
SD_ALT = 40
LT_ALT = 41
MT_ALT = 45
HT_ALT = 48
RS_ALT = 56
HC_ALT = 54
CH_ALT = 44
OH_ALT = 55
CC_ALT = 61
RC_ALT = 63


# ═══════════════════════════════════════════════════════════════════════
#  CC constants — global controls
# ═══════════════════════════════════════════════════════════════════════

SHUFFLE            = 9    # Shuffle amount
EXTERNAL_IN_LEVEL  = 12   # External input level
AUTO_FILL_IN       = 14   # Auto fill in on/off
MASTER_FX_ON       = 15   # Master FX on/off
DELAY_LEVEL        = 16   # Delay send level
DELAY_TIME         = 17   # Delay time
DELAY_FEEDBACK     = 18   # Delay feedback
MASTER_FX_CTRL     = 19   # Master FX control knob
AUTO_FILL_IN_MANUAL = 70  # Auto fill in manual trigger
ACCENT             = 71   # Accent level
REVERB_LEVEL       = 91   # Reverb send level


# ═══════════════════════════════════════════════════════════════════════
#  CC constants — per-instrument (Tune / Decay / Level / Ctrl)
# ═══════════════════════════════════════════════════════════════════════

# Bass Drum
BD_TUNE  = 20
BD_DECAY = 23
BD_LEVEL = 24
BD_CTRL  = 96

# Snare Drum
SD_TUNE  = 25
SD_DECAY = 28
SD_LEVEL = 29
SD_CTRL  = 97

# Low Tom
LT_TUNE  = 46
LT_DECAY = 47
LT_LEVEL = 48
LT_CTRL  = 102

# Mid Tom
MT_TUNE  = 49
MT_DECAY = 50
MT_LEVEL = 51
MT_CTRL  = 103

# High Tom
HT_TUNE  = 52
HT_DECAY = 53
HT_LEVEL = 54
HT_CTRL  = 104

# Rim Shot
RS_TUNE  = 55
RS_DECAY = 56
RS_LEVEL = 57
RS_CTRL  = 105

# Hand Clap
HC_TUNE  = 58
HC_DECAY = 59
HC_LEVEL = 60
HC_CTRL  = 106

# Closed Hi-Hat
CH_TUNE  = 61
CH_DECAY = 62
CH_LEVEL = 63
CH_CTRL  = 107

# Open Hi-Hat
OH_TUNE  = 80
OH_DECAY = 81
OH_LEVEL = 82
OH_CTRL  = 108

# Crash Cymbal
CC_TUNE  = 83
CC_DECAY = 84
CC_LEVEL = 85
CC_CTRL  = 109

# Ride Cymbal
RC_TUNE  = 86
RC_DECAY = 87
RC_LEVEL = 88
RC_CTRL  = 110


# ═══════════════════════════════════════════════════════════════════════
#  Drum note map
# ═══════════════════════════════════════════════════════════════════════

ROLAND_TR8S_DRUM_MAP: typing.Dict[str, int] = {
	"bd": BD,
	"sd": SD,
	"lt": LT,
	"mt": MT,
	"ht": HT,
	"rs": RS,
	"hc": HC,
	"ch": CH,
	"oh": OH,
	"cc": CC,
	"rc": RC,
}


# ═══════════════════════════════════════════════════════════════════════
#  CC name map
# ═══════════════════════════════════════════════════════════════════════

ROLAND_TR8S_CC_MAP: typing.Dict[str, int] = {
	# Global controls
	"shuffle":              SHUFFLE,
	"external_in_level":    EXTERNAL_IN_LEVEL,
	"auto_fill_in":         AUTO_FILL_IN,
	"master_fx_on":         MASTER_FX_ON,
	"delay_level":          DELAY_LEVEL,
	"delay_time":           DELAY_TIME,
	"delay_feedback":       DELAY_FEEDBACK,
	"master_fx_ctrl":       MASTER_FX_CTRL,
	"auto_fill_in_manual":  AUTO_FILL_IN_MANUAL,
	"accent":               ACCENT,
	"reverb_level":         REVERB_LEVEL,

	# Bass Drum
	"bd_tune":  BD_TUNE,
	"bd_decay": BD_DECAY,
	"bd_level": BD_LEVEL,
	"bd_ctrl":  BD_CTRL,

	# Snare Drum
	"sd_tune":  SD_TUNE,
	"sd_decay": SD_DECAY,
	"sd_level": SD_LEVEL,
	"sd_ctrl":  SD_CTRL,

	# Low Tom
	"lt_tune":  LT_TUNE,
	"lt_decay": LT_DECAY,
	"lt_level": LT_LEVEL,
	"lt_ctrl":  LT_CTRL,

	# Mid Tom
	"mt_tune":  MT_TUNE,
	"mt_decay": MT_DECAY,
	"mt_level": MT_LEVEL,
	"mt_ctrl":  MT_CTRL,

	# High Tom
	"ht_tune":  HT_TUNE,
	"ht_decay": HT_DECAY,
	"ht_level": HT_LEVEL,
	"ht_ctrl":  HT_CTRL,

	# Rim Shot
	"rs_tune":  RS_TUNE,
	"rs_decay": RS_DECAY,
	"rs_level": RS_LEVEL,
	"rs_ctrl":  RS_CTRL,

	# Hand Clap
	"hc_tune":  HC_TUNE,
	"hc_decay": HC_DECAY,
	"hc_level": HC_LEVEL,
	"hc_ctrl":  HC_CTRL,

	# Closed Hi-Hat
	"ch_tune":  CH_TUNE,
	"ch_decay": CH_DECAY,
	"ch_level": CH_LEVEL,
	"ch_ctrl":  CH_CTRL,

	# Open Hi-Hat
	"oh_tune":  OH_TUNE,
	"oh_decay": OH_DECAY,
	"oh_level": OH_LEVEL,
	"oh_ctrl":  OH_CTRL,

	# Crash Cymbal
	"cc_tune":  CC_TUNE,
	"cc_decay": CC_DECAY,
	"cc_level": CC_LEVEL,
	"cc_ctrl":  CC_CTRL,

	# Ride Cymbal
	"rc_tune":  RC_TUNE,
	"rc_decay": RC_DECAY,
	"rc_level": RC_LEVEL,
	"rc_ctrl":  RC_CTRL,
}
