"""Emergence - generative drums that breathe, build, and break.

Six sections form a weighted graph that cycles infinitely.  The journey
usually flows void -> pulse -> swarm -> fury -> dissolve -> void, but
the graph's probabilistic edges mean sections sometimes repeat, and a
rare "fracture" section can erupt from swarm or fury - four bars of
controlled rhythmic chaos where even the kick pattern mutates.

Six Perlin noise fields wander independently at prime-ish speeds.
Because p.cycle increments forever, each pass through the form starts
at a different point in every noise field.  No two bars are ever the
same.  Cellular automata evolve each bar.  Ghost fills breathe with
Perlin modulation.  The result is dense but musical - structured
randomness within tight rhythmic constraints.

Sections:

  void       8 bars   Near-silence.  A heartbeat.
  pulse     12 bars   The kick finds its feet.  Layers hint.
  swarm     16 bars   Everything alive.  Density builds.
  fury       8 bars   Full intensity.  Short.  Explosive.
  fracture   4 bars   Musical chaos.  The beat mutates.  Rare.
  dissolve  12 bars   The exhale.  Layers fall away.

Channel 10 (zero-indexed) = MIDI channel 11.
"""

import subsequence
import subsequence.easing
import subsequence.sequence_utils
import subsequence.constants.instruments.gm_drums as gm_drums

DRUM_CHANNEL = 9
composition = subsequence.Composition(bpm=132)
groove = subsequence.Groove.from_agr("Swing 16ths 57.agr")

# ── Form ──────────────────────────────────────────────────────────────
#
# Six sections with weighted transitions.  The usual arc is:
#
#   void -> pulse -> swarm -> fury -> dissolve -> void -> ...
#
# But: swarm can erupt into fracture (20%).  Fury has a 40% chance
# of fracture.  Fracture is only 4 bars - a flash - then it scatters
# to dissolve, pulse, or all the way back to void.  Some sections
# can repeat (pulse lingers, swarm sustains).  The path through
# form is never quite the same.

composition.form({
	"void":      (8,  [("pulse", 4), ("void", 1)]),
	"pulse":     (12, [("swarm", 3), ("pulse", 1)]),
	"swarm":     (16, [("fury", 3), ("swarm", 1), ("fracture", 1)]),
	"fury":      (8,  [("dissolve", 3), ("fracture", 2)]),
	"fracture":  (4,  [("dissolve", 2), ("pulse", 1), ("void", 1)]),
	"dissolve":  (12, [("void", 3), ("pulse", 1)]),
}, start="pulse")

