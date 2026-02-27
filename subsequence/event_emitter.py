import asyncio
import typing


CallbackType = typing.Callable[..., typing.Any]


class EventEmitter:

	"""
	A simple event emitter supporting sync and async callbacks.
	"""

	def __init__ (self) -> None:

		"""
		Initialize an empty event registry.
		"""

		self._listeners: typing.Dict[str, typing.List[CallbackType]] = {}


	def on (self, event_name: str, callback: CallbackType) -> None:

		"""
		Register a callback for an event name.
		"""

		if event_name not in self._listeners:
			self._listeners[event_name] = []

		self._listeners[event_name].append(callback)

	def off (self, event_name: str, callback: CallbackType) -> None:

		"""
		Unregister a previously registered callback.

		Raises ``ValueError`` if the callback is not registered for the event.
		"""

		if event_name not in self._listeners or callback not in self._listeners[event_name]:
			raise ValueError(f"Callback not registered for event {event_name!r}")

		self._listeners[event_name].remove(callback)


	def emit_sync (self, event_name: str, *args: typing.Any, **kwargs: typing.Any) -> None:

		"""
		Emit an event and call non-async listeners immediately.
		"""

		if event_name not in self._listeners:
			return

		for callback in self._listeners[event_name]:

			if asyncio.iscoroutinefunction(callback):
				raise ValueError("Async callback encountered in emit_sync")

			callback(*args, **kwargs)


	async def emit_async (self, event_name: str, *args: typing.Any, **kwargs: typing.Any) -> None:

		"""
		Emit an event and await async listeners.
		"""

		if event_name not in self._listeners:
			return

		tasks: typing.List[typing.Awaitable[typing.Any]] = []

		for callback in self._listeners[event_name]:

			if asyncio.iscoroutinefunction(callback):
				tasks.append(callback(*args, **kwargs))

			else:
				callback(*args, **kwargs)

		if tasks:
			await asyncio.gather(*tasks)
