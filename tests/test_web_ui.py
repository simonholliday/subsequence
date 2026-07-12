"""Tests for the background Web UI dashboard (WebUI).

The web UI is a read-only dashboard served on localhost.  These cover the two
load-bearing pieces: the state snapshot broadcast to clients, and the HTTP
server lifecycle (start binds a worker thread; stop shuts it down and joins it).
"""

import json

import subsequence
import subsequence.pattern
import subsequence.web_ui


def test_web_ui_get_state_has_expected_shape(patch_midi: None) -> None:
    """_get_state() returns a JSON-serialisable dict with the keys the frontend reads."""

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    ui = subsequence.web_ui.WebUI(comp)

    state = ui._get_state(comp)

    for key in (
        "bpm",
        "key",
        "patterns",
        "signals",
        "playhead_pulse",
        "pulses_per_beat",
        "global_bar",
    ):
        assert key in state

    assert state["bpm"] == 120
    assert state["key"] == "C"
    assert isinstance(state["patterns"], list)
    assert isinstance(state["signals"], dict)

    # It is sent over the WebSocket, so it must serialise.
    json.dumps(state)


def test_web_ui_http_server_starts_and_stops_cleanly(patch_midi: None) -> None:
    """_start_http_server() binds a worker thread; stop() shuts it down and joins it.

    Guards the port/thread cleanup path that stop() exists to provide.
    """

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    ui = subsequence.web_ui.WebUI(
        comp, http_port=0
    )  # ephemeral port — avoids conflicts

    ui._start_http_server()

    assert ui._httpd is not None
    assert ui._http_thread is not None
    assert ui._http_thread.is_alive()

    ui.stop()

    assert ui._httpd is None
    assert ui._http_thread is None


def test_web_ui_get_state_serialises_running_pattern(patch_midi: None) -> None:
    """A running pattern appears in state["patterns"] with its name, mute state, and notes."""

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")

    pattern = subsequence.pattern.Pattern(channel=0, length=4)
    pattern.add_note(position=24, pitch=60, velocity=90, duration=12)
    comp._running_patterns["bass"] = pattern

    ui = subsequence.web_ui.WebUI(comp)
    state = ui._get_state(comp)

    assert len(state["patterns"]) == 1

    entry = state["patterns"][0]
    assert entry["name"] == "bass"
    assert entry["muted"] is False
    assert entry["length_pulses"] == 96
    assert entry["drum_map"] is None
    assert entry["notes"] == [{"p": 60, "s": 24, "d": 12, "v": 90}]

    # The pattern entry rides the same WebSocket payload, so it must serialise.
    json.dumps(state)
