import subsequence.chords
import subsequence.voicings


def test_root_position_identity () -> None:

	"""Inversion 0 should return a copy of the original intervals."""

	assert subsequence.voicings.invert_chord([0, 4, 7], 0) == [0, 4, 7]


def test_first_inversion_triad () -> None:

	"""First inversion of a major triad: bottom note up an octave."""

	result = subsequence.voicings.invert_chord([0, 4, 7], 1)

	# E is bass (interval 4 becomes 0), G above (+3), C above (+8)
	assert result == [0, 3, 8]


def test_second_inversion_triad () -> None:

	"""Second inversion of a major triad: two bottom notes up an octave."""

	result = subsequence.voicings.invert_chord([0, 4, 7], 2)

	# G is bass (interval 7 becomes 0), C above (+5), E above (+9)
	assert result == [0, 5, 9]


def test_first_inversion_seventh () -> None:

	"""First inversion of a dominant seventh chord."""

	result = subsequence.voicings.invert_chord([0, 4, 7, 10], 1)

	# [4, 7, 10, 12] -> re-zeroed: [0, 3, 6, 8]
	assert result == [0, 3, 6, 8]


def test_second_inversion_seventh () -> None:

	"""Second inversion of a dominant seventh chord."""

	result = subsequence.voicings.invert_chord([0, 4, 7, 10], 2)

	# [7, 10, 12, 16] -> re-zeroed: [0, 3, 5, 9]
	assert result == [0, 3, 5, 9]


def test_third_inversion_seventh () -> None:

	"""Third inversion of a dominant seventh chord."""

	result = subsequence.voicings.invert_chord([0, 4, 7, 10], 3)

	# [10, 12, 16, 19] -> re-zeroed: [0, 2, 6, 9]
	assert result == [0, 2, 6, 9]


def test_inversion_wraps_around () -> None:

	"""Inversion >= note count should wrap (like an extra octave cycle)."""

	# Inversion 3 on a triad wraps to 0 (root position).
	assert subsequence.voicings.invert_chord([0, 4, 7], 3) == [0, 4, 7]

	# Inversion 4 on a triad wraps to 1 (first inversion).
	assert subsequence.voicings.invert_chord([0, 4, 7], 4) == [0, 3, 8]


def test_empty_intervals () -> None:

	"""Empty interval list should return empty."""

	assert subsequence.voicings.invert_chord([], 0) == []
	assert subsequence.voicings.invert_chord([], 1) == []


def test_minor_triad_inversions () -> None:

	"""Minor triad inversions should work correctly."""

	minor = [0, 3, 7]

	# First inversion: [3, 7, 12] -> [0, 4, 9]
	assert subsequence.voicings.invert_chord(minor, 1) == [0, 4, 9]

	# Second inversion: [7, 12, 15] -> [0, 5, 8]
	assert subsequence.voicings.invert_chord(minor, 2) == [0, 5, 8]


# ─── Voice leading ──────────────────────────────────────────────


def test_voice_lead_no_previous () -> None:

	"""With no previous voicing, return root position."""

	result = subsequence.voicings.voice_lead([0, 4, 7], 60, None)

	assert result == [60, 64, 67]


def test_voice_lead_picks_closest () -> None:

	"""Voice leading should pick the inversion closest to the previous voicing."""

	# Previous: C major root position [60, 64, 67]
	# Target: F major (root 65). Inversions:
	#   root:  [65, 69, 72] — cost = |65-60| + |69-64| + |72-67| = 5+5+5 = 15
	#   1st:   [65+0, 65+3, 65+8] = [65, 68, 73] — cost = 5+4+6 = 15
	#   2nd:   [65+0, 65+5, 65+9] = [65, 70, 74] — cost = 5+6+7 = 18
	# Root and 1st both cost 15. Root wins (checked first).
	result = subsequence.voicings.voice_lead([0, 4, 7], 65, [60, 64, 67])

	assert result == [65, 69, 72]


def test_voice_lead_prefers_smaller_movement () -> None:

	"""Voice leading should prefer the inversion with smallest total movement."""

	# Previous: first inversion C major = [64, 67, 72]
	# Target: F major (root 65). Inversions:
	#   root:  [65, 69, 72] — cost = |65-64| + |69-67| + |72-72| = 1+2+0 = 3
	#   1st:   [65, 68, 73] — cost = 1+1+1 = 3
	#   2nd:   [65, 70, 74] — cost = 1+3+2 = 6
	# Root and 1st tie at 3, root wins (first checked).
	result = subsequence.voicings.voice_lead([0, 4, 7], 65, [64, 67, 72])

	assert result == [65, 69, 72]


