"""Tests for subsequence.helpers.wing — Behringer WING OSC helper.

These tests mock the socket layer and do NOT require a live WING device.
"""

import socket
import struct
import typing
import unittest.mock

import pytest

import subsequence.helpers.wing as wing


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_osc_response(address: str, type_tags: str, *values: typing.Any) -> bytes:
	"""Build a minimal OSC response packet for use in socket mocks.

	Constructs address + type tag string + values following the OSC 1.0 spec:
	all segments are null-terminated and zero-padded to 4-byte boundaries.
	"""
	def _pad(data: bytes) -> bytes:
		"""Null-terminate and pad to 4-byte boundary."""
		data = data + b"\x00"
		remainder = len(data) % 4
		if remainder:
			data = data + b"\x00" * (4 - remainder)
		return data

	blob = _pad(address.encode())
	blob += _pad(("," + type_tags).encode())

	for tag, value in zip(type_tags, values):
		if tag == "s":
			blob += _pad(value.encode())
		elif tag == "f":
			blob += struct.pack(">f", value)
		elif tag == "i":
			blob += struct.pack(">i", value)

	return blob


def _discovery_response_bytes (ip: str = "192.168.0.116") -> bytes:
	"""Build the bytes the WING sends in reply to a /? broadcast."""
	info = f"WING,{ip},WING-PP-20021049,wing-rack,0100A9P0604AAE,3.1-0-g9f314617:release"
	return _build_osc_response("/*", "s", info)


# ── discover() ────────────────────────────────────────────────────────────────


def test_discover_returns_device_info () -> None:

	"""discover() should parse the WING reply into a dict with ip/model/firmware."""

	response = _discovery_response_bytes("192.168.1.50")

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_sock)
		MockSocket.return_value.__exit__ = unittest.mock.MagicMock(return_value=False)
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.return_value = (response, ("192.168.1.50", 2223))

		result = wing.discover(timeout=1.0)

	assert result is not None
	assert result["ip"] == "192.168.1.50"
	assert result["device"] == "WING"
	assert result["model"] == "WING-PP-20021049"
	assert result["form_factor"] == "wing-rack"
	assert "3.1" in result["firmware"]


def test_discover_timeout_returns_none () -> None:

	"""discover() should return None when no device responds."""

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.side_effect = socket.timeout

		result = wing.discover(timeout=0.1)

	assert result is None


def test_discover_builds_correct_osc_address () -> None:

	"""discover() should send an OSC message with address '/?'."""

	import pythonosc.osc_message

	response = _discovery_response_bytes()
	sent_packets: typing.List[bytes] = []

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock

		def capture_sendto (data: bytes, addr: tuple) -> None:
			sent_packets.append(data)

		mock_sock.sendto.side_effect = capture_sendto
		mock_sock.recvfrom.return_value = (response, ("192.168.0.116", 2223))

		wing.discover(timeout=1.0)

	assert len(sent_packets) >= 1
	# The sent packet should be a valid OSC message with address "/?".
	msg = pythonosc.osc_message.OscMessage(sent_packets[0])
	assert msg.address == "/?"


# ── query() ───────────────────────────────────────────────────────────────────


def test_query_node_returns_children () -> None:

	"""query() on a node address should return type='node' with children list."""

	# Build a response like /ch/1 → ['in', 'flt', 'fdr', 'mute']
	response = _build_osc_response("/ch/1", "ssss", "in", "flt", "fdr", "mute")

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.return_value = (response, ("192.168.0.116", 2223))

		result = wing.query("192.168.0.116", "/ch/1")

	assert result is not None
	assert result["type"] == "node"
	assert result["children"] == ["in", "flt", "fdr", "mute"]
	assert result["address"] == "/ch/1"


def test_query_numeric_leaf_extracts_float_and_int () -> None:

	"""query() on a numeric leaf should return value_f (float) and value_i (int)."""

	# Build a response like /ch/1/fdr → ('0.0', 0.75, 0) — string + float + int
	response = _build_osc_response("/ch/1/fdr", "sfi", "0.0", 0.75, 0)

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.return_value = (response, ("192.168.0.116", 2223))

		result = wing.query("192.168.0.116", "/ch/1/fdr")

	assert result is not None
	assert result["type"] == "leaf"
	assert result["value"] == "0.0"
	assert result["value_f"] == pytest.approx(0.75, abs=0.01)
	assert result["address"] == "/ch/1/fdr"


def test_query_string_leaf () -> None:

	"""query() on a string-only leaf should return type='leaf' with value."""

	response = _build_osc_response("/ch/1/name", "s", "Kick")

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.return_value = (response, ("192.168.0.116", 2223))

		result = wing.query("192.168.0.116", "/ch/1/name")

	assert result is not None
	assert result["type"] == "leaf"
	assert result["value"] == "Kick"
	assert result["value_f"] is None
	assert result["value_i"] is None


def test_query_timeout_returns_none () -> None:

	"""query() should return None when the WING does not reply."""

	with unittest.mock.patch("socket.socket") as MockSocket:
		mock_sock = unittest.mock.MagicMock()
		MockSocket.return_value = mock_sock
		mock_sock.recvfrom.side_effect = socket.timeout

		result = wing.query("192.168.0.116", "/ch/1", timeout=0.1)

	assert result is None


# ── _classify() ───────────────────────────────────────────────────────────────


def test_classify_node_multiple_strings () -> None:
	assert wing._classify(["in", "flt", "fdr"]) == "node"


def test_classify_leaf_single_string () -> None:
	assert wing._classify(["Kick"]) == "leaf"


def test_classify_leaf_empty_string () -> None:
	assert wing._classify([""]) == "leaf"


def test_classify_leaf_has_float () -> None:
	assert wing._classify(["0.0", 0.75, 0]) == "leaf"


def test_classify_empty () -> None:
	assert wing._classify([]) == "leaf"
