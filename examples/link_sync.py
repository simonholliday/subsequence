"""
Ableton Link synchronisation demo.

Two ways to use this example:

1. **Standalone** (no other Link peers):
   Run this script.  Subsequence creates a new Link session and plays a simple
   pattern.  Any other Link-enabled app that joins the same LAN will
   automatically lock to its tempo and phase.

2. **Peer** (other Link apps already running on the LAN):
   Run this script while Ableton Live, another Subsequence instance, or any
   other Link-enabled app is running on the same network.  Subsequence will
   detect the session, wait for the next bar boundary, then join in tempo-locked.

Requirements:
    pip install subsequence[link]

Usage:
    python examples/link_sync.py
"""

import subsequence

# A simple four-on-the-floor kick + offbeat hihat for audible phase verification.
# When running alongside another Link app, the downbeat should land exactly together.

comp = subsequence.Composition(bpm=120, key="C")

# Join the Link session.  quantum=4 means one bar in 4/4 time.
# Playback waits for the next bar boundary before the first note sounds.
comp.link(quantum=4.0)


@comp.pattern(channel=10, beats=4)
def kick(p):
    p.hit(35, beats=[0, 2], velocity=110, duration=0.1)


@comp.pattern(channel=10, beats=4)
def hat(p):
    density = p.data.get("density", 0.7)
    p.hit(42, beats=[1, 3], velocity=int(80 * density), duration=0.05)


@comp.pattern(channel=10, beats=8)
def snare(p):
    p.hit(38, beats=[2, 6], velocity=100, duration=0.15)


comp.play()
