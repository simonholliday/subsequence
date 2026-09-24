"""TCP eval server for live coding a running composition.

Start the server by calling ``composition.live()`` before ``composition.play()``.
The server listens on a TCP port (default 5555) and accepts Python code from any
source - the bundled REPL client, an editor plugin, or a raw socket connection.

Protocol
────────
Messages are delimited by ``\\x04`` (ASCII EOT). The server reads until it
receives this sentinel, evaluates the code, and sends the result (or error
traceback) followed by ``\\x04``.  Messages may be sent back to back without
waiting for each answer, and each is answered in turn; an empty message is
answered ``OK``.

While an answer is pending, a client may send ``\\x03`` (ASCII ETX, the byte
Ctrl+C types) to stop the code the server is running, and the answer then
reads ``KeyboardInterrupt``.  The performance carries on.  An ETX that
arrives with nothing running does nothing, and is never read as code.  This
works on Unix, where the server can interrupt its own main thread.

Each message is a declaration pass in its own right, run on the loop that owns
the composition: whatever it declares afresh is brought in at the next whole
multiple of its own length, whatever it re-declares is swapped in place, and
what it leaves behind is remembered under ``REPL_SOURCE`` so a watched file's
save never tears the performer's own work down.

Security note: the server binds to ``localhost`` only and is opt-in via
``composition.live()``. It executes arbitrary Python in the composition's
process - this is intentional for live coding. Any process on the same
machine that can connect to the port has full code execution in this
process, so do not enable live mode on shared or multi-user hosts, and
never expose the port to a network.
"""

import asyncio
import contextlib
import logging
import os
import select
import signal
import socket
import threading
import traceback
import types
import typing

if typing.TYPE_CHECKING:
	from subsequence.composition import Composition


logger = logging.getLogger(__name__)

SENTINEL = b"\x04"

# The longest message the server will wait for, sentinel included.  asyncio's
# default is 64 KiB, which a pasted composition file can pass; past this a
# connection is closed rather than buffered without end.
MESSAGE_LIMIT = 16 * 1024 * 1024

# What the REPL declares is filed under this name, so a watched file's save
# removes only what that file stopped declaring and never the performer's
# typing (#2999).
REPL_SOURCE = "<repl>"

# The signals a performance ends on (see run_until_stopped).
STOPPING_SIGNALS = (signal.SIGINT, signal.SIGTERM)

# What a client sends to stop the code the server is running: ETX, the byte
# Ctrl+C types (#3371).
INTERRUPT = b"\x03"

# The signal that request arrives as.  asyncio has no handler for it, so it
# stops the typed code and nothing else - the music carries on.  Unix only:
# elsewhere there is no SIGUSR1, and no way to interrupt the main thread.
REPL_INTERRUPT: typing.Optional[signal.Signals] = getattr(signal, "SIGUSR1", None) if hasattr(signal, "pthread_kill") else None


class Interrupted (BaseException):

	"""A stopping signal arrived while performer code held the event loop, and stopped that code.

	A BaseException, as KeyboardInterrupt is, so the ``except Exception`` that
	reports a submission's own errors does not swallow it.
	"""

	def __init__ (self, number: int) -> None:

		"""Remember which signal it was."""

		super().__init__(number)
		self.number = number


