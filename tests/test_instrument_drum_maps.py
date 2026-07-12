"""Tests for the faithful-core drum-map vocabulary.

Every device drum map aliases only the General MIDI names for voices the device
genuinely has — no creative approximations onto unrelated voices.  These shared
GM names (canonically from ``pymididefs.drums``) are the vocabulary symbolic
mirroring re-resolves per device, so the same name plays the right voice on a
DRM1 *and* a GM sampler.  These tests lock that contract: faithful aliases
resolve to the correct per-device note, and the trimmed DRM1 approximations are
gone.
"""

import pymididefs.drums

import subsequence.constants.instruments.vermona_drm1_drums as drm1
import subsequence.constants.instruments.roland_tr8s as tr8s
import subsequence.constants.instruments.gm_drums as gm


# ── DRM1: faithful aliases kept, approximations removed ─────────────────────


def test_drm1_keeps_faithful_gm_aliases() -> None:
    """The DRM1 map aliases GM names only for the voices it really has."""

    m = drm1.VERMONA_DRM1_DRUM_MAP

    assert m["kick_1"] == drm1.KICK
    assert m["kick_2"] == drm1.KICK
    assert m["snare_1"] == drm1.SNARE
    assert m["snare_2"] == drm1.SNARE
    assert m["hand_clap"] == drm1.CLAP  # GM 39 == DRM1 CLAP 39
    assert m["hi_hat_closed"] == drm1.HIHAT_1_CLOSED  # note 44 (not GM's 42)
    assert m["hi_hat_pedal"] == drm1.HIHAT_1_CLOSED
    assert m["hi_hat_open"] == drm1.HIHAT_1_OPEN


def test_drm1_native_names_unchanged() -> None:
    """The DRM1's own voice names are untouched by the trim."""

    m = drm1.VERMONA_DRM1_DRUM_MAP

    for name in (
        "kick",
        "snare",
        "clap",
        "drum_1",
        "drum_2",
        "multi",
        "hihat_1_closed",
        "hihat_1_open",
        "hihat_2_closed",
        "hihat_2_open",
    ):
        assert name in m


def test_drm1_approximations_removed() -> None:
    """The subjective GM approximations are gone — the DRM1 lacks these voices."""

    m = drm1.VERMONA_DRM1_DRUM_MAP

    for name in (
        "side_stick",
        "low_tom",
        "low_floor_tom",
        "high_tom",
        "crash_1",
        "crash_2",
        "splash_cymbal",
        "chinese_cymbal",
        "ride_1",
        "ride_2",
        "ride_bell",
        "tambourine",
        "cabasa",
        "maracas",
        "shaker",
        "cowbell",
        "claves",
        "high_woodblock",
        "low_bongo",
        "mute_high_conga",
        "high_agogo",
        "vibraslap",
    ):
        assert name not in m


# ── TR-8S: faithful GM aliases added ────────────────────────────────────────


def test_tr8s_faithful_gm_aliases() -> None:
    """The TR-8S gains GM aliases for the voices it genuinely has."""

    m = tr8s.ROLAND_TR8S_DRUM_MAP

    assert m["kick_1"] == tr8s.BD
    assert m["snare_1"] == tr8s.SD
    assert m["side_stick"] == tr8s.RS  # GM 37 == TR-8S RS 37
    assert m["hand_clap"] == tr8s.HC
    assert m["hi_hat_closed"] == tr8s.CH  # note 42
    assert m["hi_hat_pedal"] == tr8s.CH
    assert m["hi_hat_open"] == tr8s.OH
    assert m["crash_1"] == tr8s.CC
    assert m["ride_1"] == tr8s.RC


def test_tr8s_toms_grouped_by_register() -> None:
    """GM's six toms map onto the TR-8S's three by register."""

    m = tr8s.ROLAND_TR8S_DRUM_MAP

    assert m["low_floor_tom"] == tr8s.LT
    assert m["high_floor_tom"] == tr8s.LT
    assert m["low_tom"] == tr8s.MT
    assert m["low_mid_tom"] == tr8s.MT
    assert m["high_mid_tom"] == tr8s.HT
    assert m["high_tom"] == tr8s.HT


def test_tr8s_omits_absent_voices() -> None:
    """GM voices the TR-8S lacks are not aliased (no approximations)."""

    m = tr8s.ROLAND_TR8S_DRUM_MAP

    for name in (
        "cowbell",
        "tambourine",
        "splash_cymbal",
        "chinese_cymbal",
        "ride_bell",
        "low_conga",
        "high_bongo",
        "claves",
        "shaker",
        "short_guiro",
        "mute_triangle",
    ):
        assert name not in m


# ── Cross-map canonical contract (the symbolic-mirror premise) ──────────────


def test_shared_gm_vocabulary_across_devices() -> None:
    """The faithful kit names exist in all three maps — the shared vocabulary."""

    for name in ("kick_1", "snare_1", "hand_clap", "hi_hat_closed", "hi_hat_open"):
        assert name in drm1.VERMONA_DRM1_DRUM_MAP
        assert name in tr8s.ROLAND_TR8S_DRUM_MAP
        assert name in gm.GM_DRUM_MAP


def test_same_name_resolves_to_device_specific_notes() -> None:
    """One canonical name → the correct, *different* note on each device.

    This is exactly what symbolic mirroring relies on: ``"hi_hat_closed"`` is
    note 44 on the DRM1 but 42 in General MIDI / on the TR-8S.
    """

    assert drm1.VERMONA_DRM1_DRUM_MAP["hi_hat_closed"] == 44
    assert gm.GM_DRUM_MAP["hi_hat_closed"] == 42
    assert tr8s.ROLAND_TR8S_DRUM_MAP["hi_hat_closed"] == 42


# ── Unnumbered primary aliases (kick/snare/crash/ride) ──────────────────────


def test_gm_map_includes_primary_aliases() -> None:
    """gm_drums.GM_DRUM_MAP resolves both the bare primaries and the numbered names."""

    m = gm.GM_DRUM_MAP
    assert m["kick"] == m["kick_1"] == 36
    assert m["snare"] == m["snare_1"] == 38
    assert m["crash"] == m["crash_1"] == 49
    assert m["ride"] == m["ride_1"] == 51


def test_gm_map_is_superset_of_pure_spec() -> None:
    """Subsequence merges the aliases in; the upstream pymididefs spec stays clean."""

    assert gm.GM_DRUM_MAP["kick"] == 36
    assert "kick" not in pymididefs.drums.GM_DRUM_MAP  # pure spec is one name per note
    assert len(gm.GM_DRUM_MAP) > len(
        pymididefs.drums.GM_DRUM_MAP
    )  # aliases merged on top of the clean spec


def test_tr8s_primary_aliases() -> None:
    """The TR-8S has a real kick / snare / crash / ride, so all four bare names resolve."""

    m = tr8s.ROLAND_TR8S_DRUM_MAP
    assert m["kick"] == tr8s.BD
    assert m["snare"] == tr8s.SD
    assert m["crash"] == tr8s.CC
    assert m["ride"] == tr8s.RC


def test_drm1_primary_aliases_only_where_voiced() -> None:
    """The DRM1 has kick/snare (native) but no crash/ride voice — so neither is aliased."""

    m = drm1.VERMONA_DRM1_DRUM_MAP
    assert m["kick"] == drm1.KICK
    assert m["snare"] == drm1.SNARE
    assert "crash" not in m
    assert "ride" not in m
