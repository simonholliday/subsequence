"""TCP eval server for live coding a running composition.

Start the server by calling ``composition.live()`` before ``composition.play()``.
The server listens on a TCP port (default 5555) and accepts Python code from any
source — the bundled REPL client, an editor plugin, or a raw socket connection.

Protocol
────────
Messages are delimited by ``\\x04`` (ASCII EOT). The server reads until it
receives this sentinel, evaluates the code, and sends the result (or error
traceback) followed by ``\\x04``.

Security note: the server binds to ``localhost`` only. It executes arbitrary
Python in the composition's process — this is intentional for live coding, but
the port should not be exposed to untrusted networks.
"""

import asyncio
import builtins
import logging
import traceback
import typing


logger = logging.getLogger(__name__)

SENTINEL = b"\x04"


class LiveServer:

	"""Async TCP server that evaluates Python code inside a running composition."""

	def __init__ (self, composition: typing.Any, port: int = 5555) -> None:

		"""Store a reference to the composition and the port to listen on."""

		self._composition = composition
		self._port = port
		self._server: typing.Optional[asyncio.AbstractServer] = None
		self._namespace: typing.Dict[str, typing.Any] = {}

	async def start (self) -> None:

		"""Start listening for connections on localhost."""

		self._namespace = self._build_namespace()

		self._server = await asyncio.start_server(
			self._handle_connection,
			host = "127.0.0.1",
			port = self._port
		)

		logger.info(f"Live server listening on 127.0.0.1:{self._port}")

	async def stop (self) -> None:

		"""Close the server and wait for it to shut down."""

		if self._server is not None:
			self._server.close()
			await self._server.wait_closed()
			self._server = None
			logger.info("Live server stopped")

	async def _handle_connection (self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:

		"""Handle a single client connection with an eval/exec loop."""

		peer = writer.get_extra_info("peername")
		logger.info(f"Live client connected: {peer}")

		try:

			while True:

				code = await self._read_message(reader)

				if code is None:
					break

				response = await asyncio.to_thread(self._evaluate, code)
				writer.write(response.encode() + SENTINEL)
				await writer.drain()

		except ConnectionResetError:
			logger.info(f"Live client disconnected (reset): {peer}")

		except Exception as exc:
			logger.warning(f"Live connection error: {exc}")

		finally:
			writer.close()
			try:
				await writer.wait_closed()
			except Exception:
				pass
			logger.info(f"Live client disconnected: {peer}")

	async def _read_message (self, reader: asyncio.StreamReader) -> typing.Optional[str]:

		"""Read bytes until the sentinel or EOF, returning the decoded string or None."""

		chunks: typing.List[bytes] = []

		while True:

			try:
				chunk = await reader.read(4096)
			except ConnectionResetError:
				return None

			if not chunk:
				return None

			if SENTINEL in chunk:
				before, _, _ = chunk.partition(SENTINEL)
				chunks.append(before)
				break

			chunks.append(chunk)

		data = b"".join(chunks).decode("utf-8").strip()

		return data if data else None

	def _evaluate (self, code: str) -> str:

		"""Validate, then eval/exec the code string. Return the result or error traceback."""

		# Validate syntax before executing — never run invalid code.
		try:
			compile(code, "<live>", "exec")
		except SyntaxError:
			return traceback.format_exc()

		# Try as an expression first (returns a value).
		try:
			result = eval(compile(code, "<live>", "eval"), self._namespace)
			return repr(result) if result is not None else "OK"
		except SyntaxError:
			pass
		except SystemExit:
			return "SystemExit is not allowed in live mode."
		except Exception:
			return traceback.format_exc()

		# Fall back to statement execution.
		try:
			exec(compile(code, "<live>", "exec"), self._namespace)
			return "OK"
		except SystemExit:
			return "SystemExit is not allowed in live mode."
		except Exception:
			return traceback.format_exc()

	def _build_namespace (self) -> typing.Dict[str, typing.Any]:

		"""Build the namespace dict with safe builtins that can't block the sequencer."""

		import subsequence

		safe_builtins = {name: getattr(builtins, name) for name in dir(builtins)}

		blocked = {"help", "input", "breakpoint", "exit", "quit"}

		for name in blocked:
			safe_builtins[name] = _blocked(name)

		return {
			"__builtins__": safe_builtins,
			"composition": self._composition,
			"subsequence": subsequence,
		}


def _blocked (name: str) -> typing.Callable:

	"""Return a function that raises RuntimeError when called."""

	def _raise (*args: typing.Any, **kwargs: typing.Any) -> None:
		raise RuntimeError(f"{name}() is not available in live mode — it would block the sequencer.")

	_raise.__name__ = name
	_raise.__qualname__ = name

	return _raise
