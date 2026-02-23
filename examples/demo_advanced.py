"""Direct Pattern API demo — drums, bass, and arp in E aeolian minor.

This produces the same music as demo.py, but uses the Direct Pattern API:
Pattern subclasses instead of decorated functions, and a manually managed
async event loop instead of composition.play().

Use this approach when you need persistent state across cycles, incremental
pattern updates, or multiple independent sequencers.
"""

import asyncio

import subsequence.composition
import subsequence.constants
import subsequence.constants.gm_drums as gm_drums
import subsequence.harmonic_state
import subsequence.pattern
import subsequence.pattern_builder
import subsequence.sequencer

DRUMS_CHANNEL = 9
BASS_CHANNEL  = 5
SYNTH_CHANNEL = 0


class DrumPattern (subsequence.pattern.Pattern):
	"""Kick, snare, and hi-hats — built using the PatternBuilder bridge."""

	def __init__ (self) -> None:
		super().__init__(channel=DRUMS_CHANNEL, length=4)
		self._build()

	def _build (self) -> None:
		self.steps = {}
		p = subsequence.pattern_builder.PatternBuilder(
			self, cycle=0, drum_note_map=gm_drums.GM_DRUM_MAP
		)
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100)
		p.hit_steps("snare_1", [4, 12], velocity=100)
		p.hit_steps("hi_hat_closed", range(16), velocity=80)
		p.velocity_shape(low=60, high=100)

	def on_reschedule (self) -> None:
		self._build()


class BassPattern (subsequence.pattern.Pattern):
	"""Quarter-note bass following the harmony engine's current chord."""

	def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState) -> None:
		super().__init__(channel=BASS_CHANNEL, length=4)
		self.harmonic_state = harmonic_state
		self._build()

	def _build (self) -> None:
		self.steps = {}
		chord = self.harmonic_state.get_current_chord()
		root  = chord.root_note(40)
		for beat in range(4):
			self.add_note_beats(beat, pitch=root, velocity=100, duration_beats=0.9)

	def on_reschedule (self) -> None:
		self._build()


class ArpPattern (subsequence.pattern.Pattern):
	"""Ascending arpeggio cycling through the current chord's tones."""

	def __init__ (self, harmonic_state: subsequence.harmonic_state.HarmonicState) -> None:
		super().__init__(channel=SYNTH_CHANNEL, length=4)
		self.harmonic_state = harmonic_state
		self._build()

	def _build (self) -> None:
		self.steps = {}
		chord   = self.harmonic_state.get_current_chord()
		pitches = chord.tones(root=60, count=4)
		self.add_arpeggio_beats(pitches, step_beats=0.25, velocity=90)

	def on_reschedule (self) -> None:
		self._build()


async def main () -> None:
	seq = subsequence.sequencer.Sequencer(initial_bpm=120)
	harmonic_state = subsequence.harmonic_state.HarmonicState(
		key_name="E", graph_style="aeolian_minor", key_gravity_blend=0.8
	)
	await subsequence.composition.schedule_harmonic_clock(
		seq, lambda: harmonic_state, cycle_beats=4
	)

	drums = DrumPattern()
	bass  = BassPattern(harmonic_state)
	arp   = ArpPattern(harmonic_state)

	await subsequence.composition.schedule_patterns(seq, [drums, bass, arp])
	await subsequence.composition.run_until_stopped(seq)


if __name__ == "__main__":
	asyncio.run(main())
