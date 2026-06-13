"""Role parameter bundles — starting points you splat, not a role API.

The design deliberately ships **no** role nouns (no ``p.bass()`` verb): a
"role" is just a small bundle of placement parameters a part usually wants,
kept as plain data so you splat and override it.  Each bundle holds keyword
arguments shared by the placement surface — ``comp.phrase_part(...)`` and
``p.motif(...)`` / ``p.phrase(...)`` (``root`` register anchor, ``velocity``,
and the chord-snapping ``fit`` dial):

	import subsequence

	comp.phrase_part(channel=2, part="bass", **subsequence.roles.BASS)
	comp.phrase_part(channel=4, part="lead", **subsequence.roles.LEAD, root=78)   # override root

	@comp.pattern(channel=3, bars=2)
	def pad (p):
		p.motif(chords, **subsequence.roles.PAD)

These are taste defaults, not rules — a bass usually sits low and locks to
chord tones (high ``fit``), a pad sits mid and floats (lower ``fit``).  Change
any value freely; the bundle is a dict.
"""

import typing


# A bass: low register, strong, locked hard to the chord tones.
BASS: typing.Dict[str, typing.Any] = {
	"root": 36,			# C2
	"velocity": 105,
	"fit": 0.9,
}

# A pad: mid register, soft, floating loosely over the changes.
PAD: typing.Dict[str, typing.Any] = {
	"root": 60,			# C4
	"velocity": 70,
	"fit": 0.6,
}

# A lead: upper register, present, playing against the changes.
LEAD: typing.Dict[str, typing.Any] = {
	"root": 72,			# C5
	"velocity": 95,
	"fit": 0.7,
}

# An arp: mid register, even and bright, free to wander between chord tones.
ARP: typing.Dict[str, typing.Any] = {
	"root": 60,			# C4
	"velocity": 85,
	"fit": 0.5,
}

# The bundles by name, for programmatic lookup.
ROLES: typing.Dict[str, typing.Dict[str, typing.Any]] = {
	"bass": BASS,
	"pad": PAD,
	"lead": LEAD,
	"arp": ARP,
}
