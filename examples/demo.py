"""
Subsequence Demo — Composition API

A generative composition in E major using the Composition API.
Patterns evolve on every reschedule via stochastic decisions
in the builder functions.
"""

import logging
import random

import subsequence


# Configure logging.
logging.basicConfig(level=logging.INFO)


# ─── MIDI Setup (user-defined, not module constants) ─────────────────
#
# These values are specific to your studio. Change them to match
# your MIDI interface and instrument channel assignments.

MIDI_DEVICE = "Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"

DRUMS_MIDI_CHANNEL = 9
EP_MIDI_CHANNEL = 8
SYNTH_MIDI_CHANNEL = 0
BASS_MIDI_CHANNEL = 5

DRUM_NOTE_MAP = {
	"kick":      36,
	"snare":     38,
	"hh_closed": 44,
	"hh_open":   46,
}


# ─── Composition ─────────────────────────────────────────────────────

composition = subsequence.Composition(
	device = MIDI_DEVICE,
	bpm = 125,
	key = "E"
)

composition.harmony(
	style = "turnaround_global",
	cycle = 4,
	dominant_7th = True,
	gravity = 0.8,
	minor_weight = 0.25,
)


# ─── Drums ───────────────────────────────────────────────────────────

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def kick_snare (p):
	"""
	Four-on-the-floor kick with euclidean distribution and ghost notes,
	plus a backbeat snare on beats 1 and 3.
	"""

	# Euclidean kick with 20% stochastic dropout — different every cycle.
	p.euclidean("kick", pulses=4, velocity=105, dropout=0.2)

	# Backbeat snare, always present.
	if p.cycle > 3:
		p.hit("snare", beats=[1, 3], velocity=100)


@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=5, drum_note_map=DRUM_NOTE_MAP)
def hats (p):
	"""
	Bresenham hi-hats over a 5-beat cycle create a subtle polyrhythm
	against the 4-beat kick/snare. Van der Corput velocity shaping
	adds natural-feeling accents.
	"""

	# 8 hits over 20 16th-note steps with light dropout.
	p.bresenham("hh_closed", pulses=8, velocity=80, dropout=0.1)

	# Van der Corput velocity distribution for organic feel.
	p.velocity_shape(low=60, high=100)

	# Occasional open hat near the end of the cycle.
	if random.random() < 0.6:
		p.note("hh_open", beat=-0.5, velocity=85, duration=0.1)


# ─── Harmonic Instruments ───────────────────────────────────────────

@composition.pattern(channel=EP_MIDI_CHANNEL, length=4)
def chords (p, chord):
	"""
	Sustained chord pads that follow the harmonic state.
	The chord argument is automatically injected from the
	harmonic clock — no manual wiring needed.
	"""

	p.chord(chord, root=52, velocity=90, sustain=True)


@composition.pattern(channel=SYNTH_MIDI_CHANNEL, length=4)
def motif (p, chord):
	"""
	A cycling arpeggio built from the current chord tones.
	Each reschedule gets the latest chord, so the motif
	naturally follows the harmonic progression.
	"""

	tones = chord.tones(root=76)[:3]
	p.arpeggio(tones, step=0.25, velocity=90)


@composition.pattern(channel=BASS_MIDI_CHANNEL, length=4)
def bass (p, chord):
	"""
	A steady 16th-note bassline on the chord root.
	Reinforces the harmonic foundation with a busy pulse.
	"""

	root = chord.tones(root=40)[0]
	p.fill(root, step=0.25, velocity=90, duration=0.2)


# ─── Play ────────────────────────────────────────────────────────────

if __name__ == "__main__":
	composition.play()
