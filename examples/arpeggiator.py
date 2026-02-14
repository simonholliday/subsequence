"""
Subsequence — Polyrhythmic Arpeggiator

A generative composition built around interlocking polyrhythms. Seven
patterns cycle at five different lengths, creating a web of shifting
accents that never quite repeats.

How it works
────────────
Each pattern has its own cycle length in beats. The sequencer runs them
all independently — when a short pattern loops back to beat 0, the longer
ones are still mid-cycle. This creates polyrhythms: a 3-beat arpeggio
against a 4-beat drum pattern creates a 3:4 feel; a 5-beat arpeggio adds
a 5:4 layer on top.

The patterns fully align every 420+ beats (over 100 bars at 120 BPM),
so the piece sounds different on every pass through. Meanwhile the
turnaround harmony graph drifts between keys, so the chord colours
are always shifting underneath.

Pattern overview
────────────────
  Pattern          │ Length            │ Role
  ─────────────────┼───────────────────┼──────────────────────────────────
  Vermona DRM1     │ 4 quarter notes   │ Steady reference beat (kick/snare/hats)
  Roland TR8S      │ 6 quarter notes   │ Euclidean percussion on a triplet grid
  Voce EP          │ 4 quarter notes   │ Sustained chords (harmonic anchor)
  Moog Matriarch   │ 9 sixteenth notes │ Three-octave sixteenth-note arpeggio (9:16)
  Model D          │ 5 quarter notes   │ Eighth-note arpeggio (5:4)
  Carbon 8         │ 7 quarter notes   │ Dotted-eighth arpeggio (7:4)
  Minitaur         │ 21 eighth notes   │ Bass arpeggio (float length)

How to run
──────────
1. Set MIDI_DEVICE below to your MIDI interface name.
2. Adjust channel numbers to match your studio routing.
3. Run: python examples/arpeggiator.py
4. Press Ctrl+C to stop.

Tweakable parameters
────────────────────
- BPM: Change the tempo in the Composition constructor.
- KEY: Starting key for the harmony. The turnaround graph will modulate
  away from this over time, but gravity pulls it back.
- Pattern lengths: Try changing a length to hear how the polyrhythm shifts.
  Prime numbers (3, 5, 7, 11, 13) create the most variety against 4.
- Arpeggio step sizes: Smaller step = faster notes. Try dur.THIRTYSECOND
  or dur.QUARTER for very different textures.
- Harmony gravity: Higher values (0.9) stay closer to the home key.
  Lower values (0.5) wander further and more often.
"""

import subsequence
import subsequence.constants.durations as dur
import subsequence.constants.gm_drums
import subsequence.sequence_utils


# ─── MIDI Setup ──────────────────────────────────────────────────────
#
# Change these to match your MIDI interface and instrument routing.
# Channel numbers are 0-indexed (MIDI channel 1 = 0, channel 10 = 9).

MIDI_DEVICE = "Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"

# Tonal instruments — each gets its own arpeggio pattern.
MIDI_CHANNEL_MOOG_MATRIARCH = 0    # Fast sixteenth-note arpeggio
MIDI_CHANNEL_MODEL_D = 3           # Eighth-note arpeggio
MIDI_CHANNEL_CARBON_8 = 4          # Dotted-eighth arpeggio
MIDI_CHANNEL_MINITAUR = 5          # Bass arpeggio (float length)
MIDI_CHANNEL_VOCE_EP = 11          # Sustained chords (not arpeggios)

# Percussion instruments.
MIDI_CHANNEL_VERMONA_DRM1 = 9      # Reference drums (standard beat)
MIDI_CHANNEL_ROLAND_TR8S = 10      # Polyrhythmic drums (GM notes)

# Drum note map for the Vermona DRM1.
# This is specific to YOUR drum machine — change these to match
# your instrument's note assignments.
DRM1_DRUM_MAP = {
	"kick":      36,
	"snare":     38,
	"hh_closed": 42,
}


# ─── Composition ─────────────────────────────────────────────────────
#
# The turnaround harmony graph enables modulation between all 12 major
# and minor keys via ii-V-I progressions. Gravity pulls the harmony
# back toward the home key, but it will wander. Chords change every
# 4 beats (one bar). No form is defined — the piece plays indefinitely
# with evolving harmony as the structure.

