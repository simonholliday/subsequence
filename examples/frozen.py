"""Frozen progressions demo — verse and chorus with pre-baked harmony.

This example shows how to capture chord progressions from the live harmony
engine and lock them to form sections, so the verse always plays the same
chords and the chorus always plays the same chords — while leaving the
bridge to generate freely each time.

Key idea: call composition.harmony() with different gravity/nir_strength
values before each freeze() call.  The engine advances through each call,
so the sections feel harmonically connected even though they repeat.

Form:
    verse  (8 bars)  — plays ~2–3 times, frozen to a stable diatonic sequence
    chorus (4 bars)  — plays once per cycle, frozen to a more adventurous sequence
    bridge (4 bars)  — no section_chords() binding, generates fresh live chords each time
"""

import logging

import subsequence
import subsequence.helpers.wing as wing

import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.constants.midi_notes as midi_notes

logging.basicConfig(level=logging.INFO)

DRUM_CHANNEL = 9
BASS_CHANNEL  = 5
ARP_CHANNEL   = 0

# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

composition = subsequence.Composition(bpm=120, key="C")

# ---------------------------------------------------------------------------
# Freeze progressions
#
# Call harmony() once per section style, then freeze() immediately.
# Each freeze() advances the engine, so verse → chorus → bridge feel
# like a single continuous harmonic journey.
# ---------------------------------------------------------------------------

# Verse: high gravity keeps chords close to the tonic; low NIR = settled feel.
composition.harmony(
	style="functional_major",
	cycle_beats=4,
	gravity=0.85,
	nir_strength=0.2,
)
verse = composition.freeze(8)   # 8 chord changes (one per bar)

# Chorus: looser gravity lets the engine wander; high NIR pushes motion forward.
composition.harmony(
	style="functional_major",
	cycle_beats=4,
	gravity=0.35,
	nir_strength=0.8,
)
chorus = composition.freeze(4)  # 4 chord changes

# Bridge: no freeze — the engine generates live chords every time it plays.
# harmony() reconfigures for a suspended colour that suits improvisation.
composition.harmony(
	style="suspended",
	cycle_beats=4,
	gravity=0.5,
	nir_strength=0.5,
)

# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

composition.form({
	"verse":  (8, [("verse", 2), ("chorus", 1)]),
	"chorus": (4, [("bridge", 1)]),
	"bridge": (4, [("verse",  1)]),
}, start="verse")

# Bind frozen progressions to sections.
composition.section_chords("verse",  verse)
composition.section_chords("chorus", chorus)
# bridge is intentionally unbound — it always generates live chords.

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	p.hit_steps("kick_2",       {0, 8, 12},  velocity=100)
	p.hit_steps("snare_1",      {4, 12},     velocity=90)
	p.hit_steps("hi_hat_closed", range(16),  velocity=65)

	if p.section and p.section.name == "chorus":
		# Open hi-hat on the off-beat in the chorus for extra lift.
		p.hit_steps("hi_hat_open", {6, 14}, velocity=75)


@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):

	# Root note of the current chord, one octave below middle C.
	root = chord.root_note(36)

	p.sequence(steps={0, 4, 8, 12}, pitches=root, velocities=95)
	p.legato(0.9)

	if p.section and p.section.name == "chorus":
		# Add a passing note on beat 3 in the chorus.
		fifth = chord.root_note(36) + 7
		p.sequence(steps={10}, pitches=fifth, velocities=80)


@composition.pattern(channel=ARP_CHANNEL, length=4)
def arp (p, chord):

	if not p.section or p.section.name == "verse":
		# Verse: simple root-chord arpeggio.
		pitches = chord.tones(root=60, count=4)
		p.arpeggio(pitches, step=0.5, velocity=75)

	elif p.section.name == "chorus":
		# Chorus: faster sixteenth-note arpeggio across a wider range.
		pitches = chord.tones(root=60, count=8)
		p.arpeggio(pitches, step=0.25, velocity=80)

	# Bridge: silence — let the live harmony breathe on its own.


# ---------------------------------------------------------------------------

if __name__ == "__main__":

	composition.display()
	composition.play()
