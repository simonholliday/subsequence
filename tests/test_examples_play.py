"""Every example runs the way a musician runs it, and plays (#3041).

Nothing ran ``examples/``, so an example could go on advertising an API that had moved: the Direct
Pattern API was broken for two days while ``demo_advanced.py`` showed it off (#2959), and
``frozen.py`` passed ``harmony()`` the retired ``gravity=`` for three days, until this test.

Each runs as ``__main__``, as ``python examples/<name>.py`` runs it, with the one call that never
returns replaced: ``play()`` renders four bars, and the Direct Pattern API's ``run_until_stopped()``
runs its sequencer in render mode.  A second pass plays 128 bars on a fixed seed, through every
section of each form, and fails on a silent bar (#3506).  A pattern that raises is logged rather than raised, and iss.py
keeps going when a fetch fails, so any warning fails an example too, logged or raised - every
example runs clean today, and a warning is how the next rename will show.  Nothing reaches a device (the fake backend, and a render opens
nothing), the network (a socket refuses to connect; ``iss.py`` gets a stand-in for ``requests``) or
a Link session (``link()`` is replaced, and recorded).
"""

import logging
import pathlib
import socket
import sys
import types
import typing
import warnings

import mido
import pytest

import subsequence
import subsequence.composition
import subsequence.form_state


EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

BARS = 4

# Loaded by another example, which needs to be running for it to mean anything.
_LOADED_BY = {"live_patterns.py": "live_init.py"}


def _names () -> typing.List[str]:

	names = sorted(path.name for path in EXAMPLES.glob("*.py") if path.name not in _LOADED_BY)

	assert len(names) >= 12, f"only {len(names)} examples found"

	return names


# Where the station is on each fetch, in turn: iss.py's tempo follows the latitude, and its harmony
# changes style between daylight and eclipse.
_ORBIT = [(30.0, "daylight"), (51.0, "eclipsed"), (-51.0, "eclipsed"), (0.0, "daylight")]


class _Telemetry:

	"""What api.wheretheiss.at answers: iss.py's stand-in for a fetch."""

	def __init__ (self, latitude: float, visibility: str) -> None:

		self.latitude = latitude
		self.visibility = visibility

	def json (self) -> typing.Dict[str, typing.Any]:

		return {
			"latitude": self.latitude, "longitude": -60.0, "altitude": 420.0, "velocity": 27600.0,
			"visibility": self.visibility, "footprint": 4500.0, "solar_lat": 10.0, "solar_lon": 45.0,
			"daynum": 2461000.5,
		}


