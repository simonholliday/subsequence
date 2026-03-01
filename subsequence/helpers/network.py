"""Network utility functions.

Provides robust local IP and broadcast address discovery without requiring
external dependencies like `psutil`.
"""

import socket
import typing


def get_local_ip () -> str:

	"""Discover the primary local IP address of the machine.

	Uses a non-connecting UDP socket trick to find the IP of the default
	outbound interface currently used for external routing.

	Returns:
		The local IP address as a string, or "127.0.0.1" if discovery fails.
	"""

	local_ip = "127.0.0.1"
	try:
		# Connecting a UDP socket to an external address (no data is actually
		# sent) reveals which local IP the OS would use for that route.
		probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			probe.connect(("8.8.8.8", 80))
			local_ip = probe.getsockname()[0]
		finally:
			probe.close()
	except Exception:
		pass

	return local_ip


def get_local_broadcasts () -> typing.List[str]:

	"""Return subnet broadcast addresses inferred from local interface IPs.

	Computes the /24 broadcast address based on the primary local IP route.

	Returns:
		A list containing the computed broadcast address, or an empty list
		if the primary interface is a loopback or link-local address.
	"""

	broadcasts: typing.List[str] = []
	local_ip = get_local_ip()

	if not local_ip.startswith("127.") and not local_ip.startswith("169.254."):
		parts = local_ip.split(".")
		if len(parts) == 4:
			parts[3] = "255"
			broadcasts.append(".".join(parts))

	return broadcasts
