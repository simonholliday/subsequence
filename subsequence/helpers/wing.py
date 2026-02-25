"""Behringer WING mixer helper.

NOTE: This module is specific to Behringer WING series mixers (WING, WING Rack,
WING Compact).  It is NOT part of the core Subsequence module and is provided
as a convenience for users who want to integrate WING discovery and address
exploration with their Subsequence compositions.

OSC port: The WING listens on UDP **port 2223** for all OSC traffic.

Typical workflow
----------------
::

    import subsequence
    import subsequence.helpers.wing as wing

    # 1. Find the mixer on the LAN
    device = wing.discover()
    if device is None:
        raise RuntimeError("No WING found on the network")

    ip = device["ip"]
    print(f"Found {device['model']} at {ip}  (firmware {device['firmware']})")

    # 2. Tell Subsequence to send OSC to it
    composition.osc(send_port=wing.WING_PORT, send_host=ip)

    # 3. In your patterns, use standard p.osc() / p.osc_ramp() with WING addresses
    @composition.pattern(channel=0, length=4)
    def mixer(p):
        p.osc_ramp("/ch/1/fdr", 0.0, 0.75, shape="ease_in")   # fade up channel 1

    # 4. Explore available addresses at development time
    wing.print_node(ip, "/ch/1")        # list all parameters under channel 1
    wing.print_node(ip, "/ch/1/fdr")    # inspect the fader leaf value

CLI usage
---------
::

    # Discover — prints the device info
    python -m subsequence.helpers.wing

    # Query a node — pretty-prints its structure / value
    python -m subsequence.helpers.wing /ch/1
    python -m subsequence.helpers.wing /ch/1/fdr
    python -m subsequence.helpers.wing /

Address conventions
-------------------
Addresses use the WING's internal node tree.  Key top-level nodes::

    /ch/1..40     Input channels
    /aux/1..8     Aux inputs
    /bus/1..16    Mix buses
    /main/lr      Main L/R bus
    /main/m       Mono / centre bus
    /mtx/1..8     Matrix outputs
    /fx/1..8      FX returns
    /dca/1..8     DCA groups
    /mgrp/1..8    Mute groups

Useful leaf addresses per channel (e.g. ``/ch/1/…``)::

    fdr           Fader level, 0.0 (−∞) .. 1.0 (≈+10 dB)
    pan           Pan, 0.0 (full L) .. 1.0 (full R), 0.5 = centre
    mute          Mute, 0 = unmuted, 1 = muted
    name          Channel name (string)
    col           Colour index (int)
"""

import socket
import sys
import typing

import pythonosc.osc_message
import pythonosc.osc_message_builder


WING_PORT: int = 2223
"""Default UDP port for the Behringer WING."""

_BROADCAST_ADDRS: typing.List[str] = ["255.255.255.255"]
"""Broadcast addresses tried by :func:`discover`.  Supplemented at runtime with
subnet-specific addresses derived from local interfaces."""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_osc(address: str) -> bytes:
	"""Build a no-argument OSC message for *address*."""
	return pythonosc.osc_message_builder.OscMessageBuilder(address=address).build().dgram


def _parse_osc(data: bytes) -> typing.Optional[pythonosc.osc_message.OscMessage]:
	"""Parse raw bytes into an OscMessage, returning None on failure."""
	try:
		return pythonosc.osc_message.OscMessage(data)
	except Exception:
		return None


def _local_broadcasts () -> typing.List[str]:
	"""Return subnet broadcast addresses inferred from local interface IPs.

	Uses a non-connecting UDP socket trick to find the IP of the default
	outbound interface, then computes its /24 broadcast address.
	"""
	broadcasts: typing.List[str] = []
	try:
		# Connecting a UDP socket to an external address (no data is actually
		# sent) reveals which local IP the OS would use for that route.
		probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			probe.connect(("8.8.8.8", 80))
			local_ip = probe.getsockname()[0]
		finally:
			probe.close()

		if not local_ip.startswith("127.") and not local_ip.startswith("169.254."):
			parts = local_ip.split(".")
			if len(parts) == 4:
				parts[3] = "255"
				broadcasts.append(".".join(parts))
	except Exception:
		pass
	return broadcasts