def _play (name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, bars: int = BARS, seed: typing.Optional[int] = None) -> typing.Dict[str, typing.Any]:

	"""Run one example as __main__; what it played, and what it asked for on the way.

	A ``seed`` is given to every Composition the example builds, so a take can be replayed.
	"""

	played: typing.Dict[str, typing.Any] = {"files": [], "linked": 0, "fetches": 0, "sections": set()}

	def refuse (*args: typing.Any, **kwargs: typing.Any) -> None:
		raise OSError("the examples' smoke test does not reach the network")

	def render_instead_of_playing (self: subsequence.Composition) -> None:
		filename = str(tmp_path / f"{name}.mid")
		self.render(bars=bars, filename=filename)
		played["files"].append(filename)

	running = subsequence.composition.run_until_stopped

	async def render_instead_of_running (sequencer: typing.Any) -> None:

		# A Composition's render comes through here too, already rendering.
		if sequencer.render_mode:
			await running(sequencer)
			return

		filename = str(tmp_path / f"{name}.mid")
		sequencer.recording = True
		sequencer.record_filename = filename
		sequencer.render_mode = True
		sequencer.render_bars = bars
		await sequencer.start()
		await sequencer.task
		await sequencer.stop()
		played["files"].append(filename)

	def link_nowhere (self: subsequence.Composition, *args: typing.Any, **kwargs: typing.Any) -> None:
		played["linked"] += 1

	def fetch (url: str, **kwargs: typing.Any) -> _Telemetry:
		latitude, visibility = _ORBIT[played["fetches"] % len(_ORBIT)]
		played["fetches"] += 1
		return _Telemetry(latitude, visibility)

	requests = types.ModuleType("requests")
	requests.get = fetch		# type: ignore[attr-defined]

	building = subsequence.Composition.__init__

	def seeded (self: subsequence.Composition, *args: typing.Any, **kwargs: typing.Any) -> None:
		assert "seed" not in kwargs, "the example seeds itself: give the test its seed instead"
		building(self, *args, seed=seed, **kwargs)

	advancing = subsequence.form_state.FormState.advance

	def advance (self: subsequence.form_state.FormState) -> bool:
		# The section each bar belongs to, the first included: read before and after the step.
		if self._current is not None:
			played["sections"].add(self._current.name)
		moved = advancing(self)
		if self._current is not None:
			played["sections"].add(self._current.name)
		return moved

	monkeypatch.setattr(socket.socket, "connect", refuse)
	monkeypatch.setattr(socket, "create_connection", refuse)
	monkeypatch.setattr(subsequence.Composition, "play", render_instead_of_playing)
	monkeypatch.setattr(subsequence.composition, "run_until_stopped", render_instead_of_running)
	monkeypatch.setattr(subsequence.Composition, "link", link_nowhere)
	monkeypatch.setattr(subsequence.form_state.FormState, "advance", advance)
	monkeypatch.setitem(sys.modules, "requests", requests)
	monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)

	if seed is not None:
		monkeypatch.setattr(subsequence.Composition, "__init__", seeded)

	path = EXAMPLES / name
	namespace: typing.Dict[str, typing.Any] = {"__name__": "__main__", "__file__": str(path)}
	exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)		# noqa: S102

	played["notes"] = []
	played["bars"] = set()

	for filename in played["files"]:

		midi = mido.MidiFile(filename)
		beats_per_bar = next(
			(message.numerator * 4 / message.denominator for track in midi.tracks for message in track if message.type == "time_signature"),
			4.0,
		)

		for track in midi.tracks:
			tick = 0
			for message in track:
				tick += message.time
				if message.type == "note_on" and message.velocity > 0:
					played["notes"].append(message.note)
					played["bars"].add(int(tick // (midi.ticks_per_beat * beats_per_bar)))

	composition = namespace.get("composition") or namespace.get("comp")
	form = composition.form_state if isinstance(composition, subsequence.Composition) else None

	if form is None:
		played["declared"] = set()
	elif form._section_bars is not None:
		played["declared"] = set(form._section_bars)
	else:
		played["declared"] = {section.name for section in form._sequence or []}

	return played


@pytest.mark.parametrize("name", _names())
def test_an_example_plays (name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:

	with caplog.at_level(logging.WARNING), warnings.catch_warnings(record=True) as raised:
		warnings.simplefilter("always")
		played = _play(name, tmp_path, monkeypatch)

	logged = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]

	assert len(played["files"]) == 1, "the example never reached play() - did its __main__ block run?"
	assert played["notes"], "it played nothing"
	assert logged == []
	assert [str(warning.message) for warning in raised] == []


# Long enough for every example's form to come round on the seed below, and for iss.py to fetch
# eight more times.  Four bars reach neither (#3506).
THROUGH = 128


@pytest.mark.parametrize("name", _names())
def test_an_example_plays_through_its_form (name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:

	"""A guard: over 128 bars every section of the form is reached, every bar sounds, and nothing warns.

	The test above plays four bars, which reach no second section of any form, and not iss.py's
	second fetch, where its tempo starts to ramp and its harmony can change style (#3506).  The
	seed is fixed because the way through a form is a random walk, so a failure names a take that
	replays.  A bar with no note in it fails too: a part that dies out, as cellular_2d's did (#3498),
	is how a changed default most often shows.
	"""

	with caplog.at_level(logging.WARNING), warnings.catch_warnings(record=True) as raised:
		warnings.simplefilter("always")
		played = _play(name, tmp_path, monkeypatch, bars=THROUGH, seed=1)

	logged = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]

	assert logged == []
	assert [str(warning.message) for warning in raised] == []
	assert played["sections"] == played["declared"]
	assert played["bars"] == set(range(THROUGH)), f"silent bars: {sorted(set(range(THROUGH)) - played['bars'])}"


def test_iss_is_answered_from_every_point_of_the_orbit (tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:

	"""iss.py fetches every 16 bars, so 128 bars reach the stand-in's poles and its eclipse.

	If it stopped fetching, the orbit would be exercising nothing, and the test above could not say so.
	"""

	assert _play("iss.py", tmp_path, monkeypatch, bars=THROUGH, seed=1)["fetches"] == 1 + THROUGH // 16 >= len(_ORBIT)


def test_the_example_that_links_asks_to_and_joins_nothing (tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:

	"""link_sync.py calls link() once, and the replacement took it: no session was joined.

	If it stopped calling link(), the replacement would be hiding nothing, and should go.
	"""

	assert _play("link_sync.py", tmp_path, monkeypatch)["linked"] == 1


def test_the_live_file_is_played_through_the_example_that_loads_it (tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:

	"""live_patterns.py is not run alone: live_init.py loads it, and its patterns are what live_init.py plays."""

	assert "live_patterns.py" in (EXAMPLES / "live_init.py").read_text(encoding="utf-8")

	played = _play("live_init.py", tmp_path, monkeypatch)

	assert played["notes"]
