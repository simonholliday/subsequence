"""
Subsequence Demo — Composition API

A generative composition in dark E minor.

This demo shows the recommended way to build with Subsequence. Everything
is configured at the top level and patterns are simple decorated functions.
The module handles scheduling, async, and MIDI plumbing.

How to read this file
─────────────────────
1. MIDI Setup     — Tell the module which channels to use.
2. Composition    — Create a composition with a tempo and key.
3. Harmony        — Choose a chord graph and how often chords change.
4. Form           — Define the large-scale structure (sections and bar counts).
5. External Data  — Schedule a background task that feeds data into patterns.
6. Patterns       — Decorated functions that build one bar of notes each cycle.
                    They receive a PatternBuilder (p) and optionally a chord.
                    Use p.section to react to the current section.
7. Play           — Start the sequencer. Press Ctrl+C to stop.

Musical overview
────────────────
The form is a graph: intro (4 bars) plays once then moves to the verse.
From the verse (8 bars), the form goes to the chorus (75%) or a bridge
(25%). The chorus (8 bars) leads to a breakdown (67%) or back to the
verse (33%). The bridge (4 bars) always goes to the chorus. The breakdown
(4 bars) always leads back to the verse. The intro never returns.

During the intro only the kick plays. The verse adds hats and pads. The
chorus adds everything — snare, arpeggio, and bass. The bridge and
breakdown strip back to hats and a quiet pad. Chord changes happen every
bar (4 beats) via the dark_minor graph centred on E.
"""

import json
import logging
import random
import urllib.request

import subsequence
import subsequence.constants.durations as dur
import subsequence.sequence_utils


# Configure logging so you can see bar numbers and ISS fetches in the console.
logging.basicConfig(level=logging.INFO)


# ─── MIDI Setup ──────────────────────────────────────────────────────
#
# These values are specific to YOUR studio. Change them to match your
# instrument channel assignments.

DRUMS_MIDI_CHANNEL = 9       # Channel 10 in 1-indexed MIDI (standard drums)
EP_MIDI_CHANNEL = 11          # Electric piano / pad synth
SYNTH_MIDI_CHANNEL = 0       # Lead / arpeggio synth
BASS_MIDI_CHANNEL = 5        # Bass synth

# Drum note map — maps human-readable names to MIDI note numbers.
# These depend on your drum machine or sample library.
DRUM_NOTE_MAP = {
	"kick":      36,
	"snare":     38,
	"hh_closed": 44,
	"hh_open":   46,
}


# ─── Composition ─────────────────────────────────────────────────────

composition = subsequence.Composition(
	bpm = 125,
	key = "E"
)


# ─── Harmony ─────────────────────────────────────────────────────────
#
# Chords change every bar (4 beats) using the dark_minor graph, which
# favours Phrygian and aeolian cadences. Any pattern that accepts a
# "chord" parameter automatically receives the current chord.

composition.harmony(
	style = "aeolian_minor",
	cycle_beats = 4 * dur.QUARTER,
	dominant_7th = True,
	gravity = 0.8,
	minor_weight = 0.25,
)


# ─── Form ────────────────────────────────────────────────────────────
#
# The form defines the large-scale structure as a weighted graph.
# Each section has a bar count and a list of (next_section, weight)
# transitions. The intro plays once, then the form follows the graph
# — the intro never returns. Dead-end sections (empty transitions)
# self-loop.
#
# Patterns read p.section.name to decide what to play in each section.
# p.section.progress (0.0 → 1.0) lets patterns build or fade intensity
# within a section.

composition.form({
	"intro":     (4, [("verse", 1)]),
	"verse":     (8, [("chorus", 3), ("bridge", 1)]),
	"chorus":    (8, [("breakdown", 2), ("verse", 1)]),
	"bridge":    (4, [("chorus", 1)]),
	"breakdown": (4, [("verse", 1)]),
}, start="intro")


# ─── External Data ───────────────────────────────────────────────────
#
# This fetches the ISS position every 8 bars and stores it in
# composition.data. Sync functions automatically run in a thread pool
# so they never block the MIDI clock. If the fetch fails, the last
# good value is kept.

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

