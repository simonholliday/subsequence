"""Tests for the hotkey system.

Covers:
- HotkeyBinding dataclass construction
- _derive_label() for named functions, lambdas, and fallbacks
- Composition.hotkey() registration and validation
- Composition.form_jump() delegation
- FormState.jump_to() section transitions
- Composition._process_hotkeys() immediate and quantized execution
- Global enable/disable (hotkeys())
- Reserved '?' key protection
- KeystrokeListener platform detection (unsupported platform warning)
"""

import random
import typing
import pytest
import unittest.mock

import subsequence.composition as comp_mod
import subsequence.keystroke as keystroke_mod
from subsequence.composition import (
	HotkeyBinding,
	_PendingHotkeyAction,
	_derive_label,
	_HOTKEY_RESERVED,
	FormState,
	Composition,
)
from subsequence.keystroke import KeystrokeListener


# ---------------------------------------------------------------------------
# KeystrokeListener — platform detection
# ---------------------------------------------------------------------------

class TestKeystrokeListenerPlatform:

	def test_supported_flag_is_bool (self):
		assert isinstance(keystroke_mod.HOTKEYS_SUPPORTED, bool)

	def test_reason_is_none_when_supported (self):
		if keystroke_mod.HOTKEYS_SUPPORTED:
			assert keystroke_mod.HOTKEYS_UNAVAILABLE_REASON is None

	def test_reason_is_string_when_unsupported (self):
		if not keystroke_mod.HOTKEYS_SUPPORTED:
			assert isinstance(keystroke_mod.HOTKEYS_UNAVAILABLE_REASON, str)
			assert len(keystroke_mod.HOTKEYS_UNAVAILABLE_REASON) > 0

	def test_start_on_unsupported_platform_logs_warning_and_does_not_raise (self):
		"""Simulate an unsupported platform by patching HOTKEYS_SUPPORTED to False."""
		listener = KeystrokeListener()
		with unittest.mock.patch.object(keystroke_mod, "HOTKEYS_SUPPORTED", False):
			with unittest.mock.patch.object(
				keystroke_mod, "HOTKEYS_UNAVAILABLE_REASON", "Test: platform not supported"
			):
				# Should be a safe no-op — no exception, no thread started.
				listener.start()

		assert listener.active is False
		assert listener._thread is None

	def test_drain_returns_empty_when_never_started (self):
		listener = KeystrokeListener()
		assert listener.drain() == []

	def test_stop_safe_when_never_started (self):
		listener = KeystrokeListener()
		listener.stop()   # Should be a no-op.


# ---------------------------------------------------------------------------
# _derive_label
# ---------------------------------------------------------------------------

class TestDeriveLabel:

	def test_named_function (self):
		def jump_to_chorus ():
			pass
		assert _derive_label(jump_to_chorus) == "jump_to_chorus"

	def test_named_method (self):
		class Foo:
			def my_action (self):
				pass
		assert _derive_label(Foo().my_action) == "my_action"

	def test_lambda_fallback_no_source (self):
		"""Lambdas defined inline in test code cannot be inspected — fallback applies."""
		lam = lambda: None  # noqa: E731
		result = _derive_label(lam)
		# Either extracted body or fallback — must be a non-empty string.
		assert isinstance(result, str)
		assert len(result) > 0

	def test_unknown_callable_fallback (self):
		"""A callable with no __name__ and no source returns '<action>'."""
		class CallableObj:
			pass
		result = _derive_label(CallableObj())
		assert result == "<action>"


# ---------------------------------------------------------------------------
# HotkeyBinding
# ---------------------------------------------------------------------------

class TestHotkeyBinding:

	def test_fields (self):
		action = lambda: None  # noqa: E731
		binding = HotkeyBinding(key="a", action=action, quantize=0, label="do something")
		assert binding.key == "a"
		assert binding.action is action
		assert binding.quantize == 0
		assert binding.label == "do something"


# ---------------------------------------------------------------------------
# Composition.hotkeys() and Composition.hotkey()
# ---------------------------------------------------------------------------

