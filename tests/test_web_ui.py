"""Tests for the background Web UI dashboard (WebUI).

The web UI is a read-only dashboard served on localhost.  These cover the two
load-bearing pieces: the state snapshot broadcast to clients, and the HTTP
server lifecycle (start binds a worker thread; stop shuts it down and joins it).
"""

import json

import subsequence
import subsequence.web_ui


def test_web_ui_get_state_has_expected_shape (patch_midi: None) -> None:

	"""_get_state() returns a JSON-serialisable dict with the keys the frontend reads."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	ui = subsequence.web_ui.WebUI(comp)

	state = ui._get_state(comp)

	for key in ("bpm", "key", "patterns", "signals", "playhead_pulse", "pulses_per_beat", "global_bar"):
		assert key in state

	assert state["bpm"] == 120
	assert state["key"] == "C"
	assert isinstance(state["patterns"], list)
	assert isinstance(state["signals"], dict)

	# It is sent over the WebSocket, so it must serialise.
	json.dumps(state)


def test_web_ui_http_server_starts_and_stops_cleanly (patch_midi: None) -> None:

	"""_start_http_server() binds a worker thread; stop() shuts it down and joins it.

	Guards the port/thread cleanup path that stop() exists to provide.
	"""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	ui = subsequence.web_ui.WebUI(comp, http_port=0)  # ephemeral port — avoids conflicts

	ui._start_http_server()

	assert ui._httpd is not None
	assert ui._http_thread is not None
	assert ui._http_thread.is_alive()

	ui.stop()

	assert ui._httpd is None
	assert ui._http_thread is None
