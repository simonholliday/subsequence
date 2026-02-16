
import subsequence
import subsequence.constants.gm_drums

DRUMS_CHANNEL = 9
SYNTH_CHANNEL = 0
DRUM_NOTE_MAP = subsequence.constants.gm_drums.GM_DRUM_MAP

composition = subsequence.Composition(bpm=120, key="Cm")

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums(p):
	# Basic kick/snare using mini-notation for rhythm
	# 'k' and 's' are just labels here, mapped to pitch args
	p.seq("x ~ [x x] ~", pitch="kick_1")
	p.seq("~ x ~ x", pitch="snare_1")
	
	# Hi-hats with subdivisions
	# [x x] occupies one beat
	p.seq("[x x] [x x] [x x] [x x]", pitch="closed_hi_hat", velocity=80)

@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def melody(p):
	# Melody using mini-notation for pitch
	# C4(60), Eb4(63), [G4(67), C5(72)], sustain C5
	p.seq("60 63 [67 72] _", velocity=90)

if __name__ == "__main__":
	print("Press Ctrl+C to stop.")
	composition.display()
	composition.play()