composition = subsequence.Composition(
	device = MIDI_DEVICE,
	bpm = 120,
	key = "C",
	seed = 42,
)

composition.harmony(
	style = "turnaround_global",
	cycle_beats = 4 * dur.QUARTER,
	dominant_7th = True,
	gravity = 0.8,
	minor_weight = 0.25,
)


# ─── Reference Drums (Vermona DRM1) ─────────────────────────────────
#
# A completely static 4-beat pattern on a 16-step grid. This is the
# stable anchor that every other pattern plays against. No variation,
# no evolution — just a solid beat so you can hear how the polyrhythms
# shift against it.
#
# The grid:  0  1  2  3  4  5  6  7  8  9  10 11 12 13 14 15
#   kick:    x  .  .  .  x  .  .  .  x  .  .  .  x  .  .  .
#   snare:   .  .  .  .  x  .  .  .  .  .  .  .  x  .  .  .
#   hats:    x  x  x  x  x  x  x  x  x  x  x  x  x  x  x  x

@composition.pattern(channel=MIDI_CHANNEL_VERMONA_DRM1, length=4 * dur.QUARTER, drum_note_map=DRM1_DRUM_MAP)
def reference_drums (p):

	"""Steady four-on-the-floor beat. Never changes."""

	p.hit_steps("kick", [0, 4, 8, 12], velocity=127)
	p.hit_steps("snare", [4, 12], velocity=100)
	p.hit_steps("hh_closed", list(range(16)), velocity=80)


# ─── Polyrhythmic Drums (Roland TR8S) ────────────────────────────────
#
# A 6-beat pattern on a 12-step grid (triplet eighth notes). This
# creates a 3:2 feel against the 4-beat reference drums — the TR8S
# pattern completes every 6 beats while the DRM1 completes every 4,
# so they align every 12 beats (3 DRM1 cycles = 2 TR8S cycles).
#
# Uses General MIDI drum note names from the module's gm_drums map.
# The euclidean density changes each cycle via p.rng for variety.

@composition.pattern(channel=MIDI_CHANNEL_ROLAND_TR8S, length=6 * dur.QUARTER, drum_note_map=subsequence.constants.gm_drums.GM_DRUM_MAP)
def tr8s_drums (p):

	"""Euclidean percussion on a triplet grid. New density each cycle."""

	# Kick: 2-4 hits spread evenly across 12 triplet steps.
	kick_density = p.rng.randint(2, 4)
	p.euclidean("kick_1", pulses=kick_density, velocity=110)

	# Rim shot: sparse euclidean pattern, offset by rolling +3 steps.
	rim_seq = subsequence.sequence_utils.generate_euclidean_sequence(12, p.rng.randint(1, 3))
	rim_steps = subsequence.sequence_utils.sequence_to_indices(rim_seq)
	rim_steps = subsequence.sequence_utils.roll(rim_steps, 3, 12)
	p.hit_steps("side_stick", rim_steps, velocity=90, step_count=12)

	# Hand clap: occasional accent on a random triplet step.
	if p.rng.random() < 0.4:
		clap_step = p.rng.randint(0, 11)
		p.hit_steps("hand_clap", [clap_step], velocity=95, step_count=12)


# ─── Chords (Voce EP) ───────────────────────────────────────────────
#
# Sustained chords that follow the harmonic state. This is the
# harmonic anchor — it tells your ear what key and chord you're in
# while the arpeggios weave around it. The voicing sits around
# middle C (MIDI note 52) so it doesn't crowd the bass or treble
# arpeggios.

@composition.pattern(channel=MIDI_CHANNEL_VOCE_EP, length=4 * dur.QUARTER)
def chords (p, chord):

	"""Whole-bar sustained chord. Follows the turnaround harmony."""

	p.chord(chord, root=52, velocity=85, sustain=True)


