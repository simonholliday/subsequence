import asyncio
import typing

import pytest

import subsequence
import subsequence.osc


@pytest.fixture
def composition (patch_midi: None) -> subsequence.Composition:

	"""Create a composition for testing."""

	comp = subsequence.Composition(output_device="Dummy MIDI", bpm=120, key="C")
	return comp


@pytest.mark.asyncio
async def test_osc_bpm_handler (composition: subsequence.Composition) -> None:

	"""Sending /bpm should update composition tempo."""

	server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
	await server.start()
	
	# Get the actual port if 0 was used (OscServer needs to expose it or we check the transport)
	port = server._transport.get_extra_info("sockname")[1]

	# Send OSC message
	import pythonosc.udp_client
	client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
	client.send_message("/bpm", 145)

	# Give it a tiny bit of time to process
	await asyncio.sleep(0.1)

	assert composition.bpm == 145
	assert composition._sequencer.current_bpm == 145

	await server.stop()


@pytest.mark.asyncio
async def test_osc_mute_handler (composition: subsequence.Composition) -> None:

	"""Sending /mute/<name> should mute the pattern."""

	def drums (p):
		pass

	composition.pattern(channel=9)(drums)
	
	# Simulate _run's distribution of running patterns
	pattern = composition._build_pattern_from_pending(composition._pending_patterns[0])
	composition._running_patterns["drums"] = pattern

	server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
	await server.start()
	port = server._transport.get_extra_info("sockname")[1]

	import pythonosc.udp_client
	client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
	client.send_message("/mute/drums", [])

	await asyncio.sleep(0.1)

	assert pattern._muted is True

	client.send_message("/unmute/drums", [])
	await asyncio.sleep(0.1)
	assert pattern._muted is False

	await server.stop()


@pytest.mark.asyncio
async def test_osc_data_handler (composition: subsequence.Composition) -> None:

	"""Sending /data/<key> should update composition.data."""

	server = subsequence.osc.OscServer(composition, receive_port=0, send_port=0)
	await server.start()
	port = server._transport.get_extra_info("sockname")[1]

	import pythonosc.udp_client
	client = pythonosc.udp_client.SimpleUDPClient("127.0.0.1", port)
	client.send_message("/data/velocity", 0.75)

	await asyncio.sleep(0.1)

	assert composition.data["velocity"] == 0.75

	await server.stop()


@pytest.mark.asyncio
async def test_osc_status_broadcasting (composition: subsequence.Composition) -> None:

	"""The composition should broadcast status via OSC on each bar."""

	# Setup a receiver server
	import pythonosc.dispatcher
	import pythonosc.osc_server
	
	received_messages = []
	
	def handle_status (address, *args):
		received_messages.append((address, args))

	dispatcher = pythonosc.dispatcher.Dispatcher()
	dispatcher.map("/bar", handle_status)
	dispatcher.map("/bpm", handle_status)

	loop = asyncio.get_running_loop()
	recv_server = pythonosc.osc_server.AsyncIOOSCUDPServer(("127.0.0.1", 0), dispatcher, loop)
	transport, _ = await recv_server.create_serve_endpoint()
	recv_port = transport.get_extra_info("sockname")[1]

	# Configure composition OSC to send to our receiver
	composition.osc(receive_port=0, send_port=recv_port)
	
	# We need to manually trigger the _send_osc_status callback 
	# since we aren't calling composition.play()
	await composition._osc_server.start()
	
	# In composition.py, the callback is local to _run. 
	# For testing we can simulate its logic or just use the setup that _run would do.
	
	# Let's manually register a callback that mimics _run's setup
	def _send_osc_status (bar: int) -> None:
		composition._osc_server.send("/bar", bar)
		composition._osc_server.send("/bpm", composition.bpm)

	composition.on_event("bar", _send_osc_status)
	
	# Emit bar event
	composition._sequencer.events.emit_sync("bar", 42)
	
	await asyncio.sleep(0.1)
	
	# Check if we received anything
	addresses = [m[0] for m in received_messages]
	assert "/bar" in addresses
	assert "/bpm" in addresses
	
	# Find bar value
	bar_val = next(m[1][0] for m in received_messages if m[0] == "/bar")
	assert bar_val == 42

	await composition._osc_server.stop()
	transport.close()
