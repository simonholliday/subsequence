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
        return shape  # type: ignore[return-value]
    if shape not in EASING_FUNCTIONS:
        available = ", ".join(f'"{k}"' for k in sorted(EASING_FUNCTIONS))
        raise ValueError(
            f"Unknown easing shape {shape!r}. Available shapes: {available}"
        )
    return EASING_FUNCTIONS[shape]
