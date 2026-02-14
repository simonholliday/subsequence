import typing

import mido
import pytest


class FakeMidiOut:

	"""Minimal MIDI output stub for tests."""

	def send (self, message: mido.Message) -> None:

		"""Ignore outgoing MIDI messages."""

		return None


	def close (self) -> None:

		"""No-op close for the fake device."""

		return None


	def panic (self) -> None:

		"""No-op panic for the fake device."""

		return None


	def reset (self) -> None:

		"""No-op reset for the fake device."""

		return None


class FakeMidiIn:

	"""Minimal MIDI input stub for tests."""

	def __init__ (self, callback: typing.Optional[typing.Callable] = None) -> None:

		"""Store the callback for injecting test messages."""

		self.callback = callback

	def close (self) -> None:

		"""No-op close for the fake device."""

		return None

	def inject (self, message: mido.Message) -> None:

		"""Simulate receiving a MIDI message by calling the stored callback."""

		if self.callback is not None:
			self.callback(message)


def _fake_get_output_names () -> list[str]:

	"""Return a fixed list of MIDI output names for tests."""

	return ["Dummy MIDI"]


def _fake_open_output (name: str) -> FakeMidiOut:

	"""Return a fake MIDI output regardless of the name."""

	return FakeMidiOut()


# Module-level reference so tests can access the most recently created FakeMidiIn.
_current_fake_input: typing.Optional[FakeMidiIn] = None


def _fake_get_input_names () -> list[str]:

	"""Return a fixed list of MIDI input names for tests."""

	return ["Dummy MIDI"]


def _fake_open_input (name: str, callback: typing.Optional[typing.Callable] = None) -> FakeMidiIn:

	"""Return a fake MIDI input regardless of the name."""

	global _current_fake_input
	fake = FakeMidiIn(callback=callback)
	_current_fake_input = fake
	return fake


@pytest.fixture
def patch_midi (monkeypatch: pytest.MonkeyPatch) -> None:

	"""Patch mido to use fake MIDI output and input for all tests that need it."""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)
	monkeypatch.setattr(mido, "get_input_names", _fake_get_input_names)
	monkeypatch.setattr(mido, "open_input", _fake_open_input)
