import asyncio
import inspect
import logging
import typing


logger = logging.getLogger(__name__)

CallbackType = typing.Callable[..., typing.Any]


class EventEmitter:
    """
    A simple event emitter supporting sync and async callbacks.
    """

    def __init__(self) -> None:
        """
        Initialize an empty event registry.
        """

        self._listeners: typing.Dict[str, typing.List[CallbackType]] = {}

    def on(self, event_name: str, callback: CallbackType) -> None:
        """
        Register a callback for an event name.
        """

        if event_name not in self._listeners:
            self._listeners[event_name] = []

        self._listeners[event_name].append(callback)

    def off(self, event_name: str, callback: CallbackType) -> None:
        """
        Unregister a previously registered callback.

        Raises ``ValueError`` if the callback is not registered for the event.
        """

        if (
            event_name not in self._listeners
            or callback not in self._listeners[event_name]
        ):
            raise ValueError(f"Callback not registered for event {event_name!r}")

        self._listeners[event_name].remove(callback)

    def emit_sync(
        self, event_name: str, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        """
        Emit an event and call non-async listeners immediately.
        """

        if event_name not in self._listeners:
            return

        for callback in self._listeners[event_name]:
            if inspect.iscoroutinefunction(callback):
                raise ValueError("Async callback encountered in emit_sync")

            result = callback(*args, **kwargs)

            # Catch async-callable objects too (async __call__ fails the
            # iscoroutinefunction check but still returns an awaitable).
            if inspect.isawaitable(result):
                typing.cast(typing.Coroutine, result).close()
                raise ValueError("Async callback encountered in emit_sync")

    async def emit_async(
        self, event_name: str, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        """
        Emit an event, awaiting async listeners.

        One raising listener never silences the others: sync exceptions are
        logged and the remaining listeners still run, and async listeners are
        gathered with their exceptions logged individually.
        """

        if event_name not in self._listeners:
            return

        tasks: typing.List[typing.Awaitable[typing.Any]] = []

        for callback in self._listeners[event_name]:
            # Calling first and checking the RESULT handles both coroutine
            # functions and async-callable objects (async __call__), which
            # iscoroutinefunction misses.
            try:
                result = callback(*args, **kwargs)
            except Exception:
                logger.exception(
                    "Listener for %r raised - continuing with remaining listeners",
                    event_name,
                )
                continue

            if inspect.isawaitable(result):
                tasks.append(result)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for outcome in results:
                if isinstance(outcome, BaseException):
                    logger.error(
                        "Async listener for %r raised", event_name, exc_info=outcome
                    )
