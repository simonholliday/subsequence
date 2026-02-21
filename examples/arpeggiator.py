import logging
import requests

import subsequence

import subsequence.constants.durations as dur
import subsequence.constants.gm_drums as gm_drums
import subsequence.sequence_utils

logging.basicConfig(level=logging.INFO)

DRUM_CHANNEL = 10
BASS_CHANNEL = 5
ARP_CHANNEL = 0
LEAD_CHANNEL = 3

composition = subsequence.Composition(
	bpm=120,
	key="E",
	output_device="Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"
)

composition.form({
	"intro":		(8, [("section_1", 1)]),
	"section_1":	(8, [("section_1", 1), ("section_2", 2)]),
	"section_2":	(8, [("section_2", 1), ("section_1", 2)]),
}, start="intro")

composition.harmony(style="phrygian_minor", cycle_beats=16, gravity=0.75)

@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	if p.section and p.section.name == "intro":
		return

	hi_hat_open_steps = {15}

	if p.cycle and not(p.cycle % 4):
		hi_hat_open_steps.add(5)

	hi_hat_closed_steps = set(range(16)) - hi_hat_open_steps

	p.hit_steps("hi_hat_closed", hi_hat_closed_steps, velocity=75)
	p.hit_steps("hi_hat_open", hi_hat_open_steps, velocity=65)

	p.velocity_shape(low=60, high=100)

	p.hit_steps("snare_1", [4, 12], velocity=100)

	if not(p.cycle % 16):
		p.hit_steps("crash_2", {0}, velocity=127)

	if p.section and p.section.name == "section_2" and p.cycle % 8 == 0:
		p.hit_steps("hand_clap", [12], velocity=100)

	p.hit_steps("kick_1", {0, 4, 8, 12}, velocity=100)

@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):

	if p.section and p.section.name == "intro":
		return

	root = chord.root_note(33)

	bass_steps = {0, 3, 8, 12}

	if p.cycle and p.cycle % 4 == 2:
		bass_steps.update({6})

	p.sequence(
		steps=bass_steps,
		pitches=root
	)

	p.legato(0.9)

@composition.pattern(channel=ARP_CHANNEL, length=5, unit=dur.SIXTEENTH)
def arp (p, chord):

	pitches = chord.tones(root=60, count=5)
	p.arpeggio(pitches, step=dur.SIXTEENTH, direction="up")

@composition.pattern(channel=LEAD_CHANNEL, length=6, unit=dur.SIXTEENTH)
def lead (p, chord):

	root = chord.root_note(84)
	# pitches = chord.tones(root=root, count=4)

	p.sequence(
		steps=[0, 1, 3, 5],
		pitches=[root+12, root, root, root],
		durations=0.125,
	)

if __name__ == "__main__":

	composition.display()
#	composition.live()
	composition.play()
