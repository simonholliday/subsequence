"""Moog Labyrinth - compositional emulation in Subsequence.

The Moog Labyrinth is a semi-modular analog synthesizer built around two
independent 8-step generative sequencers (SEQ1, SEQ2).  Each sequencer holds
a binary pattern (which steps are "on") and a random CV value per step,
quantized to a chosen scale.  A CORRUPT knob mutates those values over time;
an EG TRIG MIX crossfader balances which sequence drives the amplitude.

This file exposes every Labyrinth compositional control as a named Python
variable.  Static controls (length, scale, range) sit at the top.  Controls
that are most useful when they evolve slowly (CORRUPT, EG_TRIG_MIX) are
driven by Conductor LFOs - adjust the LFO parameters to change the sweep
rate and depth, just as you would turn a physical knob.

MIDI channel: 1.  Connect to any synthesizer.

Polyphony note: when CHAIN_SEQ is False (the default), SEQ1 and SEQ2 run on
independent cycle lengths and will occasionally fire notes simultaneously.  A
polyphonic instrument will voice both; a monophonic instrument will apply its
own voice-stealing or last-note priority logic.  Either works, but 2-voice
polyphony or more gives the most faithful representation of the Labyrinth's
two parallel signal paths.
"""

import logging

import subsequence
import subsequence.constants.durations as dur
import subsequence.chords
import subsequence.intervals

logging.basicConfig(level=logging.INFO)

CHANNEL = 1

# ─── STATIC LABYRINTH CONTROLS ───────────────────────────────────────────────

# TEMPO: Internal clock rate in beats per minute.
# Labyrinth range: approximately 20–240 BPM.
TEMPO = 125

# SEQ1_LENGTH / SEQ2_LENGTH: Number of active steps in each sequencer.
# The sequencer cycles through steps 1..N then wraps.  Shorter values create
# tighter, faster-repeating figures.  When CHAIN_SEQ is True the effective
# length is SEQ1_LENGTH + SEQ2_LENGTH (up to 16 steps).
# Labyrinth range: 1–8 per sequencer.
SEQ1_LENGTH = 7
SEQ2_LENGTH = 5

# SEQ1_UNIT / SEQ2_UNIT: Rhythmic value of each step.
# Labyrinth clocks both sequencers from the same master TEMPO, dividing the
# clock internally.  Changing the unit here alters the feel without touching
# the BPM.  dur.EIGHTH = eighth notes; dur.SIXTEENTH = twice as dense.
SEQ1_UNIT = dur.EIGHTH
SEQ2_UNIT = dur.EIGHTH

# QUANTIZE_ROOT: Root note for the quantizer applied to both sequencers.
# Labyrinth transposes the quantized output of both SEQ1 and SEQ2 when a
# MIDI Note On message is received.  In Subsequence, change this string to
# transpose the entire piece.
# String: "C", "D", "Eb", "F#", "Bb", etc.
QUANTIZE_ROOT = "C"

# QUANTIZE_MODE: Scale mode applied to random pitch values from both sequencers.
# Labyrinth has 15 built-in quantization modes.  Set to None for unquantized
# (chromatic - all 12 semitones available).
#
# Equivalents for Labyrinth's 15 modes:
#   Mode  1  Unquantized          → None
#   Mode  2  Chromatic            → None  (all semitones, same effect)
#   Mode  3  Major                → "major"
#   Mode  4  Pentatonic           → "major_pentatonic"
#   Mode  5  Melodic Minor        → "melodic_minor"
#   Mode  6  Harmonic Minor       → "harmonic_minor"
#   Mode  7  Diminished 6th       → "dorian"   (closest available)
#   Mode  8  Whole Tone           → "major"    (closest available)
#   Mode  9  Hirajoshi Pentatonic → "hirajoshi"
#   Mode 10  7 Sus 4              → "mixolydian"
#   Mode 11  Major 7th            → "major"
#   Mode 12  Major 13th           → "lydian"
#   Mode 13  Minor 7th            → "dorian"
#   Mode 14  Minor 11th           → "minor"    (aeolian)
#   Mode 15  Hang Drum            → "hirajoshi" (closest available)
#   Mode 16  Quads (minor 3rds)   → "minor_pentatonic"
QUANTIZE_MODE = "minor_pentatonic"