# ─── Arpeggio: Moog Matriarch (9 sixteenth notes) ───────────────────
#
# A fast arpeggio that sweeps chord tones across three octaves at
# sixteenth-note speed. Three chord tones × 3 octaves = 9 notes per
# cycle, so the pattern length is 9 sixteenth notes (2.25 beats).
#
# Against the 4-beat drums this creates a 9:16 polyrhythm — one of
# the most complex ratios in the piece. The arpeggio's downbeat
# shifts constantly, never landing in the same place twice for a
# very long time.
#
# Starts at C3 (MIDI 48) and rises to around G5, sweeping through
# the full mid range of the Matriarch.

@composition.pattern(channel=MIDI_CHANNEL_MOOG_MATRIARCH, length=9 * dur.SIXTEENTH)
def matriarch_arp (p, chord):

	"""Three-octave sixteenth-note arpeggio. 9:16 polyrhythm against the drums."""

	base_tones = chord.tones(root=48)[:3]
	tones = []
	for octave in range(3):
		tones.extend([t + 12 * octave for t in base_tones])
	p.arpeggio(tones, step=dur.SIXTEENTH, velocity=90, duration=0.2)


# ─── Arpeggio: Model D (5 quarter notes, eighth-note steps) ─────────
#
# A slower 5-beat arpeggio at eighth-note speed. With 5 quarter notes
# at eighth-note steps, that's 10 notes per cycle. The 5:4 polyrhythm
# against the drums creates a wide, spacious feel — the arpeggio
# "drifts" against the beat, landing on different subdivisions each bar.
#
# Voiced around C4 (MIDI 60) for a clear mid-range tone, well above
# the Minitaur bass. Uses all available chord tones (3 for triads,
# 4 for sevenths).

@composition.pattern(channel=MIDI_CHANNEL_MODEL_D, length=5 * dur.QUARTER)
def model_d_arp (p, chord):

	"""Spacious 5-beat arpeggio. Creates a 5:4 polyrhythm."""

	tones = chord.tones(root=60)
	p.arpeggio(tones, step=dur.EIGHTH, velocity=85, duration=dur.DOTTED_SIXTEENTH)


# ─── Arpeggio: Carbon 8 (7 quarter notes, dotted-sixteenth steps) ───
#
# A 7-beat arpeggio at dotted-sixteenth speed (three sixteenth notes
# per step). This is the most complex polyrhythm in the piece: 7 beats
# against 4 gives a 7:4 ratio, and the dotted-sixteenth step adds
# another layer of rhythmic tension within the 7-beat cycle.
#
# Voiced high around C5 (MIDI 72) for a bell-like, crystalline
# quality that sits above the other arpeggios.

@composition.pattern(channel=MIDI_CHANNEL_CARBON_8, length=7 * dur.QUARTER)
def carbon8_arp (p, chord):

	"""High 7-beat arpeggio with dotted-sixteenth rhythm. 7:4 polyrhythm."""

	tones = chord.tones(root=72)[:3]
	p.arpeggio(tones, step=dur.DOTTED_SIXTEENTH, velocity=80, duration=dur.SIXTEENTH)


# ─── Bass Arpeggio: Minitaur (21 eighth notes) ──────────────────────
#
# A bass arpeggio with a length of 21 eighth notes. This demonstrates
# Subsequence's float length support — 21 eighth notes = 10.5 quarter
# notes, which doesn't divide evenly into standard 4-beat bars.
#
# The result is a bass line that constantly shifts its downbeat
# relative to the drums. It takes a very long time to realign,
# keeping the low end perpetually fresh.
#
# Uses just root and fifth for a simple, grounding bass movement
# in the low register (MIDI 36 = C2).

@composition.pattern(channel=MIDI_CHANNEL_MINITAUR, length=21 * dur.EIGHTH)
def minitaur_bass (p, chord):

	"""Bass arpeggio with float length (21 eighth notes = 10.5 beats)."""

	tones = chord.tones(root=36)
	root = tones[0]
	fifth = tones[2] if len(tones) >= 3 else root + 7
	p.arpeggio([root, fifth], step=dur.EIGHTH, velocity=100, duration=dur.DOTTED_SIXTEENTH)


# ─── Play ────────────────────────────────────────────────────────────

if __name__ == "__main__":

	# Show the live status line (BPM, key, bar, chord).
	composition.display()

	# Start the sequencer. Press Ctrl+C to stop.
	composition.play()
