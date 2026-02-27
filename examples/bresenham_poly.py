"""Dense generative drums - inspired by dense electronic music production.

Uses composition.form() to define four sections that cycle infinitely
with weighted probabilistic transitions.  Each section has its own
sonic character from bar one - Perlin noise modulates parameters within
sections, and the weighted graph means the journey through form is
never quite the same twice.

Form sections (16 bars each, graph transitions):

  A  "pulse"     Kick anchor + sparse cellular ghost texture
  B  "emerge"    Layers enter, ghost fills thicken via Perlin
  C  "peak"      Full density, all voices, maximum ghost fill
  D  "dissolve"  Strip back, echoes of the peak

Channel 10 (zero-indexed) = MIDI channel 11.
"""

import subsequence
import subsequence.easing
import subsequence.sequence_utils
import subsequence.constants.instruments.gm_drums as gm_drums

DRUM_CHANNEL = 10

composition = subsequence.Composition(bpm=120)

groove = subsequence.Groove.from_agr("Swing 16ths 57.agr")

# ── Form: weighted graph cycles through sections infinitely ──────────
# Each section is 16 bars.  Transitions are weighted so the form usually
# progresses pulse → emerge → peak → dissolve → pulse, but sometimes
# a section repeats - keeping the trajectory while adding surprise.
composition.form({
	"pulse":    (16, [("emerge", 3), ("pulse", 1)]),
	"emerge":   (16, [("peak", 3), ("emerge", 1)]),
	"peak":     (16, [("dissolve", 3), ("peak", 1)]),
	"dissolve": (16, [("pulse", 3), ("emerge", 1)]),
}, start="pulse")