# SEQ1_CV_RANGE / SEQ2_CV_RANGE: Pitch range attenuator for each sequencer.
# On the Labyrinth this physically attenuates the CV voltage before the
# quantizer, compressing the melodic interval reach.
#   0.0 = all steps play the root pitch only (maximum compression)
#   0.5 = roughly one octave of pitch range available
#   1.0 = full two-octave pitch pool available
# Labyrinth range: 0.0–1.0 (knob fully CCW to CW).
SEQ1_CV_RANGE = 0.85
SEQ2_CV_RANGE = 0.60

# SEQ1_OCTAVE / SEQ2_OCTAVE: Base octave for each sequencer's pitch pool.
# On the Labyrinth, the VCO FREQUENCY knob offsets the base pitch that the
# sequencer CV is added on top of.  Setting these an octave apart replicates
# tuning one oscillator up or down relative to the other - a common technique
# for adding register contrast between the two sequences.
# Range: integer octave number (0 = sub-bass, 3 = mid, 4 = upper-mid, 5 = high).
SEQ1_OCTAVE = 4
SEQ2_OCTAVE = 3

# CHAIN_SEQ: Chain SEQ1 and SEQ2 into one continuous loop (True / False).
# When True, both sequencers run as a single (SEQ1_LENGTH + SEQ2_LENGTH)-step
# pattern instead of two independent polymetric cycles.  This matches the
# Labyrinth's CHAIN SEQ mode, which allows sequences up to 16 steps.
# Polymetric polyrhythm only occurs when CHAIN_SEQ is False.
CHAIN_SEQ = False

# ─── CONDUCTOR-DRIVEN CONTROLS ────────────────────────────────────────────────
# These controls are best experienced as slowly evolving values rather than
# fixed settings, so they are implemented as Conductor LFOs.  Adjust the
# cycle_beats, min_val, and max_val parameters to control the sweep behaviour.

composition = subsequence.Composition(bpm=TEMPO, key=QUANTIZE_ROOT)

# SEQ1_CORRUPT / SEQ2_CORRUPT: Probability-based mutation amount (0.0–1.0).
#   0.0       = frozen - no mutation; the sequence repeats exactly.
#   0.0–0.5   = pitch and velocity mutation only; the rhythm (which steps fire)
#               is preserved.  Mirrors Labyrinth CORRUPT below 12 o'clock.
#   0.5–1.0   = rhythm also mutates - steps drop in and out with increasing
#               probability.  Mirrors Labyrinth CORRUPT above 12 o'clock
#               (BIT FLIP territory).
# Labyrinth range: 0.0–1.0 (fully CCW = off; 12 o'clock = pitch-only threshold;
#                            fully CW = maximum chaos).
composition.conductor.lfo("SEQ1_CORRUPT", shape="triangle", cycle_beats=48, min_val=0.0, max_val=0.55)
composition.conductor.lfo("SEQ2_CORRUPT", shape="sine",     cycle_beats=32, min_val=0.0, max_val=0.45)

# EG_TRIG_MIX: Velocity crossfader between SEQ1 and SEQ2 (0.0–1.0).
# Maps directly to the Labyrinth's EG TRIG MIX panel knob:
#   0.0 = SEQ1 triggers at full velocity; SEQ2 output is suppressed.
#   0.5 = both sequences at equal velocity.
#   1.0 = SEQ2 at full velocity; SEQ1 output is suppressed.
# Labyrinth range: 0.0–1.0 (fully CCW to fully CW).
composition.conductor.lfo("EG_TRIG_MIX", shape="triangle", cycle_beats=64, min_val=0.2, max_val=0.8)


# ─── PHYSICAL CONTROLLER MAPPING (OPTIONAL) ───────────────────────────────────
# The three controls above (SEQ1_CORRUPT, SEQ2_CORRUPT, EG_TRIG_MIX) map
# perfectly to physical knobs on a MIDI controller - matching how you would
# turn the equivalent knobs on the hardware Labyrinth.
#
# To enable: uncomment the block below, replace "My Controller" with the exact
# name of your MIDI input device, and assign your CC numbers to match the knobs
# you want to use.  Then comment out the three lfo() lines above, since the
# hardware knobs will take over those signals.
#
# composition.midi_input("My Controller")
#
# composition.cc_map(14, "SEQ1_CORRUPT", min_val=0.0, max_val=1.0)
# composition.cc_map(15, "SEQ2_CORRUPT", min_val=0.0, max_val=1.0)
# composition.cc_map(16, "EG_TRIG_MIX",  min_val=0.0, max_val=1.0)
#
# Any CC number (0–127) is valid.  Check your controller's documentation or
# MIDI monitor software to find the CC number each knob transmits.
#
# Note: cc_map() and lfo() both write to the same named signal, so you can
# mix the two - for example, keep EG_TRIG_MIX as an LFO while manually
# controlling CORRUPT from a knob.


