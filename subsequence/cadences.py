"""Cadences — the curated formula table behind the producer cadence names.

A cadence is a two-chord tail formula plus a melodic close degree.  The
producer names are primary — ``"strong"``, ``"soft"``, ``"open"``,
``"fakeout"`` — with the theory names (authentic, plagal, half, deceptive)
accepted as aliases, per the standing rule: theory machinery under the hood,
producer words on the surface.

The table is pure data; the consumers wire it in:

- ``Progression.cadence(name)`` — tail substitution on a progression value.
- ``Progression.generate(cadence=)`` / ``freeze(cadence=)`` — the formula
  becomes pins on the final bars of the constrained walk.
- ``Motif.generate(cadence=)`` — the close degree becomes ``end_on``.
- ``Composition.request_cadence()`` / ``section_cadence()`` — the live
  clock steers its walk to arrive at the formula.
- ``sentence()`` / ``period()`` — the close degree aims the final unit.

Formula elements follow the progression-element grammar: ints are diatonic
degrees (quality inferred from key+scale at resolution time — ``4`` is IV
in major and iv in minor), roman strings carry their quality with them
(``"V"`` is the major dominant even in minor — the cadential convention).
"""

import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class Cadence:
    """One cadence formula — a named tail plus its melodic close.

    Attributes:
            name: The producer name (the primary key in the table).
            theory_name: The traditional name, for the curious.
            formula: The chord tail, in progression-element grammar, ending on
                    the arrival chord.
            close_degree: The scale degree a melody lands on at this cadence
                    (1 for full closes; 5 for the open half — and 1 for the
                    fakeout too: the melody resolves as promised while the
                    harmony swerves, which is the trick of it).
    """

    name: str
    theory_name: str
    formula: typing.Tuple[typing.Any, ...]
    close_degree: int


# The curated table — producer names primary.  Two-chord tails throughout:
# a cadence is an arrival WITH its approach, and two chords is the smallest
# honest spelling of that.
CADENCES: typing.Dict[str, Cadence] = {
    "strong": Cadence(
        name="strong",
        theory_name="authentic",
        formula=("V", 1),
        close_degree=1,
    ),
    "soft": Cadence(
        name="soft",
        theory_name="plagal",
        formula=(4, 1),
        close_degree=1,
    ),
    "open": Cadence(
        name="open",
        theory_name="half",
        formula=(4, "V"),
        close_degree=5,
    ),
    "fakeout": Cadence(
        name="fakeout",
        theory_name="deceptive",
        formula=("V", 6),
        close_degree=1,
    ),
}

# Theory names as aliases — accuracy costs nothing here, the words name the
# same formulas.
_ALIASES: typing.Dict[str, str] = {
    "authentic": "strong",
    "perfect": "strong",
    "plagal": "soft",
    "half": "open",
    "deceptive": "fakeout",
    "interrupted": "fakeout",
}


def cadence_formula(name: str) -> Cadence:
    """Look up a cadence by producer name or theory alias, loudly.

    Raises:
            ValueError: If the name is unknown — the error lists every valid
                    name and alias.
    """

    if not isinstance(name, str):
        raise TypeError(f"a cadence is named by string, got {name!r}")

    key = name.strip().lower()
    key = _ALIASES.get(key, key)

    if key not in CADENCES:
        names = ", ".join(sorted(CADENCES))
        aliases = ", ".join(sorted(_ALIASES))
        raise ValueError(
            f"Unknown cadence {name!r}. Cadences: {names} (aliases: {aliases})."
        )

    return CADENCES[key]
