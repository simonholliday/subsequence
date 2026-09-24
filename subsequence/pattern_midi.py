"""Mixin class providing MIDI and OSC control-message methods for PatternBuilder.

This module is not intended to be used directly. ``PatternMidiMixin``
is inherited by ``PatternBuilder`` in ``pattern_builder.py``.
"""

import functools
import logging
import typing
import weakref

import pymididefs.cc
import pymididefs.rpn

import subsequence.constants
import subsequence.constants.pulses
import subsequence.declarations
import subsequence.easing
import subsequence.groove
import subsequence.pattern


logger = logging.getLogger(__name__)

# Parts already told that a bend or slide named a note they did not have,
# by verb, so a rebuilding part says it once rather than every cycle.
_warned_missing_targets: "weakref.WeakKeyDictionary[subsequence.pattern.Pattern, typing.Set[str]]" = weakref.WeakKeyDictionary()


def _notes (count: int) -> str:

	"""'1 note', '4 notes'."""

	return f"{count} note" if count == 1 else f"{count} notes"


def _mark_glide (bends: typing.List["subsequence.pattern.CcEvent"], source: int, target: int, amount: float) -> None:

	"""Tag a glide's bends with the notes it joins and the amount it was laid at, for a tuning to re-aim (#3476)."""

	for bend in bends:
		bend.glide = (source, target, amount)


