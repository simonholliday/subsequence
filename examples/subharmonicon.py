"""Moog Subharmonicon - compositional emulation in Subsequence.

The Moog Subharmonicon is built around two interlocking ideas:

  1. SUBHARMONIC OSCILLATORS - each of the two VCOs has two sub-oscillators
     whose pitch equals the VCO frequency divided by an integer (1–16),
     producing mathematically related undertones below the fundamental.

  2. POLYRHYTHMIC CLOCK DIVISION - four independent rhythm generators each
     divide the master tempo by an integer (1–16).  Any combination of
     generators can be routed to drive either or both of the two 4-step
     sequencers, creating complex trigger patterns from simple arithmetic.

This file exposes every Subharmonicon compositional control as a named Python
variable.  Static controls sit at the top.  VELOCITY_SWELL is driven by a
Conductor LFO to create a natural dynamic ebb and flow over time.

─── POLYPHONY AND MIDI CHANNEL ROUTING ──────────────────────────────────────

The Subharmonicon has six simultaneous sound sources per trigger event:
  VCO1 · VCO1 SUB1 · VCO1 SUB2   (Sequencer 1 group)
  VCO2 · VCO2 SUB1 · VCO2 SUB2   (Sequencer 2 group)

Each voice is registered as its own pattern so that its MIDI channel can be
set independently.  Three common routing configurations:

  TWO CHANNELS (default, channels 1 and 2)
    Set all VCO1 group variables to channel 1 and all VCO2 group variables to
    channel 2.  Each channel receives up to 3 simultaneous notes per trigger;
    a 3-voice polyphonic instrument is needed on each channel.

  SIX CHANNELS (one mono synth per voice)
    Assign each of the six channel variables below a unique MIDI channel (1–6).
    Every instrument receives exactly one note at a time - any mono synth works.
    This most closely mirrors the Subharmonicon's six independent signal paths.

  ONE CHANNEL (maximum polyphony)
    Set all six channel variables to 1.  The instrument receives up to 6
    simultaneous notes and needs at least 6-voice polyphony.
"""

import logging
import math

import subsequence
import subsequence.constants.durations as dur
import subsequence.constants.midi_notes as midi_notes

logging.basicConfig(level=logging.INFO)


# ─── MIDI CHANNEL ROUTING ─────────────────────────────────────────────────────
# Default: two-channel setup (channels 1 and 2).
# For six mono instruments, assign each a unique channel (e.g. 1 through 6).

VCO1_CHANNEL      = 1   # VCO1 main oscillator
VCO1_SUB1_CHANNEL = 1   # VCO1 first subharmonic oscillator
VCO1_SUB2_CHANNEL = 1   # VCO1 second subharmonic oscillator

VCO2_CHANNEL      = 2   # VCO2 main oscillator
VCO2_SUB1_CHANNEL = 2   # VCO2 first subharmonic oscillator
VCO2_SUB2_CHANNEL = 2   # VCO2 second subharmonic oscillator


# ─── STATIC SUBHARMONICON CONTROLS ───────────────────────────────────────────

# TEMPO: Master clock rate in beats per minute.  All four rhythm generators
# derive their rates by dividing this value by an integer.  The sequencers
# advance on each pulse from their assigned rhythm generators.
# Subharmonicon range: 20–3000 BPM (internal clock, 1 pulse per quarter note).
TEMPO = 120

# VCO1_FREQ / VCO2_FREQ: Base pitch of each oscillator as a MIDI note number.
# All subharmonic oscillators derive their pitch from this value.  On the
# hardware, this is the VCO FREQ knob.  Sequencer steps are offsets from here.
# Range: 0–127 (MIDI note number).  Middle C = 60.
VCO1_FREQ = midi_notes.C4
VCO2_FREQ = midi_notes.G3

# VCO1_SUB1_FREQ / VCO1_SUB2_FREQ / VCO2_SUB1_FREQ / VCO2_SUB2_FREQ:
# Integer divisor for each subharmonic oscillator.
# Subharmonic pitch = parent VCO pitch ÷ divisor.
# Subharmonicon range: 1–16.
#
# Approximate musical intervals below the parent VCO (rounded to nearest semitone):
#   Divisor  1  = unison           (0 semitones)
#   Divisor  2  = octave below     (−12)
#   Divisor  3  = 12th below       (−19, octave + perfect fifth)
#   Divisor  4  = two octaves down (−24)
#   Divisor  5  = two octaves + major 3rd below (−28)
#   Divisor  6  = two octaves + minor 7th below (−31)
#   Divisor  8  = three octaves down (−36)
#   Divisor 16  = four octaves down  (−48)
VCO1_SUB1_FREQ = 2   # Octave below VCO1
VCO1_SUB2_FREQ = 3   # A 12th below VCO1 (octave + fifth)

