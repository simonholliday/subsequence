"""Tests for stage 8 — presets & polish.

Genre progression table; Xenakis sieve kernel + algebra; Toussaint rhythm
measures; world-rhythm Motif.preset; role parameter bundles; the
Hooktheory-informed major graph style; and Steedman's Progression.elaborate.
"""

import math
import typing

import pytest

import subsequence
import subsequence.chords
import subsequence.harmonic_state
import subsequence.progressions
import subsequence.roles
import subsequence.sequence_utils as su


# ---------------------------------------------------------------------------
# Genre progression table
# ---------------------------------------------------------------------------


def test_every_preset_parses_and_resolves () -> None:

	"""Every genre preset is a valid, resolvable progression."""

	for name in subsequence.progressions._PRESETS:
		value = subsequence.progression(name)
		assert isinstance(value, subsequence.Progression)
		resolved = value.resolve("C", "major")
		assert resolved.is_concrete
		assert len(resolved.chords) == len(value.spans)


def test_named_presets_resolve_as_expected () -> None:

	"""A few presets resolve to their known chords."""

	assert [c.name() for c in subsequence.progression("trance_epic").resolve("A", "aeolian").chords] == ["Am", "F", "C", "G"]
	assert [c.name() for c in subsequence.progression("pop_axis").resolve("C").chords] == ["C", "G", "Am", "F"]
	assert [c.name() for c in subsequence.progression("twelve_bar_blues").resolve("E").chords][:4] == ["E7", "E7", "E7", "E7"]


def test_unknown_preset_lists_the_table () -> None:

	"""An unknown name raises, naming the known presets."""

	with pytest.raises(ValueError, match="Unknown progression preset"):
		subsequence.progression("not_a_genre")


# ---------------------------------------------------------------------------
# Xenakis sieves
# ---------------------------------------------------------------------------


def test_sieve_union_builds_scales_and_pools () -> None:

	"""The primary union form builds scales, whole-tone, and non-octave pools."""

	major = su.sieve([(12, 0), (12, 2), (12, 4), (12, 5), (12, 7), (12, 9), (12, 11)], hi=12)
	assert major == [0, 2, 4, 5, 7, 9, 11]

	assert su.sieve([(2, 0)], hi=12) == [0, 2, 4, 6, 8, 10]		# whole-tone

	pool = su.sieve([(5, 0), (7, 1)], lo=60, hi=96)				# a non-octave pool
	assert pool == sorted(pool) and pool[0] >= 60 and pool[-1] < 96
	assert 60 in pool and 64 in pool		# 5·0 and 7·1+... members


def test_sieve_validates_modulus () -> None:

	"""A modulus below 1 raises."""

	with pytest.raises(ValueError, match="modulus"):
		su.sieve([(0, 0)], hi=8)


def test_sieve_algebra () -> None:

	"""residual_class composes under | & ~."""

	rc = su.residual_class
	assert (rc(2, 0) | rc(3, 0)).evaluate(hi=12) == [0, 2, 3, 4, 6, 8, 9, 10]
	assert (rc(2, 0) & rc(3, 0)).evaluate(hi=12) == [0, 6]		# multiples of 6
	assert (~rc(2, 0)).evaluate(hi=8) == [1, 3, 5, 7]			# the odds
	assert 4 in rc(2, 0) and 5 not in rc(2, 0)


# ---------------------------------------------------------------------------
# Toussaint measures
# ---------------------------------------------------------------------------


def test_evenness_picks_out_euclidean_rhythms () -> None:

	"""A maximally-even (Euclidean) rhythm scores higher than a clustered one."""

	assert su.rhythmic_evenness([0, 3, 6], 8) > su.rhythmic_evenness([0, 1, 2], 8)
	assert su.rhythmic_evenness([0, 4, 8, 12], 16) == pytest.approx(1.0)		# perfectly even
	assert su.rhythmic_evenness([0], 8) == 1.0								# degenerate


