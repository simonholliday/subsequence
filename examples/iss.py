import logging
import requests

import subsequence

import subsequence.constants.durations as dur
import subsequence.constants.gm_drums as gm_drums
import subsequence.constants.midi_notes as notes
import subsequence.easing
import subsequence.sequence_utils
import subsequence.harmony as harmony

logging.basicConfig(level=logging.INFO)

DRUMS_CHANNEL = 9
BASS_CHANNEL = 5
CHORD_CHANNEL = 0
ARP_CHANNEL = 3

composition = subsequence.Composition(
	bpm=120,
	key="E",
	output_device="Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"
)

CHORD_GRAPH_DAYLIGHT = "functional_major"
CHORD_GRAPH_ECLIPSED = "dorian_minor"

ISS_CHORD_KEY        = "E"
ISS_CHORD_ROOT_MIDI  = notes.E3
ISS_CHORD_COUNT      = 12        # spans ~two octaves of diatonic steps

# EasedValue instances smooth discrete ISS telemetry updates into continuous
# per-pattern-cycle values.  By not providing an initial value, the very first
# fetch instantly sets the target without an unintended ease from 0.0.
iss_lat       = subsequence.easing.EasedValue()
iss_lon       = subsequence.easing.EasedValue()
iss_alt       = subsequence.easing.EasedValue()
iss_vel       = subsequence.easing.EasedValue()
iss_footprint = subsequence.easing.EasedValue()
iss_sol_lat   = subsequence.easing.EasedValue()
iss_sol_lon   = subsequence.easing.EasedValue()

def fetch_iss (p) -> None:

	"""Fetch ISS data into composition data."""

	try:

		response = requests.get(
			"https://api.wheretheiss.at/v1/satellites/25544"
		)

		body = response.json()

		# Utility shortcut to scale and clamp values to expected range.
		def sc(val, mn, mx) -> float:
			return subsequence.sequence_utils.scale_clamp(float(val), mn, mx)

		# Position (Restrained by 51.6° orbital inclination).
		# EasedValue.update() preserves the old value automatically, so patterns
		# can interpolate smoothly without any _prev keys in composition.data.
		lat = float(body["latitude"])
		lon = float(body["longitude"])
		iss_lat.update(sc(lat, -51.6, 51.6))
		iss_lon.update(sc(lon, -180, 180))   # Wraps at International Date Line

		# Altitude (370-460km range, periodically boosted)
		alt = float(body["altitude"])
		iss_alt.update(sc(alt, 370, 460))

		# Velocity (~27,500-27,750 km/h; inversely related to altitude)
		vel = float(body["velocity"])
		iss_vel.update(sc(vel, 27500, 27750))

		# Visibility (1.0 = daylight, 0.0 = eclipsed in Earth's shadow)
		vis = body["visibility"]
		composition.data["iss_visibility"] = 1.0 if vis == "daylight" else 0.0

		# Footprint (Diameter of visibility from ground (~4,400-4,600km))
		foot = float(body["footprint"])
		iss_footprint.update(sc(foot, 4400, 4600))

		# Solar Position (Sub-solar point where sun is directly overhead)
		sol_lat = float(body["solar_lat"])
		sol_lon = float(body["solar_lon"])
		iss_sol_lat.update(sc(sol_lat, -23.44, 23.44)) # Tilted between Tropics
		iss_sol_lon.update(sc(sol_lon, -180, 180))

		# Time (Standard astronomical and epoch formats)
		composition.data["iss_timestamp"] = int(body["timestamp"]) # Unix Epoch
		composition.data["iss_daynum"] = float(body["daynum"])	# Julian Day Number

		logging.info(
			f"ISS  lat={lat:+.1f}  lon={lon:+.1f}  "
			f"alt={alt:.1f}km  vel={vel:.3f}km/h  "
			f"vis={vis}  foot={foot:.0f}km  "
			f"sol=({sol_lat:+.1f},{sol_lon:+.1f})"
		)

		# Map velocity to BPM range 80-140.
		# On the first call (before playback starts) set BPM instantly so we
		# begin at the correct tempo; afterwards ramp smoothly.
		target_bpm = 60 + (80 * iss_vel.current)

		if p.cycle == 0:
			composition.set_bpm(target_bpm)
		else:
			composition.target_bpm(target_bpm, bars=16, shape="ease_in_out")

		# Change harmony style based on visibility, and store the mode so
		# patterns can build chord sequences in the matching scale.
		if vis == "daylight":
			composition.harmony(style=CHORD_GRAPH_DAYLIGHT, cycle_beats=4, gravity=0.5)
			mode = "ionian"
		else:
			composition.harmony(style=CHORD_GRAPH_ECLIPSED, cycle_beats=4, gravity=0.5)
			mode = "dorian"

		composition.data["iss_mode"] = mode

		# Map altitude to a chord from the diatonic ladder and store it so
		# altitude_chord and bass can both read it without recomputing.
		sequence = harmony.diatonic_chord_sequence(
			ISS_CHORD_KEY,
			root_midi = ISS_CHORD_ROOT_MIDI,
			count = ISS_CHORD_COUNT,
			mode = mode,
		)
		idx = int(iss_alt.current * (len(sequence) - 1))
		iss_chord, iss_root = sequence[idx]
		composition.data["iss_chord"]      = iss_chord
		composition.data["iss_chord_root"] = iss_root

	except Exception as exc:
		logging.warning(f"ISS fetch failed (keeping last value): {exc}")

