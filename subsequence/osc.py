"""OSC integration for realtime control and state broadcasting.

Start the OSC server by calling ``composition.osc()`` before ``composition.play()``.
The server listens on a UDP port (default 9000) for incoming control messages
and sends state updates to a target host/port (default 127.0.0.1:9001).

Built-in Receive Handlers
─────────────────────────
- ``/bpm <int>``: Set tempo
- ``/mute/<name>``: Mute a pattern
- ``/unmute/<name>``: Unmute a pattern
- ``/data/<key> <value>``: Update shared data (supports int, float, str)

Built-in Send Events
────────────────────
- ``/bar <int>``: On bar change
- ``/chord <string>``: On chord change
- ``/section <string>``: On section change
- ``/bpm <int>``: On tempo change
"""

import asyncio
import logging
import typing

import pythonosc.dispatcher
import pythonosc.osc_server
import pythonosc.udp_client

if typing.TYPE_CHECKING:
	from subsequence.composition import Composition


logger = logging.getLogger(__name__)


class OscServer:

	"""Async OSC server/client for bi-directional communication."""

	def __init__ (
		self,
		composition: "Composition",
		receive_port: int = 9000,
		send_port: int = 9001,
		send_host: str = "127.0.0.1"
	) -> None:

		self._composition = composition
		self._receive_port = receive_port
		self._send_port = send_port
		self._send_host = send_host
		
		self._server: typing.Optional[typing.Any] = None
		self._transport: typing.Optional[asyncio.BaseTransport] = None
		self._client: typing.Optional[pythonosc.udp_client.SimpleUDPClient] = None
		self._dispatcher = pythonosc.dispatcher.Dispatcher()

		# Register built-in handlers
		self._dispatcher.map("/bpm", self._handle_bpm)
		self._dispatcher.map("/mute/*", self._handle_mute)
		self._dispatcher.map("/unmute/*", self._handle_unmute)
		self._dispatcher.map("/data/*", self._handle_data)


	async def start (self) -> None:

		"""Start the OSC server and client."""

		# client for sending
		self._client = pythonosc.udp_client.SimpleUDPClient(self._send_host, self._send_port)

		# server for receiving
		self._server = pythonosc.osc_server.AsyncIOOSCUDPServer(
			("0.0.0.0", self._receive_port),
			self._dispatcher,
			asyncio.get_event_loop()  # type: ignore[arg-type]
		)

		transport, _ = await self._server.create_serve_endpoint()
		self._transport = transport

		logger.info(f"OSC listening on :{self._receive_port}, sending to {self._send_host}:{self._send_port}")


	async def stop (self) -> None:

		"""Stop the OSC server."""

		if self._transport:
			self._transport.close()
			self._transport = None
			logger.info("OSC server stopped")


	def send (self, address: str, *args: typing.Any) -> None:

		"""Send an OSC message."""

		if self._client:
			try:
				self._client.send_message(address, args)
			except Exception as e:
				logger.warning(f"OSC send error: {e}")


	def map (self, address: str, handler: typing.Callable) -> None:

		"""Register a custom OSC handler."""

		self._dispatcher.map(address, handler)


	# Handlers

	def _handle_bpm (self, address: str, *args: typing.Any) -> None:
		if not args:
			return
		try:
			bpm = int(args[0])
			self._composition.set_bpm(bpm)
		except (ValueError, TypeError):
			logger.warning(f"Invalid OSC BPM argument: {args[0]}")

	def _handle_mute (self, address: str, *args: typing.Any) -> None:
		# address is like /mute/drums
		parts = address.split("/")
		if len(parts) >= 3:
			name = parts[2]
			self._composition.mute(name)

	def _handle_unmute (self, address: str, *args: typing.Any) -> None:
		parts = address.split("/")
		if len(parts) >= 3:
			name = parts[2]
			self._composition.unmute(name)

	def _handle_data (self, address: str, *args: typing.Any) -> None:
		# address is like /data/intensity
		if not args:
			return
		parts = address.split("/")
		if len(parts) >= 3:
			key = parts[2]
			self._composition.data[key] = args[0]