@contextlib.contextmanager
def stop_signals_reach_the_code () -> typing.Iterator[None]:

	"""While performer code holds the event loop, let Ctrl+C and SIGTERM stop it, then act as usual.

	Typed code runs on the event loop (#2999), and a performance hears SIGINT
	and SIGTERM through ``loop.add_signal_handler``, whose callbacks run on
	that same loop.  So code that never returned - ``while True: pass``, or a
	sleep - stopped the music AND left the process deaf to both signals: only
	SIGKILL ended it, with every sounding note left hanging (#3367).

	For as long as the code runs, each of those signals raises
	:class:`Interrupted` inside it instead.  Once the code has stopped, the
	signal goes on to whatever it would have reached, exactly once: under
	``play()`` that is the handler that ends the performance, cleanly.  (asyncio
	has already queued the wake-up that signal made, so its own Python-level
	handler, which does nothing, is the one called here.)

	The REPL's own Ctrl+C (:data:`REPL_INTERRUPT`, #3371) stops the code the
	same way, wherever the server holds that signal.  Handed on, it reaches
	only the server's own handler, which does nothing: the performance
	carries on.  Anywhere the server does not hold it, it is left alone.

	The handlers are lent to the code, not given: whatever the code itself
	does to them is undone as it finishes, so typed code cannot leave the
	performance unable to stop.

	Signals are only ever delivered to the main thread, so on any other thread
	this changes nothing.
	"""

	if threading.current_thread() is not threading.main_thread():
		yield
		return

	numbers = list(STOPPING_SIGNALS)

	if REPL_INTERRUPT is not None and signal.getsignal(REPL_INTERRUPT) is _absorb:
		numbers.append(REPL_INTERRUPT)

	previous = {number: signal.getsignal(number) for number in numbers}

	# A handler installed from outside Python reads as None and cannot be put back.
	swapped = [number for number, handler in previous.items() if handler is not None]
	received: typing.List[signal.Signals] = []

	def _interrupt (number: int, frame: typing.Optional[types.FrameType]) -> None:
		received.append(signal.Signals(number))
		raise Interrupted(number)

	for number in swapped:
		signal.signal(number, _interrupt)

	try:
		yield

	finally:

		for number in swapped:
			signal.signal(number, previous[number])

		for arrived in dict.fromkeys(received):

			handler = previous[arrived]

			if handler == signal.SIG_DFL:
				signal.raise_signal(arrived)
			elif callable(handler):
				handler(arrived, None)


def _absorb (number: int, frame: typing.Optional[types.FrameType]) -> None:

	"""Hold :data:`REPL_INTERRUPT` for as long as the server runs, so one that lands late does nothing.

	Its default action is to end the process, and a client's request can arrive
	just as the code it meant to stop finishes of its own accord.
	"""


class _InterruptWatcher (threading.Thread):

	"""Watches one client while its typed code holds the loop, and stops that code when the client asks.

	The loop cannot hear the request, because the code is holding it.  So this
	thread peeks at the client's socket through a second handle, never taking
	anything from it: whatever is there is still there for the loop to read
	once the code has stopped, and the server drops the ETX then.  Each new
	ETX sends :data:`REPL_INTERRUPT` to the main thread itself, because only a
	signal to that thread breaks into a blocking call such as ``sleep``.
	"""

	def __init__ (self, fileno: int) -> None:

		"""Take a second handle on the client's socket, the thread to interrupt, and a pipe to be woken by."""

		super().__init__(name="live-interrupt-watcher", daemon=True)

		self._peek = socket.socket(fileno=os.dup(fileno))
		self._main = threading.main_thread().ident

		# finish() runs on the loop, so it must not wait out a poll: a byte down
		# this pipe ends the watch at once.  Polling instead held every typed
		# line's answer, and the clock with it, for up to a poll's length.
		self._wake_read, self._wake_write = os.pipe()

	def run (self) -> None:

		"""Peek until the code finishes, interrupting once for each ETX that arrives."""

		seen = 0

		try:

			while True:

				readable, _, _ = select.select([self._peek.fileno(), self._wake_read], [], [])

				if self._wake_read in readable:
					return

				try:
					pending = self._peek.recv(65536, socket.MSG_PEEK)
				except OSError:
					return

				# The client has gone; the loop will find that out for itself.
				if not pending:
					return

				requests = pending.count(INTERRUPT)

				if requests > seen and REPL_INTERRUPT is not None and self._main is not None:
					seen = requests
					signal.pthread_kill(self._main, REPL_INTERRUPT)

				# What is pending stays pending until the loop reads it, so the
				# socket stays readable: wait on the pipe a moment rather than spin.
				woken, _, _ = select.select([self._wake_read], [], [], 0.05)

				if woken:
					return

		finally:
			self._peek.close()
			os.close(self._wake_read)

	def finish (self) -> None:

		"""Stop watching, now that the code has finished."""

		os.write(self._wake_write, b"\x00")
		self.join(timeout = 1.0)
		os.close(self._wake_write)


