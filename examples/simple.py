import logging

import subsequence
import subsequence.helpers.wing as wing

import subsequence.constants.durations as dur
import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.constants.instruments.vermona_drm1_drums as vermona_drm1_drums
import subsequence.constants.midi_notes as midi_notes
import subsequence.sequence_utils

import subsequence.constants.instruments.vermona_drm1_drums as vermona_drm1_drums

logging.basicConfig(level=logging.INFO)

# DRUM_CHANNEL = 9
DRUM_CHANNEL = 10
BASS_CHANNEL = 5
ARP_CHANNEL = 0
LEAD_CHANNEL = 3

composition = subsequence.Composition(
	bpm=125,
	key="E"
)

groove = subsequence.Groove.from_agr("Swing 16ths 57.agr")

# Auto-discover the Behringer WING on the local network and connect.
# If no WING is found, OSC automation is simply skipped (p.osc() calls
# are silently dropped when no OSC server is configured).
_wing = wing.discover()
if _wing:
	logging.info("WING found at %s (%s firmware %s)", _wing["ip"], _wing["model"], _wing["firmware"])
	composition.osc(send_port=wing.WING_PORT, send_host=_wing["ip"])
else:
	logging.info("No WING found on the network — OSC automation disabled")

composition.form({
	"intro":		(8, [("section_1", 1)]),
	"section_1":	(8, [("section_2", 2), ("section_1", 1)]),
	"section_2":	(8, [("section_3", 2), ("section_2", 1)]),
	"section_3":	(8, [("section_3", 1), ("section_1", 1)]),
}, start="intro")

@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=vermona_drm1_drums.VERMONA_DRM1_DRUM_MAP)
def drums (p):

	p.hit_steps("kick_2", {0, 4, 8, 12}, velocity=100)
	p.hit_steps("kick_2", {1, 15}, velocity=50)
	p.hit_steps("snare_1", {4, 12}, velocity=100)

	if not p.section:
		return

	if p.section.name != "intro":

		p.hit_steps("hi_hat_closed", range(0,14,2), velocity=100)
		p.hit_steps("hi_hat_open", {14}, velocity=75)

	p.groove(groove)

@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p):

	bass_steps = {0, 3, 8, 12}

	"""
	bass_full_grid = set(range(0, 16))
	bass_steps_left = bass_full_grid - bass_steps
	x = 3
	random_selection = p.rng.sample(list(bass_steps_left), x)
	"""

	# Each note should be added per individual decision
	# Section has a big influence, lateness in bar also is a factor.
	# Perhaps pick in order 6, 10, 5, 7 etc? One at a time? Pick random combinations?
	# As we get further through the composition, larger chance of picking a more complex pattern?
	# Add same to drum pattern (kick, hat density)
	# Add arp/chord layer

	if p.section:

		if p.section.name == "section_1":
			bass_steps.update({6})

		elif p.section.name == "section_2":
			bass_steps.update({6,10})

		elif p.section.name == "section_3":
			bass_steps.update({5,7})

		"""
		elif p.section.name == "section_3":

			if p.rng.random() >= 0.5:
				bass_steps.update({6,7,9,10,11})
		"""

	bass_pitch = midi_notes.E1

	if p.cycle % 8 == 7:
		bass_pitch = midi_notes.G1

	p.sequence(
		steps=bass_steps,
		pitches=bass_pitch
	)

	p.legato(0.95)

	# Bend the last note up 1 semitone (0.5 of a standard ±2 st range),
	# easing in over its full duration.
	p.bend(note=-1, amount=0.5, shape="ease_in")

if __name__ == "__main__":

	composition.display(grid=True, grid_scale=2)
	composition.play()
	
