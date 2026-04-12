"""Mixin class providing MIDI and OSC control-message methods for PatternBuilder.

This module is not intended to be used directly. ``PatternMidiMixin``
is inherited by ``PatternBuilder`` in ``pattern_builder.py``.
"""

import typing

import subsequence.constants
import subsequence.easing
import subsequence.pattern


class PatternMidiMixin:

	"""MIDI control, OSC, and note-correlated pitch bend methods for PatternBuilder.

	All methods here operate on ``self._pattern`` (a ``Pattern`` instance),
	which is set by ``PatternBuilder.__init__``.
	"""

	# ── Instance attributes provided by PatternBuilder at runtime ────────
	_pattern: subsequence.pattern.Pattern
	_default_grid: int
	_cc_name_map: typing.Optional[typing.Dict[str, int]]

	if typing.TYPE_CHECKING:
		def _resolve_cc (self, control: typing.Union[int, str]) -> int: ...

	# ── Shared ramp helper ──────────────────────────────────────────────────

	def _ramp_pulses (
		self,
		beat_start: float,
		beat_end: float,
		start: float,
		end: float,
		shape: typing.Union[str, subsequence.easing.EasingFn],
		resolution: int,
		event_fn: typing.Callable[[int, float], None],
	) -> None:

		"""Walk from beat_start to beat_end, calling event_fn(pulse, value) at each step.

		Shared inner loop for ``cc_ramp()``, ``pitch_bend_ramp()``, and ``osc_ramp()``.
		``event_fn`` receives the pulse position and the linearly-interpolated (then
		eased) value, and is responsible for creating and appending the event.
		"""

		pulse_start = int(beat_start * subsequence.constants.MIDI_QUARTER_NOTE)
		pulse_end = int(beat_end * subsequence.constants.MIDI_QUARTER_NOTE)
		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:
			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start + (end - start) * eased_t
			event_fn(pulse, interpolated)
			pulse += resolution

	# ── CC messages ─────────────────────────────────────────────────────────

	def cc (self, control: typing.Union[int, str], value: int, beat: float = 0.0) -> "PatternMidiMixin":

		"""
		Send a single CC message at a beat position.

		Parameters:
			control: MIDI CC number (0–127), or a string name resolved
				via the pattern's ``cc_name_map``.
			value: CC value (0–127).
			beat: Beat position within the pattern.
		"""

		cc_num: int = self._resolve_cc(control)
		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = cc_num,
				value = value
			)
		)
		return self

	def cc_ramp (
		self,
		control: typing.Union[int, str],
		start: int,
		end: int,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> "PatternMidiMixin":

		"""
		Interpolate a CC value over a beat range.

		Parameters:
			control: MIDI CC number (0–127), or a string name resolved
				via the pattern's ``cc_name_map``.
			start: Starting CC value (0–127).
			end: Ending CC value (0–127).
			beat_start: Beat position to begin the ramp.
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between CC messages (1 = every pulse, ~20ms at 120 BPM).
				Higher values (e.g. 2 or 4) reduce MIDI traffic density but may sound
				stepped at slow tempos.
			shape: Easing curve — a name string (e.g. ``"exponential"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.
		"""

		cc_num: int = self._resolve_cc(control)

		if beat_end is None:
			beat_end = self._pattern.length

		def _event (pulse: int, val: float) -> None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = cc_num,
					value = max(0, min(127, int(round(val))))
				)
			)

		self._ramp_pulses(beat_start, beat_end, float(start), float(end), shape, resolution, _event)
		return self

	# ── Pitch bend ──────────────────────────────────────────────────────────

	def pitch_bend (self, value: float, beat: float = 0.0) -> "PatternMidiMixin":

		"""
		Send a single pitch bend message at a beat position.

		Parameters:
			value: Pitch bend amount, normalised from -1.0 to 1.0.
			beat: Beat position within the pattern.
		"""

		midi_value = max(-8192, min(8191, int(round(value * 8192))))
		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'pitchwheel',
				value = midi_value
			)
		)
		return self

	def pitch_bend_ramp (
		self,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> "PatternMidiMixin":

		"""
		Interpolate pitch bend over a beat range.

		Parameters:
			start: Starting pitch bend (-1.0 to 1.0).
			end: Ending pitch bend (-1.0 to 1.0).
			beat_start: Beat position to begin the ramp.
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between pitch bend messages (1 = every pulse).
				Higher values (e.g. 2 or 4) reduce MIDI traffic density but may sound
				stepped at slow tempos.
			shape: Easing curve — a name string (e.g. ``"ease_out"``) or any
			       callable that maps [0, 1] → [0, 1].  Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.
		"""

		if beat_end is None:
			beat_end = self._pattern.length

		def _event (pulse: int, val: float) -> None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'pitchwheel',
					value = max(-8192, min(8191, int(round(val * 8192))))
				)
			)

		self._ramp_pulses(beat_start, beat_end, start, end, shape, resolution, _event)
		return self

	# ── Program change and SysEx ─────────────────────────────────────────────

	def program_change (
		self,
		program: int,
		beat: float = 0.0,
		bank_msb: typing.Optional[int] = None,
		bank_lsb: typing.Optional[int] = None,
	) -> "PatternMidiMixin":

		"""Send a Program Change message, optionally preceded by bank select.

		Switches the instrument patch on this pattern's MIDI channel.
		Program numbers follow the General MIDI numbering (0–127, where
		e.g. 0 = Acoustic Grand Piano, 40 = Violin, 33 = Electric Bass).

		To select a patch in a specific bank, provide ``bank_msb`` and/or
		``bank_lsb``.  The bank select CC messages (CC 0 for MSB, CC 32 for
		LSB) are sent at the same beat position immediately before the
		program change, in the order the synthesizer expects.

		Parameters:
			program: Program (patch) number (0–127).
			beat: Beat position within the pattern (default 0.0).
			bank_msb: Bank select coarse (CC 0), 0–127.  ``None`` = omit.
			bank_lsb: Bank select fine (CC 32), 0–127.  ``None`` = omit.

		Example:
			```python
			@composition.pattern(channel=1, length=4)
			def strings (p):
			    # GM — no bank needed
			    p.program_change(48)

			    # Roland JV-1080 bank 1, patch 48
			    p.program_change(48, bank_msb=81, bank_lsb=0)

			    # Change patch only at the first bar of each section
			    if p.section.bar == 0:
			        p.program_change(48, bank_msb=1)
			```
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		if bank_msb is not None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = 0,
					value = max(0, min(127, bank_msb)),
				)
			)

		if bank_lsb is not None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = 32,
					value = max(0, min(127, bank_lsb)),
				)
			)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'program_change',
				value = max(0, min(127, program)),
			)
		)
		return self

	def sysex (self, data: typing.Union[bytes, typing.List[int]], beat: float = 0.0) -> "PatternMidiMixin":

		"""
		Send a System Exclusive (SysEx) message at a beat position.

		SysEx messages allow deep integration with synthesizers and other
		hardware: patch dumps, parameter control, and vendor-specific commands.
		The ``data`` argument should contain only the inner payload bytes,
		without the surrounding ``0xF0`` / ``0xF7`` framing — mido adds those
		automatically.

		Parameters:
			data: SysEx payload as ``bytes`` or a list of integers (0–127).
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# GM System On — reset a GM-compatible device to defaults
			p.sysex([0x7E, 0x7F, 0x09, 0x01])
			```
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'sysex',
				data = bytes(data)
			)
		)
		return self

	# ── OSC messages ─────────────────────────────────────────────────────────

	def osc (self, address: str, *args: typing.Any, beat: float = 0.0) -> "PatternMidiMixin":

		"""
		Send an OSC message at a beat position.

		Requires ``composition.osc()`` to be called before ``composition.play()``.
		If no OSC server is configured the event is silently dropped.

		Parameters:
			address: OSC address path (e.g. ``"/mixer/fader/1"``).
			*args: OSC arguments — float, int, str, or bytes.
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# Enable a chorus effect at beat 2
			p.osc("/fx/chorus/enable", 1, beat=2.0)

			# Set a mixer pan value immediately
			p.osc("/mixer/pan/1", -0.5)
			```
		"""

		pulse = int(beat * subsequence.constants.MIDI_QUARTER_NOTE)

		self._pattern.osc_events.append(
			subsequence.pattern.OscEvent(
				pulse = pulse,
				address = address,
				args = args
			)
		)
		return self

	def osc_ramp (
		self,
		address: str,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 4,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear"
	) -> "PatternMidiMixin":

		"""
		Interpolate an OSC float value over a beat range.

		Generates one OSC message per ``resolution`` pulses, sending the
		interpolated value to ``address`` at each step. Useful for smoothly
		automating mixer faders, effect parameters, and other continuous controls
		on a remote machine.

		Requires ``composition.osc()`` to be called before ``composition.play()``.
		If no OSC server is configured the events are silently dropped.

		Parameters:
			address: OSC address path (e.g. ``"/mixer/fader/1"``).
			start: Starting float value.
			end: Ending float value.
			beat_start: Beat position to begin the ramp (default 0.0).
			beat_end: Beat position to end the ramp. Defaults to pattern length.
			resolution: Pulses between OSC messages (default 4 — approximately
				6 messages per beat at 120 BPM, which is smooth for fader
				automation while keeping UDP traffic light). Use ``resolution=1``
				for pulse-level precision.
			shape: Easing curve — a name string (e.g. ``"ease_in"``) or any
			       callable that maps [0, 1] → [0, 1]. Defaults to ``"linear"``.
			       See :mod:`subsequence.easing` for available shapes.

		Example:
			```python
			# Fade a mixer fader up over 4 beats
			p.osc_ramp("/mixer/fader/1", start=0.0, end=1.0)

			# Ease in a reverb send over the last 2 beats
			p.osc_ramp("/fx/reverb/wet", 0.0, 0.8, beat_start=2, beat_end=4, shape="ease_in")
			```
		"""

		if beat_end is None:
			beat_end = self._pattern.length

		def _event (pulse: int, val: float) -> None:
			self._pattern.osc_events.append(
				subsequence.pattern.OscEvent(
					pulse = pulse,
					address = address,
					args = (val,)
				)
			)

		self._ramp_pulses(beat_start, beat_end, start, end, shape, resolution, _event)
		return self

	# ── Note-correlated pitch bend ────────────────────────────────────────────

	def _generate_bend_events (
		self,
		start_value: float,
		end_value: float,
		pulse_start: int,
		pulse_end: int,
		resolution: int,
		shape: typing.Union[str, subsequence.easing.EasingFn],
	) -> None:

		"""Generate a series of pitchwheel CcEvents between two pulse positions.

		This is the shared inner loop used by ``bend()``, ``portamento()``, and
		``slide()``.  Appends events directly to ``self._pattern.cc_events``.

		Parameters:
			start_value: Normalised bend at the start of the ramp (-1.0 to 1.0).
			end_value: Normalised bend at the end of the ramp (-1.0 to 1.0).
			pulse_start: Absolute pulse position to start the ramp.
			pulse_end: Absolute pulse position to end the ramp.
			resolution: Number of pulses between consecutive events.
			shape: Easing curve name or callable.
		"""

		span = pulse_end - pulse_start

		if span <= 0:
			return

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:
			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start_value + (end_value - start_value) * eased_t
			midi_value = max(-8192, min(8191, int(round(interpolated * 8192))))
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'pitchwheel',
					value = midi_value,
				)
			)
			pulse += resolution

	def bend (
		self,
		note: int,
		amount: float,
		start: float = 0.0,
		end: float = 1.0,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
	) -> "PatternMidiMixin":

		"""Bend a specific note by index.

		Generates a pitch bend ramp that covers a fraction of the target note's
		duration, then resets to 0.0 at the next note's onset.  Call this
		*after* ``legato()`` / ``staccato()`` so that note durations are final.

		Parameters:
			note: Note index (0 = first, -1 = last, etc.).
			amount: Target bend normalised to -1.0..1.0 (positive = up).
				With a standard ±2-semitone pitch wheel range, 0.5 = 1 semitone.
			start: Fraction of the note's duration at which the ramp begins
				(0.0 = note onset, default).
			end: Fraction of the note's duration at which the ramp ends
				(1.0 = note end, default).
			shape: Easing curve — a name string (e.g. ``"ease_in"``) or any
			       callable mapping [0, 1] → [0, 1].  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.

		Raises:
			IndexError: If *note* is out of range for the current pattern.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=midi_notes.E1)
			p.legato(0.95)

			# Bend the last note up one semitone (with ±2 st range), easing in
			p.bend(note=-1, amount=0.5, shape="ease_in")

			# Bend the second note down, starting halfway through
			p.bend(note=1, amount=-0.3, start=0.5)
			```
		"""

		if not self._pattern.steps:
			return self

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)

		# Resolve note index (supports negative indexing)
		position = sorted_positions[note]
		note_idx = note if note >= 0 else len(sorted_positions) + note

		# Duration: use the longest note at this step
		step = self._pattern.steps[position]
		note_duration = max(n.duration for n in step.notes)

		# Clamp start/end fractions and compute pulse range for the ramp
		start_clamped = max(0.0, min(1.0, start))
		end_clamped = max(0.0, min(1.0, end))
		bend_start_pulse = position + int(note_duration * start_clamped)
		bend_end_pulse = position + int(note_duration * end_clamped)

		self._generate_bend_events(0.0, amount, bend_start_pulse, bend_end_pulse, resolution, shape)

		# Reset bend at the next note's onset (or pulse 0 for the last note)
		if note_idx < len(sorted_positions) - 1:
			reset_pulse = sorted_positions[note_idx + 1]
		else:
			reset_pulse = 0

		reset_midi = max(-8192, min(8191, int(round(0.0 * 8192))))
		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = reset_pulse,
				message_type = 'pitchwheel',
				value = reset_midi,
			)
		)
		return self

	def portamento (
		self,
		time: float = 0.15,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
	) -> "PatternMidiMixin":

		"""Glide between all consecutive notes using pitch bend.

		Generates a pitch bend ramp in the tail of each note, bending toward
		the next note's pitch, then resets at the next note's onset.  Call this
		*after* ``legato()`` / ``staccato()`` so that note durations are final.

		Most effective on mono instruments where pitch bend is per-channel.

		Parameters:
			time: Fraction of each note's duration used for the glide
				(default 0.15 — last 15% of the note).
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0 — standard ±2 st).  Pairs with intervals larger
				than this value are skipped.  Pass ``None`` to disable range
				checking and always generate the bend (large intervals are
				clamped to ±1.0).
			wrap: If ``True`` (default), glide from the last note toward the
				first note of the next cycle.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
			p.legato(0.95)

			# Gentle glide across all note transitions
			p.portamento(time=0.15, shape="ease_in_out")

			# Wide bend range (synth set to ±12 semitones)
			p.portamento(time=0.2, bend_range=12)

			# No range limit — bend as far as MIDI allows
			p.portamento(time=0.1, bend_range=None)
			```
		"""

		if not self._pattern.steps:
			return self

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		n = len(sorted_positions)

		def _lowest_pitch (pos: int) -> int:
			return min(note.pitch for note in self._pattern.steps[pos].notes)

		def _longest_duration (pos: int) -> int:
			return max(note.duration for note in self._pattern.steps[pos].notes)

		for i in range(n):
			a_pos = sorted_positions[i]
			is_last = (i == n - 1)

			if is_last:
				if not wrap:
					continue
				b_pos = sorted_positions[0]
			else:
				b_pos = sorted_positions[i + 1]

			interval = _lowest_pitch(b_pos) - _lowest_pitch(a_pos)

			if bend_range is not None and abs(interval) > bend_range:
				continue

			normaliser = bend_range if bend_range is not None else 2.0
			amount = max(-1.0, min(1.0, interval / normaliser))

			a_duration = _longest_duration(a_pos)
			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)

			# Reset at the destination note's onset
			reset_pulse = b_pos if not is_last else 0
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)
		return self

	def slide (
		self,
		notes: typing.Optional[typing.List[int]] = None,
		steps: typing.Optional[typing.List[int]] = None,
		time: float = 0.15,
		shape: typing.Union[str, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
		extend: bool = True,
	) -> "PatternMidiMixin":

		"""TB-303-style selective slide into specific notes.

		Like ``portamento()`` but only applies to flagged destination notes.
		Specify target notes by index (``notes=[1, 3]``) or by step grid
		position (``steps=[4, 12]``).  If ``extend=True`` (default) the
		preceding note's duration is extended to meet the slide target, matching
		the 303's behaviour where slide notes do not retrigger.

		Call this *after* ``legato()`` / ``staccato()`` so that note durations
		are final.

		Parameters:
			notes: List of note indices to slide *into* (0 = first).
				Supports negative indexing.  Mutually exclusive with *steps*.
			steps: List of step grid indices to slide *into*.
				Converted to pulse positions using ``self._default_grid``.
				Mutually exclusive with *notes*.
			time: Fraction of the preceding note's duration used for the glide.
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0).  Pairs with larger intervals are skipped.
				Pass ``None`` to disable range checking.
			wrap: If ``True`` (default), include a wrap-around slide from the
				last note back toward the first.
			extend: If ``True`` (default), extend the preceding note's duration
				to reach the slide target's onset — 303-style legato through
				the glide.

		Raises:
			ValueError: If neither *notes* nor *steps* is provided.

		Example:
			```python
			p.sequence(steps=[0, 4, 8, 12], pitches=[40, 42, 40, 43])
			p.legato(0.95)

			# Slide into the 2nd and 4th notes
			p.slide(notes=[1, 3], time=0.2, shape="ease_in")

			# Same using step grid indices
			p.slide(steps=[4, 12], time=0.2, shape="ease_in")

			# Slide without extending the preceding note
			p.slide(notes=[1, 3], extend=False)
			```
		"""

		if notes is None and steps is None:
			raise ValueError("slide() requires either 'notes' or 'steps'")

		if not self._pattern.steps:
			return self

		sorted_positions = sorted(self._pattern.steps.keys())
		total_pulses = int(self._pattern.length * subsequence.constants.MIDI_QUARTER_NOTE)
		n = len(sorted_positions)

		# Resolve flagged pulse positions
		if notes is not None:
			flagged: typing.Set[int] = set()
			for idx in notes:
				flagged.add(sorted_positions[idx])
		else:
			# steps is not None
			step_pulses = total_pulses // self._default_grid
			flagged = set()
			for s in (steps or []):
				flagged.add(s * step_pulses)

		def _lowest_pitch (pos: int) -> int:
			return min(note.pitch for note in self._pattern.steps[pos].notes)

		def _longest_duration (pos: int) -> int:
			return max(note.duration for note in self._pattern.steps[pos].notes)

		for i in range(n):
			a_pos = sorted_positions[i]
			is_last = (i == n - 1)

			if is_last:
				if not wrap:
					continue
				b_pos = sorted_positions[0]
			else:
				b_pos = sorted_positions[i + 1]

			# Only generate glide if the destination is flagged
			if b_pos not in flagged:
				continue

			interval = _lowest_pitch(b_pos) - _lowest_pitch(a_pos)

			if bend_range is not None and abs(interval) > bend_range:
				continue

			normaliser = bend_range if bend_range is not None else 2.0
			amount = max(-1.0, min(1.0, interval / normaliser))

			a_duration = _longest_duration(a_pos)

			# Optionally extend preceding note to meet the target onset (303 style)
			if extend:
				if is_last:
					gap = (total_pulses - a_pos) + sorted_positions[0]
				else:
					gap = b_pos - a_pos
				for note in self._pattern.steps[a_pos].notes:
					note.duration = gap

			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)

			# Reset at the destination note's onset
			reset_pulse = b_pos if not is_last else 0
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)
		return self