class LiveServer:

	"""Async TCP server that evaluates Python code inside a running composition."""

	def __init__ (self, composition: "Composition", port: int = 5555) -> None:

		"""Store a reference to the composition and the port to listen on."""

		self._composition = composition
		self._port = port
		self._server: typing.Optional[asyncio.AbstractServer] = None
		self._namespace: typing.Dict[str, typing.Any] = {}
		self._clients: typing.Set[asyncio.StreamWriter] = set()

		# What REPL_INTERRUPT meant before the server held it, for stop() to put back.
		self._holding_repl_interrupt = False
		self._repl_interrupt_before: typing.Any = None

	async def start (self) -> None:

		"""Start listening for connections on localhost."""

		self._namespace = self._composition._build_live_namespace()

		self._server = await asyncio.start_server(
			self._handle_connection,
			host = "127.0.0.1",
			port = self._port,
			limit = MESSAGE_LIMIT
		)

		# A client can stop its own typed code only where the server can hold the
		# signal that asks, which is on Unix and on the main thread.
		if REPL_INTERRUPT is not None and threading.current_thread() is threading.main_thread():
			self._repl_interrupt_before = signal.signal(REPL_INTERRUPT, _absorb)
			self._holding_repl_interrupt = True

		# port=0 asks the system for a free port, and that port is the one to name:
		# the log said 0, which no client can connect to (#3554).
		self._port = self._server.sockets[0].getsockname()[1]

		logger.info(f"Live server listening on 127.0.0.1:{self._port}")

	async def stop (self) -> None:

		"""Close the server, and every client still connected, then wait for it to shut down.

		From Python 3.12.1 ``wait_closed()`` waits for every open connection, and
		a REPL left connected in another terminal never closes by itself: Ctrl+C
		silenced the music and ``play()`` then waited for that client to quit
		(#3365).  ``Server.close_clients()`` would do this from Python 3.13; the
		server keeps its own list so it works on every version this supports.
		"""

		if self._server is not None:
			self._server.close()

			for writer in list(self._clients):
				writer.close()

			await self._server.wait_closed()
			self._server = None
			logger.info("Live server stopped")

		if self._holding_repl_interrupt and REPL_INTERRUPT is not None and threading.current_thread() is threading.main_thread():
			signal.signal(REPL_INTERRUPT, self._repl_interrupt_before)
			self._holding_repl_interrupt = False

	async def _handle_connection (self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:

		"""Handle a single client connection with an eval/exec loop."""

		peer = writer.get_extra_info("peername")
		logger.info(f"Live client connected: {peer}")
		self._clients.add(writer)

		try:

			# A client that connected just as stop() began is not in the list it
			# closed, so it leaves here instead of waiting to be read from.
			while self._server is not None and self._server.is_serving():

				code = await self._read_message(reader)

				if code is None:
					break

				response = await self._submit(code, writer) if code else "OK"
				writer.write(response.encode() + SENTINEL)
				await writer.drain()

		except ConnectionResetError:
			logger.info(f"Live client disconnected (reset): {peer}")

		except Exception as exc:
			logger.warning(f"Live connection error: {exc}")

		finally:
			self._clients.discard(writer)
			writer.close()
			try:
				await writer.wait_closed()
			except Exception:
				pass
			logger.info(f"Live client disconnected: {peer}")

	async def _read_message (self, reader: asyncio.StreamReader) -> typing.Optional[str]:

		"""Read one message, up to its sentinel, or None once the client has gone.

		Whatever follows the sentinel stays in the reader for the next call, so
		messages sent back to back, or one split across two sends, each arrive
		whole.  This used to read in chunks and keep only what came before the
		first sentinel in each, so a second message in the same read was lost and
		its client waited forever, and an empty message read as the client
		leaving (#3364).  Bytes after the last sentinel when the client closes are
		a message it never finished, and are dropped.
		"""

		try:
			raw = await reader.readuntil(SENTINEL)
		except (asyncio.IncompleteReadError, ConnectionResetError):
			return None

		# An ETX is a request to stop code that was running, never code itself,
		# and by now that code has finished either way (#3371).
		return raw[:-len(SENTINEL)].replace(INTERRUPT, b"").decode("utf-8", errors = "replace").strip()

	@contextlib.contextmanager
	def _watching (self, client: typing.Optional[asyncio.StreamWriter]) -> typing.Iterator[None]:

		"""While typed code runs, listen to the client that sent it for a request to stop it (#3371).

		Only while the server really holds :data:`REPL_INTERRUPT` - the handler
		in place now, not what the server set at start, since typed code can
		replace it.  Anywhere else, sending it would end the process instead.
		"""

		transport_socket = client.get_extra_info("socket") if client is not None else None
		held = REPL_INTERRUPT is not None and signal.getsignal(REPL_INTERRUPT) is _absorb

		if transport_socket is None or not held or threading.current_thread() is not threading.main_thread():
			yield
			return

		watcher = _InterruptWatcher(transport_socket.fileno())
		watcher.start()

		try:
			yield
		finally:
			watcher.finish()

	async def _submit (self, code: str, client: typing.Optional[asyncio.StreamWriter] = None) -> str:

		"""Play one typed submission into the composition, and start what it added.

		A line typed at the REPL is a declaration in its own right, and is
		treated as one - the same pass a file save gets.  What it declares
		afresh comes in at the next whole multiple of its own length, so a
		new part lands on a bar line rather than wherever the typing fell
		(:meth:`Composition._next_start_pulse`), and re-declaring a part that
		is already playing swaps its body in place instead of standing a
		second copy beside it.

		Until #2999 a submission was run on a worker thread and then left
		alone: a new ``@composition.pattern`` was acknowledged with ``OK``
		and never heard, and a re-declared ``layer()`` came back as a second
		layer with a ``#2`` on its name.  Running it here, on the loop that
		owns the pattern registry and the scheduler's queue, is what lets the
		declaration be acted on - at the cost of holding the clock for as
		long as the submission runs, which is the same bargain a watched file
		save already makes.

		What the REPL declares is remembered under its own name, so a later
		file save tears down its own deletions and leaves the performer's
		typing alone.

		While it runs, ``client`` - the connection it came from - can stop it
		with an ETX, which is what the REPL sends for Ctrl+C (#3371).
		"""

		composition = self._composition

		# Each submission is a fresh declaration pass, exactly as a save is.
		# Names left over from startup are what turned a re-declared layer
		# into a second one, because the name it would have reused was still
		# taken.
		composition._declared_names = set()
		before = composition._pending_snapshot()

		with self._watching(client):
			response, declared = self._evaluate(code)

		# A submission that raised, or was interrupted, starts nothing - and
		# neither does the next one on its behalf (#3377).
		if not declared:
			composition._roll_back_pending(before)
			return response

		# Bring anything newly declared into rotation.  A part that was
		# already playing hot-swapped inside the exec and is not here.
		await composition._activate_new_pending_patterns()

		composition._source_declared[REPL_SOURCE] = (
			composition._source_declared.get(REPL_SOURCE, set()) | composition._declared_names
		)

		return response

	def _evaluate (self, code: str) -> typing.Tuple[str, bool]:

		"""Validate, then eval/exec the code string.

		Returns the text to send back, and whether the code ran to completion -
		a submission that raised has declared nothing worth scheduling, and its
		half-built patterns must not be started.
		"""

		# Validate syntax before executing - never run invalid code.
		try:
			statement = compile(code, "<live>", "exec")
		except SyntaxError:
			return traceback.format_exc(), False

		# An expression answers with its value, and anything else runs as a
		# statement.  Which one it is gets settled here, before anything runs,
		# so the code runs exactly once.  This used to try eval() and fall back
		# to exec() on any SyntaxError, so an expression that raised one while
		# RUNNING - compile() or eval() on bad text - was run a second time as a
		# statement, side effects and all (#3366).
		try:
			expression: typing.Optional[types.CodeType] = compile(code, "<live>", "eval")
		except SyntaxError:
			expression = None

		try:

			with stop_signals_reach_the_code():

				try:

					if expression is not None:
						result = eval(expression, self._namespace)
						return (repr(result) if result is not None else "OK"), True

					exec(statement, self._namespace)
					return "OK", True

				except SystemExit:
					return "SystemExit is not allowed in live mode.", False
				except Exception:
					return traceback.format_exc(), False

		except Interrupted as interrupted:

			# The REPL's own Ctrl+C answers as Python's REPL does; anything
			# else is the performance being stopped.
			if interrupted.number == REPL_INTERRUPT:
				return "KeyboardInterrupt", False

			return f"Interrupted by {signal.Signals(interrupted.number).name}.", False