composition.schedule(fetch_iss, cycle_beats = 16 * 4 * dur.QUARTER, wait_for_initial=True)

@composition.pattern(channel=DRUMS_CHANNEL, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums (p):

	kick_steps = set(range(0, 16, 4))
	p.hit_steps("kick_1", kick_steps, velocity=100)

	if iss_vel.current > 0.25:
		snare_steps = set(range(4, 16, 8))
		p.hit_steps("snare_1", snare_steps, velocity=100)

	# Closed hi-hat on every 16th note.
	# Velocity eases from the previous to the current ISS latitude over the
	# 16-bar fetch cycle. Range: silent at 0 (southern extreme) to 100 at 1 (northern).
	progress = (p.cycle % 16) / 16
	hat_velocity = int(100 * iss_lat.get(progress))
	p.hit_steps("hi_hat_closed", range(16), velocity=hat_velocity)

@composition.pattern(channel=ARP_CHANNEL, length=4)
def arp (p):

	chord = composition.data.get("iss_chord")
	root  = composition.data.get("iss_chord_root")

	if chord is None or root is None:
		return

	# 4 ascending chord tones spanning two octaves.
	pitches = chord.tones(root, count=4)

	# Velocity eases from the previous to the current ISS longitude over the
	# 16-bar fetch cycle. Range: silent at 0 (western extreme) to 100 at 1 (eastern).
	progress = (p.cycle % 16) / 16
	arp_velocity = int(100 * iss_lon.get(progress))

	# Arpeggio direction follows the ISS's north/south trajectory:
	# rising latitude (heading north) → ascending, falling → descending.
	direction = "up" if iss_lat.delta >= 0 else "down"
	p.arpeggio(pitches, step=0.25, velocity=arp_velocity, duration=0.05, direction=direction)

@composition.pattern(channel=BASS_CHANNEL, length=16)
def bass (p):

	chord = composition.data.get("iss_chord")
	root  = composition.data.get("iss_chord_root")

	if chord is None or root is None:
		return

	bass_root = chord.bass_note(root, octave_offset=-2)

	p.sequence(steps=range(0, 64, 2), pitches=bass_root)
	p.legato(0.9)

@composition.pattern(channel=CHORD_CHANNEL, length=16)
def chord (p):

	chord = composition.data.get("iss_chord")
	root  = composition.data.get("iss_chord_root")

	if chord is None or root is None:
		return

	# Play the chord as 4 notes (triad + octave doublings via count=4).
	p.chord(chord, root=root, velocity=85, count=4, legato=0.975)

if __name__ == "__main__":

	composition.display()
	composition.play()