@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	"""Build one bar of drums for the current form section."""

	if not p.section:
		return

	section = p.section.name
	t = p.section.progress  # 0.0 -> ~1.0 within this section

	# ── Six Perlin fields - the wandering soul of the piece ───────
	# Each has a different speed (prime-ish multipliers) so they
	# never synchronise.  p.cycle increments every bar across all
	# sections, so each pass through the form samples a fresh region
	# of every noise field.
	ghost_wander = subsequence.sequence_utils.perlin_1d(p.cycle * 0.07, seed=1)
	hat_feel     = subsequence.sequence_utils.perlin_1d(p.cycle * 0.05, seed=2)
	tom_swell    = subsequence.sequence_utils.perlin_1d(p.cycle * 0.04, seed=3)
	kick_morph   = subsequence.sequence_utils.perlin_1d(p.cycle * 0.09, seed=4)
	space        = subsequence.sequence_utils.perlin_1d(p.cycle * 0.06, seed=5)
	chaos_spark  = subsequence.sequence_utils.perlin_1d(p.cycle * 0.13, seed=6)

	def ease (value: float, shape: str = "linear") -> float:

		"""Apply the named easing curve to a normalised value."""

		return subsequence.easing.get_easing(shape)(value)

	# ═══════════════════════════════════════════════════════════════
	#  VOID
	#
	#  Near silence.  A half-time kick fading in from nothing.
	#  Cellular automata whisper underneath - a rhythm heard through
	#  walls.  A side stick appears and disappears, gated by Perlin.
	#  The most important instrument here is space itself.
	# ═══════════════════════════════════════════════════════════════
	if section == "void":

		# Heartbeat: half-time kick - always audible, gently rising
		kick_vel = round(62 + 18 * ease(t, "ease_in"))
		p.hit_steps("kick_1", [0, 8], velocity=kick_vel)

		# Cellular whisper - high dropout, evolving from bar 1
		ca_dropout = 1.0 - (0.05 + 0.08 * ease(t, "ease_in"))
		p.cellular("kick_1", rule=30, velocity=28, no_overlap=True, dropout=ca_dropout)

		# Side stick - Perlin-gated, only appears when noise allows
		if ghost_wander > 0.65 and t >= 0.4:
			p.hit_steps("side_stick", [4], velocity=round(28 + 18 * ghost_wander))

		# A second side stick hints at the coming pulse
		if hat_feel > 0.55 and t >= 0.75:
			p.hit_steps("side_stick", [12], velocity=round(22 + 16 * hat_feel))

	# ═══════════════════════════════════════════════════════════════
	#  PULSE
	#
	#  The kick finds its footing - half-time becoming four-on-the-
	#  floor.  Snare enters tentatively.  Hats appear as whispers.
	#  Everything is a promise of what's to come.  Transition-aware:
	#  a snare roll builds if swarm is next.
	# ═══════════════════════════════════════════════════════════════
	elif section == "pulse":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=78)

		# Kick: half-time -> four-on-the-floor at progress 0.4
		if t < 0.4:
			kick_vel = round(70 + 20 * ease(t / 0.4))
			p.hit_steps("kick_1", [0, 8], velocity=kick_vel)
		else:
			kick_vel = round(85 + 12 * ease((t - 0.4) / 0.6, "ease_in"))
			p.hit_steps("kick_1", [0, 4, 8, 12], velocity=kick_vel)

		# Cellular ghost kicks - evolving texture underneath
		ca_dropout = 1.0 - (0.08 + 0.15 * ease(t, "ease_in"))
		p.cellular("kick_1", rule=30, velocity=28, no_overlap=True, dropout=ca_dropout)

		# Snare enters at progress 0.3
		if t >= 0.3:
			snare_vel = round(52 + 28 * ease(min(1.0, (t - 0.3) / 0.7), "ease_in"))
			p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Hats emerge in second half - sparse, Perlin-coloured
		if t >= 0.5:
			hat_d = 0.06 + 0.14 * ease(min(1.0, (t - 0.5) / 0.5), "ease_in")
			hat_d *= (0.5 + hat_feel * 0.5)
			p.bresenham_poly(parts={"hi_hat_closed": hat_d}, velocity={"hi_hat_closed": 50 + round(14 * hat_feel)})

		# Transition: snare roll if heading to swarm
		if (p.section.last_bar
				and p.section.next_section == "swarm"):
			p.hit_steps("snare_1", [8, 10, 12, 13, 14, 15], velocity=round(50 + 30 * ease(t)))

	# ═══════════════════════════════════════════════════════════════
	#  SWARM
	#
	#  The organism awakens.  All voices present from bar one, their
	#  density breathing with Perlin.  Ghost fills on kick and snare.
	#  Open hats punctuate.  Toms stir when their Perlin field rises.
	#  Chaos sparks trigger occasional snare fills.
	# ═══════════════════════════════════════════════════════════════
	elif section == "swarm":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=100)

		# Kick: confident, building
		kick_vel = round(90 + 14 * ease(t, "ease_in"))
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=kick_vel)

		# Kick ghosts: CA layer, Perlin-breathing density
		ca_dropout = 1.0 - (0.20 + 0.20 * ghost_wander)
		p.cellular("kick_1", rule=30, velocity=34, no_overlap=True, dropout=ca_dropout)

		# Kick ghost fill: offbeat bias, enters at 0.15
		if t >= 0.15:
			gf_d = (0.05 + 0.15 * ease(min(1.0, (t - 0.15) / 0.85))) * (0.5 + ghost_wander * 0.5)
			if gf_d > 0.02:
				p.ghost_fill("kick_1", density=gf_d, velocity=(22, 42), bias="offbeat", no_overlap=True)

		# Snare: gaining authority
		snare_vel = round(76 + 20 * ease(t))
		p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Snare ghosts: "before" bias - groove glue
		gs_d = (0.04 + 0.14 * ease(t, "ease_in_out"))
		gs_d *= (0.6 + ghost_wander * 0.4)
		if gs_d > 0.02:
			p.ghost_fill("snare_1", density=gs_d, velocity=(18, 36), bias="before", no_overlap=True)

		# Hats: density builds, open hat enters at 0.55
		hat_d = 0.18 + 0.38 * ease(t, "ease_in_out")
		hat_d *= (0.55 + hat_feel * 0.45)
		parts = {"hi_hat_closed": hat_d}
		if t >= 0.55:
			hat_open_d = 0.02 + 0.09 * ease(min(1.0, (t - 0.55) / 0.45))
			hat_open_d *= (0.35 + hat_feel * 0.65)
			parts["hi_hat_open"] = hat_open_d
		p.bresenham_poly(
			parts=parts,
			velocity={"hi_hat_closed": 62, "hi_hat_open": 78}, )

		# Toms: emerge when tom_swell Perlin rises
		if t >= 0.4 and tom_swell > 0.35:
			tom_d = 0.20 * ease(min(1.0, (t - 0.4) / 0.6)) * (tom_swell - 0.35) / 0.65
			if tom_d > 0.01:
				p.bresenham_poly(parts={
						"high_tom":    tom_d * 0.50,
						"low_mid_tom": tom_d * 0.30,
						"low_tom":     tom_d * 0.20, },
					velocity={
						"high_tom": 76, "low_mid_tom": 71, "low_tom": 66, },
				)

		# Chaos spark: snare fill on phrase boundaries
		if chaos_spark > 0.78 and p.section.bar % 4 == 3:
			p.hit_steps("snare_1", [13, 14, 15], velocity=round(52 + 38 * chaos_spark))

		# Transition: ride swell if fury is next
		if (p.section.last_bar
				and p.section.next_section == "fury"):
			p.hit_steps("ride_1", [0, 4, 8, 12], velocity=68)

	# ═══════════════════════════════════════════════════════════════
	#  FURY
	#
	#  Maximum intensity.  Every voice at full power, every ghost
	#  layer active.  Short - 8 bars - a controlled explosion.
	#  CA fractal textures on hats, tom cascades, snare fills
	#  ignited by the chaos spark.  Dense but locked to the grid.
	# ═══════════════════════════════════════════════════════════════
	elif section == "fury":

		# Crash on entry and every 4th bar to sustain energy
		if p.section.first_bar or p.section.bar % 4 == 0:
			p.hit_steps("crash_1", [0], velocity=120)

		# Kick: FULL POWER
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=112)

		# Maximum kick ghost layering: CA + probability fill
		p.cellular("kick_1", rule=30, velocity=40, no_overlap=True, dropout=0.26)
		gf_d = 0.22 * (0.5 + ghost_wander * 0.5)
		p.ghost_fill("kick_1", density=gf_d, velocity=(28, 48), bias="offbeat", no_overlap=True)

		# Snare: full authority
		p.hit_steps("snare_1", [4, 12], velocity=108)

		# Thick snare ghosts
		gs_d = 0.20 * (0.6 + ghost_wander * 0.4)
		p.ghost_fill("snare_1", density=gs_d, velocity=(22, 42), bias="before", no_overlap=True)

		# Hats: near-maximum density, Perlin-breathing
		hat_d = 0.78 + 0.22 * hat_feel
		hat_open_d = 0.09 + 0.09 * hat_feel
		p.bresenham_poly(
			parts={"hi_hat_closed": hat_d, "hi_hat_open": hat_open_d},
			velocity={"hi_hat_closed": 72, "hi_hat_open": 86}, )

		# CA hat fractal texture - Rule 90 Sierpinski patterns
		p.cellular("hi_hat_closed", rule=90, velocity=42, no_overlap=True, dropout=0.36)

		# Tom cascades
		tom_d = 0.28 * (0.3 + tom_swell * 0.7)
		if tom_d > 0.01:
			p.bresenham_poly(parts={
					"high_tom":    tom_d * 0.40,
					"low_mid_tom": tom_d * 0.35,
					"low_tom":     tom_d * 0.25, },
				velocity={
					"high_tom": 90, "low_mid_tom": 85, "low_tom": 80, },
			)

		# Chaos spark: dense syncopated snare bursts
		if chaos_spark > 0.6:
			spark_density = 0.12 + 0.22 * (chaos_spark - 0.6) / 0.4
			spark_vel = round(45 + 35 * (chaos_spark - 0.6) / 0.4)
			p.ghost_fill("snare_1", density=spark_density,
				velocity=(spark_vel - 12, spark_vel), bias="syncopated", no_overlap=True)

		# Transition: tom cascade into fracture
		if (p.section.last_bar
				and p.section.next_section == "fracture"):
			p.hit_steps("high_tom", [12, 13], velocity=110)
			p.hit_steps("low_mid_tom", [14], velocity=105)
			p.hit_steps("low_tom", [15], velocity=100)

	# ═══════════════════════════════════════════════════════════════
	#  FRACTURE
	#
	#  Musical chaos - four bars of controlled madness.  The kick
	#  itself mutates: euclidean rhythms with Perlin-driven pulse
	#  counts instead of four-on-the-floor.  CA Rule 110 (Turing-
	#  complete) drives hats - intricate, non-repeating, structured.
	#  Syncopated snare ghosts at high density.  Tom barrage.
	#  Everything is algorithmically placed - structured chaos,
	#  not noise.
	# ═══════════════════════════════════════════════════════════════
	elif section == "fracture":

		# No crash - fracture erupts mid-flow, not at a boundary

		# Kick: MUTATED - euclidean with Perlin-driven pulse count
		# 3 pulses = angular, minimal.  8 pulses = dense machine-gun.
		pulse_count = round(3 + 5 * kick_morph)
		p.euclidean("kick_1", pulses=pulse_count, velocity=round(92 + 20 * kick_morph))

		# Kick CA: Rule 110 - Turing-complete, complex
		p.cellular("kick_1", rule=110, velocity=44, no_overlap=True, dropout=0.20)

		# Snare anchor + dense syncopated ghosts
		p.hit_steps("snare_1", [4, 12], velocity=102)
		p.ghost_fill("snare_1", density=0.28 * (0.5 + ghost_wander * 0.5),
			velocity=(26, 55), bias="syncopated", no_overlap=True)

		# Hats: CA Rule 110 - intricate, unpredictable, structured
		p.cellular("hi_hat_closed", rule=110, velocity=round(50 + 24 * hat_feel), dropout=0.16)

		# Open hat accents when Perlin allows
		if hat_feel > 0.4:
			oh_d = 0.10 * hat_feel
			p.bresenham_poly(parts={"hi_hat_open": oh_d}, velocity={"hi_hat_open": 85}, )

		# Tom barrage - all three voices at high density
		tom_d = 0.36 * (0.3 + tom_swell * 0.7)
		if tom_d > 0.01:
			p.bresenham_poly(parts={
					"high_tom":    tom_d * 0.35,
					"low_mid_tom": tom_d * 0.35,
					"low_tom":     tom_d * 0.30, },
				velocity={
					"high_tom": 92, "low_mid_tom": 88, "low_tom": 82, },
			)

		# Ride: CA chaos layer when spark is high
		if chaos_spark > 0.42:
			p.cellular("ride_1", rule=30, velocity=round(38 + 30 * chaos_spark), dropout=0.42)

	# ═══════════════════════════════════════════════════════════════
	#  DISSOLVE
	#
	#  The exhale.  Kick drops to half-time.  Layers thin and fade
	#  with eased curves.  A CA whisper returns near the end -
	#  echoing the void.  The final bars fill with pedal hat wash
	#  before silence takes over.
	# ═══════════════════════════════════════════════════════════════
	elif section == "dissolve":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=86)

		# Kick: half-time from the start, fading
		kick_vel = round(90 - 28 * ease(t, "ease_out"))
		p.hit_steps("kick_1", [0, 8], velocity=kick_vel)

		# Snare: fading backbeat - disappears around 75% through
		snare_vel = round(86 - 55 * ease(t, "ease_out"))
		if snare_vel > 36:
			p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Snare ghosts thin out
		gs_d = 0.20 * (1.0 - 0.92 * ease(t, "ease_out"))
		gs_d *= (0.6 + ghost_wander * 0.4)
		if gs_d > 0.02:
			p.ghost_fill("snare_1", density=gs_d, velocity=(16, 30), bias="before", no_overlap=True)

		# Hats thin
		hat_d = 0.45 * (1.0 - 0.88 * ease(t, "ease_out"))
		hat_d *= (0.55 + hat_feel * 0.45)
		if hat_d > 0.01:
			p.bresenham_poly(parts={"hi_hat_closed": hat_d}, velocity={"hi_hat_closed": 56}, )

		# Toms fade in first third
		if t < 0.33:
			tom_d = 0.16 * (1.0 - ease(t * 3.0, "ease_out"))
			tom_d *= (0.3 + tom_swell * 0.7)
			if tom_d > 0.01:
				p.bresenham_poly(parts={
						"high_tom":    tom_d * 0.50,
						"low_mid_tom": tom_d * 0.30,
						"low_tom":     tom_d * 0.20, },
					velocity={
						"high_tom": 70, "low_mid_tom": 65, "low_tom": 60, },
				)

		# CA whisper returns near the end - echoing the void
		if t >= 0.7:
			p.cellular("kick_1", rule=30, velocity=18, no_overlap=True, dropout=0.90)

		# Pedal hat wash in final 2 bars
		if p.section.bar >= p.section.bars - 2:
			wash_bar = p.section.bar - (p.section.bars - 2)
			pedal_vel = round(46 - 20 * ease(wash_bar / 1.0, "ease_out"))
			p.hit_steps("hi_hat_pedal", range(16), velocity=max(20, pedal_vel))

		# Closing crash on the very last step
		if p.section.last_bar:
			p.hit_steps("crash_1", [15], velocity=70)

	# ── Lightning ─────────────────────────────────────────────────
	# When the chaos_spark Perlin peaks above 0.92, a rare burst
	# of maximum density fires on top of whatever section is
	# playing.  Occurs roughly once every 70-80 bars - a flash
	# of transcendence.  Void is exempt (silence is sacred).
	if chaos_spark > 0.92 and section != "void":
		p.ghost_fill("kick_1", density=0.32, velocity=(34, 55), bias="uniform", no_overlap=True)
		p.ghost_fill("snare_1", density=0.22, velocity=(28, 48), bias="syncopated", no_overlap=True)
		if section != "fracture":  # fracture already has ride
			p.cellular("ride_1", rule=30, velocity=46, dropout=0.48)

	# ── Groove template (optional) ────────────────────────────────
	# Uncomment to add swing feel from the .agr groove file:
	# p.groove(groove)

if __name__ == "__main__":

	composition.display(grid=True, grid_scale=2)
	composition.play()
