"""
Subsequence Advanced Demo — Direct Pattern API

The same generative composition as demo.py, but using direct Pattern
subclassing instead of the Composition decorator API. This is the
"power user" approach — you manage the sequencer, harmonic state,
and form state yourself, gaining full control over scheduling and
pattern internals.

If you're new to Subsequence, start with demo.py. Come here when you
need something the Composition API doesn't expose.

How to read this file
─────────────────────
1. MIDI Setup      — Device name and channel assignments (same as demo.py).
2. Sequencer       — Create the low-level sequencer with a tempo.
3. Harmony         — Create a HarmonicState and schedule it on a beat clock.
4. Form            — Create a FormState and schedule it to advance each bar.
5. External Data   — Schedule a background task via the module helper.
6. Pattern Classes — Subclass Pattern directly. Override _build_pattern()
                     to populate notes and on_reschedule() to rebuild each
                     cycle. Read the FormState yourself for section awareness.
7. Main            — Wire everything together and run until Ctrl+C.

Musical overview
────────────────
Identical to demo.py: the form is a graph where the intro (4 bars)
plays once then moves to the verse. From there, the form follows
weighted transitions — verse leads to chorus (75%) or bridge (25%),
chorus goes to breakdown (67%) or verse (33%), bridge always goes
to chorus, and breakdown always returns to verse. The intro never
returns. The kick always plays. The snare enters in the chorus with
euclidean density modulated by ISS longitude. Hats are muted during
the intro. Chords build intensity through each section. The arpeggio
and bass only play during the chorus. Chord changes happen every bar
(4 beats) via the dark_minor graph in E.
"""

import asyncio
import json
import logging
import random
import typing
import urllib.request

import subsequence.composition
import subsequence.constants
import subsequence.harmonic_state
import subsequence.harmony
import subsequence.pattern
import subsequence.sequence_utils
import subsequence.sequencer


# Configure logging so you can see bar numbers and ISS fetches in the console.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── MIDI Setup ──────────────────────────────────────────────────────
#
# These values are specific to YOUR studio. Change them to match your
# MIDI interface and instrument channel assignments.

MIDI_DEVICE = "Scarlett 2i4 USB:Scarlett 2i4 USB MIDI 1 16:0"

DRUMS_MIDI_CHANNEL = 9       # Channel 10 in 1-indexed MIDI (standard drums)
EP_MIDI_CHANNEL = 8          # Electric piano / pad synth
SYNTH_MIDI_CHANNEL = 0       # Lead / arpeggio synth
BASS_MIDI_CHANNEL = 5        # Bass synth

# Drum note map — maps names to MIDI note numbers.
# These depend on your drum machine or sample library.
DRUM_KICK = 36
DRUM_SNARE = 38
DRUM_HH_CLOSED = 44
DRUM_HH_OPEN = 46


# ─── Pattern Classes ─────────────────────────────────────────────────
#
# Each pattern is a subclass of Pattern. The key methods are:
#
#   _build_pattern()   — Clear self.steps and populate notes for one cycle.
#   on_reschedule()    — Called by the sequencer before each new cycle.
#                        Increment your cycle counter and call _build_pattern().
#
# Unlike the Composition API (where the module injects chords and section
# info for you), here you hold references to the shared HarmonicState and
# FormState and read them yourself.
#
# All drum patterns use a 16-step grid (sixteenth notes) over 4 beats.


