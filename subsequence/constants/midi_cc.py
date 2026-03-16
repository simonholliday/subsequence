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
"""

import typing

# ─── Common Continuous Controllers (MSB) ─────────────────────────────
BANK_SELECT_MSB = 0
MODULATION_WHEEL = 1
BREATH_CONTROLLER = 2
FOOT_CONTROLLER = 4
PORTAMENTO_TIME = 5
DATA_ENTRY_MSB = 6
VOLUME = 7
BALANCE = 8
PAN = 10
EXPRESSION = 11
EFFECT_CONTROL_1 = 12
EFFECT_CONTROL_2 = 13

# ─── General Purpose Controllers (MSB) ───────────────────────────────
GENERAL_PURPOSE_1 = 16
GENERAL_PURPOSE_2 = 17
GENERAL_PURPOSE_3 = 18
GENERAL_PURPOSE_4 = 19

# ─── Common Continuous Controllers (LSB) ─────────────────────────────
BANK_SELECT_LSB = 32
MODULATION_WHEEL_LSB = 33
BREATH_CONTROLLER_LSB = 34
FOOT_PEDAL_LSB = 36
PORTAMENTO_TIME_LSB = 37
DATA_ENTRY_LSB = 38

# ─── On/Off Switches (0-63=Off, 64-127=On) ───────────────────────────
SUSTAIN_PEDAL = 64
PORTAMENTO_ON_OFF = 65
SOSTENUTO_PEDAL = 66
SOFT_PEDAL = 67
LEGATO_PEDAL = 68
HOLD_2 = 69

# ─── Sound Controllers ───────────────────────────────────────────────
SOUND_VARIATION = 70
FILTER_RESONANCE = 71
RELEASE_TIME = 72
ATTACK_TIME = 73
FILTER_CUTOFF = 74
SOUND_CONTROL_6 = 75
SOUND_CONTROL_7 = 76
SOUND_CONTROL_8 = 77
SOUND_CONTROL_9 = 78
SOUND_CONTROL_10 = 79

# ─── General Purpose Controllers (LSB) ───────────────────────────────
GENERAL_PURPOSE_5 = 80
GENERAL_PURPOSE_6 = 81
GENERAL_PURPOSE_7 = 82
GENERAL_PURPOSE_8 = 83

# ─── Effect Controllers ──────────────────────────────────────────────
PORTAMENTO_CONTROL = 84
REVERB_DEPTH = 91
TREMOLO_DEPTH = 92
CHORUS_DEPTH = 93
CELESTE_DEPTH = 94
PHASER_DEPTH = 95

# ─── Parameter Control ───────────────────────────────────────────────
DATA_INCREMENT = 96
DATA_DECREMENT = 97
NRPN_LSB = 98
NRPN_MSB = 99
RPN_LSB = 100
RPN_MSB = 101

# ─── Channel Mode Messages ───────────────────────────────────────────
ALL_SOUND_OFF = 120
RESET_ALL_CONTROLLERS = 121
LOCAL_CONTROL_ON_OFF = 122
ALL_NOTES_OFF = 123
OMNI_MODE_OFF = 124
OMNI_MODE_ON = 125
MONO_MODE_ON = 126
POLY_MODE_ON = 127

# ─── Complete CC map ─────────────────────────────────────────────────
#
# Pass this dict to map string names to CC integers if needed.

GM_CC_MAP: typing.Dict[str, int] = {
	"bank_select_msb": BANK_SELECT_MSB,
	"modulation_wheel": MODULATION_WHEEL,
	"breath_controller": BREATH_CONTROLLER,
	"foot_controller": FOOT_CONTROLLER,
	"portamento_time": PORTAMENTO_TIME,
	"data_entry_msb": DATA_ENTRY_MSB,
	"volume": VOLUME,
	"balance": BALANCE,
	"pan": PAN,
	"expression": EXPRESSION,
	"effect_control_1": EFFECT_CONTROL_1,
	"effect_control_2": EFFECT_CONTROL_2,
	"general_purpose_1": GENERAL_PURPOSE_1,
	"general_purpose_2": GENERAL_PURPOSE_2,
	"general_purpose_3": GENERAL_PURPOSE_3,
	"general_purpose_4": GENERAL_PURPOSE_4,
	"bank_select_lsb": BANK_SELECT_LSB,
	"modulation_wheel_lsb": MODULATION_WHEEL_LSB,
	"breath_controller_lsb": BREATH_CONTROLLER_LSB,
	"foot_pedal_lsb": FOOT_PEDAL_LSB,
	"portamento_time_lsb": PORTAMENTO_TIME_LSB,
	"data_entry_lsb": DATA_ENTRY_LSB,
	"sustain_pedal": SUSTAIN_PEDAL,
	"portamento_on_off": PORTAMENTO_ON_OFF,
	"sostenuto_pedal": SOSTENUTO_PEDAL,
	"soft_pedal": SOFT_PEDAL,
	"legato_pedal": LEGATO_PEDAL,
	"hold_2": HOLD_2,
	"sound_variation": SOUND_VARIATION,
	"filter_resonance": FILTER_RESONANCE,
	"release_time": RELEASE_TIME,
	"attack_time": ATTACK_TIME,
	"filter_cutoff": FILTER_CUTOFF,
	"sound_control_6": SOUND_CONTROL_6,
	"sound_control_7": SOUND_CONTROL_7,
	"sound_control_8": SOUND_CONTROL_8,
	"sound_control_9": SOUND_CONTROL_9,
	"sound_control_10": SOUND_CONTROL_10,
	"general_purpose_5": GENERAL_PURPOSE_5,
	"general_purpose_6": GENERAL_PURPOSE_6,
	"general_purpose_7": GENERAL_PURPOSE_7,
	"general_purpose_8": GENERAL_PURPOSE_8,
	"portamento_control": PORTAMENTO_CONTROL,
	"reverb_depth": REVERB_DEPTH,
	"tremolo_depth": TREMOLO_DEPTH,
	"chorus_depth": CHORUS_DEPTH,
	"celeste_depth": CELESTE_DEPTH,
	"phaser_depth": PHASER_DEPTH,
	"data_increment": DATA_INCREMENT,
	"data_decrement": DATA_DECREMENT,
	"nrpn_lsb": NRPN_LSB,
	"nrpn_msb": NRPN_MSB,
	"rpn_lsb": RPN_LSB,
	"rpn_msb": RPN_MSB,
	"all_sound_off": ALL_SOUND_OFF,
	"reset_all_controllers": RESET_ALL_CONTROLLERS,
	"local_control_on_off": LOCAL_CONTROL_ON_OFF,
	"all_notes_off": ALL_NOTES_OFF,
	"omni_mode_off": OMNI_MODE_OFF,
	"omni_mode_on": OMNI_MODE_ON,
	"mono_mode_on": MONO_MODE_ON,
	"poly_mode_on": POLY_MODE_ON,
}