class TestHotkeyRegistration:

	def _make_composition (self) -> Composition:
		# Avoid MIDI hardware init — we only test the hotkey logic.
		return Composition.__new__(Composition)

	def setup_method (self):

		# Manually initialise just the hotkey-related state.
		self.comp = self._make_composition()
		self.comp._hotkeys_enabled = False
		self.comp._hotkey_bindings = {}
		self.comp._pending_hotkey_actions = []
		self.comp._keystroke_listener = None
		self.comp._form_state = None

	def test_hotkeys_enables (self):
		self.comp.hotkeys()
		assert self.comp._hotkeys_enabled is True

	def test_hotkeys_disables (self):
		self.comp.hotkeys(enabled=False)
		assert self.comp._hotkeys_enabled is False

	def test_hotkey_registers (self):
		action = lambda: None  # noqa: E731
		self.comp.hotkey("a", action)
		assert "a" in self.comp._hotkey_bindings
		b = self.comp._hotkey_bindings["a"]
		assert b.key == "a"
		assert b.action is action
		assert b.quantize == 0

	def test_hotkey_overwrites_existing (self):
		a1 = lambda: None  # noqa: E731
		a2 = lambda: None  # noqa: E731
		self.comp.hotkey("a", a1)
		self.comp.hotkey("a", a2)
		assert self.comp._hotkey_bindings["a"].action is a2

	def test_hotkey_explicit_label (self):
		self.comp.hotkey("a", lambda: None, label="my label")  # noqa: E731
		assert self.comp._hotkey_bindings["a"].label == "my label"

	def test_hotkey_explicit_quantize (self):
		self.comp.hotkey("a", lambda: None, quantize=4)  # noqa: E731
		assert self.comp._hotkey_bindings["a"].quantize == 4

	def test_hotkey_rejects_reserved_key (self):
		with pytest.raises(ValueError, match="reserved"):
			self.comp.hotkey(_HOTKEY_RESERVED, lambda: None)  # noqa: E731

	def test_hotkey_rejects_multi_char_key (self):
		with pytest.raises(ValueError, match="single character"):
			self.comp.hotkey("ab", lambda: None)  # noqa: E731


# ---------------------------------------------------------------------------
# FormState.jump_to()
# ---------------------------------------------------------------------------

class TestFormStateJumpTo:

	def _make_graph_form (self) -> FormState:
		return FormState(
			sections = {
				"intro":   (4, [("verse", 1)]),
				"verse":   (8, [("chorus", 1), ("verse", 2)]),
				"chorus":  (8, [("verse", 1)]),
				"outro":   (4, None),
			},
			start = "intro",
		)

	def test_jump_changes_current_section (self):
		state = self._make_graph_form()
		assert state.get_section_info().name == "intro"
		state.jump_to("chorus")
		assert state.get_section_info().name == "chorus"

	def test_jump_resets_bar_in_section (self):
		state = self._make_graph_form()
		# Advance a few bars into 'intro'.
		state.advance()
		state.advance()
		state.jump_to("chorus")
		section = state.get_section_info()
		assert section.bar == 0

	def test_jump_increments_section_index (self):
		state = self._make_graph_form()
		original_index = state.get_section_info().index
		state.jump_to("verse")
		assert state.get_section_info().index == original_index + 1

	def test_jump_clears_finished_flag (self):
		"""Jumping to a non-terminal section after finishing should revive the form."""
		state = self._make_graph_form()
		# Force finish.
		state._finished = True
		state.jump_to("verse")
		assert not state._finished
		assert state.get_section_info() is not None

	def test_jump_unknown_section_raises (self):
		state = self._make_graph_form()
		with pytest.raises(ValueError, match="unknown_section"):
			state.jump_to("unknown_section")

	def test_jump_non_graph_mode_raises (self):
		state = FormState(sections=[("verse", 4), ("chorus", 4)])
		with pytest.raises(ValueError, match="graph mode"):
			state.jump_to("chorus")


# ---------------------------------------------------------------------------
# Composition.form_jump()
# ---------------------------------------------------------------------------