composition.schedule(fetch_iss, cycle_beats=32 * dur.QUARTER)


# ─── Drums ───────────────────────────────────────────────────────────
#
# All drum patterns use a 16-step grid (sixteenth notes) over 4 beats.
# The drum_note_map lets you write "kick" instead of 36.

@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4 * dur.QUARTER, drum_note_map=DRUM_NOTE_MAP)
def kick_snare (p):
	"""
	Four-on-the-floor kick with a euclidean snare.
	The snare only plays in the chorus — otherwise this pattern is
	kick-only, which works as a sparse foundation for other sections.
	"""

	# Fixed kick on every beat — steps 0, 4, 8, 12 on the 16-step grid.
	p.hit_steps("kick", [0, 4, 8, 12], velocity=127)

	# Snare only during the chorus.
	if p.section and p.section.name == "chorus":
		nl = composition.data.get("longitude_norm", 0.5)
		max_snare_hits = max(2, round(nl * 8))
		snare_hits = random.randint(1, max_snare_hits)
		snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, snare_hits)
		snare_steps = subsequence.sequence_utils.sequence_to_indices(snare_seq)
		snare_steps = subsequence.sequence_utils.roll(snare_steps, 4, 16)
		p.hit_steps("snare", snare_steps, velocity=100)


@composition.pattern(channel=DRUMS_MIDI_CHANNEL, length=4 * dur.QUARTER, drum_note_map=DRUM_NOTE_MAP)
def hats (p):
	"""
	Bresenham hi-hats with stochastic dropout and velocity shaping.
	Plays in verse, chorus, and breakdown — muted during the intro.
	"""

	# Silent during intro.
	if not p.section or p.section.name == "intro":
		return

	# 8 hits across 16 steps via Bresenham line algorithm.
	hat_seq = subsequence.sequence_utils.generate_bresenham_sequence(16, 8)
	hat_steps = subsequence.sequence_utils.sequence_to_indices(hat_seq)
	p.hit_steps("hh_closed", hat_steps, velocity=80)

	# Random dropout and van der Corput velocity shaping for organic feel.
	p.dropout(0.1)
	p.velocity_shape(low=60, high=100)

	# Occasional open hat near the end of the bar (step 14 = beat 3.5).
	if random.random() < 0.6:
		p.hit_steps("hh_open", [14], velocity=85)


# ─── Harmonic Instruments ────────────────────────────────────────────
#
# These patterns accept a "chord" parameter, which the module fills
# automatically from the harmonic state.

@composition.pattern(channel=EP_MIDI_CHANNEL, length=4 * dur.QUARTER)
def chords (p, chord):
	"""
	Sustained chord pads that follow the harmonic state.
	Silent during intro. Quiet during breakdown. Full volume in
	verse and chorus with intensity building through each section.
	"""

	if not p.section or p.section.name == "intro":
		return

	if p.section.name == "breakdown":
		p.chord(chord, root=52, velocity=50, sustain=True)
		return

	# Build intensity through the section.
	vel = int(70 + 30 * p.section.progress)
	p.chord(chord, root=52, velocity=vel, sustain=True)


@composition.pattern(channel=SYNTH_MIDI_CHANNEL, length=4 * dur.QUARTER)
def motif (p, chord):
	"""
	A cycling arpeggio built from the current chord tones.
	Only plays during the chorus.
	"""

	if not p.section or p.section.name != "chorus":
		return

	tones = chord.tones(root=76)[:3]
	p.arpeggio(tones, step=dur.SIXTEENTH, velocity=90)


@composition.pattern(channel=BASS_MIDI_CHANNEL, length=4 * dur.QUARTER)
def bass (p, chord):
	"""
	A 16th-note bassline on the chord root.
	Only plays during the chorus — other sections have no bass.
	"""

	if not p.section or p.section.name != "chorus":
		return

	root = chord.tones(root=40)[0]
	p.hit_steps(root, list(range(16)), velocity=90, duration=0.2)


# ─── Play ────────────────────────────────────────────────────────────

if __name__ == "__main__":

	composition.display()
	composition.play()
