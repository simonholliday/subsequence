import asyncio
import typing

import pytest
import pythonosc.dispatcher
import pythonosc.osc_server
import pythonosc.udp_client

import subsequence
import subsequence.osc


async def _wait_for(
    condition: typing.Callable[[], bool], deadline: float = 2.0, poll: float = 0.01
) -> None:
    """Poll until `condition()` is true or the deadline passes; avoids flat sleeps that flake under load."""

    loop = asyncio.get_running_loop()
    end = loop.time() + deadline

    while not condition():
        if loop.time() >= end:
            return

        await asyncio.sleep(poll)


@pytest.fixture
def composition(patch_midi: None) -> subsequence.Composition:
    """Create a composition for testing."""

    comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
    return comp


@pytest.mark.asyncio
async def test_osc_bpm_handler(composition: subsequence.Composition) -> None:
    """Sending /bpm should update composition tempo."""

    server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
    await server.start()

    # Get the actual port if 0 was used (OscServer needs to expose it or we check the transport)
    port = server._transport.get_extra_info("sockname")[1]

    # Send OSC message
    client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
    client.send_message("/bpm", 145)

    # Poll until the handler has run (UDP delivery is async).
    await _wait_for(lambda: composition.bpm == 145)

    assert composition.bpm == 145
    assert composition._sequencer.current_bpm == 145

    await server.stop()


@pytest.mark.asyncio
async def test_osc_mute_handler(composition: subsequence.Composition) -> None:
    """Sending /mute/<name> should mute the pattern."""

    def drums(p: "subsequence.pattern_builder.PatternBuilder") -> None:
        pass

    composition.pattern(channel=9)(drums)

    # Simulate _run's distribution of running patterns
    pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])
    composition._running_patterns["drums"] = pattern

    server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
    await server.start()
    port = server._transport.get_extra_info("sockname")[1]

    client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
    client.send_message("/mute/drums", [])

    await _wait_for(lambda: pattern._muted is True)

    assert pattern._muted is True

    client.send_message("/unmute/drums", [])
    await _wait_for(lambda: pattern._muted is False)
    assert pattern._muted is False

    await server.stop()


@pytest.mark.asyncio
async def test_osc_data_handler(composition: subsequence.Composition) -> None:
    """Sending /data/<key> should update composition.data."""

    server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
    await server.start()
    port = server._transport.get_extra_info("sockname")[1]

    client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
    client.send_message("/data/velocity", 0.75)

    await _wait_for(lambda: composition.data.get("velocity") == 0.75)

    assert composition.data["velocity"] == 0.75

    await server.stop()


@pytest.mark.asyncio
async def test_osc_status_broadcasting(composition: subsequence.Composition) -> None:
    """The composition should broadcast status via OSC on each bar."""

    # Setup a receiver server

    received_messages = []

    def handle_status(address: str, *args: typing.Any) -> None:
        received_messages.append((address, args))

    dispatcher = pythonosc.dispatcher.Dispatcher()
    dispatcher.map("/bar", handle_status)
    dispatcher.map("/bpm", handle_status)

    loop = asyncio.get_running_loop()
    recv_server = pythonosc.osc_server.AsyncIOOSCUDPServer(
        ("127.0.0.1", 0), dispatcher, loop
    )
    transport, _ = await recv_server.create_serve_endpoint()
    recv_port = transport.get_extra_info("sockname")[1]

    # Configure composition OSC to send to our receiver
    composition.osc(receive_port=0, send_port=recv_port)

    # We need to manually wire up the broadcast since we aren't calling
    # composition.play(); register the PRODUCTION method that _run() uses
    # so this test exercises real code, not a copy of it.
    await composition._osc_server.start()

    composition.on_event("bar", composition._broadcast_osc_status)

    # Emit bar event
    composition._sequencer.events.emit_sync("bar", 42)

    await _wait_for(lambda: {"/bar", "/bpm"} <= {m[0] for m in received_messages})

    # Check if we received anything
    addresses = [m[0] for m in received_messages]
    assert "/bar" in addresses
    assert "/bpm" in addresses

    # Find bar value
    bar_val = next(m[1][0] for m in received_messages if m[0] == "/bar")
    assert bar_val == 42

    await composition._osc_server.stop()
    transport.close()
