"""
Browser dashboard for a running composition.

Serves a read-only web UI that shows the live state of a composition —
tempo, current chord, section, pattern grids, and conductor signals —
over a local HTTP + WebSocket pair.  Started via ``composition.web_ui()``.
"""

import asyncio
import http.server
import json
import logging
import os
import socketserver
import threading
import traceback
import typing
import weakref

import websockets
import websockets.asyncio.server
import websockets.exceptions

import subsequence.helpers.network

logger = logging.getLogger(__name__)

class WebUI:

	"""
	Background Web UI Server.
	Delivers composition state to connected web clients via WebSockets without
	blocking the audio loop, and serves the static frontend assets via HTTP.

	Both servers bind to localhost (127.0.0.1) by default.  Pass an explicit
	``http_host`` / ``ws_host`` (e.g. "0.0.0.0") to opt into LAN exposure: the
	dashboard is read-only (inbound WebSocket messages are discarded) but it
	broadcasts full composition state, so only expose it on a trusted network.
	"""

	def __init__ (self, composition: typing.Any, http_port: int = 8080, ws_port: int = 8765, ws_host: str = "127.0.0.1", http_host: str = "127.0.0.1") -> None:

		"""
		Prepare the dashboard servers without starting them; call start() to go live.
		"""

		self.composition_ref = weakref.ref(composition)
		self.http_port = http_port
		self.ws_port = ws_port
		self.ws_host = ws_host
		self.http_host = http_host
		self._http_thread: typing.Optional[threading.Thread] = None
		self._httpd: typing.Optional[socketserver.TCPServer] = None
		self._ws_server: typing.Optional[websockets.asyncio.server.Server] = None
		self._broadcast_task: typing.Optional[asyncio.Task] = None
		self._last_state: typing.Optional[typing.Dict[str, typing.Any]] = None
		self._clients: typing.Set[websockets.asyncio.server.ServerConnection] = set()
		self._last_bar: int = -1
		self._cached_patterns: typing.List[typing.Dict[str, typing.Any]] = []

	def start (self) -> None:

		"""
		Launch the dashboard: HTTP server for the frontend, WebSocket server for live state.
		"""

		self._start_http_server()
		# Keep a reference: an unreferenced task may be garbage-collected
		# before it completes (asyncio docs).
		self._ws_bootstrap_task = asyncio.create_task(self._start_ws_server())

	def _start_http_server (self) -> None:

		"""
		Serve the static dashboard assets on a daemon thread and log the URLs to visit.
		"""

		if self._http_thread and self._http_thread.is_alive():
			return

		web_dir = os.path.join(os.path.dirname(__file__), "assets", "web")
		if not os.path.exists(web_dir):
			os.makedirs(web_dir, exist_ok=True)

		ws_port = self.ws_port

		class Handler(http.server.SimpleHTTPRequestHandler):
			def __init__ (self, *args: typing.Any, **kwargs: typing.Any) -> None:
				super().__init__(*args, directory=web_dir, **kwargs)
			def log_message (self, format: str, *args: typing.Any) -> None:
				pass # Suppress HTTP access logging to keep the console clean
			def do_GET (self) -> None:
				# Serve the dashboard with the real websocket port substituted —
				# the page hardcoding 8765 made WebUI(ws_port=...) a dashboard
				# that could never connect.
				if self.path in ("/", "/index.html"):
					try:
						with open(os.path.join(web_dir, "index.html"), "r", encoding="utf-8") as fh:
							page = fh.read().replace("__WS_PORT__", str(ws_port))
					except OSError:
						self.send_error(404)
						return
					body = page.encode("utf-8")
					self.send_response(200)
					self.send_header("Content-Type", "text/html; charset=utf-8")
					self.send_header("Content-Length", str(len(body)))
					self.end_headers()
					self.wfile.write(body)
					return
				super().do_GET()

		# Bind on the main thread so stop() has a reference to shut the server
		# down cleanly (serve_forever runs on the worker thread below).  Localhost
		# by default — see the class docstring for LAN-exposure guidance.
		# Subclass rather than mutating the TCPServer CLASS attribute, which
		# would change behaviour for every TCPServer in the process.
		class _ReusableTCPServer (socketserver.TCPServer):
			allow_reuse_address = True
		self._httpd = _ReusableTCPServer((self.http_host, self.http_port), Handler)

		def run_server () -> None:
			try:
				assert self._httpd is not None
				self._httpd.serve_forever()
			except Exception as e:
				logger.error(f"HTTP Server error: {e}")

		self._http_thread = threading.Thread(target=run_server, daemon=True)
		self._http_thread.start()
		
		local_ip = subsequence.helpers.network.get_local_ip()
		urls = [f"http://localhost:{self.http_port}"]
		# If a distinct LAN IP was discovered, add the standard loopback and the LAN IP
		if local_ip != "127.0.0.1":
			urls.append(f"http://127.0.0.1:{self.http_port}")
			urls.append(f"http://{local_ip}:{self.http_port}")
			
		logger.info("Web UI Dashboard available at:\n  " + "\n  ".join(urls))

	async def _handle_client (self, websocket: websockets.asyncio.server.ServerConnection) -> None:

		"""
		Track a connected browser for broadcasts; incoming messages are discarded (read-only UI).
		"""

		self._clients.add(websocket)
		try:
			# We don't process incoming commands in the PoC, just keep alive 
			# and listen to keep the connection open cleanly.
			async for _message in websocket:
				pass
		except websockets.exceptions.ConnectionClosed:
			pass
		finally:
			self._clients.remove(websocket)

	async def _start_ws_server (self) -> None:

		"""
		Open the WebSocket endpoint and kick off the periodic state broadcast.
		"""

		try:
			self._ws_server = await websockets.asyncio.server.serve(self._handle_client, self.ws_host, self.ws_port)
			self._broadcast_task = asyncio.create_task(self._broadcast_loop())
		except Exception as e:
			logger.error(f"WebSocket server error: {e}")

	async def _broadcast_loop (self) -> None:

		"""
		Push composition state to all connected browsers 10x/sec, skipping unchanged frames.
		"""

		while True:
			# Broadcast 10 times a second to keep UI snappy without bogging down the loop
			await asyncio.sleep(0.1)
			
			if not self._clients:
				continue
			
			comp = self.composition_ref()
			if comp is None:
				break

			try:
				state = self._get_state(comp)

				# Serialising the full note set 10x/sec on the audio loop is
				# avoidable jitter - skip when nothing changed since last send.
				if state == self._last_state:
					continue

				self._last_state = state
				message = json.dumps(state)
				websockets.broadcast(self._clients.copy(), message)
			except Exception as e:
				logger.error(f"Error broadcasting UI state: {e}\n{traceback.format_exc()}")

	def _get_state (self, comp: typing.Any) -> typing.Dict[str, typing.Any]:

		"""
		Snapshot the musical state of the composition (tempo, chord, section, patterns, signals) as a JSON-ready dict.
		"""

		state: typing.Dict[str, typing.Any] = {
			# The LIVE tempo — comp.bpm is the declared value and freezes
			# during target_bpm ramps, clock-follow, and Link tempo changes.
			"bpm": comp.sequencer.current_bpm if comp.sequencer else comp.bpm,
			"section": None,
			"chord": None,
			"patterns": [],
			"signals": {},
			"playhead_pulse": 0,
			"pulses_per_beat": 24,
			"key": comp.key,
			"section_bar": None,
			"section_bars": None,
			"next_section": None,
			"global_bar": 0,
			"global_beat": 0
		}
		
		if comp.sequencer:
			state["playhead_pulse"] = comp.sequencer.pulse_count
			state["pulses_per_beat"] = comp.sequencer.pulses_per_beat
			state["global_bar"] = max(0, comp.sequencer.current_bar) + 1
			state["global_beat"] = max(0, comp.sequencer.current_beat) + 1
		
		if comp.form_state:
			section_info = comp.form_state.get_section_info()
			if section_info:
				state["section"] = section_info.name
				state["section_bar"] = section_info.bar + 1
				state["section_bars"] = section_info.bars
				state["next_section"] = section_info.next_section
				
		if comp.harmonic_state and comp.harmonic_state.current_chord:
			state["chord"] = comp.harmonic_state.current_chord.name()
			
		# Refresh pattern grid only when the bar changes, so the visual update
		# is synced to when the pattern *starts playing*, not when it's rebuilt
		# (which happens one lookahead beat early).
		current_bar = state["global_bar"]
		if current_bar != self._last_bar:
			self._last_bar = current_bar
			self._cached_patterns = []
			for name, pattern in comp.running_patterns.items():
				pattern_data: typing.Dict[str, typing.Any] = {
					"name": name,
					"muted": getattr(pattern, "_muted", False),
					"length_pulses": int(pattern.length * state["pulses_per_beat"]),
					"drum_map": getattr(pattern, "_drum_note_map", None),
					"notes": []
				}
				if hasattr(pattern, "steps"):
					for pulse, step in pattern.steps.items():
						for note in getattr(step, "notes", []):
							pattern_data["notes"].append({
								"p": note.pitch,
								"s": pulse,
								"d": note.duration,
								"v": note.velocity
							})
				self._cached_patterns.append(pattern_data)
		state["patterns"] = self._cached_patterns

		def _extract_val (val: typing.Any) -> typing.Optional[float]:
			if hasattr(val, "current"): # Matches EasedValue
				try:
					return float(val.current)
				except Exception as e:
					logger.debug(f"WebUI failed to extract float from .current on {val}: {e}")
			if callable(getattr(val, "value", None)):
				try:
					return float(val.value())
				except Exception as e:
					logger.debug(f"WebUI failed to extract float from .value() on {val}: {e}")
			elif hasattr(val, "value"):
				try:
					return float(val.value)
				except Exception as e:
					logger.debug(f"WebUI failed to extract float from .value on {val}: {e}")
			elif type(val) in (int, float, bool):
				return float(val)
			return None

		# Extract from conductor
		if comp.conductor:
			beat_time = comp.sequencer.pulse_count / comp.sequencer.pulses_per_beat if comp.sequencer else 0.0
			for name, signal in comp.conductor._signals.items():
				try:
					state["signals"][name] = float(signal.value_at(beat_time))
				except Exception as e:
					# A raising signal should be diagnosable, not vanish from
					# the dashboard (same treatment as _extract_val below).
					logger.debug(f"WebUI failed to read conductor signal '{name}': {e}")
					
		# Extract from composition data dictionary
		for name, val in comp.data.items():
			extracted = _extract_val(val)
			if extracted is not None:
				state["signals"][name] = extracted

		return state

	def stop (self) -> None:

		"""
		Shut down both servers cleanly so ports and threads don't leak.
		"""

		if self._broadcast_task:
			self._broadcast_task.cancel()
			self._broadcast_task = None

		if self._ws_server:
			self._ws_server.close()
			# If the event loop is still running, await the shutdown
			try:
				loop = asyncio.get_running_loop()
				loop.create_task(self._ws_server.wait_closed())
			except RuntimeError:
				pass
			self._ws_server = None

		# Shut the HTTP server down cleanly so the listening port and worker
		# thread don't leak for the life of the process.  serve_forever() runs on
		# _http_thread, so shutdown() must be called from another thread (here).
		if self._httpd is not None:
			self._httpd.shutdown()
			self._httpd.server_close()
			self._httpd = None

		if self._http_thread is not None:
			self._http_thread.join(timeout=2.0)
			self._http_thread = None
