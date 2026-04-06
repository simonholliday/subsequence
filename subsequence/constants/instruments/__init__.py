"""Instrument definitions — note maps, CC maps, and constants.

Each instrument module exports constants and lookup dictionaries that can be
passed to ``@composition.pattern()`` via ``drum_note_map`` and ``cc_name_map``.

Available instruments:

- ``subsequence.constants.instruments.gm_cc`` - General MIDI CC assignments
- ``subsequence.constants.instruments.gm_drums`` - General MIDI Level 1 drums
- ``subsequence.constants.instruments.gm_instruments`` - General MIDI Level 1 program numbers
- ``subsequence.constants.instruments.roland_tr8s`` - Roland TR-8S (drums + CCs)
- ``subsequence.constants.instruments.vermona_drm1_drums`` - Vermona DRM1 MKIV drums
"""
