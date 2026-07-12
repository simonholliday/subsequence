import dataclasses
import math
import random
import typing


@dataclasses.dataclass(frozen=True)
class HarmonicRhythm:
    """A bounded, optionally-quantised *harmonic rhythm* — how long each chord lasts.

    Harmonic rhythm is the rate at which the chords change.  It can be regular,
    irregular, or static; this spec describes the **irregular** case — each chord
    lasts a fresh random length somewhere between ``low`` and ``high`` beats.  When
    ``step`` is given, those lengths snap to whole multiples of it, so the result
    is irregular but still lands on a musical grid (e.g. always a whole-note
    boundary).

    Build one with :func:`between` rather than constructing it directly::

            harmonic_rhythm = between(WHOLE, 3 * WHOLE, step=WHOLE)   # 1, 2, or 3 whole notes

    The other two harmonic-rhythm shapes are expressed without this class:
    a single ``float`` (static — every chord the same length) and a ``list`` of
    floats (a *shaped* rhythm such as ``[WHOLE, HALF, HALF]``, cycled per chord).
    ``p.progression()`` / ``comp.chords()`` accept all three.
    """

    low: float
    high: float
    step: typing.Optional[float] = None

    def __post_init__(self) -> None:
        """Validate the bounds at construction so a typo surfaces at the call site."""

        if self.low <= 0:
            raise ValueError(
                f"harmonic rhythm low ({self.low:g}) must be positive — lengths are in beats"
            )
        if self.high < self.low:
            raise ValueError(
                f"harmonic rhythm high ({self.high:g}) must be at least low ({self.low:g})"
            )
        if self.step is not None and self.step <= 0:
            raise ValueError(f"harmonic rhythm step ({self.step:g}) must be positive")

    def resolve(self, rng: random.Random) -> float:
        """Draw one chord length in beats from this spec.

        With a ``step``, the length is a whole multiple of it snapped *inside*
        ``[low, high]`` (so a quantised rhythm never strays past its bounds).  If
        no whole multiple fits within the bounds, the nearest in-range length is
        used.  Without a ``step``, the draw is continuous and uniform.
        """

        if self.step:
            # Smallest/largest step-multiples that still sit within the bounds.
            # The epsilon absorbs float dust so e.g. 12 / 4 floors to 3, not 2.
            lo = max(1, math.ceil(self.low / self.step - 1e-9))
            hi = math.floor(self.high / self.step + 1e-9)
            if hi < lo:
                hi = lo
            length = rng.randint(lo, hi) * self.step

            # Honour the bounds over the grid: when no whole multiple fits inside
            # [low, high] (e.g. between(2, 3, step=4)), clamp to the nearest edge so
            # the result never strays past the bounds the musician asked for.
            return float(min(self.high, max(self.low, length)))

        return float(rng.uniform(self.low, self.high))


def between(
    low: float, high: float, step: typing.Optional[float] = None
) -> HarmonicRhythm:
    """A harmonic rhythm that varies *between* two lengths (in beats).

    Each chord lasts a random length in ``[low, high]``.  Pass ``step`` to snap
    those lengths to a grid — e.g. ``between(WHOLE, 3 * WHOLE, step=WHOLE)`` gives
    one, two, or three whole notes, never anything in between.

    Reads aloud the way you'd describe it: "between one and three whole notes,
    in whole-note steps."
    """

    return HarmonicRhythm(low=low, high=high, step=step)