class TestFormJump:

	def setup_method (self):
		self.comp = Composition.__new__(Composition)
		self.comp._form_state = None
		self.comp._hotkey_bindings = {}
		self.comp._pending_hotkey_actions = []
		self.comp._keystroke_listener = None
		self.comp._hotkeys_enabled = False

	def test_form_jump_no_form_raises (self):
		with pytest.raises(ValueError, match="form"):
			self.comp.form_jump("chorus")

	def test_form_jump_delegates_to_form_state (self):
		mock_state = unittest.mock.MagicMock(spec=FormState)
		self.comp._form_state = mock_state
		self.comp.form_jump("chorus")
		mock_state.jump_to.assert_called_once_with("chorus")


# ---------------------------------------------------------------------------
# Composition._process_hotkeys()
# ---------------------------------------------------------------------------

class TestProcessHotkeys:

	def setup_method (self):
		self.comp = Composition.__new__(Composition)
		self.comp._hotkeys_enabled = True
		self.comp._hotkey_bindings = {}
		self.comp._pending_hotkey_actions = []
		self.comp._form_state = None

		# Replace the real keystroke listener with a controllable mock.
		self.mock_listener = unittest.mock.MagicMock()
		self.mock_listener.drain.return_value = []
		self.comp._keystroke_listener = self.mock_listener

	def _register (self, key: str, fn: typing.Callable, quantize: int = 0) -> None:
		self.comp._hotkey_bindings[key] = HotkeyBinding(
			key=key, action=fn, quantize=quantize, label=key
		)

	# --- immediate actions --------------------------------------------------

	def test_immediate_action_fires_on_bar (self):
		called = []
		self._register("a", lambda: called.append(True))
		self.mock_listener.drain.return_value = ["a"]
		self.comp._process_hotkeys(bar=1)
		assert called == [True]

	def test_unknown_key_is_ignored (self):
		self.mock_listener.drain.return_value = ["z"]
		# Should not raise.
		self.comp._process_hotkeys(bar=1)

	def test_action_exception_is_swallowed (self):
		def boom ():
			raise RuntimeError("oops")
		self._register("a", boom)
		self.mock_listener.drain.return_value = ["a"]
		# Should not propagate.
		self.comp._process_hotkeys(bar=1)

	# --- quantized actions --------------------------------------------------

	def test_quantized_action_is_deferred (self):
		called = []
		self._register("a", lambda: called.append(True), quantize=4)
		self.mock_listener.drain.return_value = ["a"]
		# Bar 1 is not divisible by 4 — should not fire yet.
		self.comp._process_hotkeys(bar=1)
		assert called == []
		assert len(self.comp._pending_hotkey_actions) == 1

	def test_quantized_action_fires_at_boundary (self):
		called = []
		self._register("a", lambda: called.append(True), quantize=4)

		# Enqueue manually at bar 1.
		self.comp._pending_hotkey_actions.append(
			_PendingHotkeyAction(
				binding=self.comp._hotkey_bindings["a"],
				requested_bar=1,
			)
		)

		# Bar 4 is divisible by 4 — should fire.
		self.comp._process_hotkeys(bar=4)
		assert called == [True]
		assert len(self.comp._pending_hotkey_actions) == 0

	def test_quantized_action_remains_pending_before_boundary (self):
		called = []
		self._register("a", lambda: called.append(True), quantize=4)
		self.comp._pending_hotkey_actions.append(
			_PendingHotkeyAction(
				binding=self.comp._hotkey_bindings["a"],
				requested_bar=1,
			)
		)
		# Bar 2 is not divisible by 4.
		self.comp._process_hotkeys(bar=2)
		assert called == []
		assert len(self.comp._pending_hotkey_actions) == 1

	# --- ? key --------------------------------------------------------------

	def test_question_mark_calls_list_hotkeys (self):
		self.mock_listener.drain.return_value = [_HOTKEY_RESERVED]
		self.comp._list_hotkeys = unittest.mock.MagicMock()
		self.comp._process_hotkeys(bar=1)
		self.comp._list_hotkeys.assert_called_once()

	# --- no listener --------------------------------------------------------

	def test_no_listener_returns_early (self):
		self.comp._keystroke_listener = None
		# Should be a no-op.
		self.comp._process_hotkeys(bar=1)