class KickSnarePattern (subsequence.pattern.Pattern):

	"""Four-on-the-floor kick with a euclidean snare (chorus only)."""

	def __init__ (
		self,
		form_state: subsequence.composition.FormState,
		data: typing.Dict[str, typing.Any],
		length: int = 4,
		reschedule_lookahead: int = 1
	) -> None:

		"""Initialize the kick/snare pattern with form state and shared data."""

		super().__init__(
			channel = DRUMS_MIDI_CHANNEL,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.form_state = form_state
		self.data = data
		self.rng = random.Random()
		self.cycle_count = 0

		self._build_pattern()

	def _build_pattern (self) -> None:

		"""Build a 16-step kick/snare cycle, section-aware."""

		self.steps = {}

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		# Fixed kick on every beat — steps 0, 4, 8, 12 on the 16-step grid.
		kick_sequence = [0] * 16
		for idx in [0, 4, 8, 12]:
			kick_sequence[idx] = 1

		self.add_sequence(
			kick_sequence,
			step_duration = step_duration,
			pitch = DRUM_KICK,
			velocity = 127
		)

		# Snare only during the chorus.
		section = self.form_state.get_section_info()

		if section and section.name == "chorus":
			nl = self.data.get("longitude_norm", 0.5)
			max_snare_hits = max(2, round(nl * 8))
			snare_hits = self.rng.randint(1, max_snare_hits)
			snare_seq = subsequence.sequence_utils.generate_euclidean_sequence(16, snare_hits)
			snare_indices = subsequence.sequence_utils.sequence_to_indices(snare_seq)
			snare_indices = subsequence.sequence_utils.roll(snare_indices, 4, 16)

			snare_sequence = [0] * 16
			for idx in snare_indices:
				snare_sequence[idx] = 1

			self.add_sequence(
				snare_sequence,
				step_duration = step_duration,
				pitch = DRUM_SNARE,
				velocity = 100
			)

	def on_reschedule (self) -> None:

		"""Rebuild the pattern before the next cycle is scheduled."""

		self.cycle_count += 1
		self._build_pattern()


class HatPattern (subsequence.pattern.Pattern):

	"""Bresenham hi-hats with stochastic dropout and velocity shaping."""

	def __init__ (
		self,
		form_state: subsequence.composition.FormState,
		length: int = 4,
		reschedule_lookahead: int = 1
	) -> None:

		"""Initialize the hi-hat pattern with form state."""

		super().__init__(
			channel = DRUMS_MIDI_CHANNEL,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.form_state = form_state
		self.rng = random.Random()

		self._build_pattern()

	def _build_pattern (self) -> None:

		"""Build a 16-step hi-hat cycle, muted during the intro."""

		self.steps = {}

		# Silent during intro.
		section = self.form_state.get_section_info()
		if not section or section.name == "intro":
			return

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		# 8 hits distributed across 16 steps via Bresenham.
		hh_sequence = subsequence.sequence_utils.generate_bresenham_sequence(steps=16, pulses=8)

		# Van der Corput velocity shaping for organic feel.
		vdc_values = subsequence.sequence_utils.generate_van_der_corput_sequence(n=16, base=2)
		hh_velocities = [int(60 + (v * 40)) for v in vdc_values]

		# Stochastic dropout.
		for i in range(16):
			if hh_sequence[i] and self.rng.random() < 0.1:
				hh_sequence[i] = 0

		self.add_sequence(
			hh_sequence,
			step_duration = step_duration,
			pitch = DRUM_HH_CLOSED,
			velocity = hh_velocities
		)

		# Occasional open hat at step 14 (beat 3.5).
		if self.rng.random() < 0.6:
			self.add_note(
				14 * step_duration,
				DRUM_HH_OPEN,
				85,
				step_duration
			)

	def on_reschedule (self) -> None:

		"""Rebuild the pattern before the next cycle is scheduled."""

		self._build_pattern()


class ChordPadPattern (subsequence.pattern.Pattern):

	"""Sustained chord pads that follow the harmonic state."""

	def __init__ (
		self,
		harmonic_state: subsequence.harmonic_state.HarmonicState,
		form_state: subsequence.composition.FormState,
		channel: int,
		length: int = 4,
		reschedule_lookahead: int = 1,
		root_midi: int = 52
	) -> None:

		"""Initialize the chord pad with harmonic state, form state, and root note."""

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.form_state = form_state
		self.root_midi = root_midi

		self._build_pattern()

	def _build_pattern (self) -> None:

		"""Build a sustained chord, section-aware with intensity shaping."""

		self.steps = {}

		section = self.form_state.get_section_info()

		# Silent during intro.
		if not section or section.name == "intro":
			return

		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)
		chord_intervals = chord.intervals()

		duration = int(self.length * subsequence.constants.MIDI_QUARTER_NOTE)

		# Quiet during breakdown.
		if section.name == "breakdown":
			velocity = 50
		else:
			# Build intensity through the section.
			velocity = int(70 + 30 * section.progress)

		for interval in chord_intervals:
			self.add_note(
				position = 0,
				pitch = chord_root + interval,
				velocity = velocity,
				duration = duration
			)

	def on_reschedule (self) -> None:

		"""Rebuild the chord pad after the harmonic state advances."""

		self._build_pattern()


class MotifPattern (subsequence.pattern.Pattern):

	"""A cycling arpeggio built from the current chord tones (chorus only)."""

	def __init__ (
		self,
		harmonic_state: subsequence.harmonic_state.HarmonicState,
		form_state: subsequence.composition.FormState,
		channel: int,
		length: int = 4,
		reschedule_lookahead: int = 1,
		root_midi: int = 76
	) -> None:

		"""Initialize the arpeggio motif with harmonic state, form state, and root note."""

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.form_state = form_state
		self.root_midi = root_midi

		self._build_pattern()

	def _build_pattern (self) -> None:

		"""Build a cycling arpeggio from chord tones, chorus only."""

		self.steps = {}

		# Only plays during the chorus.
		section = self.form_state.get_section_info()
		if not section or section.name != "chorus":
			return

		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)
		chord_intervals = chord.intervals()[:3]

		pitches = [chord_root + interval for interval in chord_intervals]

		self.add_arpeggio_beats(pitches=pitches, step_beats=0.25, velocity=90)

	def on_reschedule (self) -> None:

		"""Rebuild the arpeggio after the harmonic state advances."""

		self._build_pattern()


