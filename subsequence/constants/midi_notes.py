"""MIDI note number constants.

Maps note names to their MIDI note numbers (0–127). Convention: **C4 = 60** (Middle C),
matching the MIDI Manufacturers Association standard and most DAWs (Ableton, Logic, Reaper).

Notes are named ``<Pitch><Octave>`` for naturals and ``<Pitch>S<Octave>`` for sharps::

    import subsequence.constants.midi_notes as notes

    p.note(notes.A4, velocity=100)       # 69
    p.arpeggio(chord.tones(notes.E2))    # 40
    root = notes.C3                      # 48

Range: C0 (12) through G9 (127). Sub-octave notes (MIDI 0–11) are omitted as they are
rarely used musically. Use raw integers for those if needed.

Sharps are provided (e.g. ``CS4`` for C♯4); flats are enharmonic equivalents
(Db4 == CS4 == 61).
"""

# ── Octave 0 ── (C4 = 60, so C0 = 12)
C0  = 12
CS0 = 13
D0  = 14
DS0 = 15
E0  = 16
F0  = 17
FS0 = 18
G0  = 19
GS0 = 20
A0  = 21
AS0 = 22
B0  = 23

# ── Octave 1 ──
C1  = 24
CS1 = 25
D1  = 26
DS1 = 27
E1  = 28
F1  = 29
FS1 = 30
G1  = 31
GS1 = 32
A1  = 33
AS1 = 34
B1  = 35

# ── Octave 2 ──
C2  = 36
CS2 = 37
D2  = 38
DS2 = 39
E2  = 40
F2  = 41
FS2 = 42
G2  = 43
GS2 = 44
A2  = 45
AS2 = 46
B2  = 47

# ── Octave 3 ──
C3  = 48
CS3 = 49
D3  = 50
DS3 = 51
E3  = 52
F3  = 53
FS3 = 54
G3  = 55
GS3 = 56
A3  = 57
AS3 = 58
B3  = 59

# ── Octave 4 — Middle C ──
C4  = 60  # Middle C
CS4 = 61
D4  = 62
DS4 = 63
E4  = 64
F4  = 65
FS4 = 66
G4  = 67
GS4 = 68
A4  = 69  # Concert pitch (440 Hz)
AS4 = 70
B4  = 71

# ── Octave 5 ──
C5  = 72
CS5 = 73
D5  = 74
DS5 = 75
E5  = 76
F5  = 77
FS5 = 78
G5  = 79
GS5 = 80
A5  = 81
AS5 = 82
B5  = 83

# ── Octave 6 ──
C6  = 84
CS6 = 85
D6  = 86
DS6 = 87
E6  = 88
F6  = 89
FS6 = 90
G6  = 91
GS6 = 92
A6  = 93
AS6 = 94
B6  = 95

# ── Octave 7 ──
C7  = 96
CS7 = 97
D7  = 98
DS7 = 99
E7  = 100
F7  = 101
FS7 = 102
G7  = 103
GS7 = 104
A7  = 105
AS7 = 106
B7  = 107

# ── Octave 8 ──
C8  = 108
CS8 = 109
D8  = 110
DS8 = 111
E8  = 112
F8  = 113
FS8 = 114
G8  = 115
GS8 = 116
A8  = 117
AS8 = 118
B8  = 119

# ── Octave 9 (C9–G9 only — G9 = 127 is the MIDI ceiling) ──
C9  = 120
CS9 = 121
D9  = 122
DS9 = 123
E9  = 124
F9  = 125
FS9 = 126
G9  = 127
