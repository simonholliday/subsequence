"""ISS telemetry → music.

Every musical parameter is driven by a real ISS data signal.
This example shows how Subsequence turns external data into a live composition:
  - The harmony engine changes chords every bar automatically.
  - ISS parameters modulate tempo, dynamics, rhythm density, and timbre.
  - Slowly-changing data is used as probability weights so patterns vary
    bar-to-bar even when the underlying signal barely moves.

Data is fetched from the public wheretheiss.at API every ~32 seconds (16 bars at
120 BPM). EasedValues interpolate between fetches so patterns see smooth curves
rather than sudden jumps.

ISS parameter → musical role
  latitude    → BPM, kick dropout, snare probability, hi-hat velocity,
                arp direction, chord-graph gravity
  longitude   → arp velocity
  altitude    → chord voicing count (3 or 4 notes)
  velocity    → (fetched and logged; very stable, available for experimentation)
  visibility  → chord graph style (major / Dorian minor), ride / shaker gating
  footprint   → ride cymbal pulse count
  solar lat   → chord velocity (solar warmth)
  solar lon   → open hi-hat accent step
  daynum      → (fetched and logged; use as daily seed if desired)

Listening guide — what you can determine by ear
  "Near a pole or the equator?"
      Fast tempo + solid kick + snare backbeat = near a pole.
      Slow tempo + sparse kick + no snare = near the equator.
  "Heading north or south?"
      Arpeggio ascending = heading north.
      Arpeggio descending = heading south.
      Direction flips at each orbital extreme (~every 46 minutes).
  "Daylight or eclipse?"
      Major key + ride cymbal = sunlight.
      Minor key + shaker = eclipse.
      This is the most dramatic shift — listen for the mode change.
  "Northern or southern hemisphere?"
      Louder hi-hats = northern hemisphere.
      Quieter hi-hats = southern hemisphere.
      (Subtle — easier to notice over several bars.)
"""

import logging
import requests

import subsequence
import subsequence.constants.gm_drums as gm_drums
import subsequence.easing
import subsequence.sequence_utils

logging.basicConfig(level=logging.INFO)

DRUMS_CHANNEL = 9
BASS_CHANNEL  = 5
CHORD_CHANNEL = 0
ARP_CHANNEL   = 3

composition = subsequence.Composition(
	bpm=120,
	key="E",
	output_device="Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"
)

# Day/night determines the harmonic mode.
# Major sounds open and functional; Dorian minor is darker and introspective.
CHORD_GRAPH_DAYLIGHT = "functional_major"
CHORD_GRAPH_ECLIPSED = "dorian_minor"

# EasedValues interpolate between API fetches, giving patterns a smooth curve
# rather than a step jump every 32 seconds. No initial value → first fetch
# sets the target immediately with no unintended ease from 0.
iss_lat       = subsequence.easing.EasedValue()  # 0=south pole, 0.5=equator, 1=north
iss_lon       = subsequence.easing.EasedValue()  # 0=180°W, 1=180°E
iss_alt       = subsequence.easing.EasedValue()  # 370–460 km → 0–1
iss_vel       = subsequence.easing.EasedValue()  # 27,500–27,750 km/h (very stable)
iss_footprint = subsequence.easing.EasedValue()  # Ground visibility diameter
iss_sol_lat   = subsequence.easing.EasedValue()  # Subsolar latitude (−23.4°–23.4°)
iss_sol_lon   = subsequence.easing.EasedValue()  # Subsolar longitude (−180°–180°)

# At 120 BPM, 16 bars ≈ 32 seconds. All patterns use
# progress = (p.cycle % FETCH_BARS) / FETCH_BARS
# to track where they are within each interpolation window.
FETCH_BARS = 16

# Safety default: gives patterns a working chord source if the first fetch fails.
composition.harmony(style=CHORD_GRAPH_DAYLIGHT, cycle_beats=4, gravity=0.5)