class BassPattern (subsequence.pattern.Pattern):

	"""A 16th-note bassline on the chord root (chorus only)."""

	def __init__ (
		self,
		harmonic_state: subsequence.harmonic_state.HarmonicState,
		form_state: subsequence.composition.FormState,
		channel: int,
		length: int = 4,
		reschedule_lookahead: int = 1,
		root_midi: int = 40
	) -> None:

		"""Initialize the bassline with harmonic state, form state, and root note."""

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.harmonic_state = harmonic_state
		self.form_state = form_state
		self.root_midi = root_midi

		self._build_pattern()

	def _build_pattern (self) -> None:

		"""Build a 16-step bassline anchored to the current chord root, chorus only."""

		self.steps = {}

		# Only plays during the chorus.
		section = self.form_state.get_section_info()
		if not section or section.name != "chorus":
			return

		step_duration = subsequence.constants.MIDI_SIXTEENTH_NOTE

		chord = self.harmonic_state.get_current_chord()
		chord_root = self.harmonic_state.get_chord_root_midi(self.root_midi, chord)

		# Fill all 16 steps with the chord root.
		bass_sequence = [1] * 16

		self.add_sequence(
			bass_sequence,
			step_duration = step_duration,
			pitch = chord_root,
			velocity = 90,
			note_duration = 5
		)

	def on_reschedule (self) -> None:

		"""Rebuild the bassline after the harmonic state advances."""

		self._build_pattern()


# ─── Main ────────────────────────────────────────────────────────────

