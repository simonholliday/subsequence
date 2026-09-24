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

Sent at every bar line, whether or not anything changed:

- ``/bar <int>``: The bar number
- ``/bpm <float>``: The tempo
- ``/chord <string>``: The chord sounding, while one is
- ``/section <string>``: The form's section, while a form is running
"""

import asyncio
import logging
import time
import typing

import pythonosc.dispatcher
import pythonosc.osc_message_builder
import pythonosc.osc_packet
import pythonosc.udp_client

if typing.TYPE_CHECKING:
	from subsequence.composition import Composition


logger = logging.getLogger(__name__)

# How far ahead a bundle's timetag is honoured.  Past this, take it for a
# mistake — two machines whose clocks disagree, or a timetag written in the
# wrong epoch — and play it now, saying so.  A control surface that appears to
# do nothing for an hour is worse than one that acts early and tells you.
MAX_TIMETAG_AHEAD_SECONDS = 60.0


class _TimetagProtocol (asyncio.DatagramProtocol):

	"""Honour a bundle's timetag without stopping the music to wait for it.

	python-osc reaches a bundle's timetag by calling ``time.sleep()`` - inside
	``datagram_received``, on the event loop, which is the loop the MIDI clock
	runs on.  A bundle dated half a second ahead stopped the piece for half a
	second and then burst the missed notes out together; one dated an hour
	ahead stopped it for an hour, with Ctrl+C held until the end.  It happened
	whatever the address, handled or not, because ``handlers_for_address``
	returns a generator and a generator is always truthy, so the guard meant to
	skip unhandled messages never fired (#3001).

	This parses the packet itself, plays what is due, and gives the rest to
	``loop.call_later``.  Nothing waits.
	"""

	def __init__ (
		self,
		dispatcher: pythonosc.dispatcher.Dispatcher,
		loop: asyncio.AbstractEventLoop,
	) -> None:

		"""Hold the dispatcher to invoke through and the loop to schedule on."""

		self._dispatcher = dispatcher
		self._loop = loop
		self._transport: typing.Optional[asyncio.DatagramTransport] = None
		self._pending: typing.Set[asyncio.TimerHandle] = set()
		self._warned_about_horizon = False

	def connection_made (self, transport: asyncio.BaseTransport) -> None:

		"""Keep the transport, which is how a handler's reply gets back."""

		self._transport = typing.cast(asyncio.DatagramTransport, transport)

	def datagram_received (self, data: bytes, client_address: typing.Tuple[str, int]) -> None:

		"""Split one packet into what is due now and what is due later."""

		try:
			packet = pythonosc.osc_packet.OscPacket(data)
		except pythonosc.osc_packet.ParseError:
			return

		now = time.time()

		for timed in packet.messages:

			ahead = timed.time - now

			if ahead > MAX_TIMETAG_AHEAD_SECONDS:
				if not self._warned_about_horizon:
					self._warned_about_horizon = True
					logger.warning(
						"An OSC message is timed %.0f seconds ahead, past the %.0f-second "
						"limit - playing it now. Check the sending machine's clock.",
						ahead, MAX_TIMETAG_AHEAD_SECONDS,
					)
				ahead = 0.0

			if ahead <= 0.0:
				self._invoke(timed.message, client_address)
				continue

			handle = self._loop.call_later(ahead, self._fire, timed.message, client_address)
			self._pending.add(handle)

	def _fire (self, message: typing.Any, client_address: typing.Tuple[str, int]) -> None:

		"""A message whose timetag has come round."""

		self._pending = {handle for handle in self._pending if not handle.cancelled()}

		self._invoke(message, client_address)

	def _invoke (self, message: typing.Any, client_address: typing.Tuple[str, int]) -> None:

		"""Hand one message to every handler mapped to its address, and reply if asked."""

		for handler in self._dispatcher.handlers_for_address(message.address):

			try:
				result = handler.invoke(client_address, message)
			except Exception:
				# One bad handler must not take the OSC server down with it, and
				# certainly must not reach the clock.
				logger.exception("OSC handler for %s failed", message.address)
				continue

			if result is not None:
				self._reply(result, client_address)

	def _reply (self, result: typing.Any, client_address: typing.Tuple[str, int]) -> None:

		"""Send a handler's return value back, the way python-osc's own server does."""

		if self._transport is None:
			return

		parts = list(result) if isinstance(result, tuple) else [result]
		builder = pythonosc.osc_message_builder.OscMessageBuilder(address = parts[0])

		for argument in parts[1:]:
			builder.add_arg(argument)

		self._transport.sendto(builder.build().dgram, client_address)

	def close (self) -> None:

		"""Drop every message still waiting for its timetag.

		A stopped composition must not have an OSC message fire into it a
		minute later.
		"""

		for handle in self._pending:
			handle.cancel()

		self._pending.clear()


class OscServer:

	"""Async OSC server/client for bi-directional communication."""

	def __init__ (
		self,
		composition: "Composition",
		receive_port: int = 9000,
		send_port: int = 9001,
		send_host: str = "127.0.0.1",
		receive_host: str = "127.0.0.1"
	) -> None:

		"""
		Wire up the OSC ports and built-in control handlers; call start() to begin listening.
		"""

		self._composition = composition
		self._receive_port = receive_port
		self._receive_host = receive_host
		self._send_port = send_port
		self._send_host = send_host

		self._protocol: typing.Optional[_TimetagProtocol] = None
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

		# Server for receiving.  Not python-osc's own AsyncIOOSCUDPServer: its
		# protocol sleeps on the loop to honour a bundle's timetag, which stops
		# the clock (#3001).  _TimetagProtocol schedules instead.
		loop = asyncio.get_running_loop()

		transport, protocol = await loop.create_datagram_endpoint(
			lambda: _TimetagProtocol(self._dispatcher, loop),
			local_addr = (self._receive_host, self._receive_port),
		)

		self._transport = transport
		self._protocol = protocol

		# Name the interface, not just the port: "this machine only" and
		# "anything that can reach this machine" are very different things to
		# have just switched on, and only one of them is the default.
		reach = "this machine only" if self._receive_host in ("127.0.0.1", "localhost", "::1") else "the network"

		logger.info(
			f"OSC listening on {self._receive_host}:{self._receive_port} ({reach}), "
			f"sending to {self._send_host}:{self._send_port}"
		)


	async def stop (self) -> None:

		"""Stop the OSC server and close the outgoing client socket."""

		if self._protocol is not None:
			# Anything still waiting for its timetag is dropped: a stopped
			# composition must not be played into a minute later.
			self._protocol.close()
			self._protocol = None

		if self._transport:
			self._transport.close()
			self._transport = None
			logger.info("OSC server stopped")

		if self._client is not None:
			# python-osc's SimpleUDPClient owns a raw socket; close it so a
			# stopped composition doesn't keep a zombie sender alive.
			try:
				self._client._sock.close()
			except (AttributeError, OSError):
				pass
			self._client = None


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

		"""
		Set the composition tempo from an incoming ``/bpm <int>`` message.
		"""

		if not args:
			return

		try:
			bpm = int(args[0])
			self._composition.set_bpm(bpm)
		# int() raises OverflowError for an infinite argument, which this missed,
		# so /bpm inf was logged as a traceback rather than refused (#3561).
		except (ValueError, TypeError, OverflowError):
			logger.warning(f"Invalid OSC BPM argument: {args[0]}")

	def _handle_mute (self, address: str, *args: typing.Any) -> None:

		"""
		Silence the pattern named in an incoming ``/mute/<name>`` message.
		"""

		# address is like /mute/drums
		parts = address.split("/")
		if len(parts) >= 3:
			name = parts[2]
			self._composition.mute(name)

	def _handle_unmute (self, address: str, *args: typing.Any) -> None:

		"""
		Bring back the pattern named in an incoming ``/unmute/<name>`` message.
		"""

		parts = address.split("/")
		if len(parts) >= 3:
			name = parts[2]
			self._composition.unmute(name)

	def _handle_data (self, address: str, *args: typing.Any) -> None:

		"""
		Update a composition.data value from an incoming ``/data/<key> <value>`` message, preserving the existing numeric type.
		"""

		# address is like /data/intensity
		if not args:
			return

		parts = address.split("/")
		if len(parts) >= 3:
			key = parts[2]
			val = args[0]
			if key in self._composition.data:
				existing = self._composition.data[key]
				if isinstance(existing, (float, int)):
					try:
						val = float(val) if isinstance(existing, float) else int(val)
					except (ValueError, TypeError):
						logger.warning(f"OSC /data: failed to cast {val} to numeric for key {key}")
						return

			self._composition.data[key] = val