VCO2_SUB1_FREQ = 2   # Octave below VCO2
VCO2_SUB2_FREQ = 4   # Two octaves below VCO2

# SEQ1_STEPS / SEQ2_STEPS: The four absolute pitches of each sequencer as MIDI
# note numbers.  On the hardware, the four STEP knobs set relative offsets from
# VCO_FREQ; here, enter the resulting absolute pitches directly.
# Stay within ±SEQ_OCT octaves of VCO_FREQ for authentic behaviour.
# List of exactly 4 MIDI note numbers.
SEQ1_STEPS = [
	midi_notes.C4,
	midi_notes.E4,
	midi_notes.G4,
	midi_notes.C5,
]

SEQ2_STEPS = [
	midi_notes.G3,
	midi_notes.C4,
	midi_notes.D4,
	midi_notes.G4,
]

# SEQ_OCT: Octave range available to the STEP knobs, shared by both sequencers.
# This is a reference constraint for choosing SEQ1_STEPS / SEQ2_STEPS values -
# on the hardware it limits how far each step can deviate from VCO_FREQ.
# Options: 1 (±1 octave), 2 (±2 octaves), 5 (±5 octaves).
SEQ_OCT = 2

# QUANTIZE_MODE: Scale applied to all sequencer pitch output.
# The Subharmonicon has four quantize modes; the closest Subsequence equivalents:
#   "12-ET" (chromatic equal temperament)   → "major"  (or any 12-note mode)
#   "8-ET"  (diatonic equal temperament)    → "major"
#   "12-JI" (chromatic just intonation)     → "major"  (approximated in MIDI)
#   "8-JI"  (diatonic just intonation)      → "major"  (approximated in MIDI)
#   None    (unquantized / continuous)      → None
# Any valid subsequence scale mode string is accepted.
QUANTIZE_ROOT = "C"
QUANTIZE_MODE = None   # None for unquantized; e.g. "major", "minor_pentatonic"

# SEQ1_ASSIGN_OSC1: When True, SEQ1 steps control VCO1's pitch.
# When False, VCO1 plays at VCO1_FREQ every step (no pitch variation from SEQ1).
SEQ1_ASSIGN_OSC1 = True

# SEQ1_ASSIGN_SUB1 / SEQ1_ASSIGN_SUB2: When True, the sub-oscillators follow
# the stepped VCO1 pitch, maintaining their harmonic relationship to the current
# step.  When False, the sub plays at its fixed divisor from VCO1_FREQ only.
SEQ1_ASSIGN_SUB1 = True
SEQ1_ASSIGN_SUB2 = True

SEQ2_ASSIGN_OSC2 = True
SEQ2_ASSIGN_SUB1 = True
SEQ2_ASSIGN_SUB2 = True

# RHYTHM1_DIV through RHYTHM4_DIV: Integer clock divisor for each rhythm
# generator.  The generator fires a clock pulse every N master clock ticks
# (quarter notes).  Lower values = faster rhythm; higher values = slower.
#   Divisor  1 = fires every quarter note (same rate as TEMPO)
#   Divisor  2 = every half note
#   Divisor  3 = every dotted half note
#   Divisor  4 = every whole note (one bar in 4/4)
#   Divisor  8 = every two bars
#   Divisor 16 = every four bars
# Subharmonicon range: 1–16.
RHYTHM1_DIV = 3
RHYTHM2_DIV = 4
RHYTHM3_DIV = 5
RHYTHM4_DIV = 7

# RHYTHM*_SEQ1 / RHYTHM*_SEQ2: Route each rhythm generator to SEQ1, SEQ2,
# or both.  The sequencer advances whenever any assigned generator fires.
# If no generator is assigned to a sequencer, that sequencer will not play.
RHYTHM1_SEQ1 = True
RHYTHM1_SEQ2 = False

