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


def _fake_get_output_names () -> list[str]:

	"""Return a fixed list of MIDI output names for tests."""

	return ["Dummy MIDI"]


def _fake_open_output (name: str) -> FakeMidiOut:

	"""Return a fake MIDI output regardless of the name."""

	return FakeMidiOut()


@pytest.fixture
def patch_midi (monkeypatch: pytest.MonkeyPatch) -> None:

	"""Patch mido to use fake MIDI output for all tests that need it."""

	monkeypatch.setattr(mido, "get_output_names", _fake_get_output_names)
	monkeypatch.setattr(mido, "open_output", _fake_open_output)