def _classify (params: typing.List[typing.Any]) -> str:
	"""Return 'node' or 'leaf' based on the response param types.

	- Any float or int in the params → numeric leaf.
	- All strings, more than one → node (directory listing of children).
	- Single string → string leaf.
	"""
	if not params:
		return "leaf"
	if any(isinstance(p, (float, int)) and not isinstance(p, bool) for p in params):
		return "leaf"
	if len(params) > 1:
		return "node"
	return "leaf"


# ── Public API ────────────────────────────────────────────────────────────────


def discover (
	port: int = WING_PORT,
	timeout: float = 2.0,
) -> typing.Optional[typing.Dict[str, str]]:
	"""Auto-discover a Behringer WING on the local network.

	Sends an OSC ``/?`` broadcast to UDP port *port* and waits for a reply.
	The WING responds with a comma-separated info string containing its IP,
	model, and firmware version.

	Parameters:
		port: UDP port to broadcast on (default 2223 — the WING's OSC port).
		timeout: Seconds to wait for a reply.

	Returns:
		A ``dict`` with keys ``ip``, ``device``, ``model``, ``form_factor``,
		``firmware``, or ``None`` if no device replied.

	Example::

		device = wing.discover()
		if device:
			print(device["ip"])        # "192.168.0.116"
			print(device["firmware"])  # "3.1-0-g9f314617:release"
	"""
	dgram = _build_osc("/?")

	# Build list of broadcast addresses to try: global first, then subnet-specific
	broadcasts = list(_BROADCAST_ADDRS) + _local_broadcasts()
	# Deduplicate while preserving order
	seen: typing.Set[str] = set()
	unique_broadcasts: typing.List[str] = []
	for b in broadcasts:
		if b not in seen:
			seen.add(b)
			unique_broadcasts.append(b)

	for broadcast in unique_broadcasts:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
			sock.settimeout(timeout / len(unique_broadcasts))
			sock.sendto(dgram, (broadcast, port))
			try:
				data, addr = sock.recvfrom(4096)
			except socket.timeout:
				continue
		finally:
			sock.close()

		msg = _parse_osc(data)
		if msg is None:
			continue

		params = list(msg.params)
		if not params or not isinstance(params[0], str):
			continue

		# Response: "WING,192.168.0.116,WING-PP-20021049,wing-rack,ID,firmware"
		fields = params[0].split(",")
		result: typing.Dict[str, str] = {
			"ip": addr[0],
			"device": fields[0] if len(fields) > 0 else "",
			"model": fields[2] if len(fields) > 2 else "",
			"form_factor": fields[3] if len(fields) > 3 else "",
			"firmware": fields[5] if len(fields) > 5 else "",
		}
		return result

	return None


def query (
	host: str,
	address: str,
	port: int = WING_PORT,
	timeout: float = 2.0,
) -> typing.Optional[typing.Dict[str, typing.Any]]:
	"""Query a node or leaf address on the WING and return a structured dict.

	Sends an argument-less OSC message to *address*.  The WING responds with
	either a list of child node names (for a node address) or the current value
	of a parameter (for a leaf address).

	Parameters:
		host: WING IP address (e.g. ``"192.168.0.116"``).
		address: OSC address to query (e.g. ``"/ch/1"`` or ``"/ch/1/fdr"``).
		port: UDP port (default 2223).
		timeout: Seconds to wait for a reply.

	Returns:
		A ``dict`` with keys:

		- ``address`` (str): The OSC address of the response.
		- ``type`` (str): ``"node"`` or ``"leaf"``.
		- For **nodes**: ``children`` (list[str]) — child node names.
		- For **string leaves**: ``value`` (str).
		- For **numeric leaves**: ``value`` (str), ``value_f`` (float|None),
		  ``value_i`` (int|None).

		Returns ``None`` on timeout.

	Example::

		result = wing.query(ip, "/ch/1/fdr")
		# {'address': '/ch/1/fdr', 'type': 'leaf', 'value': '0.0',
		#  'value_f': 0.75, 'value_i': 0}

		result = wing.query(ip, "/ch/1")
		# {'address': '/ch/1', 'type': 'node',
		#  'children': ['in', 'flt', 'clink', 'col', 'name', 'fdr', ...]}
	"""
	dgram = _build_osc(address)
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		sock.settimeout(timeout)
		sock.sendto(dgram, (host, port))
		try:
			data, _ = sock.recvfrom(65535)
		except socket.timeout:
			return None
	finally:
		sock.close()

	msg = _parse_osc(data)
	if msg is None:
		return None

	params = list(msg.params)
	kind = _classify(params)

	result: typing.Dict[str, typing.Any] = {
		"address": msg.address,
		"type": kind,
	}

	if kind == "node":
		result["children"] = [str(p) for p in params]
	else:
		# Leaf — extract typed values
		result["value"] = str(params[0]) if params else ""
		floats = [p for p in params if isinstance(p, float)]
		ints = [p for p in params if isinstance(p, int) and not isinstance(p, bool)]
		result["value_f"] = floats[0] if floats else None
		result["value_i"] = ints[0] if ints else None

	return result