RHYTHM2_SEQ1 = True
RHYTHM2_SEQ2 = True

RHYTHM3_SEQ1 = False
RHYTHM3_SEQ2 = True

RHYTHM4_SEQ1 = False
RHYTHM4_SEQ2 = False

# RHYTHM_LOGIC: How to combine multiple rhythm generators driving the same
# sequencer.
#   "OR"  (default) - advance on any trigger, even simultaneous ones.
#                     Subharmonicon factory default (MIDI CC 113 value 0–63).
#   "XOR"           - advance only when exactly one generator fires; if two
#                     fire at the same tick, neither advances the sequencer.
#                     Subharmonicon CC 113 value 64–127.
RHYTHM_LOGIC = "OR"

# NOTE_DURATION: How long each note sounds, in beats.  On the Subharmonicon
# this is shaped by the VCA EG DECAY and ATTACK knobs.  A value near 1.0
# (full quarter note) gives a sustained feel; lower values create staccato.
# Range: 0.0–(very large float, notes can overlap).
NOTE_DURATION = dur.QUARTER * 0.85


# ─── CONDUCTOR-DRIVEN CONTROLS ────────────────────────────────────────────────

composition = subsequence.Composition(bpm=TEMPO, key=QUANTIZE_ROOT)

# VELOCITY_SWELL: Slowly modulates note velocity across all voices, creating
# a natural dynamic arc over time - analogous to slowly sweeping the VCA EG AMT
# or the individual oscillator LEVEL knobs on the Subharmonicon during a
# performance.  Adjust cycle_beats for faster or slower swells.
# Range: 0–127 (MIDI velocity).
composition.conductor.lfo("VELOCITY_SWELL", shape="sine", cycle_beats=16,
	min_val=55, max_val=105)


# ─── PHYSICAL CONTROLLER MAPPING (OPTIONAL) ───────────────────────────────────
# The Subharmonicon's controls can be driven from a physical MIDI controller
# using cc_map().  VELOCITY_SWELL is the most natural candidate - a single
# expression pedal or fader replaces the LFO above.
#
# Integer parameters (SUB FREQ divisors, RHYTHM DIV) can also be mapped, but
# note that CC values are continuous (0–127) and will need rounding when read.
# For example, cc_map(20, "VCO1_SUB1_FREQ", min_val=1, max_val=16) maps a
# knob to divisor 1–16, but intermediate float values will appear in p.data
# until rounded in the pattern code.
#
# To enable: uncomment the block below, replace "My Controller" with the exact
# name of your MIDI input device, and assign your CC numbers to match the knobs
# you want to use.  Then comment out the lfo() line above, since the hardware
# control will take over that signal.
#
# composition.midi_input("My Controller")
#
# composition.cc_map(7, "VELOCITY_SWELL", min_val=55, max_val=105)
#
# Any CC number (0–127) is valid.  Check your controller's documentation or
# MIDI monitor software to find the CC number each knob transmits.


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _subharmonic_note (base_midi, divisor):
	"""Return the MIDI note of a subharmonic oscillator at base_midi ÷ divisor.

	The Subharmonicon's sub-oscillators generate undertones at integer fractions
	of the parent VCO pitch.  Divisor 1 = unison, 2 = one octave below, etc.

	MIDI is integer semitones, so irrational subharmonics (÷3, ÷5, ÷6, etc.)
	are rounded to the nearest semitone - the same approximation the hardware
	makes when MIDI CC controls the SUB FREQ integer value.
	"""
	if divisor <= 1:
		return base_midi
	# The formula: there are 12 semitones per octave, and dividing a frequency
	# by N lowers the pitch by log₂(N) octaves.  So the MIDI note offset is
	# 12 × log₂(N) semitones below the fundamental.  round() snaps to the
	# nearest semitone (MIDI can only represent whole semitones).
	return round(base_midi - 12 * math.log2(divisor))