@composition.pattern(channel=DRUM_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	if not p.section:
		return

	section = p.section.name
	t = p.section.progress  # 0.0 → ~1.0 within this section

	# ── Perlin-driven wandering parameters ────────────────────────────
	# Each wanders smoothly over time.  Because p.cycle increments
	# forever, each pass through the form starts at a different point
	# in the noise field - "no sound ever plays the same way twice."
	ghost_wander = subsequence.sequence_utils.perlin_1d(p.cycle * 0.07, seed=1)
	hat_feel     = subsequence.sequence_utils.perlin_1d(p.cycle * 0.05, seed=2)
	tom_swell    = subsequence.sequence_utils.perlin_1d(p.cycle * 0.04, seed=3)

	def ease (value: float, shape: str = "linear") -> float:
		"""Apply an easing curve to a 0-1 progress value."""
		return subsequence.easing.get_easing(shape)(value)

	# ═══════════════════════════════════════════════════════════════════
	#  A: "PULSE"
	#
	#  Minimal.  Four-on-the-floor kick is the only constant.  A single
	#  cellular automaton ghost layer slowly emerges, the snare enters
	#  mid-section, and hats begin to appear at the tail.  Space and air.
	# ═══════════════════════════════════════════════════════════════════
	if section == "pulse":

		# Crash marks the top of the section
		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=120)

		# Kick: four on the floor, steady
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=90)

		# Snare backbeat enters at progress 0.25 (~bar 4), tentative
		if t >= 0.25:
			snare_vel = round(65 + 13 * ease(min(1.0, (t - 0.25) / 0.75), "ease_in"))
			p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Cellular ghost kicks emerge at progress 0.5 - Rule 30 structured chaos
		if t >= 0.5:
			ca_dropout = 1.0 - (0.1 + 0.2 * ease(min(1.0, (t - 0.5) / 0.5), "ease_in"))
			p.cellular("kick_1", rule=30, velocity=35,
				no_overlap=True, dropout=ca_dropout)

		# Hats begin to appear at progress 0.75 - just a whisper
		if t >= 0.75:
			hat_d = 0.10 + 0.10 * ease(min(1.0, (t - 0.75) / 0.25), "ease_in")
			hat_d *= (0.7 + hat_feel * 0.6)
			p.bresenham_poly(
				parts={"hi_hat_closed": hat_d},
				velocity={"hi_hat_closed": 62},
			)

	# ═══════════════════════════════════════════════════════════════════
	#  B: "EMERGE"
	#
	#  Layers enter and thicken.  Ghost fills appear on kick and snare,
	#  driven by Perlin noise.  Hats open up.  Open hats begin to
	#  punctuate.  The groove starts to breathe.
	# ═══════════════════════════════════════════════════════════════════
	elif section == "emerge":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=95)

		# Kick: building confidence
		kick_vel = round(96 + 11 * ease(t, "ease_in"))
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=kick_vel)

		# Kick ghosts: CA layer thickens through section
		ca_dropout = 1.0 - (0.3 + 0.2 * ease(t, "ease_in"))
		p.cellular("kick_1", rule=30, velocity=38,
			no_overlap=True, dropout=ca_dropout)

		# Kick ghost fill: enters at progress 0.25, density builds
		if t >= 0.25:
			gf_density = (0.05 + 0.13 * ease(min(1.0, (t - 0.25) / 0.75)))
			gf_density *= (0.6 + ghost_wander * 0.4)
			if gf_density > 0.02:
				p.ghost_fill("kick_1", density=gf_density,
					velocity=(28, 45), bias="offbeat", no_overlap=True)

		# Snare: gaining confidence through section
		snare_vel = round(78 + 17 * ease(t))
		p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Snare ghosts: "before" bias - offset ghosts as groove glue
		gs_density = 0.06 + 0.09 * ease(t, "ease_in_out")
		gs_density *= (0.7 + ghost_wander * 0.3)
		if gs_density > 0.02:
			p.ghost_fill("snare_1", density=gs_density,
				velocity=(20, 36), bias="before", no_overlap=True)

		# Hats: closed present throughout, open enters at progress 0.75
		hat_d = 0.20 + 0.25 * ease(t, "ease_in_out")
		hat_d *= (0.7 + hat_feel * 0.6)
		parts = {"hi_hat_closed": hat_d}
		if t >= 0.75:
			hat_open_d = 0.02 + 0.06 * ease(min(1.0, (t - 0.75) / 0.25), "ease_in_out")
			hat_open_d *= (0.5 + hat_feel * 0.5)
			parts["hi_hat_open"] = hat_open_d
		p.bresenham_poly(
			parts=parts,
			velocity={"hi_hat_closed": 68, "hi_hat_open": 80},
		)

	# ═══════════════════════════════════════════════════════════════════
	#  C: "PEAK"
	#
	#  Full density from bar one.  All voices active.  No building -
	#  Perlin noise modulates density and velocity, keeping the section
	#  alive without ramping.  CA hat texture adds fractal micro-detail.
	#  Toms sweep across the kit.  Dense but not chaotic,
	#  everything interlocking.
	# ═══════════════════════════════════════════════════════════════════
	elif section == "peak":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=95)

		# Kick: full authority, constant
		p.hit_steps("kick_1", [0, 4, 8, 12], velocity=110)

		# Kick ghosts: maximum layers (CA + probability fill)
		p.cellular("kick_1", rule=30, velocity=38,
			no_overlap=True, dropout=0.35)

		gf_density = 0.20 * (0.6 + ghost_wander * 0.4)
		p.ghost_fill("kick_1", density=gf_density,
			velocity=(28, 45), bias="offbeat", no_overlap=True)

		# Snare: full, constant
		p.hit_steps("snare_1", [4, 12], velocity=100)

		# Snare ghosts: high density, Perlin-modulated
		gs_density = 0.18 * (0.7 + ghost_wander * 0.3)
		p.ghost_fill("snare_1", density=gs_density,
			velocity=(20, 36), bias="before", no_overlap=True)

		# Hats: full density, Perlin-breathing toward every step
		hat_d = 0.75 + 0.25 * hat_feel
		hat_open_d = 0.12 * (0.5 + hat_feel * 0.5)
		p.bresenham_poly(
			parts={"hi_hat_closed": hat_d, "hi_hat_open": hat_open_d},
			velocity={"hi_hat_closed": 68, "hi_hat_open": 80},
		)

		# CA hat texture: Sierpinski-like patterns
		p.cellular("hi_hat_closed", rule=90, velocity=40,
			no_overlap=True, dropout=0.45)

		# Toms: Perlin-driven sweeps - high, mid, low interlock
		tom_d = 0.25 * (0.4 + tom_swell * 0.6)
		if tom_d > 0.01:
			p.bresenham_poly(
				parts={
					"high_tom":    tom_d * 0.50,
					"low_mid_tom": tom_d * 0.30,
					"low_tom":     tom_d * 0.20,
				},
				velocity={"high_tom": 85, "low_mid_tom": 80, "low_tom": 75},
			)

	# ═══════════════════════════════════════════════════════════════════
	#  D: "DISSOLVE"
	#
	#  Strip back.  Kick drops to half-time, opening space.  Layers
	#  thin and fade.  The final bar fills with pedal hat before the
	#  crash resets.  Each dissolve is different because the Perlin
	#  noise has drifted.
	# ═══════════════════════════════════════════════════════════════════
	elif section == "dissolve":

		if p.section.first_bar:
			p.hit_steps("crash_1", [0], velocity=95)

		# Kick: half-time from the start, fading
		kick_vel = round(100 - 15 * ease(t, "ease_out"))
		p.hit_steps("kick_1", [0, 8], velocity=kick_vel)

		# Snare: fading backbeat
		snare_vel = round(100 - 35 * ease(t, "ease_out"))
		p.hit_steps("snare_1", [4, 12], velocity=snare_vel)

		# Snare ghosts: thinning out
		gs_density = 0.22 * (1.0 - 0.9 * ease(t, "ease_out"))
		gs_density *= (0.7 + ghost_wander * 0.3)
		if gs_density > 0.02:
			p.ghost_fill("snare_1", density=gs_density,
				velocity=(20, 36), bias="before", no_overlap=True)

		# Hats: thinning
		hat_d = 0.58 * (1.0 - 0.8 * ease(t, "ease_out"))
		hat_d *= (0.7 + hat_feel * 0.6)
		if hat_d > 0.01:
			p.bresenham_poly(
				parts={"hi_hat_closed": hat_d},
				velocity={"hi_hat_closed": 68},
			)

		# Toms: fade out in first half of section
		if t < 0.5:
			tom_d = 0.35 * (1.0 - ease(t * 2.0, "ease_out"))
			tom_d *= (0.4 + tom_swell * 0.6)
			if tom_d > 0.01:
				p.bresenham_poly(
					parts={
						"high_tom":    tom_d * 0.50,
						"low_mid_tom": tom_d * 0.30,
						"low_tom":     tom_d * 0.20,
					},
					velocity={"high_tom": 85, "low_mid_tom": 80, "low_tom": 75},
				)

		# Final bar: transition fill into the next section
		if p.section.last_bar:
			p.hit_steps("hi_hat_pedal", range(16), velocity=55)
			p.hit_steps("crash_1", [15], velocity=90)

	# ── Post-placement: groove template ───────────────────────────────
	# p.groove(groove)

if __name__ == "__main__":
	composition.display(grid=True, grid_scale=5)
	composition.play()