# ─── PITCH POOL BUILDER ───────────────────────────────────────────────────────
# Converts QUANTIZE_ROOT, QUANTIZE_MODE, and a CV_RANGE value into a sorted
# list of MIDI pitches spanning two octaves.  SEQ1_CV_RANGE and SEQ2_CV_RANGE
# then clip the pool so that lower values compress pitch content toward the root,
# faithfully replicating the Labyrinth's CV RANGE attenuator before its quantizer.

def _build_pitch_pool (root, mode, cv_range, base_octave=3):
	"""Build the list of MIDI note numbers available to a sequencer.

	This replicates the Labyrinth's internal quantizer: random CV voltages are
	snapped to the nearest note in the chosen scale.  The CV RANGE attenuator
	then compresses the available range toward the root - lower values mean
	fewer pitches to choose from, so melodies stay closer to home.
	"""

	# Convert the root note name ("C", "F#", etc.) to a pitch class number
	# (0 = C, 1 = C#, 2 = D, ... 11 = B).
	root_pc = subsequence.chords.key_name_to_pc(root)

	# Get the pitch classes that belong to this scale.  For example,
	# C minor pentatonic → [0, 3, 5, 7, 10] (the notes C, Eb, F, G, Bb).
	# If no scale is selected, use all 12 chromatic semitones.
	if mode is None:
		scale_notes = list(range(12))
	else:
		scale_notes = subsequence.intervals.scale_pitch_classes(root_pc, mode)

	# Convert pitch classes to actual MIDI note numbers across two octaves.
	# MIDI note formula: note = 12 × (octave + 1) + pitch_class.
	# For example, C4 = 12 × 5 + 0 = 60.
	base_midi = 12 * (base_octave + 1) + root_pc
	pitches = []
	for octave_offset in range(2):
		for pc in scale_notes:
			midi = base_midi + octave_offset * 12 + (pc - root_pc) % 12
			if 0 <= midi <= 127:
				pitches.append(midi)

	# Remove any duplicates and sort low to high.
	pitches = sorted(set(pitches))

	# CV_RANGE clips the pool: 1.0 = full range, 0.0 = root pitch only.
	n = max(1, round(len(pitches) * cv_range))
	return pitches[:n]


SEQ1_PITCHES = _build_pitch_pool(QUANTIZE_ROOT, QUANTIZE_MODE, SEQ1_CV_RANGE, base_octave=SEQ1_OCTAVE)
SEQ2_PITCHES = _build_pitch_pool(QUANTIZE_ROOT, QUANTIZE_MODE, SEQ2_CV_RANGE, base_octave=SEQ2_OCTAVE)


# ─── SEQUENCER PATTERNS ───────────────────────────────────────────────────────

if CHAIN_SEQ:

	# CHAIN SEQ mode: SEQ1 and SEQ2 run as one longer loop.
	# Merge both pitch pools into one combined set (removing duplicates).
	CHAINED_PITCHES = sorted(set(SEQ1_PITCHES + SEQ2_PITCHES))

	@composition.pattern(channel=CHANNEL, steps=SEQ1_LENGTH + SEQ2_LENGTH, unit=SEQ1_UNIT)
	def chained (p):

		corrupt  = p.signal("SEQ1_CORRUPT")
		trig_mix = p.signal("EG_TRIG_MIX")

		# In chained mode, velocity is loudest at the extremes of the crossfader
		# and quietest at centre (where the two sequences would cancel out).
		vel_ceiling = round(110 * (0.5 + abs(trig_mix - 0.5)))

		# Rhythm mutation: CORRUPT above 0.5 starts suppressing steps.
		rhythm_dropout = max(0.0, (corrupt - 0.5) * 2.0)

		for step in range(SEQ1_LENGTH + SEQ2_LENGTH):

			if p.rng.random() < rhythm_dropout:
				continue

			pitch = p.rng.choice(CHAINED_PITCHES)

			# Pitch mutation: CORRUPT below 0.5 drifts pitch within the pool.
			if corrupt > 0.0 and p.rng.random() < corrupt * 0.8:
				pitch = p.rng.choice(CHAINED_PITCHES)

			vel = round(p.rng.uniform(0.65, 1.0) * vel_ceiling)
			p.hit_steps(pitch, [step], velocity=max(1, vel), duration=SEQ1_UNIT * 0.85)

