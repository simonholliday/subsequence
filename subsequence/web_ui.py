import asyncio
import http.server
import json
import logging
import os
import socketserver
import threading
import typing
import weakref

import websockets
import websockets.asyncio.server
import websockets.exceptions

logger = logging.getLogger(__name__)

class WebUI:

    """
    Background Web UI Server.
    Delivers composition state to connected web clients via WebSockets without
    blocking the audio loop, and serves the static frontend assets via HTTP.
    """

    def __init__ (self, composition: typing.Any, http_port: int = 8080, ws_port: int = 8765) -> None:

        self.composition_ref = weakref.ref(composition)
        self.http_port = http_port
        self.ws_port = ws_port
        self._http_thread: typing.Optional[threading.Thread] = None
        self._ws_server: typing.Optional[websockets.asyncio.server.Server] = None
        self._broadcast_task: typing.Optional[asyncio.Task] = None
        self._clients: typing.Set[websockets.asyncio.server.ServerConnection] = set()

    def start (self) -> None:

        self._start_http_server()
        asyncio.create_task(self._start_ws_server())

    def _start_http_server (self) -> None:

        if self._http_thread and self._http_thread.is_alive():
            return

        web_dir = os.path.join(os.path.dirname(__file__), "assets", "web")
        if not os.path.exists(web_dir):
            os.makedirs(web_dir, exist_ok=True)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
                super().__init__(*args, directory=web_dir, **kwargs)
            def log_message(self, format: str, *args: typing.Any) -> None:
                pass # Suppress HTTP access logging to keep the console clean

        def run_server() -> None:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("", self.http_port), Handler) as httpd:
                try:
                    httpd.serve_forever()
                except Exception as e:
                    logger.error(f"HTTP Server error: {e}")

        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        logger.info(f"Web UI Dashboard available at http://localhost:{self.http_port}")

    async def _handle_client (self, websocket: websockets.asyncio.server.ServerConnection) -> None:

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

        try:
            self._ws_server = await websockets.asyncio.server.serve(self._handle_client, "0.0.0.0", self.ws_port)
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")

    async def _broadcast_loop (self) -> None:

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
                message = json.dumps(state)
                websockets.broadcast(self._clients, message)
            except Exception as e:
                import traceback
                logger.error(f"Error broadcasting UI state: {e}\n{traceback.format_exc()}")

    def _get_state (self, comp: typing.Any) -> typing.Dict[str, typing.Any]:

        state: typing.Dict[str, typing.Any] = {
            "bpm": comp.bpm,
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
            state["patterns"].append(pattern_data)

        def _extract_val(val: typing.Any) -> typing.Optional[float]:
            if hasattr(val, "current"): # Matches EasedValue
                try:
                    return float(val.current)
                except Exception:
                    pass
            if callable(getattr(val, "value", None)):
                try:
                    return float(val.value())
                except Exception:
                    pass
            elif hasattr(val, "value"):
                try:
                    return float(val.value)
                except Exception:
                    pass
            elif type(val) in (int, float, bool):
                return float(val)
            return None

        # Extract from conductor
        if comp.conductor:
            beat_time = comp.sequencer.pulse_count / comp.sequencer.pulses_per_beat if comp.sequencer else 0.0
            for name, signal in comp.conductor._signals.items():
                try:
                    state["signals"][name] = float(signal.value_at(beat_time))
                except Exception:
                    pass
                    
        # Extract from composition data dictionary
        for name, val in comp.data.items():
            extracted = _extract_val(val)
            if extracted is not None:
                state["signals"][name] = extracted

        return state

    def stop (self) -> None:

        if self._broadcast_task:
            self._broadcast_task.cancel()
        if self._ws_server:
            self._ws_server.close()
            # If the event loop is still running, await the shutdown
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ws_server.wait_closed())
            except RuntimeError:
                pass