def test_voice_lead_size_mismatch_falls_back () -> None:

	"""When chord sizes differ, fall back to root position."""

	# Previous was a seventh chord (4 notes), new is a triad (3 notes).
	result = subsequence.voicings.voice_lead([0, 4, 7], 60, [60, 64, 67, 70])

	assert result == [60, 64, 67]


def test_voice_lead_empty_intervals () -> None:

	"""Empty intervals should return empty."""

	assert subsequence.voicings.voice_lead([], 60, None) == []
	assert subsequence.voicings.voice_lead([], 60, [60, 64, 67]) == []


# ─── VoiceLeadingState ──────────────────────────────────────────


def test_state_first_call_root_position () -> None:

	"""First call to VoiceLeadingState should return root position."""

	state = subsequence.voicings.VoiceLeadingState()
	result = state.next([0, 4, 7], 60)

	assert result == [60, 64, 67]


def test_state_persists_across_calls () -> None:

	"""VoiceLeadingState should use the previous voicing for the next call."""

	state = subsequence.voicings.VoiceLeadingState()

	# First: C major root position.
	v1 = state.next([0, 4, 7], 60)

	assert v1 == [60, 64, 67]

	# Second: the state should now pick an inversion that's close to v1.
	v2 = state.next([0, 3, 7], 62)

	# D minor inversions relative to [60, 64, 67]:
	#   root:  [62, 65, 69] — cost = 2+1+2 = 5
	#   1st:   [62, 66, 71] — cost = 2+2+4 = 8
	#   2nd:   [62, 67, 69] — cost = 2+3+2 = 7
	assert v2 == [62, 65, 69]

	# Third call should use v2 as the reference.
	assert state.previous_voicing == v2


def test_state_size_change_resets () -> None:

	"""When chord size changes, state should fall back to root position."""

	state = subsequence.voicings.VoiceLeadingState()

	# Triad.
	state.next([0, 4, 7], 60)

	# Seventh chord — different size, falls back to root position.
	v2 = state.next([0, 4, 7, 10], 60)

	assert v2 == [60, 64, 67, 70]

	# State should now have the seventh chord voicing.
	assert state.previous_voicing == [60, 64, 67, 70]


# ─── Chord.tones() count parameter ─────────────────────────────


def test_tones_count_matches_natural () -> None:

	"""count equal to natural note count should match default."""

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	assert chord.tones(root=60, count=3) == chord.tones(root=60)


def test_tones_count_extends_triad () -> None:

	"""count > 3 on a triad should cycle intervals into higher octaves."""

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	# C major: [0, 4, 7] -> 5 notes: C E G C' E'
	assert chord.tones(root=60, count=5) == [60, 64, 67, 72, 76]


def test_tones_count_extends_two_octaves () -> None:

	"""count=7 on a triad should span two full octaves plus the root."""

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	assert chord.tones(root=60, count=7) == [60, 64, 67, 72, 76, 79, 84]


def test_tones_count_one () -> None:

	"""count=1 should return just the root."""

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	assert chord.tones(root=60, count=1) == [60]


def test_tones_count_with_inversion () -> None:

	"""count should work together with inversion."""

	chord = subsequence.chords.Chord(root_pc=0, quality="major")

	# First inversion intervals: [0, 3, 8]
	# 5 notes: 60, 63, 68, 72, 75
	result = chord.tones(root=60, inversion=1, count=5)

	assert result == [60, 63, 68, 72, 75]


def test_tones_count_seventh_chord () -> None:

	"""count should extend seventh chords correctly."""

	chord = subsequence.chords.Chord(root_pc=0, quality="dominant_7th")

	# [0, 4, 7, 10] -> 6 notes: C E G Bb C' E'
	assert chord.tones(root=60, count=6) == [60, 64, 67, 70, 72, 76]


def test_tones_count_minor () -> None:

	"""count should extend minor triads correctly."""

	chord = subsequence.chords.Chord(root_pc=0, quality="minor")

	# [0, 3, 7] -> 5 notes: C Eb G C' Eb'
	assert chord.tones(root=60, count=5) == [60, 63, 67, 72, 75]