else:

	# Independent polymetric mode: SEQ1 and SEQ2 run on separate cycle lengths.
	# With SEQ1_LENGTH=7 and SEQ2_LENGTH=5 using EIGHTH notes, the full pattern
	# repeats every LCM(7,5)=35 eighth notes (8.75 bars at 4/4).

	@composition.pattern(channel=CHANNEL, steps=SEQ1_LENGTH, unit=SEQ1_UNIT)
	def seq1 (p):

		# Read the current value of each Conductor LFO signal.
		# These change slowly over time (see the LFO definitions above).
		corrupt  = p.signal("SEQ1_CORRUPT")   # 0.0–0.55, sweeping
		trig_mix = p.signal("EG_TRIG_MIX")    # 0.2–0.8, sweeping

		# EG_TRIG_MIX: fully left (0.0) = SEQ1 loud; fully right (1.0) = SEQ1 quiet.
		vel_ceiling = round(110 * (1.0 - trig_mix))

		# Rhythm mutation kicks in above CORRUPT 0.5 (BIT FLIP territory).
		# Scale 0.5–1.0 into 0.0–1.0 so it ramps from "no dropout" to "all dropout".
		rhythm_dropout = max(0.0, (corrupt - 0.5) * 2.0)

		for step in range(SEQ1_LENGTH):

			# p.rng is this pattern's random number generator (seeded for
			# reproducibility).  p.rng.random() returns a float between 0.0 and 1.0.
			# If that value falls below the dropout probability, this step is skipped.
			if p.rng.random() < rhythm_dropout:
				continue  # This step's bit is suppressed this cycle.

			# Pick a random pitch from the quantized pool for this step.
			pitch = p.rng.choice(SEQ1_PITCHES)

			# Pitch mutation: the higher the CORRUPT value, the more likely
			# the original pitch gets swapped for a different one from the pool.
			if corrupt > 0.0 and p.rng.random() < corrupt * 0.8:
				pitch = p.rng.choice(SEQ1_PITCHES)

			# Random velocity between 65% and 100% of the ceiling, for humanisation.
			vel = round(p.rng.uniform(0.65, 1.0) * vel_ceiling)
			p.hit_steps(pitch, [step], velocity=max(1, vel), duration=SEQ1_UNIT * 0.85)

	@composition.pattern(channel=CHANNEL, steps=SEQ2_LENGTH, unit=SEQ2_UNIT)
	def seq2 (p):
		"""SEQ2: mirrors SEQ1 logic (see comments there) but reads SEQ2_CORRUPT
		and uses the opposite trig_mix polarity - SEQ2 is loudest when the
		crossfader is fully right (1.0)."""

		corrupt  = p.signal("SEQ2_CORRUPT")
		trig_mix = p.signal("EG_TRIG_MIX")

		# EG_TRIG_MIX: SEQ2 is loud when the crossfader is fully right (1.0).
		# This is the inverse of SEQ1's formula (1.0 - trig_mix).
		vel_ceiling = round(110 * trig_mix)

		# Rhythm dropout: same logic as SEQ1 - CORRUPT above 0.5 starts
		# suppressing steps.
		rhythm_dropout = max(0.0, (corrupt - 0.5) * 2.0)

		for step in range(SEQ2_LENGTH):

			if p.rng.random() < rhythm_dropout:
				continue

			pitch = p.rng.choice(SEQ2_PITCHES)

			if corrupt > 0.0 and p.rng.random() < corrupt * 0.8:
				pitch = p.rng.choice(SEQ2_PITCHES)

			vel = round(p.rng.uniform(0.65, 1.0) * vel_ceiling)
			p.hit_steps(pitch, [step], velocity=max(1, vel), duration=SEQ2_UNIT * 0.85)


if __name__ == "__main__":

	composition.display(grid=True, grid_scale=4)
	composition.web_ui()
	composition.play()