def fetch_iss (p) -> None:

	"""Fetch ISS telemetry and update BPM, harmony style, and shared data."""

	try:
		body = requests.get("https://api.wheretheiss.at/v1/satellites/25544").json()
		sc   = subsequence.sequence_utils.scale_clamp  # normalise any value to 0–1

		lat     = float(body["latitude"])
		lon     = float(body["longitude"])
		alt     = float(body["altitude"])
		vel     = float(body["velocity"])
		vis     = body["visibility"]
		foot    = float(body["footprint"])
		sol_lat = float(body["solar_lat"])
		sol_lon = float(body["solar_lon"])
		daynum  = float(body["daynum"])    # Julian Day Number — logged for context

		# Normalise to 0–1 using each parameter's known physical range.
		iss_lat.update(sc(lat,      -51.6, 51.6))   # Orbital inclination bounds
		iss_lon.update(sc(lon,      -180,  180))
		iss_alt.update(sc(alt,       370,  460))
		iss_vel.update(sc(vel,     27500, 27750))    # Very stable; available for use
		iss_footprint.update(sc(foot,   4400, 4600))
		iss_sol_lat.update(sc(sol_lat, -23.44, 23.44))  # Earth's axial tilt bounds
		iss_sol_lon.update(sc(sol_lon,  -180,  180))

		composition.data["iss_visibility"] = 1.0 if vis == "daylight" else 0.0

		# Solar longitude selects which 16th-note step gets an open hi-hat accent.
		# It shifts ~2 steps per hour as the subsolar point circles the Earth.
		composition.data["iss_hat_accent"] = int(iss_sol_lon.current * 15)

		logging.info(
			f"ISS  lat={lat:+.1f}°  lon={lon:+.1f}°  alt={alt:.0f}km  "
			f"vel={vel:.0f}km/h  vis={vis}  foot={foot:.0f}km  "
			f"sol=({sol_lat:+.1f}°,{sol_lon:+.1f}°)  day={daynum:.1f}"
		)

		# pole_proximity: 0 at the equator, 1 at the orbital extremes (±51.6°).
		# Latitude oscillates through its full range every ~92-minute orbit —
		# the fastest-changing ISS parameter and the primary musical driver here.
		pole_proximity = abs(iss_lat.current - 0.5) * 2

		# BPM: the music accelerates as the ISS arcs toward the poles and relaxes
		# at each equator crossing. Ramps smoothly over 4 bars.
		target_bpm = 90 + (40 * pole_proximity)    # 90 at equator, 130 at poles
		if p.cycle == 0:
			composition.set_bpm(target_bpm)        # Instant on startup
		else:
			composition.target_bpm(target_bpm, bars=4, shape="ease_in_out")

		# Chord-graph gravity: near the equator, transitions make bolder leaps
		# (low gravity). Near the poles they prefer strong resolution (high gravity).
		gravity = 0.3 + (0.5 * pole_proximity)     # 0.3 equator → 0.8 poles

		# The harmony engine picks a new chord every 4 beats, completely independent
		# of the fetch cycle. ISS data only steers the *style* and *character*.
		if vis == "daylight":
			composition.harmony(style=CHORD_GRAPH_DAYLIGHT, cycle_beats=4, gravity=gravity)
		else:
			composition.harmony(style=CHORD_GRAPH_ECLIPSED, cycle_beats=4, gravity=gravity)

	except Exception as exc:
		logging.warning(f"ISS fetch failed (keeping last values): {exc}")


composition.schedule(fetch_iss, cycle_beats=FETCH_BARS * 4, wait_for_initial=True)


# ── Core drums ─────────────────────────────────────────────────────────────────
@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	progress       = (p.cycle % FETCH_BARS) / FETCH_BARS
	pole_proximity = abs(iss_lat.get(progress) - 0.5) * 2
	equator_prox   = 1.0 - pole_proximity

	# Kick: four-on-the-floor, but near the equator each hit has a 40% chance
	# of dropping. This thins the pulse at the orbit's midpoint and fills it
	# back in as the ISS climbs toward a pole.
	p.hit_steps("kick_1", [0, 4, 8, 12], velocity=100,
	            probability=1.0 - 0.4 * equator_prox)

	# Snare: a fresh coin flip every bar, weighted by pole proximity.
	# The backbeat fades in near the poles and disappears near the equator.
	if p.rng.random() < pole_proximity:
		p.hit_steps("snare_1", [4, 12], velocity=100)

	# Hi-hat: velocity follows latitude — louder in the northern hemisphere,
	# quieter in the south. EasedValue.get() interpolates within each fetch window.
	p.hit_steps("hi_hat_closed", range(16), velocity=int(100 * iss_lat.get(progress)))

	# Open hi-hat: one accent per bar, placed by the sun's longitude.
	# A very slow signal — but it IS shifting, and it IS orbital.
	p.hit_steps("hi_hat_open", [composition.data.get("iss_hat_accent", 6)], velocity=60)