async def main () -> None:

	"""Wire up the sequencer, harmony, form, patterns, and run until Ctrl+C."""

	logger.info("Subsequence Advanced Demo starting...")

	# ─── Sequencer ───────────────────────────────────────────────────

	seq = subsequence.sequencer.Sequencer(
		midi_device_name = MIDI_DEVICE,
		initial_bpm = 125
	)

	# ─── Harmony ─────────────────────────────────────────────────────
	#
	# Create a HarmonicState and schedule it to advance every 4 beats
	# (once per bar). Any pattern that holds this reference can read
	# the current chord via harmonic_state.get_current_chord().

	harmonic_state = subsequence.harmonic_state.HarmonicState(
		key_name = "E",
		graph_style = "dark_minor",
		include_dominant_7th = True,
		key_gravity_blend = 0.8,
		minor_turnaround_weight = 0.25
	)

	await subsequence.composition.schedule_harmonic_clock(
		sequencer = seq,
		harmonic_state = harmonic_state,
		cycle_beats = 4,
		reschedule_lookahead = 1
	)

	# ─── Form ────────────────────────────────────────────────────────
	#
	# Create a graph-based FormState and schedule it to advance each
	# bar. The intro plays once, then the form follows weighted
	# transitions — it never returns to the intro. Patterns hold a
	# reference and call get_section_info() to decide what to play.

	form_state = subsequence.composition.FormState({
		"intro":     (4, [("verse", 1)]),
		"verse":     (8, [("chorus", 3), ("bridge", 1)]),
		"chorus":    (8, [("breakdown", 2), ("verse", 1)]),
		"bridge":    (4, [("chorus", 1)]),
		"breakdown": (4, [("verse", 1)]),
	}, start="intro")

	await subsequence.composition.schedule_form(
		sequencer = seq,
		form_state = form_state,
		reschedule_lookahead = 1
	)

	# ─── External Data ───────────────────────────────────────────────
	#
	# Fetch ISS position every 8 bars (32 beats). The result is stored
	# in seq.data so patterns can read it. Sync functions run in a
	# thread pool so they never block the MIDI clock.

	def fetch_iss () -> None:

		"""Fetch ISS position and normalize lat/long to 0-1 range."""

		try:
			request = urllib.request.urlopen("https://api.wheretheiss.at/v1/satellites/25544", timeout=5)
			body = json.loads(request.read())
			seq.data["latitude_norm"] = (body["latitude"] + 52) / 104.0
			seq.data["longitude_norm"] = (body["longitude"] + 180) / 360.0
			logger.info(f"ISS lat={body['latitude']:.1f} lon={body['longitude']:.1f}")

		except Exception as exc:
			logger.warning(f"ISS fetch failed (keeping last value): {exc}")

	await subsequence.composition.schedule_task(sequencer=seq, fn=fetch_iss, cycle_beats=32)

	# ─── Patterns ────────────────────────────────────────────────────
	#
	# Create pattern instances, passing in the shared harmonic_state
	# and form_state. Each pattern reads these during _build_pattern().

	kick_snare = KickSnarePattern(form_state=form_state, data=seq.data)
	hats = HatPattern(form_state=form_state)
	chords = ChordPadPattern(
		harmonic_state = harmonic_state,
		form_state = form_state,
		channel = EP_MIDI_CHANNEL,
		root_midi = 52
	)
	motif = MotifPattern(
		harmonic_state = harmonic_state,
		form_state = form_state,
		channel = SYNTH_MIDI_CHANNEL,
		root_midi = 76
	)
	bass = BassPattern(
		harmonic_state = harmonic_state,
		form_state = form_state,
		channel = BASS_MIDI_CHANNEL,
		root_midi = 28
	)

	await subsequence.composition.schedule_patterns(
		sequencer = seq,
		patterns = [kick_snare, hats, chords, motif, bass],
		start_pulse = 0
	)

	# ─── Events ──────────────────────────────────────────────────────

	def on_bar (bar: int) -> None:

		"""Log bar number and current section for visibility."""

		section = form_state.get_section_info()
		section_name = section.name if section else "—"
		logger.info(f"Bar {bar + 1}  [{section_name}]")

	seq.on_event("bar", on_bar)

	# ─── Play ────────────────────────────────────────────────────────

	await subsequence.composition.run_until_stopped(seq)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