def test_offbeatness_counts_coprime_pulses () -> None:

	"""Four-on-the-floor is fully on-beat; off-beats land on coprime pulses."""

	assert su.offbeatness([0, 4, 8, 12], 16) == 0
	assert su.offbeatness([1, 3, 5, 7, 9, 11, 13, 15], 16) == 8		# all odd = all coprime
	assert su.offbeatness([0, 3, 6, 10, 13], 16) == 2				# bossa: pulses 3 and 13


def test_syncopation_rises_off_the_beat () -> None:

	"""On-beat rhythms score low; weak-pulse rhythms score high."""

	assert su.syncopation([0], 16) == 0.0
	assert su.syncopation([3, 7, 11, 15], 16) > su.syncopation([0, 4, 8, 12], 16)

	with pytest.raises(ValueError, match="one value per grid"):
		su.syncopation([0], 16, weights=[1.0, 0.5])


# ---------------------------------------------------------------------------
# World-rhythm Motif.preset
# ---------------------------------------------------------------------------


def test_preset_places_clave_onsets () -> None:

	"""son clave 3-2 onsets land at the catalogued pulses over one bar."""

	clave = subsequence.Motif.preset("son_clave_3_2")
	assert clave.onsets() == [0.0, 0.75, 1.5, 2.5, 3.0]		# pulses 0,3,6,10,12 of 16
	assert clave.length == 4.0
	assert all(event.pitch == "claves" for event in clave.events)		# default GM voice


def test_preset_default_voices_resolve_against_gm () -> None:

	"""The default voices are real GM drum names — a no-pitch preset sounds.

	Regression for the review's "silent default voice" finding: place the
	preset against the GM map and assert the drum names resolve to notes.
	"""

	import subsequence.constants.instruments.gm_drums as gm
	import subsequence.pattern as pattern_mod
	import subsequence.pattern_builder as pb

	for name in subsequence.motifs._WORLD_RHYTHMS:
		_steps, _grid, voice = subsequence.motifs._WORLD_RHYTHMS[name]
		assert voice in gm.GM_DRUM_MAP, f"{name}: default voice {voice!r} is not a GM drum"

	# And the placed motif actually emits notes through the funnel.
	builder = pb.PatternBuilder(
		pattern=pattern_mod.Pattern(channel=9, length=4.0),
		cycle=0,
		drum_note_map=gm.GM_DRUM_MAP,
	)
	builder.motif(subsequence.Motif.preset("son_clave_3_2"))
	notes = [note.pitch for step in builder._pattern.steps.values() for note in step.notes]
	assert notes == [75, 75, 75, 75, 75]		# 5 claves hits, GM note 75


def test_preset_pitch_override_and_12_pulse () -> None:

	"""pitch= overrides the voice; a bell pattern uses its 12-pulse grid."""

	clave = subsequence.Motif.preset("son_clave_3_2", pitch="rim")
	assert all(event.pitch == "rim" for event in clave.events)

	bembe = subsequence.Motif.preset("bembe")
	assert len(bembe.onsets()) == 7
	assert bembe.onsets()[1] == pytest.approx(2 * 4.0 / 12)		# pulse 2 of a 12-grid bar


def test_preset_unknown_name_raises () -> None:

	"""An unknown rhythm name lists the table."""

	with pytest.raises(ValueError, match="Unknown rhythm preset"):
		subsequence.Motif.preset("not_a_rhythm")


# ---------------------------------------------------------------------------
# Role bundles
# ---------------------------------------------------------------------------


def test_role_bundles_are_splattable_kwargs () -> None:

	"""Roles are plain kwarg dicts over the placement surface."""

	assert subsequence.roles.BASS["root"] == 36
	assert set(subsequence.roles.LEAD) <= {"root", "velocity", "fit"}
	assert set(subsequence.roles.ROLES) == {"bass", "pad", "lead", "arp"}

	# Splatting into a placement call is the intended use.
	composition = subsequence.Composition.__new__(subsequence.Composition)
	merged = {**subsequence.roles.PAD, "root": 48}
	assert merged["root"] == 48 and merged["fit"] == subsequence.roles.PAD["fit"]


# ---------------------------------------------------------------------------
# Hooktheory-informed graph style
# ---------------------------------------------------------------------------