# ── Ride cymbal (daylight only) ─────────────────────────────────────────────────
@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def ride (p):

	# The ride only plays in sunlight — it brightens the texture and disappears
	# completely during eclipse, leaving the shaker to fill the space instead.
	if composition.data.get("iss_visibility") != 1.0:
		return

	progress = (p.cycle % FETCH_BARS) / FETCH_BARS

	# Footprint is the diameter of the ISS's ground visibility cone.
	# A wider footprint (higher orbit) feels more expansive → more ride hits.
	pulses = 3 + int(4 * iss_footprint.get(progress))   # 3–7 pulses
	p.euclidean("ride_1", pulses)
	p.velocity_shape(low=50, high=90)   # Organic dynamics via low-discrepancy sequence


# ── Shaker (eclipse only) ───────────────────────────────────────────────────────
@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def shaker (p):

	# Shaker fills the darker eclipse texture — steady 16ths with subtle variation.
	if composition.data.get("iss_visibility") == 1.0:
		return

	p.hit_steps("shaker", range(16), velocity=45)
	p.humanize(timing=0.02, velocity=0.1)   # Slight timing and velocity imprecision


# ── Arpeggio ────────────────────────────────────────────────────────────────────
@composition.pattern(channel=ARP_CHANNEL, length=4)
def arp (p, chord):

	# `chord` is injected by the harmony engine and changes every bar automatically.
	progress     = (p.cycle % FETCH_BARS) / FETCH_BARS
	arp_velocity = int(40 + 60 * iss_lon.get(progress))   # 40–100, louder heading east

	# Direction mirrors the ISS's north/south heading — ascending when going north,
	# descending when going south. iss_lat.delta is positive while climbing, negative
	# while descending. The flip happens naturally at each pole (~every 46 minutes).
	direction = "up" if iss_lat.delta >= 0 else "down"

	pitches = chord.tones(root=60, count=4)   # Four chord tones from C4 upward
	p.arpeggio(pitches, step=0.25, velocity=arp_velocity, duration=0.05, direction=direction)


# ── Bass ────────────────────────────────────────────────────────────────────────
@composition.pattern(channel=BASS_CHANNEL, length=4)
def bass (p, chord):

	# `chord` is injected by the harmony engine — new chord each bar, same rhythm.
	# bass_note() finds the chord's root nearest to E3 (MIDI 52), then drops one octave.
	bass_root = chord.bass_note(52, octave_offset=-1)

	# Eighth notes across the bar: a steady, unwavering orbital pulse.
	p.sequence(steps=range(0, 16, 2), pitches=bass_root)
	p.legato(0.9)


# ── Chord pad ───────────────────────────────────────────────────────────────────
@composition.pattern(channel=CHORD_CHANNEL, length=4)
def chords (p, chord):

	# `chord` is injected by the harmony engine and advances every bar.
	progress = (p.cycle % FETCH_BARS) / FETCH_BARS

	# Solar proximity: when the ISS's latitude aligns with the subsolar latitude,
	# the ISS is near solar noon — chords swell louder and brighter.
	solar_prox = 1.0 - abs(iss_lat.get(progress) - iss_sol_lat.get(progress))
	velocity   = 65 + int(30 * solar_prox)   # 65–95

	# Altitude controls voicing density. A higher orbit adds a fourth chord tone;
	# at lower altitude the voicing is a simple triad. Very slow, but audible
	# over a longer session as altitude drifts by tens of kilometres.
	count = 4 if iss_alt.current > 0.5 else 3

	p.chord(chord, root=52, velocity=velocity, count=count, legato=0.975)


if __name__ == "__main__":
	composition.display()
	composition.play()
