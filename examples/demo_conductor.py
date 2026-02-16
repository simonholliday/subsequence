
import subsequence
import subsequence.constants.gm_drums

DRUMS_CHANNEL = 9
SYNTH_CHANNEL = 0
DRUM_NOTE_MAP = subsequence.constants.gm_drums.GM_DRUM_MAP

composition = subsequence.Composition(bpm=120, key="Cm")

# Define global signals that all patterns can read.
# Sine LFO cycling every 8 bars (32 beats) — drives pad dynamics.
composition.conductor.lfo("swell", shape="sine", cycle_beats=32, min_val=0.3, max_val=1.0)

# Linear ramp from 0 to 1 over 16 bars (64 beats) — builds intensity.
composition.conductor.line("buildup", start_val=0.0, end_val=1.0, duration_beats=64)

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=DRUM_NOTE_MAP)
def drums(p):
	# Kick stays constant
	p.seq("x . [x x] .", pitch="kick_1")

	# Hi-hat density increases with the buildup signal.
	# Early on (buildup ~0) only downbeats play; later, sixteenths fill in.
	buildup = p.signal("buildup")

	if buildup > 0.6:
		p.seq("[x x] [x x] [x x] [x x]", pitch="closed_hi_hat", velocity=80)
	elif buildup > 0.3:
		p.seq("x x x x", pitch="closed_hi_hat", velocity=80)
	else:
		p.seq("x . x .", pitch="closed_hi_hat", velocity=70)

@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def pads(p):
	# Read the swell signal — modulates velocity smoothly
	swell = p.signal("swell")
	velocity = int(60 + 60 * swell)

	p.seq("60 63 [67 72] _", velocity=velocity)

if __name__ == "__main__":
	print("Press Ctrl+C to stop.")
	composition.display()
	composition.play()