class PatternMidiMixin:

	"""MIDI control, OSC, and note-correlated pitch bend methods for PatternBuilder.

	All methods here operate on ``self._pattern`` (a ``Pattern`` instance),
	which is set by ``PatternBuilder.__init__``.
	"""

	# ── Instance attributes provided by PatternBuilder at runtime ────────
	_pattern: subsequence.pattern.Pattern
	_default_grid: int
	_cc_name_map: typing.Optional[typing.Dict[str, int]]
	_nrpn_name_map: typing.Optional[typing.Dict[str, int]]
	_pending_glides: typing.List[typing.Callable[[], None]]
	_grooves_applied: typing.List[typing.Tuple[subsequence.groove.Groove, float, int]]
	_grooved_notes: typing.Dict[int, typing.Tuple[subsequence.pattern.Note, int]]
	_groove_chain_broken: bool

	if typing.TYPE_CHECKING:
		import subsequence.pattern_builder  # noqa: F401 — type-checking only
		def _resolve_cc (self, control: typing.Union[int, str]) -> int: ...
		def _resolve_nrpn (self, parameter: typing.Union[int, str]) -> int: ...
		def _resolve_rpn (self, parameter: typing.Union[int, str]) -> int: ...
		def _defer (self, pending: typing.List[typing.Any], lay: typing.Callable[[], object]) -> None: ...
		def _will_need_finishing (self) -> None: ...
		def _wrapped_beat (self, beat: float) -> float: ...
		def _wrapped_pulse (self, beat: float) -> int: ...

	def _next_first_onset (self, first: int) -> int:

		"""Where the next cycle's first note will play, counted from this cycle's start (#2927).

		A glide that wraps leads into that note, so its reset lands there, and
		so does the end of the note ``slide(extend=True)`` lengthens into it.
		It plays where this cycle's first note did, one cycle on, unless a
		groove moves it: a pattern that is not a whole number of the groove's
		cycles long starts each time round from a different place in the
		groove, so three swung sixteenths have their first note straight one
		time and late the next.  The grooves this build applied are then
		applied again from the next cycle's start, to the pulse the note was
		placed on.  That holds only while the grooves are all that has moved
		the notes since: once a note has been placed after a groove, or moved
		since by ``rotate()``, ``reverse()``, ``randomize()`` or the like,
		where the first note plays next time is more than the grooves can
		say, so the old rule stands.  Foreseeing it anyway made some of those
		worse.  A note taken away is no matter.
		"""

		total_pulses = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
		as_before = total_pulses + first

		if not self._grooves_applied or self._groove_chain_broken or not self._as_the_groove_left_them():
			return as_before

		# The note the glides measure the first step by: its lowest.
		note = min(self._pattern.steps[first].notes, key=lambda sounding: sounding.pitch)
		next_time = self._pattern._placed_pulse(first, note)

		for template, strength, origin in self._grooves_applied:
			next_time, _ = subsequence.groove._grooved_pulse(
				next_time, template, subsequence.constants.MIDI_QUARTER_NOTE, strength, origin + total_pulses,
			)

		return total_pulses + next_time

	def _as_the_groove_left_them (self) -> bool:

		"""Whether every note is one the last groove left, on the pulse it left it on (#2927).

		By identity, not only by pulse: a rotation can lay evenly spaced notes
		exactly where others were, and the note that comes first was then
		placed somewhere else.  A note taken away since does not count.
		"""

		for pulse, step in self._pattern.steps.items():
			for sounding in step.notes:
				left = self._grooved_notes.get(id(sounding))

				if left is None or left[0] is not sounding or left[1] != pulse:
					return False

		return True

	# ── Shared ramp helper ──────────────────────────────────────────────────

	def _ramp_pulse_span (
		self,
		pulse_start: int,
		pulse_end: int,
		start: float,
		end: float,
		shape: typing.Union[str, subsequence.easing.EasingFn],
		resolution: int,
		event_fn: typing.Callable[[int, float], None],
	) -> None:

		"""Walk from pulse_start to pulse_end, calling event_fn(pulse, value) at each step.

		The pulse-domain kernel shared by every ramp on this mixin - the
		beat-based ramps via :meth:`_ramp_pulses` and the note-correlated pitch
		bends via :meth:`_generate_bend_events`.  ``event_fn`` receives the pulse
		position and the linearly-interpolated (then eased) value, and is
		responsible for creating and appending the event.
		"""

		span = pulse_end - pulse_start

		if span <= 0:
			return

		if resolution < 1:
			raise ValueError("resolution must be at least 1 pulse")

		easing_fn = subsequence.easing.get_easing(shape)
		pulse = pulse_start

		while pulse <= pulse_end:
			t = (pulse - pulse_start) / span
			eased_t = easing_fn(t)
			interpolated = start + (end - start) * eased_t
			event_fn(pulse, interpolated)
			pulse += resolution

		# The loop lands on pulse_end only when resolution divides the span —
		# otherwise emit the target explicitly, so a ramp always reaches the
		# value it was asked to reach.
		if span % resolution != 0:
			event_fn(pulse_end, start + (end - start) * easing_fn(1.0))

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

		The beat-based entry to :meth:`_ramp_pulse_span`, shared by
		``cc_ramp()``, ``pitch_bend_ramp()``, ``nrpn_ramp()``/``rpn_ramp()``,
		and ``osc_ramp()``.

		A ramp starting before beat 0 wraps from the end, as a note does, and
		keeps its length - so it crosses the cycle's end and lands each event
		inside the pattern rather than before it (#3005).  Wrapping the start
		alone would leave the span negative, and a negative span emits nothing
		at all.
		"""

		if beat_start < 0:

			span = beat_end - beat_start
			beat_start = self._wrapped_beat(beat_start)
			beat_end = beat_start + span

			cycle = subsequence.constants.pulses.beats_to_pulses(self._pattern.length)
			place = event_fn

			def fold (pulse: int, value: float) -> None:
				"""Fold a pulse past the cycle's end back to where it sounds."""
				place(pulse % cycle, value)

			event_fn = fold

		pulse_start = subsequence.constants.pulses.beats_to_pulses(beat_start)
		pulse_end = subsequence.constants.pulses.beats_to_pulses(beat_end)

		self._ramp_pulse_span(pulse_start, pulse_end, start, end, shape, resolution, event_fn)

	# ── CC messages ─────────────────────────────────────────────────────────

	def cc (self, control: typing.Union[int, str], value: int, beat: subsequence.declarations.GridBeats = 0.0) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send a single CC message at a beat position.

		Parameters:
			control: MIDI CC number (0–127), or a string name resolved
				via the pattern's ``cc_name_map``.  A number outside 0–127
				raises, naming it: MIDI cannot carry it, so it would have
				been dropped at every send (#3004).
			value: CC value (0–127); out-of-range values are clamped, as on
				every sibling verb - a computed value running past an end is
				a controller reaching its limit, not a mistake.
			beat: Beat position within the pattern.
		"""

		cc_num: int = self._resolve_cc(control)
		pulse = self._wrapped_pulse(beat)

		# Clamp to the 7-bit CC range like every sibling (cc_ramp / program_change
		# / pitch_bend) so a computed out-of-range value is corrected here rather
		# than silently dropped and logged when mido rejects it at dispatch time.
		clamped_value = max(0, min(127, int(round(value))))

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = cc_num,
				value = clamped_value
			)
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def cc_ramp (
		self,
		control: typing.Union[int, str],
		start: int,
		end: int,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear"
	) -> "subsequence.pattern_builder.PatternBuilder":

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
			shape: Easing curve - a name string (e.g. ``"exponential"``) or any
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
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	# ── Pitch bend ──────────────────────────────────────────────────────────

	def pitch_bend (self, value: float, beat: subsequence.declarations.GridBeats = 0.0) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send a single pitch bend message at a beat position.

		Parameters:
			value: Pitch bend amount, normalised from -1.0 to 1.0.
			beat: Beat position within the pattern.
		"""

		# The asymmetric clamp is correct: MIDI's 14-bit bend range is -8192..+8191.
		midi_value = max(-8192, min(8191, int(round(value * 8192))))
		pulse = self._wrapped_pulse(beat)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'pitchwheel',
				value = midi_value
			)
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def pitch_bend_ramp (
		self,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 1,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear"
	) -> "subsequence.pattern_builder.PatternBuilder":

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
			shape: Easing curve - a name string (e.g. ``"ease_out"``) or any
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
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	# ── RPN / NRPN parameter control ────────────────────────────────────────
	# RPN (Registered) and NRPN (Non-Registered) Parameter Numbers are the
	# standard MIDI conventions for addressing parameters beyond the 128 CC
	# slots, with optional 14-bit value precision.  Both are sequences of
	# regular control_change messages co-scheduled at the same pulse:
	#   CC 99 / 98     NRPN parameter MSB / LSB        (or 101 / 100 for RPN)
	#   CC 6  / 38     Data Entry MSB / LSB
	#   CC 101=127, 100=127   NULL — defensive deselect
	# The Sequencer's MidiEvent.sequence tie-breaker preserves emission order
	# at the same pulse, so the synth assigns the value to the right parameter.

	def _append_param_select (self, pulse: int, parameter: int, msb_cc: int, lsb_cc: int) -> None:

		"""Emit the two-CC parameter-select pair (NRPN: 99/98, RPN: 101/100).

		Events are emitted on the pattern's channel - leaving ``CcEvent.channel``
		unset (None) lets the sequencer fall through to ``pattern.channel``
		at dispatch time, which is the normal behaviour for every other CC
		method on this mixin.
		"""

		param_msb, param_lsb = pymididefs.cc.pack_14bit(parameter)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = msb_cc,
				value = param_msb,
			)
		)
		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = lsb_cc,
				value = param_lsb,
			)
		)

	def _append_data_entry (
		self,
		pulse: int,
		value: int,
		fine: bool,
		parameter: typing.Optional[typing.Tuple[str, int]] = None,
	) -> None:

		"""Emit Data Entry MSB (and LSB if fine=True) for a parameter value.

		*parameter* is the ``("nrpn"|"rpn", number)`` this value is written for,
		carried on the event so the build's closing pass can re-select it if
		something else has taken the channel's selection since (#3070).
		"""

		if fine:
			value_msb, value_lsb = pymididefs.cc.pack_14bit(value)
		else:
			if not 0 <= value <= 127:
				raise ValueError(f"NRPN/RPN value must be 0–127 when fine=False, got {value}")
			value_msb = value
			value_lsb = None

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = pymididefs.cc.DATA_ENTRY_MSB,
				value = value_msb,
				parameter = parameter,
			)
		)

		if value_lsb is not None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = pymididefs.cc.DATA_ENTRY_LSB,
					value = value_lsb,
					parameter = parameter,
				)
			)

	def _validate_ramp_endpoints (self, start: int, end: int, fine: bool) -> None:

		"""Reject out-of-range NRPN/RPN ramp endpoints up front.

		Mirrors the strict behaviour of ``_append_data_entry`` for one-shots
		so a typo (e.g. forgetting ``fine=True`` with a 14-bit value) raises
		immediately rather than silently clamping at every ramp step.
		"""

		limit = 16383 if fine else 127

		for label, value in (("start", start), ("end", end)):
			if not 0 <= value <= limit:
				raise ValueError(f"NRPN/RPN ramp {label} must be 0–{limit} (fine={fine}), got {value}")

	def _append_null_reset (self, pulse: int) -> None:

		"""Emit the RPN NULL sentinel (CC 101=127, CC 100=127) to deselect.

		Defensive practice: prevents a stray later CC 6 / 38 from being
		applied to whichever parameter was last selected on this channel.
		"""

		null_msb, null_lsb = pymididefs.cc.pack_14bit(pymididefs.rpn.NULL_PARAMETER)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = pymididefs.cc.RPN_MSB,
				value = null_msb,
			)
		)
		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'control_change',
				control = pymididefs.cc.RPN_LSB,
				value = null_lsb,
			)
		)

	def nrpn (
		self,
		parameter: typing.Union[int, str],
		value: int,
		beat: subsequence.declarations.GridBeats = 0.0,
		fine: bool = False,
		null_reset: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send a single NRPN parameter write at a beat position.

		NRPN (Non-Registered Parameter Number) addresses synth-specific
		parameters that don't fit into the 128 standard CC slots - Sequential,
		Korg, Roland, Elektron and others use it heavily for filter cutoff,
		envelope amounts, oscillator detune, and similar deep parameters.
		Many such parameters need values beyond 0–127 (e.g. 0–1023, 0–254);
		set ``fine=True`` for full 14-bit precision.

		Emitted on the pattern's MIDI channel.  To target a different MIDI channel
		(e.g. a per-channel RPN config), define a separate pattern on that
		MIDI channel or use ``composition.trigger(channel=…)`` for a one-shot.

		Parameters:
			parameter: 14-bit NRPN parameter number (0–16383), or a string
				resolved via the pattern's ``nrpn_name_map``.
			value: Parameter value.  0–127 if ``fine=False``; 0–16383 if
				``fine=True``.
			beat: Beat position within the pattern.
			fine: If True, send 14-bit value via Data Entry MSB+LSB
				(CC 6 + CC 38).  If False (default), send only Data Entry
				MSB - sufficient for the common 0–127 range.
			null_reset: If True (default), follow with the RPN null sentinel
				to deselect the active parameter and prevent stray later
				CC 6 / 38 messages from hitting it.

		Example:
			```python
			# Sequential Take 5 fine-tune (14-bit, range 0–1400)
			p.nrpn(9, 700, fine=True)

			# Roland JV-1080 reverb level (7-bit)
			p.nrpn(0x0140, 80)
			```
		"""

		param = self._resolve_nrpn(parameter)
		pulse = self._wrapped_pulse(beat)

		self._append_param_select(pulse, param, pymididefs.cc.NRPN_MSB, pymididefs.cc.NRPN_LSB)
		self._append_data_entry(pulse, value, fine, ("nrpn", param))

		if null_reset:
			self._append_null_reset(pulse)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def rpn (
		self,
		parameter: typing.Union[int, subsequence.declarations.RpnParameter],
		value: int,
		beat: subsequence.declarations.GridBeats = 0.0,
		fine: bool = False,
		null_reset: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send a single RPN parameter write at a beat position.

		RPN (Registered Parameter Number) addresses the small standardised
		set of parameters defined by the MIDI specification - pitch bend
		range, master tuning, modulation depth - supported by virtually any
		MIDI synth.  String names resolve via ``pymididefs.rpn.RPN_MAP``
		out of the box, no map needed.

		Standard RPN names: ``pitch_bend_sensitivity``,
		``channel_fine_tuning``, ``channel_coarse_tuning``,
		``tuning_program_select``, ``tuning_bank_select``,
		``modulation_depth_range``.

		Emitted on the pattern's MIDI channel.

		Parameters:
			parameter: 14-bit RPN parameter number (0–16383), or one of the
				standard string names above.
			value: Parameter value.  0–127 if ``fine=False``; 0–16383 if
				``fine=True``.  Pitch bend sensitivity uses MSB = semitones
				and LSB = cents, so set ``fine=True`` for sub-semitone control.
			beat: Beat position within the pattern.
			fine: If True, send 14-bit value via Data Entry MSB+LSB.
			null_reset: If True (default), follow with the RPN null sentinel.

		Example:
			```python
			# Set pitch bend range to ±12 semitones
			p.rpn("pitch_bend_sensitivity", 12)

			# 4 semitones plus 50 cents
			p.rpn("pitch_bend_sensitivity", 4 * 128 + 50, fine=True)
			```
		"""

		param = self._resolve_rpn(parameter)
		pulse = self._wrapped_pulse(beat)

		self._append_param_select(pulse, param, pymididefs.cc.RPN_MSB, pymididefs.cc.RPN_LSB)
		self._append_data_entry(pulse, value, fine, ("rpn", param))

		if null_reset:
			self._append_null_reset(pulse)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def nrpn_ramp (
		self,
		parameter: typing.Union[int, str],
		start: int,
		end: int,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 4,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear",
		fine: bool = True,
		null_reset: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Interpolate an NRPN value over a beat range.

		The parameter is selected once at ``beat_start``; subsequent steps
		emit only Data Entry messages.  Synths track the most recently
		selected NRPN per the spec, so re-selecting per step would just
		waste bandwidth.  If ``null_reset=True`` the RPN null sentinel is
		appended once at ``beat_end``.

		**Another ramp or one-shot in the window is safe** (#3070).  A second
		``nrpn_ramp``, an ``rpn_ramp``, or a one-shot ``nrpn()``/``rpn()``
		takes the MIDI channel's selection, which used to redirect every later step
		of this ramp - a one-shot's default ``null_reset`` sent them to the NULL
		parameter, where they did nothing at all.  The end of the build now
		re-selects wherever the selection has drifted, and only there, so a ramp
		on its own still emits exactly the messages described above.

		**What it cannot see:** a plain ``p.cc(6, …)`` or ``p.cc(38, …)`` on
		this MIDI channel, which is you addressing whatever was last selected and is
		left alone deliberately; and another *pattern* writing NRPN to the same
		MIDI channel, which is outside this builder entirely.

		Bandwidth note: with ``fine=True`` (default) every step emits two
		CCs.  Default ``resolution=4`` is one update every four pulses
		(~83 ms at 120 BPM, where one pulse is ~21 ms), which keeps the bus
		lightly loaded.  Increase
		``resolution`` (e.g. ``8``) on slow DIN-MIDI links if you hear
		other messages getting delayed.

		Emitted on the pattern's MIDI channel.

		Parameters:
			parameter: 14-bit NRPN parameter number, or a string resolved
				via the pattern's ``nrpn_name_map``.
			start: Starting value (0–16383 when ``fine=True``, 0–127 when False).
			end: Ending value.
			beat_start: Beat position to begin the ramp.
			beat_end: Beat position to end the ramp.  Defaults to pattern length.
			resolution: Pulses between Data Entry messages (default 4).
			shape: Easing curve - string name or callable [0, 1] → [0, 1].
			fine: If True (default), use full 14-bit Data Entry MSB+LSB.
			null_reset: If True (default), append the null sentinel at the
				end of the ramp (not per step).
		"""

		param = self._resolve_nrpn(parameter)
		self._validate_ramp_endpoints(start, end, fine)

		if beat_end is None:
			beat_end = self._pattern.length

		pulse_end = subsequence.constants.pulses.beats_to_pulses(beat_end)

		kind = "nrpn"

		# Make sure the build's closing pass runs: it is what keeps this ramp
		# pointed at its own parameter if anything else selects one in the
		# window (#3070).  A hand-built pattern has no engine to finish it.
		self._will_need_finishing()

		self._append_param_select(self._wrapped_pulse(beat_start), param, pymididefs.cc.NRPN_MSB, pymididefs.cc.NRPN_LSB)

		def _event (pulse: int, val: float) -> None:
			# Clamp guards against custom easing callables that overshoot [0, 1].
			if fine:
				value = max(0, min(16383, int(round(val))))
			else:
				value = max(0, min(127, int(round(val))))
			self._append_data_entry(pulse, value, fine, (kind, param))

		self._ramp_pulses(beat_start, beat_end, float(start), float(end), shape, resolution, _event)

		if null_reset:
			self._append_null_reset(pulse_end)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def rpn_ramp (
		self,
		parameter: typing.Union[int, subsequence.declarations.RpnParameter],
		start: int,
		end: int,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 4,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear",
		fine: bool = True,
		null_reset: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Interpolate an RPN value over a beat range.

		Identical to :meth:`nrpn_ramp` but uses CC 101 / 100 for parameter
		selection.  String names resolve via ``pymididefs.rpn.RPN_MAP``.
		Another ramp or one-shot in the window is safe for the same reason
		(#3070); a plain ``p.cc(6, …)`` on this MIDI channel is still yours to keep
		track of.
		"""

		param = self._resolve_rpn(parameter)
		self._validate_ramp_endpoints(start, end, fine)

		if beat_end is None:
			beat_end = self._pattern.length

		pulse_end = subsequence.constants.pulses.beats_to_pulses(beat_end)

		kind = "rpn"

		# Make sure the build's closing pass runs: it is what keeps this ramp
		# pointed at its own parameter if anything else selects one in the
		# window (#3070).  A hand-built pattern has no engine to finish it.
		self._will_need_finishing()

		self._append_param_select(self._wrapped_pulse(beat_start), param, pymididefs.cc.RPN_MSB, pymididefs.cc.RPN_LSB)

		def _event (pulse: int, val: float) -> None:
			# Clamp guards against custom easing callables that overshoot [0, 1].
			if fine:
				value = max(0, min(16383, int(round(val))))
			else:
				value = max(0, min(127, int(round(val))))
			self._append_data_entry(pulse, value, fine, (kind, param))

		self._ramp_pulses(beat_start, beat_end, float(start), float(end), shape, resolution, _event)

		if null_reset:
			self._append_null_reset(pulse_end)

		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	# ── Program change and SysEx ─────────────────────────────────────────────

	def program_change (
		self,
		program: int,
		beat: subsequence.declarations.GridBeats = 0.0,
		bank_msb: typing.Optional[int] = None,
		bank_lsb: typing.Optional[int] = None,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Send a Program Change message, optionally preceded by bank select.

		Switches the instrument patch on this pattern's MIDI channel.
		Program numbers follow the General MIDI numbering (0–127, where
		e.g. 0 = Acoustic Grand Piano, 40 = Violin, 33 = Electric Bass).

		To select a patch in a specific bank, provide ``bank_msb`` and/or
		``bank_lsb``.  The bank select CC messages (CC 0 for MSB, CC 32 for
		LSB) are sent at the same beat position immediately before the
		program change, in the order the synthesiser expects.  All of them
		reach the synthesiser before any note starting on the same beat, so
		that note already plays with the new patch.

		Parameters:
			program: Program (patch) number (0–127).
			beat: Beat position within the pattern (default 0.0).
			bank_msb: Bank select coarse (CC 0), 0–127.  ``None`` = omit.
			bank_lsb: Bank select fine (CC 32), 0–127.  ``None`` = omit.

		Example:
			```python
			@composition.pattern(channel=1, beats=4)
			def strings (p):
			    # GM - no bank needed
			    p.program_change(48)

			    # Roland JV-1080 bank 1, patch 48
			    p.program_change(48, bank_msb=81, bank_lsb=0)

			    # Change patch only at the first bar of each section
			    if p.section.bar == 0:
			        p.program_change(48, bank_msb=1)
			```
		"""

		pulse = self._wrapped_pulse(beat)

		if bank_msb is not None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = 0,
					value = max(0, min(127, int(round(bank_msb)))),
				)
			)

		if bank_lsb is not None:
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'control_change',
					control = 32,
					value = max(0, min(127, int(round(bank_lsb)))),
				)
			)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'program_change',
				value = max(0, min(127, int(round(program)))),
			)
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def sysex (self, data: typing.Union[bytes, typing.List[int]], beat: subsequence.declarations.GridBeats = 0.0) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send a System Exclusive (SysEx) message at a beat position.

		SysEx messages allow deep integration with synthesisers and other
		hardware: patch dumps, parameter control, and vendor-specific commands.
		The ``data`` argument should contain only the inner payload bytes,
		without the surrounding ``0xF0`` / ``0xF7`` framing - mido adds those
		automatically.

		Parameters:
			data: SysEx payload as ``bytes`` or a list of integers (0–127).
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# GM System On - reset a GM-compatible device to defaults
			p.sysex([0x7E, 0x7F, 0x09, 0x01])
			```
		"""

		# Validate at build time: MIDI sysex payloads are 7-bit.  A byte over
		# 127 would be rejected by mido at dispatch and the message silently
		# dropped every cycle with a misleading "device disconnected" log.
		invalid = [b for b in data if not 0 <= b <= 127]

		if invalid:
			raise ValueError(
				f"sysex data bytes must be 0-127 (7-bit MIDI data) - got {invalid[:4]}. "
				"Mask computed values (checksums, packed parameters) with & 0x7F first."
			)

		pulse = self._wrapped_pulse(beat)

		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = pulse,
				message_type = 'sysex',
				data = bytes(data)
			)
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	# ── OSC messages ─────────────────────────────────────────────────────────

	def osc (self, address: str, *args: typing.Any, beat: subsequence.declarations.GridBeats = 0.0) -> "subsequence.pattern_builder.PatternBuilder":

		"""
		Send an OSC message at a beat position.

		Requires ``composition.osc()`` to be called before ``composition.play()``.
		If no OSC server is configured the event is silently dropped.

		Parameters:
			address: OSC address path (e.g. ``"/mixer/fader/1"``).
			``*args``: OSC arguments - float, int, str, or bytes.
			beat: Beat position within the pattern (default 0.0).

		Example:
			```python
			# Enable a chorus effect at beat 2
			p.osc("/fx/chorus/enable", 1, beat=2.0)

			# Set a mixer pan value immediately
			p.osc("/mixer/pan/1", -0.5)
			```
		"""

		pulse = self._wrapped_pulse(beat)

		self._pattern.osc_events.append(
			subsequence.pattern.OscEvent(
				pulse = pulse,
				address = address,
				args = args
			)
		)
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def osc_ramp (
		self,
		address: str,
		start: float,
		end: float,
		beat_start: float = 0.0,
		beat_end: typing.Optional[float] = None,
		resolution: int = 4,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear"
	) -> "subsequence.pattern_builder.PatternBuilder":

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
			resolution: Pulses between OSC messages (default 4 - approximately
				6 messages per beat at 120 BPM, which is smooth for fader
				automation while keeping UDP traffic light). Use ``resolution=1``
				for pulse-level precision.
			shape: Easing curve - a name string (e.g. ``"ease_in"``) or any
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
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

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

		Used by ``bend()``, ``portamento()``, and ``slide()``.  Delegates the
		span/resolution walk (including the emit-the-endpoint rule) to
		:meth:`_ramp_pulse_span` and contributes only the pitchwheel
		conversion - normalised value scaled to 14-bit and clamped - appending
		events directly to ``self._pattern.cc_events``.

		Parameters:
			start_value: Normalised bend at the start of the ramp (-1.0 to 1.0).
			end_value: Normalised bend at the end of the ramp (-1.0 to 1.0).
			pulse_start: Absolute pulse position to start the ramp.
			pulse_end: Absolute pulse position to end the ramp.
			resolution: Number of pulses between consecutive events.
			shape: Easing curve name or callable.
		"""

		def _event (pulse: int, val: float) -> None:
			midi_value = max(-8192, min(8191, int(round(val * 8192))))
			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = pulse,
					message_type = 'pitchwheel',
					value = midi_value,
				)
			)

		self._ramp_pulse_span(pulse_start, pulse_end, start_value, end_value, shape, resolution, _event)

	def bend (
		self,
		note: int,
		amount: float,
		start: float = 0.0,
		end: float = 1.0,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Bend a specific note by index.

		Generates a pitch bend ramp that covers a fraction of the target note's
		duration, then resets to 0.0 at the next note's onset.

		The bend is laid when the build finishes, against the notes where they
		finally sit, so it can be called anywhere in the builder: before or
		after ``legato()``, ``groove()`` or any other transform.  The index
		counts the notes as they finally play.

		Parameters:
			note: Note index (0 = first, -1 = last, etc.).  If this cycle has no
				such note, nothing is bent, and a warning says so once.
			amount: Target bend normalised to -1.0..1.0 (positive = up).
				With a standard ±2-semitone pitch wheel range, 0.5 = 1 semitone.
			start: Fraction of the note's duration at which the ramp begins
				(0.0 = note onset, default).
			end: Fraction of the note's duration at which the ramp ends
				(1.0 = note end, default).  A note that rings on past the next
				one's onset counts only its time before it, since the next note
				resets the pitch wheel they share.
			shape: Easing curve - a name string (e.g. ``"ease_in"``) or any
			       callable mapping [0, 1] → [0, 1].  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.

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

		self._check_glide(shape, resolution)
		self._defer(self._pending_glides, functools.partial(self._lay_bend, note, amount, start, end, shape, resolution))
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def _lay_bend (
		self,
		note: int,
		amount: float,
		start: float,
		end: float,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn],
		resolution: int,
	) -> None:

		"""Lay the bend ``bend()`` asked for, against the notes where they finally sit."""

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		n = len(sorted_positions)

		# A note the cycle does not have is skipped, so a sparse bar still plays.
		if not -n <= note < n:
			self._say_once("bend", f"bends note {note}, but this cycle has {_notes(n)}, so it did not bend.")
			return

		# Resolve note index (supports negative indexing)
		position = sorted_positions[note]
		note_idx = note if note >= 0 else n + note

		# Duration: use the longest note at this step
		step = self._pattern.steps[position]
		note_duration = max(sounding.duration for sounding in step.notes)

		# Reset bend at the next note's onset.  For the last note that is the
		# NEXT cycle's first onset, not pulse 0 - a bend tail spilling past the
		# cycle end was cancelled mid-flight by a pulse-0 reset, leaving the
		# next cycle's first note bent.
		if note_idx < len(sorted_positions) - 1:
			reset_pulse = sorted_positions[note_idx + 1]
		else:
			reset_pulse = self._next_first_onset(sorted_positions[0])

		# The next note resets the pitch wheel the two share, so a note that
		# rings on past it has only the time before it to bend in: the ramp is
		# fitted there, still reaching its full amount.  Measured against the
		# whole note, it ran on past the reset and bent the next note (#3477).
		span = min(note_duration, reset_pulse - position)

		# Clamp start/end fractions and compute pulse range for the ramp
		start_clamped = max(0.0, min(1.0, start))
		end_clamped = max(0.0, min(1.0, end))
		bend_start_pulse = position + int(span * start_clamped)
		bend_end_pulse = position + int(span * end_clamped)

		self._generate_bend_events(0.0, amount, bend_start_pulse, bend_end_pulse, resolution, shape)

		reset_midi = max(-8192, min(8191, int(round(0.0 * 8192))))
		self._pattern.cc_events.append(
			subsequence.pattern.CcEvent(
				pulse = reset_pulse,
				message_type = 'pitchwheel',
				value = reset_midi,
			)
		)

	def portamento (
		self,
		time: float = 0.15,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""Glide between all consecutive notes using pitch bend.

		Generates a pitch bend ramp in the tail of each note, bending toward
		the next note's pitch, then resets at the next note's onset.

		The glides are laid when the build finishes, against the notes where
		they finally sit, so this can be called anywhere in the builder: before
		or after ``legato()``, ``groove()`` or any other transform.  Each glide
		ends on the next note's actual onset, swung or not.

		Most effective on mono instruments where pitch bend is per-channel.

		Parameters:
			time: Fraction of each note's duration used for the glide
				(default 0.15 - last 15% of the note).
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0 - standard ±2 st).  Pairs with intervals larger
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

			# No range limit - bend as far as MIDI allows
			p.portamento(time=0.1, bend_range=None)
			```
		"""

		if bend_range is not None and bend_range <= 0:
			raise ValueError(
				f"bend_range must be a positive number of semitones (your instrument's "
				f"pitch-wheel range) - got {bend_range}. Pass None to disable range checking."
			)

		self._check_glide(shape, resolution)
		self._defer(self._pending_glides, functools.partial(self._lay_portamento, time, shape, resolution, bend_range, wrap))
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def _lay_portamento (
		self,
		time: float,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn],
		resolution: int,
		bend_range: typing.Optional[float],
		wrap: bool,
	) -> None:

		"""Lay the glides ``portamento()`` asked for, against the notes where they finally sit."""

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
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

			# Reset at the destination note's onset.  For the wrap-around pair
			# that is the NEXT cycle's first onset, not pulse 0 - a glide
			# spilling past the cycle end was cancelled mid-flight by the
			# pulse-0 reset, leaving the first note fully bent.
			if is_last:
				reset_pulse = self._next_first_onset(sorted_positions[0])
			else:
				reset_pulse = b_pos

			# A note that rings on past its destination has only the time
			# before it to glide in, since the two share one pitch wheel: in the
			# tail of the whole note the glide ran after the reset and bent the
			# destination (#3478).
			a_duration = min(_longest_duration(a_pos), reset_pulse - a_pos)
			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			laid = len(self._pattern.cc_events)
			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)
			_mark_glide(self._pattern.cc_events[laid:], _lowest_pitch(a_pos), _lowest_pitch(b_pos), amount)

			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)

	def slide (
		self,
		notes: typing.Optional[typing.List[int]] = None,
		steps: typing.Optional[typing.List[int]] = None,
		time: float = 0.15,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn] = "linear",
		resolution: int = 1,
		bend_range: typing.Optional[float] = 2.0,
		wrap: bool = True,
		extend: bool = True,
	) -> "subsequence.pattern_builder.PatternBuilder":

		"""TB-303-style selective slide into specific notes.

		Like ``portamento()`` but only applies to flagged destination notes.
		Specify target notes by index (``notes=[1, 3]``) or by step grid
		position (``steps=[4, 12]``).  If ``extend=True`` (default) the
		preceding note's duration is extended to meet the slide target, matching
		the 303's behaviour where slide notes do not retrigger.

		The slides are laid when the build finishes, against the notes where
		they finally sit, so this can be called anywhere in the builder: before
		or after ``legato()``, ``groove()`` or any other transform.  Each glide
		ends on its target's actual onset, swung or not.

		A target with no note (an index past the last note, or a step no note
		falls on) is skipped, so a bar that comes out sparse still plays.  If
		none of the named targets has a note, a warning says so once.

		Parameters:
			notes: List of note indices to slide *into* (0 = first), counting
				the notes as they finally play.  Supports negative indexing.
				Mutually exclusive with *steps*.
			steps: List of step grid indices to slide *into*.  A step's note is
				found where swing or a groove moved it, from a quarter of a step
				early to half a step late.  Mutually exclusive with *notes*.
			time: Fraction of the preceding note's duration used for the glide.
			shape: Easing curve.  Defaults to ``"linear"``.
			resolution: Pulses between pitch bend messages.
			bend_range: Instrument's pitch wheel range in semitones
				(default 2.0).  Pairs with larger intervals are skipped.
				Pass ``None`` to disable range checking.
			wrap: If ``True`` (default), include a wrap-around slide from the
				last note back toward the first.
			extend: If ``True`` (default), extend the preceding note's duration
				to reach the slide target's onset - 303-style legato through
				the glide.

		Raises:
			ValueError: If neither or both of *notes* and *steps* are provided.

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

		if notes is not None and steps is not None:
			raise ValueError("slide() takes notes= or steps=, not both - they name the same slide targets two different ways")

		if bend_range is not None and bend_range <= 0:
			raise ValueError(
				f"bend_range must be a positive number of semitones (your instrument's "
				f"pitch-wheel range) - got {bend_range}. Pass None to disable range checking."
			)

		self._check_glide(shape, resolution)
		self._defer(self._pending_glides, functools.partial(self._lay_slide, notes, steps, time, shape, resolution, bend_range, wrap, extend))
		return typing.cast("subsequence.pattern_builder.PatternBuilder", self)

	def _lay_slide (
		self,
		notes: typing.Optional[typing.List[int]],
		steps: typing.Optional[typing.List[int]],
		time: float,
		shape: typing.Union[subsequence.declarations.EasingCurve, subsequence.easing.EasingFn],
		resolution: int,
		bend_range: typing.Optional[float],
		wrap: bool,
		extend: bool,
	) -> None:

		"""Lay the slides ``slide()`` asked for, against the notes where they finally sit."""

		if not self._pattern.steps:
			return

		sorted_positions = sorted(self._pattern.steps.keys())
		n = len(sorted_positions)

		# Resolve each named target to the note it means.  A target with no
		# note is skipped, so a bar that comes out sparse still plays.
		flagged: typing.Set[int] = set()

		if notes is not None:
			for idx in notes:
				if -n <= idx < n:
					flagged.add(sorted_positions[idx])

			if notes and not flagged:
				self._say_once("slide", f"slides into notes {list(notes)}, but this cycle has {_notes(n)}, so it did not slide.")

		else:
			# steps is not None.  Each step's straight position is the SAME
			# pulse the placement methods use — beats_to_pulses(step * (length /
			# grid)) — so a step lands even where the grid doesn't divide the
			# bar evenly.  Its note is the nearest one from a quarter of a step
			# early to half a step late, which is where swing or a groove moved
			# it: half a step late is as far as 75% swing reaches, and the two
			# bounds add to less than a step, so neighbouring steps never claim
			# the same note.
			step_beats = self._pattern.length / self._default_grid
			step_pulses = step_beats * subsequence.constants.MIDI_QUARTER_NOTE

			for s in (steps or []):
				straight = subsequence.constants.pulses.beats_to_pulses(s * step_beats)
				near = [pos for pos in sorted_positions if -0.25 * step_pulses <= pos - straight <= 0.5 * step_pulses]

				if near:
					flagged.add(min(near, key=lambda pos: abs(pos - straight)))

			if steps and not flagged:
				self._say_once("slide", f"slides into steps {list(steps)}, but no note falls on any of them, so it did not slide.")

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

			# Optionally extend preceding note to meet the target onset (303 style)
			if extend:
				if is_last:
					gap = self._next_first_onset(sorted_positions[0]) - a_pos
				else:
					gap = b_pos - a_pos
				for note in self._pattern.steps[a_pos].notes:
					note.duration = gap

			# Read the duration AFTER any extension so the glide occupies the
			# tail of the note as actually played and lands on the target
			# onset.  (Reading it before the extend block made the bend jump
			# near the note's start and then hold flat - the opposite of a
			# slide.)
			# Reset at the destination note's onset.  For the wrap-around pair
			# the destination is the NEXT cycle's first onset: resetting at
			# pulse 0 fired while a spilled glide was still in flight, so the
			# destination note played fully bent.
			reset_pulse = b_pos if not is_last else self._next_first_onset(sorted_positions[0])

			# Without extend=, a note that rings on past its target has only the
			# time before it to slide in, as in portamento() (#3478).
			a_duration = min(_longest_duration(a_pos), reset_pulse - a_pos)

			glide_start_pulse = a_pos + int(a_duration * (1.0 - time))
			glide_end_pulse = a_pos + a_duration

			laid = len(self._pattern.cc_events)
			self._generate_bend_events(0.0, amount, glide_start_pulse, glide_end_pulse, resolution, shape)
			_mark_glide(self._pattern.cc_events[laid:], _lowest_pitch(a_pos), _lowest_pitch(b_pos), amount)

			self._pattern.cc_events.append(
				subsequence.pattern.CcEvent(
					pulse = reset_pulse,
					message_type = 'pitchwheel',
					value = 0,
				)
			)

	def _check_glide (self, shape: typing.Union[str, subsequence.easing.EasingFn], resolution: int) -> None:

		"""Refuse a glide's bad arguments at the call that wrote them, not when the build finishes."""

		if resolution < 1:
			raise ValueError("resolution must be at least 1 pulse")

		subsequence.easing.get_easing(shape)

	def _say_once (self, verb: str, message: str) -> None:

		"""Warn that a part named a note it does not have, the first time only."""

		warned = _warned_missing_targets.setdefault(self._pattern, set())

		if verb in warned:
			return

		warned.add(verb)
		builder_fn = getattr(self._pattern, "_builder_fn", None)
		part = f"Part '{builder_fn.__name__}'" if builder_fn is not None else f"A part on channel {self._pattern.channel + 1}"

		logger.warning(f"{part} {message} A target with no note is skipped, and this is said once.")