def _compute_triggers (divisors, logic="OR"):
	"""Return (trigger_steps, cycle_length) for a set of rhythm generator divisors.

	Each divisor N produces a clock that fires every N master ticks (quarter
	notes).  cycle_length is math.lcm(*divisors) - the full polyrhythmic period
	in quarter notes.  trigger_steps is the sorted list of tick positions within
	that period at which the sequencer advances.

	logic="OR":  advance on any tick from any generator (Subharmonicon default).
	logic="XOR": advance only when exactly one generator fires; simultaneous
	             pulses from different generators cancel each other out.
	"""
	if not divisors:
		return [], 1

	# math.lcm() finds the Lowest Common Multiple of all divisors - this is
	# the number of master clock ticks before the combined polyrhythm repeats.
	# For example, divisors 3 and 4 → LCM = 12 (the pattern repeats every 12
	# quarter notes).
	cycle    = math.lcm(*divisors)

	# Build a set of tick positions for each rhythm generator.
	# range(0, cycle, d) produces every d-th tick: divisor 3 over 12 ticks
	# gives {0, 3, 6, 9}, divisor 4 gives {0, 4, 8}.
	tick_sets = [set(range(0, cycle, d)) for d in divisors]

	if logic == "OR":
		# OR: the sequencer advances on any tick from any generator.
		# set().union() merges all tick sets into one; sorted() puts them in
		# time order.  Example: {0, 3, 6, 9} ∪ {0, 4, 8} = {0, 3, 4, 6, 8, 9}.
		merged = sorted(set().union(*tick_sets))
	else:
		# XOR: only ticks where exactly one generator fires count.
		# If two generators fire at the same tick, they cancel out.
		merged = sorted(t for t in range(cycle)
		                if sum(t in s for s in tick_sets) == 1)

	return merged, cycle


# ─── POLYRHYTHM COMPUTATION ───────────────────────────────────────────────────
# Collect which rhythm generator divisors are routed to each sequencer, then
# compute the merged trigger pattern and cycle length for each.

# Gather the clock divisors routed to each sequencer.  This pairs each
# RHYTHM*_DIV value with its RHYTHM*_SEQ1/SEQ2 switch, then keeps only the
# divisors whose switch is True.  For example, if RHYTHM1 (÷3) and RHYTHM2
# (÷4) are routed to SEQ1, seq1_divs will be [3, 4].
seq1_divs = [d for d, on in [
	(RHYTHM1_DIV, RHYTHM1_SEQ1), (RHYTHM2_DIV, RHYTHM2_SEQ1),
	(RHYTHM3_DIV, RHYTHM3_SEQ1), (RHYTHM4_DIV, RHYTHM4_SEQ1),
] if on]

seq2_divs = [d for d, on in [
	(RHYTHM1_DIV, RHYTHM1_SEQ2), (RHYTHM2_DIV, RHYTHM2_SEQ2),
	(RHYTHM3_DIV, RHYTHM3_SEQ2), (RHYTHM4_DIV, RHYTHM4_SEQ2),
] if on]

seq1_triggers, seq1_cycle = _compute_triggers(seq1_divs, RHYTHM_LOGIC)
seq2_triggers, seq2_cycle = _compute_triggers(seq2_divs, RHYTHM_LOGIC)


# ─── SEQ 1 GROUP: VCO1 · VCO1 SUB1 · VCO1 SUB2 ──────────────────────────────
# Each voice registers its own pattern so that MIDI channel routing is fully
# independent.  When voices share a channel the instrument needs polyphony;
# when each has its own channel any mono synth works.
#
# The step counter advances globally across pattern cycles using p.cycle, so
# the sequencer correctly steps through all four pitches even when the trigger
# pattern repeats on a cycle shorter than four steps.

