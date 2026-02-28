"""Easing functions for transitions and ramps.

Easing functions map a normalised progress value *t* in [0, 1] to an eased
output in [0, 1].  They are used by ``conductor.line()``, ``target_bpm()``,
``cc_ramp()``, and ``pitch_bend_ramp()`` to shape how a value moves from a
start to an end over time.

Pass a name string or a plain callable to any ``shape`` parameter:

    composition.conductor.line("filter", 0, 1, 64, shape="ease_in_out")
    composition.target_bpm(140, bars=8, shape="s_curve")
    p.cc_ramp(74, 0, 127, shape="exponential")

    # Custom callable — receives and returns a float in [0, 1]:
    p.cc_ramp(74, 0, 127, shape=lambda t: t ** 0.5)

Available shapes:

    "linear"      Constant rate (default).
    "ease_in"     Slow start, accelerates — fade-ins, building tension.
    "ease_out"    Fast start, decelerates — fade-outs, natural decay.
    "ease_in_out" Smooth S-curve (Hermite smoothstep) — BPM changes, crossfades.
    "exponential" Very slow start, rapid end (cubic) — filter sweeps.
    "logarithmic" Rapid start, very gradual end (cubic) — volume fades.
    "s_curve"     Smoother S-curve (Perlin smootherstep) — long, gentle transitions.

All functions satisfy f(0) = 0 and f(1) = 1 and are monotonically non-decreasing.
Input outside [0, 1] is not defined.
"""

from __future__ import annotations

import typing


# ─── Easing functions ─────────────────────────────────────────────────────────


def linear (t: float) -> float:
    """No transformation — constant rate of change."""
    return t


def ease_in (t: float) -> float:
    """Quadratic ease-in: slow start, accelerates toward the end."""
    return t * t


def ease_out (t: float) -> float:
    """Quadratic ease-out: fast start, decelerates toward the end."""
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out (t: float) -> float:
    """Hermite smoothstep S-curve: smooth start and end, faster in the middle."""
    return t * t * (3.0 - 2.0 * t)


def exponential (t: float) -> float:
    """Cubic ease-in: very slow start with rapid acceleration.

    Approximates a perceptually linear response for audio parameters like
    filter cutoff, where the human ear's logarithmic sensitivity means a
    slow early ramp sounds more even.
    """
    return t * t * t


def logarithmic (t: float) -> float:
    """Cubic ease-out: rapid initial change that tapers to a gradual end.

    Useful for decay shapes and volume fades where most of the audible change
    happens early and the tail fades imperceptibly.
    """
    return 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t)


def s_curve (t: float) -> float:
    """Perlin smootherstep: a smoother S-curve than ease_in_out.

    Has zero first *and* second derivatives at t=0 and t=1, eliminating the
    subtle acceleration jerk at the boundaries.  Best for long, slow
    transitions where the smoothness is perceptible.
    """
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


# ─── Registry and lookup ──────────────────────────────────────────────────────

EasingFn = typing.Callable[[float], float]

EASING_FUNCTIONS: typing.Dict[str, EasingFn] = {
    "linear":      linear,
    "ease_in":     ease_in,
    "ease_out":    ease_out,
    "ease_in_out": ease_in_out,
    "exponential": exponential,
    "logarithmic": logarithmic,
    "s_curve":     s_curve,
}


def get_easing (shape: typing.Union[str, EasingFn]) -> EasingFn:
    """Return the easing function for *shape*.

    *shape* may be a name string (see :data:`EASING_FUNCTIONS`) or any
    callable that maps a float in [0, 1] to a float in [0, 1].

    Raises :class:`ValueError` for unknown string names.
    """
    if callable(shape):
        return shape
    if shape not in EASING_FUNCTIONS:
        available = ", ".join(f'"{k}"' for k in sorted(EASING_FUNCTIONS))
        raise ValueError(
            f"Unknown easing shape {shape!r}. Available shapes: {available}"
        )
    return EASING_FUNCTIONS[shape]

def map_value (
    value: float,
    in_min: float = 0.0,
    in_max: float = 1.0,
    out_min: float = 0.0,
    out_max: float = 1.0,
    shape: typing.Union[str, EasingFn] = "linear",
    clamp: bool = True
) -> float:
    """Map a value from an input range to an output range, with optional easing.

    Linearly maps *value* from the range ``[in_min, in_max]`` into a normalised
    progress ratio [0.0, 1.0], applies the designated easing curve, and
    interpolates that eased ratio into the output range ``[out_min, out_max]``.

    This is particularly useful for musically scaling raw generative outputs
    (which usually fall between 0.0 and 1.0) into MIDI ranges like pitch or
    velocity, while automatically applying musical volume or tension curves.

    Parameters:
        value: The raw input to scale.
        in_min: The lower bound of the input's expected range.
        in_max: The upper bound of the input's expected range.
        out_min: The lower bound of the mapped output range.
        out_max: The upper bound of the mapped output range.
        shape: The easing curve to apply to the mapped ratio before
            outputting (e.g. \"linear\", \"ease_in_out\"). See
            :func:`get_easing` for all available shapes.
        clamp: If True (the default), values outside the input range
            will be clamped so they never exceed the output bounds.
            Essential for ensuring MIDI values don't break valid ranges.

    Returns:
        The mapped and eased value as a float.
    """

    if in_min == in_max:
        return out_min

    # 1. Normalise to [0.0, 1.0]
    t = (value - in_min) / (in_max - in_min)

    # 2. Clamp
    if clamp:
        t = max(0.0, min(1.0, t))

    # 3. Apply easing curve
    eased_t = get_easing(shape)(t)

    # 4. Map to output range
    return out_min + (out_max - out_min) * eased_t


