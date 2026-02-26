"""Composition API demo — drums, bass, and arp in E aeolian minor.

This is the simplest way to build a composition with Subsequence.
The Composition class handles the MIDI clock, device discovery, and
harmony engine so you can focus on writing patterns.

For the same music built with the Direct Pattern API, see demo_advanced.py.
"""

import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums

DRUMS_CHANNEL = 9
BASS_CHANNEL  = 5
SYNTH_CHANNEL = 0

composition = subsequence.Composition(bpm=120, key="E")
composition.harmony(style="aeolian_minor", cycle_beats=4, gravity=0.8)

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):
	p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
	p.hit_steps("snare_1", [4, 12], velocity=100)
	p.hit_steps("hi_hat_closed", range(16), velocity=80)
	p.velocity_shape(low=60, high=100)

@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):
	root = chord.root_note(40)
	p.sequence(steps=[0, 4, 8, 12], pitches=root)
	p.legato(0.9)

@composition.pattern(channel=SYNTH_CHANNEL, length=4)
def arp (p, chord):
	pitches = chord.tones(root=60, count=4)
	p.arpeggio(pitches, step=0.25, velocity=90, direction="up")

if __name__ == "__main__":
	composition.play()