def test_hooktheory_style_builds_and_walks (patch_midi: None) -> None:

	"""The corpus-weighted major style is reachable by name and walks diatonic chords."""

	composition = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C", seed=3)
	composition.harmony(style="hooktheory_major", cycle_beats=4)

	frozen = composition.freeze(8)
	names = {c.name() for c in frozen.chords}

	# Everything it draws is C-major diatonic (triads + the V7 colour).
	diatonic = {"C", "Dm", "Em", "F", "G", "Am", "Bdim", "G7"}
	assert names <= diatonic
	assert "C" in names		# the tonic appears


def test_pop_major_alias (patch_midi: None) -> None:

	"""'pop_major' is an alias for the Hooktheory style."""

	hs = subsequence.harmonic_state.HarmonicState(key_name="C", graph_style="pop_major")
	assert hs.current_chord.name() == "C"


# ---------------------------------------------------------------------------
# Steedman elaborate()
# ---------------------------------------------------------------------------


def test_elaborate_depth_0_is_identity () -> None:

	"""depth=0 returns the progression unchanged."""

	blues = subsequence.progression("twelve_bar_blues").resolve("C")
	assert blues.elaborate(0) is blues


def test_elaborate_inserts_secondary_dominants () -> None:

	"""depth=1 puts a V7 before each chord; depth=2 a secondary ii-V."""

	one_bar = subsequence.progression(["C"]).resolve("C")		# a single C

	d1 = one_bar.elaborate(1)
	assert [c.name() for c in d1.chords] == ["G7", "C"]		# V7 → I

	d2 = one_bar.elaborate(2)
	assert [c.name() for c in d2.chords] == ["Dm7", "G7", "C"]	# ii-V-I

	# Spans subdivide the original bar evenly.
	assert d2.spans[0].beats == pytest.approx(4.0 / 3)


def test_elaborate_subdivides_and_preserves_decorations () -> None:

	"""Each target keeps its decorations on its (subdivided) sub-span."""

	value = subsequence.progression([("Cmaj7", 4)]).resolve("C").extend(9)
	d1 = value.elaborate(1)

	assert len(d1.spans) == 2
	assert d1.spans[0].beats == pytest.approx(2.0) and d1.spans[1].beats == pytest.approx(2.0)
	assert d1.spans[1].extensions == (9,)		# the C kept its 9th
	assert d1.spans[0].extensions == ()			# the inserted G7 is bare


def test_elaborate_determinism_and_seed_warning () -> None:

	"""depth<3 is deterministic; depth>=3 is seeded (and warns without a seed)."""

	blues = subsequence.progression("twelve_bar_blues").resolve("C")

	# Deterministic for shallow depth (no random choices).
	assert [c.name() for c in blues.elaborate(2).chords] == [c.name() for c in blues.elaborate(2).chords]

	# Seeded reproducibility at depth 3.
	assert [c.name() for c in blues.elaborate(3, seed=7).chords] == [c.name() for c in blues.elaborate(3, seed=7).chords]

	with pytest.warns(UserWarning, match="tritone"):
		blues.elaborate(3)


def test_elaborate_requires_concrete_rooted_chords () -> None:

	"""A key-relative progression, or a PitchSet, raises."""

	with pytest.raises(ValueError, match="key-relative"):
		subsequence.progression([1, 4, 5]).elaborate(1)

	pitchset = subsequence.progressions.Progression(
		spans=(subsequence.progressions.ChordSpan(chord=subsequence.progressions.PitchSet([60, 63, 67]), beats=4.0),)
	)
	with pytest.raises(ValueError, match="rooted chords"):
		pitchset.elaborate(1)

	with pytest.raises(ValueError, match="depth"):
		subsequence.progression(["C"]).resolve("C").elaborate(-1)


def test_elaborate_blues_depth_per_chorus () -> None:

	"""The flagship: a 12-bar blues grows more ii-Vs each chorus."""

	blues = subsequence.progression("twelve_bar_blues").resolve("C")

	assert len(blues.chords) == 12
	assert len(blues.elaborate(1).chords) == 24		# +1 approach per bar
	assert len(blues.elaborate(2).chords) == 36		# +2 per bar