# ─── Stateful interpolation ───────────────────────────────────────────────────


class EasedValue:

    """Smoothly interpolates between discrete data updates.

    When external data arrives in snapshots — API polls, sensor readings,
    OSC messages — jumping instantly to each new value often sounds jarring.
    ``EasedValue`` remembers the previous value and provides a smooth,
    eased interpolation to the new one over a normalised progress window.

    A typical use-case is a ``composition.schedule()`` function that writes
    to ``composition.data`` every *N* bars, paired with a pattern that reads
    the smoothed value on every rebuild:

    Example::

        # Module level: create one per data field you want to smooth.
        iss_lat = subsequence.easing.EasedValue(initial=0.5)

        # Scheduled task (fires every 16 bars):
        def fetch_data(p):
            new_lat = get_latest_latitude()   # 0.0–1.0
            iss_lat.update(new_lat)

        # Pattern (rebuilds every bar).  16-bar cycle matches the schedule.
        @composition.pattern(channel=0, length=4)
        def drums(p):
            progress = (p.cycle % 16) / 16   # 0 → 1 over one fetch cycle
            velocity = int(100 * iss_lat.get(progress))
            p.hit_steps("kick_1", range(16), velocity=velocity)

    Args:
        initial: Optional starting value.  If provided, the first call to
            :meth:`update` will ease from this initial value.  If omitted,
            the first call to :meth:`update` will instantly set both the
            *previous* and *current* values to the new target, preventing
            an unintended transition from a default value.
    """

    def __init__ (self, initial: typing.Optional[float] = None) -> None:

        # We keep the internal float fields strictly non-Optional (defaulting to 0.0)
        # to guarantee mypy safety and branch-free math in get() and delta. The
        # _has_updated flag abstracts the "first-update" logic away safely.
        val = initial if initial is not None else 0.0
        self._prev:    float = val
        self._current: float = val
        self._has_updated: bool = initial is not None

    def update (self, value: float) -> None:

        """Accept a new target value.

        The current value becomes the new *previous* baseline, and
        *value* becomes the target that :meth:`get` interpolates toward.
        If no ``initial`` value was provided at construction, the very first
        call to this method sets both *previous* and *current* to *value*.

        Args:
            value: The new target, typically a normalised float in [0, 1]
                (though any numeric range is accepted as long as consumers
                interpret it consistently).
        """

        if not self._has_updated:
            self._prev = value
            self._current = value
            self._has_updated = True
        else:
            self._prev    = self._current
            self._current = value

    def get (
        self,
        progress: float,
        shape: typing.Union[str, EasingFn] = "ease_in_out",
    ) -> float:

        """Return the interpolated value at *progress* through the transition.

        Args:
            progress: How far through the current transition, in [0, 1].
                ``0.0`` returns the previous value; ``1.0`` returns the
                current target.  Typically computed as
                ``(p.cycle % N) / N`` where *N* is the number of pattern
                cycles per data-fetch cycle.
            shape: Easing shape name (see :data:`EASING_FUNCTIONS`) or a
                callable ``f(t) -> t`` in [0, 1].  Defaults to
                ``"ease_in_out"`` (Hermite smoothstep).

        Returns:
            The interpolated float between the previous and current value.
        """

        eased = get_easing(shape)(progress)
        return self._prev + (self._current - self._prev) * eased

    @property
    def current (self) -> float:
        """The most recently set target value (after the last :meth:`update`)."""
        return self._current

    @property
    def previous (self) -> float:
        """The value that was current before the last :meth:`update`."""
        return self._prev

    @property
    def delta (self) -> float:
        """Signed change between the previous and current value.

        Positive means the value rose on the last :meth:`update`; negative
        means it fell; zero means it was unchanged.  The magnitude reflects
        the size of the jump.

        This property is constant across all pattern rebuilds within one fetch
        cycle, making it straightforward to branch on direction without
        worrying about sample-level fluctuations:

        Example::

            # Choose arpeggio direction based on which way the value is moving.
            direction = "up" if iss_lat.delta >= 0 else "down"
            p.arpeggio(pitches, step=0.25, direction=direction)

            # Scale an effect by how large the change was.
            urgency = abs(iss_lat.delta)   # 0.0 = stable, larger = big jump
        """
        return self._current - self._prev
