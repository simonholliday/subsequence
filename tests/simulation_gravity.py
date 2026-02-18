import random
import sys
import collections
import statistics

# Add project root to path
sys.path.append(".")

from subsequence.harmonic_state import HarmonicState
from subsequence.chords import Chord

GRAPH_STYLES = [
    "functional_major",
    "aeolian_minor",
    "phrygian_minor",
    "lydian_major",
    "dorian_minor",
    "chromatic_mediant",
    "suspended",
    "mixolydian",
    "whole_tone",
    "diminished",
    "turnaround"
]

# Thresholds for pass/fail.
MAX_TOP_1_PCT = 0.45
MAX_TOP_2_PCT = 0.75
MAX_STREAK = 10


def analyze_style(style, gravity, nir_strength=0.5, steps=1000, seed=42):
    rng = random.Random(seed)

    try:
        hs = HarmonicState(
            key_name="C",
            graph_style=style,
            include_dominant_7th=True,
            key_gravity_blend=gravity,
            nir_strength=nir_strength,
            rng=rng
        )
    except Exception as e:
        print(f"Failed to init {style}: {e}")
        return None

    history_roots = []

    current = hs.current_chord
    history_roots.append(current.root_pc)

    for _ in range(steps):
        chord = hs.step()
        history_roots.append(chord.root_pc)

    # Analyze streaks (same root)
    streaks = []
    current_streak = 1
    max_streak = 0

    for i in range(1, len(history_roots)):
        if history_roots[i] == history_roots[i-1]:
            current_streak += 1
        else:
            streaks.append(current_streak)
            max_streak = max(max_streak, current_streak)
            current_streak = 1

    max_streak = max(max_streak, current_streak)

    avg_streak = statistics.mean(streaks) if streaks else 0
    unique_roots = len(set(history_roots))

    # Analyze distribution
    counts = collections.Counter(history_roots)
    if not counts:
        return None

    total_steps = len(history_roots)
    sorted_common = counts.most_common()
    top_1_pct = sorted_common[0][1] / total_steps
    top_2_pct = (sorted_common[0][1] + sorted_common[1][1]) / total_steps if len(sorted_common) > 1 else top_1_pct

    return {
        "style": style,
        "gravity": gravity,
        "nir_strength": nir_strength,
        "max_streak": max_streak,
        "avg_streak": avg_streak,
        "unique_roots": unique_roots,
        "top_1_pct": top_1_pct,
        "top_2_pct": top_2_pct
    }


def run_simulation():
    print(f"{'Style':<20} | {'Grav':<4} | {'NIR':<4} | {'Max Strk':<8} | {'Top 1%':<6} | {'Top 2%':<6} | {'Unique':<6}")
    print("-" * 75)

    results = []
    failures = 0

    for style in GRAPH_STYLES:
        for gravity in [0.0, 0.5, 0.8, 1.0]:
            for nir in [0.0, 0.5, 1.0]:
                res = analyze_style(style, gravity, nir_strength=nir)
                if res:
                    results.append(res)

                    flag = ""
                    if res['top_1_pct'] > MAX_TOP_1_PCT or res['top_2_pct'] > MAX_TOP_2_PCT or res['max_streak'] > MAX_STREAK:
                        flag = " FAIL"
                        failures += 1

                    print(f"{style:<20} | {gravity:<4.1f} | {nir:<4.1f} | {res['max_streak']:<8} | {res['top_1_pct']:<6.2f} | {res['top_2_pct']:<6.2f} | {res['unique_roots']:<6}{flag}")

    print()

    if failures:
        print(f"RESULT: {failures} combination(s) exceeded thresholds (top_1>{MAX_TOP_1_PCT}, top_2>{MAX_TOP_2_PCT}, streak>{MAX_STREAK})")
    else:
        print(f"RESULT: All {len(results)} combinations passed.")


if __name__ == "__main__":
    run_simulation()
