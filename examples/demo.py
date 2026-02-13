"""
Subsequence Demo — Composition API

A generative composition in dark E minor using the Composition API.
Patterns evolve on every reschedule via stochastic decisions
in the builder functions.
"""

import json
import logging
import random
import urllib.request

import subsequence
import subsequence.sequence_utils


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
	style = "dark_minor",
	cycle = 4,
	dominant_7th = True,
	gravity = 0.8,
	minor_weight = 0.25,
)


# ─── External Data ───────────────────────────────────────────────────

def fetch_iss () -> None:

	"""Fetch ISS position and normalize lat/long to 0-1 range."""

	try:
		request = urllib.request.urlopen("https://api.wheretheiss.at/v1/satellites/25544", timeout=5)
		body = json.loads(request.read())
		composition.data["latitude_norm"] = (body["latitude"] + 52) / 104.0
		composition.data["longitude_norm"] = (body["longitude"] + 180) / 360.0
		logging.info(f"ISS lat={body['latitude']:.1f} lon={body['longitude']:.1f}")

	except Exception as exc:
		logging.warning(f"ISS fetch failed (keeping last value): {exc}")

composition.schedule(fetch_iss, cycle=32)


# ─── Drums ───────────────────────────────────────────────────────────

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def kick_snare (p):
	"""
	Four-on-the-floor kick anchors the groove while an ISS-modulated
	euclidean snare is rolled to land on backbeat positions.
	"""

	# Fixed four-on-the-floor kick — steps 0, 4, 8, 12 on a 16-step grid.
	p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

	# Euclidean snare: ISS longitude modulates max density.
	if p.cycle > 3:
		nl = composition.data.get("longitude_norm", 0.5)
		max_snare_hits = max(2, round(nl * 8))
		snare_hits = random.randint(1, max_snare_hits)
		snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, snare_hits)
		snare_steps = subsequence.sequence_utils.sequence_to_indices(snare_seq)
		snare_steps = subsequence.sequence_utils.roll(snare_steps, 4, 16)
		p.hit_steps("snare", snare_steps, velocity=100)


@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def hats (p):
	"""
	Bresenham hi-hats on a 16-step grid with van der Corput velocity
	shaping for natural-feeling accents.
	"""

	# 8 hits distributed across 16 steps via Bresenham.
	hat_seq = subsequence.sequence_utils.generate_bresenham_sequence(16, 8)
	hat_steps = subsequence.sequence_utils.sequence_to_indices(hat_seq)
	p.hit_steps("hh_closed", hat_steps, velocity=80)

	# Stochastic dropout and van der Corput velocity shaping.
	p.dropout(0.1)
	p.velocity_shape(low=60, high=100)

	# Occasional open hat near the end of the cycle (step 14 = beat 3.5).
	if random.random() < 0.6:
		p.hit_steps("hh_open", [14], velocity=85)


# ─── Harmonic Instruments ───────────────────────────────────────────

@composition.pattern(channel=EP_MIDI_CHANNEL, length=4)
def chords (p, chord):
	"""
	Sustained chord pads that follow the harmonic state.
	Placed at step 0 and held for the full 16-step cycle.
	"""

	p.chord(chord, root=52, velocity=90, sustain=True)


@composition.pattern(channel=SYNTH_MIDI_CHANNEL, length=4)
def motif (p, chord):
	"""
	A cycling arpeggio built from the current chord tones.
	Three pitches distributed across 16 steps at quarter-note intervals.
	"""

	tones = chord.tones(root=76)[:3]
	p.arpeggio(tones, step=0.25, velocity=90)


@composition.pattern(channel=BASS_MIDI_CHANNEL, length=4)
def bass (p, chord):
	"""
	A 16th-note bassline on the chord root filling all 16 steps.
	"""

	root = chord.tones(root=40)[0]
	p.hit_steps(root, list(range(16)), velocity=90, duration=0.2)


# ─── Play ────────────────────────────────────────────────────────────

if __name__ == "__main__":

	def on_bar (bar: int) -> None:

		"""
		Log the current bar for visibility.
		"""

		logging.info(f"Bar {bar + 1}")

	composition.on_event("bar", on_bar)

	composition.play()
