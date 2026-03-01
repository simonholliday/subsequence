import logging

import subsequence
import subsequence.helpers.wing as wing

import subsequence.constants.durations as dur
import subsequence.constants.instruments.gm_drums as gm_drums
import subsequence.constants.instruments.vermona_drm1_drums as vermona_drm1_drums
import subsequence.constants.midi_notes as midi_notes
import subsequence.sequence_utils
import subsequence.constants.instruments.gm_drums as gm_drums

logging.basicConfig(level=logging.INFO)

DRUM_CHANNEL = 9
BASS_CHANNEL = 5
ARP_CHANNEL = 0
LEAD_CHANNEL = 3

composition = subsequence.Composition(
	bpm=125,
	key="E"
)

groove = subsequence.Groove(
	offsets=[0.0, 0.035, 0.0, 0.035, 0.0, 0.035, 0.0, 0.035, 0.0, 0.035, 0.0, 0.035, 0.0, 0.035, 0.0, 0.035],
	grid=0.25
)

composition.form({
	"intro":		(8, [("section_1", 1)]),
	"section_1":	(8, [("section_2", 2), ("section_1", 1)]),
	"section_2":	(8, [("section_3", 2), ("section_2", 1)]),
	"section_3":	(8, [("section_3", 1), ("section_1", 1)]),
}, start="intro")

# A Sine wave LFO over 16 bars (64 beats) that cycles between 0.0 and 1.0.
# We'll refer to it by name ("drum_swell") inside the pattern.
composition.conductor.lfo("drum_swell", shape="sine", cycle_beats=128.0, min_val=0.0, max_val=1.0, phase=0.75)

@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	# Read the sine wave value for the current bar (0.0 to 1.0)
	swell = p.signal("drum_swell")

	perlin = subsequence.sequence_utils.perlin_1d(p.cycle * 0.07, seed=1)

	p.hit_steps("kick_2", {0, 4, 8, 12}, velocity=100)

	# Ghost layering: CA + probability fill
	p.cellular("kick_2", rule=30, velocity=40, no_overlap=True, dropout=0.25)

	logging.info(f"Cycle: {p.cycle}")
	logging.info(f"Swell: {swell:.2f}")
	p.ghost_fill("kick_2", density=swell * perlin, velocity=(15, 35), bias="offbeat", no_overlap=True)

	p.hit_steps("snare_1", {4, 12}, velocity=100)
	p.ghost_fill("snare_1", density=swell, velocity=(40, 65), bias="syncopated", no_overlap=True)

	if not p.section:
		return

	if p.section.name != "intro":

		p.hit_steps("hi_hat_closed", range(0,14,2), velocity=100)

		# Create the standard syncopated bias for a 16-step grid
		bias_sync = p.build_ghost_bias(16, "uniform")

		# Explicitly ensure step 14 has a 0% chance of receiving a closed hi-hat ghost note
		# so it doesn't clash with the open hi-hat we're placing there.
		bias_sync[14] = 0.0

		# Calculate a continuously evolving velocity curve for our ghost notes.
		# This uses Perlin noise to create a smooth, wave-like change in volume
		# that drifts over time. We map the 0.2-0.8 noise directly to MIDI 
		# velocities 5-50 using our map_value helper.
		# `p.cycle * 16 + i` ensures the wave progresses continuously through every bar.
		hat_velocities = [
			int(subsequence.easing.map_value(
				value=subsequence.sequence_utils.perlin_1d((p.cycle * 16 + i) * 0.1, seed=10),
				out_min=50, out_max=75,
				shape="ease_in"
			)) for i in range(16)
		]

		p.ghost_fill(
			"hi_hat_closed",
			density=swell,
			velocity=hat_velocities,
			bias=bias_sync,
			no_overlap=True
		)
		p.hit_steps("hi_hat_open", {14}, velocity=75)

	p.groove(groove)

@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p):

	return

	bass_pitch = midi_notes.E1

	bass_steps = set(range(0,16,1))

	p.sequence(
		steps=bass_steps,
		pitches=bass_pitch,
		durations=0.05,
		velocities=25
	)

	return

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

	composition.display(grid=True, grid_scale=4)
#	composition.web_ui()
	composition.play()
	