def walk (
	host: str,
	address: str = "/",
	port: int = WING_PORT,
	timeout: float = 2.0,
	max_depth: int = 3,
	_depth: int = 0,
) -> typing.Optional[typing.Dict[str, typing.Any]]:
	"""Recursively walk the WING's node tree from *address*.

	Returns a nested dict representing the subtree.  Stops at *max_depth*
	levels to avoid issuing hundreds of queries against a large mixer tree.

	Parameters:
		host: WING IP address.
		address: Starting node address (default ``"/"`` — the root).
		port: UDP port (default 2223).
		timeout: Per-query timeout.
		max_depth: Maximum recursion depth (default 3).

	Returns:
		Nested ``dict`` — same structure as :func:`query` but with an extra
		``"children"`` key on nodes mapping child names to their own subtrees.
		``None`` on timeout.

	Example::

		tree = wing.walk(ip, "/ch/1", max_depth=1)
		for name, child in tree["children"].items():
		    print(name, child)
	"""
	result = query(host, address, port=port, timeout=timeout)
	if result is None:
		return None

	if result["type"] == "node" and _depth < max_depth:
		children_map: typing.Dict[str, typing.Any] = {}
		for child_name in result["children"]:
			child_address = address.rstrip("/") + "/" + child_name
			child_result = walk(
				host, child_address, port=port, timeout=timeout,
				max_depth=max_depth, _depth=_depth + 1
			)
			children_map[child_name] = child_result
		result["children"] = children_map

	return result


def print_node (
	host: str,
	address: str = "/",
	port: int = WING_PORT,
	timeout: float = 2.0,
) -> None:
	"""Query *address* and print a human-readable summary.

	For nodes: prints the list of children.
	For leaves: prints the current value(s).

	Parameters:
		host: WING IP address.
		address: OSC address to query (default ``"/"``).
		port: UDP port (default 2223).
		timeout: Seconds to wait for a reply.

	Example::

		wing.print_node("192.168.0.116", "/ch/1")
		wing.print_node("192.168.0.116", "/ch/1/fdr")
	"""
	result = query(host, address, port=port, timeout=timeout)

	if result is None:
		print(f"{address}  (no reply)")
		return

	if result["type"] == "node":
		children = result["children"]
		print(f"{address}  [{len(children)} children]")
		for child in children:
			print(f"  {child}")
	else:
		value_f = result.get("value_f")
		value_i = result.get("value_i")
		value_str = result.get("value", "")

		parts: typing.List[str] = [repr(value_str)]
		if value_f is not None:
			parts.append(f"float={value_f}")
		if value_i is not None:
			parts.append(f"int={value_i}")

		print(f"{address}  {',  '.join(parts)}")


# ── CLI entry point ───────────────────────────────────────────────────────────


def _main () -> None:
	"""Command-line interface.

	Usage::

		# Auto-discover WING on the LAN
		python -m subsequence.helpers.wing

		# Query a specific address (requires --host or auto-discovery)
		python -m subsequence.helpers.wing /ch/1
		python -m subsequence.helpers.wing /ch/1/fdr
		python -m subsequence.helpers.wing --host 192.168.0.116 /ch/1
	"""
	args = sys.argv[1:]

	host: typing.Optional[str] = None
	address: typing.Optional[str] = None

	i = 0
	while i < len(args):
		if args[i] == "--host" and i + 1 < len(args):
			host = args[i + 1]
			i += 2
		elif args[i].startswith("/"):
			address = args[i]
			i += 1
		else:
			i += 1

	# Discover if no host given
	if host is None:
		print("Discovering WING on local network...")
		device = discover()
		if device is None:
			print("No WING found.")
			return
		host = device["ip"]
		print(
			f"Found {device['device']} {device['model']} ({device['form_factor']})  "
			f"at {host}  firmware {device['firmware']}"
		)

	if address is not None:
		print_node(host, address)


if __name__ == "__main__":
	_main()