if seq1_triggers:

	if SEQ1_ASSIGN_OSC1:

		@composition.pattern(channel=VCO1_CHANNEL, steps=seq1_cycle, unit=dur.QUARTER)
		def vco1 (p):
			# p.signal() reads the current value of a Conductor LFO - a slowly
			# changing parameter that evolves over time (see VELOCITY_SWELL above).
			vel = round(p.signal("VELOCITY_SWELL"))

			# Walk through each trigger position in the polyrhythmic cycle.
			# enumerate() gives us both the index (trigger_idx) and the beat
			# position (tick) of each trigger.
			for trigger_idx, tick in enumerate(seq1_triggers):

				# Step counter: the sequencer has 4 steps and cycles through them
				# endlessly.  p.cycle counts how many times this pattern has been
				# rebuilt (i.e., which loop of the polyrhythmic cycle we're on).
				# Multiplying by the number of triggers per cycle and adding the
				# current trigger index gives a global trigger count, then % 4
				# wraps it back to a 4-step sequence.
				step  = (p.cycle * len(seq1_triggers) + trigger_idx) % 4
				pitch = SEQ1_STEPS[step]
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)

			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)

	if SEQ1_ASSIGN_SUB1:

		@composition.pattern(channel=VCO1_SUB1_CHANNEL, steps=seq1_cycle, unit=dur.QUARTER)
		def vco1_sub1 (p):
			vel = round(p.signal("VELOCITY_SWELL"))
			for trigger_idx, tick in enumerate(seq1_triggers):
				# Step counter - same logic as vco1 above.
				step = (p.cycle * len(seq1_triggers) + trigger_idx) % 4

				# If SEQ1 is assigned to control VCO1's pitch, the sub-oscillator
				# follows the stepped pitch.  Otherwise it stays at VCO1_FREQ.
				# (The "X if condition else Y" syntax is Python's inline if/else.)
				vco_pitch = SEQ1_STEPS[step] if SEQ1_ASSIGN_OSC1 else VCO1_FREQ
				pitch     = _subharmonic_note(vco_pitch, VCO1_SUB1_FREQ)
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)
			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)

	if SEQ1_ASSIGN_SUB2:

		@composition.pattern(channel=VCO1_SUB2_CHANNEL, steps=seq1_cycle, unit=dur.QUARTER)
		def vco1_sub2 (p):
			# Same structure as vco1_sub1 - see comments there.
			vel = round(p.signal("VELOCITY_SWELL"))
			for trigger_idx, tick in enumerate(seq1_triggers):
				step      = (p.cycle * len(seq1_triggers) + trigger_idx) % 4
				vco_pitch = SEQ1_STEPS[step] if SEQ1_ASSIGN_OSC1 else VCO1_FREQ
				pitch     = _subharmonic_note(vco_pitch, VCO1_SUB2_FREQ)
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)
			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)


# ─── SEQ 2 GROUP: VCO2 · VCO2 SUB1 · VCO2 SUB2 ──────────────────────────────
# Mirrors SEQ1 group above - see comments there for detailed explanations of
# the step counter, ternary pitch selection, and subharmonic calculation.

if seq2_triggers:

	if SEQ2_ASSIGN_OSC2:

		@composition.pattern(channel=VCO2_CHANNEL, steps=seq2_cycle, unit=dur.QUARTER)
		def vco2 (p):
			vel = round(p.signal("VELOCITY_SWELL"))
			for trigger_idx, tick in enumerate(seq2_triggers):
				step  = (p.cycle * len(seq2_triggers) + trigger_idx) % 4
				pitch = SEQ2_STEPS[step]
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)
			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)

	if SEQ2_ASSIGN_SUB1:

		@composition.pattern(channel=VCO2_SUB1_CHANNEL, steps=seq2_cycle, unit=dur.QUARTER)
		def vco2_sub1 (p):
			vel = round(p.signal("VELOCITY_SWELL"))
			for trigger_idx, tick in enumerate(seq2_triggers):
				step      = (p.cycle * len(seq2_triggers) + trigger_idx) % 4
				vco_pitch = SEQ2_STEPS[step] if SEQ2_ASSIGN_OSC2 else VCO2_FREQ
				pitch     = _subharmonic_note(vco_pitch, VCO2_SUB1_FREQ)
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)
			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)

	if SEQ2_ASSIGN_SUB2:

		@composition.pattern(channel=VCO2_SUB2_CHANNEL, steps=seq2_cycle, unit=dur.QUARTER)
		def vco2_sub2 (p):
			vel = round(p.signal("VELOCITY_SWELL"))
			for trigger_idx, tick in enumerate(seq2_triggers):
				step      = (p.cycle * len(seq2_triggers) + trigger_idx) % 4
				vco_pitch = SEQ2_STEPS[step] if SEQ2_ASSIGN_OSC2 else VCO2_FREQ
				pitch     = _subharmonic_note(vco_pitch, VCO2_SUB2_FREQ)
				p.hit_steps(pitch, [tick], velocity=vel, duration=NOTE_DURATION)
			if QUANTIZE_MODE:
				p.quantize(QUANTIZE_ROOT, QUANTIZE_MODE)


if __name__ == "__main__":

	composition.display(grid=True, grid_scale=4)
	composition.web_ui()
	composition.play()
