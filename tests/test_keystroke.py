"""Unit tests for subsequence.keystroke.KeystrokeListener.

All terminal interaction (termios/tty/select/stdin) is mocked so the tests
run headless: they pin the listener's lifecycle contract — the thread joins
on stop() and the saved terminal settings are always restored.
"""

import select
import sys
import termios
import threading
import tty
import typing

import pytest

import subsequence.keystroke


_SENTINEL_SETTINGS: typing.List[typing.Any] = ["sentinel-terminal-settings"]


class _FakeStdin:
    """Minimal stdin stand-in: a fileno and a read that never produces keys."""

    def fileno(self) -> int:
        return 99

    def read(self, n: int) -> str:
        return ""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def fake_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.List[typing.Tuple[int, int, typing.Any]]:
    """Mock the terminal layer and return a recorder of tcsetattr calls."""

    restored: typing.List[typing.Tuple[int, int, typing.Any]] = []

    monkeypatch.setattr(subsequence.keystroke, "HOTKEYS_SUPPORTED", True)
    monkeypatch.setattr(subsequence.keystroke, "HOTKEYS_UNAVAILABLE_REASON", None)

    monkeypatch.setattr(termios, "tcgetattr", lambda fd: _SENTINEL_SETTINGS)
    monkeypatch.setattr(
        termios,
        "tcsetattr",
        lambda fd, when, settings: restored.append((fd, when, settings)),
    )
    monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(
        select, "select", lambda rlist, wlist, xlist, timeout=None: ([], [], [])
    )
    monkeypatch.setattr(sys, "stdin", _FakeStdin())

    return restored


def test_start_stop_joins_thread_and_restores_terminal(
    fake_terminal: typing.List[typing.Tuple[int, int, typing.Any]],
) -> None:
    """stop() joins the listener thread and restores the original termios settings."""

    listener = subsequence.keystroke.KeystrokeListener()
    listener.start()

    assert listener.active is True
    assert isinstance(listener._thread, threading.Thread)

    listener.stop()

    # The background thread must have exited (joined), not been abandoned.
    assert listener._thread is not None
    assert not listener._thread.is_alive()
    assert listener.active is False

    # The terminal was restored with the exact settings tcgetattr returned.
    assert (99, termios.TCSADRAIN, _SENTINEL_SETTINGS) in fake_terminal


def test_stop_without_start_is_noop(
    fake_terminal: typing.List[typing.Tuple[int, int, typing.Any]],
) -> None:
    """stop() on a never-started listener does nothing and touches no terminal state."""

    listener = subsequence.keystroke.KeystrokeListener()
    listener.stop()

    assert listener._thread is None
    assert listener.active is False
    assert fake_terminal == []
